"""Quality, A/B comparison, and release gate derive from immutable run facts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agentrig.errors import AgentRigError, ErrorCode
from agentrig.evaluations.models import (
    EvaluationOutcome,
    EvaluationRecordStatus,
    EvaluatorType,
)
from agentrig.evaluations.schemas import EvaluationResult
from agentrig.gates import (
    ReleasePolicy,
    default_release_policy,
    evaluate_release_gate,
)
from agentrig.pricing import apply_pricing_snapshot
from agentrig.profiles import ModelPricing, PricingSnapshot
from agentrig.reporting import ReportingService
from agentrig.reporting.quality import build_comparison_report, build_quality_report
from agentrig.runs.models import CaseRunStatus, RunEventType, RunStatus
from agentrig.runs.redactor import Redactor
from agentrig.runs.schemas import (
    CaseRunDetail,
    CaseRunPage,
    CaseRunSummary,
    RunEvent,
    RunPage,
    RunView,
)

NOW = datetime(2026, 8, 10, tzinfo=timezone.utc)


def test_repository_default_release_policy_matches_server_default() -> None:
    policy_path = (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "release-policies"
        / "default-agent-release.json"
    )
    from_file = ReleasePolicy.model_validate_json(policy_path.read_text(encoding="utf-8"))

    assert from_file == default_release_policy()


def _event(
    identifier: str,
    case_run_id: str,
    sequence: int,
    event_type: RunEventType,
    payload: dict[str, object],
) -> RunEvent:
    return RunEvent(
        id=identifier,
        case_run_id=case_run_id,
        seq=sequence,
        event_type=event_type,
        payload=payload,
        created_at=NOW,
    )


def _evaluation(
    identifier: str,
    case_run_id: str,
    verdict: str,
    reference: str,
) -> EvaluationResult:
    return EvaluationResult(
        id=identifier,
        case_run_id=case_run_id,
        evaluator_type=EvaluatorType.RULE,
        evaluator_source="agentrig.rule.v1",
        status=EvaluationRecordStatus.COMPLETED,
        verdict=verdict,  # type: ignore[arg-type]
        summary=verdict,
        evidence_refs=[reference],
        created_at=NOW,
        updated_at=NOW,
    )


def _detail(
    role: str,
    outcome: EvaluationOutcome,
    *,
    duration_seconds: int,
    input_tokens: int,
    output_tokens: int,
) -> CaseRunDetail:
    identifier = f"cr_{role}"
    driver_event_id = f"evt_{role}_driver"
    events = [
        _event(
            driver_event_id,
            identifier,
            1,
            RunEventType.DRIVER_REQUEST,
            {
                "phase": "completed",
                "duration_ms": 100 if role == "baseline" else 150,
                "ttft_ms": 10 if role == "baseline" else 20,
            },
        ),
        _event(
            f"evt_{role}_usage",
            identifier,
            2,
            RunEventType.USAGE,
            {
                "prompt_tokens": input_tokens,
                "completion_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                **(
                    {"prompt_tokens_details": {"cached_tokens": 3}}
                    if role == "baseline"
                    else {}
                ),
            },
        ),
    ]
    if role == "baseline":
        events.extend(
            [
                _event(
                    "evt_baseline_provider_miss",
                    identifier,
                    3,
                    RunEventType.PROVIDER_ATTEMPT,
                    {"tool_call_id": "call_1", "provider": "fixture", "status": "miss"},
                ),
                _event(
                    "evt_baseline_provider_hit",
                    identifier,
                    4,
                    RunEventType.PROVIDER_ATTEMPT,
                    {"tool_call_id": "call_1", "provider": "sample", "status": "hit"},
                ),
            ]
        )
    else:
        events.append(
            _event(
                "evt_candidate_provider_hit",
                identifier,
                3,
                RunEventType.PROVIDER_ATTEMPT,
                {"tool_call_id": "call_2", "provider": "fixture", "status": "hit"},
            )
        )
    return CaseRunDetail(
        id=identifier,
        run_id="run_ab",
        case_id="case_release",
        version="v1" if role == "baseline" else "v2",
        repeat_index=1,
        comparison_pair_id="pair_1",
        comparison_role=role,  # type: ignore[arg-type]
        status=CaseRunStatus.COMPLETED,
        primary_evaluator=EvaluatorType.RULE,
        evaluation_state=outcome,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=duration_seconds),
        error_code=None,
        error_message=None,
        summary={},
        case_snapshot={"turns": []},
        target_snapshot={"id": f"target_{role}"},
        profile_snapshot={},
        events=events,
        evaluations=[
            _evaluation(
                f"eval_{role}",
                identifier,
                outcome.value,
                driver_event_id,
            )
        ],
    )


def _run(status: RunStatus = RunStatus.COMPLETED) -> RunView:
    return RunView(
        id="run_ab",
        status=status,
        selection_snapshot={},
        resolved_case_ids=["case_release"],
        profile_snapshot={},
        target_snapshots=[{"id": "target_baseline"}, {"id": "target_candidate"}],
        total_count=2,
        completed_count=2,
        failed_count=0,
        skipped_count=0,
        cancelled_count=0,
        created_at=NOW,
        started_at=NOW,
        finished_at=NOW + timedelta(seconds=3),
        error_code=None,
        error_message=None,
    )


class _RunRepository:
    def __init__(
        self,
        run: RunView,
        details: list[CaseRunDetail],
        *,
        recovery_runs: list[RunView] | None = None,
        recovery_details: list[CaseRunDetail] | None = None,
    ) -> None:
        self.run = run
        self.details = details
        self.recovery_runs = recovery_runs or []
        self.recovery_details = recovery_details or []

    async def get_run(self, run_id: str) -> RunView | None:
        if run_id == self.run.id:
            return self.run
        return next((item for item in self.recovery_runs if item.id == run_id), None)

    async def list_runs(
        self,
        *,
        target_id: str | None,
        limit: int,
        offset: int,
    ) -> RunPage:
        del target_id
        items = [self.run][offset : offset + limit]
        return RunPage(items=items, total=1, limit=limit, offset=offset)

    async def list_recovery_runs(
        self,
        recovery_of_run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> RunPage:
        matches = [
            item
            for item in self.recovery_runs
            if item.recovery_of_run_id == recovery_of_run_id
        ]
        return RunPage(
            items=matches[offset : offset + limit],
            total=len(matches),
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
        all_details = [*self.details, *self.recovery_details]
        summaries = [
            CaseRunSummary.model_validate(
                item.model_dump(
                    exclude={
                        "case_snapshot",
                        "target_snapshot",
                        "profile_snapshot",
                        "events",
                        "evaluations",
                    }
                )
            )
            for item in all_details
            if item.run_id == run_id
        ]
        return CaseRunPage(
            items=summaries[offset : offset + limit],
            total=len(summaries),
            limit=limit,
            offset=offset,
        )

    async def get_case_run(self, case_run_id: str) -> CaseRunDetail | None:
        return next(
            (
                item
                for item in [*self.details, *self.recovery_details]
                if item.id == case_run_id
            ),
            None,
        )


class _UnusedRepository:
    pass


def _service(
    *,
    run: RunView | None = None,
    details: list[CaseRunDetail] | None = None,
    recovery_runs: list[RunView] | None = None,
    recovery_details: list[CaseRunDetail] | None = None,
) -> ReportingService:
    resolved = details or [
        _detail(
            "baseline",
            EvaluationOutcome.PASS,
            duration_seconds=1,
            input_tokens=10,
            output_tokens=5,
        ),
        _detail(
            "candidate",
            EvaluationOutcome.FAIL,
            duration_seconds=2,
            input_tokens=12,
            output_tokens=8,
        ),
    ]
    unused = _UnusedRepository()
    return ReportingService(
        cases=unused,  # type: ignore[arg-type]
        targets=unused,  # type: ignore[arg-type]
        samples=unused,  # type: ignore[arg-type]
        runs=_RunRepository(
            run or _run(),
            resolved,
            recovery_runs=recovery_runs,
            recovery_details=recovery_details,
        ),  # type: ignore[arg-type]
        redactor=Redactor(),
        max_report_case_runs=100,
        max_export_records=100,
    )


async def test_quality_report_aggregates_stable_latency_usage_reliability_and_evidence() -> None:
    service = _service()

    first = await service.quality_report("run_ab")
    second = await service.quality_report("run_ab")

    assert first.schema_version == "agentrig.quality-report.v1"
    assert first.source_snapshot_hash == second.source_snapshot_hash
    assert first.outcomes.pass_count == 1
    assert first.outcomes.fail_count == 1
    assert first.latency.run_duration_ms == 3_000
    assert first.latency.case_run.p50_ms == 1_000
    assert first.latency.case_run.p95_ms == 2_000
    assert first.latency.ttft.p95_ms == 20
    assert first.usage.input_tokens == 22
    assert first.usage.output_tokens == 13
    assert first.usage.total_tokens == 35
    assert first.usage.cached_input_tokens is None
    assert first.usage.reasoning_tokens is None
    assert first.reliability.provider_attempt_count == 3
    assert first.reliability.fallback_attempt_count == 1
    assert first.reliability.recovered_group_count == 1
    assert first.reliability.recovery_success_rate == 1
    assert first.evidence_quality.reference_validity_rate == 1
    assert first.evidence_quality.missing_reference_count == 0
    assert "cost_not_available_without_pricing_snapshot" in first.limitations
    assert "来源快照" in service.render_quality_report(first).content


def test_pricing_is_frozen_into_usage_and_never_recomputed_at_report_time() -> None:
    details = [
        _detail(
            "baseline",
            EvaluationOutcome.PASS,
            duration_seconds=1,
            input_tokens=10,
            output_tokens=5,
        ),
        _detail(
            "candidate",
            EvaluationOutcome.PASS,
            duration_seconds=1,
            input_tokens=12,
            output_tokens=8,
        ),
    ]
    snapshot = PricingSnapshot(
        source="operator-fixture",
        effective_at=NOW,
        rates=[
            ModelPricing(
                model="model-a",
                input_per_million="1",
                cached_input_per_million="0.1",
                output_per_million="2",
            )
        ],
    )
    for detail in details:
        usage_event = next(
            event for event in detail.events if event.event_type is RunEventType.USAGE
        )
        usage_event.payload = apply_pricing_snapshot(
            {
                **usage_event.payload,
                "model": "model-a",
                "cached_input_tokens": (
                    3 if detail.comparison_role == "baseline" else 0
                ),
            },
            snapshot,
        )

    first = build_quality_report(_run(), details, generated_at=NOW)
    assert first.usage.estimated_cost == "0.0000453"
    assert first.usage.currency == "USD"
    assert first.usage.cost_kind == "estimated"
    assert first.usage.pricing_source == "operator-fixture"
    assert first.usage.pricing_effective_at == NOW
    assert first.usage.pricing_snapshot_hash is not None
    assert "cost_not_available_without_pricing_snapshot" not in first.limitations

    # A new current price cannot alter the already persisted event-level cost.
    changed_current_price = snapshot.model_copy(
        update={
            "rates": [
                ModelPricing(
                    model="model-a",
                    input_per_million="999",
                    cached_input_per_million="999",
                    output_per_million="999",
                )
            ]
        }
    )
    assert changed_current_price != snapshot
    second = build_quality_report(_run(), details, generated_at=NOW)
    assert second.usage == first.usage


def test_pricing_does_not_assume_missing_cache_tokens_are_zero() -> None:
    snapshot = PricingSnapshot(
        source="operator-fixture",
        effective_at=NOW,
        rates=[
            ModelPricing(
                model="model-a",
                input_per_million="1",
                cached_input_per_million="0.1",
                output_per_million="2",
            )
        ],
    )
    usage = apply_pricing_snapshot(
        {"model": "model-a", "input_tokens": 10, "output_tokens": 2},
        snapshot,
    )
    assert "cost" not in usage


async def test_comparison_report_classifies_regression_and_uses_total_metric_ratios() -> None:
    service = _service()

    report = await service.comparison_report("run_ab")

    assert report.schema_version == "agentrig.comparison-report.v1"
    assert report.summary.total_pairs == 1
    assert report.summary.comparable_pairs == 1
    assert report.summary.regression_count == 1
    assert report.pairs[0].classification == "regression"
    assert report.pairs[0].duration_delta.ratio == 1
    assert report.metrics.duration_regression_ratio == 1
    assert report.metrics.token_regression_ratio == pytest.approx(5 / 15)
    assert report.limitations == ["capability_snapshot_not_available"]
    assert "regression" in service.render_comparison_report(report).content


@pytest.mark.parametrize(
    ("baseline_outcome", "candidate_outcome", "classification"),
    [
        (EvaluationOutcome.PASS, EvaluationOutcome.PASS, "unchanged_pass"),
        (EvaluationOutcome.FAIL, EvaluationOutcome.FAIL, "unchanged_fail"),
        (EvaluationOutcome.PASS, EvaluationOutcome.FAIL, "regression"),
        (EvaluationOutcome.FAIL, EvaluationOutcome.PASS, "fix"),
        (
            EvaluationOutcome.PASS,
            EvaluationOutcome.INCONCLUSIVE,
            "changed_inconclusive",
        ),
    ],
)
def test_comparison_outcome_classifications_are_explicit(
    baseline_outcome: EvaluationOutcome,
    candidate_outcome: EvaluationOutcome,
    classification: str,
) -> None:
    details = [
        _detail(
            "baseline",
            baseline_outcome,
            duration_seconds=1,
            input_tokens=10,
            output_tokens=5,
        ),
        _detail(
            "candidate",
            candidate_outcome,
            duration_seconds=2,
            input_tokens=12,
            output_tokens=8,
        ),
    ]

    report = build_comparison_report(_run(), details, generated_at=NOW)

    assert report.pairs[0].classification == classification


def test_comparison_marks_missing_or_duplicate_roles_as_incomplete() -> None:
    baseline = _detail(
        "baseline",
        EvaluationOutcome.PASS,
        duration_seconds=1,
        input_tokens=10,
        output_tokens=5,
    )
    duplicate = baseline.model_copy(update={"id": "cr_baseline_duplicate"})

    missing = build_comparison_report(_run(), [baseline], generated_at=NOW)
    duplicated = build_comparison_report(
        _run(),
        [baseline, duplicate],
        generated_at=NOW,
    )

    assert missing.summary.incomplete_pair_count == 1
    assert duplicated.summary.incomplete_pair_count == 1
    assert "pair_requires_exactly_one_baseline_and_candidate" in (
        duplicated.pairs[0].limitations
    )


def test_report_replay_is_stable_across_twenty_input_order_variations() -> None:
    original = [
        _detail(
            "baseline",
            EvaluationOutcome.PASS,
            duration_seconds=1,
            input_tokens=10,
            output_tokens=5,
        ),
        _detail(
            "candidate",
            EvaluationOutcome.FAIL,
            duration_seconds=2,
            input_tokens=12,
            output_tokens=8,
        ),
    ]
    expected_quality = build_quality_report(_run(), original, generated_at=NOW)
    expected_comparison = build_comparison_report(_run(), original, generated_at=NOW)

    for iteration in range(20):
        details = [
            item.model_copy(
                update={"events": list(reversed(item.events))}
                if iteration % 2
                else {"events": list(item.events)}
            )
            for item in (reversed(original) if iteration % 2 else original)
        ]
        quality = build_quality_report(_run(), details, generated_at=NOW)
        comparison = build_comparison_report(_run(), details, generated_at=NOW)
        assert quality == expected_quality
        assert comparison == expected_comparison


async def test_infrastructure_failure_is_not_classified_as_product_regression() -> None:
    baseline = _detail(
        "baseline",
        EvaluationOutcome.PASS,
        duration_seconds=1,
        input_tokens=10,
        output_tokens=5,
    )
    candidate = _detail(
        "candidate",
        EvaluationOutcome.FAIL,
        duration_seconds=2,
        input_tokens=12,
        output_tokens=8,
    )
    failed_evaluation = candidate.evaluations[0].model_copy(
        update={"status": EvaluationRecordStatus.ERROR, "verdict": None}
    )
    candidate = candidate.model_copy(
        update={
            "status": CaseRunStatus.FAILED,
            "evaluation_state": EvaluationOutcome.EVALUATION_ERROR,
            "error_code": "target_unreachable",
            "error_message": "connection failed",
            "evaluations": [failed_evaluation],
        }
    )
    report = await _service(details=[baseline, candidate]).comparison_report("run_ab")

    assert report.summary.regression_count == 0
    assert report.summary.infrastructure_error_count == 1
    assert report.pairs[0].classification == "infrastructure_error"


async def test_terminal_recovery_attempt_overlays_infrastructure_failure_with_lineage() -> None:
    baseline = _detail(
        "baseline",
        EvaluationOutcome.PASS,
        duration_seconds=1,
        input_tokens=10,
        output_tokens=5,
    )
    candidate = _detail(
        "candidate",
        EvaluationOutcome.FAIL,
        duration_seconds=2,
        input_tokens=12,
        output_tokens=8,
    )
    candidate = candidate.model_copy(
        update={
            "status": CaseRunStatus.FAILED,
            "evaluation_state": EvaluationOutcome.EVALUATION_ERROR,
            "error_code": "target_unreachable",
            "error_message": "connection failed",
            "evaluations": [
                candidate.evaluations[0].model_copy(
                    update={"status": EvaluationRecordStatus.ERROR, "verdict": None}
                )
            ],
        }
    )
    recovery_run = _run().model_copy(
        update={
            "id": "run_recovery",
            "recovery_of_run_id": "run_ab",
            "recovery_reason": "retry target connection",
            "resolved_case_ids": ["case_release"],
            "target_snapshots": [{"id": "target_candidate"}],
            "total_count": 1,
            "completed_count": 1,
            "created_at": NOW + timedelta(minutes=1),
            "started_at": NOW + timedelta(minutes=1),
            "finished_at": NOW + timedelta(minutes=1, seconds=1),
        }
    )
    recovered = _detail(
        "candidate",
        EvaluationOutcome.PASS,
        duration_seconds=1,
        input_tokens=11,
        output_tokens=6,
    )
    recovered_events = [
        event.model_copy(
            update={
                "id": f"{event.id}_recovery",
                "case_run_id": "cr_candidate_recovery",
            }
        )
        for event in recovered.events
    ]
    recovered = recovered.model_copy(
        update={
            "id": "cr_candidate_recovery",
            "run_id": recovery_run.id,
            "attempt_id": "attempt_candidate_recovery",
            "recovery_of_case_run_id": candidate.id,
            "started_at": recovery_run.started_at,
            "finished_at": recovery_run.finished_at,
            "events": recovered_events,
            "evaluations": [
                recovered.evaluations[0].model_copy(
                    update={
                        "id": "eval_candidate_recovery",
                        "case_run_id": "cr_candidate_recovery",
                        "evidence_refs": ["evt_candidate_driver_recovery"],
                    }
                )
            ],
        }
    )
    service = _service(
        details=[baseline, candidate],
        recovery_runs=[recovery_run],
        recovery_details=[recovered],
    )

    quality = await service.quality_report("run_ab")
    comparison = await service.comparison_report("run_ab")

    assert quality.outcomes.pass_count == 2
    assert quality.outcomes.execution_failed_count == 0
    assert quality.recovery is not None
    assert quality.recovery.recovery_run_ids == ["run_recovery"]
    assert quality.recovery.applied_recovery_run_ids == ["run_recovery"]
    assert quality.recovery.superseded_attempt_ids == [candidate.id]
    assert quality.recovery.replaced_attempt_count == 1
    assert comparison.summary.infrastructure_error_count == 0
    assert comparison.summary.unchanged_pass_count == 1
    assert comparison.recovery == quality.recovery


async def test_evidence_quality_distinguishes_foreign_and_missing_references() -> None:
    baseline = _detail(
        "baseline",
        EvaluationOutcome.PASS,
        duration_seconds=1,
        input_tokens=10,
        output_tokens=5,
    )
    candidate = _detail(
        "candidate",
        EvaluationOutcome.FAIL,
        duration_seconds=2,
        input_tokens=12,
        output_tokens=8,
    )
    candidate = candidate.model_copy(
        update={
            "evaluations": [
                candidate.evaluations[0].model_copy(
                    update={
                        "evidence_refs": ["evt_baseline_driver", "evt_does_not_exist"]
                    }
                )
            ]
        }
    )

    quality = await _service(details=[baseline, candidate]).quality_report("run_ab")

    assert quality.evidence_quality.valid_reference_count == 1
    assert quality.evidence_quality.foreign_reference_count == 1
    assert quality.evidence_quality.missing_reference_count == 1
    assert quality.evidence_quality.reference_validity_rate == pytest.approx(1 / 3)


async def test_usage_aggregation_keeps_complete_totals_but_rejects_partial_dimensions() -> None:
    baseline = _detail(
        "baseline",
        EvaluationOutcome.PASS,
        duration_seconds=1,
        input_tokens=10,
        output_tokens=5,
    )
    candidate = _detail(
        "candidate",
        EvaluationOutcome.PASS,
        duration_seconds=1,
        input_tokens=12,
        output_tokens=8,
    )
    candidate_events = list(candidate.events)
    candidate_events[1] = candidate_events[1].model_copy(
        update={"payload": {"total_tokens": 20}}
    )
    candidate = candidate.model_copy(update={"events": candidate_events})

    quality = await _service(details=[baseline, candidate]).quality_report("run_ab")

    assert quality.usage.total_tokens == 35
    assert quality.usage.input_tokens is None
    assert quality.usage.output_tokens is None
    assert "input_tokens" in quality.usage.missing_fields
    assert "output_tokens" in quality.usage.missing_fields


async def test_quality_and_comparison_require_terminal_ab_run() -> None:
    running = _service(run=_run(RunStatus.RUNNING))
    with pytest.raises(AgentRigError) as exc:
        await running.quality_report("run_ab")
    assert exc.value.detail.code is ErrorCode.CONFLICT

    non_ab_detail = _detail(
        "candidate",
        EvaluationOutcome.PASS,
        duration_seconds=1,
        input_tokens=1,
        output_tokens=1,
    ).model_copy(
        update={"comparison_pair_id": None, "comparison_role": "candidate"}
    )
    non_ab = _service(details=[non_ab_detail])
    with pytest.raises(AgentRigError) as non_ab_exc:
        await non_ab.comparison_report("run_ab")
    assert non_ab_exc.value.detail.code is ErrorCode.VALIDATION_ERROR


async def test_release_gate_prioritizes_fail_inconclusive_and_warn_deterministically() -> None:
    service = _service()
    quality = await service.quality_report("run_ab")
    comparison = await service.comparison_report("run_ab")
    policy = ReleasePolicy(
        name="test",
        warnings={
            "max_duration_regression_ratio": 0.5,
            "max_token_regression_ratio": 0.2,
        },
        minimum_samples={"comparable_pairs": 1, "latency": 1, "token": 1},
    )

    failed = evaluate_release_gate(quality, comparison, policy, generated_at=NOW)
    failed_later = evaluate_release_gate(
        quality,
        comparison,
        policy,
        generated_at=NOW + timedelta(days=1),
    )
    assert failed.verdict == "fail"
    assert failed.result_hash == failed_later.result_hash
    assert next(item for item in failed.checks if item.name == "outcome_regressions").outcome == "fail"

    passing_comparison = comparison.model_copy(
        update={
            "summary": comparison.summary.model_copy(
                update={
                    "regression_count": 0,
                    "unchanged_pass_count": 1,
                }
            ),
            "pairs": [
                comparison.pairs[0].model_copy(update={"classification": "unchanged_pass"})
            ],
        }
    )
    warned = evaluate_release_gate(quality, passing_comparison, policy)
    assert warned.verdict == "warn"

    no_reference_quality = quality.model_copy(
        update={
            "evidence_quality": quality.evidence_quality.model_copy(
                update={"reference_validity_rate": None}
            )
        }
    )
    inconclusive = evaluate_release_gate(
        no_reference_quality,
        passing_comparison,
        policy,
    )
    assert inconclusive.verdict == "inconclusive"

    insufficient_comparison = passing_comparison.model_copy(
        update={
            "summary": passing_comparison.summary.model_copy(
                update={"comparable_pairs": 0, "changed_inconclusive_count": 1}
            ),
            "pairs": [
                passing_comparison.pairs[0].model_copy(
                    update={"classification": "changed_inconclusive"}
                )
            ],
        }
    )
    insufficient = evaluate_release_gate(quality, insufficient_comparison, policy)
    minimum_check = next(
        item for item in insufficient.checks if item.name == "minimum_comparable_pairs"
    )
    assert minimum_check.outcome == "inconclusive"
    assert insufficient.verdict == "inconclusive"


def test_release_policy_rejects_unknown_or_out_of_range_fields() -> None:
    with pytest.raises(ValueError):
        ReleasePolicy.model_validate({"name": "bad", "unknown": True})
    with pytest.raises(ValueError):
        ReleasePolicy.model_validate(
            {
                "name": "bad",
                "blocking": {"min_evidence_reference_validity": 1.1},
            }
        )


def test_repository_default_release_policy_matches_the_stable_contract() -> None:
    policy = ReleasePolicy.model_validate_json(
        Path("configs/release-policies/default-agent-release.json").read_text(
            encoding="utf-8"
        )
    )
    assert policy.name == "default-agent-release"
    assert policy.blocking.max_outcome_regressions == 0
