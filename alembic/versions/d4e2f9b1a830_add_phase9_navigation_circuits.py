"""add_phase9_navigation_circuits

Revision ID: d4e2f9b1a830
Revises: c1f9e2a3b507
Create Date: 2026-05-27 00:00:00.000000

PB09-04: Phase 9 Navigation campaign circuit support.
Adds phase9_campaign_circuits and phase9_campaign_circuit_stops tables for
local-only CampaignCircuit / CampaignCircuitStop persistence.
Adds tags_json column to navigation_bookmarks for bookmark tag vocabulary.
No FK constraints to Operations campaign objectives or Intel tables (weak-link design).
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e2f9b1a830"
down_revision: Union[str, Sequence[str], None] = "c1f9e2a3b507"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add bookmark tags column, create circuit tables."""
    # Add tags_json to existing navigation_bookmarks table.
    # server_default ensures existing rows get the safe default "[]".
    op.add_column(
        "navigation_bookmarks",
        sa.Column(
            "tags_json",
            sa.Text(),
            nullable=False,
            server_default="'[]'",
        ),
    )

    op.create_table(
        "phase9_campaign_circuits",
        sa.Column("circuit_id", sa.String(length=36), nullable=False),
        sa.Column("workflow_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("linked_campaign_id", sa.String(length=36), nullable=True),
        sa.Column("source_label", sa.String(length=32), nullable=False),
        sa.Column("last_activity_log_event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("circuit_id"),
    )
    op.create_index(
        op.f("ix_phase9_campaign_circuits_workflow_type"),
        "phase9_campaign_circuits",
        ["workflow_type"],
    )
    op.create_index(
        op.f("ix_phase9_campaign_circuits_title"),
        "phase9_campaign_circuits",
        ["title"],
    )
    op.create_index(
        op.f("ix_phase9_campaign_circuits_linked_campaign_id"),
        "phase9_campaign_circuits",
        ["linked_campaign_id"],
    )

    op.create_table(
        "phase9_campaign_circuit_stops",
        sa.Column("stop_id", sa.String(length=36), nullable=False),
        sa.Column("circuit_id", sa.String(length=36), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("system_name", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("linked_intel_fact_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("stop_id"),
    )
    op.create_index(
        op.f("ix_phase9_campaign_circuit_stops_circuit_id"),
        "phase9_campaign_circuit_stops",
        ["circuit_id"],
    )


def downgrade() -> None:
    """Downgrade schema: remove circuit tables and bookmark tags column."""
    op.drop_index(
        op.f("ix_phase9_campaign_circuit_stops_circuit_id"),
        table_name="phase9_campaign_circuit_stops",
    )
    op.drop_table("phase9_campaign_circuit_stops")

    op.drop_index(
        op.f("ix_phase9_campaign_circuits_linked_campaign_id"),
        table_name="phase9_campaign_circuits",
    )
    op.drop_index(
        op.f("ix_phase9_campaign_circuits_title"),
        table_name="phase9_campaign_circuits",
    )
    op.drop_index(
        op.f("ix_phase9_campaign_circuits_workflow_type"),
        table_name="phase9_campaign_circuits",
    )
    op.drop_table("phase9_campaign_circuits")

    op.drop_column("navigation_bookmarks", "tags_json")
