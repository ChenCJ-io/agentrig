"""AssistantSession/Event/Turn 的应用服务。"""

from __future__ import annotations

import asyncio
from typing import Any

from ..errors import AgentRigError, ErrorCode
from ..identifiers import new_id
from .models import (
    ActorType,
    AssistantEventType,
    AssistantSessionStatus,
    AssistantTurnStatus,
    DeliveryStatus,
)
from .repository import AssistantRepository
from .schemas import (
    AssistantEventPage,
    AssistantEventView,
    AssistantMessageCreate,
    AssistantMessageReceipt,
    AssistantSessionCreate,
    AssistantSessionPage,
    AssistantSessionView,
    AssistantTurnView,
)


class AssistantService:
    def __init__(self, repository: AssistantRepository) -> None:
        self._repository = repository
        # Keep the lock pool bounded while serializing message admission per
        # session. The repository's client_message_id constraint still provides
        # idempotency; this guard prevents two different user turns from racing.
        self._message_locks = [asyncio.Lock() for _ in range(64)]

    async def create_session(
        self,
        value: AssistantSessionCreate,
        *,
        created_by: str,
    ) -> AssistantSessionView:
        return await self._repository.create_session(
            new_id("asst"),
            value,
            created_by=created_by,
        )

    async def get_session(self, session_id: str) -> AssistantSessionView:
        session = await self._repository.get_session(session_id)
        if session is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"assistant session not found: {session_id}",
                details={"session_id": session_id},
            )
        return session

    async def list_sessions(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> AssistantSessionPage:
        return await self._repository.list_sessions(
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def archive_session(self, session_id: str) -> AssistantSessionView:
        await self.get_session(session_id)
        session = await self._repository.archive_session(session_id)
        assert session is not None
        return session

    async def set_matrix_room(
        self,
        session_id: str,
        matrix_room_id: str,
    ) -> AssistantSessionView:
        session = await self.get_session(session_id)
        self._ensure_active(session)
        return await self._repository.set_matrix_room(session_id, matrix_room_id)

    async def send_message(
        self,
        session_id: str,
        value: AssistantMessageCreate,
        *,
        actor_id: str,
    ) -> AssistantMessageReceipt:
        lock = self._message_locks[hash(session_id) % len(self._message_locks)]
        async with lock:
            session = await self.get_session(session_id)
            self._ensure_active(session)
            if value.active_plan_id is not None and value.active_plan_id != session.active_plan_id:
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "active plan changed before the message was accepted",
                    details={
                        "expected": value.active_plan_id,
                        "actual": session.active_plan_id,
                    },
                )
            open_turn = await self._repository.get_latest_open_turn(session_id)
            if open_turn is not None:
                trigger = await self.get_event(open_turn.trigger_event_id)
                if (
                    trigger.client_message_id == value.client_message_id
                    and trigger.actor_id == actor_id
                ):
                    return AssistantMessageReceipt(
                        event_id=trigger.id,
                        turn_id=open_turn.id,
                        delivery_status=trigger.delivery_status,
                    )
                raise AgentRigError(
                    ErrorCode.ASSISTANT_TURN_CONFLICT,
                    "Manager is still processing the previous turn",
                    retryable=True,
                    details={
                        "turn_id": open_turn.id,
                        "status": open_turn.status.value,
                    },
                )
            event, turn = await self._repository.create_user_message(
                event_id=new_id("asstevt"),
                turn_id=new_id("asstturn"),
                session_id=session_id,
                client_message_id=value.client_message_id,
                actor_id=actor_id,
                content=value.content,
                active_plan_id=value.active_plan_id,
                plan_action=(
                    value.plan_action.model_dump(mode="json")
                    if value.plan_action is not None
                    else None
                ),
            )
        return AssistantMessageReceipt(
            event_id=event.id,
            turn_id=turn.id,
            delivery_status=event.delivery_status,
        )

    async def list_events(
        self,
        session_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> AssistantEventPage:
        await self.get_session(session_id)
        return await self._repository.list_events(
            session_id,
            after_seq=max(0, after_seq),
            limit=max(1, min(limit, 500)),
        )

    async def get_context(self, session_id: str) -> dict[str, Any]:
        """供 Manager 恢复上下文的紧凑投影，不复制大体积 RunEvent。"""

        session = await self.get_session(session_id)
        events = await self._repository.list_events(
            session_id,
            after_seq=max(0, session.last_event_seq - 20),
            limit=20,
        )
        plan = (
            await self._repository.get_plan(session.active_plan_id)
            if session.active_plan_id is not None
            else None
        )
        return {
            "session": session.model_dump(mode="json"),
            "active_plan": plan.model_dump(mode="json") if plan is not None else None,
            "recent_events": [item.model_dump(mode="json") for item in events.items],
        }

    async def get_event(self, event_id: str) -> AssistantEventView:
        event = await self._repository.get_event(event_id)
        if event is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"assistant event not found: {event_id}",
                details={"event_id": event_id},
            )
        return event

    async def get_turn(self, turn_id: str) -> AssistantTurnView:
        turn = await self._repository.get_turn(turn_id)
        if turn is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"assistant turn not found: {turn_id}",
                details={"turn_id": turn_id},
            )
        return turn

    async def cancel_turn(self, turn_id: str) -> AssistantTurnView:
        turn = await self.get_turn(turn_id)
        if turn.status in {
            AssistantTurnStatus.COMPLETED,
            AssistantTurnStatus.FAILED,
            AssistantTurnStatus.CANCELLED,
        }:
            if turn.status is AssistantTurnStatus.CANCELLED:
                return turn
            raise AgentRigError(
                ErrorCode.ASSISTANT_TURN_CONFLICT,
                f"cannot cancel a {turn.status.value} turn",
                details={"turn_id": turn_id, "status": turn.status.value},
            )
        updated = await self._repository.set_turn_status(
            turn_id,
            AssistantTurnStatus.CANCELLED,
        )
        assert updated is not None
        return updated

    async def set_turn_status(
        self,
        turn_id: str,
        status: AssistantTurnStatus,
        **values: Any,
    ) -> AssistantTurnView:
        await self.get_turn(turn_id)
        updated = await self._repository.set_turn_status(turn_id, status, **values)
        assert updated is not None
        return updated

    async def set_event_delivery(
        self,
        event_id: str,
        status: DeliveryStatus,
        *,
        last_error: str | None = None,
    ) -> AssistantEventView:
        await self.get_event(event_id)
        updated = await self._repository.mark_event_delivery(
            event_id,
            status,
            last_error=last_error,
        )
        assert updated is not None
        return updated

    async def create_system_turn(
        self,
        session_id: str,
        *,
        event_type: AssistantEventType,
        payload: dict[str, Any],
        plan_id: str | None = None,
        run_id: str | None = None,
    ) -> tuple[AssistantEventView, AssistantTurnView]:
        await self.get_session(session_id)
        turn_id = new_id("asstturn")
        return await self._repository.create_system_turn(
            event_id=new_id("asstevt"),
            turn_id=turn_id,
            session_id=session_id,
            event_type=event_type.value,
            payload=payload,
            plan_id=plan_id,
            run_id=run_id,
        )

    async def append_event(
        self,
        session_id: str,
        event_type: AssistantEventType,
        *,
        actor_type: ActorType,
        actor_id: str,
        payload: dict[str, Any],
        turn_id: str | None = None,
        plan_id: str | None = None,
        run_id: str | None = None,
        case_run_id: str | None = None,
        invocation_id: str | None = None,
        decision_id: str | None = None,
        matrix_event_id: str | None = None,
        delivery_status: DeliveryStatus = DeliveryStatus.LOCAL,
    ) -> AssistantEventView:
        await self.get_session(session_id)
        return await self._repository.append_event(
            event_id=new_id("asstevt"),
            session_id=session_id,
            event_type=event_type.value,
            actor_type=actor_type.value,
            actor_id=actor_id,
            payload=payload,
            turn_id=turn_id,
            plan_id=plan_id,
            run_id=run_id,
            case_run_id=case_run_id,
            invocation_id=invocation_id,
            decision_id=decision_id,
            matrix_event_id=matrix_event_id,
            delivery_status=delivery_status,
        )

    @staticmethod
    def _ensure_active(session: AssistantSessionView) -> None:
        if session.status is not AssistantSessionStatus.ACTIVE:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "assistant session is archived",
                details={"session_id": session.id},
            )
