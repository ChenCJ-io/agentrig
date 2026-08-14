"""报告和导出的稳定服务端契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..capabilities.schemas import CapabilityDiff
from ..evaluations.models import EvaluationOutcome
from ..runs.models import CaseRunStatus, RunStatus


class RunReportTarget(BaseModel):
    id: str
    name: str
    version: str | None = None


class RunReportRun(BaseModel):
    id: str
    status: RunStatus
    resolved_case_ids: list[str]
    total_count: int
    completed_count: int
    failed_count: int
    skipped_count: int
    cancelled_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


class RunOutcomeCounts(BaseModel):
    total: int
    evaluated: int
    pass_count: int
    fail_count: int
    inconclusive_count: int
    awaiting_verdict_count: int
    evaluation_error_count: int


class RecoveryProvenance(BaseModel):
    """报告使用 Recovery Run 时的可审计覆盖关系。"""

    source_run_id: str
    recovery_run_ids: list[str] = Field(default_factory=list)
    applied_recovery_run_ids: list[str] = Field(default_factory=list)
    effective_attempt_count: int = Field(ge=0)
    replaced_attempt_count: int = Field(ge=0)
    superseded_attempt_ids: list[str] = Field(default_factory=list)
    effective_attempt_ids: list[str] = Field(default_factory=list)


class RunReportFailure(BaseModel):
    id: str
    case_id: str
    version: str | None
    repeat_index: int
    status: CaseRunStatus
    evaluation_state: EvaluationOutcome
    error_code: str | None
    error_message: str | None
    evaluation_summary: str | None


class RunReport(BaseModel):
    schema_version: Literal["agentrig.run-report.v1"] = "agentrig.run-report.v1"
    generated_at: datetime
    run: RunReportRun
    targets: list[RunReportTarget] = Field(default_factory=list)
    outcomes: RunOutcomeCounts
    failures: list[RunReportFailure] = Field(default_factory=list)
    recovery: RecoveryProvenance | None = None


class _StableReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class LatencyDistribution(_StableReportModel):
    count: int = Field(ge=0)
    minimum_ms: float | None = Field(default=None, ge=0)
    p50_ms: float | None = Field(default=None, ge=0)
    p95_ms: float | None = Field(default=None, ge=0)
    maximum_ms: float | None = Field(default=None, ge=0)


class QualityScope(_StableReportModel):
    resolved_case_ids: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)
    case_run_count: int = Field(ge=0)


class QualityOutcomeCounts(_StableReportModel):
    total: int = Field(ge=0)
    pass_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    inconclusive_count: int = Field(ge=0)
    awaiting_verdict_count: int = Field(ge=0)
    evaluation_error_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)
    interrupted_count: int = Field(ge=0)
    execution_failed_count: int = Field(ge=0)


class QualityLatencyMetrics(_StableReportModel):
    run_duration_ms: float | None = Field(default=None, ge=0)
    case_run: LatencyDistribution
    driver_request: LatencyDistribution
    ttft: LatencyDistribution


class QualityUsageMetrics(_StableReportModel):
    usage_event_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: str | None = None
    currency: str | None = None
    cost_kind: str | None = None
    pricing_source: str | None = None
    pricing_effective_at: datetime | None = None
    pricing_snapshot_hash: str | None = None
    missing_fields: list[str] = Field(default_factory=list)


class QualityReliabilityMetrics(_StableReportModel):
    driver_request_count: int = Field(ge=0)
    provider_attempt_count: int = Field(ge=0)
    fallback_attempt_count: int = Field(ge=0)
    provider_error_count: int = Field(ge=0)
    recoverable_group_count: int = Field(ge=0)
    recovered_group_count: int = Field(ge=0)
    recovery_success_rate: float | None = Field(default=None, ge=0, le=1)
    timeout_count: int = Field(ge=0)
    error_codes: dict[str, int] = Field(default_factory=dict)


class QualityDecisionMetrics(_StableReportModel):
    total: int = Field(ge=0)
    terminal: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    provenance_candidates: int = Field(ge=0)
    provenance_linked: int = Field(ge=0)
    provenance_link_rate: float | None = Field(default=None, ge=0, le=1)


class QualityInvocationMetrics(_StableReportModel):
    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    timed_out: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    duration: LatencyDistribution


class QualityCollaborationMetrics(_StableReportModel):
    decisions: QualityDecisionMetrics
    invocations: QualityInvocationMetrics


class QualityEvidenceMetrics(_StableReportModel):
    evaluation_count: int = Field(ge=0)
    evaluation_error_count: int = Field(ge=0)
    evaluations_without_references: int = Field(ge=0)
    reference_count: int = Field(ge=0)
    valid_reference_count: int = Field(ge=0)
    foreign_reference_count: int = Field(ge=0)
    missing_reference_count: int = Field(ge=0)
    reference_validity_rate: float | None = Field(default=None, ge=0, le=1)
    redaction_status: Literal["applied"] = "applied"


class QualityReport(_StableReportModel):
    schema_version: Literal["agentrig.quality-report.v1"] = (
        "agentrig.quality-report.v1"
    )
    generated_at: datetime
    run_id: str
    run_status: RunStatus
    source_snapshot_hash: str
    scope: QualityScope
    outcomes: QualityOutcomeCounts
    latency: QualityLatencyMetrics
    usage: QualityUsageMetrics
    reliability: QualityReliabilityMetrics
    collaboration: QualityCollaborationMetrics
    evidence_quality: QualityEvidenceMetrics
    recovery: RecoveryProvenance | None = None
    limitations: list[str] = Field(default_factory=list)


ComparisonClassification = Literal[
    "unchanged_pass",
    "unchanged_fail",
    "regression",
    "fix",
    "changed_inconclusive",
    "infrastructure_error",
    "incomplete_pair",
    "incomparable_environment",
]
CapabilityComparisonDisplay = Literal[
    "not_available",
    "comparable",
    "warning_difference",
    "incomparable",
    "unknown",
]


class ComparisonSide(_StableReportModel):
    case_run_id: str
    target_id: str
    version: str | None
    status: CaseRunStatus
    outcome: EvaluationOutcome
    evidence_refs: list[str] = Field(default_factory=list)
    duration_ms: float | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class MetricDelta(_StableReportModel):
    baseline: float | None = None
    candidate: float | None = None
    absolute: float | None = None
    ratio: float | None = None


class ComparisonPair(_StableReportModel):
    comparison_pair_id: str
    case_id: str
    repeat_index: int
    classification: ComparisonClassification
    baseline: ComparisonSide | None = None
    candidate: ComparisonSide | None = None
    duration_delta: MetricDelta
    token_delta: MetricDelta
    capability_comparison: CapabilityComparisonDisplay = "not_available"
    capability_diff: CapabilityDiff | None = None
    limitations: list[str] = Field(default_factory=list)


class ComparisonSummary(_StableReportModel):
    total_pairs: int = Field(ge=0)
    comparable_pairs: int = Field(ge=0)
    regression_count: int = Field(ge=0)
    fix_count: int = Field(ge=0)
    unchanged_pass_count: int = Field(ge=0)
    unchanged_fail_count: int = Field(ge=0)
    changed_inconclusive_count: int = Field(ge=0)
    infrastructure_error_count: int = Field(ge=0)
    incomplete_pair_count: int = Field(ge=0)
    incomparable_environment_count: int = Field(ge=0)


class ComparisonAggregateMetrics(_StableReportModel):
    duration_sample_count: int = Field(ge=0)
    duration_regression_ratio: float | None = None
    token_sample_count: int = Field(ge=0)
    token_regression_ratio: float | None = None


class ComparisonReport(_StableReportModel):
    schema_version: Literal["agentrig.comparison-report.v1"] = (
        "agentrig.comparison-report.v1"
    )
    generated_at: datetime
    run_id: str
    source_snapshot_hash: str
    summary: ComparisonSummary
    metrics: ComparisonAggregateMetrics
    pairs: list[ComparisonPair] = Field(default_factory=list)
    recovery: RecoveryProvenance | None = None
    limitations: list[str] = Field(default_factory=list)


class ExportCounts(BaseModel):
    runs: int
    test_cases: int
    samples: int
    total_records: int


class TargetExportPreview(BaseModel):
    schema_version: Literal["agentrig.export-preview.v1"] = (
        "agentrig.export-preview.v1"
    )
    target_id: str
    counts: ExportCounts
    max_export_records: int
    within_limit: bool


class TargetExportScope(BaseModel):
    runs: list[dict[str, Any]] = Field(default_factory=list)
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    samples: list[dict[str, Any]] = Field(default_factory=list)


class TargetExportBundle(BaseModel):
    schema_version: Literal["agentrig.export.v1"] = "agentrig.export.v1"
    target_id: str
    generated_at: datetime
    target: dict[str, Any]
    counts: ExportCounts
    scope: TargetExportScope
    redaction: str
