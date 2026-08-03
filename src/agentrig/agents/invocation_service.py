"""Worker 任务的角色校验、幂等提交和终态约束。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from ..assistant.repository import AssistantRepository
from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from ..runs.redactor import Redactor
from .invocation_models import AgentInvocationStatus, AgentRole
from .invocation_repository import AgentInvocationRepository
from .invocation_schemas import (
    AgentInvocationCreate,
    AgentInvocationFailure,
    AgentInvocationPage,
    AgentInvocationView,
    AgentResultSubmit,
)
from .ports import AgentTaskContext


class AgentInvocationService:
    def __init__(
        self,
        repository: AgentInvocationRepository,
        *,
        assistant_repository: AssistantRepository | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self._repository = repository
        self._assistant_repository = assistant_repository
        self._redactor = redactor or Redactor()

    async def create_or_get(
        self,
        value: AgentInvocationCreate,
    ) -> AgentInvocationView:
        existing = await self._repository.get_by_idempotency_key(
            value.role,
            value.idempotency_key,
        )
        if existing is not None:
            return existing
        context = await self._enrich(value.context)
        matrix_room_id = value.matrix_room_id
        if (
            matrix_room_id is None
            and context.session_id is not None
            and self._assistant_repository is not None
        ):
            session = await self._assistant_repository.get_session(context.session_id)
            matrix_room_id = session.matrix_room_id if session is not None else None
        value = value.model_copy(
            update={
                "context": context,
                "matrix_room_id": matrix_room_id,
                "input_snapshot": self._redactor.redact(value.input_snapshot),
            }
        )
        input_hash = self.payload_hash(value.input_snapshot)
        return await self._repository.create(
            new_id("agentinv"),
            value,
            input_hash=input_hash,
        )

    async def get(self, invocation_id: str) -> AgentInvocationView:
        invocation = await self._repository.get(invocation_id)
        if invocation is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"agent invocation not found: {invocation_id}",
                details={"invocation_id": invocation_id},
            )
        return invocation

    async def list_for_session(
        self,
        session_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> AgentInvocationPage:
        return await self._repository.list_for_session(
            session_id,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def list_all(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> AgentInvocationPage:
        return await self._repository.list_all(
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def mark_dispatched(
        self,
        invocation_id: str,
        *,
        matrix_room_id: str,
        request_event_id: str,
        assigned_agent: str,
    ) -> AgentInvocationView:
        invocation = await self.get(invocation_id)
        if invocation.status is AgentInvocationStatus.COMPLETED:
            return invocation
        if invocation.status not in {
            AgentInvocationStatus.CREATED,
            AgentInvocationStatus.DISPATCHED,
        }:
            self._raise_conflict(invocation)
        return await self._repository.set_status(
            invocation_id,
            AgentInvocationStatus.DISPATCHED,
            matrix_room_id=matrix_room_id,
            request_event_id=request_event_id,
            assigned_agent=assigned_agent,
        )

    async def claim(
        self,
        invocation_id: str,
        *,
        role: AgentRole,
        assigned_agent: str,
    ) -> AgentInvocationView:
        invocation = await self._for_role(invocation_id, role)
        if invocation.status is AgentInvocationStatus.RUNNING:
            return invocation
        if invocation.status is not AgentInvocationStatus.DISPATCHED:
            raise AgentRigError(
                ErrorCode.AGENT_INVOCATION_NOT_READY,
                "agent invocation is not ready to claim",
                details={"status": invocation.status.value},
            )
        return await self._repository.set_status(
            invocation_id,
            AgentInvocationStatus.RUNNING,
            assigned_agent=assigned_agent,
        )

    async def submit_result(
        self,
        invocation_id: str,
        value: AgentResultSubmit,
        *,
        role: AgentRole,
    ) -> AgentInvocationView:
        invocation = await self._for_role(invocation_id, role)
        if value.idempotency_key != invocation.idempotency_key:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "agent result idempotency key does not match the task",
            )
        result_hash = self.payload_hash(value.result)
        if invocation.status is AgentInvocationStatus.COMPLETED:
            if invocation.result_hash == result_hash:
                return invocation
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "agent invocation already has a different result",
            )
        if invocation.status not in {
            AgentInvocationStatus.DISPATCHED,
            AgentInvocationStatus.RUNNING,
        }:
            self._raise_conflict(invocation)
        return await self._repository.set_status(
            invocation_id,
            AgentInvocationStatus.COMPLETED,
            result_payload=value.result,
            result_hash=result_hash,
            response_event_id=value.response_event_id,
        )

    async def fail(
        self,
        invocation_id: str,
        value: AgentInvocationFailure,
        *,
        role: AgentRole,
    ) -> AgentInvocationView:
        invocation = await self._for_role(invocation_id, role)
        if invocation.status.terminal:
            return invocation
        return await self._repository.set_status(
            invocation_id,
            AgentInvocationStatus.FAILED,
            response_event_id=value.response_event_id,
            error_code=value.error_code,
            error_message=value.error_message,
            retryable=value.retryable,
        )

    async def mark_timed_out(self, invocation_id: str) -> AgentInvocationView:
        invocation = await self.get(invocation_id)
        if invocation.status.terminal:
            return invocation
        return await self._repository.set_status(
            invocation_id,
            AgentInvocationStatus.TIMED_OUT,
            error_code=ErrorCode.AGENT_INVOCATION_TIMED_OUT.value,
            error_message="agent invocation exceeded its component deadline",
            retryable=True,
        )

    async def attach_result_ref(
        self,
        invocation_id: str,
        result_ref: str,
    ) -> AgentInvocationView:
        invocation = await self.get(invocation_id)
        if invocation.status is not AgentInvocationStatus.COMPLETED:
            self._raise_conflict(invocation)
        return await self._repository.attach_result_ref(invocation_id, result_ref)

    async def attach_response_event(
        self,
        invocation_id: str,
        response_event_id: str,
        *,
        role: AgentRole,
    ) -> AgentInvocationView:
        """Attach the stable Matrix receipt emitted after a Worker finishes."""
        invocation = await self._for_role(invocation_id, role)
        if not invocation.status.terminal:
            self._raise_conflict(invocation)
        if invocation.response_event_id is not None:
            if invocation.response_event_id == response_event_id:
                return invocation
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "agent invocation already has a different response event",
            )
        return await self._repository.attach_response_event(
            invocation_id,
            response_event_id,
        )

    async def cancel_in_progress(self) -> None:
        await self._repository.cancel_non_terminal()

    async def _for_role(
        self,
        invocation_id: str,
        role: AgentRole,
    ) -> AgentInvocationView:
        invocation = await self.get(invocation_id)
        if invocation.agent_role is not role:
            raise AgentRigError(
                ErrorCode.AGENT_ROLE_FORBIDDEN,
                f"{role.value} cannot access a {invocation.agent_role.value} task",
                details={"invocation_id": invocation_id},
            )
        return invocation

    async def _enrich(self, context: AgentTaskContext) -> AgentTaskContext:
        if self._assistant_repository is None or context.plan_id is not None:
            return context
        plan = await self._assistant_repository.get_plan_by_run_id(context.run_id)
        if plan is None:
            return context
        return context.model_copy(
            update={
                "plan_id": plan.id,
                "session_id": plan.session_id,
            }
        )

    @staticmethod
    def payload_hash(value: dict[str, Any]) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def deadline_expired(deadline: datetime) -> bool:
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= deadline

    @staticmethod
    def _raise_conflict(invocation: AgentInvocationView) -> None:
        raise AgentRigError(
            ErrorCode.CONFLICT,
            f"agent invocation is already {invocation.status.value}",
            details={"invocation_id": invocation.id, "status": invocation.status.value},
        )
