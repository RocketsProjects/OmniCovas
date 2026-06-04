# omnicovas/features/hull_triggers.py
"""
omnicovas.features.hull_triggers

Feature 3 (Pillar 1, Tier 1 — Pure Telemetry).

Handlers: HullDamage, ShieldsDown, ShieldsUp.

Publishes:
    HULL_DAMAGE      — every HullDamage event
    HULL_CRITICAL_25 — once per downward crossing below 25% (0.25)
    HULL_CRITICAL_10 — once per downward crossing below 10% (0.10)
    SHIELDS_DOWN     — every ShieldsDown event
    SHIELDS_UP       — every ShieldsUp event

Ref: Phase 2 Development Guide Week 9, Part A
Ref: Master Blueprint v4.2 — Pillar 1, Feature 3

Law 5 (Zero Hallucination):
    No threshold events on first reading; repair does not re-broadcast.

Law 7 (Telemetry Rigidity):
    All writes use TelemetrySource.JOURNAL.
"""

from __future__ import annotations

import logging
from typing import Any

from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import (
    HULL_CRITICAL_10,
    HULL_CRITICAL_25,
    HULL_DAMAGE,
    SHIELDS_DOWN,
    SHIELDS_UP,
)
from omnicovas.core.state_manager import StateManager, TelemetrySource

logger = logging.getLogger(__name__)

_HULL_25_FRACTION: float = 0.25  # KB: combat_mechanics::hull_warning_threshold
_HULL_10_FRACTION: float = 0.10  # KB: combat_mechanics::hull_critical_threshold


async def handle_hull_damage(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
    prev_holder: dict[str, float | None],
) -> None:
    """Handle HullDamage journal event.

    Args:
        event: HullDamage journal event with timestamp and Health fields
        state: Shared StateManager instance
        broadcaster: Shared ShipStateBroadcaster instance
        prev_holder: Mutable dict holding previous hull health value
    """
    ts = event.get("timestamp")
    health_raw = event.get("Health")

    if health_raw is None:
        return

    new_health = float(health_raw)
    prev_health = prev_holder["value"]
    prev_holder["value"] = new_health

    state.update_field("hull_health", new_health, TelemetrySource.JOURNAL, ts)

    health_pct = round(new_health * 100, 1)
    logger.info(
        "HullDamage -> %.1f%% (prev=%.1f%%)",
        health_pct,
        (prev_health or 0.0) * 100,
    )

    await broadcaster.publish(
        HULL_DAMAGE,
        ShipStateEvent.now(
            HULL_DAMAGE,
            {"health": new_health, "health_pct": health_pct},
            source="journal",
        ),
    )

    if prev_health is not None:
        if prev_health >= _HULL_25_FRACTION and new_health < _HULL_25_FRACTION:
            await broadcaster.publish(
                HULL_CRITICAL_25,
                ShipStateEvent.now(
                    HULL_CRITICAL_25,
                    {
                        "health": new_health,
                        "health_pct": health_pct,
                        "threshold": _HULL_25_FRACTION,
                    },
                    source="journal",
                ),
            )
            logger.warning("HULL_CRITICAL_25: hull at %.1f%%", health_pct)

        if prev_health >= _HULL_10_FRACTION and new_health < _HULL_10_FRACTION:
            await broadcaster.publish(
                HULL_CRITICAL_10,
                ShipStateEvent.now(
                    HULL_CRITICAL_10,
                    {
                        "health": new_health,
                        "health_pct": health_pct,
                        "threshold": _HULL_10_FRACTION,
                    },
                    source="journal",
                ),
            )
            logger.warning("HULL_CRITICAL_10: hull at %.1f%%", health_pct)


async def handle_shields_down(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle ShieldsDown journal event.

    Args:
        event: ShieldsDown journal event with timestamp
        state: Shared StateManager instance
        broadcaster: Shared ShipStateBroadcaster instance
    """
    ts = event.get("timestamp")
    state.update_field("shield_up", False, TelemetrySource.JOURNAL, ts)
    logger.warning("ShieldsDown -> shields collapsed")

    await broadcaster.publish(
        SHIELDS_DOWN,
        ShipStateEvent.now(SHIELDS_DOWN, {"timestamp": str(ts)}, source="journal"),
    )


async def handle_shields_up(
    event: dict[str, Any],
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Handle ShieldsUp journal event.

    Args:
        event: ShieldsUp journal event with timestamp
        state: Shared StateManager instance
        broadcaster: Shared ShipStateBroadcaster instance
    """
    ts = event.get("timestamp")
    state.update_field("shield_up", True, TelemetrySource.JOURNAL, ts)
    logger.info("ShieldsUp -> shields regenerated")

    await broadcaster.publish(
        SHIELDS_UP,
        ShipStateEvent.now(SHIELDS_UP, {"timestamp": str(ts)}, source="journal"),
    )


def register(
    dispatcher_register: Any,
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Register Hull Triggers handlers with the EventDispatcher.

    Args:
        dispatcher_register: EventDispatcher.register method
        state: The shared StateManager instance
        broadcaster: The shared ShipStateBroadcaster instance
    """
    prev_holder: dict[str, float | None] = {"value": None}

    async def _hull_damage(event: dict[str, Any]) -> None:
        await handle_hull_damage(event, state, broadcaster, prev_holder)

    async def _shields_down(event: dict[str, Any]) -> None:
        await handle_shields_down(event, state, broadcaster)

    async def _shields_up(event: dict[str, Any]) -> None:
        await handle_shields_up(event, state, broadcaster)

    dispatcher_register("HullDamage", _hull_damage)
    dispatcher_register("ShieldsDown", _shields_down)
    dispatcher_register("ShieldsUp", _shields_up)

    logger.info(
        "Hull Triggers handlers registered (HullDamage, ShieldsDown, ShieldsUp)"
    )
