"""Pillar 1 event-type string constants — single source of truth.

Every ``broadcaster.subscribe(...)`` and ``broadcaster.publish(...)`` call
references a constant defined here. Importing a bad constant name raises
``ImportError`` at module-load time; using a magic string silently
registers a subscription that will never fire. The whole point of this
file is to make that second failure mode impossible.

New event types added in later Phase 2 weeks extend this module only —
they do not live in feature files. This keeps the Seven-Layer Debugging
Vocabulary layer boundary (layer 5 — broadcaster) sharp.

References:
    * Master Blueprint v4.1, Section 11 (Fault Tolerance — subscriber isolation).
    * Phase 2 Development Guide, Week 7 Part A, task 1.
    * Phase 2 Development Guide, Pillar 1 Event Type Reference (appendix).
    * CLAUDE.md Pattern 1 (Event Broadcasting).
"""

from __future__ import annotations

from typing import Final

# --- Core lifecycle ---------------------------------------------------------
# Published whenever any field of the ship's identity/state block changes
# enough that downstream subscribers may want a coalesced "something moved"
# signal. Fine-grained events below are the canonical path; SHIP_STATE_CHANGED
# is the catch-all for UI refreshes and Activity-Log summaries.
SHIP_STATE_CHANGED: Final[str] = "SHIP_STATE_CHANGED"
LOADOUT_CHANGED: Final[str] = "LOADOUT_CHANGED"

# --- Hull & shield (Week 9 — Hull & Integrity Triggers) ---------------------
# HULL_DAMAGE fires on every HullDamage journal event (combat subscribers).
# HULL_CRITICAL_* fire exactly once per downward threshold crossing.
HULL_DAMAGE: Final[str] = "HULL_DAMAGE"
HULL_CRITICAL_25: Final[str] = "HULL_CRITICAL_25"
HULL_CRITICAL_10: Final[str] = "HULL_CRITICAL_10"
SHIELDS_DOWN: Final[str] = "SHIELDS_DOWN"
SHIELDS_UP: Final[str] = "SHIELDS_UP"

# --- Fuel (Week 7 Parts C/D — Fuel & Jump Range) ----------------------------
FUEL_LOW: Final[str] = "FUEL_LOW"
FUEL_CRITICAL: Final[str] = "FUEL_CRITICAL"
RESERVOIR_REPLENISHED: Final[str] = "RESERVOIR_REPLENISHED"

# --- Navigation & location (Week 9 Part C — Extended Event Broadcaster) -----
FSD_JUMP: Final[str] = "FSD_JUMP"
DOCKED: Final[str] = "DOCKED"
UNDOCKED: Final[str] = "UNDOCKED"

# --- Commander status (Week 9 Part C) ---------------------------------------
# WANTED is per-system and clears on FSD jump to a different system.
WANTED: Final[str] = "WANTED"
DESTROYED: Final[str] = "DESTROYED"

# --- Power distribution (Week 9 Part D) -------------------------------------
PIPS_CHANGED: Final[str] = "PIPS_CHANGED"

# --- Heat management (Week 9 Part E — Tier 2) -------------------------------
HEAT_WARNING: Final[str] = "HEAT_WARNING"
# HEAT_DAMAGE maps to the real Elite journal HeatDamage event (distinct from
# threshold-inferred HEAT_WARNING so the overlay can label it separately).
HEAT_DAMAGE: Final[str] = "HEAT_DAMAGE"

# --- Cargo (Week 8 — Cargo Monitoring) --------------------------------------
CARGO_CHANGED: Final[str] = "CARGO_CHANGED"

# --- Modules (Week 8 Module Health + Week 9 Critical Event Broadcaster) -----
# MODULE_DAMAGED fires when a module's health crosses below 80%.
# MODULE_CRITICAL fires when a module's health crosses below 20%.
MODULE_DAMAGED: Final[str] = "MODULE_DAMAGED"
MODULE_CRITICAL: Final[str] = "MODULE_CRITICAL"

# --- Phase 4 -- Combat state ------------------------------------------------
COMBAT_STATE_CHANGED: Final[str] = "COMBAT_STATE_CHANGED"

# --- Phase 4 -- Interdiction / escape (D1B) ---------------------------------
# INTERDICTION_STARTED: Status.json bit 23 rising edge (being pulled from SC).
# INTERDICTION_ENDED:   EscapeInterdiction or Interdicted journal event.
INTERDICTION_STARTED: Final[str] = "INTERDICTION_STARTED"
INTERDICTION_ENDED: Final[str] = "INTERDICTION_ENDED"

# --- Phase 4 -- Critical response confirmation proposal (D4) ----------------
# Proposal-only audit events. Confirmation records commander review only and
# does not execute any game action.
CRITICAL_RESPONSE_PROPOSAL_SHOWN: Final[str] = "CRITICAL_RESPONSE_PROPOSAL_SHOWN"
CRITICAL_RESPONSE_PROPOSAL_CONFIRMED: Final[str] = (
    "CRITICAL_RESPONSE_PROPOSAL_CONFIRMED"
)
CRITICAL_RESPONSE_PROPOSAL_CANCELED: Final[str] = "CRITICAL_RESPONSE_PROPOSAL_CANCELED"
CRITICAL_RESPONSE_PROPOSAL_BLOCKED: Final[str] = "CRITICAL_RESPONSE_PROPOSAL_BLOCKED"

# --- Phase 4 -- PvP encounter local audit (E1A) ----------------------------
# Local-only commander note writes. These are Activity Log audit records, not
# external reputation claims.
PVP_ENCOUNTER_CREATED: Final[str] = "PVP_ENCOUNTER_CREATED"
PVP_ENCOUNTER_UPDATED: Final[str] = "PVP_ENCOUNTER_UPDATED"
PVP_ENCOUNTER_DELETED: Final[str] = "PVP_ENCOUNTER_DELETED"
PVP_ENCOUNTER_LINKED: Final[str] = "PVP_ENCOUNTER_LINKED"
PVP_ENCOUNTER_BLOCKED: Final[str] = "PVP_ENCOUNTER_BLOCKED"

# --- Phase 5 -- Source infrastructure proof records (PB05-02) ---------------
# Generic source-chain audit events. No provider-specific constants.
# SOURCE_REGISTRY_REGISTERED / SOURCE_HEALTH_UPDATED: registry lifecycle.
# Remaining six: Activity Log source-chain proof helpers (Stage D).
SOURCE_REGISTRY_REGISTERED: Final[str] = "SOURCE_REGISTRY_REGISTERED"
SOURCE_HEALTH_UPDATED: Final[str] = "SOURCE_HEALTH_UPDATED"
SOURCE_CHAIN_RESOLVED: Final[str] = "SOURCE_CHAIN_RESOLVED"
EXTERNAL_REQUEST_QUEUED: Final[str] = "EXTERNAL_REQUEST_QUEUED"
EXTERNAL_REQUEST_BLOCKED: Final[str] = "EXTERNAL_REQUEST_BLOCKED"
SOURCE_RATE_LIMITED: Final[str] = "SOURCE_RATE_LIMITED"
SOURCE_CACHE_HIT: Final[str] = "SOURCE_CACHE_HIT"
SOURCE_STALE_CACHE_USE: Final[str] = "SOURCE_STALE_CACHE_USE"

# --- Phase 4 -- Combat session (PB04-06 F1/F3) ------------------------------
# Schema-locked to verified Frontier journal events. Active CZ detection and
# CZ kind (low/medium/high) remain Unsupported -- no verified local source.
# MISSION_SNAPSHOT_LOADED fires from the startup Missions event (Active[]
# present is not proof a session "started"); MISSION_ADDED fires from
# MissionAccepted only. Combat reward totals derive only from RedeemVoucher
# Type=bounty / Type=CombatBond -- MissionCompleted.Reward is not counted.
COMBAT_SESSION_STATE_CHANGED: Final[str] = "COMBAT_SESSION_STATE_CHANGED"
MISSION_SNAPSHOT_LOADED: Final[str] = "MISSION_SNAPSHOT_LOADED"
MISSION_ADDED: Final[str] = "MISSION_ADDED"
MISSION_COMPLETED: Final[str] = "MISSION_COMPLETED"
MISSION_FAILED: Final[str] = "MISSION_FAILED"
MISSION_ABANDONED: Final[str] = "MISSION_ABANDONED"
MISSION_REDIRECTED: Final[str] = "MISSION_REDIRECTED"
LOCAL_CONFLICT_CONTEXT_UPDATED: Final[str] = "LOCAL_CONFLICT_CONTEXT_UPDATED"
COMBAT_REWARD_SUMMARY_UPDATED: Final[str] = "COMBAT_REWARD_SUMMARY_UPDATED"
COMBAT_RANK_UPDATED: Final[str] = "COMBAT_RANK_UPDATED"

# --- Phase 5 -- Navigation bookmarks and saved routes (PB05-09) ------------
NAVIGATION_BOOKMARK_CREATED: Final[str] = "NAVIGATION_BOOKMARK_CREATED"
NAVIGATION_BOOKMARK_UPDATED: Final[str] = "NAVIGATION_BOOKMARK_UPDATED"
NAVIGATION_BOOKMARK_DELETED: Final[str] = "NAVIGATION_BOOKMARK_DELETED"
NAVIGATION_SAVED_ROUTE_CREATED: Final[str] = "NAVIGATION_SAVED_ROUTE_CREATED"
NAVIGATION_SAVED_ROUTE_UPDATED: Final[str] = "NAVIGATION_SAVED_ROUTE_UPDATED"
NAVIGATION_SAVED_ROUTE_DELETED: Final[str] = "NAVIGATION_SAVED_ROUTE_DELETED"

# --- Phase 7 -- Squadrons local-only foundation (PB07-03) -----------------
SQUADRON_STATE_CHANGED: Final[str] = "SQUADRON_STATE_CHANGED"

# --- Phase 7 -- Squadrons local write/revoke proof events (PB07-07) --------
SQUADRON_ROSTER_CREATED: Final[str] = "SQUADRON_ROSTER_CREATED"
SQUADRON_ROSTER_REVOKED: Final[str] = "SQUADRON_ROSTER_REVOKED"
SQUADRON_INVITE_CREATED: Final[str] = "SQUADRON_INVITE_CREATED"
SQUADRON_INVITE_REVOKED: Final[str] = "SQUADRON_INVITE_REVOKED"
SQUADRON_ROLE_CREATED: Final[str] = "SQUADRON_ROLE_CREATED"
SQUADRON_ROLE_REVOKED: Final[str] = "SQUADRON_ROLE_REVOKED"
SQUADRON_SHARED_OP_CREATED: Final[str] = "SQUADRON_SHARED_OP_CREATED"
SQUADRON_SHARED_OP_REVOKED: Final[str] = "SQUADRON_SHARED_OP_REVOKED"
SQUADRON_SHARED_NAV_CREATED: Final[str] = "SQUADRON_SHARED_NAV_CREATED"
SQUADRON_SHARED_NAV_REVOKED: Final[str] = "SQUADRON_SHARED_NAV_REVOKED"
SQUADRON_EMERGENCY_NOTE_CREATED: Final[str] = "SQUADRON_EMERGENCY_NOTE_CREATED"
SQUADRON_EMERGENCY_NOTE_REVOKED: Final[str] = "SQUADRON_EMERGENCY_NOTE_REVOKED"
SQUADRON_LOG_APPENDED: Final[str] = "SQUADRON_LOG_APPENDED"
SQUADRON_RESERVED_INTENT_BLOCKED: Final[str] = "SQUADRON_RESERVED_INTENT_BLOCKED"

# --- Phase 8 -- Engineering local planning proof events ---------------------
ENGINEERING_GOAL_CREATED: Final[str] = "engineering.goal.created"
ENGINEERING_GOAL_UPDATED: Final[str] = "engineering.goal.updated"
ENGINEERING_GOAL_STATE_CHANGED: Final[str] = "engineering.goal.state_changed"
ENGINEERING_GOAL_COMPLETED: Final[str] = "engineering.goal.completed"
ENGINEERING_GOAL_ARCHIVED: Final[str] = "engineering.goal.archived"
ENGINEERING_BUILDPLAN_CREATED: Final[str] = "engineering.buildplan.created"
ENGINEERING_BUILDPLAN_UPDATED: Final[str] = "engineering.buildplan.updated"
ENGINEERING_BUILDPLAN_IMPORTED: Final[str] = "engineering.buildplan.imported"
ENGINEERING_BUILDPLAN_FORMAT_VERIFICATION_CHANGED: Final[str] = (
    "engineering.buildplan.format_verification_changed"
)
ENGINEERING_BUILDPLAN_STATE_CHANGED: Final[str] = "engineering.buildplan.state_changed"
ENGINEERING_BUILDPLAN_EXPORTED: Final[str] = "engineering.buildplan.exported"
ENGINEERING_BUILDPLAN_EXPORT_REMOTE_ATTEMPTED: Final[str] = (
    "engineering.buildplan.export_remote_attempted"
)
ENGINEERING_BUILDPLAN_ARCHIVED: Final[str] = "engineering.buildplan.archived"
ENGINEERING_MATERIAL_GAP_COMPUTED: Final[str] = "engineering.material_gap.computed"
ENGINEERING_MATERIAL_GAP_OVERRIDE_SET: Final[str] = (
    "engineering.material_gap.override_set"
)
ENGINEERING_MATERIAL_GAP_OVERRIDE_CLEARED: Final[str] = (
    "engineering.material_gap.override_cleared"
)
ENGINEERING_ACQUISITION_PLAN_CREATED: Final[str] = (
    "engineering.acquisition_plan.created"
)
ENGINEERING_ACQUISITION_PLAN_UPDATED: Final[str] = (
    "engineering.acquisition_plan.updated"
)
ENGINEERING_ACQUISITION_PLAN_STATE_CHANGED: Final[str] = (
    "engineering.acquisition_plan.state_changed"
)
ENGINEERING_ACQUISITION_PLAN_COMPLETED_VIA_OPERATIONS: Final[str] = (
    "engineering.acquisition_plan.completed_via_operations"
)
ENGINEERING_ACQUISITION_PLAN_TASK_ABANDONED_VIA_OPERATIONS: Final[str] = (
    "engineering.acquisition_plan.task_abandoned_via_operations"
)
ENGINEERING_ACQUISITION_PLAN_ARCHIVED: Final[str] = (
    "engineering.acquisition_plan.archived"
)
ENGINEERING_ACQUISITION_HANDOFF_TO_NAVIGATION: Final[str] = (
    "engineering.acquisition.handoff_to_navigation"
)
ENGINEERING_ACQUISITION_CANDIDATES_RETURNED: Final[str] = (
    "engineering.acquisition.candidates_returned"
)
ENGINEERING_ACQUISITION_CANDIDATE_SELECTED: Final[str] = (
    "engineering.acquisition.candidate_selected"
)
ENGINEERING_TASK_HANDOFF_TO_OPERATIONS: Final[str] = (
    "engineering.task.handoff_to_operations"
)
ENGINEERING_BLUEPRINT_PROGRESS_CREATED: Final[str] = (
    "engineering.blueprint_progress.created"
)
ENGINEERING_BLUEPRINT_PROGRESS_UPDATED: Final[str] = (
    "engineering.blueprint_progress.updated"
)
ENGINEERING_BLUEPRINT_PROGRESS_STATE_CHANGED: Final[str] = (
    "engineering.blueprint_progress.state_changed"
)
ENGINEERING_ENGINEER_UNLOCK_STATE_CREATED: Final[str] = (
    "engineering.engineer_unlock_state.created"
)
ENGINEERING_ENGINEER_UNLOCK_STATE_UPDATED: Final[str] = (
    "engineering.engineer_unlock_state.updated"
)
ENGINEERING_GUARDIAN_TECH_PROGRESS_CREATED: Final[str] = (
    "engineering.guardian_tech_progress.created"
)
ENGINEERING_GUARDIAN_TECH_PROGRESS_UPDATED: Final[str] = (
    "engineering.guardian_tech_progress.updated"
)
ENGINEERING_SUIT_ENGINEERING_STATE_CREATED: Final[str] = (
    "engineering.suit_engineering_state.created"
)
ENGINEERING_SUIT_ENGINEERING_STATE_UPDATED: Final[str] = (
    "engineering.suit_engineering_state.updated"
)
ENGINEERING_READINESS_COMMANDER_NOTE_SET: Final[str] = (
    "engineering.readiness.commander_note_set"
)
ENGINEERING_IMPORT_FORMAT_VERIFIED: Final[str] = "engineering.import.format_verified"
ENGINEERING_IMPORT_FORMAT_REJECTED: Final[str] = "engineering.import.format_rejected"
ENGINEERING_IMPORT_SOURCE_STATE_CREATED: Final[str] = (
    "engineering.import_source_state.created"
)
ENGINEERING_IMPORT_SOURCE_STATE_UPDATED: Final[str] = (
    "engineering.import_source_state.updated"
)
ENGINEERING_PRIVACY_CONSENT_CHANGED: Final[str] = "engineering.privacy.consent_changed"
ENGINEERING_SOURCE_ATTEMPT_BLOCKED: Final[str] = "engineering.source_attempt.blocked"
ENGINEERING_SOURCE_ATTEMPT_DISABLED: Final[str] = "engineering.source_attempt.disabled"
ENGINEERING_SOURCE_ATTEMPT_FAILED: Final[str] = "engineering.source_attempt.failed"
ENGINEERING_HANDOFF_TO_INTEL: Final[str] = "engineering.handoff_to_intel"
ENGINEERING_HANDOFF_TO_NAVIGATION: Final[str] = "engineering.handoff_to_navigation"
ENGINEERING_HANDOFF_TO_OPERATIONS: Final[str] = "engineering.handoff_to_operations"
ENGINEERING_HANDOFF_TO_SETTINGS: Final[str] = "engineering.handoff_to_settings"
ENGINEERING_HANDOFF_TO_ACTIVITY_LOG: Final[str] = "engineering.handoff_to_activity_log"
ENGINEERING_AI_DRAFT_EMITTED: Final[str] = "engineering.ai.draft_emitted"

# --- Phase 9 -- Intel BGS / Powerplay local fact projection -----------------
# PB09-07 canonical Activity Log proof taxonomy. Observation-specific events are
# registered for proof filtering; active emitters remain limited to approved
# Phase 9 runtime flows.
PHASE_9_BGS_FACTS_PROJECTED: Final[str] = "phase_9.bgs.facts_projected"
PHASE_9_BGS_FACTION_OBSERVATION_RECORDED: Final[str] = (
    "phase_9.bgs.faction_observation_recorded"
)
PHASE_9_BGS_FACTION_EFFECTS_PROJECTED: Final[str] = (
    "phase_9.bgs.faction_effects_projected"
)
PHASE_9_POWERPLAY_FACTS_PROJECTED: Final[str] = "phase_9.powerplay.facts_projected"
PHASE_9_POWERPLAY_PLEDGE_CHANGED: Final[str] = "phase_9.powerplay.pledge_changed"
PHASE_9_POWERPLAY_RANK_OBSERVED: Final[str] = "phase_9.powerplay.rank_observed"
PHASE_9_POWERPLAY_MERITS_OBSERVED: Final[str] = "phase_9.powerplay.merits_observed"
PHASE_9_POWERPLAY_COLLECT_OBSERVED: Final[str] = "phase_9.powerplay.collect_observed"
PHASE_9_POWERPLAY_DELIVER_OBSERVED: Final[str] = "phase_9.powerplay.deliver_observed"
PHASE_9_POWERPLAY_VOTE_OBSERVED: Final[str] = "phase_9.powerplay.vote_observed"
PHASE_9_POWERPLAY_VOUCHER_OBSERVED: Final[str] = "phase_9.powerplay.voucher_observed"
PHASE_9_POWERPLAY_SALARY_OBSERVED: Final[str] = "phase_9.powerplay.salary_observed"
PHASE_9_POWERPLAY_FAST_TRACK_OBSERVED: Final[str] = (
    "phase_9.powerplay.fast_track_observed"
)
PHASE_9_POWERPLAY_MICRO_RESOURCE_REQUESTED: Final[str] = (
    "phase_9.powerplay.micro_resource_requested"
)
PHASE_9_POWERPLAY_MICRO_RESOURCE_DELIVERED: Final[str] = (
    "phase_9.powerplay.micro_resource_delivered"
)

# --- Phase 9 -- Campaign objective proof events (PB09-03) -------------------
# Canonical Activity Log payload shape is owned by PB09-07.
# PB09-03 emits these events with minimal redacted payloads:
#   campaign_id, workflow_type, state (where applicable), title_length,
#   source_chain (for ai_draft_emitted), redacted=True.
# No raw private text (title, description, blockers, next_actions) in payloads.
PHASE_9_CAMPAIGN_OBJECTIVE_CREATED: Final[str] = "phase_9.campaign.objective_created"
PHASE_9_CAMPAIGN_OBJECTIVE_UPDATED: Final[str] = "phase_9.campaign.objective_updated"
PHASE_9_CAMPAIGN_OBJECTIVE_STATE_CHANGED: Final[str] = (
    "phase_9.campaign.objective_state_changed"
)
PHASE_9_CAMPAIGN_OBJECTIVE_BLOCKED: Final[str] = "phase_9.campaign.objective_blocked"
PHASE_9_CAMPAIGN_OBJECTIVE_COMPLETED: Final[str] = (
    "phase_9.campaign.objective_completed"
)
PHASE_9_CAMPAIGN_OBJECTIVE_ARCHIVED: Final[str] = "phase_9.campaign.objective_archived"
PHASE_9_CAMPAIGN_INTEL_FACT_LINKED: Final[str] = "phase_9.campaign.intel_fact_linked"
PHASE_9_CAMPAIGN_INTEL_FACT_UNLINKED: Final[str] = (
    "phase_9.campaign.intel_fact_unlinked"
)
PHASE_9_CAMPAIGN_NAVIGATION_CIRCUIT_LINKED: Final[str] = (
    "phase_9.campaign.navigation_circuit_linked"
)
PHASE_9_CAMPAIGN_NAVIGATION_CIRCUIT_UNLINKED: Final[str] = (
    "phase_9.campaign.navigation_circuit_unlinked"
)
PHASE_9_CAMPAIGN_AI_DRAFT_EMITTED: Final[str] = "phase_9.campaign.ai_draft_emitted"
PHASE_9_CAMPAIGN_AI_DRAFT_CONFIRMED_GATE: Final[str] = (
    "phase_9.campaign.ai_draft_confirmed_gate"
)
PHASE_9_CAMPAIGN_AI_DRAFT_CANCELED_GATE: Final[str] = (
    "phase_9.campaign.ai_draft_canceled_gate"
)
PHASE_9_CAMPAIGN_AI_DRAFT_VALIDATION_FAILED: Final[str] = (
    "phase_9.campaign.ai_draft_rejected_validation"
)
PHASE_9_CAMPAIGN_AI_DRAFT_REQUESTED_GATE_SHOWN: Final[str] = (
    "phase_9.campaign.ai_draft_requested_gate_shown"
)
PHASE_9_CAMPAIGN_AI_DRAFT_REJECTED_VALIDATION: Final[str] = (
    "phase_9.campaign.ai_draft_rejected_validation"
)
PHASE_9_CAMPAIGN_HANDOFF_TO_INTEL: Final[str] = "phase_9.campaign.handoff_to_intel"
PHASE_9_CAMPAIGN_HANDOFF_TO_NAVIGATION: Final[str] = (
    "phase_9.campaign.handoff_to_navigation"
)
PHASE_9_CAMPAIGN_HANDOFF_TO_SQUADRONS: Final[str] = (
    "phase_9.campaign.handoff_to_squadrons"
)
PHASE_9_CAMPAIGN_HANDOFF_TO_ACTIVITY_LOG: Final[str] = (
    "phase_9.campaign.handoff_to_activity_log"
)

# --- Phase 9 -- Navigation campaign circuit proof events (PB09-04) ----------
# Canonical Activity Log payload shape is owned by PB09-07.
# PB09-04 emits these events with minimal redacted payloads:
#   circuit_id, workflow_type, stop_count (where applicable), source_label,
#   linked_campaign_id (where applicable), tag (where applicable), redacted=True.
# No raw private text (title, system_name, note) in payloads.
PHASE_9_NAVIGATION_CIRCUIT_CREATED: Final[str] = "phase_9.navigation.circuit_created"
PHASE_9_NAVIGATION_CIRCUIT_UPDATED: Final[str] = "phase_9.navigation.circuit_updated"
PHASE_9_NAVIGATION_CIRCUIT_ARCHIVED: Final[str] = "phase_9.navigation.circuit_archived"
PHASE_9_NAVIGATION_STOP_ADDED: Final[str] = "phase_9.navigation.stop_added"
PHASE_9_NAVIGATION_STOP_UPDATED: Final[str] = "phase_9.navigation.stop_updated"
PHASE_9_NAVIGATION_STOP_REMOVED: Final[str] = "phase_9.navigation.stop_removed"
PHASE_9_NAVIGATION_BOOKMARK_TAGGED: Final[str] = "phase_9.navigation.bookmark_tagged"
PHASE_9_NAVIGATION_CIRCUIT_LINKED_TO_CAMPAIGN: Final[str] = (
    "phase_9.navigation.circuit_linked_to_campaign"
)
PHASE_9_NAVIGATION_CIRCUIT_UNLINKED_FROM_CAMPAIGN: Final[str] = (
    "phase_9.navigation.circuit_unlinked_from_campaign"
)
PHASE_9_NAVIGATION_SPANSH_LINK_OPENED: Final[str] = (
    "phase_9.navigation.spansh_link_opened"
)

# --- Phase 9 -- Squadron local campaign note proof events (PB09-05) ----------
# Canonical Activity Log payload shape is owned by PB09-07.
# PB09-05 emits these events with minimal redacted payloads:
#   note_id, linked_campaign_id (where applicable), workflow_type, visibility,
#   redacted=True, exported=False.
# No raw note_text, no CMDR names, no squadron member identifiers in payloads.
PHASE_9_SQUADRON_LOCAL_NOTE_CREATED: Final[str] = "phase_9.squadron.local_note_created"
PHASE_9_SQUADRON_LOCAL_NOTE_UPDATED: Final[str] = "phase_9.squadron.local_note_updated"
PHASE_9_SQUADRON_LOCAL_NOTE_ARCHIVED: Final[str] = (
    "phase_9.squadron.local_note_archived"
)
PHASE_9_SQUADRON_LOCAL_NOTE_LINKED_TO_CAMPAIGN: Final[str] = (
    "phase_9.squadron.local_note_linked_to_campaign"
)
PHASE_9_SQUADRON_LOCAL_NOTE_UNLINKED_FROM_CAMPAIGN: Final[str] = (
    "phase_9.squadron.local_note_unlinked_from_campaign"
)

# --- Phase 9 -- source attempt proof events (PB09-07) -----------------------
PHASE_9_SOURCE_ATTEMPT_BLOCKED: Final[str] = "phase_9.source_attempt_blocked"
PHASE_9_SOURCE_ATTEMPT_DISABLED: Final[str] = "phase_9.source_attempt_disabled"
PHASE_9_SOURCE_ATTEMPT_REQUIRES_AUTH: Final[str] = (
    "phase_9.source_attempt_requires_auth"
)
PHASE_9_SOURCE_ATTEMPT_UNSUPPORTED: Final[str] = "phase_9.source_attempt_unsupported"
PHASE_9_SOURCE_ATTEMPT_NO_VERIFIED_SOURCE: Final[str] = (
    "phase_9.source_attempt_no_verified_source"
)


# Audit aid: every constant exported by this module. Used by the Week 9
# Critical Event Broadcaster audit test to guarantee no event-type
# constant is referenced before it is declared here.
ALL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        SHIP_STATE_CHANGED,
        LOADOUT_CHANGED,
        HULL_DAMAGE,
        HULL_CRITICAL_25,
        HULL_CRITICAL_10,
        SHIELDS_DOWN,
        SHIELDS_UP,
        FUEL_LOW,
        FUEL_CRITICAL,
        RESERVOIR_REPLENISHED,
        FSD_JUMP,
        DOCKED,
        UNDOCKED,
        WANTED,
        DESTROYED,
        PIPS_CHANGED,
        HEAT_WARNING,
        HEAT_DAMAGE,
        CARGO_CHANGED,
        MODULE_DAMAGED,
        MODULE_CRITICAL,
        COMBAT_STATE_CHANGED,
        INTERDICTION_STARTED,
        INTERDICTION_ENDED,
        CRITICAL_RESPONSE_PROPOSAL_SHOWN,
        CRITICAL_RESPONSE_PROPOSAL_CONFIRMED,
        CRITICAL_RESPONSE_PROPOSAL_CANCELED,
        CRITICAL_RESPONSE_PROPOSAL_BLOCKED,
        PVP_ENCOUNTER_CREATED,
        PVP_ENCOUNTER_UPDATED,
        PVP_ENCOUNTER_DELETED,
        PVP_ENCOUNTER_LINKED,
        PVP_ENCOUNTER_BLOCKED,
        COMBAT_SESSION_STATE_CHANGED,
        MISSION_SNAPSHOT_LOADED,
        MISSION_ADDED,
        MISSION_COMPLETED,
        MISSION_FAILED,
        MISSION_ABANDONED,
        MISSION_REDIRECTED,
        LOCAL_CONFLICT_CONTEXT_UPDATED,
        COMBAT_REWARD_SUMMARY_UPDATED,
        COMBAT_RANK_UPDATED,
        SOURCE_REGISTRY_REGISTERED,
        SOURCE_HEALTH_UPDATED,
        SOURCE_CHAIN_RESOLVED,
        EXTERNAL_REQUEST_QUEUED,
        EXTERNAL_REQUEST_BLOCKED,
        SOURCE_RATE_LIMITED,
        SOURCE_CACHE_HIT,
        SOURCE_STALE_CACHE_USE,
        NAVIGATION_BOOKMARK_CREATED,
        NAVIGATION_BOOKMARK_UPDATED,
        NAVIGATION_BOOKMARK_DELETED,
        NAVIGATION_SAVED_ROUTE_CREATED,
        NAVIGATION_SAVED_ROUTE_UPDATED,
        NAVIGATION_SAVED_ROUTE_DELETED,
        SQUADRON_STATE_CHANGED,
        SQUADRON_ROSTER_CREATED,
        SQUADRON_ROSTER_REVOKED,
        SQUADRON_INVITE_CREATED,
        SQUADRON_INVITE_REVOKED,
        SQUADRON_ROLE_CREATED,
        SQUADRON_ROLE_REVOKED,
        SQUADRON_SHARED_OP_CREATED,
        SQUADRON_SHARED_OP_REVOKED,
        SQUADRON_SHARED_NAV_CREATED,
        SQUADRON_SHARED_NAV_REVOKED,
        SQUADRON_EMERGENCY_NOTE_CREATED,
        SQUADRON_EMERGENCY_NOTE_REVOKED,
        SQUADRON_LOG_APPENDED,
        SQUADRON_RESERVED_INTENT_BLOCKED,
        ENGINEERING_GOAL_CREATED,
        ENGINEERING_GOAL_UPDATED,
        ENGINEERING_GOAL_STATE_CHANGED,
        ENGINEERING_GOAL_COMPLETED,
        ENGINEERING_GOAL_ARCHIVED,
        ENGINEERING_BUILDPLAN_CREATED,
        ENGINEERING_BUILDPLAN_UPDATED,
        ENGINEERING_BUILDPLAN_IMPORTED,
        ENGINEERING_BUILDPLAN_FORMAT_VERIFICATION_CHANGED,
        ENGINEERING_BUILDPLAN_STATE_CHANGED,
        ENGINEERING_BUILDPLAN_EXPORTED,
        ENGINEERING_BUILDPLAN_EXPORT_REMOTE_ATTEMPTED,
        ENGINEERING_BUILDPLAN_ARCHIVED,
        ENGINEERING_MATERIAL_GAP_COMPUTED,
        ENGINEERING_MATERIAL_GAP_OVERRIDE_SET,
        ENGINEERING_MATERIAL_GAP_OVERRIDE_CLEARED,
        ENGINEERING_ACQUISITION_PLAN_CREATED,
        ENGINEERING_ACQUISITION_PLAN_UPDATED,
        ENGINEERING_ACQUISITION_PLAN_STATE_CHANGED,
        ENGINEERING_ACQUISITION_PLAN_COMPLETED_VIA_OPERATIONS,
        ENGINEERING_ACQUISITION_PLAN_TASK_ABANDONED_VIA_OPERATIONS,
        ENGINEERING_ACQUISITION_PLAN_ARCHIVED,
        ENGINEERING_ACQUISITION_HANDOFF_TO_NAVIGATION,
        ENGINEERING_ACQUISITION_CANDIDATES_RETURNED,
        ENGINEERING_ACQUISITION_CANDIDATE_SELECTED,
        ENGINEERING_TASK_HANDOFF_TO_OPERATIONS,
        ENGINEERING_BLUEPRINT_PROGRESS_CREATED,
        ENGINEERING_BLUEPRINT_PROGRESS_UPDATED,
        ENGINEERING_BLUEPRINT_PROGRESS_STATE_CHANGED,
        ENGINEERING_ENGINEER_UNLOCK_STATE_CREATED,
        ENGINEERING_ENGINEER_UNLOCK_STATE_UPDATED,
        ENGINEERING_GUARDIAN_TECH_PROGRESS_CREATED,
        ENGINEERING_GUARDIAN_TECH_PROGRESS_UPDATED,
        ENGINEERING_SUIT_ENGINEERING_STATE_CREATED,
        ENGINEERING_SUIT_ENGINEERING_STATE_UPDATED,
        ENGINEERING_READINESS_COMMANDER_NOTE_SET,
        ENGINEERING_IMPORT_FORMAT_VERIFIED,
        ENGINEERING_IMPORT_FORMAT_REJECTED,
        ENGINEERING_IMPORT_SOURCE_STATE_CREATED,
        ENGINEERING_IMPORT_SOURCE_STATE_UPDATED,
        ENGINEERING_PRIVACY_CONSENT_CHANGED,
        ENGINEERING_SOURCE_ATTEMPT_BLOCKED,
        ENGINEERING_SOURCE_ATTEMPT_DISABLED,
        ENGINEERING_SOURCE_ATTEMPT_FAILED,
        ENGINEERING_HANDOFF_TO_INTEL,
        ENGINEERING_HANDOFF_TO_NAVIGATION,
        ENGINEERING_HANDOFF_TO_OPERATIONS,
        ENGINEERING_HANDOFF_TO_SETTINGS,
        ENGINEERING_HANDOFF_TO_ACTIVITY_LOG,
        ENGINEERING_AI_DRAFT_EMITTED,
        PHASE_9_BGS_FACTS_PROJECTED,
        PHASE_9_BGS_FACTION_OBSERVATION_RECORDED,
        PHASE_9_BGS_FACTION_EFFECTS_PROJECTED,
        PHASE_9_POWERPLAY_FACTS_PROJECTED,
        PHASE_9_POWERPLAY_PLEDGE_CHANGED,
        PHASE_9_POWERPLAY_RANK_OBSERVED,
        PHASE_9_POWERPLAY_MERITS_OBSERVED,
        PHASE_9_POWERPLAY_COLLECT_OBSERVED,
        PHASE_9_POWERPLAY_DELIVER_OBSERVED,
        PHASE_9_POWERPLAY_VOTE_OBSERVED,
        PHASE_9_POWERPLAY_VOUCHER_OBSERVED,
        PHASE_9_POWERPLAY_SALARY_OBSERVED,
        PHASE_9_POWERPLAY_FAST_TRACK_OBSERVED,
        PHASE_9_POWERPLAY_MICRO_RESOURCE_REQUESTED,
        PHASE_9_POWERPLAY_MICRO_RESOURCE_DELIVERED,
        PHASE_9_CAMPAIGN_OBJECTIVE_CREATED,
        PHASE_9_CAMPAIGN_OBJECTIVE_UPDATED,
        PHASE_9_CAMPAIGN_OBJECTIVE_STATE_CHANGED,
        PHASE_9_CAMPAIGN_OBJECTIVE_BLOCKED,
        PHASE_9_CAMPAIGN_OBJECTIVE_COMPLETED,
        PHASE_9_CAMPAIGN_OBJECTIVE_ARCHIVED,
        PHASE_9_CAMPAIGN_INTEL_FACT_LINKED,
        PHASE_9_CAMPAIGN_INTEL_FACT_UNLINKED,
        PHASE_9_CAMPAIGN_NAVIGATION_CIRCUIT_LINKED,
        PHASE_9_CAMPAIGN_NAVIGATION_CIRCUIT_UNLINKED,
        PHASE_9_CAMPAIGN_AI_DRAFT_REQUESTED_GATE_SHOWN,
        PHASE_9_CAMPAIGN_AI_DRAFT_EMITTED,
        PHASE_9_CAMPAIGN_AI_DRAFT_CONFIRMED_GATE,
        PHASE_9_CAMPAIGN_AI_DRAFT_CANCELED_GATE,
        PHASE_9_CAMPAIGN_AI_DRAFT_VALIDATION_FAILED,
        PHASE_9_CAMPAIGN_HANDOFF_TO_INTEL,
        PHASE_9_CAMPAIGN_HANDOFF_TO_NAVIGATION,
        PHASE_9_CAMPAIGN_HANDOFF_TO_SQUADRONS,
        PHASE_9_CAMPAIGN_HANDOFF_TO_ACTIVITY_LOG,
        PHASE_9_NAVIGATION_CIRCUIT_CREATED,
        PHASE_9_NAVIGATION_CIRCUIT_UPDATED,
        PHASE_9_NAVIGATION_CIRCUIT_ARCHIVED,
        PHASE_9_NAVIGATION_STOP_ADDED,
        PHASE_9_NAVIGATION_STOP_UPDATED,
        PHASE_9_NAVIGATION_STOP_REMOVED,
        PHASE_9_NAVIGATION_BOOKMARK_TAGGED,
        PHASE_9_NAVIGATION_CIRCUIT_LINKED_TO_CAMPAIGN,
        PHASE_9_NAVIGATION_CIRCUIT_UNLINKED_FROM_CAMPAIGN,
        PHASE_9_NAVIGATION_SPANSH_LINK_OPENED,
        PHASE_9_SQUADRON_LOCAL_NOTE_CREATED,
        PHASE_9_SQUADRON_LOCAL_NOTE_UPDATED,
        PHASE_9_SQUADRON_LOCAL_NOTE_ARCHIVED,
        PHASE_9_SQUADRON_LOCAL_NOTE_LINKED_TO_CAMPAIGN,
        PHASE_9_SQUADRON_LOCAL_NOTE_UNLINKED_FROM_CAMPAIGN,
        PHASE_9_SOURCE_ATTEMPT_BLOCKED,
        PHASE_9_SOURCE_ATTEMPT_DISABLED,
        PHASE_9_SOURCE_ATTEMPT_REQUIRES_AUTH,
        PHASE_9_SOURCE_ATTEMPT_UNSUPPORTED,
        PHASE_9_SOURCE_ATTEMPT_NO_VERIFIED_SOURCE,
    }
)

# The six criticals audited by the Week 9 Critical Event Broadcaster test.
# Matches Phase 2 Development Guide, Week 9 Part B, task 1 exactly.
CRITICAL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        HULL_CRITICAL_25,
        HULL_CRITICAL_10,
        SHIELDS_DOWN,
        FUEL_LOW,
        FUEL_CRITICAL,
        MODULE_CRITICAL,
    }
)

# Heat-specific critical events (Phase 3.4 addition).
HEAT_CRITICAL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        HEAT_WARNING,
        HEAT_DAMAGE,
    }
)

# Interdiction-specific urgent events (Phase 4 D1B).
# Used by D3 overlay to subscribe to the alert lane.
INTERDICTION_URGENT_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        INTERDICTION_STARTED,
        INTERDICTION_ENDED,
    }
)
