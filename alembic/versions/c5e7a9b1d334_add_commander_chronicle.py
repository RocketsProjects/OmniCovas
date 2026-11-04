"""Persist the GKI-07 Commander Chronicle.

One table keyed by the Commander Memory profile, so commanders never share a
Chronicle; the forget workflow deletes a commander's rows. The unique
fingerprint per commander makes replayed Journal lines idempotent.

Revision ID: c5e7a9b1d334
Revises: b4d6f8a0c223
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5e7a9b1d334"
down_revision: Union[str, Sequence[str], None] = "b4d6f8a0c223"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chronicle_entries",
        sa.Column("entry_id", sa.String(length=32), primary_key=True),
        sa.Column("profile_key", sa.String(length=64), nullable=False, index=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("evidence", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=160), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("source_event", sa.String(length=32), nullable=True),
        sa.Column("replayed", sa.Boolean(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("profile_key", "fingerprint", name="uq_chronicle_entry"),
    )


def downgrade() -> None:
    op.drop_table("chronicle_entries")
