"""add_operations_objectives

Revision ID: c7d9e1f4a852
Revises: b8c3d5e7f210
Create Date: 2026-08-19 00:00:00.000000

PB14-R1: one Commander-entered objective per Operations mode. Authored
intent, stored beside the derived cockpit rather than inside Commander
Memory, which a rebuild deletes and re-derives.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c7d9e1f4a852"
down_revision: Union[str, Sequence[str], None] = "b8c3d5e7f210"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the Operations objective table."""
    op.create_table(
        "operations_objectives",
        sa.Column("objective_id", sa.String(length=36), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("last_activity_log_event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("objective_id"),
    )
    op.create_index(
        "ix_operations_objectives_operation",
        "operations_objectives",
        ["operation"],
    )
    op.create_index(
        "ix_operations_objectives_state",
        "operations_objectives",
        ["state"],
    )
    # One current objective per mode. Archived rows are retained history and
    # sit outside the constraint, so clearing never blocks the next objective.
    op.create_index(
        "uq_operations_objectives_current",
        "operations_objectives",
        ["operation"],
        unique=True,
        sqlite_where=sa.text("state != 'archived'"),
    )


def downgrade() -> None:
    """Drop the Operations objective table.

    Downgrading discards Commander-authored intent. Nothing can reconstruct
    it from the flight recorder, which never held it.
    """
    op.drop_index(
        "uq_operations_objectives_current", table_name="operations_objectives"
    )
    op.drop_index("ix_operations_objectives_state", table_name="operations_objectives")
    op.drop_index(
        "ix_operations_objectives_operation", table_name="operations_objectives"
    )
    op.drop_table("operations_objectives")
