"""MCP、HTTP 和未来 V2 助手共用的 Run Service。"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from ..capabilities import (
    CapabilityComparisonPolicy,
    CapabilityDiff,
    TargetCapabilitySnapshot,
    build_legacy_snapshot,
    compare_capabilities,
)
from ..errors import AgentRigError, ErrorCode
from ..evaluations.schemas import EvaluationResult, ExternalVerdictSubmit
from ..evaluations.service import EvaluationService
from .models import FailureClass, RunEventType, RunStatus
from .planner import RunPlan, RunPlanner
from .repository import RunRepository
from .scheduler import RunScheduler
from .schemas import (
    CaseRunDetail,
    CaseRunPage,
    RunCasesRequest,
    RunCellDetail,
    RunCellPage,
    RunCellRetryRequest,
    RunEventPage,
    RunPage,
    RunPreview,
    RunProgressSummary,
    RunRecoveryResult,
    RunSubmitResult,
    RunView,
)

if TYPE_CHECKING:
    from ..jobs import DurableJobService, DurableWorker


class RunService:
    def __init__(
        self,
        *,
        planner: RunPlanner,
        scheduler: RunScheduler,
        repository: RunRepository,
        evaluations: EvaluationService,
        durable_jobs: DurableJobService | None = None,
        durable_worker: DurableWorker | None = None,
        durable_scheduler_enabled: bool = False,
    ) -> None:
        self._planner = planner
        self._scheduler = scheduler
        self._repository = repository
        self._evaluations = evaluations
        self._durable_jobs = durable_jobs
        self._durable_worker = durable_worker
        self._durable_scheduler_enabled = durable_scheduler_enabled

    async def run_cases(self, request: RunCasesRequest) -> RunSubmitResult:
        plan = await self._planner.plan(request, dispatch_intent="immediate")
        await self.start_staged_run(plan)
        return plan.response

    async def stage_run_cases(self, request: RunCasesRequest) -> RunPlan:
        """落库 Run/CaseRun 但暂不调度，供 V2 先建立 Plan→Run 关联。"""

        return await self._planner.plan(request, dispatch_intent="evaluation_plan")

    async def start_staged_run(self, plan: RunPlan) -> None:
        if self._durable_scheduler_enabled:
            if self._durable_jobs is None:
                raise RuntimeError("durable scheduler is enabled without a job service")
            await self._durable_jobs.enqueue_plan(
                "default",
                plan.response.run_id,
                plan.executable_case_run_ids,
            )
            return
        self._scheduler.submit(
            plan.response.run_id,
            plan.executable_case_run_ids,
            concurrency=plan.concurrency,
        )

    async def preview_run_cases(self, request: RunCasesRequest) -> RunPreview:
        return await self._planner.preview(request)

    async def get_run(self, run_id: str) -> RunView:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"run not found: {run_id}",
                details={"run_id": run_id},
            )
        return run

    async def list_runs(
        self,
        *,
        target_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> RunPage:
        return await self._repository.list_runs(
            target_id=target_id,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def list_case_runs(
        self,
        run_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> CaseRunPage:
        await self.get_run(run_id)
        return await self._repository.list_case_runs(
            run_id,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def get_case_run(self, case_run_id: str) -> CaseRunDetail:
        case_run = await self._repository.get_case_run(case_run_id)
        if case_run is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"case run not found: {case_run_id}",
                details={"case_run_id": case_run_id},
            )
        return case_run

    async def list_run_cells(
        self,
        run_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> RunCellPage:
        await self.get_run(run_id)
        return await self._repository.list_run_cells(
            run_id,
            limit=max(1, min(limit, 200)),
            offset=max(0, offset),
        )

    async def get_run_cell(self, run_id: str, cell_id: str) -> RunCellDetail:
        await self.get_run(run_id)
        cell = await self._repository.get_run_cell(run_id, cell_id)
        if cell is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"run cell not found: {cell_id}",
                details={"run_id": run_id, "cell_id": cell_id},
            )
        return cell

    async def get_run_summary(self, run_id: str) -> RunProgressSummary:
        run = await self.get_run(run_id)
        first = await self._repository.list_run_cells(
            run_id,
            limit=200,
            offset=0,
        )
        cells = list(first.items)
        while len(cells) < first.total:
            page = await self._repository.list_run_cells(
                run_id,
                limit=200,
                offset=len(cells),
            )
            if page.total != first.total or not page.items:
                raise AgentRigError(
                    ErrorCode.CONFLICT,
                    "run cells changed while building summary; retry the request",
                    details={"run_id": run_id},
                    retryable=True,
                )
            cells.extend(page.items)
        attempts = [attempt for cell in cells for attempt in cell.attempts]
        terminal_statuses = {
            RunStatus.COMPLETED,
            RunStatus.CANCELLED,
            RunStatus.INTERRUPTED,
            RunStatus.FAILED,
        }
        return RunProgressSummary(
            run_id=run.id,
            status=run.status,
            terminal=run.status in terminal_statuses,
            manifest_hash=run.manifest_hash,
            recovery_of_run_id=run.recovery_of_run_id,
            cell_count=first.total,
            attempt_count=len(attempts),
            finished_attempt_count=sum(
                item.status.value
                in {"completed", "failed", "skipped", "cancelled", "interrupted"}
                for item in attempts
            ),
            cells_by_status=dict(
                sorted(Counter(item.status.value for item in cells).items())
            ),
            attempts_by_status=dict(
                sorted(Counter(item.status.value for item in attempts).items())
            ),
            evaluation_outcomes=dict(
                sorted(Counter(item.evaluation_state.value for item in attempts).items())
            ),
            failure_classes=dict(
                sorted(
                    Counter(
                        item.failure_class.value
                        for item in attempts
                        if item.failure_class is not None
                    ).items()
                )
            ),
        )

    async def retry_run_cells(
        self,
        run_id: str,
        value: RunCellRetryRequest,
    ) -> RunRecoveryResult:
        source = await self.get_run(run_id)
        if source.status not in {
            RunStatus.COMPLETED,
            RunStatus.CANCELLED,
            RunStatus.INTERRUPTED,
            RunStatus.FAILED,
        }:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "recovery can only be created from a terminal run",
                details={"run_id": run_id, "status": source.status.value},
            )
        cells = [await self.get_run_cell(run_id, cell_id) for cell_id in value.cell_ids]
        retryable = {
            FailureClass.TARGET_UNREACHABLE,
            FailureClass.TOOL_RESULT_UNAVAILABLE,
            FailureClass.TIMEOUT,
            FailureClass.EVALUATION_ERROR,
            FailureClass.CANCELLED,
            FailureClass.INTERRUPTED,
            FailureClass.INTERNAL_ERROR,
            FailureClass.UNKNOWN,
        }
        blocked: list[dict[str, str | None]] = []
        for cell in cells:
            if cell.failure_class in retryable:
                continue
            if (
                value.override_behavior_fail
                and cell.failure_class is FailureClass.BEHAVIOR_REGRESSION
            ):
                continue
            blocked.append(
                {
                    "cell_id": cell.cell_id,
                    "status": cell.status.value,
                    "failure_class": (
                        cell.failure_class.value
                        if cell.failure_class is not None
                        else None
                    ),
                }
            )
        if blocked:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "selected cells are not eligible for recovery",
                details={
                    "blocked_cells": blocked,
                    "override_behavior_fail": value.override_behavior_fail,
                },
            )
        plan = await self._planner.recover(source, cells, reason=value.reason)
        try:
            await self.start_staged_run(plan)
        except Exception as exc:
            await self._repository.set_run_status(
                plan.response.run_id,
                RunStatus.FAILED,
                error_code=ErrorCode.INTERNAL_ERROR.value,
                error_message=f"failed to start recovery run: {exc}",
            )
            raise
        return RunRecoveryResult.model_validate(plan.response.model_dump(mode="json"))

    async def get_capability_snapshot(
        self,
        case_run_id: str,
    ) -> TargetCapabilitySnapshot:
        case_run = await self.get_case_run(case_run_id)
        return case_run.capability_snapshot or build_legacy_snapshot(
            case_run_id=case_run.id,
            target=case_run.target_snapshot,
            collected_at=case_run.started_at or case_run.finished_at,
        )

    async def compare_capability_snapshots(
        self,
        baseline_case_run_id: str,
        candidate_case_run_id: str,
        policy: CapabilityComparisonPolicy | None = None,
    ) -> CapabilityDiff:
        baseline = await self.get_capability_snapshot(baseline_case_run_id)
        candidate = await self.get_capability_snapshot(candidate_case_run_id)
        return compare_capabilities(baseline, candidate, policy)

    async def list_case_run_events(
        self,
        case_run_id: str,
        *,
        event_types: list[RunEventType] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> RunEventPage:
        await self.get_case_run(case_run_id)
        return await self._repository.list_case_run_events(
            case_run_id,
            event_types=event_types,
            limit=max(1, min(limit, 500)),
            offset=max(0, offset),
        )

    async def cancel_run(self, run_id: str) -> RunView:
        await self.get_run(run_id)
        if self._durable_scheduler_enabled:
            if self._durable_worker is None:
                raise RuntimeError("durable scheduler is enabled without a worker runtime")
            await self._durable_worker.cancel_run("default", run_id)
            return await self.get_run(run_id)
        await self._scheduler.cancel(run_id)
        return await self.get_run(run_id)

    async def submit_external_verdict(
        self,
        case_run_id: str,
        value: ExternalVerdictSubmit,
    ) -> EvaluationResult:
        return await self._evaluations.submit_external_verdict(case_run_id, value)
