"""服务端报告与导出必须跨越分页且执行真实脱敏。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agentrig.cases.models import ReviewStatus
from agentrig.cases.schemas import TestCasePage as CasePage
from agentrig.cases.schemas import TestCaseView as CaseView
from agentrig.errors import AgentRigError, ErrorCode
from agentrig.evaluations.models import EvaluationOutcome, EvaluatorType
from agentrig.reporting import ReportingService
from agentrig.runs.models import CaseRunStatus, RunStatus
from agentrig.runs.redactor import Redactor
from agentrig.runs.schemas import CaseRunPage, CaseRunSummary, RunPage, RunView
from agentrig.targets.schemas import TargetView
from agentrig.tool_results.models import SampleKind, SampleStatus
from agentrig.tool_results.schemas import SamplePage, SampleView

NOW = datetime(2026, 8, 5, tzinfo=timezone.utc)


def run_view(
    index: int = 0,
    *,
    status: RunStatus = RunStatus.COMPLETED,
) -> RunView:
    return RunView(
        id=f"run_{index:04d}",
        status=status,
        selection_snapshot={},
        resolved_case_ids=[f"case_{index:04d}"],
        profile_snapshot={},
        target_snapshots=[
            {
                "id": "target_reporting",
                "name": "Reporting Target",
                "version": "v1",
                "options": {"authorization": "Bearer must-not-leak"},
            }
        ],
        total_count=1,
        completed_count=1,
        failed_count=0,
        skipped_count=0,
        cancelled_count=0,
        created_at=NOW,
        started_at=NOW,
        finished_at=NOW,
        error_code=None,
        error_message=None,
    )


def case_run(index: int, *, outcome: EvaluationOutcome) -> CaseRunSummary:
    return CaseRunSummary(
        id=f"case_run_{index:04d}",
        run_id="run_0000",
        case_id=f"case_{index:04d}",
        version="v1",
        repeat_index=0,
        comparison_pair_id=None,
        comparison_role="candidate",
        status=CaseRunStatus.COMPLETED,
        primary_evaluator=EvaluatorType.RULE,
        evaluation_state=outcome,
        started_at=NOW,
        finished_at=NOW,
        error_code=None,
        error_message=None,
        summary={"evaluation_summary": f"summary {index}"},
    )


def make_case(index: int) -> CaseView:
    return CaseView.model_validate(
        {
            "id": f"case_{index:04d}",
            "name": f"Case {index}",
            "turns": [{"position": 1, "user_message": "hello"}],
            "review_status": ReviewStatus.DRAFT,
            "created_at": NOW,
            "updated_at": NOW,
        }
    )


def sample(index: int) -> SampleView:
    return SampleView(
        id=f"sample_{index:04d}",
        name=f"Sample {index}",
        tool_name="search",
        sample_kind=SampleKind.SINGLE,
        content={"items": []},
        status=SampleStatus.DRAFT,
        source_type="manual",
        created_at=NOW,
        updated_at=NOW,
    )


class FakeRunRepository:
    def __init__(self, runs: list[RunView], case_runs: list[CaseRunSummary]) -> None:
        self.runs = runs
        self.case_runs = case_runs

    async def get_run(self, run_id: str) -> RunView | None:
        return next((item for item in self.runs if item.id == run_id), None)

    async def list_runs(
        self,
        *,
        target_id: str | None,
        limit: int,
        offset: int,
    ) -> RunPage:
        del target_id
        return RunPage(
            items=self.runs[offset : offset + limit],
            total=len(self.runs),
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
        del run_id
        return CaseRunPage(
            items=self.case_runs[offset : offset + limit],
            total=len(self.case_runs),
            limit=limit,
            offset=offset,
        )


class FakeCaseRepository:
    def __init__(self, items: list[CaseView]) -> None:
        self.items = items

    async def list_page(
        self,
        _selector: object,
        *,
        limit: int,
        offset: int,
    ) -> CasePage:
        return CasePage(
            items=self.items[offset : offset + limit],
            total=len(self.items),
            limit=limit,
            offset=offset,
        )


class FakeSampleRepository:
    def __init__(self, items: list[SampleView]) -> None:
        self.items = items

    async def list_page(
        self,
        *,
        status: SampleStatus | None,
        tool_name: str | None,
        limit: int,
        offset: int,
    ) -> SamplePage:
        del status, tool_name
        return SamplePage(
            items=self.items[offset : offset + limit],
            total=len(self.items),
            limit=limit,
            offset=offset,
        )


class FakeTargetRepository:
    async def get(self, target_id: str) -> TargetView | None:
        if target_id != "target_reporting":
            return None
        return TargetView(
            id=target_id,
            name="Reporting Target",
            driver_type="http_sse",
            endpoint="https://agent.example.test",
            created_at=NOW,
            updated_at=NOW,
        )


def reporting_service(
    *,
    runs: list[RunView],
    case_runs: list[CaseRunSummary],
    cases: list[CaseView] | None = None,
    samples: list[SampleView] | None = None,
    max_report_case_runs: int = 1_000,
    max_export_records: int = 1_000,
) -> ReportingService:
    return ReportingService(
        cases=FakeCaseRepository(cases or []),  # type: ignore[arg-type]
        targets=FakeTargetRepository(),  # type: ignore[arg-type]
        samples=FakeSampleRepository(samples or []),  # type: ignore[arg-type]
        runs=FakeRunRepository(runs, case_runs),  # type: ignore[arg-type]
        redactor=Redactor(),
        max_report_case_runs=max_report_case_runs,
        max_export_records=max_export_records,
    )


async def test_run_report_aggregates_case_runs_beyond_first_page() -> None:
    case_runs = [
        case_run(
            index,
            outcome=(EvaluationOutcome.FAIL if index == 204 else EvaluationOutcome.PASS),
        )
        for index in range(205)
    ]
    service = reporting_service(runs=[run_view()], case_runs=case_runs)

    report = await service.run_report("run_0000")

    assert report.outcomes.total == 205
    assert report.outcomes.pass_count == 204
    assert report.outcomes.fail_count == 1
    assert [item.case_id for item in report.failures] == ["case_0204"]
    assert "case_0204" in service.render_run_report(report).content


async def test_report_limits_and_terminal_download_are_explicit() -> None:
    oversized = reporting_service(
        runs=[run_view()],
        case_runs=[case_run(index, outcome=EvaluationOutcome.PASS) for index in range(2)],
        max_report_case_runs=1,
    )
    with pytest.raises(AgentRigError, match="CaseRun limit"):
        await oversized.run_report("run_0000")

    running = reporting_service(
        runs=[run_view(status=RunStatus.RUNNING)],
        case_runs=[case_run(0, outcome=EvaluationOutcome.AWAITING_VERDICT)],
    )
    report = await running.run_report("run_0000")
    with pytest.raises(AgentRigError) as exc:
        running.render_run_report(report)
    assert exc.value.detail.code is ErrorCode.CONFLICT
    assert exc.value.detail.retryable is True


async def test_target_export_is_complete_and_redacted_across_pages() -> None:
    service = reporting_service(
        runs=[run_view(index) for index in range(205)],
        case_runs=[],
        cases=[make_case(index) for index in range(205)],
        samples=[sample(index) for index in range(205)],
    )

    preview = await service.export_preview("target_reporting")
    bundle = await service.target_export("target_reporting")
    rendered = service.render_target_export(bundle, "json")

    assert preview.counts.total_records == 615
    assert preview.within_limit is True
    assert len(bundle.scope.runs) == 205
    assert len(bundle.scope.test_cases) == 205
    assert len(bundle.scope.samples) == 205
    assert "must-not-leak" not in rendered.content
    assert "[REDACTED]" in rendered.content


async def test_target_export_rejects_oversized_dataset_instead_of_truncating() -> None:
    service = reporting_service(
        runs=[run_view(index) for index in range(2)],
        case_runs=[],
        cases=[make_case(index) for index in range(2)],
        max_export_records=3,
    )

    preview = await service.export_preview("target_reporting")
    assert preview.within_limit is False

    with pytest.raises(AgentRigError) as exc:
        await service.target_export("target_reporting")
    assert exc.value.detail.code is ErrorCode.VALIDATION_ERROR
    assert exc.value.detail.details == {
        "record_count": 4,
        "max_export_records": 3,
    }
