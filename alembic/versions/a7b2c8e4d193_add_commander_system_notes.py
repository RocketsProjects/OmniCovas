"""add_commander_system_notes

Revision ID: a7b2c8e4d193
Revises: f6a4b9d2c715
Create Date: 2026-08-16 00:00:00.000000

LNA-004: Commander-authored notes about visited systems. Stored separately
from Commander Memory because Memory is derived and a rebuild deletes and
re-derives its records; authored notes must survive that.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a7b2c8e4d193"
down_revision: Union[str, Sequence[str], None] = "f6a4b9d2c715"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the Commander system-notes table."""
    op.create_table(
        "commander_system_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("star_system", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # One note per system, edited in place.
        sa.UniqueConstraint("star_system", name="uq_commander_system_notes_system"),
    )
    op.create_index(
        "ix_commander_system_notes_star_system",
        "commander_system_notes",
        ["star_system"],
    )


def downgrade() -> None:
    """Drop the Commander system-notes table.

    Downgrading discards Commander-authored text; it is not recoverable from
    the flight recorder, which never held it.
    """
    op.drop_index(
        "ix_commander_system_notes_star_system",
        table_name="commander_system_notes",
    )
    op.drop_table("commander_system_notes")
