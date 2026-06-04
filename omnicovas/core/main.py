"""
omnicovas.core.main

Main entry point for the OmniCOVAS Python core brain.

Phase 2 pipeline:
    configure_logging()  <- must run first
    ResourceMonitor      <- Principle 10 enforcement
    JournalWatcher ──┐
                     ├─> EventDispatcher ──┬─> Handlers ─> StateManager
    StatusReader ────┘                     ├─> EventRecorder -> SQLite
                                           ├─> ApiBridge -> FastAPI/WebSocket
                                           └─> ShipStateBroadcaster -> subs

See: Master Blueprint v4.1 Section 3 (Tech Stack)
See: Phase 2 Development Guide Week 7, Part B (broadcaster wiring)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone

from omnicovas.core.api_bridge import ApiBridge
from omnicovas.core.broadcaster import ShipStateBroadcaster
from omnicovas.core.dispatcher import EventDispatcher
from omnicovas.core.handlers import make_handlers
from omnicovas.core.journal_watcher import JournalWatcher
from omnicovas.core.latency import BudgetedDispatcher
from omnicovas.core.logging_config import configure_logging
from omnicovas.core.resource_monitor import ResourceMonitor
from omnicovas.core.state_manager import StateManager
from omnicovas.core.status_reader import StatusReader
from omnicovas.db.engine import init_database, make_session_factory
from omnicovas.db.recorder import EventRecorder

logger = logging.getLogger(__name__)


async def main() -> None:
    """
    Main async entry point.

    Wires together every component in the correct order:
        0. configure_logging()      -- must be first so all subsequent logs work
        1. ResourceMonitor          -- start early to observe startup resource use
        2. Database                 -- init schema, create session row
        3. StateManager             -- in-memory session state
        3b. ShipStateBroadcaster    -- Phase 2 pub/sub backbone (one instance, shared)
        4. ApiBridge                -- FastAPI + WebSocket + /resources endpoint
        5. EventDispatcher          -- routes events to handlers + recorder + bridge
        6. JournalWatcher           -- reads journal files
        7. StatusReader             -- polls Status.json
        8. Emit ready JSON to stdout for Tauri sidecar to pick up port

    Broadcaster construction note:
        The broadcaster is instantiated here alongside the StateManager.
        It is passed into make_handlers() so every handler can publish
        ShipStateEvents. Do NOT construct the broadcaster inside any handler
        -- multiple broadcaster instances would mean missed subscriptions.
    """
    # Step 0: logging must be configured before anything else logs
    configure_logging()

    logger.info("OmniCOVAS core brain starting...")

    # Step 1: resource monitor
    resource_monitor = ResourceMonitor()
    await resource_monitor.start()

    # Step 2: database
    engine = await init_database()
    session_factory = make_session_factory(engine)
    recorder = EventRecorder(session_factory)

    # Step 3: state manager
    state = StateManager()

    # Step 3b: broadcaster -- one instance, shared across all handlers.
    # Subscribers (future pillars, activity log sink) register here before
    # the journal watcher starts so no events are missed.
    broadcaster = ShipStateBroadcaster()

    # Shared Activity Log for critical events, Week 13 confirmations, and
    # commander-initiated PvP note writes.
    from omnicovas.core.activity_log import (
        ActivityEntry,
        ActivityLog,
        subscribe_critical_events,
    )

    activity_log = ActivityLog()

    # Phase 5 PB05-06: Source routing foundation
    from omnicovas.api import source as source_api
    from omnicovas.core.source_registry import SourceRegistry
    from omnicovas.features.provider_lookups import register_providers

    source_registry = SourceRegistry()
    register_providers(source_registry)
    source_api.set_source_registry(source_registry)

    # Step 4: API bridge
    bridge = ApiBridge(
        state_manager=state,
        resource_monitor=resource_monitor,
        activity_log=activity_log,
        session_factory=session_factory,
    )

    # Step 5: dispatcher wiring -- broadcaster passed to make_handlers
    dispatcher = EventDispatcher()
    for event_type, handler in make_handlers(
        state, broadcaster, activity_log, session_factory
    ).items():
        dispatcher.register(event_type, handler)

    # Register Pillar 1 feature handlers (Phase 2)
    from omnicovas.features import cargo as _cargo
    from omnicovas.features import fuel as _fuel
    from omnicovas.features import loadout as _loadout
    from omnicovas.features import module_health as _module_health
    from omnicovas.features import ship_state as _ship_state

    _loadout.register(dispatcher.register, state, broadcaster)
    _ship_state.register(dispatcher.register, state, broadcaster)
    _fuel.register(dispatcher.register, state, broadcaster)
    _cargo.register(dispatcher.register, state, broadcaster)
    _module_health.register_subscriber(state, broadcaster)

    # Activity Log — Critical Event Broadcaster (Feature 7, Week 9)
    # Subscribe BEFORE Week 9 feature handlers register so no critical
    # broadcasts are missed during subsequent setup.
    subscribe_critical_events(activity_log, broadcaster)

    # Week 9 feature handlers
    from omnicovas.features import extended_events as _extended_events
    from omnicovas.features import heat_management as _heat_management
    from omnicovas.features import hull_triggers as _hull_triggers
    from omnicovas.features import power_distribution as _power_distribution

    _hull_triggers.register(dispatcher.register, state, broadcaster)
    _extended_events.register(dispatcher.register, state, broadcaster)
    _power_distribution.register(dispatcher.register, state, broadcaster)
    _heat_management.register(dispatcher.register, state, broadcaster)

    # Week 10: Rebuy Calculator (Feature 11 -- Tier 1, no registration needed;
    # rebuy is computed on-demand from state captured by ship_state handlers)
    logger.info("Rebuy Calculator ready (on-demand via /rebuy endpoint)")

    # Phase 3 Week 11: subscribe to every broadcaster event type and forward
    # the ShipStateEvent to the ApiBridge WebSocket so the UI receives all
    # Phase 2 broadcasts without the UI having to poll.
    from omnicovas.core.broadcaster import ShipStateEvent
    from omnicovas.core.event_types import ALL_EVENT_TYPES

    async def _forward_to_ws(event: ShipStateEvent) -> None:
        await bridge.push_event(
            {
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(),
                "payload": event.payload,
                "source": event.source,
            }
        )

    for _et in ALL_EVENT_TYPES:
        broadcaster.subscribe(_et, _forward_to_ws)

    dispatcher.register_recorder(recorder.record_event)

    async def push_to_bridge(event: dict[str, object], raw_line: str) -> None:
        await bridge.push_event(event)

    dispatcher.register_recorder(push_to_bridge)

    logger.info("Event handlers, recorder, broadcaster, and bridge registered.")

    # Step 6: journal watcher
    def _on_journal_rollover(old: object, new: object) -> None:
        """Record an auditable Activity Log entry when the watcher switches to a
        newer journal (JOURNAL_ROLLOVER_01). Local-only proof; no provider call."""
        old_name = getattr(old, "name", None) or "none"
        new_name = getattr(new, "name", None) or "unknown"
        activity_log.append(
            ActivityEntry(
                event_type="JOURNAL_ROLLOVER",
                timestamp=datetime.now(timezone.utc).isoformat(),
                summary=f"Journal rollover: {old_name} -> {new_name}",
                source="journal",
            )
        )
        logger.info("Journal rollover recorded: %s -> %s", old_name, new_name)

    budgeted = BudgetedDispatcher(dispatcher)
    journal_watcher = JournalWatcher(
        dispatch_fn=budgeted.dispatch, on_rollover=_on_journal_rollover
    )
    current_journal = journal_watcher._find_current_journal()
    journal_filename = current_journal.name if current_journal else "unknown"
    await recorder.start_session(journal_filename=journal_filename)
    await journal_watcher.start()

    # Step 7: Status.json reader
    status_reader = StatusReader(dispatch_fn=budgeted.dispatch)
    await status_reader.start()

    # Step 8: start API bridge last
    await bridge.start()
    if not await bridge.wait_until_ready():
        logger.error("API bridge did not become ready in time")
        return

    # Emit ready JSON so Tauri can pick up the port
    ready_message = {
        "status": "ready",
        "port": bridge.port,
        "host": bridge.host,
        "version": "0.1.0",
    }
    print(json.dumps(ready_message), flush=True)
    sys.stdout.flush()
    logger.info("Ready signal emitted: port=%d", bridge.port)
    logger.info("OmniCOVAS core brain running. Press Ctrl+C to stop.")

    try:
        while True:
            await asyncio.sleep(5)
            snap = state.snapshot
            res = resource_monitor.latest
            res_str = (
                f"mem={res.memory_used_mb:.0f}MB cpu={res.cpu_percent:.1f}%"
                if res is not None
                else "mem=? cpu=?"
            )
            logger.info(
                "[STATE] system=%s station=%s docked=%s hull=%s "
                "fuel=%s ship=%s (db=%d ws=%d %s)",
                snap.current_system,
                snap.current_station,
                snap.is_docked,
                snap.hull_health,
                snap.fuel_main,
                snap.current_ship_type,
                recorder.events_recorded,
                bridge._broadcaster.client_count,
                res_str,
            )
    except asyncio.CancelledError:
        pass
    finally:
        await status_reader.stop()
        await journal_watcher.stop()
        await bridge.stop()
        await resource_monitor.stop()
        await recorder.end_session()
        await engine.dispose()
        logger.info(
            "OmniCOVAS core brain stopped. Total events processed: %d",
            dispatcher.events_processed,
        )


if __name__ == "__main__":
    asyncio.run(main())
