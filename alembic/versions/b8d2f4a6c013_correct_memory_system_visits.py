"""Stop counting logins as system visits in Commander Memory (GKI-08 closeout).

A system's ``visit_count`` used to rise on every ``Location``, so each relog read as
another visit.  Its ledger keeps every observation with its event, so the supported
count can be recomputed: each arrival, plus the first stay if a login found it.  The
observations themselves are untouched.

Revision ID: b8d2f4a6c013
Revises: d6f8b0c2e445
"""

from alembic import op

revision = "b8d2f4a6c013"
down_revision = "d6f8b0c2e445"
branch_labels = None
depends_on = None

_SAME_ENTITY = """
    FROM commander_memory_observations AS seen
    WHERE seen.profile_key = commander_memory_records.profile_key
      AND seen.category = commander_memory_records.category
      AND seen.entity_key = commander_memory_records.entity_key
"""


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE commander_memory_records
        SET visit_count = (
            SELECT COUNT(*) {_SAME_ENTITY} AND seen.source_event != 'Location'
        ) + COALESCE((
            SELECT seen.source_event = 'Location' {_SAME_ENTITY}
            ORDER BY seen.observed_at, seen.source_event
            LIMIT 1
        ), 0)
        WHERE category = 'systems'
          AND EXISTS (SELECT 1 {_SAME_ENTITY})
        """
    )


def downgrade() -> None:
    # A lower count is valid in the earlier schema; the inflated one is not restored.
    pass
