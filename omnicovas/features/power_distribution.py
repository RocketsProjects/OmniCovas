# omnicovas/features/power_distribution.py
"""
omnicovas.features.power_distribution

Power Distribution Monitoring -- Feature 9 (Pillar 1, Tier 1 — Pure Telemetry).

Handler: Status (dispatcher event from Status.json poll)
Publishes: PIPS_CHANGED — only when SYS/ENG/WEP pips differ from previous reading
Runs alongside handlers.py handle_status — does not duplicate state writes.

Ref: Phase 2 Development Guide Week 9, Part D
Ref: Master Blueprint v4.2 — Pillar 1, Feature 9

Law 5 (Zero Hallucination):
    on-foot (Pips absent) does not clear previous pips; no broadcast

Law 7 (Telemetry Rigidity):
    reads pip values from event payload directly
"""

from __future__ import annotations

import logging
from typing import Any

from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import PIPS_CHANGED
from omnicovas.core.state_manager import StateManager

logger = logging.getLogger(__name__)


async def handle_status_pips(
    event: dict[str, Any],
    broadcaster: ShipStateBroadcaster,
    prev_holder: dict[str, tuple[int, int, int] | None],
) -> None:
    """Handle Status pips event — publish PIPS_CHANGED when pips change.

    Journal fields:
        Pips    -- [SYS, ENG, WEP] list of 0-3 ints

    Behavior:
        Only broadcasts PIPS_CHANGED when pips differ from previous reading.
        Absent Pips (on-foot) does not clear previous pips; no broadcast.

    Args:
        event: Status event from Status.json poll
        broadcaster: ShipStateBroadcaster instance
        prev_holder: dict with "value" key holding previous pip tuple or None
    """
    pips_raw = event.get("Pips")

    if not isinstance(pips_raw, list) or len(pips_raw) != 3:
        logger.debug(
            "Status pips absent — on-foot or pre-ship; no PIPS_CHANGED broadcast"
        )
        return

    new_pips = (int(pips_raw[0]), int(pips_raw[1]), int(pips_raw[2]))
    prev = prev_holder["value"]
    prev_holder["value"] = new_pips

    if prev is None or new_pips != prev:
        logger.debug(
            "PIPS_CHANGED: sys=%d eng=%d wep=%d (prev=%s)",
            new_pips[0],
            new_pips[1],
            new_pips[2],
            prev,
        )
        await broadcaster.publish(
            PIPS_CHANGED,
            ShipStateEvent.now(
                PIPS_CHANGED,
                {"sys": new_pips[0], "eng": new_pips[1], "wep": new_pips[2]},
                source="status_json",
            ),
        )


def register(
    dispatcher_register: Any,
    state: StateManager,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Register Power Distribution handler with the EventDispatcher.

    Args:
        dispatcher_register: EventDispatcher.register method
        state: The shared StateManager instance (unused but kept for
            signature consistency)
        broadcaster: The shared ShipStateBroadcaster instance
    """
    prev_holder: dict[str, tuple[int, int, int] | None] = {"value": None}

    async def _status_pips(event: dict[str, Any]) -> None:
        await handle_status_pips(event, broadcaster, prev_holder)

    dispatcher_register("Status", _status_pips)

    logger.info("Power Distribution handler registered (Status)")
