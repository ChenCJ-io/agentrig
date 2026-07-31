"""Run、CaseRun 与 append-only 证据事件的 SQLAlchemy Repository。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ....evaluations.models import EvaluationOutcome, EvaluatorType
from ....evaluations.schemas import EvaluationResult
from ....identifiers import new_id
from ....runs.models import CaseRunStatus, RunEventType, RunStatus
from ....runs.schemas import (
    CaseRunDetail,
    CaseRunPage,
    CaseRunSummary,
    RunEvent,
    RunEventPage,
    RunPage,
    RunView,
)
from ..orm import CaseRunORM, EvaluationORM, RunEventORM, RunORM, utc_now
from ..session import Database


class SqlRunRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def create_run(
        self,
        *,
        run_id: str,
        selection_snapshot: dict[str, Any],
        resolved_case_ids: list[str],
        profile_snapshot: dict[str, Any],
        target_snapshots: list[dict[str, Any]],
    ) -> RunView:
        row = RunORM(
            id=run_id,
            status=RunStatus.QUEUED.value,
            selection_snapshot=selection_snapshot,
            resolved_case_ids=resolved_case_ids,
            profile_snapshot=profile_snapshot,
            target_snapshots=target_snapshots,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._run_view(row)

    async def create_case_run(
        self,
        *,
        case_run_id: str,
        run_id: str,
        case_id: str,
        case_snapshot: dict[str, Any],
        target_snapshot: dict[str, Any],
        profile_snapshot: dict[str, Any],
        version: str | None,
        repeat_index: int,
        comparison_pair_id: str | None,
        comparison_role: str | None,
        status: CaseRunStatus,
        primary_evaluator: EvaluatorType,
        evaluation_state: EvaluationOutcome,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        row = CaseRunORM(
            id=case_run_id,
            run_id=run_id,
            case_id=case_id,
            case_snapshot=case_snapshot,
            target_snapshot=target_snapshot,
            profile_snapshot=profile_snapshot,
            version=version,
            repeat_index=repeat_index,
            comparison_pair_id=comparison_pair_id,
            comparison_role=comparison_role,
            status=status.value,
            primary_evaluator=primary_evaluator.value,
            evaluation_state=evaluation_state.value,
            error_code=error_code,
            error_message=error_message,
            finished_at=utc_now() if status is CaseRunStatus.SKIPPED else None,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()

    async def get_run(self, run_id: str) -> RunView | None:
        async with self._database.session() as session:
            row = await session.get(RunORM, run_id)
            return self._run_view(row) if row is not None else None

    async def list_runs(self, *, limit: int, offset: int) -> RunPage:
        async with self._database.session() as session:
            total = int(await session.scalar(select(func.count(RunORM.id))) or 0)
            rows = list(
                await session.scalars(
                    select(RunORM)
                    .order_by(RunORM.created_at.desc(), RunORM.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
        return RunPage(
            items=[self._run_view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def list_case_runs(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> CaseRunPage:
        async with self._database.session() as session:
            total = int(
                await session.scalar(
                    select(func.count(CaseRunORM.id)).where(CaseRunORM.run_id == run_id)
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(CaseRunORM)
                    .where(CaseRunORM.run_id == run_id)
                    .order_by(CaseRunORM.id)
                    .limit(limit)
                    .offset(offset)
                )
            )
        return CaseRunPage(
            items=[self._case_summary(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_case_run(self, case_run_id: str) -> CaseRunDetail | None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(CaseRunORM)
                .where(CaseRunORM.id == case_run_id)
                .options(
                    selectinload(CaseRunORM.events),
                    selectinload(CaseRunORM.evaluations),
                )
            )
            if row is None:
                return None
            summary = self._case_summary(row)
            return CaseRunDetail(
                **summary.model_dump(),
                case_snapshot=row.case_snapshot,
                target_snapshot=row.target_snapshot,
                profile_snapshot=row.profile_snapshot,
                events=[self._event_view(item) for item in row.events],
                evaluations=[self._evaluation_view(item) for item in row.evaluations],
            )

    async def list_case_run_events(
        self,
        case_run_id: str,
        *,
        event_types: list[RunEventType] | None,
        limit: int,
        offset: int,
    ) -> RunEventPage:
        filters = [RunEventORM.case_run_id == case_run_id]
        if event_types:
            filters.append(
                RunEventORM.event_type.in_([item.value for item in event_types])
            )
        async with self._database.session() as session:
            total = int(
                await session.scalar(
                    select(func.count(RunEventORM.id)).where(*filters)
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(RunEventORM)
                    .where(*filters)
                    .order_by(RunEventORM.seq)
                    .limit(limit)
                    .offset(offset)
                )
            )
        return RunEventPage(
            items=[self._event_view(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def set_run_status(
        self,
        run_id: str,
        status: RunStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        async with self._database.session() as session:
            row = await session.get(RunORM, run_id)
            assert row is not None
            row.status = status.value
            row.error_code = error_code
            row.error_message = error_message
            if status is RunStatus.RUNNING and row.started_at is None:
                row.started_at = utc_now()
            if status in {
                RunStatus.COMPLETED,
                RunStatus.CANCELLED,
                RunStatus.INTERRUPTED,
                RunStatus.FAILED,
            }:
                row.finished_at = utc_now()
            await session.commit()

    async def set_case_run_status(
        self,
        case_run_id: str,
        status: CaseRunStatus,
        *,
        evaluation_state: EvaluationOutcome | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        async with self._database.session() as session:
            row = await session.get(CaseRunORM, case_run_id)
            assert row is not None
            row.status = status.value
            if evaluation_state is not None:
                row.evaluation_state = evaluation_state.value
            row.error_code = error_code
            row.error_message = error_message
            if summary is not None:
                row.summary = summary
            if status is CaseRunStatus.RUNNING and row.started_at is None:
                row.started_at = utc_now()
            if status in {
                CaseRunStatus.COMPLETED,
                CaseRunStatus.FAILED,
                CaseRunStatus.SKIPPED,
                CaseRunStatus.CANCELLED,
                CaseRunStatus.INTERRUPTED,
            }:
                row.finished_at = utc_now()
            await session.commit()

    async def append_event(
        self,
        case_run_id: str,
        event_type: RunEventType,
        payload: dict[str, Any],
    ) -> RunEvent:
        async with self._database.session() as session:
            last_seq = int(
                await session.scalar(
                    select(func.max(RunEventORM.seq)).where(
                        RunEventORM.case_run_id == case_run_id
                    )
                )
                or 0
            )
            row = RunEventORM(
                id=new_id("evt"),
                case_run_id=case_run_id,
                seq=last_seq + 1,
                event_type=event_type.value,
                payload=payload,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._event_view(row)

    async def set_evaluation_state(
        self,
        case_run_id: str,
        evaluation_state: EvaluationOutcome,
    ) -> None:
        async with self._database.session() as session:
            row = await session.get(CaseRunORM, case_run_id)
            assert row is not None
            row.evaluation_state = evaluation_state.value
            await session.commit()

    async def mark_in_progress_interrupted(self) -> None:
        now = utc_now()
        async with self._database.session() as session:
            runs = list(
                await session.scalars(
                    select(RunORM).where(
                        RunORM.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value])
                    )
                )
            )
            case_runs = list(
                await session.scalars(
                    select(CaseRunORM).where(
                        CaseRunORM.status.in_(
                            [CaseRunStatus.QUEUED.value, CaseRunStatus.RUNNING.value]
                        )
                    )
                )
            )
            for run_row in runs:
                run_row.status = RunStatus.INTERRUPTED.value
                run_row.finished_at = now
                run_row.error_code = "interrupted"
                run_row.error_message = "service restarted before the run completed"
            for case_run_row in case_runs:
                case_run_row.status = CaseRunStatus.INTERRUPTED.value
                case_run_row.evaluation_state = (
                    EvaluationOutcome.EVALUATION_ERROR.value
                )
                case_run_row.finished_at = now
                case_run_row.error_code = "interrupted"
                case_run_row.error_message = "service restarted before the case run completed"
            await session.commit()

    async def refresh_run_counts(self, run_id: str) -> RunView:
        async with self._database.session() as session:
            row = await session.get(RunORM, run_id)
            assert row is not None
            statuses = list(
                await session.scalars(
                    select(CaseRunORM.status).where(CaseRunORM.run_id == run_id)
                )
            )
            row.total_count = len(statuses)
            row.completed_count = statuses.count(CaseRunStatus.COMPLETED.value)
            row.failed_count = statuses.count(CaseRunStatus.FAILED.value)
            row.skipped_count = statuses.count(CaseRunStatus.SKIPPED.value)
            row.cancelled_count = statuses.count(CaseRunStatus.CANCELLED.value)
            await session.commit()
            await session.refresh(row)
            return self._run_view(row)

    @staticmethod
    def _run_view(row: RunORM) -> RunView:
        return RunView.model_validate(
            {
                "id": row.id,
                "status": row.status,
                "selection_snapshot": row.selection_snapshot,
                "resolved_case_ids": row.resolved_case_ids,
                "profile_snapshot": row.profile_snapshot,
                "target_snapshots": row.target_snapshots,
                "total_count": row.total_count,
                "completed_count": row.completed_count,
                "failed_count": row.failed_count,
                "skipped_count": row.skipped_count,
                "cancelled_count": row.cancelled_count,
                "created_at": row.created_at,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "error_code": row.error_code,
                "error_message": row.error_message,
            }
        )

    @staticmethod
    def _case_summary(row: CaseRunORM) -> CaseRunSummary:
        return CaseRunSummary.model_validate(
            {
                "id": row.id,
                "run_id": row.run_id,
                "case_id": row.case_id,
                "version": row.version,
                "repeat_index": row.repeat_index,
                "comparison_pair_id": row.comparison_pair_id,
                "comparison_role": row.comparison_role,
                "status": row.status,
                "primary_evaluator": row.primary_evaluator,
                "evaluation_state": row.evaluation_state,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "error_code": row.error_code,
                "error_message": row.error_message,
                "summary": row.summary,
            }
        )

    @staticmethod
    def _event_view(row: RunEventORM) -> RunEvent:
        return RunEvent.model_validate(
            {
                "id": row.id,
                "case_run_id": row.case_run_id,
                "seq": row.seq,
                "event_type": row.event_type,
                "payload": row.payload,
                "created_at": row.created_at,
            }
        )

    @staticmethod
    def _evaluation_view(row: EvaluationORM) -> EvaluationResult:
        return EvaluationResult.model_validate(
            {
                "id": row.id,
                "case_run_id": row.case_run_id,
                "evaluator_type": row.evaluator_type,
                "evaluator_source": row.evaluator_source,
                "status": row.status,
                "verdict": row.verdict,
                "summary": row.summary,
                "criteria": row.criteria,
                "evidence_refs": row.evidence_refs,
                "config_snapshot": row.config_snapshot,
                "model_metadata": row.model_metadata,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
