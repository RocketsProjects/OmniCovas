"""Persist Commander-supplied Engineering reference catalogues.

Revision ID: e8a4c2d7f901
Revises: d4f2a91c3b67
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8a4c2d7f901"
down_revision: Union[str, Sequence[str], None] = "d4f2a91c3b67"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "engineering_catalogs",
        sa.Column("catalog_key", sa.String(length=192), primary_key=True),
        sa.Column("catalog_id", sa.String(length=96), nullable=False, index=True),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("license_label", sa.String(length=128), nullable=False),
        sa.Column("rights_basis", sa.String(length=256), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False, unique=True),
        sa.Column("catalog_json", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("engineering_catalogs")
