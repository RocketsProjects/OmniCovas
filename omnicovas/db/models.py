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

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    text as sa_text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):  # type: ignore[misc,unused-ignore]
    """Base class for all SQLAlchemy models."""

    pass


class NotificationShadowDecision(Base):
    """Local redacted diagnostic evidence, bounded independently of Activity Log."""

    __tablename__ = "notification_shadow_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    commander: Mapped[str | None] = mapped_column(String(64), index=True)
    candidate_id: Mapped[str] = mapped_column(String(160), nullable=False)
    evaluated_at: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    record_json: Mapped[str] = mapped_column(Text, nullable=False)


class NotificationShadowCheckpoint(Base):
    """Acknowledgement/high-water state only; never restores an active warning."""

    __tablename__ = "notification_shadow_checkpoints"
    commander: Mapped[str] = mapped_column(String(64), primary_key=True)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)


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


class EngineeringCatalogRef(Base):
    """Commander-supplied, locally persisted Engineering reference pack.

    The pack is reference data, never telemetry.  Its digest and declared
    provenance are stored beside the normalized JSON so every build remains
    explainable without an outbound lookup or a hidden global catalogue.
    """

    __tablename__ = "engineering_catalogs"

    catalog_key: Mapped[str] = mapped_column(String(192), primary_key=True)
    catalog_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license_label: Mapped[str] = mapped_column(String(128), nullable=False)
    rights_basis: Mapped[str] = mapped_column(String(256), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    catalog_json: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


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


class CommanderMemorySettings(Base):
    """Singleton local settings for the private Commander Memory service."""

    __tablename__ = "commander_memory_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_profile_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_rebuild_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommanderMemoryProfile(Base):
    """Pseudonymous local profile boundary for Commander Memory observations.

    A forgotten profile remains as a display-name-free tombstone so retained
    Journal history cannot silently repopulate it during a later rebuild.
    """

    __tablename__ = "commander_memory_profiles"

    profile_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    forgotten_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommanderMemoryRecord(Base):
    """Latest local observed-memory aggregate for one profile/category/entity."""

    __tablename__ = "commander_memory_records"
    __table_args__ = (
        UniqueConstraint(
            "profile_key",
            "category",
            "entity_key",
            name="uq_commander_memory_record_entity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("commander_memory_profiles.profile_key", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_key: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    parent_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    parent_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    visit_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    source_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(128), nullable=True)
    freshness: Mapped[str] = mapped_column(String(24), nullable=False)
    caveat: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    latest_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommanderMemoryObservation(Base):
    """Deduplication ledger for deterministic live ingestion and rebuilds."""

    __tablename__ = "commander_memory_observations"

    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_key: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("commander_memory_profiles.profile_key", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_key: Mapped[str] = mapped_column(String(256), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    source_event: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(128), nullable=True)


class GalacticIntelligenceEncounter(Base):
    """When OmniCOVAS last briefed a Commander about one documented place (GKI-04).

    An encounter is OmniCOVAS's own record of having briefed, never evidence that
    the Commander visited anything: it backs the frequency and cooldown preferences.
    Keyed by the Commander Memory profile so commanders never share history.
    """

    __tablename__ = "galactic_intelligence_encounters"
    __table_args__ = (
        UniqueConstraint(
            "profile_key", "encounter_key", name="uq_galactic_intelligence_encounter"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    encounter_key: Mapped[str] = mapped_column(String(160), nullable=False)
    first_briefed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_briefed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, index=True
    )
    briefing_count: Mapped[int] = mapped_column(Integer, nullable=False)


class GalacticIntelligenceBriefing(Base):
    """One automatic briefing and its dismissal (GKI-04).

    ``event_key`` identifies the Journal observation that produced it, so the same
    event delivered twice (catch-up, reconnect, restart) never briefs twice.
    """

    __tablename__ = "galactic_intelligence_briefings"
    __table_args__ = (
        UniqueConstraint(
            "profile_key", "event_key", name="uq_galactic_intelligence_briefing_event"
        ),
    )

    briefing_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    encounter_key: Mapped[str] = mapped_column(String(160), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class Expedition(Base):
    """A Commander's planned expedition (GKI-06).

    Commander-authored and keyed by the Commander Memory profile, so commanders
    never share expeditions; forgetting a commander deletes theirs.  ``story_json``
    holds the chapters the Commander has read and ``history_json`` the structured,
    Chronicle-ready record of what happened on the journey.
    """

    __tablename__ = "expeditions"

    expedition_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    entry: Mapped[str] = mapped_column(String(16), nullable=False)
    theme_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    narrative_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    goal_scope: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    story_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    history_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ExpeditionStop(Base):
    """One canonical stop on an expedition, with every reason for going (GKI-06).

    A documented place is one stop however many purposes it serves.  ``manual_state``
    is what the Commander said; ``evidence_json`` is what the Journal showed, kept
    apart so a skipped stop that was later reached still says both.
    """

    __tablename__ = "expedition_stops"
    __table_args__ = (
        UniqueConstraint("expedition_id", "stop_key", name="uq_expedition_stop_key"),
    )

    stop_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    expedition_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("expeditions.expedition_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    stop_key: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    place_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    system_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    system_address: Mapped[int | None] = mapped_column(nullable=True)
    purposes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    manual_state: Mapped[str] = mapped_column(String(16), nullable=False)
    manual_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ChronicleEntry(Base):
    """One entry in a Commander's Chronicle (GKI-07).

    Holds only what no other store keeps: Journal evidence at documented sites,
    bodies and stations that Commander Memory does not record (a landing, a body
    reached, an approach), Codex registrations, and what the Commander said (a
    confirmed visit, a saved story).  System and station visits are read from
    Commander Memory and journey progress from the expeditions, never copied here.
    ``fingerprint`` identifies the observation or the Commander's choice, so a
    replayed Journal line is never recorded twice; ``evidence`` is ``observed``
    (the Journal showed it) or ``commander`` (the Commander said so).
    """

    __tablename__ = "chronicle_entries"
    __table_args__ = (
        UniqueConstraint("profile_key", "fingerprint", name="uq_chronicle_entry"),
    )

    entry_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    profile_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source_event: Mapped[str | None] = mapped_column(String(32), nullable=True)
    replayed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class CommanderSystemNote(Base):
    """A Commander-authored note about a star system (LNA-004).

    Deliberately its own table rather than a field on a Commander Memory
    record: Memory is derived and a rebuild deletes and re-derives every
    record, which would destroy anything the Commander wrote by hand. This is
    authored data, so it outlives rebuilds and is owned by the Commander.

    One note per system, edited in place. The system name is the identity —
    notes are keyed by what the Commander sees, not by an address that a
    renamed or unresolved system could lose.
    """

    __tablename__ = "commander_system_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    star_system: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True, index=True
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    def __repr__(self) -> str:
        return f"<CommanderSystemNote system={self.star_system!r}>"


class ExobiologyRuleEvidence(Base):
    """One species observation weighed against the occurrence rules (Rule Sentinel).

    Retired with the legacy occurrence ruleset (FU-021, 2026-11-07). Nothing writes
    here any more. The table and its migration stay so existing local databases keep
    the evidence they recorded and the schema history remains linear.

    A confirmed ScanOrganic proves the species was present under the conditions the
    journal recorded for that body. Where the rules said that was impossible, the rule
    is wrong or incomplete, and this table is where that proof is kept.

    Deliberately its own table rather than a field on the journal event: the flight
    recorder holds what happened, unaltered, and must stay that way. This holds a
    judgement about what happened, made against a ruleset version that will change.
    Both are needed, and mixing them would let a rule update silently rewrite history.

    Identity is the species plus the body plus the predicate that was contradicted, so
    re-scanning the same colony increments a count rather than filing the same finding
    again. `ruleset_version` and `ruleset_sha256` pin which rules produced the verdict,
    so evidence recorded under an older ruleset is never reinterpreted as though the
    current rules had existed at observation time.
    """

    __tablename__ = "exobiology_rule_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    #: SUPPORTING_OBSERVATION | NEW_EMPIRICAL_EVIDENCE | RULE_CONTRADICTION
    classification: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #: OPEN | CORROBORATED | CANONICAL_UPDATE_PROPOSED | REJECTED_BAD_EVIDENCE
    #: | RESOLVED
    review_state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    species_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    species_name: Mapped[str] = mapped_column(String(128), nullable=False)
    genus: Mapped[str] = mapped_column(String(64), nullable=False)
    variant: Mapped[str | None] = mapped_column(String(128), nullable=True)

    star_system: Mapped[str | None] = mapped_column(String(128), nullable=True)
    system_address: Mapped[str | None] = mapped_column(String(32), nullable=True)
    body_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    body_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    #: Verdict the rules returned for this species at this body, before the
    #: observation was taken into account.
    evaluation_before_observation: Mapped[str] = mapped_column(
        String(16), nullable=False
    )
    contradicted_branch: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contradicted_predicate: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    #: The body facts the journal recorded, as JSON. Local scan values only.
    observed_facts: Mapped[str] = mapped_column(Text, nullable=False)

    ruleset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ruleset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    #: Always the local journal. Present so a future import path cannot be mistaken
    #: for first-hand telemetry.
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    first_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        UniqueConstraint(
            "species_id",
            "body_name",
            "contradicted_predicate",
            "ruleset_sha256",
            name="uq_exobiology_rule_evidence_identity",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ExobiologyRuleEvidence {self.classification} "
            f"species={self.species_id!r} body={self.body_name!r}>"
        )


class OperationsObjectiveRef(Base):
    """A Commander-entered objective for one Operations mode (PB14-R1).

    Answers "what am I trying to accomplish?" — Commander intent, never
    telemetry. The mode answers "what workflow am I viewing?" and readiness
    answers "am I ready?"; those are derived and live elsewhere. Nothing in
    this table is ever promoted to a fact.

    Deliberately its own table rather than a Commander Memory record: Memory
    is derived, and a rebuild deletes and re-derives every record, which would
    silently destroy authored intent during a maintenance action the Commander
    is told is safe. The same reasoning already governs
    :class:`CommanderSystemNote`.

    Identity is created once and never regenerated. Changing the text edits
    this row, because a restated goal is the same goal — closing and replacing
    it would manufacture a completion the Commander never declared.

    ``state`` reuses the Phase 9 campaign vocabulary rather than forking a
    second lifecycle language. Only three of its five values arise here:
    ``active``, ``completed`` and ``archived``. There is no proposal step, and
    an objective never becomes ``blocked`` — blockers are derived from
    readiness and an objective is not a blocker.

    At most one non-archived row exists per operation, enforced by a partial
    unique index: that row is the mode's current objective. Cleared objectives
    are archived, not deleted, so the Activity Log proof of what happened keeps
    the row it points at.
    """

    __tablename__ = "operations_objectives"

    objective_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    #: Operations mode key — the vocabulary in `readiness.OPERATION_PROFILES`.
    operation: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    #: Commander-authored free text. Private local state; never logged raw.
    text: Mapped[str] = mapped_column(Text, nullable=False)
    #: "active" | "completed" | "archived" (Phase 9 campaign vocabulary).
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    #: Always "commander_entered". Stored so a read cannot infer the class.
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Phase 14 R6 / `P14-H02`: the Commander's explicitly SELECTED target for
    #: this operation, held as structured columns beside the free text rather
    #: than parsed out of it. Mining needs to know "which commodity, how many
    #: tonnes" to report fill progress; reading that out of a sentence would
    #: mean guessing at Commander intent, which PB14-R1 forbids. Both are
    #: nullable because a Commander may state a goal without one.
    target_commodity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_activity_log_event_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        # One current objective per mode. Archived rows are history and are
        # deliberately outside the constraint so clearing never blocks the
        # next objective.
        Index(
            "uq_operations_objectives_current",
            "operation",
            unique=True,
            sqlite_where=sa_text("state != 'archived'"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<OperationsObjectiveRef operation={self.operation!r} "
            f"state={self.state!r}>"
        )
