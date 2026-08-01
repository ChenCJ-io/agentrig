"""V2 助手与 EvaluationPlan 的持久化端口。"""

from __future__ import annotations

from typing import Any, Protocol

from .models import AssistantTurnStatus, DeliveryStatus
from .schemas import (
    AssistantEventPage,
    AssistantEventView,
    AssistantSessionCreate,
    AssistantSessionPage,
    AssistantSessionView,
    AssistantTurnView,
    EvaluationPlanCreate,
    EvaluationPlanPatch,
    EvaluationPlanView,
)


class AssistantRepository(Protocol):
    async def create_session(
        self,
        session_id: str,
        value: AssistantSessionCreate,
        *,
        created_by: str,
    ) -> AssistantSessionView: ...

    async def get_session(self, session_id: str) -> AssistantSessionView | None: ...

    async def get_session_by_matrix_room(
        self,
        matrix_room_id: str,
    ) -> AssistantSessionView | None: ...

    async def list_sessions(
        self,
        *,
        limit: int,
        offset: int,
    ) -> AssistantSessionPage: ...

    async def archive_session(self, session_id: str) -> AssistantSessionView | None: ...

    async def set_matrix_room(
        self,
        session_id: str,
        matrix_room_id: str,
    ) -> AssistantSessionView: ...

    async def create_user_message(
        self,
        *,
        event_id: str,
        turn_id: str,
        session_id: str,
        client_message_id: str,
        actor_id: str,
        content: str,
        active_plan_id: str | None,
    ) -> tuple[AssistantEventView, AssistantTurnView]: ...

    async def create_system_turn(
        self,
        *,
        event_id: str,
        turn_id: str,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        plan_id: str | None,
        run_id: str | None,
    ) -> tuple[AssistantEventView, AssistantTurnView]: ...

    async def get_event(self, event_id: str) -> AssistantEventView | None: ...

    async def get_event_by_matrix_id(
        self,
        matrix_event_id: str,
    ) -> AssistantEventView | None: ...

    async def get_linked_event(
        self,
        session_id: str,
        *,
        event_type: str,
        run_id: str,
    ) -> AssistantEventView | None: ...

    async def list_events(
        self,
        session_id: str,
        *,
        after_seq: int,
        limit: int,
    ) -> AssistantEventPage: ...

    async def append_event(
        self,
        *,
        event_id: str,
        session_id: str,
        event_type: str,
        actor_type: str,
        actor_id: str,
        payload: dict[str, Any],
        turn_id: str | None = None,
        plan_id: str | None = None,
        run_id: str | None = None,
        case_run_id: str | None = None,
        invocation_id: str | None = None,
        matrix_event_id: str | None = None,
        delivery_status: DeliveryStatus = DeliveryStatus.LOCAL,
    ) -> AssistantEventView: ...

    async def get_turn(self, turn_id: str) -> AssistantTurnView | None: ...

    async def get_latest_open_turn(
        self,
        session_id: str,
    ) -> AssistantTurnView | None: ...

    async def create_turn(
        self,
        *,
        turn_id: str,
        session_id: str,
        trigger_event_id: str,
    ) -> AssistantTurnView: ...

    async def set_turn_status(
        self,
        turn_id: str,
        status: AssistantTurnStatus,
        **values: Any,
    ) -> AssistantTurnView | None: ...

    async def mark_event_delivery(
        self,
        event_id: str,
        status: DeliveryStatus,
        *,
        matrix_event_id: str | None = None,
        last_error: str | None = None,
    ) -> AssistantEventView | None: ...

    async def create_plan(
        self,
        plan_id: str,
        value: EvaluationPlanCreate,
    ) -> EvaluationPlanView: ...

    async def get_plan(self, plan_id: str) -> EvaluationPlanView | None: ...

    async def get_plan_by_run_id(self, run_id: str) -> EvaluationPlanView | None: ...

    async def update_draft_plan(
        self,
        plan_id: str,
        value: EvaluationPlanPatch,
    ) -> EvaluationPlanView | None: ...

    async def save_plan_preview(
        self,
        plan_id: str,
        *,
        preview: dict[str, Any],
        selection_hash: str,
        confirmation: dict[str, Any],
    ) -> EvaluationPlanView: ...

    async def confirm_plan(
        self,
        plan_id: str,
        *,
        confirmation_event_id: str,
        confirmed_by: str,
    ) -> EvaluationPlanView: ...

    async def cancel_plan(self, plan_id: str) -> EvaluationPlanView: ...

    async def mark_plan_submitted(
        self,
        plan_id: str,
        *,
        idempotency_key: str,
        run_id: str,
    ) -> EvaluationPlanView: ...

    async def save_plan_error(
        self,
        plan_id: str,
        error: dict[str, Any],
    ) -> EvaluationPlanView: ...

    async def get_integration_cursor(self, integration: str) -> str | None: ...

    async def save_integration_cursor(
        self,
        integration: str,
        cursor: str,
        metadata: dict[str, Any],
    ) -> None: ...
