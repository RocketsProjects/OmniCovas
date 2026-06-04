# omnicovas/features/extended_events.py
"""
omnicovas.features.extended_events

Feature 8 (Pillar 1, Tier 1 — Pure Telemetry).

Handlers: Docked, Undocked, FSDJump, CommitCrime, Bounty, ShipDestroyed, Died

Publishes:
    DOCKED      — on Docked journal event
    UNDOCKED    — on Undocked journal event
    FSD_JUMP    — on FSDJump journal event (NOT StartJump)
    WANTED      — on CommitCrime or Bounty events
    DESTROYED   — on ShipDestroyed or Died events

Runs alongside handlers.py — does not replace Phase 1 state updates.

Ref: Phase 2 Development Guide Week 9, Part C
Ref: Master Blueprint v4.2 — Pillar 1, Feature 8

Law 5: only broadcast when required journal fields are present
Law 7: all writes use TelemetrySource.JOURNAL
"""

from __future__ import annotations

import logging
from typing import Any

from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import DESTROYED, DOCKED, FSD_JUMP, UNDOCKED, WANTED
from omnicovas.core.state_manager import StateManager, TelemetrySource

logger = logging.getLogger(__name__)


async def handle_docked(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle Docked journal event."""
    ts = event.get("timestamp")
    station = event.get("StationName")
    station_type = event.get("StationType")
    system = event.get("StarSystem")
    market_id = event.get("MarketID")

    state.update_field("is_docked", True, TelemetrySource.JOURNAL, ts)
    if station is not None:
        state.update_field("current_station", str(station), TelemetrySource.JOURNAL, ts)
    if system is not None:
        state.update_field("current_system", str(system), TelemetrySource.JOURNAL, ts)

    logger.info("Docked -> %s in %s", station, system)

    await broadcaster.publish(
        DOCKED,
        ShipStateEvent.now(
            DOCKED,
            {
                "station": station,
                "station_type": station_type,
                "system": system,
                "market_id": market_id,
            },
            source="journal",
        ),
    )


async def handle_undocked(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle Undocked journal event."""
    ts = event.get("timestamp")
    station = event.get("StationName")

    state.update_field("is_docked", False, TelemetrySource.JOURNAL, ts)
    state.update_field("current_station", None, TelemetrySource.JOURNAL, ts)

    logger.info("Undocked from %s", station)

    await broadcaster.publish(
        UNDOCKED,
        ShipStateEvent.now(UNDOCKED, {"station": station}, source="journal"),
    )


async def handle_fsd_jump(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
    last_system_holder: dict[str, str | None],
) -> None:
    """Handle FSDJump journal event."""
    ts = event.get("timestamp")
    new_system = event.get("StarSystem")

    if new_system is None:
        return

    system_address = event.get("SystemAddress")
    population = event.get("Population")
    prev_system = last_system_holder["value"]
    last_system_holder["value"] = str(new_system)

    state.update_field("current_system", str(new_system), TelemetrySource.JOURNAL, ts)
    state.update_field("is_in_supercruise", False, TelemetrySource.JOURNAL, ts)

    if prev_system is not None and str(new_system) != prev_system:
        state.update_field("is_wanted_in_system", False, TelemetrySource.JOURNAL, ts)
        logger.debug("FSDJump to new system — clearing wanted state")

    logger.info("FSDJump -> %s", new_system)

    await broadcaster.publish(
        FSD_JUMP,
        ShipStateEvent.now(
            FSD_JUMP,
            {
                "system": str(new_system),
                "system_address": system_address,
                "population": population,
            },
            source="journal",
        ),
    )


async def handle_commit_crime(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle CommitCrime journal event."""
    ts = event.get("timestamp")
    crime_type = event.get("CrimeType")

    state.update_field("is_wanted_in_system", True, TelemetrySource.JOURNAL, ts)

    logger.warning("CommitCrime -> %s — wanted in current system", crime_type)

    await broadcaster.publish(
        WANTED,
        ShipStateEvent.now(
            WANTED,
            {"crime_type": crime_type, "system": state.snapshot.current_system},
            source="journal",
        ),
    )


async def handle_bounty(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle Bounty journal event."""
    ts = event.get("timestamp")
    reward = event.get("TotalReward")

    state.update_field("is_wanted_in_system", True, TelemetrySource.JOURNAL, ts)

    logger.warning("Bounty -> reward=%s — wanted in current system", reward)

    await broadcaster.publish(
        WANTED,
        ShipStateEvent.now(
            WANTED,
            {"reward": reward, "system": state.snapshot.current_system},
            source="journal",
        ),
    )


async def handle_ship_destroyed(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle ShipDestroyed journal event."""
    ts = event.get("timestamp")
    snap = state.snapshot

    logger.warning(
        "ShipDestroyed -> %s in %s (hull=%.0f%%)",
        snap.current_ship_type,
        snap.current_system,
        (snap.hull_health or 0.0) * 100,
    )

    await broadcaster.publish(
        DESTROYED,
        ShipStateEvent.now(
            DESTROYED,
            {
                "ship_type": snap.current_ship_type,
                "hull_health": snap.hull_health,
                "system": snap.current_system,
            },
            source="journal",
        ),
    )

    state.update_field("hull_health", None, TelemetrySource.JOURNAL, ts)
    state.update_field("modules", {}, TelemetrySource.JOURNAL, ts)
    state.update_field("shield_up", None, TelemetrySource.JOURNAL, ts)
    state.update_field("current_ship_id", None, TelemetrySource.JOURNAL, ts)


async def handle_died(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle Died journal event (commander death)."""
    await handle_ship_destroyed(event, state, broadcaster)


def register(
    dispatcher_register: Any,
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Register Extended Events handlers with the EventDispatcher."""
    last_system_holder: dict[str, str | None] = {"value": None}

    async def _docked(event: dict[str, Any]) -> None:
        await handle_docked(event, state, broadcaster)

    async def _undocked(event: dict[str, Any]) -> None:
        await handle_undocked(event, state, broadcaster)

    async def _fsd_jump(event: dict[str, Any]) -> None:
        await handle_fsd_jump(event, state, broadcaster, last_system_holder)

    async def _commit_crime(event: dict[str, Any]) -> None:
        await handle_commit_crime(event, state, broadcaster)

    async def _bounty(event: dict[str, Any]) -> None:
        await handle_bounty(event, state, broadcaster)

    async def _ship_destroyed(event: dict[str, Any]) -> None:
        await handle_ship_destroyed(event, state, broadcaster)

    async def _died(event: dict[str, Any]) -> None:
        await handle_died(event, state, broadcaster)

    dispatcher_register("Docked", _docked)
    dispatcher_register("Undocked", _undocked)
    dispatcher_register("FSDJump", _fsd_jump)
    dispatcher_register("CommitCrime", _commit_crime)
    dispatcher_register("Bounty", _bounty)
    dispatcher_register("ShipDestroyed", _ship_destroyed)
    dispatcher_register("Died", _died)

    logger.info(
        "Extended Events handlers registered "
        "(Docked, Undocked, FSDJump, CommitCrime, Bounty, ShipDestroyed, Died)"
    )
