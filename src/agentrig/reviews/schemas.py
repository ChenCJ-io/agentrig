"""Strict public contracts for review and evaluator governance."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ReviewLabel = Literal["pass", "fail", "inconclusive", "evaluation_error"]
SubjectKind = Literal["case_run", "production_trace", "production_span"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ReviewItemCreate(_StrictModel):
    subject_kind: SubjectKind
    subject_id: str = Field(min_length=1, max_length=96)
    queue: str = Field(default="default", min_length=1, max_length=128)
    priority: int = Field(default=0, ge=-100, le=100)
    assignment: str | None = Field(default=None, max_length=300)
    cohort: str | None = Field(default=None, max_length=128)
    required_reviews: int = Field(default=1, ge=1, le=10)
    created_reason: str = Field(min_length=1, max_length=2_000)
    created_by: str = Field(min_length=1, max_length=300)


class ReviewItemView(_StrictModel):
    id: str
    project_id: str
    subject_kind: SubjectKind
    subject_id: str
    subject_snapshot_hash: str
    queue: str
    priority: int
    assignment: str | None
    cohort: str | None
    status: Literal["open", "in_review", "adjudication", "resolved", "dismissed"]
    required_reviews: int
    created_reason: str
    created_by: str
    created_at: datetime
    resolved_at: datetime | None


class ReviewItemPage(_StrictModel):
    items: list[ReviewItemView]
    total: int
    limit: int
    offset: int


class AnnotationCriterion(_StrictModel):
    criterion: str = Field(min_length=1, max_length=300)
    outcome: ReviewLabel
    evidence_refs: list[str] = Field(default_factory=list)
    blocking: bool = False


class AnnotationCreate(_StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=300)
    label: ReviewLabel
    criteria: list[AnnotationCriterion] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)
    rationale_summary: str = Field(min_length=1, max_length=10_000)
    confidence: Literal["low", "medium", "high"]
    supersedes: str | None = None

    @field_validator("evidence_refs")
    @classmethod
    def evidence_is_unique(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("evidence refs must be non-empty")
        return list(dict.fromkeys(value))


class AnnotationView(_StrictModel):
    schema_version: Literal["agentrig.annotation.v1"] = "agentrig.annotation.v1"
    id: str
    project_id: str
    review_item_id: str
    revision: int
    reviewer_id: str
    label: ReviewLabel
    criteria: list[AnnotationCriterion]
    evidence_refs: list[str]
    rationale_summary: str
    confidence: Literal["low", "medium", "high"]
    status: Literal["submitted"]
    supersedes: str | None
    created_at: datetime


class GoldLabelResolve(_StrictModel):
    adjudicator_id: str = Field(min_length=1, max_length=300)
    role: Literal["reviewer", "adjudicator"] = "adjudicator"
    label: ReviewLabel | None = None
    status: Literal["resolved", "disputed"] = "resolved"
    rationale_summary: str = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def resolved_needs_label(self) -> GoldLabelResolve:
        if self.status == "resolved" and self.label is None:
            raise ValueError("resolved gold labels require an explicit label")
        return self


class GoldLabelView(_StrictModel):
    schema_version: Literal["agentrig.gold-label.v1"] = "agentrig.gold-label.v1"
    id: str
    project_id: str
    review_item_id: str
    revision: int
    label: ReviewLabel | None
    source_annotation_ids: list[str]
    resolution_method: Literal["consensus", "adjudication", "disputed"]
    adjudicator_id: str
    rationale_summary: str
    status: Literal["resolved", "disputed"]
    content_hash: str
    created_at: datetime


class EvaluatorVersionCreate(_StrictModel):
    evaluator_id: str = Field(min_length=1, max_length=96)
    evaluator_kind: Literal["rule", "evidence_judge", "external"]
    name: str = Field(min_length=1, max_length=300)
    semantic_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
    code_revision: str = Field(min_length=1, max_length=300)
    prompt_version: str | None = Field(default=None, max_length=300)
    prompt_hash: str | None = Field(default=None, max_length=128)
    model_id: str | None = Field(default=None, max_length=300)
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    tool_hashes: dict[str, str] = Field(default_factory=dict)
    skill_hashes: dict[str, str] = Field(default_factory=dict)
    output_schema_hash: str = Field(min_length=1, max_length=128)
    created_by: str = Field(min_length=1, max_length=300)


class EvaluatorVersionView(_StrictModel):
    id: str
    project_id: str
    evaluator_id: str
    evaluator_kind: Literal["rule", "evidence_judge", "external"]
    name: str
    semantic_version: str
    status: Literal["draft", "active", "retired"]
    config_snapshot: dict[str, Any]
    content_hash: str
    created_by: str
    approved_by: str | None
    alignment_run_id: str | None
    created_at: datetime
    activated_at: datetime | None


class AlignmentPrediction(_StrictModel):
    gold_label_id: str
    predicted_label: ReviewLabel
    cohorts: dict[str, str] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)


class AlignmentRunCreate(_StrictModel):
    gold_label_ids: list[str] = Field(min_length=1)
    predictions: list[AlignmentPrediction] = Field(default_factory=list)

    @field_validator("gold_label_ids")
    @classmethod
    def gold_ids_are_unique(cls, value: list[str]) -> list[str]:
        unique = list(dict.fromkeys(value))
        if len(unique) != len(value):
            raise ValueError("gold_label_ids must be unique")
        return value


class AlignmentMetrics(_StrictModel):
    total_gold: int
    eligible_gold: int
    predicted: int
    missing: int
    disputed: int
    coverage: float
    agreement: float
    confusion_matrix: dict[str, dict[str, int]]
    precision_by_label: dict[str, float | None]
    recall_by_label: dict[str, float | None]
    false_pass_rate: float
    false_fail_rate: float
    inconclusive_rate: float
    evaluation_error_rate: float


class AlignmentReport(_StrictModel):
    schema_version: Literal["agentrig.alignment-report.v1"] = (
        "agentrig.alignment-report.v1"
    )
    id: str
    project_id: str
    evaluator_version_id: str
    gold_label_ids: list[str]
    status: Literal["completed"]
    metrics: AlignmentMetrics
    cohort_metrics: dict[str, AlignmentMetrics]
    disagreements: list[dict[str, Any]]
    missing: list[str]
    limitations: list[str]
    source_snapshot_hash: str
    created_at: datetime
    finished_at: datetime


class EvaluatorActivate(_StrictModel):
    alignment_run_id: str
    approved_by: str = Field(min_length=1, max_length=300)
    allow_overall_regression: bool = False
