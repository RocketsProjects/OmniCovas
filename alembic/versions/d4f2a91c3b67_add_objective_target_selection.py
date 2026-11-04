"""Add the Commander's structured target selection to Operations objectives.

Phase 14 R6 / `P14-H02` — "Commander selects a target mining commodity."

The objective already holds the Commander's sentence. Mining additionally needs
to know *which commodity* and *how many tonnes*, because fill progress
(`P14-H03`) is meaningless without a denominator. Reading those out of the
sentence would mean parsing free text to infer intent, which PB14-R1 forbids and
which no amount of care makes safe. They are therefore stored as what they are:
an explicit selection the Commander made, in columns of their own.

Both are nullable. An objective without a target is a perfectly ordinary
objective, and existing rows keep working untouched.

Revision ID: d4f2a91c3b67
Revises: c7d9e1f4a852
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f2a91c3b67"
down_revision: Union[str, Sequence[str], None] = "c7d9e1f4a852"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "operations_objectives",
        sa.Column("target_commodity", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "operations_objectives",
        sa.Column("target_quantity", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("operations_objectives", "target_quantity")
    op.drop_column("operations_objectives", "target_commodity")
