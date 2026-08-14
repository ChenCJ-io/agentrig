"""Repair adaptive provenance columns missing from legacy create-all databases.

Revision ID: 20260811_0007
Revises: 20260811_0006
Create Date: 2026-08-11

Older development databases could contain the V2 assistant tables created directly
from the ORM, then be stamped at revision 0004 during the Alembic transition.  Those
tables predated the two provenance columns introduced by 0004, so later queries
failed even though Alembic reported the database at head.  Keep this migration
idempotent so both clean installs and stamped legacy databases converge on the same
schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0007"
down_revision: str | None = "20260811_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade() -> None:
    if "decision_id" not in _column_names("assistant_events"):
        op.add_column("assistant_events", sa.Column("decision_id", sa.String(96)))
    if "ix_assistant_events_decision_id" not in _index_names("assistant_events"):
        op.create_index(
            "ix_assistant_events_decision_id",
            "assistant_events",
            ["decision_id"],
        )

    if "origin_decision_id" not in _column_names("evaluation_plans"):
        op.add_column(
            "evaluation_plans",
            sa.Column("origin_decision_id", sa.String(96)),
        )
    if "ix_evaluation_plans_origin_decision_id" not in _index_names(
        "evaluation_plans"
    ):
        op.create_index(
            "ix_evaluation_plans_origin_decision_id",
            "evaluation_plans",
            ["origin_decision_id"],
        )


def downgrade() -> None:
    # Revision 0006 already assumes the 0004 provenance columns exist.  Removing
    # repaired columns here would make that schema internally inconsistent.
    pass
