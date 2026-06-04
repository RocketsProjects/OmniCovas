"""
omnicovas.core.state_manager

In-memory current state of the commander's session.

Holds the live truth of "right now": current ship, system, cargo, fuel, etc.
This is NOT a database — it is pure in-memory state for zero-latency reads.
The database (omnicovas.db) persists history; this class holds "now".

Law 7 (Telemetry Rigidity):
    Source priority enforced. When multiple sources report conflicting state,
    the higher-priority source always wins. Local journal is the ultimate truth.

    Priority order (lowest number = highest priority):
        1. journal       — local, authoritative game events
        2. status_json   — local, live hardware/UI state
        3. capi          — remote, Frontier API
        4. eddn          — remote, crowdsourced
        5. inferred      — OmniCOVAS-derived, never overrides real telemetry

Law 5 (Zero Hallucination Doctrine):
    StateManager NEVER fabricates data to fill gaps.
    Missing fields stay missing (None) until real telemetry arrives.

See: Master Blueprint v4.1 Section 2 (Data Pipeline)
See: Phase 2 Development Guide Week 7, Part B
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from typing import Any, Literal
from uuid import uuid4

logger = logging.getLogger(__name__)


class TelemetrySource(IntEnum):
    """
    Source priority for state updates.

    Lower value = higher priority. A lower-numbered source always
    wins a conflict against a higher-numbered source.
    """

    JOURNAL = 1
    STATUS_JSON = 2
    CAPI = 3
    EDDN = 4
    INFERRED = 5


@dataclass
class FieldSource:
    """
    Records which source last set a given field, for conflict resolution.
    """

    source: TelemetrySource
    timestamp: str | None = None
    source_file: str | None = None


@dataclass
class ModuleInfo:
    """
    State of a single ship module, populated from the Loadout journal event.

    Health is 0.0-1.0 (matching the journal field directly -- do NOT convert
    to percent). power and priority are None for modules that lack those
    fields in the Loadout payload (e.g. Fighter Hangar bays).

    The engineering field carries the raw Engineering block from the journal
    verbatim. Phase 2 does not parse engineer effects -- that is Pillar 6
    work in Phase 8. We preserve the raw block so Phase 8 has it available.

    See: Phase 2 Development Guide Week 8, Part A (Loadout Awareness)
    """

    slot: str
    item: str
    item_localised: str | None
    # 0.0 (destroyed) -> 1.0 (intact). Matches journal Module.Health directly.
    health: float
    power: float | None
    priority: int | None
    on: bool
    # Raw engineering block from journal -- parsed in Phase 8 (Pillar 6).
    # None when module has no engineering modifications.
    engineering: dict[str, Any] | None
    # Insured credit value of this module from Loadout.Modules[].Value.
    # None when the journal does not include a Value field (older versions).
    # Used by the Rebuy Calculator (Feature 11, Week 10).
    value: int | None = None
    # Ammunition fields from Loadout.Modules[].AmmoInClip / AmmoInHopper.
    # Present only on weapon and ammo-bearing modules; None otherwise.
    # Preserved verbatim from the journal for downstream consumers; not
    # interpreted here.
    ammo_in_clip: int | None = None
    ammo_in_hopper: int | None = None


CombatSourceLabel = Literal[
    "journal",
    "status",
    "companion",
    "cache",
    "commander_entered",
    "inferred",
    "unknown",
]
CombatFreshnessState = Literal["fresh", "stale", "unknown"]
CombatFieldValue = str | int | bool | None

SquadronSourceLabel = Literal["local", "commander_local", "local_state", "unknown"]
SquadronFreshnessState = Literal["fresh", "stale", "unknown"]
SquadronTruthClass = Literal["verified", "unverified", "commander_entered", "unknown"]


@dataclass(frozen=True)
class SquadronProvenance:
    """Standard provenance fields for local-only squadron data."""

    source: SquadronSourceLabel = "local"
    freshness: SquadronFreshnessState = "unknown"
    truth_class: SquadronTruthClass = "unknown"
    caveat: str | None = "No local context yet"
    fallback_wording: str | None = "Reserved — requires future security doctrine"
    local_only: bool = True
    transport_attempted: bool = False
    timestamp: str | None = None


@dataclass(frozen=True)
class PeerState:
    """Local-only state of a squadron peer."""

    id: str = field(default_factory=lambda: uuid4().hex)
    commander_name: str | None = None
    role: str | None = None
    provenance: SquadronProvenance = field(default_factory=SquadronProvenance)


@dataclass(frozen=True)
class TelemetrySyncState:
    """Local-only state of telemetry synchronization."""

    active: bool = False
    last_sync_at: str | None = None
    provenance: SquadronProvenance = field(default_factory=SquadronProvenance)


@dataclass(frozen=True)
class InviteCode:
    """Local-only representation of an invite code."""

    id: str = field(default_factory=lambda: uuid4().hex)
    code: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    provenance: SquadronProvenance = field(default_factory=SquadronProvenance)


@dataclass(frozen=True)
class RoleAuthority:
    """Local-only representation of role authority."""

    id: str = field(default_factory=lambda: uuid4().hex)
    role_name: str | None = None
    permissions: list[str] = field(default_factory=list)
    provenance: SquadronProvenance = field(default_factory=SquadronProvenance)


@dataclass(frozen=True)
class SharedOperationLink:
    """Local-only link to a shared operation."""

    id: str = field(default_factory=lambda: uuid4().hex)
    operation_id: str | None = None
    label: str | None = None
    provenance: SquadronProvenance = field(default_factory=SquadronProvenance)


@dataclass(frozen=True)
class SharedNavigationLink:
    """Local-only link to a shared navigation objective."""

    id: str = field(default_factory=lambda: uuid4().hex)
    system_name: str | None = None
    objective: str | None = None
    provenance: SquadronProvenance = field(default_factory=SquadronProvenance)


@dataclass(frozen=True)
class EmergencySecurityNote:
    """Local-only emergency/security note (commander-entered)."""

    id: str = field(default_factory=lambda: uuid4().hex)
    note_text: str | None = None
    created_at: str | None = None
    provenance: SquadronProvenance = field(default_factory=SquadronProvenance)


@dataclass(frozen=True)
class EmergencySecurityState:
    """Local-only state of emergency security."""

    active: bool = False
    reason: str | None = None
    notes: list[EmergencySecurityNote] = field(default_factory=list)
    provenance: SquadronProvenance = field(default_factory=SquadronProvenance)


@dataclass(frozen=True)
class SquadronLogEntry:
    """Local-only log entry for squadron activity."""

    id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: str | None = None
    event_type: str | None = None
    summary: str | None = None
    provenance: SquadronProvenance = field(default_factory=SquadronProvenance)


@dataclass(frozen=True)
class IntegrationState:
    """Local-only state of squadron-related integrations (e.g. Discord)."""

    provider: str | None = None
    status: str = "not_shipped"
    provenance: SquadronProvenance = field(default_factory=SquadronProvenance)


@dataclass(frozen=True)
class SquadronState:
    """Aggregate local-only Squadrons state."""

    peers: list[PeerState] = field(default_factory=list)
    telemetry_sync: TelemetrySyncState = field(default_factory=TelemetrySyncState)
    invites: list[InviteCode] = field(default_factory=list)
    roles: list[RoleAuthority] = field(default_factory=list)
    shared_operations: list[SharedOperationLink] = field(default_factory=list)
    shared_navigation: list[SharedNavigationLink] = field(default_factory=list)
    emergency_security: EmergencySecurityState = field(
        default_factory=EmergencySecurityState
    )
    log: list[SquadronLogEntry] = field(default_factory=list)
    integrations: list[IntegrationState] = field(default_factory=list)


@dataclass
class CombatField:
    """A combat field value plus field-level provenance."""

    value: CombatFieldValue = None
    source: CombatSourceLabel = "unknown"
    timestamp: str | None = None
    freshness: CombatFreshnessState = "unknown"


@dataclass
class CombatTargetContext:
    """Target context confirmed from local telemetry."""

    ship_type: CombatField = field(default_factory=CombatField)
    faction: CombatField = field(default_factory=CombatField)
    legal_status: CombatField = field(default_factory=CombatField)


@dataclass
class CombatThreatContext:
    """Threat context confirmed or inferred from local telemetry."""

    recent_hostile_events_count: CombatField = field(default_factory=CombatField)
    last_hostile_timestamp: CombatField = field(default_factory=CombatField)
    under_attack: CombatField = field(default_factory=CombatField)
    context_label: CombatField = field(default_factory=CombatField)


@dataclass
class CombatSessionFocus:
    """Current combat-session focus for Operations -> Combat consumers."""

    active: CombatField = field(default_factory=CombatField)
    mode_hint: CombatField = field(default_factory=CombatField)


@dataclass
class CombatWorkflowContext:
    """Interdiction/escape workflow state for Operations -> Combat consumers.

    All fields default to unknown (CombatField defaults) until journal events
    confirm them. D1B wires the handlers; D1A establishes the schema only.
    """

    interdiction_active: CombatField = field(default_factory=CombatField)
    interdiction_started_at: CombatField = field(default_factory=CombatField)
    interdiction_ended_at: CombatField = field(default_factory=CombatField)
    escape_outcome: CombatField = field(default_factory=CombatField)


@dataclass
class CombatMissionEntry:
    """Typed mission entry for Operations -> Combat mission session list.

    Populated from verified Frontier journal mission events
    (Missions, MissionAccepted, MissionCompleted, MissionFailed,
    MissionAbandoned, MissionRedirected). Carries entry-level
    provenance so each mission can be rendered with source/freshness
    independently. Not a CombatField (CombatField cannot store a list).

    Status values:
        "active"     -- in Missions Active[] snapshot or accepted this session
        "completed"  -- MissionCompleted observed
        "failed"     -- MissionFailed observed
        "abandoned"  -- MissionAbandoned observed
    """

    mission_id: int | None = None
    name: str | None = None
    faction: str | None = None
    destination_system: str | None = None
    destination_station: str | None = None
    status: str = "active"
    source_label: CombatSourceLabel = "journal"
    timestamp: str | None = None
    freshness: CombatFreshnessState = "fresh"
    caveat: str | None = None


@dataclass
class CombatZoneMissionContext:
    """Mission session and local conflict context for Operations -> Combat.

    Active CZ detection and CZ kind (low/medium/high) are intentionally
    omitted -- no verified local journal source exists for those facts;
    they remain Unsupported per Local Data Surface Reference v1.0.

    local_conflict_context is sourced from Location/FSDJump Conflicts[]
    only; it does NOT claim the commander is in a combat zone.
    """

    mission_session_active: CombatField = field(default_factory=CombatField)
    session_started_at: CombatField = field(default_factory=CombatField)
    local_conflict_context: CombatField = field(default_factory=CombatField)
    mission_session_blockers: CombatField = field(default_factory=CombatField)


@dataclass
class CombatRewardsContext:
    """Session reward and combat rank summary for Operations -> Combat.

    bounty_session_credits and combat_bond_session_credits accumulate
    only from RedeemVoucher Type=bounty and Type=CombatBond respectively.
    MissionCompleted.Reward is NOT counted as a combat reward total
    (per PB04-06 hard correction).

    combat_rank and combat_rank_progress are latest observed startup
    facts; rank thresholds are not exposed by any verified local source.
    """

    bounty_session_credits: CombatField = field(default_factory=CombatField)
    combat_bond_session_credits: CombatField = field(default_factory=CombatField)
    combat_rank: CombatField = field(default_factory=CombatField)
    combat_rank_progress: CombatField = field(default_factory=CombatField)
    session_summary_at: CombatField = field(default_factory=CombatField)


@dataclass
class CombatState:
    """Phase 4 combat state owned by the canonical StateManager."""

    target: CombatTargetContext = field(default_factory=CombatTargetContext)
    threat: CombatThreatContext = field(default_factory=CombatThreatContext)
    session: CombatSessionFocus = field(default_factory=CombatSessionFocus)
    workflow: CombatWorkflowContext = field(default_factory=CombatWorkflowContext)
    cz_missions: CombatZoneMissionContext = field(
        default_factory=CombatZoneMissionContext
    )
    rewards: CombatRewardsContext = field(default_factory=CombatRewardsContext)
    active_missions: list[CombatMissionEntry] = field(default_factory=list)


LocalContextFreshness = Literal[
    "fresh",
    "stale",
    "not_loaded",
    "live_local_telemetry",
    "local_event_history",
    "commander_observed",
]


@dataclass
class LocalStationContext:
    """Field-rich local station context preserved from a Docked event.

    Source: Journal Docked event. Frontier-native field names are exposed
    verbatim under snake_case attributes (station_services, station_economies,
    landing_pads, etc.) so downstream consumers see the same shape Frontier
    emits. Missing fields stay None per Law 5.

    Lifecycle: populated on Docked; cleared (set to None on SessionState) on
    Undocked. Freshness against live state is evaluated by the local context
    feature module, not stored here.

    See: Local Elite Data Surface Reference v1.0 §6.3 provenance, §9 forbidden
    patterns (do not collapse rich station data into shallow labels).
    """

    station_name: str | None = None
    station_type: str | None = None
    market_id: int | None = None
    star_system: str | None = None
    system_address: int | None = None
    is_docked: bool | None = None
    # Raw faction dict from Docked.StationFaction; commonly {Name, FactionState}.
    station_faction: dict[str, Any] | None = None
    station_government: str | None = None
    station_allegiance: str | None = None
    station_economy: str | None = None
    # List of {Name, Proportion} dicts preserved verbatim.
    station_economies: list[dict[str, Any]] = field(default_factory=list)
    # List of station service identifiers verbatim from journal
    # (e.g. "dock", "autodock", "commodities", "outfitting", ...).
    station_services: list[str] = field(default_factory=list)
    # Raw LandingPads dict from Docked (typically {Small, Medium, Large}).
    landing_pads: dict[str, Any] | None = None
    dist_from_star_ls: float | None = None
    # Provenance trio: which Frontier event produced this context, the
    # event timestamp string verbatim, and which file the event came from.
    source: str = "Journal"
    source_event: str | None = None
    event_timestamp: str | None = None
    source_file: str | None = None


@dataclass
class LocalSystemContext:
    """Field-rich local system context preserved from FSDJump / Location.

    Source: Journal FSDJump (primary) or Location (cold-start / fallback).
    PB04-06 F1 keeps current_system ownership on FSDJump/Docked; this
    snapshot is a SEPARATE state field and does not override scalar
    current_system.

    Conflicts and Factions are preserved verbatim alongside the
    existing combat.cz_missions.local_conflict_context summary so neither
    consumer regresses.

    See: Local Elite Data Surface Reference v1.0 §4 file semantics.
    """

    star_system: str | None = None
    system_address: int | None = None
    # Raw StarPos triple [x, y, z] preserved verbatim.
    star_pos: list[float] | None = None
    body: str | None = None
    body_id: int | None = None
    body_type: str | None = None
    system_faction: dict[str, Any] | None = None
    system_allegiance: str | None = None
    system_economy: str | None = None
    system_second_economy: str | None = None
    system_government: str | None = None
    system_security: str | None = None
    population: int | None = None
    powers: list[str] = field(default_factory=list)
    powerplay_state: str | None = None
    # Raw faction list preserved verbatim (each entry is a dict).
    factions: list[dict[str, Any]] = field(default_factory=list)
    # Raw conflict list preserved verbatim (each entry is a dict).
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    source: str = "Journal"
    source_event: str | None = None
    event_timestamp: str | None = None
    source_file: str | None = None


@dataclass(frozen=True)
class Phase9BgsMissionEffect:
    """Local Journal MissionCompleted.FactionEffects evidence.

    Stores observed event fields only. This is not a global BGS claim and does
    not interpret influence mechanics beyond listing fields Frontier emitted.
    """

    mission_id: int | None = None
    faction: str | None = None
    effect_kinds: list[str] = field(default_factory=list)
    raw_effect: dict[str, Any] = field(default_factory=dict)
    source: str = "Journal"
    source_event: str = "MissionCompleted"
    event_timestamp: str | None = None
    source_file: str | None = None


@dataclass(frozen=True)
class Phase9BgsRewardEvent:
    """Local Journal reward/bond evidence relevant to BGS review."""

    event_type: str
    reward_type: str | None = None
    amount: int | None = None
    faction: str | None = None
    faction_entries: list[dict[str, Any]] = field(default_factory=list)
    source: str = "Journal"
    source_event: str | None = None
    event_timestamp: str | None = None
    source_file: str | None = None


@dataclass(frozen=True)
class Phase9BgsState:
    """PB09-02 local-only BGS fact evidence owned by StateManager."""

    mission_effects: list[Phase9BgsMissionEffect] = field(default_factory=list)
    reward_events: list[Phase9BgsRewardEvent] = field(default_factory=list)
    updated_at: str | None = None


@dataclass(frozen=True)
class Phase9PowerplayEvent:
    """Local Journal Powerplay event evidence.

    Exact merit values are deliberately omitted while the Powerplay 2.0 KB
    entry remains review-gated.
    """

    event_type: str
    power: str | None = None
    observed_fields: dict[str, Any] = field(default_factory=dict)
    withheld_fields: list[str] = field(default_factory=list)
    source: str = "Journal"
    source_event: str | None = None
    event_timestamp: str | None = None
    source_file: str | None = None


@dataclass(frozen=True)
class Phase9PowerplayState:
    """PB09-02 local-only Powerplay fact evidence owned by StateManager."""

    pledge_power: str | None = None
    pledge_status: str | None = None
    pledge_source_event: str | None = None
    pledge_timestamp: str | None = None
    rank: int | None = None
    rank_source_event: str | None = None
    rank_timestamp: str | None = None
    events: list[Phase9PowerplayEvent] = field(default_factory=list)
    updated_at: str | None = None


@dataclass
class CargoItem:
    """A single cargo entry preserved from Cargo journal event or Cargo.json.

    Frontier-native fields preserved: Name, Name_Localised, Count, Stolen,
    MissionID. Stolen and MissionID are typically present only when relevant;
    None when the journal does not include them.
    """

    name: str
    name_localised: str | None = None
    count: int = 0
    stolen: int | None = None
    mission_id: int | None = None


@dataclass
class CargoHoldSnapshot:
    """Field-rich cargo snapshot preserved from Cargo events / Cargo.json.

    Existing scalar cargo_inventory (dict[str, int]) and cargo_count fields
    stay on SessionState for backward compatibility. This snapshot adds
    vessel context and per-item Stolen / MissionID flags that the legacy
    dict cannot carry.

    Source values: "Journal" when populated from a Cargo event, or
    "Cargo.json" when overlaid by an on-demand companion file read.
    """

    vessel: str | None = None
    capacity: int | None = None
    inventory: list[CargoItem] = field(default_factory=list)
    source: str = "Journal"
    source_event: str | None = None
    event_timestamp: str | None = None
    source_file: str | None = None


@dataclass
class SessionState:
    """
    The current state of the commander's session.

    All fields default to None -- unknown until telemetry confirms them.
    Law 5 forbids filling gaps with assumptions.

    Phase 2 additions are grouped by feature so future readers can see which
    feature owns which fields. All new fields are nullable (None = unknown).
    """

    # --- Phase 1 fields (unchanged) -----------------------------------------

    current_system: str | None = None
    current_station: str | None = None

    # Tri-state: None = unknown (not yet confirmed by telemetry), True = docked,
    # False = not docked. None is correct on startup per Law 5 -- do not default
    # to False, which would fabricate knowledge we don't have yet.
    is_docked: bool | None = None
    is_in_supercruise: bool | None = None

    # 0.0 (destroyed) -> 1.0 (full health). Matches the journal HullDamage.Health
    # field exactly -- do NOT convert to percent on ingest. KB threshold entries
    # use the same 0.0-1.0 scale (e.g. hull_critical_threshold = 0.10, not 10.0).
    hull_health: float | None = None

    shield_up: bool | None = None
    fuel_main: float | None = None
    # fuel_capacity_main: total fuel capacity in main tank (tons)
    # fuel_capacity_reserve: total fuel capacity in reservoir tank (tons)
    fuel_capacity_main: float | None = None
    fuel_capacity_reserve: float | None = None
    cargo_count: int | None = None
    cargo_capacity: int | None = None
    target_cmdr: str | None = None
    target_ship: str | None = None
    commander_name: str | None = None

    # Wallet / source-backed commander finance fields. LoadGame.Credits /
    # LoadGame.Loan and Status.json Balance may seed these; missing values
    # stay None per Law 5.
    credit_balance: int | None = None
    loan: int | None = None
    rebuy_cost: int | None = None

    # --- Phase 2 -- Ship Identity (Feature 1: Live Ship State) ---------------
    # Populated from LoadGame, Loadout, and ShipyardSwap journal events.

    # internal type string e.g. "Python", "SideWinder"
    current_ship_type: str | None = None
    # numeric ID assigned by the game to distinguish multiple ships of the
    # same type in the commander's fleet
    current_ship_id: int | None = None
    # pilot-assigned call sign e.g. "QE-01"
    current_ship_ident: str | None = None
    # pilot-assigned name e.g. "HMCS Bonaventure"
    current_ship_name: str | None = None

    # --- Phase 2 -- Hull & Shield additions (Features 1, 3, 7) --------------

    # 0.0-100.0. Populated from Status.json when available. Distinct from
    # shield_up (boolean). None until first Status read.
    shield_strength_pct: float | None = None

    # --- Phase 2 -- Fuel & Jump Range (Feature 5) ---------------------------
    # fuel_reservoir: the small supplemental tank that feeds the main tank.
    # Sourced from Status.json Fuel.FuelReservoir. Units: tons.
    fuel_reservoir: float | None = None
    # jump_range_ly: maximum jump range at current load.
    # Sourced from Loadout.MaxJumpRange -- NOT recomputed from physics.
    # Phase 5 (Exploration pillar) owns first-principles jump math.
    jump_range_ly: float | None = None

    # --- Phase 2 -- Cargo (Feature 6) ---------------------------------------
    # commodity internal name -> unit count.
    # Populated from Cargo.json, not from Loadout.
    # SRV cargo is excluded -- Phase 2 tracks Ship cargo only.
    cargo_inventory: dict[str, int] = field(default_factory=dict)

    # --- Phase 2 -- Loadout & Modules (Features 2, 4) -----------------------
    # slot name -> ModuleInfo. Ground truth from Loadout event.
    # Delta updates arrive from ModuleInfo.json during combat (Week 8).
    modules: dict[str, ModuleInfo] = field(default_factory=dict)
    # SHA-256 of the sorted Modules array.
    # Used to detect genuine loadout changes vs cosmetic re-fires of Loadout.
    loadout_hash: str | None = None

    # omnicovas/core/state_manager.py
    # Phase 2 -- Extended Events (Feature 8) --------------------------------
    # True when commander has a bounty or crime in the current system.
    # Cleared automatically on FSDJump to a different system.
    is_wanted_in_system: bool = False

    # --- Phase 2 -- Power Distribution (Feature 9) --------------------------
    # Pip values are on a 0-8 scale where total always equals 12 when in a
    # flyable ship. Status.json reports them as a [SYS, ENG, WEP] list.
    # All three are None when on-foot (Odyssey) or before first Status read.
    sys_pips: int | None = None
    eng_pips: int | None = None
    wep_pips: int | None = None

    # --- Phase 2 -- Heat (Feature 10) ---------------------------------------
    # 0.0-1.0 from Status.json Heat field. NOT a percentage.
    # 1.0 = 100% heat (damage threshold). Values above 1.0 are possible
    # during fuel scoop overheat. None until first Status read.
    heat_level: float | None = None
    # Grounded heat state ("normal", "warning", "damage").
    heat_state: str | None = None
    # Timestamp of last heat warning/damage event.
    heat_last_event_at: str | None = None
    # Grounded heat suggestion.
    heat_suggestion: str | None = None

    # --- Phase 2 -- Rebuy Calculator (Feature 11, Week 10) -----------------
    # hull_value: insured hull value in credits from Loadout.HullValue.
    # modules_value: total insured module value from Loadout.ModulesValue.
    # Both are None until a Loadout event arrives.
    hull_value: int | None = None
    modules_value: int | None = None

    # --- Phase 4 -- Combat Target & Threat Foundation -----------------------
    combat: CombatState = field(default_factory=CombatState)

    # --- Phase 7 -- Squadrons local-only foundation -------------------------
    squadron: SquadronState = field(default_factory=SquadronState)

    # --- Phase 6 extension -- Local Data Backplane --------------------------
    # Field-rich local station/system context preserved from Docked / FSDJump
    # / Location. These are SEPARATE from current_station / current_system
    # (PB04-06 F1 keeps scalar ownership on FSDJump/Docked) and exist to
    # carry StationServices, StationEconomies, LandingPads, SystemGovernment,
    # SystemSecurity, Factions, Conflicts, etc. that the scalars cannot hold.
    # None until the first qualifying event.
    local_station_context: LocalStationContext | None = None
    local_system_context: LocalSystemContext | None = None
    # --- Phase 9 -- Intel BGS / Powerplay local-first fact surface ----------
    # Local-only observed journal evidence. These projections intentionally do
    # not claim global BGS/Powerplay state and do not activate providers.
    phase9_bgs: Phase9BgsState = field(default_factory=Phase9BgsState)
    phase9_powerplay: Phase9PowerplayState = field(default_factory=Phase9PowerplayState)
    # Field-rich cargo snapshot with vessel/capacity/Stolen/MissionID flags
    # preserved. The scalar cargo_inventory dict and cargo_count stay above
    # for backward compatibility; this snapshot is additive.
    cargo_hold_snapshot: CargoHoldSnapshot | None = None

    # --- Internal audit (NOT public) ----------------------------------------
    _field_sources: dict[str, FieldSource] = field(default_factory=dict)


class StateManager:
    """
    Manages the live in-memory session state.

    Provides update methods that enforce Law 7 (source priority).
    Updates from lower-priority sources are rejected if a higher-priority
    source has already set that field.

    Source priority is automatically enforced for all SessionState fields via
    update_field(). The Phase 1 implementation covers every field -- Phase 2
    fields inherit this for free without any additional wiring.

    Usage:
        state = StateManager()
        state.update_field("current_system", "Sol", TelemetrySource.JOURNAL)
        state.update_field("fuel_main", 16.0, TelemetrySource.STATUS_JSON)
        print(state.snapshot.current_system)

    See: Phase 2 Development Guide Week 7, Part B
    """

    def __init__(self) -> None:
        self._state = SessionState()

    @property
    def snapshot(self) -> SessionState:
        """
        Read-only snapshot of current state.
        All mutations must go through update_field() to respect source priority.
        """
        return self._state

    def update_field(
        self,
        field_name: str,
        value: Any,
        source: TelemetrySource,
        timestamp: str | None = None,
        source_file: str | None = None,
    ) -> bool:
        """
        Update a single state field, respecting source priority.

        Args:
            field_name: Name of the SessionState field to update
            value: New value to set
            source: Which telemetry source produced this value
            timestamp: Optional journal timestamp for audit

        Returns:
            True if the update was accepted. False if rejected due to
            a higher-priority source already owning this field.
        """
        if not hasattr(self._state, field_name) or field_name.startswith("_"):
            logger.warning("Rejected update to unknown field: %s", field_name)
            return False

        # Phase 3.4 Patch: Allow STATUS_JSON to update continuously-polled fields
        # (fuel and shield state) even if JOURNAL set a prior value.
        # Status.json bit 3 is the live shield truth; a journal ShieldsDown event
        # must not permanently block the next Status.json shield-up reading.
        is_fuel_update = source == TelemetrySource.STATUS_JSON and field_name in (
            "fuel_main",
            "fuel_reservoir",
            "shield_up",
        )

        existing = self._state._field_sources.get(field_name)

        if not is_fuel_update and existing is not None and existing.source < source:
            logger.debug(
                "Rejected %s update to %r: existing source %s outranks %s",
                field_name,
                value,
                existing.source.name,
                source.name,
            )
            return False

        # Law 5: Never overwrite a known fuel value with None from STATUS_JSON
        if (
            is_fuel_update
            and value is None
            and getattr(self._state, field_name) is not None
        ):
            logger.debug(
                "Rejected %s: cannot overwrite known value with None from STATUS_JSON",
                field_name,
            )
            return False

        setattr(self._state, field_name, value)
        self._state._field_sources[field_name] = FieldSource(
            source=source, timestamp=timestamp, source_file=source_file
        )
        logger.debug(
            "Updated %s = %r (source: %s)",
            field_name,
            value,
            source.name,
        )
        return True

    def reset(self) -> None:
        """
        Reset all state to initial (all None / empty dicts).
        Use only at session boundaries or for tests.
        """
        self._state = SessionState()
        logger.info("StateManager reset.")

    def get_field_source(self, field_name: str) -> FieldSource | None:
        """
        Return the source metadata for a field, for audit/explainability.
        """
        return self._state._field_sources.get(field_name)

    def public_snapshot(self) -> dict[str, Any]:
        """
        Return session state as a plain dict with all private fields stripped.

        Safe to serialise and send to the UI or API clients. Use this
        everywhere state is serialised -- never call asdict() directly on the
        snapshot and then pop() private fields at each call site.

        Law 8 (Sovereignty & Transparency): state is inspectable by the
        commander, but internal audit metadata (_field_sources) is an
        implementation detail that must not appear in the public API surface.

        Returns:
            Dict of all public SessionState fields. Keys starting with '_'
            are excluded regardless of what future internal fields are added.
        """
        return {k: v for k, v in asdict(self._state).items() if not k.startswith("_")}
