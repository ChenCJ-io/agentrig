"""Remove the AgentTeams collaboration schema.

Drops the Worker invocation and Manager decision tables, the Matrix
synchronisation cursor table, and every Matrix/decision column on the
assistant tables. Historical rows produced by the AgentTeams runtime
(worker events, decision events, non-local delivery states) are scrubbed
so the remaining data matches the reduced enums.

The downgrade recreates the schema shape as it existed at revision
20260811_0007. Dropped data is NOT restored.

Revision ID: 20260907_0008
Revises: 20260811_0007
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260907_0008"
down_revision: str | None = "20260811_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_EVENT_TYPES = (
    "decision_recorded",
    "decision_status_changed",
    "recovery_proposed",
    "agent_invocation_status",
    "collaboration_intervention",
)


def upgrade() -> None:
    events = sa.table(
        "assistant_events",
        sa.column("event_type", sa.String),
        sa.column("actor_type", sa.String),
        sa.column("delivery_status", sa.String),
    )
    op.execute(
        events.delete().where(
            sa.or_(
                events.c.event_type.in_(_LEGACY_EVENT_TYPES),
                events.c.actor_type == "worker",
            )
        )
    )
    op.execute(
        events.update()
        .where(events.c.delivery_status.in_(("pending", "delivered")))
        .values(delivery_status="local")
    )

    op.drop_table("decision_records")
    op.drop_table("agent_invocations")
    op.drop_table("integration_cursors")

    op.drop_index("ix_assistant_events_decision_id", table_name="assistant_events")
    op.drop_index("ix_assistant_events_invocation_id", table_name="assistant_events")
    op.drop_index(
        "ix_evaluation_plans_origin_decision_id",
        table_name="evaluation_plans",
    )

    with op.batch_alter_table("assistant_sessions") as batch:
        batch.drop_column("matrix_room_id")
    with op.batch_alter_table("assistant_events") as batch:
        batch.drop_column("matrix_event_id")
        batch.drop_column("decision_id")
        batch.drop_column("invocation_id")
    with op.batch_alter_table("assistant_turns") as batch:
        batch.drop_column("matrix_request_event_id")
        batch.drop_column("matrix_response_event_id")
    with op.batch_alter_table("evaluation_plans") as batch:
        batch.drop_column("origin_decision_id")


def downgrade() -> None:
    with op.batch_alter_table("assistant_sessions") as batch:
        batch.add_column(sa.Column("matrix_room_id", sa.String(300)))
        batch.create_unique_constraint(
            "uq_assistant_sessions_matrix_room_id", ["matrix_room_id"]
        )
    with op.batch_alter_table("assistant_events") as batch:
        batch.add_column(sa.Column("matrix_event_id", sa.String(300)))
        batch.add_column(sa.Column("decision_id", sa.String(96)))
        batch.add_column(sa.Column("invocation_id", sa.String(96)))
        batch.create_unique_constraint(
            "uq_assistant_events_matrix_event_id", ["matrix_event_id"]
        )
    with op.batch_alter_table("assistant_turns") as batch:
        batch.add_column(sa.Column("matrix_request_event_id", sa.String(300)))
        batch.add_column(sa.Column("matrix_response_event_id", sa.String(300)))
        batch.create_unique_constraint(
            "uq_assistant_turns_matrix_request_event_id",
            ["matrix_request_event_id"],
        )
        batch.create_unique_constraint(
            "uq_assistant_turns_matrix_response_event_id",
            ["matrix_response_event_id"],
        )
    with op.batch_alter_table("evaluation_plans") as batch:
        batch.add_column(sa.Column("origin_decision_id", sa.String(96)))

    op.create_index(
        "ix_assistant_events_decision_id", "assistant_events", ["decision_id"]
    )
    op.create_index(
        "ix_assistant_events_invocation_id", "assistant_events", ["invocation_id"]
    )
    op.create_index(
        "ix_evaluation_plans_origin_decision_id",
        "evaluation_plans",
        ["origin_decision_id"],
    )

    op.create_table(
        "integration_cursors",
        sa.Column("integration", sa.String(128), primary_key=True),
        sa.Column("cursor", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

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
        sa.Column(
            "project_id",
            sa.String(96),
            nullable=False,
            server_default="default",
        ),
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
        "project_id",
    ):
        op.create_index(
            f"ix_agent_invocations_{column}", "agent_invocations", [column]
        )
    op.create_index(
        "ix_agent_invocations_run_role",
        "agent_invocations",
        ["run_id", "agent_role"],
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
        sa.Column(
            "action_idempotency_key", sa.String(128), nullable=False, unique=True
        ),
        sa.Column("action_ref_type", sa.String(64)),
        sa.Column("action_ref_id", sa.String(96)),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.Text()),
        sa.Column("proposed_by", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "project_id",
            sa.String(96),
            nullable=False,
            server_default="default",
        ),
        sa.UniqueConstraint("session_id", "turn_id", "ordinal"),
    )
    for column in (
        "session_id",
        "turn_id",
        "parent_decision_id",
        "decision_kind",
        "status",
        "confirmation_event_id",
        "project_id",
    ):
        op.create_index(
            f"ix_decision_records_{column}", "decision_records", [column]
        )
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
