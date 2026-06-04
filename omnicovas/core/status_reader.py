"""
omnicovas.core.status_reader

Monitors Elite Dangerous Status.json for live ship state changes.

Status.json is written by ED approximately every second while in-game.
It contains: pips, heat, shields, fuel, hull, flags (docked/landed/etc.).

Architecture Decision — Polling Over watchdog:
    Status.json updates at ~1Hz. watchdog on Windows can fire multiple
    events for a single write at high frequency (the "duplicate event"
    problem from the Phase 1 Dev Guide Week 2 Part C).
    Polling every 500ms with timestamp deduplication is simpler and
    more reliable for this specific file.

Law 7 (Telemetry Rigidity):
    Status.json defines current ship state for this session.
    Every change fires a StatusChanged event for downstream handlers.

See: Phase 1 Development Guide Week 2, Part C
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Default Status.json location (same directory as journal files)
DEFAULT_STATUS_PATH = Path(
    os.path.expandvars(
        r"%USERPROFILE%\Saved Games\Frontier Developments\Elite Dangerous\Status.json"
    )
)

# Polling interval in seconds
# ED writes Status.json at ~1Hz; polling at 500ms catches every change
# without burning CPU on redundant reads.
STATUS_POLL_INTERVAL = 0.5

# Fuel threshold for FuelLow sub-event (25%)
FUEL_LOW_THRESHOLD = 0.25

# Heat threshold for HeatWarning sub-event (75%)
HEAT_WARNING_THRESHOLD = 0.75


class StatusReader:
    """
    Polls Status.json and fires events when values change.

    Emits a synthetic 'Status' event type through the dispatch function,
    containing before/after state plus any derived sub-events (FuelLow,
    HeatWarning, etc.).

    Args:
        dispatch_fn: Async coroutine called with each change event (JSON string)
        status_path: Path to Status.json (defaults to standard ED location)
        poll_interval: Seconds between polls (default 0.5)

    Usage:
        reader = StatusReader(dispatch_fn=my_handler)
        await reader.start()
        # ... runs until stopped ...
        await reader.stop()

    See: Phase 1 Development Guide Week 2, Part C
    """

    def __init__(
        self,
        dispatch_fn: Callable[[str], Coroutine[Any, Any, None]],
        status_path: Path | None = None,
        poll_interval: float = STATUS_POLL_INTERVAL,
    ) -> None:
        self._dispatch_fn = dispatch_fn
        self._status_path = status_path or DEFAULT_STATUS_PATH
        self._poll_interval = poll_interval
        self._last_timestamp: str | None = None
        self._last_state: dict[str, Any] | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None

    async def _read_status(self) -> dict[str, Any] | None:
        """
        Read and parse Status.json.

        Returns:
            Parsed status dict, or None if file missing/malformed/unchanged.
        """
        if not self._status_path.exists():
            return None

        try:
            with open(self._status_path, encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return None
                status: dict[str, Any] = json.loads(content)
                return status
        except (OSError, json.JSONDecodeError) as e:
            logger.debug("Status.json read skipped: %s", e)
            return None

    def _detect_sub_events(
        self,
        old_state: dict[str, Any] | None,
        new_state: dict[str, Any],
    ) -> list[str]:
        """
        Detect meaningful state transitions between polls.

        Returns a list of sub-event names (e.g. 'FuelLow', 'HeatWarning').
        These are synthetic events OmniCOVAS generates — not from ED itself.

        Args:
            old_state: Previous status dict (None on first read)
            new_state: Current status dict

        Returns:
            List of sub-event name strings
        """
        sub_events: list[str] = []

        if old_state is None:
            return sub_events

        # Fuel transitions
        old_fuel = old_state.get("Fuel", {})
        new_fuel = new_state.get("Fuel", {})
        old_main = old_fuel.get("FuelMain", 1.0) if isinstance(old_fuel, dict) else 1.0
        new_main = new_fuel.get("FuelMain", 1.0) if isinstance(new_fuel, dict) else 1.0

        # Only fire FuelLow on the crossing (not every poll while low)
        if old_main >= FUEL_LOW_THRESHOLD and new_main < FUEL_LOW_THRESHOLD:
            sub_events.append("FuelLow")

        # Heat warning — ED reports heat as 0.0-2.0 (1.0 = max safe)
        old_heat = old_state.get("Heat", 0.0)
        new_heat = new_state.get("Heat", 0.0)
        if old_heat < HEAT_WARNING_THRESHOLD and new_heat >= HEAT_WARNING_THRESHOLD:
            sub_events.append("HeatWarning")

        # Shields — Flags bit 3 is "Shields Up"
        SHIELDS_UP_FLAG = 1 << 3
        old_flags = old_state.get("Flags", 0)
        new_flags = new_state.get("Flags", 0)
        old_shields = bool(old_flags & SHIELDS_UP_FLAG)
        new_shields = bool(new_flags & SHIELDS_UP_FLAG)
        if old_shields and not new_shields:
            sub_events.append("ShieldDown")

        # Pips changed (any element different)
        old_pips = old_state.get("Pips", [])
        new_pips = new_state.get("Pips", [])
        if old_pips != new_pips:
            sub_events.append("PipsChanged")

        # Interdiction — Flags bit 23, value 8388608 (0x00800000), "Being Interdicted"
        # Rising edge only: fires once when interdiction starts, not every poll.
        BEING_INTERDICTED_FLAG = 1 << 23
        if not (old_flags & BEING_INTERDICTED_FLAG) and (
            new_flags & BEING_INTERDICTED_FLAG
        ):
            sub_events.append("BeingInterdicted")

        return sub_events

    async def _poll_once(self) -> None:
        """
        Perform a single poll: read, detect changes, dispatch events.
        """
        new_state = await self._read_status()

        if new_state is None:
            return

        # Deduplicate by timestamp — ED updates timestamp on every write
        timestamp = new_state.get("timestamp")
        if timestamp is not None and timestamp == self._last_timestamp:
            return  # No change since last poll

        # Detect sub-events before updating state
        sub_events = self._detect_sub_events(self._last_state, new_state)

        # Build the synthetic Status event
        status_event: dict[str, Any] = {
            "event": "Status",
            "timestamp": timestamp,
            "Flags": new_state.get("Flags", 0),
            "SubEvents": sub_events,
        }

        # Law 7 (Telemetry Rigidity): Only include fields present in Status.json.
        # This prevents defaulting (e.g. 0.0 heat or empty pips) from overriding
        # valid state if Status.json happens to omit a field during a transition.
        if "Pips" in new_state:
            status_event["Pips"] = new_state["Pips"]

        if "Fuel" in new_state:
            status_event["Fuel"] = new_state["Fuel"]

        if "Heat" in new_state:
            status_event["Heat"] = new_state["Heat"]

        if "Balance" in new_state:
            status_event["Balance"] = new_state["Balance"]

        # Dispatch the main Status event
        await self._dispatch_fn(json.dumps(status_event))

        # Dispatch each sub-event as its own event for modules that care
        for sub_event_name in sub_events:
            sub_event = {
                "event": sub_event_name,
                "timestamp": timestamp,
                "source": "Status.json",
            }
            await self._dispatch_fn(json.dumps(sub_event))

        # Update tracking state
        self._last_timestamp = timestamp
        self._last_state = new_state

    async def _poll_loop(self) -> None:
        """
        Main polling loop. Runs until _running is set False.
        """
        logger.info(
            "Status.json reader polling every %.1fs: %s",
            self._poll_interval,
            self._status_path,
        )
        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                # Law 6: never crash the loop
                logger.error("Status poll error: %s", e, exc_info=True)
            await asyncio.sleep(self._poll_interval)

    async def start(self) -> None:
        """
        Start polling Status.json in the background.
        """
        if self._running:
            logger.warning("StatusReader already running.")
            return

        if not self._status_path.exists():
            logger.warning(
                "Status.json not found at %s. "
                "Reader will start but wait for ED to create it.",
                self._status_path,
            )

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("StatusReader started.")

    async def stop(self) -> None:
        """
        Stop polling gracefully.
        """
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("StatusReader stopped.")
