"""Create the AgentRig V2 assistant and AgentTeams integration schema.

Revision ID: 20260801_0002
Revises: 20260729_0001
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0002"
down_revision: str | None = "20260729_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assistant_sessions",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("workspace_id", sa.String(96), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("matrix_room_id", sa.String(300), unique=True),
        sa.Column("active_plan_id", sa.String(96)),
        sa.Column("last_event_seq", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assistant_sessions_workspace_id", "assistant_sessions", ["workspace_id"])
    op.create_index("ix_assistant_sessions_status", "assistant_sessions", ["status"])
    op.create_index("ix_assistant_sessions_active_plan_id", "assistant_sessions", ["active_plan_id"])

    op.create_table(
        "assistant_events",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(96),
            sa.ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(300), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("turn_id", sa.String(96)),
        sa.Column("plan_id", sa.String(96)),
        sa.Column("run_id", sa.String(96)),
        sa.Column("case_run_id", sa.String(96)),
        sa.Column("invocation_id", sa.String(96)),
        sa.Column("client_message_id", sa.String(128)),
        sa.Column("matrix_event_id", sa.String(300), unique=True),
        sa.Column("delivery_status", sa.String(32), nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "seq"),
        sa.UniqueConstraint("session_id", "client_message_id"),
    )
    for column in (
        "session_id",
        "event_type",
        "turn_id",
        "plan_id",
        "run_id",
        "case_run_id",
        "invocation_id",
    ):
        op.create_index(f"ix_assistant_events_{column}", "assistant_events", [column])
    op.create_index(
        "ix_assistant_events_session_created",
        "assistant_events",
        ["session_id", "created_at"],
    )

    op.create_table(
        "assistant_turns",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(96),
            sa.ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger_event_id", sa.String(96), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("matrix_request_event_id", sa.String(300), unique=True),
        sa.Column("matrix_response_event_id", sa.String(300), unique=True),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("model_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assistant_turns_session_id", "assistant_turns", ["session_id"])
    op.create_index("ix_assistant_turns_status", "assistant_turns", ["status"])

    op.create_table(
        "evaluation_plans",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(96),
            sa.ForeignKey("assistant_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_turn_id", sa.String(96), nullable=False),
        sa.Column("parent_plan_id", sa.String(96)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("goal", sa.JSON(), nullable=False),
        sa.Column("selection", sa.JSON(), nullable=False),
        sa.Column("reasoning_summary", sa.JSON(), nullable=False),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("confirmation", sa.JSON(), nullable=False),
        sa.Column("selection_hash", sa.String(64)),
        sa.Column("submit_idempotency_key", sa.String(128), unique=True),
        sa.Column("run_id", sa.String(96), unique=True),
        sa.Column("last_error", sa.JSON()),
        sa.Column("created_by", sa.String(300), nullable=False),
        sa.Column("confirmed_by", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("session_id", "revision"),
    )
    for column in (
        "session_id",
        "source_turn_id",
        "parent_plan_id",
        "status",
        "run_id",
    ):
        op.create_index(f"ix_evaluation_plans_{column}", "evaluation_plans", [column])

    op.create_table(
        "agent_invocations",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("agent_role", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("session_id", sa.String(96)),
        sa.Column("plan_id", sa.String(96)),
        sa.Column("run_id", sa.String(96), nullable=False),
        sa.Column("case_run_id", sa.String(96), nullable=False),
        sa.Column("tool_call_event_id", sa.String(96)),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("result_payload", sa.JSON()),
        sa.Column("result_ref", sa.String(300)),
        sa.Column("result_hash", sa.String(64)),
        sa.Column("matrix_room_id", sa.String(300)),
        sa.Column("request_event_id", sa.String(300), unique=True),
        sa.Column("response_event_id", sa.String(300), unique=True),
        sa.Column("assigned_agent", sa.String(300)),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("agent_role", "idempotency_key"),
    )
    for column in (
        "agent_role",
        "status",
        "session_id",
        "plan_id",
        "run_id",
        "case_run_id",
        "tool_call_event_id",
    ):
        op.create_index(f"ix_agent_invocations_{column}", "agent_invocations", [column])
    op.create_index(
        "ix_agent_invocations_run_role",
        "agent_invocations",
        ["run_id", "agent_role"],
    )

    op.create_table(
        "integration_cursors",
        sa.Column("integration", sa.String(128), primary_key=True),
        sa.Column("cursor", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("integration_cursors")
    op.drop_table("agent_invocations")
    op.drop_table("evaluation_plans")
    op.drop_table("assistant_turns")
    op.drop_table("assistant_events")
    op.drop_table("assistant_sessions")
