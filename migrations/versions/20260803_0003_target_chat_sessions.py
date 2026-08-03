"""Persist Target direct-chat sessions.

Revision ID: 20260803_0003
Revises: 20260801_0002
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0003"
down_revision: str | None = "20260801_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "target_chat_sessions",
        sa.Column("id", sa.String(96), primary_key=True),
        sa.Column("target_id", sa.String(96), nullable=False),
        sa.Column("profile_id", sa.String(96)),
        sa.Column("version", sa.String(300)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_target_chat_sessions_target_id", "target_chat_sessions", ["target_id"])
    op.create_index("ix_target_chat_sessions_profile_id", "target_chat_sessions", ["profile_id"])
    op.create_index("ix_target_chat_sessions_status", "target_chat_sessions", ["status"])
    op.create_index(
        "ix_target_chat_sessions_target_updated",
        "target_chat_sessions",
        ["target_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_table("target_chat_sessions")
