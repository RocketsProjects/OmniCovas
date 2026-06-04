"""
omnicovas.db.models

SQLAlchemy database models for OmniCOVAS persistent storage.

Two databases are maintained separately:
    - session DB: event history, sessions, metadata
    - galaxy DB: bulk imported data (Spansh dumps, etc.) — Phase 5+

This module defines the session DB schema only.

Law 8 (Sovereignty & Transparency):
    All data stays on the local machine. Commander can export or delete
    at any time. Database is a plain SQLite file they own.

See: Master Blueprint v4.0 Section 3 (Tech Stack)
See: Phase 1 Development Guide Week 3, Part B
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):  # type: ignore[misc,unused-ignore]
    """Base class for all SQLAlchemy models."""

    pass


class Session(Base):
    """
    A commander session — from game launch to exit.

    Created on first event of a new journal file.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    commander_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ship_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    journal_filename: Mapped[str] = mapped_column(String(128), nullable=False)

    events: Mapped[list["JournalEvent"]] = relationship(
        "JournalEvent",
        back_populates="session",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Session id={self.id} cmdr={self.commander_name} "
            f"ship={self.ship_type} started={self.start_time}>"
        )


class JournalEvent(Base):
    """
    One journal event from Elite Dangerous.

    Stores the raw JSON line for full replay/audit capability.
    This is the black box recorder for OmniCOVAS.
    """

    __tablename__ = "journal_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sessions.id"), nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    raw_json: Mapped[str] = mapped_column(Text, nullable=False)

    session: Mapped[Session] = relationship("Session", back_populates="events")

    def __repr__(self) -> str:
        return f"<JournalEvent id={self.id} type={self.event_type} ts={self.timestamp}>"


class PvpEncounter(Base):
    """Local PvP encounter note owned by the commander."""

    __tablename__ = "pvp_encounters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    commander_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    system: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source_label: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    encounter_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    risk_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance_event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return (
            f"<PvpEncounter id={self.id} type={self.encounter_type} "
            f"source={self.source_label} ts={self.timestamp}>"
        )


class BookmarkRef(Base):
    """Local commander-managed bookmark for Navigation."""

    __tablename__ = "navigation_bookmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_system_address: Mapped[int | None] = mapped_column(nullable=True)
    x: Mapped[float | None] = mapped_column(nullable=True)
    y: Mapped[float | None] = mapped_column(nullable=True)
    z: Mapped[float | None] = mapped_column(nullable=True)
    commander_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]"
    )  # JSON list[str] — Phase 9 local-only tag vocabulary
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<BookmarkRef id={self.id} label={self.label} target={self.target_name}>"
        )


class SavedRouteRef(Base):
    """Local commander-managed saved route record for Navigation."""

    __tablename__ = "navigation_saved_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    origin: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    hop_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    commander_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return f"<SavedRouteRef id={self.id} label={self.label} to={self.destination}>"


class EngineeringGoalRef(Base):
    """Local commander-entered Engineering goal."""

    __tablename__ = "engineering_goals"

    goal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    commander_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_kind: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    target_reference_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_build_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    linked_material_gap_view_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    linked_acquisition_handoff_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    linked_operations_task_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    last_activity_log_event_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EngineeringBuildPlanRef(Base):
    """Local target build plan, separated from Intel current-loadout truth."""

    __tablename__ = "engineering_build_plans"

    build_plan_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_ship_json: Mapped[str] = mapped_column(Text, nullable=False)
    target_loadout_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    format_verification_state: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    linked_goal_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    linked_material_gap_view_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_activity_log_event_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EngineeringMaterialGapOverrideRef(Base):
    """Commander-entered material requirement/current-count override."""

    __tablename__ = "engineering_material_gap_overrides"

    gap_view_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    goal_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    build_plan_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    material_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    material_display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    commander_override_required: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    commander_override_current: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    required_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EngineeringAcquisitionPlanRef(Base):
    """Local persistent acquisition plan; route candidates stay in Navigation."""

    __tablename__ = "engineering_acquisition_plans"

    acquisition_plan_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    linked_goal_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    linked_build_plan_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    target_materials_json: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    navigation_handoff_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    operations_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_navigation_candidate_summary_json: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_activity_log_event_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EngineeringBlueprintProgressRef(Base):
    """Local/manual readiness tracking for a commander blueprint goal."""

    __tablename__ = "engineering_blueprint_progress"

    blueprint_progress_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    blueprint_label: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    target_engineer_label: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    target_module_label: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_grade: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    linked_material_gap_view_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    linked_engineer_unlock_state_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    linked_engineercraft_event_ids_json: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EngineeringEngineerUnlockStateRef(Base):
    """Local/manual engineer unlock state without global requirement claims."""

    __tablename__ = "engineering_engineer_unlock_states"

    engineer_unlock_state_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    engineer_label: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    last_engineerprogress_event_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    commander_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements_known: Mapped[str] = mapped_column(String(32), nullable=False)
    requirements_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EngineeringGuardianTechProgressRef(Base):
    """Local/manual Guardian tech readiness tracking."""

    __tablename__ = "engineering_guardian_tech_progress"

    guardian_tech_progress_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    guardian_tech_label: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    linked_techbroker_event_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    requirements_known: Mapped[str] = mapped_column(String(32), nullable=False)
    requirements_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EngineeringSuitEngineeringStateRef(Base):
    """Local/manual suit engineering readiness tracking."""

    __tablename__ = "engineering_suit_engineering_states"

    suit_engineering_state_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    suit_engineering_label: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    requirements_known: Mapped[str] = mapped_column(String(32), nullable=False)
    requirements_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EngineeringImportSourceStateRef(Base):
    """Disabled/source-gated build reference interop state."""

    __tablename__ = "engineering_import_source_states"

    import_source_state_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_label: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    format_version_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    format_verification_state: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    format_verification_evidence_summary: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    consent_state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    last_consent_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_import_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_export_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CampaignObjectiveRef(Base):
    """Phase 9 local commander-entered campaign objective (BGS or Powerplay).

    Local-only. No FK constraints to Intel or Navigation tables to avoid coupling.
    Linked Intel fact ids and Navigation circuit ids are weak string references stored
    as JSON lists.

    DELETE endpoint soft-archives only (archived_at set, row retained).
    PB09-03 scope: BGS and Powerplay campaign workflow only.
    """

    __tablename__ = "phase9_campaign_objectives"

    campaign_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # "bgs" | "powerplay"
    title: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_subject: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # faction name (bgs) or power name (powerplay); commander-entered
    target_system: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )  # Elite system name; commander-entered
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # "proposed" | "active" | "blocked" | "completed" | "archived"
    blockers_json: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # JSON list[str] — commander-entered short labels; redacted in Activity Log
    next_actions_json: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # JSON list[str] — commander-entered
    linked_intel_facts_json: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # JSON list[str] — Intel fact ids; weak links, no FK constraint
    linked_navigation_circuits_json: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # JSON list[str] — Navigation circuit ids; weak links, deferred PB09-04
    ai_draft_history_json: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # JSON list[dict] — entries carry is_fact=false, source_chain, confidence_label
    last_activity_log_event_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CampaignCircuitRef(Base):
    """Phase 9 local commander-entered BGS/Powerplay campaign circuit.

    Local-only. No FK constraints to Operations campaign objectives — linked_campaign_id
    is a weak string reference only.

    DELETE endpoint soft-archives only (archived_at set, row retained).
    PB09-04 scope: BGS and Powerplay circuit loops / saved route planning only.
    """

    __tablename__ = "phase9_campaign_circuits"

    circuit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # "bgs" | "powerplay"
    title: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_campaign_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )  # weak ref to CampaignObjectiveRef.campaign_id; no FK constraint
    source_label: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # "commander_entered" | "derived_from_navroute" | "spansh_link_out_only"
    last_activity_log_event_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<CampaignCircuitRef circuit_id={self.circuit_id} "
            f"type={self.workflow_type} title={self.title!r}>"
        )


class CampaignCircuitStopRef(Base):
    """One ordered stop in a Phase 9 local campaign circuit.

    Separate table (not JSON column) to support per-stop CRUD with individual IDs.
    circuit_id is a weak string ref (no FK) for consistency with Phase 9 cross-entity
    link patterns.
    """

    __tablename__ = "phase9_campaign_circuit_stops"

    stop_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    circuit_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )  # weak ref to CampaignCircuitRef.circuit_id; no FK constraint
    order_index: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # 1-based position within the circuit
    system_name: Mapped[str] = mapped_column(
        String(128), nullable=False
    )  # commander-entered Elite system name
    note: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # commander-entered short note; redacted in Activity Log
    linked_intel_fact_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # optional weak ref to an Intel fact id
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<CampaignCircuitStopRef stop_id={self.stop_id} "
            f"circuit={self.circuit_id} order={self.order_index} "
            f"system={self.system_name!r}>"
        )


class SquadronCampaignNote(Base):
    """Phase 9 local commander-entered squadron campaign note (PB09-05).

    Local-only. No FK constraints to Operations campaign objectives.
    linked_campaign_id is a weak string reference only — no FK constraint.

    DELETE endpoint soft-archives only (archived_at set, row retained).
    visibility is always 'local_only'. exported is always False.
    author is always 'local_commander'.
    PB09-05 scope: BGS and Powerplay local coordination notes only.
    """

    __tablename__ = "phase9_squadron_campaign_notes"

    note_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_type: Mapped[str] = mapped_column(
        String(16), nullable=False, index=True
    )  # "bgs" | "powerplay"
    linked_campaign_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )  # weak ref to CampaignObjectiveRef.campaign_id; no FK constraint
    note_text: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # commander-entered; redacted in Activity Log
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # always "local_only"; explicit makes boundary unmistakable in payloads
    exported: Mapped[bool] = mapped_column(
        Boolean, nullable=False
    )  # always False in Phase 9
    author: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # always "local_commander" in Phase 9
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<SquadronCampaignNote note_id={self.note_id} "
            f"type={self.workflow_type} visibility={self.visibility!r}>"
        )
