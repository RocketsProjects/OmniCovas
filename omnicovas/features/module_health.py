# omnicovas/features/module_health.py
"""
omnicovas.features.module_health

Module Health — Feature 2 (Pillar 1, Tier 1 — Pure Telemetry).

Subscriber: LOADOUT_CHANGED
Publishes: MODULE_DAMAGED (health < 0.8), MODULE_CRITICAL (health < 0.2)
Per-module: one event per affected module, not batched
Ref: Phase 2 Development Guide Week 8, Part A
Ref: Master Blueprint v4.2 — Pillar 1, Feature 2
Law 5: broadcasts only when threshold crossed; healthy modules produce no events
Law 7: reads state only; does not write state
"""

from __future__ import annotations

import logging

from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import LOADOUT_CHANGED, MODULE_CRITICAL, MODULE_DAMAGED
from omnicovas.core.state_manager import StateManager

logger = logging.getLogger(__name__)

# KB: combat_mechanics::module_health_warning_threshold
_MODULE_DAMAGED_FRACTION: float = 0.8
# KB: combat_mechanics::module_health_critical_threshold
_MODULE_CRITICAL_FRACTION: float = 0.2


def register_subscriber(
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Subscribe to LOADOUT_CHANGED and scan modules for health thresholds.

    Args:
        state: Shared StateManager instance (read-only in subscriber)
        broadcaster: Shared ShipStateBroadcaster instance
    """

    async def _on_loadout_changed(event: ShipStateEvent) -> None:
        snap = state.snapshot
        damaged_count = 0
        critical_count = 0
        for slot, module in snap.modules.items():
            if module.health < _MODULE_CRITICAL_FRACTION:
                critical_count += 1
                await broadcaster.publish(
                    MODULE_CRITICAL,
                    ShipStateEvent.now(
                        MODULE_CRITICAL,
                        {
                            "slot": slot,
                            "item": module.item,
                            "health": module.health,
                            "threshold": _MODULE_CRITICAL_FRACTION,
                        },
                        source="journal",
                    ),
                )
            elif module.health < _MODULE_DAMAGED_FRACTION:
                damaged_count += 1
                await broadcaster.publish(
                    MODULE_DAMAGED,
                    ShipStateEvent.now(
                        MODULE_DAMAGED,
                        {
                            "slot": slot,
                            "item": module.item,
                            "health": module.health,
                            "threshold": _MODULE_DAMAGED_FRACTION,
                        },
                        source="journal",
                    ),
                )
        logger.info(
            "module_health scan: %d damaged, %d critical (of %d total)",
            damaged_count,
            critical_count,
            len(snap.modules),
        )

    broadcaster.subscribe(LOADOUT_CHANGED, _on_loadout_changed)
    logger.info("Module Health subscriber registered (LOADOUT_CHANGED)")
