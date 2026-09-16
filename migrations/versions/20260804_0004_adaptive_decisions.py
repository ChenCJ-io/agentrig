"""Add V2.1 adaptive decision records and provenance links.

Revision ID: 20260804_0004
Revises: 20260803_0003
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0004"
down_revision: str | None = "20260803_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assistant_events", sa.Column("decision_id", sa.String(96)))
    op.create_index("ix_assistant_events_decision_id", "assistant_events", ["decision_id"])
    op.add_column("evaluation_plans", sa.Column("origin_decision_id", sa.String(96)))
    op.create_index(
        "ix_evaluation_plans_origin_decision_id",
        "evaluation_plans",
        ["origin_decision_id"],
    )
    op.create_table(
        "decision_records",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(96),
            sa.ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_id", sa.String(96), nullable=False),
        sa.Column("parent_decision_id", sa.String(96)),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("trigger_type", sa.String(64), nullable=False),
        sa.Column("decision_kind", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("observation_summary", sa.JSON(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("selected_action", sa.JSON(), nullable=False),
        sa.Column("rationale_summary", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("policy_verdict", sa.JSON(), nullable=False),
        sa.Column("confirmation_event_id", sa.String(96)),
        sa.Column("action_idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("action_ref_type", sa.String(64)),
        sa.Column("action_ref_id", sa.String(96)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("proposed_by", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("session_id", "turn_id", "ordinal"),
    )
    for column in (
        "session_id",
        "turn_id",
        "parent_decision_id",
        "decision_kind",
        "status",
        "confirmation_event_id",
    ):
        op.create_index(f"ix_decision_records_{column}", "decision_records", [column])
    op.create_index(
        "ix_decision_records_session_created",
        "decision_records",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_decision_records_action_ref",
        "decision_records",
        ["action_ref_type", "action_ref_id"],
    )


def downgrade() -> None:
    op.drop_table("decision_records")
    op.drop_index("ix_evaluation_plans_origin_decision_id", table_name="evaluation_plans")
    op.drop_column("evaluation_plans", "origin_decision_id")
    op.drop_index("ix_assistant_events_decision_id", table_name="assistant_events")
    op.drop_column("assistant_events", "decision_id")
