"""Run、CaseRun 与 append-only 证据事件的 SQLAlchemy Repository。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.orm import selectinload

from ....canonical import canonical_hash
from ....capabilities.schemas import TargetCapabilitySnapshot
from ....errors import AgentRigError, ErrorCode
from ....evaluations.models import EvaluationOutcome, EvaluatorType
from ....evaluations.schemas import EvaluationResult
from ....identifiers import new_id
from ....runs.failure_classification import classify_failure
from ....runs.models import CaseRunStatus, FailureClass, RunEventType, RunStatus
from ....runs.schemas import (
    CaseRunDetail,
    CaseRunPage,
    CaseRunSummary,
    RunCellDetail,
    RunCellPage,
    RunCellSummary,
    RunEvent,
    RunEventPage,
    RunPage,
    RunView,
)
from ....runs.timeline import build_evidence_timeline
from ..orm import CaseRunORM, EvaluationORM, RunEventORM, RunORM, utc_now
from ..session import Database


class SqlRunRepository:
    def __init__(self, database: Database, *, project_id: str = "default") -> None:
        self._database = database
        self._project_id = project_id

    async def create_run(
        self,
        *,
        run_id: str,
        selection_snapshot: dict[str, Any],
        resolved_case_ids: list[str],
        profile_snapshot: dict[str, Any],
        target_snapshots: list[dict[str, Any]],
        manifest_schema_version: str | None = None,
        manifest_hash: str | None = None,
        manifest: dict[str, Any] | None = None,
        recovery_of_run_id: str | None = None,
        recovery_reason: str | None = None,
        cell_count: int = 0,
        attempt_count: int = 0,
    ) -> RunView:
        row = RunORM(
            id=run_id,
            project_id=self._project_id,
            status=RunStatus.QUEUED.value,
            selection_snapshot=selection_snapshot,
            resolved_case_ids=resolved_case_ids,
            profile_snapshot=profile_snapshot,
            target_snapshots=target_snapshots,
            manifest_schema_version=manifest_schema_version,
            manifest_hash=manifest_hash,
            manifest=manifest,
            recovery_of_run_id=recovery_of_run_id,
            recovery_reason=recovery_reason,
            cell_count=cell_count,
            attempt_count=attempt_count,
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
        capability_snapshot: TargetCapabilitySnapshot | None,
        version: str | None,
        repeat_index: int,
        comparison_pair_id: str | None,
        comparison_role: str | None,
        status: CaseRunStatus,
        primary_evaluator: EvaluatorType,
        evaluation_state: EvaluationOutcome,
        error_code: str | None = None,
        error_message: str | None = None,
        cell_key: str | None = None,
        evaluation_attempt_id: str | None = None,
        attempt_index: int | None = None,
        failure_class: FailureClass | None = None,
        recovery_of_case_run_id: str | None = None,
    ) -> None:
        row = CaseRunORM(
            id=case_run_id,
            project_id=self._project_id,
            run_id=run_id,
            case_id=case_id,
            case_snapshot=case_snapshot,
            target_snapshot=target_snapshot,
            profile_snapshot=profile_snapshot,
            capability_snapshot=(
                capability_snapshot.model_dump(mode="json")
                if capability_snapshot is not None
                else None
            ),
            version=version,
            repeat_index=repeat_index,
            comparison_pair_id=comparison_pair_id,
            comparison_role=comparison_role,
            cell_key=cell_key,
            evaluation_attempt_id=evaluation_attempt_id,
            attempt_index=attempt_index,
            status=status.value,
            primary_evaluator=primary_evaluator.value,
            evaluation_state=evaluation_state.value,
            error_code=error_code,
            error_message=error_message,
            failure_class=failure_class.value if failure_class is not None else None,
            recovery_of_case_run_id=recovery_of_case_run_id,
            finished_at=utc_now() if status is CaseRunStatus.SKIPPED else None,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()

    async def get_run(self, run_id: str) -> RunView | None:
        async with self._database.session() as session:
            row = await session.get(RunORM, run_id)
            return (
                self._run_view(row)
                if row is not None and row.project_id == self._project_id
                else None
            )

    async def list_runs(
        self,
        *,
        target_id: str | None,
        limit: int,
        offset: int,
    ) -> RunPage:
        filters = [RunORM.project_id == self._project_id]
        if target_id is not None:
            filters.append(
                exists(
                    select(CaseRunORM.id).where(
                        CaseRunORM.run_id == RunORM.id,
                        CaseRunORM.target_snapshot["id"].as_string() == target_id,
                    )
                )
            )
        async with self._database.session() as session:
            total = int(
                await session.scalar(select(func.count(RunORM.id)).where(*filters))
                or 0
            )
            rows = list(
                await session.scalars(
                    select(RunORM)
                    .where(*filters)
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

    async def list_recovery_runs(
        self,
        recovery_of_run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> RunPage:
        filters = [
            RunORM.project_id == self._project_id,
            RunORM.recovery_of_run_id == recovery_of_run_id,
        ]
        async with self._database.session() as session:
            total = int(
                await session.scalar(select(func.count(RunORM.id)).where(*filters))
                or 0
            )
            rows = list(
                await session.scalars(
                    select(RunORM)
                    .where(*filters)
                    .order_by(RunORM.created_at, RunORM.id)
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
                    select(func.count(CaseRunORM.id)).where(
                        CaseRunORM.run_id == run_id,
                        CaseRunORM.project_id == self._project_id,
                    )
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(CaseRunORM)
                    .where(
                        CaseRunORM.run_id == run_id,
                        CaseRunORM.project_id == self._project_id,
                    )
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
                .where(
                    CaseRunORM.id == case_run_id,
                    CaseRunORM.project_id == self._project_id,
                )
                .options(
                    selectinload(CaseRunORM.events),
                    selectinload(CaseRunORM.evaluations),
                )
            )
            if row is None:
                return None
            return self._case_detail(row)

    async def list_run_cells(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> RunCellPage:
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(CaseRunORM)
                    .where(
                        CaseRunORM.run_id == run_id,
                        CaseRunORM.project_id == self._project_id,
                    )
                    .order_by(
                        CaseRunORM.cell_key,
                        CaseRunORM.attempt_index,
                        CaseRunORM.id,
                    )
                )
            )
        grouped = self._group_cells(rows)
        cells = [self._cell_summary(items) for items in grouped.values()]
        return RunCellPage(
            items=cells[offset : offset + limit],
            total=len(cells),
            limit=limit,
            offset=offset,
        )

    async def get_run_cell(self, run_id: str, cell_id: str) -> RunCellDetail | None:
        async with self._database.session() as session:
            rows = list(
                await session.scalars(
                    select(CaseRunORM)
                    .where(
                        CaseRunORM.run_id == run_id,
                        CaseRunORM.project_id == self._project_id,
                    )
                    .options(
                        selectinload(CaseRunORM.events),
                        selectinload(CaseRunORM.evaluations),
                    )
                    .order_by(CaseRunORM.attempt_index, CaseRunORM.id)
                )
            )
        grouped = self._group_cells(rows)
        selected = grouped.get(cell_id)
        if not selected:
            return None
        summary = self._cell_summary(selected)
        attempt_details = [self._case_detail(row) for row in selected]
        return RunCellDetail(
            **summary.model_dump(),
            attempt_details=attempt_details,
            timeline=build_evidence_timeline(
                summary.cell_id,
                attempt_details,
            ),
        )

    async def set_capability_snapshot(
        self,
        case_run_id: str,
        snapshot: TargetCapabilitySnapshot,
    ) -> None:
        async with self._database.session() as session:
            row = await session.scalar(
                select(CaseRunORM).where(
                    CaseRunORM.id == case_run_id,
                    CaseRunORM.project_id == self._project_id,
                )
            )
            assert row is not None
            first_event = await session.scalar(
                select(RunEventORM.id)
                .where(RunEventORM.case_run_id == case_run_id)
                .limit(1)
            )
            if first_event is not None:
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "capability snapshot is frozen after the first RunEvent",
                )
            if row.capability_snapshot is not None:
                current = TargetCapabilitySnapshot.model_validate(row.capability_snapshot)
                if current.snapshot_id != snapshot.snapshot_id:
                    raise AgentRigError(
                        ErrorCode.CONFLICT,
                        "capability snapshot identity cannot be replaced",
                    )
            row.capability_snapshot = snapshot.model_dump(mode="json")
            await session.commit()

    async def list_case_run_events(
        self,
        case_run_id: str,
        *,
        event_types: list[RunEventType] | None,
        limit: int,
        offset: int,
    ) -> RunEventPage:
        filters = [
            RunEventORM.case_run_id == case_run_id,
            CaseRunORM.project_id == self._project_id,
        ]
        if event_types:
            filters.append(
                RunEventORM.event_type.in_([item.value for item in event_types])
            )
        async with self._database.session() as session:
            total = int(
                await session.scalar(
                    select(func.count(RunEventORM.id))
                    .join(CaseRunORM, CaseRunORM.id == RunEventORM.case_run_id)
                    .where(*filters)
                )
                or 0
            )
            rows = list(
                await session.scalars(
                    select(RunEventORM)
                    .join(CaseRunORM, CaseRunORM.id == RunEventORM.case_run_id)
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
            assert row is not None and row.project_id == self._project_id
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
        failure_class: FailureClass | None = None,
    ) -> None:
        async with self._database.session() as session:
            row = await session.get(CaseRunORM, case_run_id)
            assert row is not None and row.project_id == self._project_id
            row.status = status.value
            if evaluation_state is not None:
                row.evaluation_state = evaluation_state.value
            row.error_code = error_code
            row.error_message = error_message
            resolved_failure_class = failure_class or classify_failure(
                error_code=error_code,
                evaluation_state=evaluation_state,
                status=status,
            )
            row.failure_class = (
                resolved_failure_class.value
                if resolved_failure_class is not None
                else None
            )
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
        *,
        attempt_id: str | None = None,
    ) -> RunEvent:
        async with self._database.session() as session:
            case_run = await session.get(CaseRunORM, case_run_id)
            assert case_run is not None and case_run.project_id == self._project_id
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
                attempt_id=attempt_id,
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
            assert row is not None and row.project_id == self._project_id
            row.evaluation_state = evaluation_state.value
            failure_class = classify_failure(evaluation_state=evaluation_state)
            row.failure_class = failure_class.value if failure_class is not None else None
            await session.commit()

    async def mark_in_progress_interrupted(self) -> None:
        now = utc_now()
        async with self._database.session() as session:
            runs = list(
                await session.scalars(
                    select(RunORM).where(
                        RunORM.project_id == self._project_id,
                        RunORM.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value])
                    )
                )
            )
            case_runs = list(
                await session.scalars(
                    select(CaseRunORM).where(
                        CaseRunORM.project_id == self._project_id,
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
                case_run_row.failure_class = FailureClass.INTERRUPTED.value
            await session.commit()

    async def refresh_run_counts(self, run_id: str) -> RunView:
        async with self._database.session() as session:
            row = await session.get(RunORM, run_id)
            assert row is not None and row.project_id == self._project_id
            statuses = list(
                await session.scalars(
                    select(CaseRunORM.status).where(
                        CaseRunORM.run_id == run_id,
                        CaseRunORM.project_id == self._project_id,
                    )
                )
            )
            row.total_count = len(statuses)
            row.completed_count = statuses.count(CaseRunStatus.COMPLETED.value)
            row.failed_count = statuses.count(CaseRunStatus.FAILED.value)
            row.skipped_count = statuses.count(CaseRunStatus.SKIPPED.value)
            row.cancelled_count = statuses.count(CaseRunStatus.CANCELLED.value)
            row.finished_attempt_count = sum(
                status
                in {
                    CaseRunStatus.COMPLETED.value,
                    CaseRunStatus.FAILED.value,
                    CaseRunStatus.SKIPPED.value,
                    CaseRunStatus.CANCELLED.value,
                    CaseRunStatus.INTERRUPTED.value,
                }
                for status in statuses
            )
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
                "manifest_schema_version": row.manifest_schema_version,
                "manifest_hash": row.manifest_hash,
                "manifest": row.manifest,
                "recovery_of_run_id": row.recovery_of_run_id,
                "recovery_reason": row.recovery_reason,
                "cell_count": row.cell_count,
                "attempt_count": row.attempt_count,
                "finished_attempt_count": row.finished_attempt_count,
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
        fallback_cell_key = canonical_hash(
            {
                "case_id": row.case_id,
                "target_id": row.target_snapshot.get("id"),
                "target_role": row.comparison_role or "candidate",
                "version": row.version,
                "case_snapshot": row.case_snapshot,
                "target_snapshot": row.target_snapshot,
                "profile_snapshot": row.profile_snapshot,
                "primary_evaluator": row.primary_evaluator,
            }
        )
        return CaseRunSummary.model_validate(
            {
                "id": row.id,
                "run_id": row.run_id,
                "case_id": row.case_id,
                "version": row.version,
                "repeat_index": row.repeat_index,
                "comparison_pair_id": row.comparison_pair_id,
                "comparison_role": row.comparison_role,
                "cell_key": row.cell_key or fallback_cell_key,
                "attempt_id": row.evaluation_attempt_id or row.id,
                "attempt_index": row.attempt_index or row.repeat_index or 1,
                "status": row.status,
                "primary_evaluator": row.primary_evaluator,
                "evaluation_state": row.evaluation_state,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "error_code": row.error_code,
                "error_message": row.error_message,
                "failure_class": row.failure_class,
                "recovery_of_case_run_id": row.recovery_of_case_run_id,
                "summary": row.summary,
            }
        )

    @classmethod
    def _case_detail(cls, row: CaseRunORM) -> CaseRunDetail:
        summary = cls._case_summary(row)
        return CaseRunDetail(
            **summary.model_dump(),
            case_snapshot=row.case_snapshot,
            target_snapshot=row.target_snapshot,
            profile_snapshot=row.profile_snapshot,
            capability_snapshot=(
                TargetCapabilitySnapshot.model_validate(row.capability_snapshot)
                if row.capability_snapshot is not None
                else None
            ),
            events=[cls._event_view(item) for item in row.events],
            evaluations=[cls._evaluation_view(item) for item in row.evaluations],
        )

    @classmethod
    def _group_cells(
        cls,
        rows: list[CaseRunORM],
    ) -> dict[str, list[CaseRunORM]]:
        grouped: dict[str, list[CaseRunORM]] = {}
        for row in rows:
            key = cls._case_summary(row).cell_key
            grouped.setdefault(key, []).append(row)
        return grouped

    @classmethod
    def _cell_summary(cls, rows: list[CaseRunORM]) -> RunCellSummary:
        attempts = sorted(
            (cls._case_summary(row) for row in rows),
            key=lambda item: (item.attempt_index, item.id),
        )
        first = attempts[0]
        finished = {
            CaseRunStatus.COMPLETED,
            CaseRunStatus.FAILED,
            CaseRunStatus.SKIPPED,
            CaseRunStatus.CANCELLED,
            CaseRunStatus.INTERRUPTED,
        }
        return RunCellSummary(
            cell_id=first.cell_key,
            cell_key=first.cell_key,
            run_id=first.run_id,
            case_id=first.case_id,
            target_id=str(rows[0].target_snapshot.get("id") or "unknown-target"),
            target_role=first.comparison_role or "candidate",
            version=first.version,
            status=cls._aggregate_cell_status(attempts),
            evaluation_state=cls._aggregate_evaluation_state(attempts),
            failure_class=next(
                (item.failure_class for item in attempts if item.failure_class is not None),
                None,
            ),
            attempt_count=len(attempts),
            finished_attempt_count=sum(item.status in finished for item in attempts),
            attempts=attempts,
        )

    @staticmethod
    def _aggregate_cell_status(attempts: list[CaseRunSummary]) -> CaseRunStatus:
        statuses = {item.status for item in attempts}
        if CaseRunStatus.RUNNING in statuses:
            return CaseRunStatus.RUNNING
        if CaseRunStatus.QUEUED in statuses:
            return CaseRunStatus.QUEUED
        if CaseRunStatus.FAILED in statuses:
            return CaseRunStatus.FAILED
        if CaseRunStatus.INTERRUPTED in statuses:
            return CaseRunStatus.INTERRUPTED
        if statuses == {CaseRunStatus.SKIPPED}:
            return CaseRunStatus.SKIPPED
        if CaseRunStatus.CANCELLED in statuses:
            return CaseRunStatus.CANCELLED
        return CaseRunStatus.COMPLETED

    @staticmethod
    def _aggregate_evaluation_state(
        attempts: list[CaseRunSummary],
    ) -> EvaluationOutcome:
        outcomes = {item.evaluation_state for item in attempts}
        if EvaluationOutcome.EVALUATION_ERROR in outcomes:
            return EvaluationOutcome.EVALUATION_ERROR
        if EvaluationOutcome.FAIL in outcomes:
            return EvaluationOutcome.FAIL
        if EvaluationOutcome.AWAITING_VERDICT in outcomes:
            return EvaluationOutcome.AWAITING_VERDICT
        if outcomes == {EvaluationOutcome.PASS}:
            return EvaluationOutcome.PASS
        return EvaluationOutcome.INCONCLUSIVE

    @staticmethod
    def _event_view(row: RunEventORM) -> RunEvent:
        return RunEvent.model_validate(
            {
                "id": row.id,
                "case_run_id": row.case_run_id,
                "seq": row.seq,
                "event_type": row.event_type,
                "attempt_id": row.attempt_id,
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
