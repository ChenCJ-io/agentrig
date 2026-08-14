"""Pure release-gate checks plus the application service that loads run reports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from ..canonical import canonical_hash
from ..errors import AgentRigError, ErrorCode
from ..reporting.schemas import ComparisonReport, QualityReport
from ..reporting.service import RenderedDocument, ReportingService
from .schemas import ReleaseGateCheck, ReleaseGateResult, ReleasePolicy


class ReleaseGateService:
    def __init__(self, reporting: ReportingService) -> None:
        self._reporting = reporting

    async def evaluate(
        self,
        run_id: str,
        policy: ReleasePolicy,
    ) -> ReleaseGateResult:
        quality = await self._reporting.quality_report(run_id)
        comparison = await self._reporting.comparison_report(run_id)
        if quality.source_snapshot_hash != comparison.source_snapshot_hash:
            raise AgentRigError(
                ErrorCode.CONFLICT,
                "run evidence changed while evaluating the release gate; retry the request",
                details={"run_id": run_id},
                retryable=True,
            )
        return evaluate_release_gate(quality, comparison, policy)

    @staticmethod
    def render_markdown(result: ReleaseGateResult) -> RenderedDocument:
        checks = [
            (
                f"- **{item.outcome}** `{_markdown(item.name)}` — "
                f"{_markdown(item.message)} "
                f"(actual={item.actual}, threshold={item.threshold})"
            )
            for item in result.checks
        ]
        return RenderedDocument(
            content="\n".join(
                [
                    "# AgentRig Release Gate",
                    "",
                    f"- 运行编号：`{_markdown(result.run_id)}`",
                    f"- 结论：**{result.verdict}**",
                    (
                        f"- 策略：`{_markdown(result.policy_name)}@"
                        f"{_markdown(result.policy_version)}`"
                    ),
                    f"- 策略哈希：`{result.policy_hash}`",
                    f"- 来源快照：`{result.source_snapshot_hash}`",
                    f"- 结果哈希：`{result.result_hash}`",
                    "",
                    "## Checks",
                    "",
                    *checks,
                ]
            ),
            media_type="text/markdown; charset=utf-8",
            filename=f"agentrig-{_safe_filename(result.run_id)}-release-gate.md",
        )


def evaluate_release_gate(
    quality: QualityReport,
    comparison: ComparisonReport,
    policy: ReleasePolicy,
    *,
    generated_at: datetime | None = None,
) -> ReleaseGateResult:
    if quality.run_id != comparison.run_id:
        raise AgentRigError(
            ErrorCode.VALIDATION_ERROR,
            "quality and comparison reports must belong to the same run",
        )
    if quality.source_snapshot_hash != comparison.source_snapshot_hash:
        raise AgentRigError(
            ErrorCode.CONFLICT,
            "quality and comparison reports use different source snapshots",
            retryable=True,
        )
    checks = [
        _minimum_sample_check(
            "minimum_comparable_pairs",
            comparison.summary.comparable_pairs,
            policy.minimum_samples.comparable_pairs,
            refs=[item.comparison_pair_id for item in comparison.pairs],
        ),
        _maximum_check(
            "outcome_regressions",
            comparison.summary.regression_count,
            policy.blocking.max_outcome_regressions,
            refs=_pair_refs(comparison, "regression"),
        ),
        _maximum_check(
            "infrastructure_errors",
            comparison.summary.infrastructure_error_count,
            policy.blocking.max_infrastructure_errors,
            refs=_pair_refs(comparison, "infrastructure_error"),
        ),
        _maximum_check(
            "incomplete_pairs",
            comparison.summary.incomplete_pair_count,
            policy.blocking.max_incomplete_pairs,
            refs=_pair_refs(comparison, "incomplete_pair"),
        ),
        _maximum_check(
            "incomparable_environment_pairs",
            comparison.summary.incomparable_environment_count,
            policy.blocking.max_incomparable_environment_pairs,
            refs=_pair_refs(comparison, "incomparable_environment"),
        ),
        _minimum_check(
            "evidence_reference_validity",
            quality.evidence_quality.reference_validity_rate,
            policy.blocking.min_evidence_reference_validity,
            refs=[],
        ),
        _warning_maximum_check(
            "duration_regression_ratio",
            comparison.metrics.duration_regression_ratio,
            policy.warnings.max_duration_regression_ratio,
            sample_count=comparison.metrics.duration_sample_count,
            minimum_samples=policy.minimum_samples.latency,
            refs=[
                item.comparison_pair_id
                for item in comparison.pairs
                if item.duration_delta.ratio is not None
            ],
        ),
        _warning_maximum_check(
            "token_regression_ratio",
            comparison.metrics.token_regression_ratio,
            policy.warnings.max_token_regression_ratio,
            sample_count=comparison.metrics.token_sample_count,
            minimum_samples=policy.minimum_samples.token,
            refs=[
                item.comparison_pair_id
                for item in comparison.pairs
                if item.token_delta.ratio is not None
            ],
        ),
    ]
    verdict = _gate_verdict(checks)
    policy_hash = canonical_hash(policy)
    stable_result = {
        "schema_version": "agentrig.release-gate.v1",
        "run_id": quality.run_id,
        "verdict": verdict,
        "policy_name": policy.name,
        "policy_version": policy.policy_version,
        "policy_hash": policy_hash,
        "source_snapshot_hash": quality.source_snapshot_hash,
        "checks": [
            item.model_dump(mode="json", exclude={"message"}) for item in checks
        ],
    }
    return ReleaseGateResult(
        generated_at=generated_at or datetime.now(timezone.utc),
        run_id=quality.run_id,
        verdict=verdict,
        policy_name=policy.name,
        policy_version=policy.policy_version,
        policy_hash=policy_hash,
        source_snapshot_hash=quality.source_snapshot_hash,
        result_hash=canonical_hash(stable_result),
        checks=checks,
    )


def _maximum_check(
    name: str,
    actual: int | float | None,
    threshold: int | float,
    *,
    refs: list[str],
) -> ReleaseGateCheck:
    return _check(name, "blocking", "lte", actual, threshold, refs=refs)


def _minimum_check(
    name: str,
    actual: int | float | None,
    threshold: int | float,
    *,
    refs: list[str],
) -> ReleaseGateCheck:
    return _check(name, "blocking", "gte", actual, threshold, refs=refs)


def _minimum_sample_check(
    name: str,
    actual: int,
    threshold: int,
    *,
    refs: list[str],
) -> ReleaseGateCheck:
    if actual >= threshold:
        outcome: Literal["pass", "inconclusive"] = "pass"
        message = "minimum sample requirement satisfied"
    else:
        outcome = "inconclusive"
        message = f"observed only: {actual} samples, {threshold} required"
    return ReleaseGateCheck(
        name=name,
        severity="blocking",
        operator="gte",
        actual=actual,
        threshold=threshold,
        outcome=outcome,
        message=message,
        evidence_refs=refs,
    )


def _warning_maximum_check(
    name: str,
    actual: float | None,
    threshold: float,
    *,
    sample_count: int,
    minimum_samples: int,
    refs: list[str],
) -> ReleaseGateCheck:
    if sample_count < minimum_samples:
        return ReleaseGateCheck(
            name=name,
            severity="warning",
            operator="lte",
            actual=actual,
            threshold=threshold,
            outcome="not_evaluated",
            message=(
                f"observed only: {sample_count} samples, {minimum_samples} required"
            ),
            evidence_refs=refs,
        )
    return _check(name, "warning", "lte", actual, threshold, refs=refs)


def _check(
    name: str,
    severity: Literal["blocking", "warning"],
    operator: Literal["lte", "gte"],
    actual: int | float | None,
    threshold: int | float,
    *,
    refs: list[str],
) -> ReleaseGateCheck:
    if actual is None:
        outcome: Literal["pass", "fail", "inconclusive", "not_evaluated"] = (
            "inconclusive" if severity == "blocking" else "not_evaluated"
        )
        message = "required metric is unavailable"
    else:
        passed = actual <= threshold if operator == "lte" else actual >= threshold
        outcome = "pass" if passed else "fail"
        message = "threshold satisfied" if passed else "threshold violated"
    return ReleaseGateCheck(
        name=name,
        severity=severity,
        operator=operator,
        actual=actual,
        threshold=threshold,
        outcome=outcome,
        message=message,
        evidence_refs=refs,
    )


def _gate_verdict(
    checks: list[ReleaseGateCheck],
) -> Literal["pass", "warn", "fail", "inconclusive"]:
    if any(item.severity == "blocking" and item.outcome == "fail" for item in checks):
        return "fail"
    if any(
        item.severity == "blocking" and item.outcome == "inconclusive"
        for item in checks
    ):
        return "inconclusive"
    if any(item.severity == "warning" and item.outcome == "fail" for item in checks):
        return "warn"
    return "pass"


def _pair_refs(report: ComparisonReport, classification: str) -> list[str]:
    return [
        item.comparison_pair_id
        for item in report.pairs
        if item.classification == classification
    ]


def _safe_filename(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "-" for character in value)[:96]


def _markdown(value: object) -> str:
    return str(value).replace("`", "\\`").replace("\r", " ").replace("\n", " ")
