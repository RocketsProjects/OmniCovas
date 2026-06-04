"""
omnicovas.features.ship_state

Live Ship State -- Feature 1 (Pillar 1, Tier 1 -- Pure Telemetry).

Handles three journal events that establish and re-establish ship identity:

    LoadGame     -- fired at session start; first source of ship identity
    Loadout      -- fired after LoadGame, after outfitting, after repair;
                   the richest source of ship state
    ShipyardSwap -- fired when commander switches to a different ship;
                   clears module state until next Loadout re-grounds it

Each handler updates StateManager fields and publishes a ShipStateEvent.

Loadout hash:
    Computed from Slot + Item + BlueprintName (if engineered) per module.
    Module health is excluded so repair events (health changes, no config
    change) do not trigger LOADOUT_CHANGED. Only a genuine configuration
    change broadcasts LOADOUT_CHANGED.

    Full module parsing (ModuleInfo population) is Week 8, Feature 4.
    This handler captures identity, jump range, and fuel capacity only.

Law 5 (Zero Hallucination):
    Fields are only written when the journal event contains them.
    Missing fields stay None -- never fabricated.

Law 7 (Telemetry Rigidity):
    All updates declare TelemetrySource.JOURNAL. StateManager enforces priority.

See: Phase 2 Development Guide Week 7, Part C
See: Master Blueprint v4.1 -- Pillar 1, Feature 1
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import LOADOUT_CHANGED, SHIP_STATE_CHANGED
from omnicovas.core.state_manager import StateManager, TelemetrySource

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def handle_load_game(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle LoadGame -- establishes ship identity at session start.

    LoadGame is the first meaningful event of every session. It fires before
    Loadout, so some fields (hull health, module detail) are not yet available
    here -- they arrive with the Loadout event that always follows.

    Journal fields extracted:
        Ship      -> current_ship_type
        ShipID    -> current_ship_id
        ShipName  -> current_ship_name  (user-assigned, may be absent)
        ShipIdent -> current_ship_ident (call sign, may be absent)
        Commander -> commander_name
        Credits   -> credit_balance
        Loan      -> loan
    """
    ts = event.get("timestamp")

    ship_type = event.get("Ship")
    ship_id = event.get("ShipID")
    ship_name = event.get("ShipName")
    ship_ident = event.get("ShipIdent")
    commander = event.get("Commander")
    credits = event.get("Credits")
    loan = event.get("Loan")

    if ship_type is not None:
        state.update_field(
            "current_ship_type", str(ship_type), TelemetrySource.JOURNAL, ts
        )
    if ship_id is not None:
        state.update_field("current_ship_id", int(ship_id), TelemetrySource.JOURNAL, ts)
    if ship_name is not None:
        state.update_field(
            "current_ship_name", str(ship_name), TelemetrySource.JOURNAL, ts
        )
    if ship_ident is not None:
        state.update_field(
            "current_ship_ident", str(ship_ident), TelemetrySource.JOURNAL, ts
        )
    if commander is not None:
        state.update_field(
            "commander_name", str(commander), TelemetrySource.JOURNAL, ts
        )
    if isinstance(credits, (int, float)) and not isinstance(credits, bool):
        state.update_field("credit_balance", int(credits), TelemetrySource.JOURNAL, ts)
    if isinstance(loan, (int, float)) and not isinstance(loan, bool):
        state.update_field("loan", int(loan), TelemetrySource.JOURNAL, ts)

    logger.info(
        "LoadGame -> ship=%s id=%s cmdr=%s",
        ship_type,
        ship_id,
        commander,
    )

    await broadcaster.publish(
        SHIP_STATE_CHANGED,
        ShipStateEvent.now(
            SHIP_STATE_CHANGED,
            {
                "trigger": "LoadGame",
                "ship_type": ship_type,
                "ship_id": ship_id,
                "ship_name": ship_name,
                "ship_ident": ship_ident,
                "commander": commander,
            },
            source="journal",
        ),
    )


async def handle_loadout(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle Loadout -- re-grounds ship state after any configuration change.

    Loadout fires after LoadGame, after outfitting, and after repair.
    This handler extracts identity, hull health, jump range, and fuel capacity.
    Full module parsing (ModuleInfo) is Week 8, Feature 4.

    Journal fields extracted:
        Ship          -> current_ship_type
        ShipID        -> current_ship_id
        ShipName      -> current_ship_name
        ShipIdent     -> current_ship_ident
        HullHealth    -> hull_health  (0.0-1.0)
        MaxJumpRange  -> jump_range_ly
        FuelCapacity.Main   -> fuel_capacity_main (tons)
        FuelCapacity.Reserve -> fuel_capacity_reserve (tons)
        Modules       -> loadout_hash (SHA-256 of sorted slot/item/blueprint)
        Rebuy         -> rebuy_cost, when supplied by the journal
    """
    ts = event.get("timestamp")

    ship_type = event.get("Ship")
    ship_id = event.get("ShipID")
    ship_name = event.get("ShipName")
    ship_ident = event.get("ShipIdent")
    hull_health = event.get("HullHealth")
    max_jump = event.get("MaxJumpRange")
    fuel_capacity_block: dict[str, Any] | None = event.get("FuelCapacity")
    modules_raw = event.get("Modules", [])
    hull_value = event.get("HullValue")
    modules_value = event.get("ModulesValue")
    rebuy = event.get("Rebuy")

    if ship_type is not None:
        state.update_field(
            "current_ship_type", str(ship_type), TelemetrySource.JOURNAL, ts
        )
    if ship_id is not None:
        state.update_field("current_ship_id", int(ship_id), TelemetrySource.JOURNAL, ts)
    if ship_name is not None:
        state.update_field(
            "current_ship_name", str(ship_name), TelemetrySource.JOURNAL, ts
        )
    if ship_ident is not None:
        state.update_field(
            "current_ship_ident", str(ship_ident), TelemetrySource.JOURNAL, ts
        )
    if hull_health is not None:
        state.update_field(
            "hull_health", float(hull_health), TelemetrySource.JOURNAL, ts
        )
    if max_jump is not None:
        state.update_field(
            "jump_range_ly", float(max_jump), TelemetrySource.JOURNAL, ts
        )

    # FuelCapacity block: {"Main": float, "Reserve": float}
    if isinstance(fuel_capacity_block, dict):
        main_cap = fuel_capacity_block.get("Main")
        reserve_cap = fuel_capacity_block.get("Reserve")
        if isinstance(main_cap, (int, float)):
            state.update_field(
                "fuel_capacity_main", float(main_cap), TelemetrySource.JOURNAL, ts
            )
        if isinstance(reserve_cap, (int, float)):
            state.update_field(
                "fuel_capacity_reserve", float(reserve_cap), TelemetrySource.JOURNAL, ts
            )

    # Rebuy Calculator inputs (Feature 11, Week 10)
    if isinstance(hull_value, (int, float)):
        state.update_field("hull_value", int(hull_value), TelemetrySource.JOURNAL, ts)
    if isinstance(modules_value, (int, float)):
        state.update_field(
            "modules_value", int(modules_value), TelemetrySource.JOURNAL, ts
        )
    if isinstance(rebuy, (int, float)) and not isinstance(rebuy, bool):
        state.update_field("rebuy_cost", int(rebuy), TelemetrySource.JOURNAL, ts)

    # Compute loadout hash -- excludes health so repairs don't trigger broadcast
    new_hash = compute_loadout_hash(modules_raw)
    previous_hash = state.snapshot.loadout_hash
    state.update_field("loadout_hash", new_hash, TelemetrySource.JOURNAL, ts)

    logger.info(
        "Loadout -> ship=%s jump=%.1fly hull=%.0f%% hash=%s",
        ship_type,
        max_jump or 0.0,
        (hull_health or 0.0) * 100,
        new_hash[:8] if new_hash else "none",
    )

    # Always broadcast SHIP_STATE_CHANGED -- identity fields may have updated
    await broadcaster.publish(
        SHIP_STATE_CHANGED,
        ShipStateEvent.now(
            SHIP_STATE_CHANGED,
            {
                "trigger": "Loadout",
                "ship_type": ship_type,
                "ship_id": ship_id,
                "hull_health": hull_health,
                "jump_range_ly": max_jump,
            },
            source="journal",
        ),
    )

    # Only broadcast LOADOUT_CHANGED when configuration actually changed
    if new_hash != previous_hash:
        await broadcaster.publish(
            LOADOUT_CHANGED,
            ShipStateEvent.now(
                LOADOUT_CHANGED,
                {
                    "ship_type": ship_type,
                    "ship_id": ship_id,
                    "new_hash": new_hash,
                    "previous_hash": previous_hash,
                },
                source="journal",
            ),
        )
        logger.info(
            "LOADOUT_CHANGED broadcast (hash: %s)",
            new_hash[:8] if new_hash else "none",
        )
    else:
        logger.debug(
            "Loadout re-fired but hash unchanged (%s) -- no LOADOUT_CHANGED",
            new_hash[:8] if new_hash else "none",
        )


async def handle_shipyard_swap(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle ShipyardSwap -- commander switched to a different stored ship.

    After a swap, ship-specific state is stale and must be cleared.
    The Loadout event that always follows will re-ground everything.

    Journal fields extracted:
        ShipType -> current_ship_type
        ShipID   -> current_ship_id
    """
    ts = event.get("timestamp")

    ship_type = event.get("ShipType")
    ship_id = event.get("ShipID")

    if ship_type is not None:
        state.update_field(
            "current_ship_type", str(ship_type), TelemetrySource.JOURNAL, ts
        )
    if ship_id is not None:
        state.update_field("current_ship_id", int(ship_id), TelemetrySource.JOURNAL, ts)

    # Clear ship-specific state -- next Loadout will re-populate
    state.update_field("current_ship_name", None, TelemetrySource.JOURNAL, ts)
    state.update_field("current_ship_ident", None, TelemetrySource.JOURNAL, ts)
    state.update_field("hull_health", None, TelemetrySource.JOURNAL, ts)
    state.update_field("jump_range_ly", None, TelemetrySource.JOURNAL, ts)
    state.update_field("loadout_hash", None, TelemetrySource.JOURNAL, ts)
    state.update_field("modules", {}, TelemetrySource.JOURNAL, ts)

    logger.info(
        "ShipyardSwap -> ship=%s id=%s (state cleared, awaiting Loadout)",
        ship_type,
        ship_id,
    )

    await broadcaster.publish(
        SHIP_STATE_CHANGED,
        ShipStateEvent.now(
            SHIP_STATE_CHANGED,
            {
                "trigger": "ShipyardSwap",
                "ship_type": ship_type,
                "ship_id": ship_id,
            },
            source="journal",
        ),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(
    dispatcher_register: Any,
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Register all Live Ship State handlers with the EventDispatcher.

    Call from main() after both state and broadcaster are constructed, before
    the journal watcher starts. Wraps each handler in a closure that matches
    the single-argument EventHandler signature the dispatcher expects.

    Args:
        dispatcher_register: EventDispatcher.register method
        state: The shared StateManager instance
        broadcaster: The shared ShipStateBroadcaster instance
    """

    async def _load_game(event: dict[str, Any]) -> None:
        await handle_load_game(event, state, broadcaster)

    async def _loadout(event: dict[str, Any]) -> None:
        await handle_loadout(event, state, broadcaster)

    async def _shipyard_swap(event: dict[str, Any]) -> None:
        await handle_shipyard_swap(event, state, broadcaster)

    dispatcher_register("LoadGame", _load_game)
    dispatcher_register("Loadout", _loadout)
    dispatcher_register("ShipyardSwap", _shipyard_swap)

    logger.info("Live Ship State handlers registered (LoadGame, Loadout, ShipyardSwap)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def compute_loadout_hash(modules_raw: list[Any]) -> str:
    """Compute a stable SHA-256 hash of the ship's loadout configuration.

    Only slot, item, and engineering blueprint name are included. Module health
    is deliberately excluded so repair events do not trigger LOADOUT_CHANGED.

    Args:
        modules_raw: The Modules list from a Loadout journal event.

    Returns:
        64-character hex SHA-256 string, or empty string if modules_raw is
        empty or contains no valid entries.
    """
    if not modules_raw:
        return ""

    entries = []
    for mod in modules_raw:
        if not isinstance(mod, dict):
            continue
        slot: str = str(mod.get("Slot", ""))
        item: str = str(mod.get("Item", ""))
        engineering = mod.get("Engineering", {})
        blueprint: str = (
            str(engineering.get("BlueprintName", ""))
            if isinstance(engineering, dict)
            else ""
        )
        entries.append((slot, item, blueprint))

    entries.sort(key=lambda x: x[0])  # sort by slot for stability
    canonical = json.dumps(entries, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
