"""add_phase11_commander_memory

Revision ID: f6a4b9d2c715
Revises: e5f3a8c1b904
Create Date: 2026-08-15 00:00:00.000000

PB11-R2: local private Commander Memory settings, pseudonymous profiles,
observed-memory aggregates, and deterministic observation deduplication.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f6a4b9d2c715"
down_revision: Union[str, Sequence[str], None] = "e5f3a8c1b904"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the Phase 11 Commander Memory tables and indexes."""
    op.create_table(
        "commander_memory_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("active_profile_key", sa.String(length=64), nullable=True),
        sa.Column("last_rebuild_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "commander_memory_profiles",
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=True),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("forgotten_at", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("profile_key"),
    )
    op.create_table(
        "commander_memory_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("entity_key", sa.String(length=256), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("parent_key", sa.String(length=256), nullable=True),
        sa.Column("parent_name", sa.String(length=256), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("visit_count", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=48), nullable=False),
        sa.Column("source_event", sa.String(length=64), nullable=True),
        sa.Column("source_file", sa.String(length=128), nullable=True),
        sa.Column("freshness", sa.String(length=24), nullable=False),
        sa.Column("caveat", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("latest_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_key"],
            ["commander_memory_profiles.profile_key"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_key",
            "category",
            "entity_key",
            name="uq_commander_memory_record_entity",
        ),
    )
    op.create_index(
        op.f("ix_commander_memory_records_profile_key"),
        "commander_memory_records",
        ["profile_key"],
    )
    op.create_index(
        op.f("ix_commander_memory_records_category"),
        "commander_memory_records",
        ["category"],
    )
    op.create_index(
        op.f("ix_commander_memory_records_display_name"),
        "commander_memory_records",
        ["display_name"],
    )
    op.create_index(
        op.f("ix_commander_memory_records_last_seen_at"),
        "commander_memory_records",
        ["last_seen_at"],
    )
    op.create_table(
        "commander_memory_observations",
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("profile_key", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("entity_key", sa.String(length=256), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("source_event", sa.String(length=64), nullable=True),
        sa.Column("source_file", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(
            ["profile_key"],
            ["commander_memory_profiles.profile_key"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("fingerprint"),
    )
    op.create_index(
        op.f("ix_commander_memory_observations_profile_key"),
        "commander_memory_observations",
        ["profile_key"],
    )
    op.create_index(
        op.f("ix_commander_memory_observations_category"),
        "commander_memory_observations",
        ["category"],
    )
    op.create_index(
        op.f("ix_commander_memory_observations_observed_at"),
        "commander_memory_observations",
        ["observed_at"],
    )


def downgrade() -> None:
    """Remove all Phase 11 Commander Memory tables."""
    op.drop_index(
        op.f("ix_commander_memory_observations_observed_at"),
        table_name="commander_memory_observations",
    )
    op.drop_index(
        op.f("ix_commander_memory_observations_category"),
        table_name="commander_memory_observations",
    )
    op.drop_index(
        op.f("ix_commander_memory_observations_profile_key"),
        table_name="commander_memory_observations",
    )
    op.drop_table("commander_memory_observations")
    op.drop_index(
        op.f("ix_commander_memory_records_last_seen_at"),
        table_name="commander_memory_records",
    )
    op.drop_index(
        op.f("ix_commander_memory_records_display_name"),
        table_name="commander_memory_records",
    )
    op.drop_index(
        op.f("ix_commander_memory_records_category"),
        table_name="commander_memory_records",
    )
    op.drop_index(
        op.f("ix_commander_memory_records_profile_key"),
        table_name="commander_memory_records",
    )
    op.drop_table("commander_memory_records")
    op.drop_table("commander_memory_profiles")
    op.drop_table("commander_memory_settings")
