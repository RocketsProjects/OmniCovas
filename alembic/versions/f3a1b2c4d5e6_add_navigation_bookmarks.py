"""add_navigation_bookmarks

Revision ID: f3a1b2c4d5e6
Revises: b0f5e1a4c9d2
Create Date: 2026-05-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a1b2c4d5e6"
down_revision: Union[str, Sequence[str], None] = "b0f5e1a4c9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "navigation_bookmarks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("target_name", sa.String(length=128), nullable=False),
        sa.Column("target_system_address", sa.BigInteger(), nullable=True),
        sa.Column("x", sa.Float(), nullable=True),
        sa.Column("y", sa.Float(), nullable=True),
        sa.Column("z", sa.Float(), nullable=True),
        sa.Column("commander_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_navigation_bookmarks_entity_type"),
        "navigation_bookmarks",
        ["entity_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_navigation_bookmarks_label"),
        "navigation_bookmarks",
        ["label"],
        unique=False,
    )
    op.create_index(
        op.f("ix_navigation_bookmarks_target_name"),
        "navigation_bookmarks",
        ["target_name"],
        unique=False,
    )

    op.create_table(
        "navigation_saved_routes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("label", sa.String(length=64), nullable=False),
        sa.Column("origin", sa.String(length=128), nullable=False),
        sa.Column("destination", sa.String(length=128), nullable=False),
        sa.Column("hop_count", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.String(length=32), nullable=False),
        sa.Column("commander_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_navigation_saved_routes_destination"),
        "navigation_saved_routes",
        ["destination"],
        unique=False,
    )
    op.create_index(
        op.f("ix_navigation_saved_routes_label"),
        "navigation_saved_routes",
        ["label"],
        unique=False,
    )
    op.create_index(
        op.f("ix_navigation_saved_routes_origin"),
        "navigation_saved_routes",
        ["origin"],
        unique=False,
    )
    op.create_index(
        op.f("ix_navigation_saved_routes_source_id"),
        "navigation_saved_routes",
        ["source_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_navigation_saved_routes_source_id"), table_name="navigation_saved_routes"
    )
    op.drop_index(
        op.f("ix_navigation_saved_routes_origin"), table_name="navigation_saved_routes"
    )
    op.drop_index(
        op.f("ix_navigation_saved_routes_label"), table_name="navigation_saved_routes"
    )
    op.drop_index(
        op.f("ix_navigation_saved_routes_destination"), table_name="navigation_saved_routes"
    )
    op.drop_table("navigation_saved_routes")

    op.drop_index(
        op.f("ix_navigation_bookmarks_target_name"), table_name="navigation_bookmarks"
    )
    op.drop_index(
        op.f("ix_navigation_bookmarks_label"), table_name="navigation_bookmarks"
    )
    op.drop_index(
        op.f("ix_navigation_bookmarks_entity_type"), table_name="navigation_bookmarks"
    )
    op.drop_table("navigation_bookmarks")
