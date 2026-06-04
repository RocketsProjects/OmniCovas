"""add_phase9_squadron_campaign_notes

Revision ID: e5f3a8c1b904
Revises: d4e2f9b1a830
Create Date: 2026-05-28 00:00:00.000000

PB09-05: Phase 9 Squadron local campaign note persistence.
Adds phase9_squadron_campaign_notes table for local-only SquadronCampaignNote entries.
No FK constraints to Operations campaign objectives or Navigation circuit tables
(weak-link design, consistent with Phase 9 cross-entity link patterns).
visibility is always 'local_only'. exported is always False.
author is always 'local_commander'.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f3a8c1b904"
down_revision: Union[str, Sequence[str], None] = "d4e2f9b1a830"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create phase9_squadron_campaign_notes table."""
    op.create_table(
        "phase9_squadron_campaign_notes",
        sa.Column("note_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_type", sa.String(length=16), nullable=False),
        sa.Column("linked_campaign_id", sa.String(length=36), nullable=True),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("exported", sa.Boolean(), nullable=False),
        sa.Column("author", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("note_id"),
    )
    op.create_index(
        op.f("ix_phase9_squadron_campaign_notes_workflow_type"),
        "phase9_squadron_campaign_notes",
        ["workflow_type"],
    )
    op.create_index(
        op.f("ix_phase9_squadron_campaign_notes_linked_campaign_id"),
        "phase9_squadron_campaign_notes",
        ["linked_campaign_id"],
    )


def downgrade() -> None:
    """Downgrade schema: remove phase9_squadron_campaign_notes table."""
    op.drop_index(
        op.f("ix_phase9_squadron_campaign_notes_linked_campaign_id"),
        table_name="phase9_squadron_campaign_notes",
    )
    op.drop_index(
        op.f("ix_phase9_squadron_campaign_notes_workflow_type"),
        table_name="phase9_squadron_campaign_notes",
    )
    op.drop_table("phase9_squadron_campaign_notes")
