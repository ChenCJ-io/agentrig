"""Add canonical Run manifests and stable Cell/Attempt identities.

Revision ID: 20260811_0006
Revises: 20260810_0005
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0006"
down_revision: str | None = "20260810_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("manifest_schema_version", sa.String(64)))
    op.add_column("runs", sa.Column("manifest_hash", sa.String(72)))
    op.add_column("runs", sa.Column("manifest", sa.JSON()))
    op.add_column("runs", sa.Column("recovery_of_run_id", sa.String(96)))
    op.add_column("runs", sa.Column("recovery_reason", sa.Text()))
    op.add_column(
        "runs",
        sa.Column("cell_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "runs",
        sa.Column(
            "finished_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index("ix_runs_manifest_hash", "runs", ["manifest_hash"])
    op.create_index("ix_runs_recovery_of_run_id", "runs", ["recovery_of_run_id"])

    op.add_column("case_runs", sa.Column("cell_key", sa.String(72)))
    op.add_column("case_runs", sa.Column("evaluation_attempt_id", sa.String(96)))
    op.add_column("case_runs", sa.Column("attempt_index", sa.Integer()))
    op.add_column("case_runs", sa.Column("failure_class", sa.String(64)))
    op.add_column("case_runs", sa.Column("recovery_of_case_run_id", sa.String(96)))
    op.create_index("ix_case_runs_run_cell", "case_runs", ["run_id", "cell_key"])
    op.create_index(
        "ix_case_runs_evaluation_attempt_id",
        "case_runs",
        ["evaluation_attempt_id"],
        unique=True,
    )
    op.create_index("ix_case_runs_failure_class", "case_runs", ["failure_class"])
    op.create_index(
        "ix_case_runs_recovery_of_case_run_id",
        "case_runs",
        ["recovery_of_case_run_id"],
    )

    op.execute(
        sa.text(
            "UPDATE runs SET cell_count = total_count, attempt_count = total_count, "
            "finished_attempt_count = completed_count + failed_count + skipped_count + "
            "cancelled_count"
        )
    )
    op.execute(
        sa.text(
            "UPDATE case_runs SET evaluation_attempt_id = id, "
            "attempt_index = CASE WHEN repeat_index > 0 THEN repeat_index ELSE 1 END"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_case_runs_recovery_of_case_run_id", table_name="case_runs")
    op.drop_index("ix_case_runs_failure_class", table_name="case_runs")
    op.drop_index("ix_case_runs_evaluation_attempt_id", table_name="case_runs")
    op.drop_index("ix_case_runs_run_cell", table_name="case_runs")
    op.drop_column("case_runs", "recovery_of_case_run_id")
    op.drop_column("case_runs", "failure_class")
    op.drop_column("case_runs", "attempt_index")
    op.drop_column("case_runs", "evaluation_attempt_id")
    op.drop_column("case_runs", "cell_key")

    op.drop_index("ix_runs_manifest_hash", table_name="runs")
    op.drop_index("ix_runs_recovery_of_run_id", table_name="runs")
    op.drop_column("runs", "finished_attempt_count")
    op.drop_column("runs", "attempt_count")
    op.drop_column("runs", "cell_count")
    op.drop_column("runs", "manifest")
    op.drop_column("runs", "recovery_reason")
    op.drop_column("runs", "recovery_of_run_id")
    op.drop_column("runs", "manifest_hash")
    op.drop_column("runs", "manifest_schema_version")
