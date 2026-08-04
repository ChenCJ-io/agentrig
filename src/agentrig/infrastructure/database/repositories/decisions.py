"""DecisionRecord 的 SQLAlchemy Repository。"""

from __future__ import annotations

from sqlalchemy import func, select

from ....assistant.decision_models import DecisionKind, DecisionStatus
from ....assistant.decision_schemas import (
    DecisionRecordPage,
    DecisionRecordView,
    ManagerDecisionProposal,
)
from ..orm import DecisionRecordORM, utc_now
from ..session import Database


class SqlDecisionRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create(
        self,
        decision_id: str,
        value: ManagerDecisionProposal,
        *,
        ordinal: int,
        status: DecisionStatus,
        context_hash: str,
        policy_verdict: dict[str, object],
        action_idempotency_key: str,
    ) -> DecisionRecordView:
        now = utc_now()
        row = DecisionRecordORM(
            id=decision_id,
            session_id=value.session_id,
            turn_id=value.turn_id,
            parent_decision_id=value.parent_decision_id,
            ordinal=ordinal,
            schema_version=value.schema_version,
            trigger_type=value.trigger.value,
            decision_kind=value.decision_kind.value,
            status=status.value,
            objective=value.objective,
            observation_summary=value.observation_summary.model_dump(mode="json"),
            options=[item.model_dump(mode="json") for item in value.options],
            selected_action=value.selected_action.model_dump(mode="json"),
            rationale_summary=value.rationale_summary.model_dump(mode="json"),
            evidence_refs=[item.model_dump(mode="json") for item in value.evidence_refs],
            confidence=value.confidence,
            context_hash=context_hash,
            policy_verdict=policy_verdict,
            action_idempotency_key=action_idempotency_key,
            proposed_by=value.proposed_by,
            authorized_at=now if status is DecisionStatus.AUTHORIZED else None,
            finished_at=now if status.terminal else None,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._view(row)

    async def get(self, decision_id: str) -> DecisionRecordView | None:
        async with self._database.session() as session:
            row = await session.get(DecisionRecordORM, decision_id)
        return self._view(row) if row is not None else None

    async def get_by_idempotency_key(self, key: str) -> DecisionRecordView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(DecisionRecordORM).where(DecisionRecordORM.action_idempotency_key == key)
            )
        return self._view(row) if row is not None else None

    async def next_ordinal(self, session_id: str, turn_id: str) -> int:
        async with self._database.session() as session:
            current = await session.scalar(
                select(func.max(DecisionRecordORM.ordinal)).where(
                    DecisionRecordORM.session_id == session_id,
                    DecisionRecordORM.turn_id == turn_id,
                )
            )
        return int(current or 0) + 1

    async def list_for_session(
        self,
        session_id: str,
        *,
        status: DecisionStatus | None,
        decision_kind: DecisionKind | None,
        limit: int,
        offset: int,
    ) -> DecisionRecordPage:
        filters = [DecisionRecordORM.session_id == session_id]
        if status is not None:
            filters.append(DecisionRecordORM.status == status.value)
        if decision_kind is not None:
            filters.append(DecisionRecordORM.decision_kind == decision_kind.value)
        async with self._database.session() as session:
            total = int(
                await session.scalar(select(func.count(DecisionRecordORM.id)).where(*filters)) or 0
            )
            rows = list(
                await session.scalars(
                    select(DecisionRecordORM)
                    .where(*filters)
                    .order_by(
                        DecisionRecordORM.created_at.desc(),
                        DecisionRecordORM.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
        return DecisionRecordPage(
            items=[self._view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def set_status(
        self,
        decision_id: str,
        status: DecisionStatus,
        *,
        confirmation_event_id: str | None = None,
        action_ref_type: str | None = None,
        action_ref_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> DecisionRecordView:
        now = utc_now()
        async with self._database.session() as session:
            row = await session.get(DecisionRecordORM, decision_id)
            assert row is not None
            row.status = status.value
            if confirmation_event_id is not None:
                row.confirmation_event_id = confirmation_event_id
            if action_ref_type is not None:
                row.action_ref_type = action_ref_type
            if action_ref_id is not None:
                row.action_ref_id = action_ref_id
            row.error_code = error_code
            row.error_message = error_message
            if status is DecisionStatus.AUTHORIZED:
                row.authorized_at = now
            if status is DecisionStatus.EXECUTING:
                row.started_at = row.started_at or now
            if status.terminal:
                row.finished_at = now
            await session.commit()
            await session.refresh(row)
        return self._view(row)

    @staticmethod
    def _view(row: DecisionRecordORM) -> DecisionRecordView:
        return DecisionRecordView.model_validate(
            {
                "id": row.id,
                "session_id": row.session_id,
                "turn_id": row.turn_id,
                "parent_decision_id": row.parent_decision_id,
                "ordinal": row.ordinal,
                "schema_version": row.schema_version,
                "trigger": row.trigger_type,
                "decision_kind": row.decision_kind,
                "status": row.status,
                "objective": row.objective,
                "observation_summary": row.observation_summary,
                "options": row.options,
                "selected_action": row.selected_action,
                "rationale_summary": row.rationale_summary,
                "evidence_refs": row.evidence_refs,
                "confidence": row.confidence,
                "context_hash": row.context_hash,
                "policy_verdict": row.policy_verdict,
                "confirmation_event_id": row.confirmation_event_id,
                "action_idempotency_key": row.action_idempotency_key,
                "action_ref_type": row.action_ref_type,
                "action_ref_id": row.action_ref_id,
                "error_code": row.error_code,
                "error_message": row.error_message,
                "proposed_by": row.proposed_by,
                "created_at": row.created_at,
                "authorized_at": row.authorized_at,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
            }
        )
