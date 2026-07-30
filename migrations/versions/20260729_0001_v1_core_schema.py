"""Create the AgentRig V1 core schema.

Revision ID: 20260729_0001
Revises:
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_cases",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("supported_versions", sa.JSON(), nullable=False),
        sa.Column("primary_evaluator", sa.String(32), nullable=False),
        sa.Column("initial_state", sa.JSON(), nullable=False),
        sa.Column("case_assertions", sa.JSON(), nullable=False),
        sa.Column("case_rubric", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_test_cases_review_status", "test_cases", ["review_status"])

    op.create_table(
        "case_turns",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(96),
            sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("simulation_instruction", sa.Text()),
        sa.Column("fixtures", sa.JSON(), nullable=False),
        sa.Column("assertions", sa.JSON(), nullable=False),
        sa.Column("rubric", sa.Text()),
        sa.UniqueConstraint("case_id", "position"),
    )
    op.create_index("ix_case_turns_case_id", "case_turns", ["case_id"])

    op.create_table(
        "case_tags",
        sa.Column(
            "case_id",
            sa.String(96),
            sa.ForeignKey("test_cases.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("tag", sa.String(300), primary_key=True),
    )
    op.create_index("ix_case_tags_tag", "case_tags", ["tag"])

    op.create_table(
        "samples",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("tool_name", sa.String(300)),
        sa.Column("sample_kind", sa.String(32), nullable=False),
        sa.Column("content", sa.JSON()),
        sa.Column("match_arguments", sa.JSON(), nullable=False),
        sa.Column("ignored_argument_paths", sa.JSON(), nullable=False),
        sa.Column("supported_versions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_tool_call_id", sa.String(96)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_samples_tool_name", "samples", ["tool_name"])
    op.create_index("ix_samples_status", "samples", ["status"])
    op.create_index("ix_samples_source_tool_call_id", "samples", ["source_tool_call_id"])
    op.create_index("ix_samples_match", "samples", ["tool_name", "status"])

    op.create_table(
        "targets",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("driver_type", sa.String(128), nullable=False),
        sa.Column("endpoint", sa.Text()),
        sa.Column("secret_ref", sa.String(300)),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_targets_driver_type", "targets", ["driver_type"])

    op.create_table(
        "target_versions",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column(
            "target_id",
            sa.String(96),
            sa.ForeignKey("targets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(300), nullable=False),
        sa.Column("endpoint_override", sa.Text()),
        sa.Column("options_override", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("target_id", "version"),
    )
    op.create_index("ix_target_versions_target_id", "target_versions", ["target_id"])

    op.create_table(
        "execution_profiles",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("selection_snapshot", sa.JSON(), nullable=False),
        sa.Column("resolved_case_ids", sa.JSON(), nullable=False),
        sa.Column("profile_snapshot", sa.JSON(), nullable=False),
        sa.Column("target_snapshots", sa.JSON(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("cancelled_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_runs_status", "runs", ["status"])

    op.create_table(
        "case_runs",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(96),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(96), nullable=False),
        sa.Column("case_snapshot", sa.JSON(), nullable=False),
        sa.Column("target_snapshot", sa.JSON(), nullable=False),
        sa.Column("profile_snapshot", sa.JSON(), nullable=False),
        sa.Column("version", sa.String(300)),
        sa.Column("repeat_index", sa.Integer(), nullable=False),
        sa.Column("comparison_pair_id", sa.String(96)),
        sa.Column("comparison_role", sa.String(32)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("primary_evaluator", sa.String(32), nullable=False),
        sa.Column("evaluation_state", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("summary", sa.JSON(), nullable=False),
    )
    op.create_index("ix_case_runs_run_id", "case_runs", ["run_id"])
    op.create_index("ix_case_runs_case_id", "case_runs", ["case_id"])
    op.create_index("ix_case_runs_status", "case_runs", ["status"])
    op.create_index("ix_case_runs_run_status", "case_runs", ["run_id", "status"])
    op.create_index(
        "ix_case_runs_pair",
        "case_runs",
        ["comparison_pair_id", "comparison_role"],
    )

    op.create_table(
        "run_events",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column(
            "case_run_id",
            sa.String(96),
            sa.ForeignKey("case_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_run_id", "seq"),
    )
    op.create_index("ix_run_events_case_run_id", "run_events", ["case_run_id"])
    op.create_index("ix_run_events_event_type", "run_events", ["event_type"])

    op.create_table(
        "evaluations",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column(
            "case_run_id",
            sa.String(96),
            sa.ForeignKey("case_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evaluator_type", sa.String(32), nullable=False),
        sa.Column("evaluator_source", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("verdict", sa.String(32)),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("model_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_run_id", "evaluator_type"),
    )
    op.create_index("ix_evaluations_case_run_id", "evaluations", ["case_run_id"])


def downgrade() -> None:
    op.drop_table("evaluations")
    op.drop_table("run_events")
    op.drop_table("case_runs")
    op.drop_table("runs")
    op.drop_table("execution_profiles")
    op.drop_table("target_versions")
    op.drop_table("targets")
    op.drop_table("samples")
    op.drop_table("case_tags")
    op.drop_table("case_turns")
    op.drop_table("test_cases")
