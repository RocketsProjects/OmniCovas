"""Add bounded local notification shadow diagnostics (NHI-02).

Revision ID: f9c1a2b3d402
Revises: e8a4c2d7f901
"""

from alembic import op
import sqlalchemy as sa

revision = "f9c1a2b3d402"
down_revision = "e8a4c2d7f901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("notification_shadow_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("commander", sa.String(64), nullable=True),
        sa.Column("candidate_id", sa.String(160), nullable=False),
        sa.Column("evaluated_at", sa.Float(), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False))
    op.create_index("ix_notification_shadow_decisions_commander", "notification_shadow_decisions", ["commander"])
    op.create_index("ix_notification_shadow_decisions_evaluated_at", "notification_shadow_decisions", ["evaluated_at"])
    op.create_table("notification_shadow_checkpoints",
        sa.Column("commander", sa.String(64), primary_key=True),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False))


def downgrade() -> None:
    op.drop_table("notification_shadow_checkpoints")
    op.drop_index("ix_notification_shadow_decisions_evaluated_at", "notification_shadow_decisions")
    op.drop_index("ix_notification_shadow_decisions_commander", "notification_shadow_decisions")
    op.drop_table("notification_shadow_decisions")
