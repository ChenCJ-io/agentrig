"""MCP、HTTP 和未来 V2 助手共用的 Run Service。"""

from __future__ import annotations

from ..errors import AgentRigError, ErrorCode
from ..evaluations.schemas import EvaluationResult, ExternalVerdictSubmit
from ..evaluations.service import EvaluationService
from .models import RunEventType
from .planner import RunPlanner
from .repository import RunRepository
from .scheduler import RunScheduler
from .schemas import (
    CaseRunDetail,
    CaseRunPage,
    RunCasesRequest,
    RunEventPage,
    RunPage,
    RunSubmitResult,
    RunView,
)


class RunService:
    def __init__(
        self,
        *,
        planner: RunPlanner,
        scheduler: RunScheduler,
        repository: RunRepository,
        evaluations: EvaluationService,
    ) -> None:
        self._planner = planner
        self._scheduler = scheduler
        self._repository = repository
        self._evaluations = evaluations

    async def run_cases(self, request: RunCasesRequest) -> RunSubmitResult:
        plan = await self._planner.plan(request)
        self._scheduler.submit(
            plan.response.run_id,
            plan.executable_case_run_ids,
            concurrency=plan.concurrency,
        )
        return plan.response

    async def get_run(self, run_id: str) -> RunView:
        run = await self._repository.get_run(run_id)
        if run is None:
            raise AgentRigError(
                ErrorCode.NOT_FOUND,
                f"run not found: {run_id}",
                details={"run_id": run_id},
            )
        return run

    async def list_runs(self, *, limit: int = 50, offset: int = 0) -> RunPage:
        return await self._repository.list_runs(
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
        await self._scheduler.cancel(run_id)
        return await self.get_run(run_id)

    async def submit_external_verdict(
        self,
        case_run_id: str,
        value: ExternalVerdictSubmit,
    ) -> EvaluationResult:
        return await self._evaluations.submit_external_verdict(case_run_id, value)
