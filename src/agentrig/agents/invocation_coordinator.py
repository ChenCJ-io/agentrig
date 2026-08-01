"""将同步专业 Agent 端口映射为可审计的外部 Worker 任务。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from ..errors import AgentRigError, ErrorCode
from .invocation_models import AgentInvocationStatus, AgentRole
from .invocation_schemas import (
    AgentInvocationCreate,
    AgentInvocationFailure,
    AgentInvocationView,
    AgentTaskEnvelope,
)
from .invocation_service import AgentInvocationService


@dataclass(frozen=True)
class AgentTaskDispatch:
    matrix_room_id: str
    request_event_id: str
    assigned_agent: str


class AgentTaskTransport(Protocol):
    async def dispatch(
        self,
        invocation: AgentInvocationView,
        envelope: AgentTaskEnvelope,
    ) -> AgentTaskDispatch: ...


class UnavailableAgentTaskTransport:
    def __init__(self, reason: str) -> None:
        self._reason = reason

    async def dispatch(
        self,
        invocation: AgentInvocationView,
        envelope: AgentTaskEnvelope,
    ) -> AgentTaskDispatch:
        del invocation, envelope
        raise AgentRigError(ErrorCode.AGENTTEAMS_UNAVAILABLE, self._reason)


class AgentInvocationCoordinator:
    def __init__(
        self,
        service: AgentInvocationService,
        transport: AgentTaskTransport,
        *,
        poll_interval_seconds: float = 0.2,
    ) -> None:
        self._service = service
        self._transport = transport
        self._poll_interval_seconds = poll_interval_seconds

    async def execute(self, value: AgentInvocationCreate) -> AgentInvocationView:
        invocation = await self._service.create_or_get(value)
        if invocation.status is AgentInvocationStatus.COMPLETED:
            return invocation
        if invocation.status is AgentInvocationStatus.CREATED:
            envelope = AgentTaskEnvelope(
                task_id=invocation.id,
                role=invocation.agent_role,
                target_role=f"agentteams_{invocation.agent_role.value}",
                case_run_id=invocation.case_run_id,
                run_id=invocation.run_id,
                input_ref=f"agentrig://agent-invocations/{invocation.id}",
                deadline=invocation.deadline,
                attempt=invocation.attempt,
                input_hash=invocation.input_hash,
                callback_tool=(
                    "submit_curator_result"
                    if invocation.agent_role is AgentRole.SIMULATION_CURATOR
                    else "submit_judge_result"
                ),
            )
            try:
                dispatch = await self._transport.dispatch(invocation, envelope)
            except Exception as exc:
                await self._service.fail(
                    invocation.id,
                    AgentInvocationFailure(
                        error_code=ErrorCode.AGENTTEAMS_UNAVAILABLE.value,
                        error_message=str(exc),
                        retryable=True,
                    ),
                    role=invocation.agent_role,
                )
                raise AgentRigError(
                    ErrorCode.AGENTTEAMS_UNAVAILABLE,
                    f"failed to dispatch {invocation.agent_role.value}: {exc}",
                    retryable=True,
                ) from exc
            invocation = await self._service.mark_dispatched(
                invocation.id,
                matrix_room_id=dispatch.matrix_room_id,
                request_event_id=dispatch.request_event_id,
                assigned_agent=dispatch.assigned_agent,
            )
        while not invocation.status.terminal:
            if self._service.deadline_expired(invocation.deadline):
                invocation = await self._service.mark_timed_out(invocation.id)
                break
            now = datetime.now(timezone.utc)
            deadline = invocation.deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            remaining = max(0.0, (deadline - now).total_seconds())
            await asyncio.sleep(min(self._poll_interval_seconds, remaining))
            invocation = await self._service.get(invocation.id)
        if invocation.status is not AgentInvocationStatus.COMPLETED:
            code = (
                ErrorCode.AGENT_INVOCATION_TIMED_OUT
                if invocation.status is AgentInvocationStatus.TIMED_OUT
                else ErrorCode.AGENTTEAMS_UNAVAILABLE
            )
            raise AgentRigError(
                code,
                invocation.error_message
                or f"agent invocation ended as {invocation.status.value}",
                details={"invocation_id": invocation.id},
                retryable=invocation.retryable,
            )
        return invocation
