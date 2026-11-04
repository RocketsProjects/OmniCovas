"""Persist GKI-04 Galactic Intelligence briefings and encounters.

GKI-04 created these tables through ``metadata.create_all()`` only; this revision
records them in the migration graph so versioned installs carry them too.

Revision ID: a3c5e7f9b112
Revises: e8a4c2d7f901
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3c5e7f9b112"
down_revision: Union[str, Sequence[str], None] = "e8a4c2d7f901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "galactic_intelligence_encounters",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("profile_key", sa.String(length=64), nullable=False, index=True),
        sa.Column("encounter_key", sa.String(length=160), nullable=False),
        sa.Column("first_briefed_at", sa.DateTime(), nullable=False),
        sa.Column("last_briefed_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("briefing_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "profile_key", "encounter_key", name="uq_galactic_intelligence_encounter"
        ),
    )
    op.create_table(
        "galactic_intelligence_briefings",
        sa.Column("briefing_id", sa.String(length=32), primary_key=True),
        sa.Column("profile_key", sa.String(length=64), nullable=False, index=True),
        sa.Column("event_key", sa.String(length=64), nullable=False),
        sa.Column("encounter_key", sa.String(length=160), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("dismissed_at", sa.DateTime(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "profile_key",
            "event_key",
            name="uq_galactic_intelligence_briefing_event",
        ),
    )


def downgrade() -> None:
    op.drop_table("galactic_intelligence_briefings")
    op.drop_table("galactic_intelligence_encounters")
