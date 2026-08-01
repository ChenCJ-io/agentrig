"""AgentInvocation 持久化端口。"""

from __future__ import annotations

from typing import Protocol

from .invocation_models import AgentInvocationStatus, AgentRole
from .invocation_schemas import (
    AgentInvocationCreate,
    AgentInvocationPage,
    AgentInvocationView,
)


class AgentInvocationRepository(Protocol):
    async def create(
        self,
        invocation_id: str,
        value: AgentInvocationCreate,
        *,
        input_hash: str,
    ) -> AgentInvocationView: ...

    async def get(self, invocation_id: str) -> AgentInvocationView | None: ...

    async def get_by_idempotency_key(
        self,
        role: AgentRole,
        idempotency_key: str,
    ) -> AgentInvocationView | None: ...

    async def list_for_session(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
    ) -> AgentInvocationPage: ...

    async def set_status(
        self,
        invocation_id: str,
        status: AgentInvocationStatus,
        *,
        assigned_agent: str | None = None,
        matrix_room_id: str | None = None,
        request_event_id: str | None = None,
        response_event_id: str | None = None,
        result_payload: dict[str, object] | None = None,
        result_hash: str | None = None,
        result_ref: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        retryable: bool = False,
    ) -> AgentInvocationView: ...

    async def attach_result_ref(
        self,
        invocation_id: str,
        result_ref: str,
    ) -> AgentInvocationView: ...

    async def attach_response_event(
        self,
        invocation_id: str,
        response_event_id: str,
    ) -> AgentInvocationView: ...

    async def cancel_non_terminal(self) -> None: ...
