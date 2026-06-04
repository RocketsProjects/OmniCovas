"""Phase 4 (PB04-06) combat-session feature module.

Schema-locked against:
    authority_files/documents/03_backend_source_compliance/OmniCOVAS_Elite_Local_Data_Surface_Reference_v1_0_AI_Reference.md

Owns mutation helpers for the Operations -> Combat session-scoped facts:
    * mission session and active mission list (F1)
    * local conflict context from FSDJump/Location Conflicts[] (F1)
    * RedeemVoucher bounty/combat-bond session totals (F3)
    * Rank/Progress latest-observed combat rank facts (F3)
    * Promotion combat rank session change (F3)

Active CZ detection and CZ kind (low/medium/high) are intentionally NOT
implemented -- no verified local source exists.
MissionCompleted.Reward is NOT counted as a combat reward total.
Combat reward totals derive only from RedeemVoucher Type=bounty/CombatBond.

Follows the existing combat_state.py pattern: deepcopy -> mutate ->
publish via the shared broadcaster. No parallel state manager,
no parallel Activity Log, no new file reader.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any, Literal, cast

from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import COMBAT_SESSION_STATE_CHANGED
from omnicovas.core.state_manager import (
    CombatField,
    CombatFreshnessState,
    CombatMissionEntry,
    CombatRewardsContext,
    CombatSourceLabel,
    CombatState,
    CombatZoneMissionContext,
    StateManager,
    TelemetrySource,
)

JOURNAL_SOURCE: CombatSourceLabel = "journal"
FRESH: CombatFreshnessState = "fresh"

_BOUNTY_TYPE = "bounty"
_COMBAT_BOND_TYPE = "CombatBond"

# Provisional draft schema for PB04-07 Debrief consumption. PB04-06 does NOT
# expose a public /combat-session/debrief-summary endpoint; PB04-07 owns
# Debrief endpoint and public consumption. PB04-07 must review this draft
# before any public Debrief consumer treats it as a contract.
DEBRIEF_PAYLOAD_DRAFT_SCHEMA: dict[str, str] = {
    "bounty_session_credits": "int | None",
    "combat_bond_session_credits": "int | None",
    "combat_rank": "int | None",
    "combat_rank_progress": "int | None",
    "missions_completed_count": "int",
    "missions_failed_count": "int",
    "missions_abandoned_count": "int",
    "session_summary_at": "str | None",
    "source": "str (always 'journal')",
    "caveat": "str ('Session totals only. No external lookup.')",
}

CombatTruthClass = Literal[
    "live_local_telemetry",
    "local_screen_snapshot",
    "local_event_history",
    "unknown",
]


def truth_class_for_source_label(source_label: str | None) -> CombatTruthClass:
    """Map combat-session source labels to Local Data Surface truth classes."""
    normalized = source_label.strip().lower() if isinstance(source_label, str) else ""
    if normalized == "journal":
        return "local_event_history"
    if normalized in ("status", "status_json"):
        return "live_local_telemetry"
    if normalized == "companion":
        return "local_screen_snapshot"
    return "unknown"


def snapshot_payload(state: StateManager) -> dict[str, Any]:
    """Return the explicit Phase 4 combat-session snapshot payload."""
    combat = state.snapshot.combat
    return {
        "cz_missions": _context_payload(combat.cz_missions),
        "rewards": _context_payload(combat.rewards),
        "active_missions": _missions_payload(combat.active_missions),
    }


def empty_snapshot_payload() -> dict[str, Any]:
    """Return the explicit empty payload when state is unavailable."""
    empty = CombatState()
    return {
        "cz_missions": _context_payload(empty.cz_missions),
        "rewards": _context_payload(empty.rewards),
        "active_missions": _missions_payload(empty.active_missions),
    }


def loadout_readiness_payload(state: StateManager) -> dict[str, Any]:
    """Return F4 loadout/munitions readiness from existing baseline state.

    Consume-only: reads state.snapshot.modules / cargo_inventory / hull_value /
    modules_value / current_ship_type. No invented thresholds. The munitions
    row is rendered as 'No Verified Source' -- no journal mechanism exposes
    ammunition counts.

    Readiness blockers surfaced are factual states only:
        * module.health == 0.0 -> "Destroyed" (factual, not a threshold rule)
    No hidden thresholds (e.g., "module health < X") are applied here.
    """
    snap = state.snapshot
    modules_payload: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for slot, module in snap.modules.items():
        modules_payload.append(
            _with_truth_class(
                {
                    "slot": slot,
                    "item": module.item,
                    "item_localised": module.item_localised,
                    "health": module.health,
                    "on": module.on,
                    "source": JOURNAL_SOURCE,
                    "freshness": FRESH,
                }
            )
        )
        if module.health == 0.0:
            blockers.append(
                _with_truth_class(
                    {
                        "slot": slot,
                        "kind": "destroyed",
                        "label": "Destroyed",
                        "source": JOURNAL_SOURCE,
                        "freshness": FRESH,
                    }
                )
            )

    return {
        "modules": modules_payload,
        "modules_loaded": bool(snap.modules),
        "ship_type": snap.current_ship_type,
        "hull_value": snap.hull_value,
        "modules_value": snap.modules_value,
        "cargo_count": snap.cargo_count,
        "cargo_capacity": snap.cargo_capacity,
        "readiness_blockers": blockers,
        "munitions": _with_truth_class(
            {
                "value": None,
                "source": "no_verified_source",
                "freshness": "unknown",
                "caveat": "Ammunition counts have no verified local source.",
            }
        ),
    }


def empty_loadout_readiness_payload() -> dict[str, Any]:
    """Return F4 readiness empty payload when state is unavailable."""
    return {
        "modules": [],
        "modules_loaded": False,
        "ship_type": None,
        "hull_value": None,
        "modules_value": None,
        "cargo_count": None,
        "cargo_capacity": None,
        "readiness_blockers": [],
        "munitions": _with_truth_class(
            {
                "value": None,
                "source": "no_verified_source",
                "freshness": "unknown",
                "caveat": "Ammunition counts have no verified local source.",
            }
        ),
    }


# ---------------------------------------------------------------------------
# F1 -- Mission session helpers
# ---------------------------------------------------------------------------


def record_missions_snapshot(event: dict[str, Any], state: StateManager) -> bool:
    """Record startup Missions snapshot Active[] into active_missions.

    The startup Missions event is a snapshot, not proof a session 'started'
    -- callers log MISSION_SNAPSHOT_LOADED, not MISSION_SESSION_STARTED.
    Returns True if state changed.
    """
    timestamp = _event_timestamp(event)
    active_raw = event.get("Active")
    if not isinstance(active_raw, list):
        return False

    new_entries: list[CombatMissionEntry] = []
    for entry in active_raw:
        if not isinstance(entry, dict):
            continue
        mission_id = _coerce_int(entry.get("MissionID"))
        name = _coerce_str(entry.get("Name"))
        if mission_id is None and name is None:
            continue
        new_entries.append(
            CombatMissionEntry(
                mission_id=mission_id,
                name=name,
                faction=None,
                destination_system=None,
                destination_station=None,
                status="active",
                source_label=JOURNAL_SOURCE,
                timestamp=timestamp,
                freshness=FRESH,
                caveat="Loaded from startup Missions snapshot.",
            )
        )

    return _commit_missions_snapshot(state, new_entries, timestamp)


def record_mission_accepted(event: dict[str, Any], state: StateManager) -> bool:
    """Record MissionAccepted -- append a CombatMissionEntry."""
    mission_id = _coerce_int(event.get("MissionID"))
    name = _coerce_str(event.get("Name"))
    if mission_id is None and name is None:
        return False
    timestamp = _event_timestamp(event)
    entry = CombatMissionEntry(
        mission_id=mission_id,
        name=name,
        faction=_coerce_str(event.get("Faction")),
        destination_system=_coerce_str(event.get("DestinationSystem")),
        destination_station=_coerce_str(event.get("DestinationStation")),
        status="active",
        source_label=JOURNAL_SOURCE,
        timestamp=timestamp,
        freshness=FRESH,
        caveat=None,
    )
    return _commit_mission_append(state, entry, timestamp)


def record_mission_completed(event: dict[str, Any], state: StateManager) -> bool:
    """Record MissionCompleted -- mark matching entry completed and remove."""
    return _commit_mission_status_change(event, state, "completed")


def record_mission_failed(event: dict[str, Any], state: StateManager) -> bool:
    """Record MissionFailed -- mark matching entry failed and remove."""
    return _commit_mission_status_change(event, state, "failed")


def record_mission_abandoned(event: dict[str, Any], state: StateManager) -> bool:
    """Record MissionAbandoned -- mark matching entry abandoned and remove."""
    return _commit_mission_status_change(event, state, "abandoned")


def record_mission_redirected(event: dict[str, Any], state: StateManager) -> bool:
    """Record MissionRedirected -- update destination on matching entry."""
    mission_id = _coerce_int(event.get("MissionID"))
    if mission_id is None:
        return False
    new_system = _coerce_str(event.get("NewDestinationSystem"))
    new_station = _coerce_str(event.get("NewDestinationStation"))
    if new_system is None and new_station is None:
        return False
    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    combat = deepcopy(before)
    changed = False
    for entry in combat.active_missions:
        if entry.mission_id == mission_id:
            if new_system is not None:
                entry.destination_system = new_system
            if new_station is not None:
                entry.destination_station = new_station
            entry.timestamp = timestamp
            entry.freshness = FRESH
            changed = True
            break
    if not changed:
        return False
    return _commit_combat_replacement(state, combat, timestamp)


def record_local_conflict_context(event: dict[str, Any], state: StateManager) -> bool:
    """Record local conflict context from FSDJump/Location Conflicts[].

    Reads ONLY the Conflicts[] field. Does not touch system, station,
    docked, BGS, or faction state -- those are owned by existing handlers
    or other phases. Stores a short formatted string ('warType:status') or
    None. Never claims 'Active CZ detected'.
    """
    conflicts_raw = event.get("Conflicts")
    timestamp = _event_timestamp(event)
    formatted: str | None = None
    if isinstance(conflicts_raw, list):
        for conflict in conflicts_raw:
            if not isinstance(conflict, dict):
                continue
            war_type = _coerce_str(conflict.get("WarType"))
            status = _coerce_str(conflict.get("Status"))
            if war_type and status:
                formatted = f"{war_type}:{status}"
                break

    before = _combat_copy(state)
    if before.cz_missions.local_conflict_context.value == formatted:
        return False
    combat = deepcopy(before)
    combat.cz_missions.local_conflict_context = _field(
        formatted,
        JOURNAL_SOURCE,
        timestamp,
    )
    return _commit_combat_replacement(state, combat, timestamp)


# ---------------------------------------------------------------------------
# F3 -- RedeemVoucher / Rank / Progress / Promotion helpers
# ---------------------------------------------------------------------------


def record_redeem_voucher(event: dict[str, Any], state: StateManager) -> bool:
    """Record RedeemVoucher Type=bounty or Type=CombatBond into session totals.

    All other Types (trade, settlement, scannable, codex) are silently
    ignored. MissionCompleted.Reward is NEVER counted here.

    Session boundary policy: bounty and combat-bond totals persist across
    FSDJump and Docked. They reset only with StateManager.reset(), process
    restart, or a future explicit Commander/debrief reset outside PB04-06.1.
    """
    voucher_type = _coerce_str(event.get("Type"))
    if voucher_type not in (_BOUNTY_TYPE, _COMBAT_BOND_TYPE):
        return False
    amount = _coerce_int(event.get("Amount"))
    if amount is None:
        return False
    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    combat = deepcopy(before)
    if voucher_type == _BOUNTY_TYPE:
        current = _coerce_int(combat.rewards.bounty_session_credits.value) or 0
        combat.rewards.bounty_session_credits = _field(
            current + amount, JOURNAL_SOURCE, timestamp
        )
    else:
        current = _coerce_int(combat.rewards.combat_bond_session_credits.value) or 0
        combat.rewards.combat_bond_session_credits = _field(
            current + amount, JOURNAL_SOURCE, timestamp
        )
    combat.rewards.session_summary_at = _field(timestamp, JOURNAL_SOURCE, timestamp)
    return _commit_combat_replacement(state, combat, timestamp)


def record_rank(event: dict[str, Any], state: StateManager) -> bool:
    """Record startup Rank.Combat as latest observed combat rank."""
    combat_rank = _coerce_int(event.get("Combat"))
    if combat_rank is None:
        return False
    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    if before.rewards.combat_rank.value == combat_rank:
        return False
    combat = deepcopy(before)
    combat.rewards.combat_rank = _field(combat_rank, JOURNAL_SOURCE, timestamp)
    return _commit_combat_replacement(state, combat, timestamp)


def record_progress(event: dict[str, Any], state: StateManager) -> bool:
    """Record startup Progress.Combat as latest observed rank progress."""
    combat_progress = _coerce_int(event.get("Combat"))
    if combat_progress is None:
        return False
    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    if before.rewards.combat_rank_progress.value == combat_progress:
        return False
    combat = deepcopy(before)
    combat.rewards.combat_rank_progress = _field(
        combat_progress, JOURNAL_SOURCE, timestamp
    )
    return _commit_combat_replacement(state, combat, timestamp)


def record_promotion(event: dict[str, Any], state: StateManager) -> bool:
    """Record Promotion.Combat -- session combat rank change.

    Non-combat promotions (Trade/Explore/etc.) have no Combat field and are
    silently skipped. Progress is cleared because the journal does not
    guarantee an immediate Progress event after promotion.
    """
    if "Combat" not in event:
        return False
    combat_rank = _coerce_int(event.get("Combat"))
    if combat_rank is None:
        return False
    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    combat = deepcopy(before)
    combat.rewards.combat_rank = _field(combat_rank, JOURNAL_SOURCE, timestamp)
    combat.rewards.combat_rank_progress = CombatField()
    return _commit_combat_replacement(state, combat, timestamp)


# ---------------------------------------------------------------------------
# Broadcast helper
# ---------------------------------------------------------------------------


async def publish_session_state_changed(
    state: StateManager,
    broadcaster: ShipStateBroadcaster | None,
    reason: str,
) -> bool:
    """Publish COMBAT_SESSION_STATE_CHANGED through the shared broadcaster."""
    if broadcaster is None:
        return False
    payload = snapshot_payload(state)
    payload["reason"] = reason
    await broadcaster.publish(
        COMBAT_SESSION_STATE_CHANGED,
        ShipStateEvent.now(
            COMBAT_SESSION_STATE_CHANGED,
            payload,
            source="journal",
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _commit_missions_snapshot(
    state: StateManager,
    new_entries: list[CombatMissionEntry],
    timestamp: str | None,
) -> bool:
    before = _combat_copy(state)
    combat = deepcopy(before)
    combat.active_missions = new_entries
    combat.cz_missions.mission_session_active = _field(
        bool(new_entries), JOURNAL_SOURCE, timestamp
    )
    if new_entries and combat.cz_missions.session_started_at.value is None:
        combat.cz_missions.session_started_at = _field(
            timestamp, JOURNAL_SOURCE, timestamp
        )
    return _commit_combat_replacement(state, combat, timestamp)


def _commit_mission_append(
    state: StateManager,
    entry: CombatMissionEntry,
    timestamp: str | None,
) -> bool:
    before = _combat_copy(state)
    combat = deepcopy(before)
    combat.active_missions.append(entry)
    combat.cz_missions.mission_session_active = _field(True, JOURNAL_SOURCE, timestamp)
    if combat.cz_missions.session_started_at.value is None:
        combat.cz_missions.session_started_at = _field(
            timestamp, JOURNAL_SOURCE, timestamp
        )
    return _commit_combat_replacement(state, combat, timestamp)


def _commit_mission_status_change(
    event: dict[str, Any],
    state: StateManager,
    new_status: str,
) -> bool:
    mission_id = _coerce_int(event.get("MissionID"))
    if mission_id is None:
        return False
    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    combat = deepcopy(before)
    found = False
    remaining: list[CombatMissionEntry] = []
    for entry in combat.active_missions:
        if entry.mission_id == mission_id and not found:
            found = True
            continue
        remaining.append(entry)
    if not found:
        return False
    combat.active_missions = remaining
    combat.cz_missions.mission_session_active = _field(
        bool(remaining), JOURNAL_SOURCE, timestamp
    )
    return _commit_combat_replacement(state, combat, timestamp)


def _commit_combat_replacement(
    state: StateManager,
    combat: CombatState,
    timestamp: str | None,
) -> bool:
    return state.update_field("combat", combat, TelemetrySource.INFERRED, timestamp)


def _combat_copy(state: StateManager) -> CombatState:
    return deepcopy(state.snapshot.combat)


def _event_timestamp(event: dict[str, Any]) -> str | None:
    timestamp = event.get("timestamp")
    if isinstance(timestamp, str):
        return timestamp
    return None


def _field(
    value: str | int | bool | None,
    source: CombatSourceLabel,
    timestamp: str | None,
    freshness: CombatFreshnessState = FRESH,
) -> CombatField:
    return CombatField(
        value=value,
        source=source,
        timestamp=timestamp,
        freshness=freshness,
    )


def _context_payload(
    context: CombatZoneMissionContext | CombatRewardsContext,
) -> dict[str, Any]:
    payload: Any = asdict(context)
    for field_payload in payload.values():
        if isinstance(field_payload, dict):
            _with_truth_class(field_payload)
    return cast(dict[str, Any], payload)


def _missions_payload(
    missions: list[CombatMissionEntry],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for mission in missions:
        payload: Any = asdict(mission)
        payloads.append(
            _with_truth_class(cast(dict[str, Any], payload), "source_label")
        )
    return payloads


def _with_truth_class(
    payload: dict[str, Any],
    source_key: str = "source",
) -> dict[str, Any]:
    source_label = payload.get(source_key)
    if not isinstance(source_label, str):
        source_label = payload.get("source")
    payload["truth_class"] = truth_class_for_source_label(
        source_label if isinstance(source_label, str) else None
    )
    return payload


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _coerce_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
