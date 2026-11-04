"""add_exobiology_rule_evidence

Revision ID: b8c3d5e7f210
Revises: a7b2c8e4d193
Create Date: 2026-08-17 00:00:00.000000

Exobiology Rule Sentinel evidence store. Holds the judgement made about a confirmed
ScanOrganic against the occurrence rules in force at the time, pinned to the ruleset
version and hash that produced it. Separate from journal_events, which records what
happened and must stay unaltered.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b8c3d5e7f210"
down_revision: Union[str, Sequence[str], None] = "a7b2c8e4d193"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the exobiology rule evidence table."""
    op.create_table(
        "exobiology_rule_evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("classification", sa.String(length=32), nullable=False),
        sa.Column("review_state", sa.String(length=32), nullable=False),
        sa.Column("species_id", sa.String(length=64), nullable=False),
        sa.Column("species_name", sa.String(length=128), nullable=False),
        sa.Column("genus", sa.String(length=64), nullable=False),
        sa.Column("variant", sa.String(length=128), nullable=True),
        sa.Column("star_system", sa.String(length=128), nullable=True),
        sa.Column("system_address", sa.String(length=32), nullable=True),
        sa.Column("body_name", sa.String(length=160), nullable=True),
        sa.Column("body_id", sa.String(length=32), nullable=True),
        sa.Column("evaluation_before_observation", sa.String(length=16), nullable=False),
        sa.Column("contradicted_branch", sa.String(length=32), nullable=True),
        sa.Column("contradicted_predicate", sa.String(length=64), nullable=True),
        sa.Column("observed_facts", sa.Text(), nullable=False),
        sa.Column("ruleset_version", sa.String(length=64), nullable=False),
        sa.Column("ruleset_sha256", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # Re-scanning the same colony must increment a count, not file the finding
        # again. The ruleset hash is part of the identity so evidence gathered under
        # an older ruleset stays distinct from evidence gathered under the current one.
        sa.UniqueConstraint(
            "species_id",
            "body_name",
            "contradicted_predicate",
            "ruleset_sha256",
            name="uq_exobiology_rule_evidence_identity",
        ),
    )
    op.create_index(
        "ix_exobiology_rule_evidence_classification",
        "exobiology_rule_evidence",
        ["classification"],
    )
    op.create_index(
        "ix_exobiology_rule_evidence_review_state",
        "exobiology_rule_evidence",
        ["review_state"],
    )
    op.create_index(
        "ix_exobiology_rule_evidence_species_id",
        "exobiology_rule_evidence",
        ["species_id"],
    )


def downgrade() -> None:
    """Drop the exobiology rule evidence table.

    Downgrading discards recorded contradictions. The underlying ScanOrganic events
    survive in the flight recorder, so the evidence can be re-derived by replay; the
    review states a Commander set by hand cannot be.
    """
    op.drop_index(
        "ix_exobiology_rule_evidence_species_id", table_name="exobiology_rule_evidence"
    )
    op.drop_index(
        "ix_exobiology_rule_evidence_review_state", table_name="exobiology_rule_evidence"
    )
    op.drop_index(
        "ix_exobiology_rule_evidence_classification",
        table_name="exobiology_rule_evidence",
    )
    op.drop_table("exobiology_rule_evidence")
