"""Add runtime evidence, Project governance, and durable execution foundations.

Revision ID: 20260810_0005
Revises: 20260804_0004
Create Date: 2026-08-10
"""

from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0005"
down_revision: str | None = "20260804_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECT_TABLES = (
    "test_cases",
    "samples",
    "targets",
    "execution_profiles",
    "runs",
    "case_runs",
    "evaluations",
    "assistant_sessions",
    "evaluation_plans",
    "agent_invocations",
    "decision_records",
    "target_chat_sessions",
)


def _id() -> sa.Column[str]:
    return sa.Column("id", sa.String(96), primary_key=True)


def _project_id(*, foreign_key: bool = False) -> sa.Column[str]:
    if foreign_key:
        return sa.Column(
            "project_id",
            sa.String(96),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        )
    return sa.Column("project_id", sa.String(96), nullable=False)


def _created_at() -> sa.Column[datetime]:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)


def _index(table: str, column: str, *, unique: bool = False) -> None:
    op.create_index(f"ix_{table}_{column}", table, [column], unique=unique)


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    op.create_table(
        "projects",
        _id(),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("default_environment", sa.String(128), nullable=False),
        sa.Column("redaction_policy_id", sa.String(96)),
        sa.Column("retention_policy_id", sa.String(96)),
        _created_at(),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
    )
    _index("projects", "slug", unique=True)
    _index("projects", "status")
    op.bulk_insert(
        sa.table(
            "projects",
            sa.column("id", sa.String),
            sa.column("slug", sa.String),
            sa.column("name", sa.String),
            sa.column("status", sa.String),
            sa.column("default_environment", sa.String),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": "default",
                "slug": "default",
                "name": "Default Project",
                "status": "active",
                "default_environment": "development",
                "created_at": now,
            }
        ],
    )

    op.create_table(
        "environments",
        _id(),
        _project_id(foreign_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("release_metadata_schema", sa.JSON(), nullable=False),
        sa.Column("protected", sa.Boolean(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("project_id", "name"),
    )
    _index("environments", "project_id")
    op.bulk_insert(
        sa.table(
            "environments",
            sa.column("id", sa.String),
            sa.column("project_id", sa.String),
            sa.column("name", sa.String),
            sa.column("kind", sa.String),
            sa.column("release_metadata_schema", sa.JSON),
            sa.column("protected", sa.Boolean),
            sa.column("created_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": "env_default_development",
                "project_id": "default",
                "name": "development",
                "kind": "development",
                "release_metadata_schema": {},
                "protected": False,
                "created_at": now,
            }
        ],
    )
    op.create_table(
        "project_api_keys",
        _id(),
        _project_id(foreign_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("key_prefix", sa.String(24), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        _created_at(),
    )
    _index("project_api_keys", "project_id")
    _index("project_api_keys", "key_prefix")
    op.create_index(
        "ix_project_api_keys_project_active",
        "project_api_keys",
        ["project_id", "revoked_at"],
    )

    for table in _PROJECT_TABLES:
        op.add_column(
            table,
            sa.Column(
                "project_id",
                sa.String(96),
                nullable=False,
                server_default="default",
            ),
        )
        _index(table, "project_id")
    op.add_column("case_runs", sa.Column("capability_snapshot", sa.JSON()))
    op.add_column("run_events", sa.Column("attempt_id", sa.String(96)))
    _index("run_events", "attempt_id")

    _create_production_tables()
    _create_review_tables()
    _create_failure_tables()
    _create_job_tables()


def _create_production_tables() -> None:
    op.create_table(
        "ingest_sources",
        _id(),
        _project_id(foreign_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("api_key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(24), nullable=False),
        sa.Column("allowed_service_names", sa.JSON(), nullable=False),
        sa.Column("redaction_policy", sa.JSON(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False),
        sa.Column("daily_span_quota", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        _created_at(),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_id", "name"),
    )
    for column in ("project_id", "key_prefix"):
        _index("ingest_sources", column)
    op.create_table(
        "production_sessions",
        _id(),
        _project_id(),
        sa.Column(
            "source_id",
            sa.String(96),
            sa.ForeignKey("ingest_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_session_id_hash", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("environment", sa.String(128)),
        sa.Column("release", sa.JSON()),
        sa.Column("user_identity_hash", sa.String(64)),
        sa.Column("trace_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("project_id", "source_id", "external_session_id_hash"),
    )
    for column in ("project_id", "source_id", "environment", "status"):
        _index("production_sessions", column)
    op.create_table(
        "production_traces",
        _id(),
        _project_id(),
        sa.Column("source_id", sa.String(96), nullable=False),
        sa.Column(
            "session_id",
            sa.String(96),
            sa.ForeignKey("production_sessions.id", ondelete="SET NULL"),
        ),
        sa.Column("external_trace_id", sa.String(64), nullable=False),
        sa.Column("root_span_id", sa.String(64)),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("service_name", sa.String(300), nullable=False),
        sa.Column("environment", sa.String(128)),
        sa.Column("release", sa.JSON()),
        sa.Column("input_preview_redacted", sa.Text()),
        sa.Column("output_preview_redacted", sa.Text()),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=False),
        sa.Column("cost_snapshot", sa.JSON()),
        sa.Column("ingest_status", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(72), nullable=False),
        sa.Column("redaction_policy_hash", sa.String(72), nullable=False),
        _created_at(),
        sa.UniqueConstraint("project_id", "source_id", "external_trace_id"),
    )
    for column in (
        "project_id",
        "source_id",
        "session_id",
        "status",
        "service_name",
        "environment",
    ):
        _index("production_traces", column)
    op.create_index(
        "ix_production_traces_project_time",
        "production_traces",
        ["project_id", "started_at"],
    )
    op.create_index(
        "ix_production_traces_project_status",
        "production_traces",
        ["project_id", "status"],
    )
    op.create_table(
        "production_spans",
        _id(),
        _project_id(),
        sa.Column(
            "trace_id",
            sa.String(96),
            sa.ForeignKey("production_traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_span_id", sa.String(64), nullable=False),
        sa.Column("parent_external_span_id", sa.String(64)),
        sa.Column("span_kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("agent_path", sa.JSON(), nullable=False),
        sa.Column("model_call", sa.JSON()),
        sa.Column("tool_call", sa.JSON()),
        sa.Column("tool_result", sa.JSON()),
        sa.Column("permission", sa.JSON()),
        sa.Column("memory_operation", sa.JSON()),
        sa.Column("artifact_refs", sa.JSON(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(72), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("trace_id", "external_span_id"),
    )
    for column in ("project_id", "trace_id", "parent_external_span_id", "status"):
        _index("production_spans", column)
    op.create_index(
        "ix_production_spans_trace_time",
        "production_spans",
        ["trace_id", "started_at"],
    )
    op.create_table(
        "trace_case_lineages",
        _id(),
        _project_id(),
        sa.Column("source_trace_id", sa.String(96), nullable=False),
        sa.Column("source_span_ids", sa.JSON(), nullable=False),
        sa.Column("annotation_ids", sa.JSON(), nullable=False),
        sa.Column("failure_pattern_id", sa.String(96)),
        sa.Column("draft_case_id", sa.String(96)),
        sa.Column("draft_sample_ids", sa.JSON(), nullable=False),
        sa.Column("mapping_version", sa.String(64), nullable=False),
        sa.Column("mapping_hash", sa.String(72), nullable=False),
        sa.Column("created_by", sa.String(300), nullable=False),
        sa.Column("reviewed_by", sa.String(300)),
        sa.Column("status", sa.String(32), nullable=False),
        _created_at(),
    )
    for column in (
        "project_id",
        "source_trace_id",
        "failure_pattern_id",
        "draft_case_id",
        "status",
    ):
        _index("trace_case_lineages", column)


def _create_review_tables() -> None:
    op.create_table(
        "review_items",
        _id(),
        _project_id(),
        sa.Column("subject_type", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(96), nullable=False),
        sa.Column("subject_snapshot_hash", sa.String(72), nullable=False),
        sa.Column("queue", sa.String(128), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("assignment", sa.String(300)),
        sa.Column("cohort", sa.String(128)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("required_reviews", sa.Integer(), nullable=False),
        sa.Column("created_reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(300), nullable=False),
        _created_at(),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    for column in (
        "project_id",
        "subject_type",
        "subject_id",
        "queue",
        "priority",
        "assignment",
        "cohort",
        "status",
    ):
        _index("review_items", column)
    op.create_table(
        "annotations",
        _id(),
        _project_id(),
        sa.Column(
            "review_item_id",
            sa.String(96),
            sa.ForeignKey("review_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("annotator_id", sa.String(300), nullable=False),
        sa.Column("confidence", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("supersedes_id", sa.String(96)),
        _created_at(),
        sa.UniqueConstraint("review_item_id", "revision"),
    )
    for column in ("project_id", "review_item_id"):
        _index("annotations", column)
    op.create_table(
        "gold_labels",
        _id(),
        _project_id(),
        sa.Column("review_item_id", sa.String(96), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("annotation_ids", sa.JSON(), nullable=False),
        sa.Column("resolution_method", sa.String(64), nullable=False),
        sa.Column("adjudicator_id", sa.String(300), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(72), nullable=False),
        _created_at(),
        sa.UniqueConstraint("review_item_id", "revision"),
    )
    for column in ("project_id", "review_item_id", "status"):
        _index("gold_labels", column)
    op.create_table(
        "evaluator_versions",
        _id(),
        _project_id(),
        sa.Column("evaluator_id", sa.String(96), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("evaluator_kind", sa.String(32), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(72), nullable=False),
        sa.Column("created_by", sa.String(300), nullable=False),
        sa.Column("approved_by", sa.String(300)),
        sa.Column("alignment_run_id", sa.String(96)),
        _created_at(),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("project_id", "evaluator_id", "version"),
    )
    for column in ("project_id", "evaluator_id", "status"):
        _index("evaluator_versions", column)
    op.create_table(
        "alignment_runs",
        _id(),
        _project_id(),
        sa.Column("evaluator_version_id", sa.String(96), nullable=False),
        sa.Column("gold_label_ids", sa.JSON(), nullable=False),
        sa.Column("predictions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("cohort_metrics", sa.JSON(), nullable=False),
        sa.Column("disagreements", sa.JSON(), nullable=False),
        sa.Column("source_snapshot_hash", sa.String(72), nullable=False),
        sa.Column("limitations", sa.JSON(), nullable=False),
        _created_at(),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    for column in ("project_id", "evaluator_version_id", "status"):
        _index("alignment_runs", column)
    op.create_table(
        "governance_audit_events",
        _id(),
        _project_id(),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.String(96), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(300), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        _created_at(),
    )
    for column in ("project_id", "aggregate_type", "aggregate_id", "event_type"):
        _index("governance_audit_events", column)


def _create_failure_tables() -> None:
    op.create_table(
        "failure_signals",
        _id(),
        _project_id(),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(96), nullable=False),
        sa.Column("source_snapshot_hash", sa.String(72), nullable=False),
        sa.Column("detector_version", sa.String(64), nullable=False),
        sa.Column("signature", sa.String(72), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("environment", sa.String(128)),
        sa.Column("release", sa.JSON()),
        sa.Column("target_runtime", sa.String(300)),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.UniqueConstraint("project_id", "source_type", "source_id", "detector_version"),
    )
    for column in ("project_id", "signature", "category", "environment", "target_runtime"):
        _index("failure_signals", column)
    op.create_table(
        "failure_patterns",
        _id(),
        _project_id(),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("signature", sa.String(72), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("matcher", sa.JSON(), nullable=False),
        sa.Column("owner", sa.String(300)),
        sa.Column("confirmed_by", sa.String(300)),
        sa.Column("resolved_by_run_id", sa.String(96)),
        sa.Column("ignored_reason", sa.Text()),
        sa.Column("ignored_until", sa.DateTime(timezone=True)),
        sa.Column("representative_signal_ids", sa.JSON(), nullable=False),
        sa.Column("linked_case_ids", sa.JSON(), nullable=False),
        sa.Column("linked_suite_versions", sa.JSON(), nullable=False),
        sa.Column("linked_release_gate_ids", sa.JSON(), nullable=False),
        sa.Column("release", sa.JSON()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("project_id", "category", "status", "signature"):
        _index("failure_patterns", column)
    op.create_table(
        "failure_pattern_memberships",
        sa.Column(
            "pattern_id",
            sa.String(96),
            sa.ForeignKey("failure_patterns.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "signal_id",
            sa.String(96),
            sa.ForeignKey("failure_signals.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("membership_source", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("accepted_by", sa.String(300)),
        _created_at(),
    )
    op.create_table(
        "failure_monitors",
        _id(),
        _project_id(),
        sa.Column("pattern_id", sa.String(96), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("environment", sa.String(128)),
        sa.Column("definition_version", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.String(300)),
        sa.Column("shadow_mode", sa.Boolean(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("recurrence_count", sa.Integer(), nullable=False),
        sa.Column("notification_config", sa.JSON(), nullable=False),
        _created_at(),
    )
    for column in ("project_id", "pattern_id", "status"):
        _index("failure_monitors", column)
    op.create_table(
        "failure_pattern_events",
        _id(),
        _project_id(),
        sa.Column(
            "pattern_id",
            sa.String(96),
            sa.ForeignKey("failure_patterns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(300), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        _created_at(),
    )
    for column in ("project_id", "pattern_id", "event_type"):
        _index("failure_pattern_events", column)
    op.create_table(
        "failure_notifications",
        _id(),
        _project_id(),
        sa.Column(
            "monitor_id",
            sa.String(96),
            sa.ForeignKey("failure_monitors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pattern_id", sa.String(96), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(72), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        _created_at(),
        sa.UniqueConstraint("monitor_id", "idempotency_key"),
    )
    for column in ("project_id", "monitor_id", "pattern_id", "status"):
        _index("failure_notifications", column)


def _create_job_tables() -> None:
    op.create_table(
        "execution_jobs",
        _id(),
        _project_id(),
        sa.Column(
            "run_id",
            sa.String(96),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_run_id",
            sa.String(96),
            sa.ForeignKey("case_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(300)),
        sa.Column("lease_token_hash", sa.String(64)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("external_side_effect", sa.Boolean(), nullable=False),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "idempotency_key"),
        sa.UniqueConstraint("project_id", "case_run_id"),
    )
    for column in (
        "project_id",
        "run_id",
        "case_run_id",
        "status",
        "lease_owner",
        "lease_expires_at",
    ):
        _index("execution_jobs", column)
    op.create_index(
        "ix_execution_jobs_claim",
        "execution_jobs",
        ["status", "available_at", "priority"],
    )
    op.create_table(
        "execution_attempts",
        _id(),
        _project_id(),
        sa.Column(
            "job_id",
            sa.String(96),
            sa.ForeignKey("execution_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(300), nullable=False),
        sa.Column("lease_token_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("external_side_effect", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("job_id", "attempt"),
    )
    for column in ("project_id", "job_id"):
        _index("execution_attempts", column)
    op.create_table(
        "worker_registrations",
        sa.Column("id", sa.String(300), primary_key=True),
        sa.Column("backend", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("backend", "expires_at"):
        _index("worker_registrations", column)


def downgrade() -> None:
    for table in (
        "worker_registrations",
        "execution_attempts",
        "execution_jobs",
        "failure_notifications",
        "failure_pattern_events",
        "failure_monitors",
        "failure_pattern_memberships",
        "failure_patterns",
        "failure_signals",
        "governance_audit_events",
        "alignment_runs",
        "evaluator_versions",
        "gold_labels",
        "annotations",
        "review_items",
        "trace_case_lineages",
        "production_spans",
        "production_traces",
        "production_sessions",
        "ingest_sources",
    ):
        op.drop_table(table)
    op.drop_index("ix_run_events_attempt_id", table_name="run_events")
    op.drop_column("run_events", "attempt_id")
    op.drop_column("case_runs", "capability_snapshot")
    for table in reversed(_PROJECT_TABLES):
        op.drop_index(f"ix_{table}_project_id", table_name=table)
        op.drop_column(table, "project_id")
    op.drop_table("project_api_keys")
    op.drop_table("environments")
    op.drop_table("projects")
