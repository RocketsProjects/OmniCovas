"""add_phase8_engineering

Revision ID: a8e0c6f2b418
Revises: f3a1b2c4d5e6
Create Date: 2026-05-23 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8e0c6f2b418"
down_revision: Union[str, Sequence[str], None] = "f3a1b2c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "engineering_goals",
        sa.Column("goal_id", sa.String(length=36), nullable=False),
        sa.Column("commander_id", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_kind", sa.String(length=48), nullable=False),
        sa.Column("target_reference_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("linked_build_plan_id", sa.String(length=36), nullable=True),
        sa.Column("linked_material_gap_view_id", sa.String(length=36), nullable=True),
        sa.Column("linked_acquisition_handoff_ids_json", sa.Text(), nullable=False),
        sa.Column("linked_operations_task_id", sa.String(length=64), nullable=True),
        sa.Column("last_activity_log_event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("goal_id"),
    )
    op.create_index(op.f("ix_engineering_goals_title"), "engineering_goals", ["title"])
    op.create_index(
        op.f("ix_engineering_goals_target_kind"),
        "engineering_goals",
        ["target_kind"],
    )
    op.create_index(op.f("ix_engineering_goals_state"), "engineering_goals", ["state"])
    op.create_index(
        op.f("ix_engineering_goals_priority"), "engineering_goals", ["priority"]
    )

    op.create_table(
        "engineering_build_plans",
        sa.Column("build_plan_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_ship_json", sa.Text(), nullable=False),
        sa.Column("target_loadout_summary_json", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=48), nullable=False),
        sa.Column("format_verification_state", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("linked_goal_ids_json", sa.Text(), nullable=False),
        sa.Column("linked_material_gap_view_id", sa.String(length=36), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_activity_log_event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("build_plan_id"),
    )
    op.create_index(
        op.f("ix_engineering_build_plans_title"),
        "engineering_build_plans",
        ["title"],
    )
    op.create_index(
        op.f("ix_engineering_build_plans_source"),
        "engineering_build_plans",
        ["source"],
    )
    op.create_index(
        op.f("ix_engineering_build_plans_format_verification_state"),
        "engineering_build_plans",
        ["format_verification_state"],
    )
    op.create_index(
        op.f("ix_engineering_build_plans_state"),
        "engineering_build_plans",
        ["state"],
    )

    op.create_table(
        "engineering_material_gap_overrides",
        sa.Column("gap_view_id", sa.String(length=36), nullable=False),
        sa.Column("goal_id", sa.String(length=36), nullable=True),
        sa.Column("build_plan_id", sa.String(length=36), nullable=True),
        sa.Column("material_id", sa.String(length=96), nullable=False),
        sa.Column("material_display_name", sa.String(length=128), nullable=False),
        sa.Column("commander_override_required", sa.Integer(), nullable=True),
        sa.Column("commander_override_current", sa.Integer(), nullable=True),
        sa.Column("required_note", sa.Text(), nullable=True),
        sa.Column("current_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("gap_view_id"),
    )
    op.create_index(
        op.f("ix_engineering_material_gap_overrides_goal_id"),
        "engineering_material_gap_overrides",
        ["goal_id"],
    )
    op.create_index(
        op.f("ix_engineering_material_gap_overrides_build_plan_id"),
        "engineering_material_gap_overrides",
        ["build_plan_id"],
    )
    op.create_index(
        op.f("ix_engineering_material_gap_overrides_material_id"),
        "engineering_material_gap_overrides",
        ["material_id"],
    )

    op.create_table(
        "engineering_acquisition_plans",
        sa.Column("acquisition_plan_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("linked_goal_ids_json", sa.Text(), nullable=False),
        sa.Column("linked_build_plan_ids_json", sa.Text(), nullable=False),
        sa.Column("target_materials_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("navigation_handoff_ids_json", sa.Text(), nullable=False),
        sa.Column("operations_task_id", sa.String(length=64), nullable=True),
        sa.Column("selected_navigation_candidate_summary_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_activity_log_event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("acquisition_plan_id"),
    )
    op.create_index(
        op.f("ix_engineering_acquisition_plans_title"),
        "engineering_acquisition_plans",
        ["title"],
    )
    op.create_index(
        op.f("ix_engineering_acquisition_plans_state"),
        "engineering_acquisition_plans",
        ["state"],
    )

    op.create_table(
        "engineering_blueprint_progress",
        sa.Column("blueprint_progress_id", sa.String(length=36), nullable=False),
        sa.Column("blueprint_label", sa.String(length=128), nullable=False),
        sa.Column("target_engineer_label", sa.String(length=128), nullable=True),
        sa.Column("target_module_label", sa.String(length=128), nullable=True),
        sa.Column("target_grade", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("linked_material_gap_view_ids_json", sa.Text(), nullable=False),
        sa.Column("linked_engineer_unlock_state_id", sa.String(length=36), nullable=True),
        sa.Column("linked_engineercraft_event_ids_json", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("blueprint_progress_id"),
    )
    op.create_index(
        op.f("ix_engineering_blueprint_progress_blueprint_label"),
        "engineering_blueprint_progress",
        ["blueprint_label"],
    )
    op.create_index(
        op.f("ix_engineering_blueprint_progress_target_grade"),
        "engineering_blueprint_progress",
        ["target_grade"],
    )
    op.create_index(
        op.f("ix_engineering_blueprint_progress_state"),
        "engineering_blueprint_progress",
        ["state"],
    )

    op.create_table(
        "engineering_engineer_unlock_states",
        sa.Column("engineer_unlock_state_id", sa.String(length=36), nullable=False),
        sa.Column("engineer_label", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=False),
        sa.Column("last_engineerprogress_event_at", sa.DateTime(), nullable=True),
        sa.Column("commander_notes", sa.Text(), nullable=True),
        sa.Column("requirements_known", sa.String(length=32), nullable=False),
        sa.Column("requirements_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("engineer_unlock_state_id"),
    )
    op.create_index(
        op.f("ix_engineering_engineer_unlock_states_engineer_label"),
        "engineering_engineer_unlock_states",
        ["engineer_label"],
    )
    op.create_index(
        op.f("ix_engineering_engineer_unlock_states_state"),
        "engineering_engineer_unlock_states",
        ["state"],
    )

    op.create_table(
        "engineering_guardian_tech_progress",
        sa.Column("guardian_tech_progress_id", sa.String(length=36), nullable=False),
        sa.Column("guardian_tech_label", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("linked_techbroker_event_ids_json", sa.Text(), nullable=False),
        sa.Column("requirements_known", sa.String(length=32), nullable=False),
        sa.Column("requirements_text", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("guardian_tech_progress_id"),
    )
    op.create_index(
        op.f("ix_engineering_guardian_tech_progress_state"),
        "engineering_guardian_tech_progress",
        ["state"],
    )

    op.create_table(
        "engineering_suit_engineering_states",
        sa.Column("suit_engineering_state_id", sa.String(length=36), nullable=False),
        sa.Column("suit_engineering_label", sa.String(length=128), nullable=False),
        sa.Column("state", sa.String(length=48), nullable=False),
        sa.Column("requirements_known", sa.String(length=32), nullable=False),
        sa.Column("requirements_text", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("suit_engineering_state_id"),
    )
    op.create_index(
        op.f("ix_engineering_suit_engineering_states_state"),
        "engineering_suit_engineering_states",
        ["state"],
    )

    op.create_table(
        "engineering_import_source_states",
        sa.Column("import_source_state_id", sa.String(length=36), nullable=False),
        sa.Column("provider_label", sa.String(length=48), nullable=False),
        sa.Column("format_version_label", sa.String(length=64), nullable=True),
        sa.Column("format_verification_state", sa.String(length=32), nullable=False),
        sa.Column("format_verification_evidence_summary", sa.Text(), nullable=True),
        sa.Column("consent_state", sa.String(length=32), nullable=False),
        sa.Column("last_consent_event_id", sa.String(length=64), nullable=True),
        sa.Column("last_import_event_id", sa.String(length=64), nullable=True),
        sa.Column("last_export_event_id", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("import_source_state_id"),
    )
    op.create_index(
        op.f("ix_engineering_import_source_states_provider_label"),
        "engineering_import_source_states",
        ["provider_label"],
    )
    op.create_index(
        op.f("ix_engineering_import_source_states_format_verification_state"),
        "engineering_import_source_states",
        ["format_verification_state"],
    )
    op.create_index(
        op.f("ix_engineering_import_source_states_consent_state"),
        "engineering_import_source_states",
        ["consent_state"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_engineering_import_source_states_consent_state"),
        table_name="engineering_import_source_states",
    )
    op.drop_index(
        op.f("ix_engineering_import_source_states_format_verification_state"),
        table_name="engineering_import_source_states",
    )
    op.drop_index(
        op.f("ix_engineering_import_source_states_provider_label"),
        table_name="engineering_import_source_states",
    )
    op.drop_table("engineering_import_source_states")
    op.drop_index(
        op.f("ix_engineering_suit_engineering_states_state"),
        table_name="engineering_suit_engineering_states",
    )
    op.drop_table("engineering_suit_engineering_states")
    op.drop_index(
        op.f("ix_engineering_guardian_tech_progress_state"),
        table_name="engineering_guardian_tech_progress",
    )
    op.drop_table("engineering_guardian_tech_progress")
    op.drop_index(
        op.f("ix_engineering_engineer_unlock_states_state"),
        table_name="engineering_engineer_unlock_states",
    )
    op.drop_index(
        op.f("ix_engineering_engineer_unlock_states_engineer_label"),
        table_name="engineering_engineer_unlock_states",
    )
    op.drop_table("engineering_engineer_unlock_states")
    op.drop_index(
        op.f("ix_engineering_blueprint_progress_state"),
        table_name="engineering_blueprint_progress",
    )
    op.drop_index(
        op.f("ix_engineering_blueprint_progress_target_grade"),
        table_name="engineering_blueprint_progress",
    )
    op.drop_index(
        op.f("ix_engineering_blueprint_progress_blueprint_label"),
        table_name="engineering_blueprint_progress",
    )
    op.drop_table("engineering_blueprint_progress")
    op.drop_index(
        op.f("ix_engineering_acquisition_plans_state"),
        table_name="engineering_acquisition_plans",
    )
    op.drop_index(
        op.f("ix_engineering_acquisition_plans_title"),
        table_name="engineering_acquisition_plans",
    )
    op.drop_table("engineering_acquisition_plans")
    op.drop_index(
        op.f("ix_engineering_material_gap_overrides_material_id"),
        table_name="engineering_material_gap_overrides",
    )
    op.drop_index(
        op.f("ix_engineering_material_gap_overrides_build_plan_id"),
        table_name="engineering_material_gap_overrides",
    )
    op.drop_index(
        op.f("ix_engineering_material_gap_overrides_goal_id"),
        table_name="engineering_material_gap_overrides",
    )
    op.drop_table("engineering_material_gap_overrides")
    op.drop_index(
        op.f("ix_engineering_build_plans_state"),
        table_name="engineering_build_plans",
    )
    op.drop_index(
        op.f("ix_engineering_build_plans_format_verification_state"),
        table_name="engineering_build_plans",
    )
    op.drop_index(
        op.f("ix_engineering_build_plans_source"),
        table_name="engineering_build_plans",
    )
    op.drop_index(
        op.f("ix_engineering_build_plans_title"),
        table_name="engineering_build_plans",
    )
    op.drop_table("engineering_build_plans")
    op.drop_index(op.f("ix_engineering_goals_priority"), table_name="engineering_goals")
    op.drop_index(op.f("ix_engineering_goals_state"), table_name="engineering_goals")
    op.drop_index(
        op.f("ix_engineering_goals_target_kind"), table_name="engineering_goals"
    )
    op.drop_index(op.f("ix_engineering_goals_title"), table_name="engineering_goals")
    op.drop_table("engineering_goals")
