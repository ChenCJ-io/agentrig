"""Pure aggregation for QualityReport and ComparisonReport."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from ..agents.invocation_models import AgentInvocationStatus
from ..agents.invocation_schemas import AgentInvocationView
from ..assistant.decision_models import DecisionActionType, DecisionStatus
from ..assistant.decision_schemas import DecisionRecordView
from ..capabilities import CapabilityComparison, compare_capabilities
from ..evaluations.models import EvaluationOutcome, EvaluationRecordStatus
from ..runs.models import CaseRunStatus, RunEventType
from ..runs.schemas import CaseRunDetail, RunView
from .canonical import canonical_hash
from .schemas import (
    CapabilityComparisonDisplay,
    ComparisonAggregateMetrics,
    ComparisonClassification,
    ComparisonPair,
    ComparisonReport,
    ComparisonSide,
    ComparisonSummary,
    LatencyDistribution,
    MetricDelta,
    QualityCollaborationMetrics,
    QualityDecisionMetrics,
    QualityEvidenceMetrics,
    QualityInvocationMetrics,
    QualityLatencyMetrics,
    QualityOutcomeCounts,
    QualityReliabilityMetrics,
    QualityReport,
    QualityScope,
    QualityUsageMetrics,
    RecoveryProvenance,
)

_INFRASTRUCTURE_STATUSES = {
    CaseRunStatus.FAILED,
    CaseRunStatus.CANCELLED,
    CaseRunStatus.INTERRUPTED,
}


def report_source_snapshot(
    run: RunView,
    case_runs: Sequence[CaseRunDetail],
    decisions: Sequence[DecisionRecordView],
    invocations: Sequence[AgentInvocationView],
    recovery_runs: Sequence[RunView] = (),
) -> dict[str, Any]:
    return {
        "run": run.model_dump(mode="json"),
        "case_runs": [
            _case_run_snapshot(item)
            for item in sorted(case_runs, key=lambda item: item.id)
        ],
        "decisions": [
            item.model_dump(mode="json") for item in sorted(decisions, key=lambda item: item.id)
        ],
        "invocations": [
            item.model_dump(mode="json")
            for item in sorted(invocations, key=lambda item: item.id)
        ],
        "recovery_runs": [
            item.model_dump(mode="json")
            for item in sorted(recovery_runs, key=lambda item: item.id)
        ],
    }


def _case_run_snapshot(item: CaseRunDetail) -> dict[str, Any]:
    value = item.model_dump(mode="json")
    value["events"] = [
        event.model_dump(mode="json")
        for event in sorted(item.events, key=lambda event: (event.seq, event.id))
    ]
    value["evaluations"] = [
        evaluation.model_dump(mode="json")
        for evaluation in sorted(
            item.evaluations,
            key=lambda evaluation: (evaluation.evaluator_type.value, evaluation.id),
        )
    ]
    return value


def source_snapshot_hash(
    run: RunView,
    case_runs: Sequence[CaseRunDetail],
    decisions: Sequence[DecisionRecordView],
    invocations: Sequence[AgentInvocationView],
    recovery_runs: Sequence[RunView] = (),
) -> str:
    return canonical_hash(
        report_source_snapshot(
            run,
            case_runs,
            decisions,
            invocations,
            recovery_runs,
        )
    )


def build_quality_report(
    run: RunView,
    case_runs: Sequence[CaseRunDetail],
    decisions: Sequence[DecisionRecordView] = (),
    invocations: Sequence[AgentInvocationView] = (),
    recovery_runs: Sequence[RunView] = (),
    recovery: RecoveryProvenance | None = None,
    *,
    generated_at: datetime | None = None,
) -> QualityReport:
    outcomes = Counter(item.evaluation_state for item in case_runs)
    statuses = Counter(item.status for item in case_runs)
    all_events = [event for item in case_runs for event in item.events]
    driver_events = [
        event
        for event in all_events
        if event.event_type is RunEventType.DRIVER_REQUEST
        and event.payload.get("phase") == "completed"
    ]
    usage_events = [
        event for event in all_events if event.event_type is RunEventType.USAGE
    ]
    provider_events = [
        event
        for event in all_events
        if event.event_type is RunEventType.PROVIDER_ATTEMPT
    ]
    usage = _usage_metrics(event.payload for event in usage_events)
    evidence = _evidence_metrics(case_runs)
    limitations: list[str] = []
    if usage.usage_event_count == 0:
        limitations.append("usage_not_observed")
    if usage.estimated_cost is None:
        limitations.append("cost_not_available_without_pricing_snapshot")
    if not decisions:
        limitations.append("decision_records_not_observed")
    if not invocations:
        limitations.append("agent_invocations_not_observed")
    return QualityReport(
        generated_at=generated_at or datetime.now(timezone.utc),
        run_id=run.id,
        run_status=run.status,
        source_snapshot_hash=source_snapshot_hash(
            run,
            case_runs,
            decisions,
            invocations,
            recovery_runs,
        ),
        scope=QualityScope(
            resolved_case_ids=sorted(run.resolved_case_ids),
            target_ids=sorted(
                {
                    str(item.target_snapshot.get("id") or "inline_target")
                    for item in case_runs
                }
            ),
            case_run_count=len(case_runs),
        ),
        outcomes=QualityOutcomeCounts(
            total=len(case_runs),
            pass_count=outcomes[EvaluationOutcome.PASS],
            fail_count=outcomes[EvaluationOutcome.FAIL],
            inconclusive_count=outcomes[EvaluationOutcome.INCONCLUSIVE],
            awaiting_verdict_count=outcomes[EvaluationOutcome.AWAITING_VERDICT],
            evaluation_error_count=outcomes[EvaluationOutcome.EVALUATION_ERROR],
            skipped_count=statuses[CaseRunStatus.SKIPPED],
            cancelled_count=statuses[CaseRunStatus.CANCELLED],
            interrupted_count=statuses[CaseRunStatus.INTERRUPTED],
            execution_failed_count=statuses[CaseRunStatus.FAILED],
        ),
        latency=QualityLatencyMetrics(
            run_duration_ms=_duration_ms(run.started_at, run.finished_at),
            case_run=_distribution(
                _duration_ms(item.started_at, item.finished_at) for item in case_runs
            ),
            driver_request=_distribution(
                _non_negative_float(event.payload.get("duration_ms"))
                for event in driver_events
            ),
            ttft=_distribution(
                _non_negative_float(event.payload.get("ttft_ms"))
                for event in driver_events
            ),
        ),
        usage=usage,
        reliability=_reliability_metrics(case_runs, driver_events, provider_events),
        collaboration=QualityCollaborationMetrics(
            decisions=_decision_metrics(decisions),
            invocations=_invocation_metrics(invocations),
        ),
        evidence_quality=evidence,
        recovery=recovery,
        limitations=sorted(set(limitations)),
    )


def build_comparison_report(
    run: RunView,
    case_runs: Sequence[CaseRunDetail],
    decisions: Sequence[DecisionRecordView] = (),
    invocations: Sequence[AgentInvocationView] = (),
    recovery_runs: Sequence[RunView] = (),
    recovery: RecoveryProvenance | None = None,
    *,
    generated_at: datetime | None = None,
) -> ComparisonReport:
    grouped: dict[str, list[CaseRunDetail]] = defaultdict(list)
    for item in case_runs:
        pair_id = item.comparison_pair_id or f"missing_pair:{item.id}"
        grouped[pair_id].append(item)
    pairs = [_comparison_pair(pair_id, grouped[pair_id]) for pair_id in sorted(grouped)]
    classifications = Counter(item.classification for item in pairs)
    comparable = [
        item
        for item in pairs
        if item.classification
        in {"unchanged_pass", "unchanged_fail", "regression", "fix"}
    ]
    duration_values = [
        (item.baseline.duration_ms, item.candidate.duration_ms)
        for item in comparable
        if item.baseline is not None
        and item.candidate is not None
        and item.baseline.duration_ms is not None
        and item.candidate.duration_ms is not None
    ]
    token_values = [
        (item.baseline.total_tokens, item.candidate.total_tokens)
        for item in comparable
        if item.baseline is not None
        and item.candidate is not None
        and item.baseline.total_tokens is not None
        and item.candidate.total_tokens is not None
    ]
    limitations = (
        ["capability_snapshot_not_available"]
        if any(item.capability_comparison == "not_available" for item in pairs)
        else []
    )
    return ComparisonReport(
        generated_at=generated_at or datetime.now(timezone.utc),
        run_id=run.id,
        source_snapshot_hash=source_snapshot_hash(
            run,
            case_runs,
            decisions,
            invocations,
            recovery_runs,
        ),
        summary=ComparisonSummary(
            total_pairs=len(pairs),
            comparable_pairs=len(comparable),
            regression_count=classifications["regression"],
            fix_count=classifications["fix"],
            unchanged_pass_count=classifications["unchanged_pass"],
            unchanged_fail_count=classifications["unchanged_fail"],
            changed_inconclusive_count=classifications["changed_inconclusive"],
            infrastructure_error_count=classifications["infrastructure_error"],
            incomplete_pair_count=classifications["incomplete_pair"],
            incomparable_environment_count=classifications[
                "incomparable_environment"
            ],
        ),
        metrics=ComparisonAggregateMetrics(
            duration_sample_count=len(duration_values),
            duration_regression_ratio=_aggregate_ratio(duration_values),
            token_sample_count=len(token_values),
            token_regression_ratio=_aggregate_ratio(token_values),
        ),
        pairs=pairs,
        recovery=recovery,
        limitations=limitations,
    )


def _comparison_pair(pair_id: str, items: Sequence[CaseRunDetail]) -> ComparisonPair:
    baselines = sorted(
        (item for item in items if item.comparison_role == "baseline"),
        key=lambda item: item.id,
    )
    candidates = sorted(
        (item for item in items if item.comparison_role == "candidate"),
        key=lambda item: item.id,
    )
    baseline = baselines[0] if len(baselines) == 1 else None
    candidate = candidates[0] if len(candidates) == 1 else None
    baseline_side = _comparison_side(baseline) if baseline is not None else None
    candidate_side = _comparison_side(candidate) if candidate is not None else None
    classification = _classification(baseline, candidate)
    reference = baseline or candidate or items[0]
    capability_diff = compare_capabilities(
        baseline.capability_snapshot if baseline is not None else None,
        candidate.capability_snapshot if candidate is not None else None,
    )
    capability_labels: dict[CapabilityComparison, CapabilityComparisonDisplay] = {
        "comparable": "comparable",
        "warning_difference": "warning_difference",
        "incomparable_environment": "incomparable",
        "unknown": "unknown",
    }
    capability_comparison = capability_labels[capability_diff.comparison]
    limitations = list(capability_diff.limitations)
    if baseline is None or candidate is None:
        capability_comparison = "not_available"
    elif baseline.capability_snapshot is None or candidate.capability_snapshot is None:
        # Historical CaseRuns remain reportable without reconstructing current
        # capabilities.  The explicit not_available signal lets a Gate choose
        # inconclusive while preserving the original product outcome class.
        capability_comparison = "not_available"
    elif capability_diff.comparison == "incomparable_environment":
        classification = "incomparable_environment"
    if len(baselines) != 1 or len(candidates) != 1:
        limitations.append("pair_requires_exactly_one_baseline_and_candidate")
    return ComparisonPair(
        comparison_pair_id=pair_id,
        case_id=reference.case_id,
        repeat_index=reference.repeat_index,
        classification=classification,
        baseline=baseline_side,
        candidate=candidate_side,
        duration_delta=_metric_delta(
            baseline_side.duration_ms if baseline_side is not None else None,
            candidate_side.duration_ms if candidate_side is not None else None,
        ),
        token_delta=_metric_delta(
            float(baseline_side.total_tokens)
            if baseline_side is not None and baseline_side.total_tokens is not None
            else None,
            float(candidate_side.total_tokens)
            if candidate_side is not None and candidate_side.total_tokens is not None
            else None,
        ),
        capability_comparison=capability_comparison,
        capability_diff=capability_diff,
        limitations=limitations,
    )


def _classification(
    baseline: CaseRunDetail | None,
    candidate: CaseRunDetail | None,
) -> ComparisonClassification:
    if baseline is None or candidate is None:
        return "incomplete_pair"
    if baseline.status is CaseRunStatus.SKIPPED or candidate.status is CaseRunStatus.SKIPPED:
        return "incomplete_pair"
    if (
        baseline.status in _INFRASTRUCTURE_STATUSES
        or candidate.status in _INFRASTRUCTURE_STATUSES
        or baseline.error_code is not None
        or candidate.error_code is not None
    ):
        return "infrastructure_error"
    outcomes = (baseline.evaluation_state, candidate.evaluation_state)
    if outcomes == (EvaluationOutcome.PASS, EvaluationOutcome.PASS):
        return "unchanged_pass"
    if outcomes == (EvaluationOutcome.FAIL, EvaluationOutcome.FAIL):
        return "unchanged_fail"
    if outcomes == (EvaluationOutcome.PASS, EvaluationOutcome.FAIL):
        return "regression"
    if outcomes == (EvaluationOutcome.FAIL, EvaluationOutcome.PASS):
        return "fix"
    return "changed_inconclusive"


def _comparison_side(item: CaseRunDetail) -> ComparisonSide:
    evidence_refs: list[str] = []
    for evaluation in item.evaluations:
        if evaluation.evaluator_type is item.primary_evaluator:
            evidence_refs = list(evaluation.evidence_refs)
            break
    usage = _usage_metrics(
        event.payload for event in item.events if event.event_type is RunEventType.USAGE
    )
    return ComparisonSide(
        case_run_id=item.id,
        target_id=str(item.target_snapshot.get("id") or "inline_target"),
        version=item.version,
        status=item.status,
        outcome=item.evaluation_state,
        evidence_refs=evidence_refs,
        duration_ms=_duration_ms(item.started_at, item.finished_at),
        total_tokens=usage.total_tokens,
    )


def _usage_metrics(payloads: Iterable[dict[str, Any]]) -> QualityUsageMetrics:
    items = list(payloads)
    per_event: list[dict[str, int | None]] = []
    for payload in items:
        aliases = {
            "input_tokens": ("input_tokens", "inputTokens", "prompt_tokens", "promptTokens"),
            "output_tokens": (
                "output_tokens",
                "outputTokens",
                "completion_tokens",
                "completionTokens",
            ),
            "total_tokens": ("total_tokens", "totalTokens"),
            "cached_input_tokens": ("cached_input_tokens", "cachedInputTokens"),
            "reasoning_tokens": ("reasoning_tokens", "reasoningTokens"),
        }
        resolved_event = {
            field: _first_non_negative_int(payload, candidates)
            for field, candidates in aliases.items()
        }
        prompt_details = payload.get("prompt_tokens_details")
        if isinstance(prompt_details, dict):
            cached = _first_non_negative_int(prompt_details, ("cached_tokens",))
            if cached is not None and not any(
                key in payload for key in ("cached_input_tokens", "cachedInputTokens")
            ):
                resolved_event["cached_input_tokens"] = cached
        completion_details = payload.get("completion_tokens_details")
        if isinstance(completion_details, dict):
            reasoning = _first_non_negative_int(completion_details, ("reasoning_tokens",))
            if reasoning is not None and not any(
                key in payload for key in ("reasoning_tokens", "reasoningTokens")
            ):
                resolved_event["reasoning_tokens"] = reasoning
        input_value = resolved_event["input_tokens"]
        output_value = resolved_event["output_tokens"]
        if (
            resolved_event["total_tokens"] is None
            and input_value is not None
            and output_value is not None
        ):
            resolved_event["total_tokens"] = input_value + output_value
        per_event.append(resolved_event)
    fields = (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
    )
    resolved: dict[str, int | None] = {
        field: _complete_sum(item[field] for item in per_event) for field in fields
    }
    cost = _complete_cost(items)
    return QualityUsageMetrics(
        usage_event_count=len(items),
        input_tokens=resolved["input_tokens"],
        output_tokens=resolved["output_tokens"],
        total_tokens=resolved["total_tokens"],
        cached_input_tokens=resolved["cached_input_tokens"],
        reasoning_tokens=resolved["reasoning_tokens"],
        estimated_cost=cost["amount"] if cost is not None else None,
        currency=cost["currency"] if cost is not None else None,
        cost_kind=cost["kind"] if cost is not None else None,
        pricing_source=cost["pricing_source"] if cost is not None else None,
        pricing_effective_at=(
            cost["pricing_effective_at"] if cost is not None else None
        ),
        pricing_snapshot_hash=(
            cost["pricing_snapshot_hash"] if cost is not None else None
        ),
        missing_fields=[field for field in fields if resolved[field] is None],
    )


def _complete_cost(items: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not items:
        return None
    costs: list[dict[str, Any]] = []
    for item in items:
        value = item.get("cost")
        if not isinstance(value, dict):
            return None
        required = {
            "amount",
            "currency",
            "kind",
            "pricing_source",
            "pricing_effective_at",
            "pricing_snapshot_hash",
        }
        if not required.issubset(value):
            return None
        try:
            amount = Decimal(str(value["amount"]))
            effective_at = datetime.fromisoformat(str(value["pricing_effective_at"]))
        except (InvalidOperation, ValueError):
            return None
        if not amount.is_finite() or amount < 0 or effective_at.tzinfo is None:
            return None
        costs.append({**value, "amount": amount, "pricing_effective_at": effective_at})
    identity_fields = (
        "currency",
        "kind",
        "pricing_source",
        "pricing_effective_at",
        "pricing_snapshot_hash",
    )
    if any(
        any(item[field] != costs[0][field] for field in identity_fields)
        for item in costs[1:]
    ):
        return None
    return {
        **costs[0],
        "amount": _decimal_text(sum((item["amount"] for item in costs), Decimal(0))),
    }


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


def _reliability_metrics(
    case_runs: Sequence[CaseRunDetail],
    driver_events: Sequence[Any],
    provider_events: Sequence[Any],
) -> QualityReliabilityMetrics:
    grouped: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    provider_error_count = 0
    for event in provider_events:
        tool_call_id = str(event.payload.get("tool_call_id") or event.id)
        status = str(event.payload.get("status") or "unknown")
        grouped[(event.case_run_id, tool_call_id)].append((event.seq, status))
        provider_error_count += status == "error"
    ordered_groups = [
        [status for _, status in sorted(statuses)] for statuses in grouped.values()
    ]
    recoverable = [statuses for statuses in ordered_groups if len(statuses) > 1]
    recovered = [statuses for statuses in recoverable if statuses[-1] == "hit"]
    error_codes: Counter[str] = Counter()
    for item in case_runs:
        if item.error_code:
            error_codes[item.error_code] += 1
        for event in item.events:
            if event.event_type is RunEventType.ERROR:
                code = str(event.payload.get("code") or "unknown_error")
                error_codes[code] += 1
    timeout_count = sum(
        count for code, count in error_codes.items() if "timeout" in code.lower()
    )
    return QualityReliabilityMetrics(
        driver_request_count=len(driver_events),
        provider_attempt_count=len(provider_events),
        fallback_attempt_count=sum(
            max(0, len(value) - 1) for value in ordered_groups
        ),
        provider_error_count=provider_error_count,
        recoverable_group_count=len(recoverable),
        recovered_group_count=len(recovered),
        recovery_success_rate=(len(recovered) / len(recoverable) if recoverable else None),
        timeout_count=timeout_count,
        error_codes=dict(sorted(error_codes.items())),
    )


def _evidence_metrics(case_runs: Sequence[CaseRunDetail]) -> QualityEvidenceMetrics:
    all_event_ids = {event.id for item in case_runs for event in item.events}
    evaluation_count = 0
    evaluation_error_count = 0
    evaluations_without_references = 0
    valid = 0
    foreign = 0
    missing = 0
    for item in case_runs:
        own_event_ids = {event.id for event in item.events}
        for evaluation in item.evaluations:
            evaluation_count += 1
            evaluation_error_count += evaluation.status is EvaluationRecordStatus.ERROR
            evaluations_without_references += not evaluation.evidence_refs
            for reference in evaluation.evidence_refs:
                if reference in own_event_ids:
                    valid += 1
                elif reference in all_event_ids:
                    foreign += 1
                else:
                    missing += 1
    total = valid + foreign + missing
    return QualityEvidenceMetrics(
        evaluation_count=evaluation_count,
        evaluation_error_count=evaluation_error_count,
        evaluations_without_references=evaluations_without_references,
        reference_count=total,
        valid_reference_count=valid,
        foreign_reference_count=foreign,
        missing_reference_count=missing,
        reference_validity_rate=(valid / total if total else None),
    )


def _decision_metrics(decisions: Sequence[DecisionRecordView]) -> QualityDecisionMetrics:
    terminal = [item for item in decisions if item.status.terminal]
    succeeded = [item for item in decisions if item.status is DecisionStatus.SUCCEEDED]
    failed = [item for item in decisions if item.status is DecisionStatus.FAILED]
    provenance_candidates = [
        item
        for item in succeeded
        if item.selected_action.action_type
        not in {
            DecisionActionType.ASK_USER,
            DecisionActionType.NO_ACTION,
            DecisionActionType.REQUEST_PLAN_CONFIRMATION,
        }
    ]
    linked = [item for item in provenance_candidates if item.action_ref_id is not None]
    return QualityDecisionMetrics(
        total=len(decisions),
        terminal=len(terminal),
        succeeded=len(succeeded),
        failed=len(failed),
        provenance_candidates=len(provenance_candidates),
        provenance_linked=len(linked),
        provenance_link_rate=(
            len(linked) / len(provenance_candidates) if provenance_candidates else None
        ),
    )


def _invocation_metrics(
    invocations: Sequence[AgentInvocationView],
) -> QualityInvocationMetrics:
    statuses = Counter(item.status for item in invocations)
    return QualityInvocationMetrics(
        total=len(invocations),
        completed=statuses[AgentInvocationStatus.COMPLETED],
        failed=statuses[AgentInvocationStatus.FAILED],
        timed_out=statuses[AgentInvocationStatus.TIMED_OUT],
        cancelled=statuses[AgentInvocationStatus.CANCELLED],
        duration=_distribution(
            _duration_ms(item.started_at, item.finished_at) for item in invocations
        ),
    )


def _distribution(values: Iterable[float | None]) -> LatencyDistribution:
    resolved = sorted(value for value in values if value is not None)
    if not resolved:
        return LatencyDistribution(count=0)
    return LatencyDistribution(
        count=len(resolved),
        minimum_ms=_rounded(resolved[0]),
        p50_ms=_rounded(_nearest_rank(resolved, 0.50)),
        p95_ms=_rounded(_nearest_rank(resolved, 0.95)),
        maximum_ms=_rounded(resolved[-1]),
    )


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    index = max(0, math.ceil(percentile * len(values)) - 1)
    return values[index]


def _duration_ms(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    if started_at is None or finished_at is None:
        return None
    return max(0.0, (finished_at - started_at).total_seconds() * 1_000)


def _metric_delta(baseline: float | None, candidate: float | None) -> MetricDelta:
    if baseline is None or candidate is None:
        return MetricDelta(baseline=baseline, candidate=candidate)
    absolute = candidate - baseline
    return MetricDelta(
        baseline=_rounded(baseline),
        candidate=_rounded(candidate),
        absolute=_rounded(absolute),
        ratio=_rounded(absolute / baseline) if baseline > 0 else None,
    )


def _aggregate_ratio(values: Sequence[tuple[float | int, float | int]]) -> float | None:
    if not values:
        return None
    baseline = float(sum(item[0] for item in values))
    candidate = float(sum(item[1] for item in values))
    if baseline <= 0:
        return None
    return _rounded((candidate - baseline) / baseline)


def _first_non_negative_int(
    payload: dict[str, Any],
    keys: Sequence[str],
) -> int | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, float) and value >= 0 and value.is_integer():
            return int(value)
    return None


def _complete_sum(values: Iterable[int | None]) -> int | None:
    resolved = list(values)
    if not resolved or any(value is None for value in resolved):
        return None
    return sum(value for value in resolved if value is not None)


def _non_negative_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result) or result < 0:
        return None
    return result


def _rounded(value: float) -> float:
    return round(value, 6)
