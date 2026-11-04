# omnicovas/features/cargo.py
"""
omnicovas.features.cargo

Cargo Monitoring -- Feature 6 (Pillar 1, Tier 1 -- Pure Telemetry).

Tracks cargo inventory from journal events and publishes CARGO_CHANGED
whenever the inventory changes.

Journal events handled:
    Cargo  -- ship cargo inventory update

Vessel filter:
    Only Ship context cargo is tracked. SRV and Suit cargo are dropped.
    Events missing Vessel field are treated as Ship context.

Publishes:
    CARGO_CHANGED  -- whenever a verified cargo fact changes

Law 5 (Zero Hallucination):
    SRV/Suit cargo excluded; entries missing Name or Count skipped.

Law 7 (Telemetry Rigidity):
    All writes use TelemetrySource.JOURNAL.

See: Phase 2 Development Guide Week 8, Part A
See: Master Blueprint v4.2 -- Pillar 1, Feature 6
"""

from __future__ import annotations

import logging
from typing import Any

from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import CARGO_CHANGED
from omnicovas.core.state_manager import StateManager, TelemetrySource
from omnicovas.features import local_context_facts

logger = logging.getLogger(__name__)


def _cargo_snapshot_signature(snapshot: Any) -> tuple[Any, ...] | None:
    """Compare cargo facts while ignoring observation timestamps."""
    if snapshot is None:
        return None
    items = tuple(
        (
            item.name,
            item.name_localised,
            item.count,
            item.stolen,
            item.mission_id,
        )
        for item in snapshot.inventory
    )
    return (
        snapshot.vessel,
        snapshot.capacity,
        snapshot.total_count,
        snapshot.inventory_complete,
        items,
    )


async def handle_cargo(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle Cargo journal event -- ship cargo inventory update.

    Journal fields:
        Vessel    -- "Ship", "SRV", or "Suit" (filter to Ship only)
        Inventory -- list of {Name, Count} dicts
        Count     -- total units across all commodities (optional)

    Vessel filter:
        If Vessel is "SRV" or "Suit", skip the event entirely.
        If Vessel is absent, treat as Ship context.

    Inventory processing:
        Build a dict mapping commodity internal name (lowercase) to count.
        Skip entries missing Name or Count.
    """
    ts = event.get("timestamp")
    vessel = event.get("Vessel")

    # Filter to Ship context only
    if vessel is not None and vessel != "Ship":
        logger.debug("Cargo event for Vessel=%r — skipped (ship only)", vessel)
        return

    inventory_raw = event.get("Inventory")
    inventory_supplied = isinstance(inventory_raw, list)
    inventory_entries = inventory_raw if isinstance(inventory_raw, list) else []
    inventory_dict: dict[str, int] = {}
    for entry in inventory_entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("Name")
        count = entry.get("Count")
        if name is None or count is None:
            continue
        inventory_dict[str(name)] = int(count)

    previous_inventory = dict(state.snapshot.cargo_inventory)
    previous_count = state.snapshot.cargo_count
    previous_snapshot_signature = _cargo_snapshot_signature(
        state.snapshot.cargo_hold_snapshot
    )

    top_count = event.get("Count")
    normalized_count: int | None = None
    if top_count is not None:
        normalized_count = int(top_count)
        state.update_field(
            "cargo_count",
            normalized_count,
            TelemetrySource.JOURNAL,
            ts,
        )

    state.update_field("cargo_inventory", inventory_dict, TelemetrySource.JOURNAL, ts)

    # Phase 6 extension: build the field-rich CargoHoldSnapshot alongside
    # the scalar inventory so consumers can see per-item Stolen / MissionID
    # flags and vessel context that the dict[str, int] cannot carry.
    cargo_snapshot = local_context_facts.build_cargo_hold_snapshot(
        event,
        capacity=state.snapshot.cargo_capacity,
        source_event="Cargo",
    )
    state.update_field(
        "cargo_hold_snapshot", cargo_snapshot, TelemetrySource.JOURNAL, ts
    )

    total_units = cargo_snapshot.total_count
    cargo_changed = (
        inventory_dict != previous_inventory
        or (normalized_count is not None and normalized_count != previous_count)
        or _cargo_snapshot_signature(cargo_snapshot) != previous_snapshot_signature
    )
    if not cargo_changed:
        logger.debug(
            "Cargo unchanged: %d commodity types, %d total units",
            len(inventory_dict),
            total_units,
        )
        return

    if inventory_supplied:
        logger.info(
            "Cargo inventory -> %d commodity types, %d total units",
            len(inventory_dict),
            total_units or 0,
        )
    else:
        logger.debug(
            "Cargo count -> %s total units (inventory detail not provided)",
            total_units if total_units is not None else "unknown",
        )

    await broadcaster.publish(
        CARGO_CHANGED,
        ShipStateEvent.now(
            CARGO_CHANGED,
            {
                "cargo_count": total_units,
                "commodity_types": (
                    len(inventory_dict) if cargo_snapshot.inventory_complete else None
                ),
                "total_units": total_units,
                "inventory_complete": cargo_snapshot.inventory_complete,
                "timestamp": ts,
            },
            source="journal",
        ),
    )


def register(
    dispatcher_register: Any,
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Register Cargo Monitoring handler with the EventDispatcher.

    Args:
        dispatcher_register: EventDispatcher.register method
        state: The shared StateManager instance
        broadcaster: The shared ShipStateBroadcaster instance
    """

    async def _cargo(event: dict[str, Any]) -> None:
        await handle_cargo(event, state, broadcaster)

    dispatcher_register("Cargo", _cargo)

    logger.info("Cargo Monitoring handlers registered (Cargo)")
