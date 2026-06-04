"""Phase 6 extension — field-rich local context backplane.

Builds field-rich state objects (LocalStationContext, LocalSystemContext,
CargoHoldSnapshot) from journal events and composes the read-only snapshot
payload consumed by GET /intel/local-context/snapshot.

Sources are all local-only: journal events held in StateManager plus on-
demand reads of approved companion JSON files (Market.json, Outfitting.json,
Shipyard.json, Cargo.json, ModulesInfo.json). No external lookups, no scraping,
no provider clients.

See: Local Elite Data Surface Reference v1.0
    §4 file semantics
    §6.1 reader -> dispatcher -> handler -> state path
    §6.3 provenance
    §7 freshness / staleness / missing-file rules
    §9 forbidden patterns
See: Source Capability Routing Reference v1 §1 (local-first), §3 (P0 = local)
See: Backend Maturity Matrix v1.0 §4 (companion JSON readers partial,
     local economic facts active_phase_extension)
"""

from __future__ import annotations

import json
import logging
import os
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omnicovas.core.state_manager import (
    CargoHoldSnapshot,
    CargoItem,
    LocalStationContext,
    LocalSystemContext,
    Phase9BgsMissionEffect,
    Phase9BgsRewardEvent,
    Phase9PowerplayEvent,
    StateManager,
    TelemetrySource,
)
from omnicovas.features.rebuy import calculate_rebuy
from omnicovas.knowledge_base import load_knowledge_base

logger = logging.getLogger(__name__)

# --- Freshness / truth-class / fallback vocabulary --------------------------

FRESH = "fresh"
STALE = "stale"
NOT_LOADED = "not_loaded"
LAST_KNOWN = "last_known"
STARTUP_HYDRATION = "startup_hydration"
MARKET_SNAPSHOT_ONLY = "market_snapshot_only"
LIVE_LOCAL_TELEMETRY = "live_local_telemetry"
LOCAL_EVENT_HISTORY = "local_event_history"
LOCAL_SCREEN_SNAPSHOT = "local_screen_snapshot"
COMMANDER_OBSERVED = "commander_observed"

TRUTH_UNKNOWN = "unknown"
TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
TRUTH_LOCAL_SCREEN_SNAPSHOT = "local_screen_snapshot"

JOURNAL_SOURCE = "Journal"
MARKET_FILE = "Market.json"
CARGO_FILE = "Cargo.json"
MODULES_INFO_FILE = "ModulesInfo.json"
OUTFITTING_FILE = "Outfitting.json"
SHIPYARD_FILE = "Shipyard.json"
STATUS_FILE = "Status.json"

NO_LOCAL_STATION_CONTEXT = "No local station context observed yet"
NO_LOCAL_SYSTEM_CONTEXT = "No local system context observed yet"
NO_LOCAL_STATION_SERVICES = "No local station services observed yet"
NO_LOCAL_MARKET_SNAPSHOT = "No local snapshot for this station"
NO_LOCAL_OUTFITTING_SNAPSHOT = "No verified local outfitting snapshot"
NO_LOCAL_SHIPYARD_SNAPSHOT = "No verified local shipyard snapshot"
NO_LOCAL_CARGO_SNAPSHOT = "No local cargo snapshot observed yet"
NO_LOCAL_MODULE_LOADOUT = "No local module loadout observed yet"
NO_VERIFIED_SOURCE = "No Verified Source"
UNKNOWN = "Unknown"
NOT_LOADED_DISPLAY = "Not Loaded"
UNSUPPORTED = "Unsupported"
DISABLED = "Disabled"
KNOWLEDGE_REFERENCE = "knowledge_reference"

_PHASE9_HISTORY_LIMIT = 8
_BGS_REDEEM_TYPES = frozenset({"bounty", "CombatBond"})
_POWERPLAY_MERIT_FIELDS = frozenset({"Merits", "Merit", "MeritValue"})
_POWERPLAY_OBSERVED_FIELD_ALLOWLIST = frozenset(
    {
        "Power",
        "FromPower",
        "ToPower",
        "Type",
        "Name",
        "Name_Localised",
        "Commodity",
        "Commodity_Localised",
        "Count",
        "Votes",
        "Rank",
        "PowerplayState",
    }
)
_POWERPLAY_EVENTS = frozenset(
    {
        "Powerplay",
        "PowerplayJoin",
        "PowerplayLeave",
        "PowerplayDefect",
        "PowerplaySalary",
        "PowerplayCollect",
        "PowerplayDeliver",
        "PowerplayFastTrack",
        "PowerplayVote",
        "PowerplayVoucher",
        "PowerplayMerits",
        "PowerplayRank",
        "RequestPowerMicroResources",
        "DeliverPowerMicroResources",
    }
)


# --- State builders (handler-side) -----------------------------------------


def build_local_station_context(
    event: dict[str, Any],
    *,
    source_event: str = "Docked",
    source_file: str | None = None,
) -> LocalStationContext:
    """Build a field-rich LocalStationContext from a Docked event.

    All Frontier-native fields preserved verbatim under snake_case
    attributes. Missing fields stay None / empty list per Law 5.
    """
    return LocalStationContext(
        station_name=_string_or_none(event.get("StationName")),
        station_type=_string_or_none(event.get("StationType")),
        market_id=_int_or_none(event.get("MarketID")),
        star_system=_string_or_none(event.get("StarSystem")),
        system_address=_int_or_none(event.get("SystemAddress")),
        is_docked=True,
        station_faction=_dict_or_none(event.get("StationFaction")),
        station_government=_string_or_none(event.get("StationGovernment")),
        station_allegiance=_string_or_none(event.get("StationAllegiance")),
        station_economy=_string_or_none(event.get("StationEconomy")),
        station_economies=_list_of_dicts(event.get("StationEconomies")),
        station_services=_list_of_strings(event.get("StationServices")),
        landing_pads=_dict_or_none(event.get("LandingPads")),
        dist_from_star_ls=_float_or_none(event.get("DistFromStarLS")),
        source=JOURNAL_SOURCE,
        source_event=source_event,
        event_timestamp=_string_or_none(event.get("timestamp")),
        source_file=source_file,
    )


def build_local_system_context(
    event: dict[str, Any],
    *,
    source_event: str,
    source_file: str | None = None,
) -> LocalSystemContext:
    """Build a field-rich LocalSystemContext from an FSDJump / Location event.

    PB04-06 F1: this snapshot is a SEPARATE state field from current_system;
    callers handle the should_replace_system_context guard for Location to
    avoid colliding with FSDJump ownership of system transitions.
    """
    return LocalSystemContext(
        star_system=_string_or_none(event.get("StarSystem")),
        system_address=_int_or_none(event.get("SystemAddress")),
        star_pos=_list_of_floats(event.get("StarPos")),
        body=_string_or_none(event.get("Body")),
        body_id=_int_or_none(event.get("BodyID")),
        body_type=_string_or_none(event.get("BodyType")),
        system_faction=_dict_or_none(event.get("SystemFaction")),
        system_allegiance=_string_or_none(event.get("SystemAllegiance")),
        system_economy=_string_or_none(event.get("SystemEconomy")),
        system_second_economy=_string_or_none(event.get("SystemSecondEconomy")),
        system_government=_string_or_none(event.get("SystemGovernment")),
        system_security=_string_or_none(event.get("SystemSecurity")),
        population=_int_or_none(event.get("Population")),
        powers=_list_of_strings(event.get("Powers")),
        powerplay_state=_string_or_none(event.get("PowerplayState")),
        factions=_list_of_dicts(event.get("Factions")),
        conflicts=_list_of_dicts(event.get("Conflicts")),
        source=JOURNAL_SOURCE,
        source_event=source_event,
        event_timestamp=_string_or_none(event.get("timestamp")),
        source_file=source_file,
    )


def should_apply_location_system_context(
    existing: LocalSystemContext | None,
    location_event: dict[str, Any],
) -> bool:
    """PB04-06 F1 guard for Location events.

    A Location event may seed the system-context snapshot ONLY when:
      - no existing context has been recorded yet, OR
      - the existing context is for a different system (cold-start /
        recovery case), OR
      - the existing context is older than this Location event for the
        same system.

    Returns False when a more recent FSDJump for the same system has
    already populated the snapshot — preserving PB04-06 F1 (Location must
    not duplicate FSDJump/Docked ownership of system transitions).
    """
    if existing is None:
        return True
    new_system = _string_or_none(location_event.get("StarSystem"))
    if new_system is not None and existing.star_system != new_system:
        return True
    new_ts = _string_or_none(location_event.get("timestamp"))
    if new_ts is None or existing.event_timestamp is None:
        return False
    return new_ts > existing.event_timestamp


def build_cargo_hold_snapshot(
    event: dict[str, Any],
    *,
    capacity: int | None = None,
    source_event: str = "Cargo",
    source_file: str | None = None,
) -> CargoHoldSnapshot:
    """Build a CargoHoldSnapshot from a Cargo journal event.

    Preserves per-item Stolen and MissionID flags that the scalar
    cargo_inventory dict cannot carry. SRV / Suit vessels yield an empty
    snapshot (filter applied by the caller).
    """
    inventory: list[CargoItem] = []
    for entry in event.get("Inventory") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("Name")
        count = entry.get("Count")
        if name is None or count is None:
            continue
        try:
            count_int = int(count)
        except (TypeError, ValueError):
            continue
        inventory.append(
            CargoItem(
                name=str(name),
                name_localised=_string_or_none(entry.get("Name_Localised")),
                count=count_int,
                stolen=_int_or_none(entry.get("Stolen")),
                mission_id=_int_or_none(entry.get("MissionID")),
            )
        )
    return CargoHoldSnapshot(
        vessel=_string_or_none(event.get("Vessel")) or "Ship",
        capacity=capacity,
        inventory=inventory,
        source=JOURNAL_SOURCE,
        source_event=source_event,
        event_timestamp=_string_or_none(event.get("timestamp")),
        source_file=source_file,
    )


# --- Phase 9 PB09-02 local BGS / Powerplay state recorders -----------------


def record_phase9_bgs_mission_effects(
    event: dict[str, Any],
    state: StateManager,
) -> bool:
    """Record MissionCompleted.FactionEffects as local BGS evidence.

    The raw effect objects are preserved for proof/detail display, but no
    effect interpretation or global BGS claim is made here.
    """
    effects_raw = event.get("FactionEffects")
    if not isinstance(effects_raw, list):
        return False

    entries: list[Phase9BgsMissionEffect] = []
    for raw in effects_raw:
        effect = _dict_or_none(raw)
        if effect is None:
            continue
        entries.append(
            Phase9BgsMissionEffect(
                mission_id=_int_or_none(event.get("MissionID")),
                faction=_string_or_none(effect.get("Faction")),
                effect_kinds=_effect_kinds(effect),
                raw_effect=deepcopy(effect),
                source_event="MissionCompleted",
                event_timestamp=_string_or_none(event.get("timestamp")),
                source_file=_string_or_none(event.get("source_file")),
            )
        )

    if not entries:
        return False

    ts = _string_or_none(event.get("timestamp"))
    previous = state.snapshot.phase9_bgs
    bgs = replace(
        previous,
        mission_effects=_bounded_history(
            [*previous.mission_effects, *entries],
            _PHASE9_HISTORY_LIMIT,
        ),
        updated_at=ts,
    )
    return state.update_field(
        "phase9_bgs",
        bgs,
        TelemetrySource.JOURNAL,
        ts,
        _string_or_none(event.get("source_file")),
    )


def record_phase9_bgs_reward_event(
    event: dict[str, Any],
    state: StateManager,
) -> bool:
    """Record local bounty/bond reward events without interpreting BGS impact."""
    event_type = _string_or_none(event.get("event"))
    if event_type not in {"RedeemVoucher", "Bounty", "FactionKillBond"}:
        return False

    reward_type = _string_or_none(event.get("Type"))
    if event_type == "RedeemVoucher" and reward_type not in _BGS_REDEEM_TYPES:
        return False

    amount = (
        _int_or_none(event.get("Amount"))
        or _int_or_none(event.get("TotalReward"))
        or _int_or_none(event.get("Reward"))
    )
    faction_entries = _list_of_dicts(event.get("Factions")) or _list_of_dicts(
        event.get("Rewards")
    )
    faction = (
        _string_or_none(event.get("Faction"))
        or _string_or_none(event.get("AwardingFaction"))
        or _string_or_none(event.get("VictimFaction"))
    )

    if amount is None and faction is None and not faction_entries:
        return False

    ts = _string_or_none(event.get("timestamp"))
    entry = Phase9BgsRewardEvent(
        event_type=event_type,
        reward_type=reward_type,
        amount=amount,
        faction=faction,
        faction_entries=deepcopy(faction_entries),
        source_event=event_type,
        event_timestamp=ts,
        source_file=_string_or_none(event.get("source_file")),
    )

    previous = state.snapshot.phase9_bgs
    bgs = replace(
        previous,
        reward_events=_bounded_history(
            [*previous.reward_events, entry],
            _PHASE9_HISTORY_LIMIT,
        ),
        updated_at=ts,
    )
    return state.update_field(
        "phase9_bgs",
        bgs,
        TelemetrySource.JOURNAL,
        ts,
        _string_or_none(event.get("source_file")),
    )


def record_phase9_powerplay_event(
    event: dict[str, Any],
    state: StateManager,
) -> bool:
    """Record supported local Powerplay journal event history.

    Exact merit fields are withheld until the Powerplay 2.0 KB review gate is
    closed. The event occurrence and non-merit allowlisted fields remain local
    evidence.
    """
    event_type = _string_or_none(event.get("event"))
    if event_type not in _POWERPLAY_EVENTS:
        return False

    ts = _string_or_none(event.get("timestamp"))
    observed_fields = _powerplay_observed_fields(event)
    withheld_fields = _powerplay_withheld_fields(event)
    power = (
        _string_or_none(event.get("Power"))
        or _string_or_none(event.get("ToPower"))
        or _string_or_none(event.get("FromPower"))
    )

    entry = Phase9PowerplayEvent(
        event_type=event_type,
        power=power,
        observed_fields=observed_fields,
        withheld_fields=withheld_fields,
        source_event=event_type,
        event_timestamp=ts,
        source_file=_string_or_none(event.get("source_file")),
    )

    previous = state.snapshot.phase9_powerplay
    updates: dict[str, Any] = {
        "events": _bounded_history(
            [*previous.events, entry],
            _PHASE9_HISTORY_LIMIT,
        ),
        "updated_at": ts,
    }
    if event_type in {"Powerplay", "PowerplayJoin", "PowerplayDefect"}:
        pledged_power = _string_or_none(event.get("Power")) or _string_or_none(
            event.get("ToPower")
        )
        if pledged_power:
            updates.update(
                pledge_power=pledged_power,
                pledge_status="pledged",
                pledge_source_event=event_type,
                pledge_timestamp=ts,
            )
        elif event_type == "Powerplay" and _string_or_none(event.get("PowerplayState")):
            updates.update(
                pledge_power=None,
                pledge_status="unpledged_observed",
                pledge_source_event=event_type,
                pledge_timestamp=ts,
            )
    elif event_type == "PowerplayLeave":
        updates.update(
            pledge_power=None,
            pledge_status="unpledged_observed",
            pledge_source_event=event_type,
            pledge_timestamp=ts,
        )

    rank = _int_or_none(event.get("Rank"))
    if event_type in {"Powerplay", "PowerplayRank"} and rank is not None:
        updates.update(
            rank=rank,
            rank_source_event=event_type,
            rank_timestamp=ts,
        )

    pp = replace(previous, **updates)
    return state.update_field(
        "phase9_powerplay",
        pp,
        TelemetrySource.JOURNAL,
        ts,
        _string_or_none(event.get("source_file")),
    )


# --- Snapshot composer (API-side, on-demand) -------------------------------


def local_context_snapshot_payload(
    state: StateManager | None,
    *,
    market_path: Path | None = None,
    outfitting_path: Path | None = None,
    shipyard_path: Path | None = None,
    cargo_path: Path | None = None,
    modules_info_path: Path | None = None,
    journal_dir_path: Path | None = None,
    status_path: Path | None = None,
) -> dict[str, Any]:
    """Compose the top-level Local Context snapshot payload.

    Read-only. No external lookups. Missing files surface as
    freshness="not_loaded" with explicit fallback wording, never as
    empty arrays.
    """
    from omnicovas.features.local_state_hydration import (
        hydrate_local_state_if_needed,
    )

    hydration = hydrate_local_state_if_needed(
        state,
        journal_dir_path=journal_dir_path,
        status_path=status_path,
        market_path=market_path,
        outfitting_path=outfitting_path,
        shipyard_path=shipyard_path,
        cargo_path=cargo_path,
        modules_info_path=modules_info_path,
    )
    session_payload = session_activity_payload(state, hydration)
    market_payload = market_snapshot_payload(state, market_path=market_path)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_activity": session_payload,
        "station_context": station_context_payload(
            state, market_payload, session_payload
        ),
        "system_context": system_context_payload(state, session_payload),
        "station_services": station_services_payload(state, session_payload),
        "market_snapshot": market_payload,
        "outfitting_snapshot": outfitting_snapshot_payload(
            state, outfitting_path=outfitting_path
        ),
        "shipyard_snapshot": shipyard_snapshot_payload(
            state, shipyard_path=shipyard_path
        ),
        "cargo_hold": cargo_hold_payload(state, cargo_path=cargo_path),
        "module_loadout": module_loadout_payload(
            state, modules_info_path=modules_info_path
        ),
        "wallet_snapshot": wallet_snapshot_payload(state),
        "missing_sources": _missing_sources(
            state,
            market_path=market_path,
            outfitting_path=outfitting_path,
            shipyard_path=shipyard_path,
            cargo_path=cargo_path,
        ),
        "nullprovider_safe": True,
    }


def phase9_bgs_facts_payload(state: StateManager | None) -> dict[str, Any]:
    """Compose the PB09-02 local-first BGS fact payload for Intel."""
    snap = state.snapshot if state is not None else None
    bgs = snap.phase9_bgs if snap is not None else None
    system_ctx = snap.local_system_context if snap is not None else None
    station_ctx = snap.local_station_context if snap is not None else None

    recent_mission_effects = (
        [_phase9_bgs_mission_effect_payload(entry) for entry in bgs.mission_effects]
        if bgs is not None
        else []
    )
    recent_reward_events = (
        [_phase9_bgs_reward_payload(entry) for entry in bgs.reward_events]
        if bgs is not None
        else []
    )

    missing_sources: list[str] = []
    if system_ctx is None:
        missing_sources.append("system_context")
    if station_ctx is None:
        missing_sources.append("station_context")
    if not recent_mission_effects:
        missing_sources.append("mission_completed_faction_effects")
    if not recent_reward_events:
        missing_sources.append("bgs_reward_events")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system_bgs": _phase9_system_bgs_payload(system_ctx),
        "station_bgs": _phase9_station_bgs_payload(station_ctx),
        "recent_mission_effects": recent_mission_effects,
        "recent_reward_events": recent_reward_events,
        "knowledge_references": _phase9_bgs_knowledge_references(),
        "unsupported_claims": [
            _phase9_unsupported_claim(
                "global_bgs_state",
                "Global BGS state",
                "No local Journal event provides global BGS state.",
            ),
            _phase9_unsupported_claim(
                "cross_commander_influence",
                "Cross-commander influence",
                "Cross-commander aggregation requires a disabled/gated provider.",
            ),
        ],
        "missing_sources": missing_sources,
        "nullprovider_safe": True,
    }


def phase9_powerplay_facts_payload(state: StateManager | None) -> dict[str, Any]:
    """Compose the PB09-02 local-first Powerplay fact payload for Intel."""
    snap = state.snapshot if state is not None else None
    pp = snap.phase9_powerplay if snap is not None else None
    system_ctx = snap.local_system_context if snap is not None else None
    events = (
        [_phase9_powerplay_event_payload(entry) for entry in pp.events]
        if pp is not None
        else []
    )

    missing_sources: list[str] = []
    if pp is None or (pp.pledge_status is None and pp.pledge_power is None):
        missing_sources.append("powerplay_pledge")
    if pp is None or pp.rank is None:
        missing_sources.append("powerplay_rank")
    if not events:
        missing_sources.append("powerplay_event_history")
    if system_ctx is None:
        missing_sources.append("system_context_powerplay")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pledge": _phase9_powerplay_pledge_payload(pp),
        "rank": _phase9_powerplay_rank_payload(pp),
        "system_powerplay": _phase9_system_powerplay_payload(system_ctx),
        "recent_events": events,
        "unsupported_claims": [
            _phase9_unsupported_claim(
                "global_powerplay_state",
                "Global Powerplay state",
                "No local Journal event provides global Powerplay state.",
            ),
            _phase9_unsupported_claim(
                "powerplay_merit_values",
                "Powerplay merit values",
                (
                    "Exact Powerplay merit values remain withheld while "
                    "powerplay2_mechanics.json has needs_review=true."
                ),
            ),
        ],
        "missing_sources": missing_sources,
        "nullprovider_safe": True,
    }


def session_activity_payload(
    state: StateManager | None,
    hydration: Any,
) -> dict[str, Any]:
    """Expose local Elite session activity without using generated_at."""
    last_journal_at = hydration.last_journal_event_at
    last_companion_at = hydration.companion_activity_at
    last_game_activity_at = _max_timestamp(last_journal_at, last_companion_at)

    if hydration.recent_journal_activity:
        elite_session_state = "active"
        source = "journal_watcher"
        freshness = LIVE_LOCAL_TELEMETRY
        truth_class = TRUTH_LOCAL_EVENT_HISTORY
        caveat = (
            "Recent Journal file activity was observed. Endpoint generation "
            "time is not used as gameplay activity."
        )
        fallback = None
    elif last_journal_at is not None or _has_usable_local_context(state):
        elite_session_state = "last_known"
        source = STARTUP_HYDRATION
        freshness = LAST_KNOWN
        truth_class = TRUTH_LOCAL_EVENT_HISTORY
        caveat = (
            "Local files provide last-known game state, but no recent Journal "
            "write indicates an active Elite session."
        )
        fallback = None
    elif last_companion_at is not None:
        elite_session_state = "last_known"
        source = "companion_snapshot"
        freshness = LAST_KNOWN
        truth_class = TRUTH_LOCAL_SCREEN_SNAPSHOT
        caveat = (
            "Companion snapshots are available, but no usable Journal event "
            "history was found."
        )
        fallback = None
    elif hydration.files_available:
        elite_session_state = "unknown"
        source = "unavailable"
        freshness = NOT_LOADED
        truth_class = TRUTH_UNKNOWN
        caveat = "Local files were present but no usable activity signal was derived."
        fallback = NO_VERIFIED_SOURCE
    else:
        elite_session_state = "waiting"
        source = "unavailable"
        freshness = NOT_LOADED
        truth_class = TRUTH_UNKNOWN
        caveat = (
            "No usable local Journal or companion snapshot has been loaded yet. "
            "Endpoint generation time is not gameplay activity."
        )
        fallback = NO_VERIFIED_SOURCE

    return {
        "source": source,
        "source_event": hydration.last_journal_event_type,
        "source_file": hydration.last_journal_file,
        "event_timestamp": last_journal_at,
        "freshness": freshness,
        "truth_class": truth_class,
        "caveat": caveat,
        "fallback": fallback,
        "elite_session_state": elite_session_state,
        "last_journal_event_at": last_journal_at,
        "last_journal_event_type": hydration.last_journal_event_type,
        "last_journal_file": hydration.last_journal_file,
        "last_game_activity_at": last_game_activity_at,
        "journal_files_scanned": list(hydration.journal_files_scanned),
        "nullprovider_safe": True,
    }


def wallet_snapshot_payload(state: StateManager | None) -> dict[str, Any]:
    """Source-backed commander wallet fields."""
    snap = state.snapshot if state is not None else None

    credits = _wallet_value_payload(
        value=snap.credit_balance if snap is not None else None,
        field_source=state.get_field_source("credit_balance") if state else None,
        default_source_event="LoadGame",
        missing_caveat="No verified local credit balance has been observed.",
    )
    loan = _wallet_value_payload(
        value=snap.loan if snap is not None else None,
        field_source=state.get_field_source("loan") if state else None,
        default_source_event="LoadGame",
        missing_caveat="No verified local loan value has been observed.",
    )

    direct_rebuy = snap.rebuy_cost if snap is not None else None
    if direct_rebuy is not None:
        rebuy = _wallet_value_payload(
            value=direct_rebuy,
            field_source=state.get_field_source("rebuy_cost") if state else None,
            default_source_event="Loadout",
            missing_caveat="No verified local rebuy value has been observed.",
        )
    else:
        calculated_rebuy = calculate_rebuy(state) if state is not None else None
        rebuy_source = None
        if state is not None:
            rebuy_source = (
                state.get_field_source("hull_value")
                or state.get_field_source("modules_value")
                or state.get_field_source("modules")
            )
        rebuy = _wallet_value_payload(
            value=calculated_rebuy,
            field_source=rebuy_source,
            default_source_event="Loadout",
            missing_caveat="No verified local rebuy value has been observed.",
            caveat=(
                "Estimated from source-backed Loadout hull/module values using "
                "the standard insurance rate."
                if calculated_rebuy is not None
                else None
            ),
        )

    carrier_balance = _wallet_value_payload(
        value=None,
        field_source=None,
        default_source_event=None,
        missing_caveat=(
            "No verified local carrier balance source has been observed; "
            "carrier balance is not invented."
        ),
    )

    fields = {
        "credits": credits,
        "rebuy": rebuy,
        "loan": loan,
        "carrier_balance": carrier_balance,
    }
    unavailable = [name for name, payload in fields.items() if payload["value"] is None]
    return {
        **fields,
        "missing_sources": unavailable.copy(),
        "unavailable_fields": unavailable,
        "nullprovider_safe": True,
    }


def station_context_payload(
    state: StateManager | None,
    market_payload: dict[str, Any] | None = None,
    session_activity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Field-rich local station context payload with freshness metadata."""
    ctx = state.snapshot.local_station_context if state is not None else None
    if ctx is None:
        partial = _market_only_station_context_payload(market_payload)
        if partial is not None:
            return partial
        return _not_loaded_station_context_payload()

    reasons = _station_context_stale_reasons(ctx, state, market_payload)
    freshness = (
        STALE
        if reasons
        else LAST_KNOWN
        if _is_last_known_session(session_activity)
        else FRESH
    )
    caveat_extra = f" Stale: {'; '.join(reasons)}." if reasons else ""
    session_caveat = (
        " Last-known local context hydrated from recent journal history."
        if freshness == LAST_KNOWN
        else ""
    )
    return {
        "source": ctx.source,
        "source_event": ctx.source_event,
        "source_file": ctx.source_file,
        "event_timestamp": ctx.event_timestamp,
        "freshness": freshness,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": (
            "Local station context preserved from journal station event; not "
            "a live continuous feed." + session_caveat + caveat_extra
        ),
        "fallback": None,
        "context_kind": "journal_station_context",
        "missing_fields": _station_missing_fields(ctx),
        "station_name": ctx.station_name,
        "station_type": ctx.station_type,
        "market_id": ctx.market_id,
        "star_system": ctx.star_system,
        "system_address": ctx.system_address,
        "is_docked": ctx.is_docked,
        "station_faction": ctx.station_faction,
        "station_government": ctx.station_government,
        "station_allegiance": ctx.station_allegiance,
        "station_economy": ctx.station_economy,
        "station_economies": list(ctx.station_economies),
        "station_services": list(ctx.station_services),
        "landing_pads": ctx.landing_pads,
        "dist_from_star_ls": ctx.dist_from_star_ls,
        "nullprovider_safe": True,
    }


def system_context_payload(
    state: StateManager | None,
    session_activity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Field-rich local system context payload with freshness metadata."""
    ctx = state.snapshot.local_system_context if state is not None else None
    if ctx is None:
        return _not_loaded_system_context_payload()

    reasons = _system_context_stale_reasons(ctx, state)
    freshness = (
        STALE
        if reasons
        else LAST_KNOWN
        if _is_last_known_session(session_activity)
        else FRESH
    )
    caveat_extra = f" Stale: {'; '.join(reasons)}." if reasons else ""
    session_caveat = (
        " Last-known local context hydrated from recent journal history."
        if freshness == LAST_KNOWN
        else ""
    )
    return {
        "source": ctx.source,
        "source_event": ctx.source_event,
        "source_file": ctx.source_file,
        "event_timestamp": ctx.event_timestamp,
        "freshness": freshness,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": (
            "Local system context preserved from journal "
            f"{ctx.source_event or 'event'}; reflects commander-observed "
            "telemetry at that moment." + session_caveat + caveat_extra
        ),
        "fallback": None,
        "star_system": ctx.star_system,
        "system_address": ctx.system_address,
        "star_pos": list(ctx.star_pos) if ctx.star_pos is not None else None,
        "body": ctx.body,
        "body_id": ctx.body_id,
        "body_type": ctx.body_type,
        "system_faction": ctx.system_faction,
        "system_allegiance": ctx.system_allegiance,
        "system_economy": ctx.system_economy,
        "system_second_economy": ctx.system_second_economy,
        "system_government": ctx.system_government,
        "system_security": ctx.system_security,
        "population": ctx.population,
        "powers": list(ctx.powers),
        "powerplay_state": ctx.powerplay_state,
        "factions": [dict(f) for f in ctx.factions],
        "conflicts": [dict(c) for c in ctx.conflicts],
        "nullprovider_safe": True,
    }


def station_services_payload(
    state: StateManager | None,
    session_activity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Station services view derived from LocalStationContext.

    Commander-observed at the moment of the most recent Docked event; the
    absence of a service on a later visit does NOT prove the station no
    longer offers it.
    """
    ctx = state.snapshot.local_station_context if state is not None else None
    if ctx is None or not ctx.station_services:
        return {
            "source": JOURNAL_SOURCE,
            "source_event": ctx.source_event if ctx is not None else None,
            "source_file": ctx.source_file if ctx is not None else None,
            "event_timestamp": ctx.event_timestamp if ctx is not None else None,
            "freshness": NOT_LOADED,
            "truth_class": TRUTH_UNKNOWN,
            "caveat": (
                "Station services are observed at the moment of the most "
                "recent Docked event; none has been recorded yet."
            ),
            "fallback": NO_LOCAL_STATION_SERVICES,
            "station_name": ctx.station_name if ctx is not None else None,
            "star_system": ctx.star_system if ctx is not None else None,
            "market_id": ctx.market_id if ctx is not None else None,
            "services": None,
            "nullprovider_safe": True,
        }
    return {
        "source": ctx.source,
        "source_event": ctx.source_event,
        "source_file": ctx.source_file,
        "event_timestamp": ctx.event_timestamp,
        "freshness": LAST_KNOWN
        if _is_last_known_session(session_activity)
        else COMMANDER_OBSERVED,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": (
            "Station services are commander-observed at the moment of the "
            "most recent Docked event; later changes are not implied."
        ),
        "fallback": None,
        "station_name": ctx.station_name,
        "star_system": ctx.star_system,
        "market_id": ctx.market_id,
        "services": list(ctx.station_services),
        "nullprovider_safe": True,
    }


def market_snapshot_payload(
    state: StateManager | None,
    *,
    market_path: Path | None = None,
) -> dict[str, Any]:
    """Field-rich Market.json snapshot preserving every Frontier-native item field.

    Distinct from local_economic_facts.market_snapshot_payload (which is a
    narrower projection); this preserves Name_Localised, Category_Localised,
    StatusFlags, Consumer, Producer, Rare, Prohibited verbatim per Local
    Data Surface Reference §6.3.
    """
    raw = _read_companion_json(MARKET_FILE, market_path)
    if raw is None:
        return _not_loaded_market_payload()

    reasons = _companion_station_stale_reasons(raw, state)
    freshness = STALE if reasons else FRESH
    caveat_extra = f" Stale: {'; '.join(reasons)}." if reasons else ""
    items_raw = raw.get("Items")
    items = (
        [
            _market_item_field_rich(entry)
            for entry in items_raw
            if isinstance(entry, dict)
        ]
        if isinstance(items_raw, list)
        else None
    )
    return {
        "source": MARKET_FILE,
        "source_event": "Market",
        "source_file": MARKET_FILE,
        "event_timestamp": _string_or_none(raw.get("timestamp")),
        "freshness": freshness,
        "truth_class": TRUTH_LOCAL_SCREEN_SNAPSHOT,
        "caveat": (
            "Local station market snapshot only; not live and not global "
            "market truth. Refreshes only when the commander opens the "
            "market screen." + caveat_extra
        ),
        "fallback": None,
        "market_id": raw.get("MarketID"),
        "station_name": _string_or_none(raw.get("StationName")),
        "star_system": _string_or_none(raw.get("StarSystem")),
        "items": items,
        "nullprovider_safe": True,
    }


def outfitting_snapshot_payload(
    state: StateManager | None,
    *,
    outfitting_path: Path | None = None,
) -> dict[str, Any]:
    """Local Outfitting.json snapshot for the current/visited station.

    This is a local screen snapshot only. It is not a global module
    availability source, not provider-backed, and not proof of stations the
    commander has not visited.
    """
    raw, read_status, _snapshot_path = _read_companion_json_with_status(
        OUTFITTING_FILE, outfitting_path
    )
    if raw is None:
        return _not_loaded_outfitting_payload(read_status)

    reasons = _outfitting_stale_reasons(raw, state)
    binding_caveats = _outfitting_binding_caveats(state)
    freshness = STALE if reasons else FRESH
    status = STALE if reasons else "loaded_unbound" if binding_caveats else "loaded"
    caveat_parts = [
        (
            "Known outfitting at selected station from local Outfitting.json; "
            "not live, not global module availability, and not provider-backed."
        )
    ]
    if reasons:
        caveat_parts.append(f"Outfitting snapshot stale: {'; '.join(reasons)}.")
    if binding_caveats:
        caveat_parts.extend(binding_caveats)

    items_raw = raw.get("Items")
    if isinstance(items_raw, list):
        items = [
            _outfitting_item_dict(entry)
            for entry in items_raw
            if isinstance(entry, dict)
        ]
        item_count: int | None = len(items)
    else:
        items = None
        item_count = None
        if "Items" not in raw:
            caveat_parts.append(
                "Items field is missing; module rows were not loaded from this file."
            )
        else:
            caveat_parts.append(
                "Items field is not a list; module rows were not loaded from this file."
            )
        if status == "loaded":
            status = "items_not_loaded"

    return {
        "source": OUTFITTING_FILE,
        "source_event": _string_or_none(raw.get("event")) or "Outfitting",
        "source_file": OUTFITTING_FILE,
        "event_timestamp": _string_or_none(raw.get("timestamp")),
        "observed_at": _string_or_none(raw.get("timestamp")),
        "freshness": freshness,
        "status": status,
        "truth_class": TRUTH_LOCAL_SCREEN_SNAPSHOT,
        "caveat": " ".join(caveat_parts),
        "fallback": None,
        "market_id": raw.get("MarketID"),
        "station_name": _string_or_none(raw.get("StationName")),
        "star_system": _string_or_none(raw.get("StarSystem")),
        "horizons": raw.get("Horizons")
        if isinstance(raw.get("Horizons"), bool)
        else None,
        "item_count": item_count,
        "items": items,
        "stale_reasons": reasons,
        "nullprovider_safe": True,
    }


def shipyard_snapshot_payload(
    state: StateManager | None,
    *,
    shipyard_path: Path | None = None,
) -> dict[str, Any]:
    """Local Shipyard.json snapshot for the current/visited station.

    This is a local screen snapshot only. It is not global ship availability,
    not provider-backed, and not proof of stations the commander has not opened
    the Shipyard screen at.
    """
    raw, read_status, _snapshot_path = _read_companion_json_with_status(
        SHIPYARD_FILE, shipyard_path
    )
    if raw is None:
        return _not_loaded_shipyard_payload(read_status)

    reasons = _shipyard_stale_reasons(raw, state)
    binding_caveats = _shipyard_binding_caveats(state)
    freshness = STALE if reasons else FRESH
    status = STALE if reasons else "loaded_unbound" if binding_caveats else "loaded"
    caveat_parts = [
        (
            "Known shipyard at selected station from local Shipyard.json; "
            "not live, not global ship availability, and not provider-backed."
        )
    ]
    if reasons:
        caveat_parts.append(f"Shipyard snapshot stale: {'; '.join(reasons)}.")
    if binding_caveats:
        caveat_parts.extend(binding_caveats)

    ships_raw = raw.get("PriceList")
    if isinstance(ships_raw, list):
        ships = [
            _shipyard_ship_dict(entry) for entry in ships_raw if isinstance(entry, dict)
        ]
        ship_count: int | None = len(ships)
    else:
        ships = None
        ship_count = None
        if "PriceList" not in raw:
            caveat_parts.append(
                "PriceList field is missing; ship rows were not loaded from this file."
            )
        else:
            caveat_parts.append(
                "PriceList field is not a list; ship rows were not loaded "
                "from this file."
            )
        if status == "loaded":
            status = "price_list_not_loaded"

    return {
        "source": SHIPYARD_FILE,
        "source_event": _string_or_none(raw.get("event")) or "Shipyard",
        "source_file": SHIPYARD_FILE,
        "event_timestamp": _string_or_none(raw.get("timestamp")),
        "observed_at": _string_or_none(raw.get("timestamp")),
        "freshness": freshness,
        "status": status,
        "truth_class": TRUTH_LOCAL_SCREEN_SNAPSHOT,
        "caveat": " ".join(caveat_parts),
        "fallback": None,
        "market_id": raw.get("MarketID"),
        "station_name": _string_or_none(raw.get("StationName")),
        "star_system": _string_or_none(raw.get("StarSystem")),
        "horizons": raw.get("Horizons")
        if isinstance(raw.get("Horizons"), bool)
        else None,
        "allow_cobra_mk_iv": raw.get("AllowCobraMkIV")
        if isinstance(raw.get("AllowCobraMkIV"), bool)
        else None,
        "ship_count": ship_count,
        "ships": ships,
        "stale_reasons": reasons,
        "nullprovider_safe": True,
    }


def cargo_hold_payload(
    state: StateManager | None,
    *,
    cargo_path: Path | None = None,
) -> dict[str, Any]:
    """Field-rich cargo hold payload preferring the newer of Cargo.json or
    the last Cargo journal event.

    Per Local Data Surface §7: when Cargo.json is older than the most
    recent Cargo journal event, prefer the journal-derived snapshot.
    """
    journal_snapshot = state.snapshot.cargo_hold_snapshot if state is not None else None
    file_raw = _read_companion_json(CARGO_FILE, cargo_path)

    file_timestamp = (
        _string_or_none(file_raw.get("timestamp")) if file_raw is not None else None
    )
    journal_timestamp = (
        journal_snapshot.event_timestamp if journal_snapshot is not None else None
    )

    prefer_file = _prefer_file_over_journal(file_timestamp, journal_timestamp)

    if file_raw is not None and prefer_file:
        items_raw = file_raw.get("Inventory")
        inventory = (
            [
                _cargo_item_dict_from_file(entry)
                for entry in items_raw
                if isinstance(entry, dict)
            ]
            if isinstance(items_raw, list)
            else []
        )
        return {
            "source": CARGO_FILE,
            "source_event": "Cargo",
            "source_file": CARGO_FILE,
            "event_timestamp": file_timestamp,
            "freshness": FRESH,
            "truth_class": TRUTH_LOCAL_SCREEN_SNAPSHOT,
            "caveat": (
                "Local cargo snapshot from Cargo.json; refreshed by the game "
                "on cargo changes."
            ),
            "fallback": None,
            "vessel": _string_or_none(file_raw.get("Vessel")) or "Ship",
            "capacity": _int_or_none(file_raw.get("Capacity"))
            or (state.snapshot.cargo_capacity if state is not None else None),
            "inventory": inventory,
            "total_count": _int_or_none(file_raw.get("Count"))
            or sum(int(it.get("count") or 0) for it in inventory),
            "nullprovider_safe": True,
        }

    if journal_snapshot is not None:
        return {
            "source": journal_snapshot.source,
            "source_event": journal_snapshot.source_event,
            "source_file": journal_snapshot.source_file,
            "event_timestamp": journal_snapshot.event_timestamp,
            "freshness": FRESH,
            "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
            "caveat": (
                "Local cargo snapshot from the most recent Cargo journal "
                "event; Stolen and MissionID flags preserved."
            ),
            "fallback": None,
            "vessel": journal_snapshot.vessel,
            "capacity": journal_snapshot.capacity
            or (state.snapshot.cargo_capacity if state is not None else None),
            "inventory": [asdict(item) for item in journal_snapshot.inventory],
            "total_count": sum(item.count for item in journal_snapshot.inventory),
            "nullprovider_safe": True,
        }

    return {
        "source": JOURNAL_SOURCE,
        "source_event": None,
        "source_file": None,
        "event_timestamp": None,
        "freshness": NOT_LOADED,
        "truth_class": TRUTH_UNKNOWN,
        "caveat": (
            "No verified local cargo snapshot has been observed. "
            "Missing companion files are not proof of absence."
        ),
        "fallback": NO_LOCAL_CARGO_SNAPSHOT,
        "vessel": None,
        "capacity": state.snapshot.cargo_capacity if state is not None else None,
        "inventory": None,
        "total_count": None,
        "nullprovider_safe": True,
    }


def module_loadout_payload(
    state: StateManager | None,
    *,
    modules_info_path: Path | None = None,
) -> dict[str, Any]:
    """Field-rich module loadout payload from Loadout, optionally overlaid
    by ModulesInfo.json when newer.

    Engineering block is preserved verbatim; not parsed (Phase 8 Pillar 6
    owns engineering deep-parse).
    """
    modules = state.snapshot.modules if state is not None else {}
    loadout_source = state.get_field_source("modules") if state is not None else None

    if not modules:
        return {
            "source": JOURNAL_SOURCE,
            "source_event": None,
            "source_file": None,
            "event_timestamp": None,
            "freshness": NOT_LOADED,
            "truth_class": TRUTH_UNKNOWN,
            "caveat": ("No verified local module loadout has been observed."),
            "fallback": NO_LOCAL_MODULE_LOADOUT,
            "vessel": state.snapshot.current_ship_type if state is not None else None,
            "loadout_hash": None,
            "hull_value": None,
            "modules_value": None,
            "modules": None,
            "shield_generator": _shield_generator_unknown_payload(),
            "nullprovider_safe": True,
        }

    overlay = _read_companion_json(MODULES_INFO_FILE, modules_info_path)
    overlay_by_slot = _modules_info_overlay(overlay)
    overlay_timestamp = (
        _string_or_none(overlay.get("timestamp")) if overlay is not None else None
    )
    journal_ts = loadout_source.timestamp if loadout_source is not None else None
    apply_overlay = overlay_by_slot and _prefer_file_over_journal(
        overlay_timestamp, journal_ts
    )

    overlay_caveat = ""
    source_label = JOURNAL_SOURCE
    if apply_overlay:
        source_label = f"{JOURNAL_SOURCE}+{MODULES_INFO_FILE}"
        overlay_caveat = (
            " Power/Priority overlaid from ModulesInfo.json (newer than Loadout event)."
        )

    module_rows: list[dict[str, Any]] = []
    for slot, module in modules.items():
        overlay_entry = overlay_by_slot.get(slot) if apply_overlay else None
        power = (
            overlay_entry.get("Power")
            if overlay_entry is not None and overlay_entry.get("Power") is not None
            else module.power
        )
        priority = (
            overlay_entry.get("Priority")
            if overlay_entry is not None and overlay_entry.get("Priority") is not None
            else module.priority
        )
        module_rows.append(
            {
                "slot": module.slot,
                "item": module.item,
                "item_localised": module.item_localised,
                "on": module.on,
                "priority": priority,
                "power": power,
                "health": module.health,
                "ammo_in_clip": module.ammo_in_clip,
                "ammo_in_hopper": module.ammo_in_hopper,
                "value": module.value,
                "engineering_raw": module.engineering,
            }
        )

    return {
        "source": source_label,
        "source_event": "Loadout",
        "source_file": loadout_source.source_file
        if loadout_source is not None
        else None,
        "event_timestamp": journal_ts,
        "freshness": FRESH,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": (
            "Local module loadout from the most recent Loadout journal event."
            + overlay_caveat
        ),
        "fallback": None,
        "vessel": state.snapshot.current_ship_type if state is not None else None,
        "loadout_hash": state.snapshot.loadout_hash if state is not None else None,
        "hull_value": state.snapshot.hull_value if state is not None else None,
        "modules_value": state.snapshot.modules_value if state is not None else None,
        "modules": module_rows,
        "shield_generator": _shield_generator_payload(
            modules,
            loadout_source=loadout_source,
        ),
        "nullprovider_safe": True,
    }


def _market_only_station_context_payload(
    market_payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if market_payload is None or market_payload.get("fallback") is not None:
        return None
    station_name = _string_or_none(market_payload.get("station_name"))
    star_system = _string_or_none(market_payload.get("star_system"))
    market_id = _int_or_none(market_payload.get("market_id"))
    if station_name is None and star_system is None and market_id is None:
        return None
    return {
        "source": MARKET_FILE,
        "source_event": "Market",
        "source_file": MARKET_FILE,
        "event_timestamp": _string_or_none(market_payload.get("event_timestamp")),
        "freshness": MARKET_SNAPSHOT_ONLY,
        "truth_class": TRUTH_LOCAL_SCREEN_SNAPSHOT,
        "caveat": (
            "Station market snapshot available. Full station context will "
            "refresh on the next Docked or Location journal event."
        ),
        "fallback": None,
        "context_kind": MARKET_SNAPSHOT_ONLY,
        "missing_fields": [
            "is_docked",
            "station_type",
            "station_services",
            "landing_pads",
            "station_faction",
        ],
        "station_name": station_name,
        "station_type": None,
        "market_id": market_id,
        "star_system": star_system,
        "system_address": None,
        "is_docked": None,
        "station_faction": None,
        "station_government": None,
        "station_allegiance": None,
        "station_economy": None,
        "station_economies": None,
        "station_services": None,
        "landing_pads": None,
        "dist_from_star_ls": None,
        "nullprovider_safe": True,
    }


def _wallet_value_payload(
    *,
    value: int | None,
    field_source: Any,
    default_source_event: str | None,
    missing_caveat: str,
    caveat: str | None = None,
) -> dict[str, Any]:
    if value is None:
        return {
            "value": None,
            "source": "unavailable",
            "source_event": default_source_event,
            "source_file": None,
            "event_timestamp": None,
            "freshness": NOT_LOADED,
            "truth_class": TRUTH_UNKNOWN,
            "caveat": missing_caveat,
            "fallback": NO_VERIFIED_SOURCE,
            "nullprovider_safe": True,
        }

    source_label = _field_source_label(field_source)
    source_event = (
        "Status"
        if source_label == STATUS_FILE and default_source_event == "LoadGame"
        else default_source_event
    )
    return {
        "value": value,
        "source": source_label,
        "source_event": source_event,
        "source_file": field_source.source_file if field_source is not None else None,
        "event_timestamp": field_source.timestamp if field_source is not None else None,
        "freshness": LAST_KNOWN,
        "truth_class": LIVE_LOCAL_TELEMETRY
        if source_label == STATUS_FILE
        else TRUTH_LOCAL_EVENT_HISTORY
        if source_label == JOURNAL_SOURCE
        else TRUTH_LOCAL_SCREEN_SNAPSHOT,
        "caveat": caveat or "Source-backed local wallet field.",
        "fallback": None,
        "nullprovider_safe": True,
    }


def _field_source_label(field_source: Any) -> str:
    if field_source is None:
        return JOURNAL_SOURCE
    source_name = getattr(getattr(field_source, "source", None), "name", "")
    if source_name == "STATUS_JSON":
        return STATUS_FILE
    if source_name == "JOURNAL":
        return JOURNAL_SOURCE
    return source_name.lower() if source_name else "unknown"


def _shield_generator_payload(
    modules: dict[str, Any],
    *,
    loadout_source: Any,
) -> dict[str, Any]:
    for module in modules.values():
        item = module.item.lower()
        localised = (module.item_localised or "").lower()
        if item.startswith("int_shieldgenerator") or "shield generator" in localised:
            return {
                "fitted": True,
                "slot": module.slot,
                "item": module.item,
                "item_localised": module.item_localised,
                "source": JOURNAL_SOURCE,
                "source_event": "Loadout",
                "source_file": loadout_source.source_file
                if loadout_source is not None
                else None,
                "event_timestamp": loadout_source.timestamp
                if loadout_source is not None
                else None,
                "freshness": LAST_KNOWN,
                "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
                "caveat": "Shield generator fitted state is sourced from Loadout.",
                "fallback": None,
                "nullprovider_safe": True,
            }

    source_file = loadout_source.source_file if loadout_source is not None else None
    timestamp = loadout_source.timestamp if loadout_source is not None else None
    return {
        "fitted": False,
        "slot": None,
        "item": None,
        "item_localised": None,
        "source": JOURNAL_SOURCE,
        "source_event": "Loadout",
        "source_file": source_file,
        "event_timestamp": timestamp,
        "freshness": LAST_KNOWN,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": (
            "No shield generator module was present in the source-backed "
            "Loadout. This is a ship configuration state, not a failure."
        ),
        "fallback": None,
        "nullprovider_safe": True,
    }


def _shield_generator_unknown_payload() -> dict[str, Any]:
    return {
        "fitted": None,
        "slot": None,
        "item": None,
        "item_localised": None,
        "source": JOURNAL_SOURCE,
        "source_event": "Loadout",
        "source_file": None,
        "event_timestamp": None,
        "freshness": NOT_LOADED,
        "truth_class": TRUTH_UNKNOWN,
        "caveat": "No verified local Loadout has been observed.",
        "fallback": NO_LOCAL_MODULE_LOADOUT,
        "nullprovider_safe": True,
    }


def _station_missing_fields(ctx: LocalStationContext) -> list[str]:
    missing: list[str] = []
    for field_name in (
        "station_name",
        "station_type",
        "market_id",
        "star_system",
        "system_address",
        "station_services",
        "landing_pads",
    ):
        value = getattr(ctx, field_name)
        if value is None or value == []:
            missing.append(field_name)
    return missing


def _is_last_known_session(session_activity: dict[str, Any] | None) -> bool:
    return (
        session_activity is not None
        and session_activity.get("elite_session_state") == "last_known"
    )


def _has_usable_local_context(state: StateManager | None) -> bool:
    if state is None:
        return False
    snap = state.snapshot
    return any(
        (
            snap.local_station_context is not None,
            snap.local_system_context is not None,
            bool(snap.modules),
            snap.cargo_hold_snapshot is not None,
            snap.credit_balance is not None,
        )
    )


def _max_timestamp(*values: str | None) -> str | None:
    present = [value for value in values if value]
    return max(present) if present else None


# --- Internal helpers ------------------------------------------------------


def _read_companion_json(filename: str, path: Path | None) -> dict[str, Any] | None:
    snapshot_path = path if path is not None else _default_companion_path(filename)
    if snapshot_path is None or not snapshot_path.exists():
        return None
    try:
        raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _read_companion_json_with_status(
    filename: str, path: Path | None
) -> tuple[dict[str, Any] | None, str, Path | None]:
    snapshot_path = path if path is not None else _default_companion_path(filename)
    if snapshot_path is None or not snapshot_path.exists():
        return None, "missing", snapshot_path
    try:
        raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, "malformed", snapshot_path
    except OSError:
        return None, "unreadable", snapshot_path
    if not isinstance(raw, dict):
        return None, "malformed", snapshot_path
    return raw, "loaded", snapshot_path


def _default_companion_path(filename: str) -> Path | None:
    profile = os.environ.get("USERPROFILE", "")
    if not profile:
        return None
    return (
        Path(profile)
        / "Saved Games"
        / "Frontier Developments"
        / "Elite Dangerous"
        / filename
    )


def _not_loaded_station_context_payload() -> dict[str, Any]:
    return {
        "source": JOURNAL_SOURCE,
        "source_event": None,
        "source_file": None,
        "event_timestamp": None,
        "freshness": NOT_LOADED,
        "truth_class": TRUTH_UNKNOWN,
        "caveat": ("No verified local station context has been observed this session."),
        "fallback": NO_LOCAL_STATION_CONTEXT,
        "context_kind": "not_loaded",
        "missing_fields": [
            "station_name",
            "market_id",
            "star_system",
            "station_services",
        ],
        "station_name": None,
        "station_type": None,
        "market_id": None,
        "star_system": None,
        "system_address": None,
        "is_docked": None,
        "station_faction": None,
        "station_government": None,
        "station_allegiance": None,
        "station_economy": None,
        "station_economies": None,
        "station_services": None,
        "landing_pads": None,
        "dist_from_star_ls": None,
        "nullprovider_safe": True,
    }


def _not_loaded_system_context_payload() -> dict[str, Any]:
    return {
        "source": JOURNAL_SOURCE,
        "source_event": None,
        "source_file": None,
        "event_timestamp": None,
        "freshness": NOT_LOADED,
        "truth_class": TRUTH_UNKNOWN,
        "caveat": ("No verified local system context has been observed this session."),
        "fallback": NO_LOCAL_SYSTEM_CONTEXT,
        "star_system": None,
        "system_address": None,
        "star_pos": None,
        "body": None,
        "body_id": None,
        "body_type": None,
        "system_faction": None,
        "system_allegiance": None,
        "system_economy": None,
        "system_second_economy": None,
        "system_government": None,
        "system_security": None,
        "population": None,
        "powers": None,
        "powerplay_state": None,
        "factions": None,
        "conflicts": None,
        "nullprovider_safe": True,
    }


def _not_loaded_market_payload() -> dict[str, Any]:
    return {
        "source": MARKET_FILE,
        "source_event": "Market",
        "source_file": MARKET_FILE,
        "event_timestamp": None,
        "freshness": NOT_LOADED,
        "truth_class": TRUTH_UNKNOWN,
        "caveat": (
            "Local station market snapshot only; missing companion files are "
            "not proof of absence."
        ),
        "fallback": NO_LOCAL_MARKET_SNAPSHOT,
        "market_id": None,
        "station_name": None,
        "star_system": None,
        "items": None,
        "nullprovider_safe": True,
    }


def _not_loaded_outfitting_payload(read_status: str) -> dict[str, Any]:
    if read_status == "malformed":
        caveat = (
            "Outfitting.json could not be parsed as a valid local snapshot. "
            "Malformed companion files are not proof of module absence."
        )
    elif read_status == "unreadable":
        caveat = (
            "Outfitting.json could not be read. Unreadable companion files are "
            "not proof of module absence."
        )
    else:
        caveat = (
            "No verified local outfitting snapshot has been loaded. Missing "
            "companion files are not proof of module absence."
        )
    return {
        "source": OUTFITTING_FILE,
        "source_event": "Outfitting",
        "source_file": OUTFITTING_FILE,
        "event_timestamp": None,
        "observed_at": None,
        "freshness": NOT_LOADED,
        "status": NOT_LOADED,
        "truth_class": TRUTH_UNKNOWN,
        "caveat": caveat,
        "fallback": NO_LOCAL_OUTFITTING_SNAPSHOT,
        "market_id": None,
        "station_name": None,
        "star_system": None,
        "horizons": None,
        "item_count": None,
        "items": None,
        "stale_reasons": [],
        "nullprovider_safe": True,
    }


def _not_loaded_shipyard_payload(read_status: str) -> dict[str, Any]:
    if read_status == "malformed":
        caveat = (
            "Shipyard.json could not be parsed as a valid local snapshot. "
            "Malformed companion files are not proof of ship absence."
        )
    elif read_status == "unreadable":
        caveat = (
            "Shipyard.json could not be read. Unreadable companion files are "
            "not proof of ship absence."
        )
    else:
        caveat = (
            "No verified local shipyard snapshot has been loaded. Missing "
            "companion files are not proof of ship absence."
        )
    return {
        "source": SHIPYARD_FILE,
        "source_event": "Shipyard",
        "source_file": SHIPYARD_FILE,
        "event_timestamp": None,
        "observed_at": None,
        "freshness": NOT_LOADED,
        "status": NOT_LOADED,
        "truth_class": TRUTH_UNKNOWN,
        "caveat": caveat,
        "fallback": NO_LOCAL_SHIPYARD_SNAPSHOT,
        "market_id": None,
        "station_name": None,
        "star_system": None,
        "horizons": None,
        "allow_cobra_mk_iv": None,
        "ship_count": None,
        "ships": None,
        "stale_reasons": [],
        "nullprovider_safe": True,
    }


def _station_context_stale_reasons(
    ctx: LocalStationContext,
    state: StateManager | None,
    market_payload: dict[str, Any] | None,
) -> list[str]:
    reasons: list[str] = []
    if state is None:
        return reasons
    live = state.snapshot
    if live.is_docked is False:
        reasons.append("commander has undocked since the station snapshot")
    if (
        live.current_station is not None
        and ctx.station_name is not None
        and live.current_station != ctx.station_name
    ):
        reasons.append(
            f"current station is {live.current_station}, snapshot station is "
            f"{ctx.station_name}"
        )
    if market_payload is not None:
        live_market_id = market_payload.get("market_id")
        if (
            ctx.market_id is not None
            and live_market_id is not None
            and ctx.market_id != live_market_id
        ):
            reasons.append(
                f"current Market.json MarketID is {live_market_id}, snapshot "
                f"MarketID is {ctx.market_id}"
            )
    return reasons


def _system_context_stale_reasons(
    ctx: LocalSystemContext,
    state: StateManager | None,
) -> list[str]:
    reasons: list[str] = []
    if state is None:
        return reasons
    live = state.snapshot
    if (
        live.current_system is not None
        and ctx.star_system is not None
        and live.current_system != ctx.star_system
    ):
        reasons.append(
            f"current system is {live.current_system}, snapshot system is "
            f"{ctx.star_system}"
        )
    return reasons


def _companion_station_stale_reasons(
    snapshot: dict[str, Any],
    state: StateManager | None,
) -> list[str]:
    """Mirror of local_economic_facts._station_stale_reasons (duplicated to
    avoid a cross-module private import; small enough to keep local)."""
    if state is None:
        return []
    current = state.snapshot
    reasons: list[str] = []
    if current.is_docked is False:
        reasons.append("commander has undocked since the station snapshot")
    station_name = _string_or_none(snapshot.get("StationName"))
    if (
        current.current_station
        and station_name
        and current.current_station != station_name
    ):
        reasons.append(
            f"current station is {current.current_station}, snapshot station is "
            f"{station_name}"
        )
    star_system = _string_or_none(snapshot.get("StarSystem"))
    if current.current_system and star_system and current.current_system != star_system:
        reasons.append(
            f"current system is {current.current_system}, snapshot system is "
            f"{star_system}"
        )
    return reasons


def _outfitting_stale_reasons(
    snapshot: dict[str, Any],
    state: StateManager | None,
) -> list[str]:
    if state is None:
        return []
    current = state.snapshot
    station_ctx = current.local_station_context
    reasons: list[str] = []
    if current.is_docked is False:
        reasons.append("commander has undocked since the outfitting snapshot")

    snapshot_market_id = _int_or_none(snapshot.get("MarketID"))
    current_market_id = station_ctx.market_id if station_ctx is not None else None
    if (
        current_market_id is not None
        and snapshot_market_id is not None
        and current_market_id != snapshot_market_id
    ):
        reasons.append(
            f"current station MarketID is {current_market_id}, outfitting "
            f"snapshot MarketID is {snapshot_market_id}"
        )

    snapshot_station = _string_or_none(snapshot.get("StationName"))
    current_station = current.current_station or (
        station_ctx.station_name if station_ctx is not None else None
    )
    if current_station and snapshot_station and current_station != snapshot_station:
        reasons.append(
            f"current station is {current_station}, outfitting snapshot "
            f"station is {snapshot_station}"
        )

    snapshot_system = _string_or_none(snapshot.get("StarSystem"))
    current_system = current.current_system or (
        station_ctx.star_system if station_ctx is not None else None
    )
    if current_system and snapshot_system and current_system != snapshot_system:
        reasons.append(
            f"current system is {current_system}, outfitting snapshot system "
            f"is {snapshot_system}"
        )
    return reasons


def _outfitting_binding_caveats(state: StateManager | None) -> list[str]:
    if state is None:
        return [
            (
                "No current local station context is loaded; snapshot identity "
                "is file-derived only."
            )
        ]
    current = state.snapshot
    if current.local_station_context is None and current.current_station is None:
        return [
            (
                "No current local station context is loaded; snapshot identity "
                "is file-derived only."
            )
        ]
    return []


def _shipyard_stale_reasons(
    snapshot: dict[str, Any],
    state: StateManager | None,
) -> list[str]:
    if state is None:
        return []
    current = state.snapshot
    station_ctx = current.local_station_context
    reasons: list[str] = []
    if current.is_docked is False:
        reasons.append("commander has undocked since the shipyard snapshot")

    snapshot_market_id = _int_or_none(snapshot.get("MarketID"))
    current_market_id = station_ctx.market_id if station_ctx is not None else None
    if (
        current_market_id is not None
        and snapshot_market_id is not None
        and current_market_id != snapshot_market_id
    ):
        reasons.append(
            f"current station MarketID is {current_market_id}, shipyard "
            f"snapshot MarketID is {snapshot_market_id}"
        )

    snapshot_station = _string_or_none(snapshot.get("StationName"))
    current_station = current.current_station or (
        station_ctx.station_name if station_ctx is not None else None
    )
    if current_station and snapshot_station and current_station != snapshot_station:
        reasons.append(
            f"current station is {current_station}, shipyard snapshot station "
            f"is {snapshot_station}"
        )

    snapshot_system = _string_or_none(snapshot.get("StarSystem"))
    current_system = current.current_system or (
        station_ctx.star_system if station_ctx is not None else None
    )
    if current_system and snapshot_system and current_system != snapshot_system:
        reasons.append(
            f"current system is {current_system}, shipyard snapshot system is "
            f"{snapshot_system}"
        )
    return reasons


def _shipyard_binding_caveats(state: StateManager | None) -> list[str]:
    if state is None:
        return [
            (
                "No current local station context is loaded; snapshot identity "
                "is file-derived only."
            )
        ]
    current = state.snapshot
    if current.local_station_context is None and current.current_station is None:
        return [
            (
                "No current local station context is loaded; snapshot identity "
                "is file-derived only."
            )
        ]
    return []


def _market_item_field_rich(entry: dict[str, Any]) -> dict[str, Any]:
    """Preserve every documented Market.json Items[] field verbatim."""
    return {
        "id": entry.get("id"),
        "name": _string_or_none(entry.get("Name")),
        "name_localised": _string_or_none(entry.get("Name_Localised")),
        "category": _string_or_none(entry.get("Category")),
        "category_localised": _string_or_none(entry.get("Category_Localised")),
        "buy_price": entry.get("BuyPrice"),
        "sell_price": entry.get("SellPrice"),
        "mean_price": entry.get("MeanPrice"),
        "stock": entry.get("Stock"),
        "stock_bracket": entry.get("StockBracket"),
        "demand": entry.get("Demand"),
        "demand_bracket": entry.get("DemandBracket"),
        "consumer": entry.get("Consumer"),
        "producer": entry.get("Producer"),
        "rare": entry.get("Rare"),
        "prohibited": entry.get("Prohibited"),
        "status_flags": _list_of_strings(entry.get("StatusFlags")),
    }


def _outfitting_item_dict(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "name": _string_or_none(entry.get("Name")),
        "buy_price": entry.get("BuyPrice"),
    }


def _shipyard_ship_dict(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "ship_type": _string_or_none(entry.get("ShipType")),
        "ship_price": entry.get("ShipPrice"),
    }


def _cargo_item_dict_from_file(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _string_or_none(entry.get("Name")) or "",
        "name_localised": _string_or_none(entry.get("Name_Localised")),
        "count": _int_or_none(entry.get("Count")) or 0,
        "stolen": _int_or_none(entry.get("Stolen")),
        "mission_id": _int_or_none(entry.get("MissionID")),
    }


def _modules_info_overlay(raw: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Index ModulesInfo.json Modules[] by Slot for Power/Priority overlay."""
    if raw is None:
        return {}
    modules = raw.get("Modules")
    if not isinstance(modules, list):
        return {}
    by_slot: dict[str, dict[str, Any]] = {}
    for entry in modules:
        if not isinstance(entry, dict):
            continue
        slot = entry.get("Slot")
        if not isinstance(slot, str):
            continue
        by_slot[slot] = entry
    return by_slot


def _prefer_file_over_journal(
    file_timestamp: str | None,
    journal_timestamp: str | None,
) -> bool:
    """Prefer the file timestamp when it is strictly newer than the journal
    event timestamp. ISO-8601 timestamps compare lexicographically when both
    use Z suffix (UTC); a missing journal timestamp means we have no journal
    snapshot to defer to."""
    if file_timestamp is None:
        return False
    if journal_timestamp is None:
        return True
    return file_timestamp > journal_timestamp


def _missing_sources(
    state: StateManager | None,
    *,
    market_path: Path | None,
    outfitting_path: Path | None,
    shipyard_path: Path | None,
    cargo_path: Path | None,
) -> list[str]:
    missing: list[str] = []
    market_raw = _read_companion_json(MARKET_FILE, market_path)
    has_market_station = market_raw is not None and (
        _string_or_none(market_raw.get("StationName")) is not None
        or _string_or_none(market_raw.get("StarSystem")) is not None
        or _int_or_none(market_raw.get("MarketID")) is not None
    )
    if (
        state is None or state.snapshot.local_station_context is None
    ) and not has_market_station:
        missing.append("station_context")
    if state is None or state.snapshot.local_system_context is None:
        missing.append("system_context")
    has_services = (
        state is not None
        and state.snapshot.local_station_context is not None
        and bool(state.snapshot.local_station_context.station_services)
    )
    if not has_services and "station_services" not in missing:
        missing.append("station_services")
    if market_raw is None:
        missing.append("market_snapshot")
    if _read_companion_json(OUTFITTING_FILE, outfitting_path) is None:
        missing.append("outfitting_snapshot")
    if _read_companion_json(SHIPYARD_FILE, shipyard_path) is None:
        missing.append("shipyard_snapshot")
    if _read_companion_json(CARGO_FILE, cargo_path) is None and (
        state is None or state.snapshot.cargo_hold_snapshot is None
    ):
        missing.append("cargo_hold")
    if state is None or not state.snapshot.modules:
        missing.append("module_loadout")
    if state is None or (
        state.snapshot.credit_balance is None
        and state.snapshot.rebuy_cost is None
        and state.snapshot.loan is None
    ):
        missing.append("wallet_snapshot")
    return missing


# --- Phase 9 PB09-02 projection helpers -----------------------------------


def _phase9_system_bgs_payload(ctx: LocalSystemContext | None) -> dict[str, Any]:
    if ctx is None:
        return {
            **_phase9_source_payload(
                source=JOURNAL_SOURCE,
                source_event=None,
                event_timestamp=None,
                source_file=None,
                freshness=NOT_LOADED,
                truth_class=TRUTH_UNKNOWN,
                caveat="No verified local system BGS context has been observed.",
                fallback=NOT_LOADED_DISPLAY,
            ),
            "scope": "current_system",
            "system_name": None,
            "controlling_faction": None,
            "controlling_faction_fallback": NOT_LOADED_DISPLAY,
            "factions": [],
            "faction_count": 0,
            "factions_fallback": NOT_LOADED_DISPLAY,
        }

    controlling_faction = _named_object(ctx.system_faction)
    factions = deepcopy(ctx.factions)
    return {
        **_phase9_source_payload(
            source=ctx.source,
            source_event=ctx.source_event,
            event_timestamp=ctx.event_timestamp,
            source_file=ctx.source_file,
            freshness=LAST_KNOWN,
            truth_class=TRUTH_LOCAL_EVENT_HISTORY,
            caveat=(
                "Local system BGS context preserved from a Journal system event; "
                "not a global BGS feed."
            ),
            fallback=None,
        ),
        "scope": "current_system",
        "system_name": ctx.star_system,
        "controlling_faction": controlling_faction,
        "controlling_faction_fallback": None if controlling_faction else UNKNOWN,
        "factions": factions,
        "faction_count": len(factions),
        "factions_fallback": None if factions else UNKNOWN,
    }


def _phase9_station_bgs_payload(ctx: LocalStationContext | None) -> dict[str, Any]:
    if ctx is None:
        return {
            **_phase9_source_payload(
                source=JOURNAL_SOURCE,
                source_event=None,
                event_timestamp=None,
                source_file=None,
                freshness=NOT_LOADED,
                truth_class=TRUTH_UNKNOWN,
                caveat="No verified local station BGS context has been observed.",
                fallback=NOT_LOADED_DISPLAY,
            ),
            "scope": "current_station",
            "station_name": None,
            "system_name": None,
            "controlling_faction": None,
            "controlling_faction_fallback": NOT_LOADED_DISPLAY,
        }

    controlling_faction = _named_object(ctx.station_faction)
    return {
        **_phase9_source_payload(
            source=ctx.source,
            source_event=ctx.source_event,
            event_timestamp=ctx.event_timestamp,
            source_file=ctx.source_file,
            freshness=LAST_KNOWN,
            truth_class=TRUTH_LOCAL_EVENT_HISTORY,
            caveat=(
                "Local station faction context preserved from a Journal station "
                "event; not a global BGS feed."
            ),
            fallback=None,
        ),
        "scope": "current_station",
        "station_name": ctx.station_name,
        "system_name": ctx.star_system,
        "controlling_faction": controlling_faction,
        "controlling_faction_fallback": None if controlling_faction else UNKNOWN,
    }


def _phase9_bgs_mission_effect_payload(
    entry: Phase9BgsMissionEffect,
) -> dict[str, Any]:
    return {
        **asdict(entry),
        **_phase9_source_payload(
            source=entry.source,
            source_event=entry.source_event,
            event_timestamp=entry.event_timestamp,
            source_file=entry.source_file,
            freshness=LOCAL_EVENT_HISTORY,
            truth_class=TRUTH_LOCAL_EVENT_HISTORY,
            caveat=(
                "MissionCompleted.FactionEffects observed locally. OmniCOVAS "
                "does not infer global BGS impact from this event."
            ),
            fallback=None,
        ),
    }


def _phase9_bgs_reward_payload(entry: Phase9BgsRewardEvent) -> dict[str, Any]:
    return {
        **asdict(entry),
        **_phase9_source_payload(
            source=entry.source,
            source_event=entry.source_event,
            event_timestamp=entry.event_timestamp,
            source_file=entry.source_file,
            freshness=LOCAL_EVENT_HISTORY,
            truth_class=TRUTH_LOCAL_EVENT_HISTORY,
            caveat=(
                "Local bounty/bond reward event observed. OmniCOVAS does not "
                "infer global BGS impact from this event."
            ),
            fallback=None,
        ),
    }


def _phase9_powerplay_pledge_payload(pp: Any) -> dict[str, Any]:
    if pp is None or (pp.pledge_status is None and pp.pledge_power is None):
        return {
            **_phase9_source_payload(
                source=JOURNAL_SOURCE,
                source_event=None,
                event_timestamp=None,
                source_file=None,
                freshness=NOT_LOADED,
                truth_class=TRUTH_UNKNOWN,
                caveat="No verified local Powerplay pledge event has been observed.",
                fallback=NOT_LOADED_DISPLAY,
            ),
            "value": None,
            "power": None,
            "status": None,
        }

    value = "Unpledged" if pp.pledge_status == "unpledged_observed" else pp.pledge_power
    return {
        **_phase9_source_payload(
            source=JOURNAL_SOURCE,
            source_event=pp.pledge_source_event,
            event_timestamp=pp.pledge_timestamp,
            source_file=None,
            freshness=LOCAL_EVENT_HISTORY,
            truth_class=TRUTH_LOCAL_EVENT_HISTORY,
            caveat=(
                "Powerplay pledge state is local event history only; no global "
                "Powerplay state is claimed."
            ),
            fallback=None,
        ),
        "value": value,
        "power": pp.pledge_power,
        "status": pp.pledge_status,
    }


def _phase9_powerplay_rank_payload(pp: Any) -> dict[str, Any]:
    if pp is None or pp.rank is None:
        return {
            **_phase9_source_payload(
                source=JOURNAL_SOURCE,
                source_event=None,
                event_timestamp=None,
                source_file=None,
                freshness=NOT_LOADED,
                truth_class=TRUTH_UNKNOWN,
                caveat="No verified local Powerplay rank event has been observed.",
                fallback=NOT_LOADED_DISPLAY,
            ),
            "value": None,
        }

    return {
        **_phase9_source_payload(
            source=JOURNAL_SOURCE,
            source_event=pp.rank_source_event,
            event_timestamp=pp.rank_timestamp,
            source_file=None,
            freshness=LOCAL_EVENT_HISTORY,
            truth_class=TRUTH_LOCAL_EVENT_HISTORY,
            caveat="Powerplay rank is sourced from local Journal history.",
            fallback=None,
        ),
        "value": pp.rank,
    }


def _phase9_system_powerplay_payload(
    ctx: LocalSystemContext | None,
) -> dict[str, Any]:
    if ctx is None:
        return {
            **_phase9_source_payload(
                source=JOURNAL_SOURCE,
                source_event=None,
                event_timestamp=None,
                source_file=None,
                freshness=NOT_LOADED,
                truth_class=TRUTH_UNKNOWN,
                caveat="No verified local system Powerplay context has been observed.",
                fallback=NOT_LOADED_DISPLAY,
            ),
            "system_name": None,
            "powers": [],
            "powerplay_state": None,
        }

    has_powerplay_context = bool(ctx.powers) or ctx.powerplay_state is not None
    return {
        **_phase9_source_payload(
            source=ctx.source,
            source_event=ctx.source_event,
            event_timestamp=ctx.event_timestamp,
            source_file=ctx.source_file,
            freshness=LAST_KNOWN,
            truth_class=TRUTH_LOCAL_EVENT_HISTORY,
            caveat=(
                "Powerplay system context is observed in local Journal system "
                "context only; no global Powerplay map is claimed."
            ),
            fallback=None if has_powerplay_context else UNKNOWN,
        ),
        "system_name": ctx.star_system,
        "powers": list(ctx.powers),
        "powerplay_state": ctx.powerplay_state,
    }


def _phase9_powerplay_event_payload(entry: Phase9PowerplayEvent) -> dict[str, Any]:
    return {
        **asdict(entry),
        **_phase9_source_payload(
            source=entry.source,
            source_event=entry.source_event,
            event_timestamp=entry.event_timestamp,
            source_file=entry.source_file,
            freshness=LOCAL_EVENT_HISTORY,
            truth_class=TRUTH_LOCAL_EVENT_HISTORY,
            caveat=(
                "Local Powerplay event observed. Exact merit values are withheld "
                "while the Powerplay 2.0 KB review gate remains open."
            )
            if entry.withheld_fields
            else (
                "Local Powerplay event observed; no global Powerplay state is claimed."
            ),
            fallback=None,
        ),
    }


def _phase9_unsupported_claim(
    field_key: str,
    label: str,
    caveat: str,
) -> dict[str, Any]:
    return {
        **_phase9_source_payload(
            source="unsupported",
            source_event=None,
            event_timestamp=None,
            source_file=None,
            freshness="unknown",
            truth_class=TRUTH_UNKNOWN,
            caveat=caveat,
            fallback=UNSUPPORTED,
        ),
        "field_key": field_key,
        "label": label,
        "value": None,
    }


def _phase9_bgs_knowledge_references() -> list[dict[str, Any]]:
    kb_dir = Path(__file__).resolve().parents[1] / "knowledge_base"
    try:
        entry = load_knowledge_base(kb_dir).get("bgs_mechanics", "bgs_tick")
    except Exception:
        logger.exception("Failed to load BGS knowledge reference")
        return []
    if entry is None or entry.needs_review:
        return []
    return [
        {
            **_phase9_source_payload(
                source=KNOWLEDGE_REFERENCE,
                source_event="bgs_mechanics.json",
                event_timestamp=entry.last_updated,
                source_file="bgs_mechanics.json",
                freshness=KNOWLEDGE_REFERENCE,
                truth_class=KNOWLEDGE_REFERENCE,
                caveat=(
                    "Knowledge reference material only; not local telemetry, "
                    "not a provider lookup, and not a global BGS fact."
                ),
                fallback=None,
            ),
            "id": entry.id,
            "topic": entry.topic,
            "content": entry.content,
            "patch_verified": entry.patch_verified,
            "reference_source": entry.source,
            "confidence": entry.confidence,
        }
    ]


def _phase9_source_payload(
    *,
    source: str,
    source_event: str | None,
    event_timestamp: str | None,
    source_file: str | None,
    freshness: str,
    truth_class: str,
    caveat: str,
    fallback: str | None,
) -> dict[str, Any]:
    return {
        "source": source,
        "source_event": source_event,
        "source_file": source_file,
        "event_timestamp": event_timestamp,
        "freshness": freshness,
        "truth_class": truth_class,
        "caveat": caveat,
        "fallback": fallback,
        "nullprovider_safe": True,
    }


def _effect_kinds(effect: dict[str, Any]) -> list[str]:
    return [
        key
        for key, value in effect.items()
        if key != "Faction" and value not in (None, "", [], {})
    ]


def _powerplay_observed_fields(event: dict[str, Any]) -> dict[str, Any]:
    observed: dict[str, Any] = {}
    for key in _POWERPLAY_OBSERVED_FIELD_ALLOWLIST:
        if key in event and key not in _POWERPLAY_MERIT_FIELDS:
            value = event.get(key)
            if value not in (None, "", [], {}):
                observed[key] = deepcopy(value)
    return observed


def _powerplay_withheld_fields(event: dict[str, Any]) -> list[str]:
    return sorted(
        key for key in event if key in _POWERPLAY_MERIT_FIELDS or "merit" in key.lower()
    )


def _bounded_history(values: list[Any], limit: int) -> list[Any]:
    return list(values)[-limit:]


def _named_object(value: dict[str, Any] | None) -> str | None:
    if not isinstance(value, dict):
        return None
    return (
        _string_or_none(value.get("Name"))
        or _string_or_none(value.get("name"))
        or _string_or_none(value.get("Faction"))
        or _string_or_none(value.get("faction"))
    )


# --- Tiny coercion helpers -------------------------------------------------


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _list_of_floats(value: Any) -> list[float] | None:
    if not isinstance(value, list):
        return None
    out: list[float] = []
    for item in value:
        if isinstance(item, bool):
            return None
        if isinstance(item, (int, float)):
            out.append(float(item))
        else:
            return None
    return out


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
