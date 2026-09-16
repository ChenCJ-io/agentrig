"""Add gateway relay settings to ingest sources.

Revision ID: 20260908_0009
Revises: 20260907_0008
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0009"
down_revision: str | None = "20260907_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ingest_sources") as batch:
        batch.add_column(sa.Column("gateway", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ingest_sources") as batch:
        batch.drop_column("gateway")
