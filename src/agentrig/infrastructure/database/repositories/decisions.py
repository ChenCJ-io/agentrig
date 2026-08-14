"""DecisionRecord 的 SQLAlchemy Repository。"""

from __future__ import annotations

from sqlalchemy import func, select

from ....assistant.decision_models import DecisionKind, DecisionStatus
from ....assistant.decision_schemas import (
    DecisionRecordPage,
    DecisionRecordView,
    EvidenceRef,
    ManagerDecisionProposal,
)
from ..orm import (
    AgentInvocationORM,
    AssistantEventORM,
    AssistantSessionORM,
    CaseRunORM,
    DecisionRecordORM,
    EvaluationORM,
    EvaluationPlanORM,
    ExecutionProfileORM,
    RunEventORM,
    SampleORM,
    TargetORM,
    TargetVersionORM,
    TestCaseORM,
    utc_now,
)
from ..session import Database


class SqlDecisionRepository:
    def __init__(self, database: Database, *, project_id: str = "default") -> None:
        self._database = database
        self._project_id = project_id

    async def create(
        self,
        decision_id: str,
        value: ManagerDecisionProposal,
        *,
        status: DecisionStatus,
        context_hash: str,
        policy_verdict: dict[str, object],
        action_idempotency_key: str,
    ) -> tuple[DecisionRecordView, bool]:
        now = utc_now()
        async with self._database.session() as session:
            # Lock the parent session before allocating an ordinal. PostgreSQL
            # therefore serializes decision creation across API processes; the
            # service's striped lock provides the equivalent in-process guard
            # for SQLite, where SELECT FOR UPDATE is intentionally ignored.
            parent_id = await session.scalar(
                select(AssistantSessionORM.id)
                .where(
                    AssistantSessionORM.id == value.session_id,
                    AssistantSessionORM.project_id == self._project_id,
                )
                .with_for_update()
            )
            assert parent_id is not None
            existing = await session.scalar(
                select(DecisionRecordORM).where(
                    DecisionRecordORM.action_idempotency_key == action_idempotency_key,
                    DecisionRecordORM.project_id == self._project_id,
                )
            )
            if existing is not None:
                return self._view(existing), False
            current = await session.scalar(
                select(func.max(DecisionRecordORM.ordinal)).where(
                    DecisionRecordORM.session_id == value.session_id,
                    DecisionRecordORM.turn_id == value.turn_id,
                    DecisionRecordORM.project_id == self._project_id,
                )
            )
            row = DecisionRecordORM(
                id=decision_id,
                project_id=self._project_id,
                session_id=value.session_id,
                turn_id=value.turn_id,
                parent_decision_id=value.parent_decision_id,
                ordinal=int(current or 0) + 1,
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
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return self._view(row), True

    async def get(self, decision_id: str) -> DecisionRecordView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(DecisionRecordORM).where(
                    DecisionRecordORM.id == decision_id,
                    DecisionRecordORM.project_id == self._project_id,
                )
            )
        return self._view(row) if row is not None else None

    async def get_by_idempotency_key(self, key: str) -> DecisionRecordView | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(DecisionRecordORM).where(
                    DecisionRecordORM.action_idempotency_key == key,
                    DecisionRecordORM.project_id == self._project_id,
                )
            )
        return self._view(row) if row is not None else None

    async def evidence_ref_is_valid(
        self,
        ref: EvidenceRef,
        *,
        session_id: str,
    ) -> bool:
        async with self._database.session() as session:
            owner = await session.scalar(
                select(AssistantSessionORM.id).where(
                    AssistantSessionORM.id == session_id,
                    AssistantSessionORM.project_id == self._project_id,
                )
            )
            if owner is None:
                return False
            if ref.kind == "test_case":
                case_row = await session.scalar(
                    select(TestCaseORM).where(
                        TestCaseORM.id == ref.resource_id,
                        TestCaseORM.project_id == self._project_id,
                    )
                )
                if case_row is None:
                    return False
                return ref.version is None or (
                    ref.version in {"draft", "approved", "rejected"}
                    and case_row.review_status == ref.version
                )
            if ref.kind in {"target", "target_check"}:
                target_row = await session.scalar(
                    select(TargetORM).where(
                        TargetORM.id == ref.resource_id,
                        TargetORM.project_id == self._project_id,
                    )
                )
                if (
                    target_row is None
                    or ref.kind == "target_check"
                    or ref.version is None
                ):
                    return target_row is not None
                version_id = await session.scalar(
                    select(TargetVersionORM.id).where(
                        TargetVersionORM.target_id == ref.resource_id,
                        TargetVersionORM.version == ref.version,
                    )
                )
                return version_id is not None
            if ref.kind == "execution_profile":
                return (
                    await session.scalar(
                        select(ExecutionProfileORM.id).where(
                            ExecutionProfileORM.id == ref.resource_id,
                            ExecutionProfileORM.project_id == self._project_id,
                        )
                    )
                    is not None
                )
            if ref.kind == "tool_sample":
                return (
                    await session.scalar(
                        select(SampleORM.id).where(
                            SampleORM.id == ref.resource_id,
                            SampleORM.project_id == self._project_id,
                        )
                    )
                    is not None
                )
            if ref.kind == "assistant_event":
                event_id = await session.scalar(
                    select(AssistantEventORM.id).where(
                        AssistantEventORM.id == ref.resource_id,
                        AssistantEventORM.session_id == session_id,
                    )
                )
                return event_id is not None
            if ref.kind == "evaluation_plan":
                plan = await session.scalar(
                    select(EvaluationPlanORM).where(
                        EvaluationPlanORM.id == ref.resource_id,
                        EvaluationPlanORM.session_id == session_id,
                        EvaluationPlanORM.project_id == self._project_id,
                    )
                )
                return plan is not None and (
                    ref.version is None or ref.version == str(plan.revision)
                )
            if ref.kind == "run":
                plan_id = await session.scalar(
                    select(EvaluationPlanORM.id).where(
                        EvaluationPlanORM.run_id == ref.resource_id,
                        EvaluationPlanORM.session_id == session_id,
                        EvaluationPlanORM.project_id == self._project_id,
                    )
                )
                return plan_id is not None
            if ref.kind == "case_run":
                case_run_id = await session.scalar(
                    select(CaseRunORM.id)
                    .join(
                        EvaluationPlanORM,
                        EvaluationPlanORM.run_id == CaseRunORM.run_id,
                    )
                    .where(
                        CaseRunORM.id == ref.resource_id,
                        EvaluationPlanORM.session_id == session_id,
                        CaseRunORM.project_id == self._project_id,
                        EvaluationPlanORM.project_id == self._project_id,
                    )
                )
                return case_run_id is not None
            if ref.kind == "run_event":
                event_id = await session.scalar(
                    select(RunEventORM.id)
                    .join(CaseRunORM, CaseRunORM.id == RunEventORM.case_run_id)
                    .join(
                        EvaluationPlanORM,
                        EvaluationPlanORM.run_id == CaseRunORM.run_id,
                    )
                    .where(
                        RunEventORM.id == ref.resource_id,
                        EvaluationPlanORM.session_id == session_id,
                        CaseRunORM.project_id == self._project_id,
                        EvaluationPlanORM.project_id == self._project_id,
                    )
                )
                return event_id is not None
            if ref.kind == "evaluation":
                evaluation_id = await session.scalar(
                    select(EvaluationORM.id)
                    .join(CaseRunORM, CaseRunORM.id == EvaluationORM.case_run_id)
                    .join(
                        EvaluationPlanORM,
                        EvaluationPlanORM.run_id == CaseRunORM.run_id,
                    )
                    .where(
                        EvaluationORM.id == ref.resource_id,
                        EvaluationPlanORM.session_id == session_id,
                        EvaluationORM.project_id == self._project_id,
                        CaseRunORM.project_id == self._project_id,
                        EvaluationPlanORM.project_id == self._project_id,
                    )
                )
                return evaluation_id is not None
            if ref.kind == "agent_invocation":
                invocation_id = await session.scalar(
                    select(AgentInvocationORM.id).where(
                        AgentInvocationORM.id == ref.resource_id,
                        AgentInvocationORM.session_id == session_id,
                        AgentInvocationORM.project_id == self._project_id,
                    )
                )
                return invocation_id is not None
        return False

    async def list_for_session(
        self,
        session_id: str,
        *,
        status: DecisionStatus | None,
        decision_kind: DecisionKind | None,
        limit: int,
        offset: int,
    ) -> DecisionRecordPage:
        filters = [
            DecisionRecordORM.session_id == session_id,
            DecisionRecordORM.project_id == self._project_id,
        ]
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
        expected_statuses: set[DecisionStatus] | None = None,
    ) -> DecisionRecordView | None:
        now = utc_now()
        async with self._database.session() as session:
            row = await session.scalar(
                select(DecisionRecordORM)
                .where(
                    DecisionRecordORM.id == decision_id,
                    DecisionRecordORM.project_id == self._project_id,
                )
                .with_for_update()
            )
            assert row is not None
            if expected_statuses is not None and DecisionStatus(row.status) not in expected_statuses:
                return None
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
