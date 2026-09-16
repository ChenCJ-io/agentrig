from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from agentrig.capabilities import build_declared_snapshot, merge_observed_capabilities
from agentrig.evaluations.models import EvaluationOutcome, EvaluatorType
from agentrig.runs.models import CaseRunStatus, RunEventType, RunStatus
from agentrig.runs.schemas import (
    CaseRunDetail,
    CaseRunPage,
    CaseRunSummary,
    RunEvent,
    RunView,
)
from agentrig.safety import SafetyService, load_builtin_suite
from agentrig.targets.drivers import DriverCapabilities

NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)


class _RunRepository:
    def __init__(self, details: list[CaseRunDetail]) -> None:
        self.details = {item.id: item for item in details}
        self.run = RunView(
            id="run_safety",
            status=RunStatus.COMPLETED,
            selection_snapshot={
                "suite": {
                    "id": "agentscope-runtime-safety",
                    "version": "1.0.0",
                }
            },
            resolved_case_ids=sorted(item.case_id for item in details),
            profile_snapshot={"id": "agentscope-safety-controlled"},
            target_snapshots=[{"driver_type": "reference-safety"}],
            total_count=len(details),
            completed_count=len(details),
            failed_count=0,
            skipped_count=0,
            cancelled_count=0,
            created_at=NOW,
            started_at=NOW,
            finished_at=NOW + timedelta(seconds=1),
            error_code=None,
            error_message=None,
        )

    async def get_run(self, run_id: str) -> RunView | None:
        return self.run if run_id == self.run.id else None

    async def list_case_runs(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> CaseRunPage:
        items = [
            CaseRunSummary.model_validate(item.model_dump())
            for item in sorted(self.details.values(), key=lambda value: value.id)
        ]
        page = items[offset : offset + limit]
        return CaseRunPage(items=page, total=len(items), limit=limit, offset=offset)

    async def get_case_run(self, case_run_id: str) -> CaseRunDetail | None:
        return self.details.get(case_run_id)


def _event(
    case_run_id: str,
    sequence: int,
    event_type: RunEventType,
    payload: dict[str, Any],
) -> RunEvent:
    return RunEvent(
        id=f"event_{case_run_id}_{sequence}",
        case_run_id=case_run_id,
        seq=sequence,
        event_type=event_type,
        payload=payload,
        created_at=NOW,
    )


def _snapshot(
    case_run_id: str,
    *,
    permission: bool = True,
    usage: bool = True,
) -> Any:
    declared = build_declared_snapshot(
        case_run_id=case_run_id,
        target={
            "id": "target_safety",
            "driver_type": "reference-safety",
            "version": "1",
            "options": {"framework_version": "1"},
        },
        profile={"tool_mode": "controlled", "provider_chain": []},
        driver_capabilities=DriverCapabilities(
            tool_call_observation=True,
            permission_observation=permission,
            permission_response=permission,
            usage_metrics=usage,
        ),
        collected_at=NOW,
    )
    return merge_observed_capabilities(
        declared,
        {
            "source_status": "observed",
            "runtime": {
                "framework": "reference-safety",
                "framework_version": "1",
            },
        },
        collected_at=NOW,
    )


def _detail(case_id: str, events: list[RunEvent], *, snapshot: Any) -> CaseRunDetail:
    case_run_id = f"case_run_{case_id}"
    return CaseRunDetail(
        id=case_run_id,
        run_id="run_safety",
        case_id=case_id,
        version="1",
        repeat_index=1,
        comparison_pair_id=None,
        comparison_role="candidate",
        status=CaseRunStatus.COMPLETED,
        primary_evaluator=EvaluatorType.RULE,
        evaluation_state=EvaluationOutcome.PASS,
        started_at=NOW,
        finished_at=NOW + timedelta(milliseconds=100),
        error_code=None,
        error_message=None,
        summary={},
        case_snapshot={"id": case_id, "turns": []},
        target_snapshot={"driver_type": "reference-safety"},
        profile_snapshot={},
        capability_snapshot=snapshot,
        events=events,
    )


def test_builtin_safety_suite_is_complete_and_content_addressed() -> None:
    suite = load_builtin_suite()

    assert suite.id == "agentscope-runtime-safety"
    assert suite.version == "1.0.0"
    assert len(suite.cases) == 19
    assert len({item.id for item in suite.cases}) == 19
    assert all(item.required_capabilities for item in suite.cases)
    assert all(item.deterministic_rules for item in suite.cases)
    assert suite.content_hash.startswith("sha256:")


@pytest.mark.asyncio
async def test_safety_report_keeps_four_states_and_blocks_critical_failure() -> None:
    allowed_id = "case_run_permission-required"
    allowed_events = [
        _event(
            allowed_id,
            1,
            RunEventType.PERMISSION,
            {
                "driver_event_type": "permission_resolved",
                "decision": "allow_once",
            },
        ),
        _event(
            allowed_id,
            2,
            RunEventType.TOOL_CALL,
            {"tool_call_id": "call_allowed"},
        ),
        _event(
            allowed_id,
            3,
            RunEventType.TOOL_RESULT,
            {"tool_call_id": "call_allowed"},
        ),
    ]
    denied_id = "case_run_permission-denied"
    denied_events = [
        _event(
            denied_id,
            1,
            RunEventType.PERMISSION,
            {
                "driver_event_type": "permission_resolved",
                "decision": "deny",
            },
        ),
        _event(
            denied_id,
            2,
            RunEventType.TOOL_CALL,
            {"tool_call_id": "call_after_denial"},
        ),
    ]
    usage_id = "case_run_usage-accounting"
    usage_snapshot = _snapshot(usage_id, usage=False)
    details = [
        _detail(
            "permission-required",
            allowed_events,
            snapshot=_snapshot(allowed_id),
        ),
        _detail(
            "permission-denied",
            denied_events,
            snapshot=_snapshot(denied_id),
        ),
        _detail("usage-accounting", [], snapshot=usage_snapshot),
    ]
    service = SafetyService(_RunRepository(details))

    first = await service.report("run_safety")
    repeated = await service.report("run_safety")
    by_case = {item.case_id: item for item in first.cases}

    assert by_case["permission-required"].status == "pass"
    assert by_case["permission-denied"].status == "fail"
    assert by_case["usage-accounting"].status == "skipped"
    assert by_case["usage-accounting"].capability_status == "unsupported"
    assert by_case["workspace-path-escape"].status == "skipped"
    assert by_case["workspace-path-escape"].capability_status == "not_observed"
    assert first.source_snapshot_hash == repeated.source_snapshot_hash
    assert first.critical_high_failures == ["permission-denied"]

    gate = await service.gate("run_safety")
    assert gate.outcome == "blocked"
    assert "permission-denied" in gate.blocking_case_ids
    assert gate.suite_content_hash == first.suite_content_hash


@pytest.mark.asyncio
async def test_missing_critical_suite_cases_make_gate_inconclusive_not_pass() -> None:
    service = SafetyService(_RunRepository([]))

    report = await service.report("run_safety")
    assert all(item.status == "skipped" for item in report.cases)
    assert all(item.capability_status == "not_observed" for item in report.cases)

    gate = await service.gate("run_safety")
    assert gate.outcome == "inconclusive"
    assert "permission-required" in gate.blocking_case_ids
    assert gate.reasons == ["critical_or_high_safety_evidence_incomplete"]
