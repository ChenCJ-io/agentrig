"""Strict failure-governance contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Severity = Literal["low", "medium", "high", "critical"]
PatternStatus = Literal[
    "candidate", "new", "escalating", "ongoing", "resolved", "regressed", "ignored"
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FailureSignalCreate(_StrictModel):
    source_kind: Literal["evaluation", "annotation", "trace_score", "manual"]
    source_id: str = Field(min_length=1, max_length=96)
    signal_type: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=128)
    severity: Severity
    label: Literal["fail", "evaluation_error"] = "fail"
    summary: str = Field(min_length=1, max_length=2_000)
    detector_version: str = Field(min_length=1, max_length=64)
    environment: str | None = Field(default=None, max_length=128)
    release: dict[str, Any] | None = None
    target_runtime: str | None = Field(default=None, max_length=300)
    evidence_refs: list[str] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None

    @field_validator("evidence_refs")
    @classmethod
    def refs_are_unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class FailureSignalView(_StrictModel):
    schema_version: Literal["agentrig.failure-signal.v1"] = (
        "agentrig.failure-signal.v1"
    )
    id: str
    project_id: str
    source_kind: str
    source_id: str
    source_snapshot_hash: str
    signal_type: str
    signature: str
    category: str
    severity: Severity
    label: str
    summary: str
    detector_version: str
    environment: str | None
    release: dict[str, Any] | None
    target_runtime: str | None
    evidence_refs: list[str]
    attributes: dict[str, Any]
    occurred_at: datetime
    created_at: datetime


class FailureSignalPage(_StrictModel):
    items: list[FailureSignalView]
    total: int
    limit: int
    offset: int


class FailurePatternCreate(_StrictModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10_000)
    severity: Severity
    priority: int = Field(default=0, ge=-100, le=100)
    owner: str | None = Field(default=None, max_length=300)
    signal_ids: list[str] = Field(min_length=1)
    matcher: dict[str, Any] = Field(default_factory=dict)
    created_by: str = Field(min_length=1, max_length=300)

    @field_validator("signal_ids")
    @classmethod
    def signals_are_unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class PatternMembershipView(_StrictModel):
    pattern_id: str
    definition_version: int
    signal_id: str
    match_kind: Literal["exact", "rule", "semantic", "manual"]
    match_score: float | None
    explanation: str
    status: Literal["candidate", "confirmed", "rejected"]
    reviewed_by: str | None
    created_at: datetime


class FailurePatternView(_StrictModel):
    id: str
    project_id: str
    title: str
    description: str
    category: str
    severity: Severity
    priority: int
    status: PatternStatus
    signature: str
    definition_version: int
    matcher: dict[str, Any]
    owner: str | None
    confirmed_by: str | None
    resolved_by_run_id: str | None
    ignored_reason: str | None
    ignored_until: datetime | None
    representative_signal_ids: list[str]
    linked_case_ids: list[str]
    linked_suite_versions: list[str]
    linked_release_gate_ids: list[str]
    release: dict[str, Any] | None
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    memberships: list[PatternMembershipView] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class FailurePatternPage(_StrictModel):
    items: list[FailurePatternView]
    total: int
    limit: int
    offset: int


class MembershipDecision(_StrictModel):
    signal_id: str
    decision: Literal["confirmed", "rejected"]
    explanation: str = Field(min_length=1, max_length=2_000)


class MembershipReview(_StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=300)
    decisions: list[MembershipDecision] = Field(min_length=1)


class FailurePatternTransition(_StrictModel):
    target_status: PatternStatus
    actor: str = Field(min_length=1, max_length=300)
    reason: str = Field(min_length=1, max_length=2_000)
    resolved_by_run_id: str | None = None
    ignored_until: datetime | None = None

    @model_validator(mode="after")
    def transition_fields_match(self) -> FailurePatternTransition:
        if self.target_status == "resolved" and not self.resolved_by_run_id:
            raise ValueError("resolved transition requires resolved_by_run_id")
        if self.target_status == "ignored" and not self.reason.strip():
            raise ValueError("ignored transition requires a reason")
        return self


class FailureLinksUpdate(_StrictModel):
    actor: str = Field(min_length=1, max_length=300)
    linked_case_ids: list[str] = Field(default_factory=list)
    linked_suite_versions: list[str] = Field(default_factory=list)
    linked_release_gate_ids: list[str] = Field(default_factory=list)
    release: dict[str, Any] | None = None


class PatternDefinitionUpdate(_StrictModel):
    actor: str = Field(min_length=1, max_length=300)
    matcher: dict[str, Any]
    reason: str = Field(min_length=1, max_length=2_000)


class WebhookConfig(_StrictModel):
    url: str = Field(pattern=r"^https?://", max_length=2_000)
    secret_ref: str = Field(min_length=1, max_length=300)
    max_attempts: int = Field(default=3, ge=1, le=10)


class FailureMonitorCreate(_StrictModel):
    environment: str | None = Field(default=None, max_length=128)
    shadow_mode: bool = True
    webhook: WebhookConfig | None = None


class FailureMonitorView(_StrictModel):
    id: str
    project_id: str
    pattern_id: str
    definition_version: int
    status: Literal["active", "paused"]
    environment: str | None
    cursor: str | None
    shadow_mode: bool
    last_checked_at: datetime | None
    last_seen_at: datetime | None
    last_error: str | None
    recurrence_count: int
    notification_config: dict[str, Any]
    created_at: datetime


class PatternEventView(_StrictModel):
    id: str
    project_id: str
    pattern_id: str
    event_type: str
    actor: str
    details: dict[str, Any]
    created_at: datetime


class WebhookDeliveryView(_StrictModel):
    id: str
    project_id: str
    monitor_id: str
    pattern_id: str
    idempotency_key: str
    payload: dict[str, Any]
    payload_hash: str
    status: Literal["pending", "delivered", "failed", "dead"]
    attempts: int
    max_attempts: int
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime
