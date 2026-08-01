"""V2 助手事件、回合与 EvaluationPlan 的 SQLAlchemy 实现。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update

from ....assistant.models import (
    ActorType,
    AssistantEventType,
    AssistantSessionStatus,
    AssistantTurnStatus,
    DeliveryStatus,
    EvaluationPlanStatus,
)
from ....assistant.schemas import (
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
from ..orm import (
    AssistantEventORM,
    AssistantSessionORM,
    AssistantTurnORM,
    EvaluationPlanORM,
    IntegrationCursorORM,
    utc_now,
)
from ..session import Database


class SqlAssistantRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_session(
        self,
        session_id: str,
        value: AssistantSessionCreate,
        *,
        created_by: str,
    ) -> AssistantSessionView:
        row = AssistantSessionORM(
            id=session_id,
            workspace_id=value.workspace_id,
            title=value.title,
            status=AssistantSessionStatus.ACTIVE.value,
            created_by=created_by,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._session_view(row)

    async def get_session(self, session_id: str) -> AssistantSessionView | None:
        async with self._database.session() as session:
            row = await session.get(AssistantSessionORM, session_id)
        return self._session_view(row) if row is not None else None

    async def get_session_by_matrix_room(
        self,
        matrix_room_id: str,
    ) -> AssistantSessionView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(AssistantSessionORM).where(
                    AssistantSessionORM.matrix_room_id == matrix_room_id
                )
            )
        return self._session_view(row) if row is not None else None

    async def list_sessions(
        self,
        *,
        limit: int,
        offset: int,
    ) -> AssistantSessionPage:
        async with self._database.session() as session:
            total = int(await session.scalar(select(func.count(AssistantSessionORM.id))) or 0)
            rows = list(
                await session.scalars(
                    select(AssistantSessionORM)
                    .order_by(
                        AssistantSessionORM.updated_at.desc(),
                        AssistantSessionORM.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
        return AssistantSessionPage(
            items=[self._session_view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def archive_session(self, session_id: str) -> AssistantSessionView | None:
        async with self._database.session() as session:
            row = await session.get(AssistantSessionORM, session_id)
            if row is None:
                return None
            row.status = AssistantSessionStatus.ARCHIVED.value
            row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
        return self._session_view(row)

    async def set_matrix_room(
        self,
        session_id: str,
        matrix_room_id: str,
    ) -> AssistantSessionView:
        async with self._database.session() as session:
            row = await session.get(AssistantSessionORM, session_id)
            assert row is not None
            row.matrix_room_id = matrix_room_id
            row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
        return self._session_view(row)

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
    ) -> tuple[AssistantEventView, AssistantTurnView]:
        async with self._database.session() as session:
            existing = await session.scalar(
                select(AssistantEventORM).where(
                    AssistantEventORM.session_id == session_id,
                    AssistantEventORM.client_message_id == client_message_id,
                )
            )
            if existing is not None:
                assert existing.turn_id is not None
                turn = await session.get(AssistantTurnORM, existing.turn_id)
                assert turn is not None
                return self._event_view(existing), self._turn_view(turn)

            seq = await self._next_seq(session, session_id)
            event = AssistantEventORM(
                id=event_id,
                session_id=session_id,
                seq=seq,
                event_type=AssistantEventType.USER_MESSAGE.value,
                actor_type=ActorType.USER.value,
                actor_id=actor_id,
                payload={"content": content, "active_plan_id": active_plan_id},
                turn_id=turn_id,
                client_message_id=client_message_id,
                delivery_status=DeliveryStatus.PENDING.value,
            )
            turn = AssistantTurnORM(
                id=turn_id,
                session_id=session_id,
                trigger_event_id=event_id,
                status=AssistantTurnStatus.QUEUED.value,
            )
            session.add_all([event, turn])
            await session.commit()
            await session.refresh(event)
            await session.refresh(turn)
        return self._event_view(event), self._turn_view(turn)

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
    ) -> tuple[AssistantEventView, AssistantTurnView]:
        async with self._database.session() as session:
            seq = await self._next_seq(session, session_id)
            event = AssistantEventORM(
                id=event_id,
                session_id=session_id,
                seq=seq,
                event_type=event_type,
                actor_type=ActorType.SYSTEM.value,
                actor_id="agentrig",
                payload=payload,
                turn_id=turn_id,
                plan_id=plan_id,
                run_id=run_id,
                delivery_status=DeliveryStatus.PENDING.value,
            )
            turn = AssistantTurnORM(
                id=turn_id,
                session_id=session_id,
                trigger_event_id=event_id,
                status=AssistantTurnStatus.QUEUED.value,
            )
            session.add_all([event, turn])
            await session.commit()
            await session.refresh(event)
            await session.refresh(turn)
        return self._event_view(event), self._turn_view(turn)

    async def get_event(self, event_id: str) -> AssistantEventView | None:
        async with self._database.session() as session:
            row = await session.get(AssistantEventORM, event_id)
        return self._event_view(row) if row is not None else None

    async def get_event_by_matrix_id(
        self,
        matrix_event_id: str,
    ) -> AssistantEventView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(AssistantEventORM).where(
                    AssistantEventORM.matrix_event_id == matrix_event_id
                )
            )
        return self._event_view(row) if row is not None else None

    async def get_linked_event(
        self,
        session_id: str,
        *,
        event_type: str,
        run_id: str,
    ) -> AssistantEventView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(AssistantEventORM).where(
                    AssistantEventORM.session_id == session_id,
                    AssistantEventORM.event_type == event_type,
                    AssistantEventORM.run_id == run_id,
                )
            )
        return self._event_view(row) if row is not None else None

    async def list_events(
        self,
        session_id: str,
        *,
        after_seq: int,
        limit: int,
    ) -> AssistantEventPage:
        filters = [
            AssistantEventORM.session_id == session_id,
            AssistantEventORM.seq > after_seq,
        ]
        async with self._database.session() as session:
            total = int(
                await session.scalar(
                    select(func.count(AssistantEventORM.id)).where(*filters)
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(AssistantEventORM)
                    .where(*filters)
                    .order_by(AssistantEventORM.seq)
                    .limit(limit)
                )
            )
        return AssistantEventPage(
            items=[self._event_view(row) for row in rows],
            total=total,
            limit=limit,
            after_seq=after_seq,
        )

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
    ) -> AssistantEventView:
        async with self._database.session() as session:
            seq = await self._next_seq(session, session_id)
            row = AssistantEventORM(
                id=event_id,
                session_id=session_id,
                seq=seq,
                event_type=event_type,
                actor_type=actor_type,
                actor_id=actor_id,
                payload=payload,
                turn_id=turn_id,
                plan_id=plan_id,
                run_id=run_id,
                case_run_id=case_run_id,
                invocation_id=invocation_id,
                matrix_event_id=matrix_event_id,
                delivery_status=delivery_status.value,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._event_view(row)

    async def get_turn(self, turn_id: str) -> AssistantTurnView | None:
        async with self._database.session() as session:
            row = await session.get(AssistantTurnORM, turn_id)
        return self._turn_view(row) if row is not None else None

    async def get_latest_open_turn(
        self,
        session_id: str,
    ) -> AssistantTurnView | None:
        open_statuses = (
            AssistantTurnStatus.QUEUED.value,
            AssistantTurnStatus.DISPATCHED.value,
            AssistantTurnStatus.RUNNING.value,
        )
        async with self._database.session() as session:
            row = await session.scalar(
                select(AssistantTurnORM)
                .where(
                    AssistantTurnORM.session_id == session_id,
                    AssistantTurnORM.status.in_(open_statuses),
                )
                .order_by(AssistantTurnORM.created_at.desc())
                .limit(1)
            )
        return self._turn_view(row) if row is not None else None

    async def create_turn(
        self,
        *,
        turn_id: str,
        session_id: str,
        trigger_event_id: str,
    ) -> AssistantTurnView:
        row = AssistantTurnORM(
            id=turn_id,
            session_id=session_id,
            trigger_event_id=trigger_event_id,
            status=AssistantTurnStatus.QUEUED.value,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._turn_view(row)

    async def set_turn_status(
        self,
        turn_id: str,
        status: AssistantTurnStatus,
        **values: Any,
    ) -> AssistantTurnView | None:
        async with self._database.session() as session:
            row = await session.get(AssistantTurnORM, turn_id)
            if row is None:
                return None
            row.status = status.value
            for key in (
                "matrix_request_event_id",
                "matrix_response_event_id",
                "error_code",
                "error_message",
                "model_metadata",
            ):
                if key in values:
                    setattr(row, key, values[key])
            if status is AssistantTurnStatus.RUNNING and row.started_at is None:
                row.started_at = utc_now()
            if status in {
                AssistantTurnStatus.COMPLETED,
                AssistantTurnStatus.FAILED,
                AssistantTurnStatus.CANCELLED,
            }:
                row.finished_at = utc_now()
            await session.commit()
            await session.refresh(row)
        return self._turn_view(row)

    async def mark_event_delivery(
        self,
        event_id: str,
        status: DeliveryStatus,
        *,
        matrix_event_id: str | None = None,
        last_error: str | None = None,
    ) -> AssistantEventView | None:
        async with self._database.session() as session:
            row = await session.get(AssistantEventORM, event_id)
            if row is None:
                return None
            row.delivery_status = status.value
            row.delivery_attempts += 1
            row.matrix_event_id = matrix_event_id or row.matrix_event_id
            row.last_error = last_error
            await session.commit()
            await session.refresh(row)
        return self._event_view(row)

    async def create_plan(
        self,
        plan_id: str,
        value: EvaluationPlanCreate,
    ) -> EvaluationPlanView:
        async with self._database.session() as session:
            revision = int(
                await session.scalar(
                    select(func.max(EvaluationPlanORM.revision)).where(
                        EvaluationPlanORM.session_id == value.session_id
                    )
                )
                or 0
            ) + 1
            row = EvaluationPlanORM(
                id=plan_id,
                session_id=value.session_id,
                source_turn_id=value.source_turn_id,
                parent_plan_id=value.parent_plan_id,
                revision=revision,
                status=EvaluationPlanStatus.DRAFT.value,
                goal=value.goal,
                selection=value.selection.model_dump(mode="json"),
                reasoning_summary=value.reasoning_summary,
                preview={},
                confirmation={"required": False, "reasons": []},
                created_by=value.created_by,
            )
            session_row = await session.get(AssistantSessionORM, value.session_id)
            assert session_row is not None
            session_row.active_plan_id = plan_id
            session_row.updated_at = utc_now()
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._plan_view(row)

    async def get_plan(self, plan_id: str) -> EvaluationPlanView | None:
        async with self._database.session() as session:
            row = await session.get(EvaluationPlanORM, plan_id)
        return self._plan_view(row) if row is not None else None

    async def get_plan_by_run_id(self, run_id: str) -> EvaluationPlanView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(EvaluationPlanORM).where(EvaluationPlanORM.run_id == run_id)
            )
        return self._plan_view(row) if row is not None else None

    async def update_draft_plan(
        self,
        plan_id: str,
        value: EvaluationPlanPatch,
    ) -> EvaluationPlanView | None:
        async with self._database.session() as session:
            row = await session.get(EvaluationPlanORM, plan_id)
            if row is None:
                return None
            changes = value.model_dump(exclude_none=True)
            if "selection" in changes:
                selection = value.selection
                assert selection is not None
                row.selection = selection.model_dump(mode="json")
            if value.goal is not None:
                row.goal = value.goal
            if value.reasoning_summary is not None:
                row.reasoning_summary = value.reasoning_summary
            row.preview = {}
            row.selection_hash = None
            row.last_error = None
            row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
        return self._plan_view(row)

    async def save_plan_preview(
        self,
        plan_id: str,
        *,
        preview: dict[str, Any],
        selection_hash: str,
        confirmation: dict[str, Any],
    ) -> EvaluationPlanView:
        async with self._database.session() as session:
            row = await session.get(EvaluationPlanORM, plan_id)
            assert row is not None
            row.preview = preview
            row.selection_hash = selection_hash
            row.confirmation = confirmation
            row.last_error = None
            row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
        return self._plan_view(row)

    async def confirm_plan(
        self,
        plan_id: str,
        *,
        confirmation_event_id: str,
        confirmed_by: str,
    ) -> EvaluationPlanView:
        now = utc_now()
        async with self._database.session() as session:
            row = await session.get(EvaluationPlanORM, plan_id)
            assert row is not None
            row.status = EvaluationPlanStatus.CONFIRMED.value
            row.confirmed_by = confirmed_by
            row.confirmed_at = now
            row.updated_at = now
            row.confirmation = {
                **row.confirmation,
                "confirmation_event_id": confirmation_event_id,
                "confirmed_by": confirmed_by,
                "confirmed_at": now.isoformat(),
            }
            await session.commit()
            await session.refresh(row)
        return self._plan_view(row)

    async def cancel_plan(self, plan_id: str) -> EvaluationPlanView:
        async with self._database.session() as session:
            row = await session.get(EvaluationPlanORM, plan_id)
            assert row is not None
            row.status = EvaluationPlanStatus.CANCELLED.value
            row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
        return self._plan_view(row)

    async def mark_plan_submitted(
        self,
        plan_id: str,
        *,
        idempotency_key: str,
        run_id: str,
    ) -> EvaluationPlanView:
        now = utc_now()
        async with self._database.session() as session:
            row = await session.get(EvaluationPlanORM, plan_id)
            assert row is not None
            row.status = EvaluationPlanStatus.SUBMITTED.value
            row.submit_idempotency_key = idempotency_key
            row.run_id = run_id
            row.submitted_at = now
            row.updated_at = now
            row.last_error = None
            await session.commit()
            await session.refresh(row)
        return self._plan_view(row)

    async def save_plan_error(
        self,
        plan_id: str,
        error: dict[str, Any],
    ) -> EvaluationPlanView:
        async with self._database.session() as session:
            row = await session.get(EvaluationPlanORM, plan_id)
            assert row is not None
            row.last_error = error
            row.updated_at = utc_now()
            await session.commit()
            await session.refresh(row)
        return self._plan_view(row)

    async def get_integration_cursor(self, integration: str) -> str | None:
        async with self._database.session() as session:
            row = await session.get(IntegrationCursorORM, integration)
        return row.cursor if row is not None else None

    async def save_integration_cursor(
        self,
        integration: str,
        cursor: str,
        metadata: dict[str, Any],
    ) -> None:
        async with self._database.session() as session:
            row = await session.get(IntegrationCursorORM, integration)
            if row is None:
                session.add(
                    IntegrationCursorORM(
                        integration=integration,
                        cursor=cursor,
                        cursor_metadata=metadata,
                    )
                )
            else:
                row.cursor = cursor
                row.cursor_metadata = metadata
                row.updated_at = utc_now()
            await session.commit()

    @staticmethod
    async def _next_seq(session: Any, session_id: str) -> int:
        value = await session.scalar(
            update(AssistantSessionORM)
            .where(AssistantSessionORM.id == session_id)
            .values(
                last_event_seq=AssistantSessionORM.last_event_seq + 1,
                updated_at=utc_now(),
            )
            .returning(AssistantSessionORM.last_event_seq)
        )
        assert value is not None
        return int(value)

    @staticmethod
    def _session_view(row: AssistantSessionORM) -> AssistantSessionView:
        return AssistantSessionView.model_validate(
            {
                "id": row.id,
                "workspace_id": row.workspace_id,
                "title": row.title,
                "status": row.status,
                "matrix_room_id": row.matrix_room_id,
                "active_plan_id": row.active_plan_id,
                "last_event_seq": row.last_event_seq,
                "created_by": row.created_by,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )

    @staticmethod
    def _event_view(row: AssistantEventORM) -> AssistantEventView:
        return AssistantEventView.model_validate(
            {
                "id": row.id,
                "session_id": row.session_id,
                "seq": row.seq,
                "event_type": row.event_type,
                "actor_type": row.actor_type,
                "actor_id": row.actor_id,
                "payload": row.payload,
                "turn_id": row.turn_id,
                "plan_id": row.plan_id,
                "run_id": row.run_id,
                "case_run_id": row.case_run_id,
                "invocation_id": row.invocation_id,
                "client_message_id": row.client_message_id,
                "matrix_event_id": row.matrix_event_id,
                "delivery_status": row.delivery_status,
                "delivery_attempts": row.delivery_attempts,
                "last_error": row.last_error,
                "created_at": row.created_at,
            }
        )

    @staticmethod
    def _turn_view(row: AssistantTurnORM) -> AssistantTurnView:
        return AssistantTurnView.model_validate(
            {
                "id": row.id,
                "session_id": row.session_id,
                "trigger_event_id": row.trigger_event_id,
                "status": row.status,
                "matrix_request_event_id": row.matrix_request_event_id,
                "matrix_response_event_id": row.matrix_response_event_id,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "error_code": row.error_code,
                "error_message": row.error_message,
                "model_metadata": row.model_metadata,
                "created_at": row.created_at,
            }
        )

    @staticmethod
    def _plan_view(row: EvaluationPlanORM) -> EvaluationPlanView:
        return EvaluationPlanView.model_validate(
            {
                "id": row.id,
                "session_id": row.session_id,
                "source_turn_id": row.source_turn_id,
                "parent_plan_id": row.parent_plan_id,
                "revision": row.revision,
                "status": row.status,
                "goal": row.goal,
                "selection": row.selection,
                "reasoning_summary": row.reasoning_summary,
                "preview": row.preview,
                "confirmation": row.confirmation,
                "selection_hash": row.selection_hash,
                "submit_idempotency_key": row.submit_idempotency_key,
                "run_id": row.run_id,
                "last_error": row.last_error,
                "created_by": row.created_by,
                "confirmed_by": row.confirmed_by,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "confirmed_at": row.confirmed_at,
                "submitted_at": row.submitted_at,
            }
        )
