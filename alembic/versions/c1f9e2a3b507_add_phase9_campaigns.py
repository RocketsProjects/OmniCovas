"""add_phase9_campaigns

Revision ID: c1f9e2a3b507
Revises: a8e0c6f2b418
Create Date: 2026-05-27 00:00:00.000000

PB09-03: Phase 9 Operations campaign workflow.
Adds phase9_campaign_objectives table for local-only CampaignObjective persistence.
No FK constraints to Intel or Navigation tables (weak-link design per PB09-03).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1f9e2a3b507"
down_revision: Union[str, Sequence[str], None] = "a8e0c6f2b418"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create phase9_campaign_objectives table."""
    op.create_table(
        "phase9_campaign_objectives",
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_subject", sa.String(length=128), nullable=True),
        sa.Column("target_system", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("blockers_json", sa.Text(), nullable=False),
        sa.Column("next_actions_json", sa.Text(), nullable=False),
        sa.Column("linked_intel_facts_json", sa.Text(), nullable=False),
        sa.Column("linked_navigation_circuits_json", sa.Text(), nullable=False),
        sa.Column("ai_draft_history_json", sa.Text(), nullable=False),
        sa.Column("last_activity_log_event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("campaign_id"),
    )
    op.create_index(
        op.f("ix_phase9_campaign_objectives_workflow_type"),
        "phase9_campaign_objectives",
        ["workflow_type"],
    )
    op.create_index(
        op.f("ix_phase9_campaign_objectives_title"),
        "phase9_campaign_objectives",
        ["title"],
    )
    op.create_index(
        op.f("ix_phase9_campaign_objectives_state"),
        "phase9_campaign_objectives",
        ["state"],
    )


def downgrade() -> None:
    """Downgrade schema: drop phase9_campaign_objectives table."""
    op.drop_index(
        op.f("ix_phase9_campaign_objectives_state"),
        table_name="phase9_campaign_objectives",
    )
    op.drop_index(
        op.f("ix_phase9_campaign_objectives_title"),
        table_name="phase9_campaign_objectives",
    )
    op.drop_index(
        op.f("ix_phase9_campaign_objectives_workflow_type"),
        table_name="phase9_campaign_objectives",
    )
    op.drop_table("phase9_campaign_objectives")
