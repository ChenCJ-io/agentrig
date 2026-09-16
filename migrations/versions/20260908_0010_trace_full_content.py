"""Store optional redacted full content on production traces.

Revision ID: 20260908_0010
Revises: 20260908_0009
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260908_0010"
down_revision: str | None = "20260908_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("production_traces") as batch:
        batch.add_column(sa.Column("input_full_redacted", sa.Text(), nullable=True))
        batch.add_column(sa.Column("output_full_redacted", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("production_traces") as batch:
        batch.drop_column("output_full_redacted")
        batch.drop_column("input_full_redacted")
