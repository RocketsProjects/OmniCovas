# omnicovas/features/loadout.py
"""
omnicovas.features.loadout

Loadout Awareness — Feature 4 (Pillar 1, Tier 1 — Pure Telemetry).

Parses the Modules list from Loadout journal events and populates
SessionState.modules with ModuleInfo objects. Each module entry is
converted using the field mapping below; missing optional fields
default to safe values per Law 5 (Zero Hallucination).

Field mapping from journal Module dict to ModuleInfo:
    Slot              -> slot (str)
    Item              -> item (str)
    Item_Localised    -> item_localised (str | None)
    Health            -> health (float, 0.0-1.0)
    Power             -> power (float | None)
    Priority          -> priority (int | None)
    On                -> on (bool)
    Engineering       -> engineering (dict | None)

Law 5 (Zero Hallucination):
    Missing optional fields default per mapping above; no fields invented.

Law 7 (Telemetry Rigidity):
    All writes use TelemetrySource.JOURNAL.

See: Phase 2 Development Guide Week 8, Part A
See: Master Blueprint v4.2 — Pillar 1, Feature 4
"""

from __future__ import annotations

import logging
from typing import Any

from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import SHIP_STATE_CHANGED
from omnicovas.core.state_manager import ModuleInfo, StateManager, TelemetrySource

logger = logging.getLogger(__name__)


async def handle_loadout(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Parse Loadout Modules list and populate state.modules.

    Args:
        event: Loadout journal event containing a "Modules" list
        state: Shared StateManager instance
        broadcaster: Shared ShipStateBroadcaster instance
    """
    ts = event.get("timestamp")
    modules_dict = modules_from_loadout_event(event)
    state.update_field("modules", modules_dict, TelemetrySource.JOURNAL, ts)
    logger.info("Loadout_modules -> %d modules parsed", len(modules_dict))

    await broadcaster.publish(
        SHIP_STATE_CHANGED,
        ShipStateEvent.now(
            SHIP_STATE_CHANGED,
            {"trigger": "Loadout_modules", "module_count": len(modules_dict)},
            source="journal",
        ),
    )


def modules_from_loadout_event(event: dict[str, Any]) -> dict[str, ModuleInfo]:
    """Build a slot -> ModuleInfo map from a Loadout journal event.

    Kept sync so startup hydration can re-ground module configuration without
    needing to run the async broadcaster path.
    """
    modules_raw = event.get("Modules", [])
    modules_dict: dict[str, ModuleInfo] = {}
    for entry in modules_raw:
        if not isinstance(entry, dict):
            continue
        if "Slot" not in entry:
            continue

        slot = str(entry["Slot"])
        item = str(entry.get("Item", ""))
        item_localised = str(entry.get("Item_Localised", "")) or None
        health = float(entry.get("Health", 1.0))
        power_raw = entry.get("Power")
        power = float(power_raw) if power_raw is not None else None
        priority_raw = entry.get("Priority")
        priority = int(priority_raw) if priority_raw is not None else None
        on_val = bool(entry.get("On", True))
        eng_raw = entry.get("Engineering")
        engineering = eng_raw if isinstance(eng_raw, dict) else None
        value_raw = entry.get("Value")
        module_value = int(value_raw) if isinstance(value_raw, (int, float)) else None
        ammo_clip_raw = entry.get("AmmoInClip")
        ammo_clip = (
            ammo_clip_raw
            if isinstance(ammo_clip_raw, int) and not isinstance(ammo_clip_raw, bool)
            else None
        )
        ammo_hopper_raw = entry.get("AmmoInHopper")
        ammo_hopper = (
            ammo_hopper_raw
            if isinstance(ammo_hopper_raw, int)
            and not isinstance(ammo_hopper_raw, bool)
            else None
        )

        modules_dict[slot] = ModuleInfo(
            slot=slot,
            item=item,
            item_localised=item_localised,
            health=health,
            power=power,
            priority=priority,
            on=on_val,
            engineering=engineering,
            value=module_value,
            ammo_in_clip=ammo_clip,
            ammo_in_hopper=ammo_hopper,
        )
    return modules_dict


def register(
    dispatcher_register: Any,
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Register Loadout Awareness handler with the EventDispatcher.

    Args:
        dispatcher_register: EventDispatcher.register method
        state: Shared StateManager instance
        broadcaster: Shared ShipStateBroadcaster instance
    """

    async def _loadout(event: dict[str, Any]) -> None:
        await handle_loadout(event, state, broadcaster)

    dispatcher_register("Loadout", _loadout)
    logger.info("Loadout Awareness handlers registered (Loadout)")
