"""add_pvp_encounters

Revision ID: b0f5e1a4c9d2
Revises: 550b8eac852b
Create Date: 2026-05-07 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b0f5e1a4c9d2"
down_revision: Union[str, Sequence[str], None] = "550b8eac852b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "pvp_encounters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("commander_name", sa.String(length=64), nullable=True),
        sa.Column("system", sa.String(length=128), nullable=True),
        sa.Column("source_label", sa.String(length=32), nullable=False),
        sa.Column("encounter_type", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("risk_explanation", sa.Text(), nullable=True),
        sa.Column("provenance_event_type", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pvp_encounters_commander_name"),
        "pvp_encounters",
        ["commander_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pvp_encounters_encounter_type"),
        "pvp_encounters",
        ["encounter_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pvp_encounters_source_label"),
        "pvp_encounters",
        ["source_label"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pvp_encounters_system"),
        "pvp_encounters",
        ["system"],
        unique=False,
    )
    op.create_index(
        op.f("ix_pvp_encounters_timestamp"),
        "pvp_encounters",
        ["timestamp"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_pvp_encounters_timestamp"), table_name="pvp_encounters")
    op.drop_index(op.f("ix_pvp_encounters_system"), table_name="pvp_encounters")
    op.drop_index(op.f("ix_pvp_encounters_source_label"), table_name="pvp_encounters")
    op.drop_index(op.f("ix_pvp_encounters_encounter_type"), table_name="pvp_encounters")
    op.drop_index(op.f("ix_pvp_encounters_commander_name"), table_name="pvp_encounters")
    op.drop_table("pvp_encounters")
