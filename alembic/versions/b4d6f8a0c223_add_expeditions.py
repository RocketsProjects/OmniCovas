"""Persist GKI-06 Galactic Expeditions and their stops.

Both tables are keyed by the Commander Memory profile, so commanders never share
expeditions; the forget workflow deletes a commander's rows.

Revision ID: b4d6f8a0c223
Revises: a3c5e7f9b112
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4d6f8a0c223"
down_revision: Union[str, Sequence[str], None] = "a3c5e7f9b112"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "expeditions",
        sa.Column("expedition_id", sa.String(length=32), primary_key=True),
        sa.Column("profile_key", sa.String(length=64), nullable=False, index=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("entry", sa.String(length=16), nullable=False),
        sa.Column("theme_id", sa.String(length=64), nullable=True),
        sa.Column("narrative_id", sa.String(length=64), nullable=True),
        sa.Column("goal_scope", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("story_json", sa.Text(), nullable=False),
        sa.Column("history_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "expedition_stops",
        sa.Column("stop_id", sa.String(length=32), primary_key=True),
        sa.Column(
            "expedition_id",
            sa.String(length=32),
            sa.ForeignKey("expeditions.expedition_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("profile_key", sa.String(length=64), nullable=False, index=True),
        sa.Column("stop_key", sa.String(length=160), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("place_id", sa.String(length=128), nullable=True),
        sa.Column("system_name", sa.String(length=128), nullable=True),
        sa.Column("system_address", sa.Integer(), nullable=True),
        sa.Column("purposes_json", sa.Text(), nullable=False),
        sa.Column("manual_state", sa.String(length=16), nullable=False),
        sa.Column("manual_at", sa.DateTime(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("expedition_id", "stop_key", name="uq_expedition_stop_key"),
    )


def downgrade() -> None:
    op.drop_table("expedition_stops")
    op.drop_table("expeditions")
