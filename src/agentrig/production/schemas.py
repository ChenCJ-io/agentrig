"""Stable production evidence, OTLP result, and lineage contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class RedactionPolicy(_StrictModel):
    schema_version: Literal["agentrig.redaction-policy.v1"] = (
        "agentrig.redaction-policy.v1"
    )
    allowed_attribute_keys: list[str] = Field(
        default_factory=lambda: [
            "service.name",
            "deployment.environment.name",
            "service.version",
            "gen_ai.operation.name",
            "gen_ai.request.model",
            "gen_ai.response.model",
            "gen_ai.usage.input_tokens",
            "gen_ai.usage.output_tokens",
            "gen_ai.tool.name",
            "gen_ai.conversation.id",
            "session.id",
            "error.type",
        ]
    )
    save_input_preview: bool = False
    save_output_preview: bool = False
    preview_max_chars: int = Field(default=500, ge=0, le=4_096)


class IngestSourceCreate(_StrictModel):
    name: str = Field(min_length=1, max_length=300)
    source_type: Literal["otlp_http"] = "otlp_http"
    allowed_service_names: list[str] = Field(min_length=1)
    redaction_policy: RedactionPolicy = Field(default_factory=RedactionPolicy)
    retention_days: int = Field(default=30, ge=1, le=3_650)
    rate_limit_per_minute: int = Field(default=600, ge=1, le=100_000)
    daily_span_quota: int = Field(default=1_000_000, ge=1)
    enabled: bool = False


class IngestSourceView(_StrictModel):
    id: str
    project_id: str
    name: str
    source_type: str
    key_prefix: str
    allowed_service_names: list[str]
    redaction_policy: RedactionPolicy
    retention_days: int
    rate_limit_per_minute: int
    daily_span_quota: int
    enabled: bool
    created_at: datetime
    last_seen_at: datetime | None


class IngestSourceIssue(_StrictModel):
    source: IngestSourceView
    token: str


class ReleaseSnapshot(_StrictModel):
    environment: str | None = None
    version: str | None = None
    git_sha: str | None = None
    build_id: str | None = None
    image_digests: dict[str, str] = Field(default_factory=dict)


class ProductionSessionView(_StrictModel):
    id: str
    project_id: str
    source_id: str
    external_session_id_hash: str
    started_at: datetime
    ended_at: datetime | None
    environment: str | None
    release: dict[str, Any] | None
    trace_count: int
    status: str
    attributes: dict[str, Any]
    created_at: datetime


class ProductionTraceView(_StrictModel):
    id: str
    project_id: str
    source_id: str
    session_id: str | None
    external_trace_id: str
    root_span_id: str | None
    name: str
    started_at: datetime
    ended_at: datetime | None
    status: str
    service_name: str
    environment: str | None
    release: dict[str, Any] | None
    input_preview_redacted: str | None
    output_preview_redacted: str | None
    attributes: dict[str, Any]
    token_usage: dict[str, Any]
    ingest_status: str
    content_hash: str
    redaction_policy_hash: str
    created_at: datetime


class ProductionSpanView(_StrictModel):
    id: str
    project_id: str
    trace_id: str
    external_span_id: str
    parent_external_span_id: str | None
    span_kind: str
    name: str
    started_at: datetime
    ended_at: datetime | None
    status: str
    agent_path: list[str]
    model_call: dict[str, Any] | None
    tool_call: dict[str, Any] | None
    tool_result: dict[str, Any] | None
    permission: dict[str, Any] | None
    memory_operation: dict[str, Any] | None
    artifact_refs: list[dict[str, Any]]
    attributes: dict[str, Any]
    events: list[dict[str, Any]]
    content_hash: str
    received_at: datetime


class ProductionTraceDetail(_StrictModel):
    trace: ProductionTraceView
    spans: list[ProductionSpanView] = Field(default_factory=list)
    missing_parent_span_ids: list[str] = Field(default_factory=list)


class ProductionTracePage(_StrictModel):
    items: list[ProductionTraceView]
    total: int
    limit: int
    offset: int


class ProductionRetentionRequest(_StrictModel):
    """Bounded retention sweep; an explicit cutoff can only make deletion older."""

    source_id: str | None = None
    before: datetime | None = None
    dry_run: bool = True
    actor: str = Field(min_length=1, max_length=300)


class ProductionRetentionSourceResult(_StrictModel):
    source_id: str
    cutoff: datetime
    trace_count: int = Field(ge=0)
    span_count: int = Field(ge=0)
    session_count: int = Field(ge=0)
    lineage_count: int = Field(ge=0)
    tombstone_count: int = Field(ge=0)
    truncated: bool = False


class ProductionRetentionResult(_StrictModel):
    schema_version: Literal["agentrig.production-retention.v1"] = (
        "agentrig.production-retention.v1"
    )
    project_id: str
    dry_run: bool
    sources: list[ProductionRetentionSourceResult] = Field(default_factory=list)
    trace_count: int = Field(ge=0)
    span_count: int = Field(ge=0)
    session_count: int = Field(ge=0)
    lineage_count: int = Field(ge=0)
    tombstone_count: int = Field(ge=0)
    executed_at: datetime


class TraceCaseDraftRequest(_StrictModel):
    source_span_ids: list[str] = Field(default_factory=list)
    template_user_message: str | None = Field(default=None, max_length=100_000)
    expected_behavior: str = Field(min_length=1, max_length=100_000)
    required_capabilities: list[str] = Field(default_factory=list)
    target_versions: list[str] = Field(default_factory=list)
    annotation_ids: list[str] = Field(default_factory=list)
    failure_pattern_id: str | None = None
    created_by: str = Field(min_length=1, max_length=300)

    @field_validator("source_span_ids", "annotation_ids")
    @classmethod
    def ids_are_unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class TraceCaseDraftPreview(_StrictModel):
    source_trace_id: str
    selected_span_ids: list[str]
    generalized_user_message: str
    expected_behavior: str
    removed_fields: list[str]
    mapping_version: str
    mapping_hash: str


class TraceCaseLineageView(_StrictModel):
    id: str
    project_id: str
    source_trace_id: str
    source_span_ids: list[str]
    annotation_ids: list[str]
    failure_pattern_id: str | None
    draft_case_id: str | None
    draft_sample_ids: list[str]
    mapping_version: str
    mapping_hash: str
    created_by: str
    reviewed_by: str | None
    status: Literal["draft", "approved", "rejected"]
    created_at: datetime


class TraceCaseLineageReview(_StrictModel):
    status: Literal["approved", "rejected"]
    reviewer_id: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=10_000)


class TraceCaseDraftResult(_StrictModel):
    preview: TraceCaseDraftPreview
    case_id: str
    lineage: TraceCaseLineageView


class OtlpIngestResult(_StrictModel):
    accepted_spans: int = Field(ge=0)
    duplicate_spans: int = Field(ge=0)
    rejected_spans: int = Field(ge=0)
    conflict_spans: int = Field(ge=0)
    error_messages: list[str] = Field(default_factory=list)
