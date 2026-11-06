"""
omnicovas.core.api_bridge

FastAPI HTTP and WebSocket bridge between the Python core and the Tauri UI.

Architecture:
    Python core (asyncio)
        → FastAPI on dynamic localhost port
            → Tauri webview (tauri://localhost)
                → HTTP polling for state
                → WebSocket subscription for live events

Law 6 (Performance Priority):
    - Non-blocking startup: FastAPI bound BEFORE ready signal emitted
    - Dynamic port selection avoids conflicts with other dev tools

Law 8 (Sovereignty & Transparency):
    - /state exposes current StateManager snapshot
    - /activity-log exposes shared Activity Log proof entries
    - /health exposes basic runtime stats

See: Master Blueprint v4.0 Section 3 (Tech Stack)
See: Phase 1 Development Guide Week 5, Part A
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.api import activity_log as activity_log_router
from omnicovas.api import combat as combat_router
from omnicovas.api import combat_session as combat_session_router
from omnicovas.api import commander_memory as commander_memory_router
from omnicovas.api import engineering as engineering_router
from omnicovas.api import expeditions as expeditions_router
from omnicovas.api import galactic_historian as galactic_historian_router
from omnicovas.api import galactic_knowledge as galactic_knowledge_router
from omnicovas.api import intel as intel_router
from omnicovas.api import intel_campaign as intel_campaign_router
from omnicovas.api import intel_history as intel_history_router
from omnicovas.api import intel_reference as intel_reference_router
from omnicovas.api import knowledge_graph as knowledge_graph_router
from omnicovas.api import local_context as local_context_router
from omnicovas.api import local_economic as local_economic_router
from omnicovas.api import navigation as navigation_router
from omnicovas.api import navigation_bookmarks as navigation_bookmarks_router
from omnicovas.api import navigation_history as navigation_history_router
from omnicovas.api import operations as operations_router
from omnicovas.api import pillar1 as pillar1_router
from omnicovas.api import pvp as pvp_router
from omnicovas.api import readiness as readiness_router
from omnicovas.api import source as source_api
from omnicovas.api import squadrons as squadrons_router
from omnicovas.api import system_notes as system_notes_router
from omnicovas.api import week13 as week13_router
from omnicovas.config.vault import ConfigVault
from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.confirmation_gate import ConfirmationGate
from omnicovas.core.event_types import (
    COMBAT_SESSION_STATE_CHANGED,
    COMBAT_STATE_CHANGED,
)
from omnicovas.core.state_manager import StateManager
from omnicovas.features import commander_chronicle
from omnicovas.features.commander_chronicle import ChronicleService
from omnicovas.features.commander_memory import CommanderMemoryService
from omnicovas.features.expedition_service import ExpeditionService
from omnicovas.features.galactic_intelligence import (
    BRIEFING_EVENT,
    CLEARED_EVENT,
    GalacticIntelligence,
)
from omnicovas.features.operations_objectives import OperationsObjectiveService
from omnicovas.features.system_notes import SystemNoteService

logger = logging.getLogger(__name__)

ACTIVITY_LOG_CAPACITY = 1000

# Bridge identity. The native launcher may find an already-listening loopback
# port recorded in a previous run's log. Before adopting that listener as the
# Commander's backend it verifies these two fields on /health, so a foreign
# process that merely happens to hold a recycled port is rejected rather than
# silently trusted. Bump BRIDGE_PROTOCOL_VERSION when the bridge contract
# changes incompatibly, so an older running sidecar is not adopted by a newer
# shell (or vice versa).
BRIDGE_APP_IDENTITY = "omnicovas"
BRIDGE_PROTOCOL_VERSION = 1

# UI category classification — mirrors activity-log.js getEventCategory()
# plus CRITICAL_EVENT_TYPES from event_types.py.
_CATEGORY_CRITICAL_TYPES: frozenset[str] = frozenset(
    {
        "HULL_CRITICAL_25",
        "HULL_CRITICAL_10",
        "SHIELDS_DOWN",
        "FUEL_LOW",
        "FUEL_CRITICAL",
        "MODULE_CRITICAL",
        "DESTROYED",
    }
)
_CATEGORY_EXTENDED_TYPES: frozenset[str] = frozenset(
    {
        "FSD_JUMP",
        "DOCKED",
        "UNDOCKED",
        "WANTED",
        "INTERDICTION_STARTED",
        "INTERDICTION_ENDED",
    }
)
_CATEGORY_SOURCE_TYPES: frozenset[str] = frozenset(
    {
        "SOURCE_REGISTRY_REGISTERED",
        "SOURCE_HEALTH_UPDATED",
        "SOURCE_CHAIN_RESOLVED",
        "EXTERNAL_REQUEST_QUEUED",
        "EXTERNAL_REQUEST_BLOCKED",
        "SOURCE_RATE_LIMITED",
        "SOURCE_CACHE_HIT",
        "SOURCE_STALE_CACHE_USE",
    }
)


def find_free_port() -> int:
    """Bind to port 0 to let the OS pick a free port, then return it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class WebSocketBroadcaster:
    """
    Tracks active WebSocket clients and broadcasts messages to all of them.

    Handles client disconnection gracefully — a dead client never blocks
    broadcast to live clients.
    """

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        logger.info("WebSocket client connected (%d total)", len(self._clients))

    async def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket client."""
        async with self._lock:
            self._clients.discard(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._clients))

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Send a message to every connected client."""
        async with self._lock:
            clients = list(self._clients)

        dead: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(message)
            except Exception as e:
                logger.debug("WebSocket send failed, dropping client: %s", e)
                dead.append(client)

        if dead:
            async with self._lock:
                for client in dead:
                    self._clients.discard(client)

    @property
    def client_count(self) -> int:
        """Number of currently connected WebSocket clients."""
        return len(self._clients)


class ApiBridge:
    """FastAPI application hosting the Python↔Tauri bridge."""

    def __init__(
        self,
        state_manager: StateManager,
        host: str = "127.0.0.1",
        port: int | None = None,
        resource_monitor: Any = None,
        config_vault: ConfigVault | None = None,
        activity_log: ActivityLog | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        commander_memory_service: CommanderMemoryService | None = None,
    ) -> None:
        self._state = state_manager
        self._host = host
        self._port = port if port is not None else find_free_port()
        self._resource_monitor = resource_monitor
        self._vault = config_vault or ConfigVault()
        self._confirmation_activity_log = (
            activity_log if activity_log is not None else ActivityLog()
        )
        self._session_factory = session_factory
        self.operations_objectives = (
            OperationsObjectiveService(session_factory, self._confirmation_activity_log)
            if session_factory
            else None
        )
        self._commander_memory = commander_memory_service
        # PB10-R6: stated explicitly. The only production consumers of this
        # gate are advisory (Phase 9 campaign AI draft; route-activation
        # review proposal) and perform no action. Commander-impacting
        # confirmation is owned by the Week 13 queue.
        self._gate = ConfirmationGate.for_advisory_drafting()
        # GKI-04: one Galactic Intelligence service per bridge.  Its briefings
        # travel the same push path as every other event; the dispatcher feeds it
        # through galactic_intelligence.register().
        self.galactic_intelligence = GalacticIntelligence(
            state_manager,
            session_factory,
            self._vault,
            profile_provider=lambda: (
                commander_memory_service.active_profile_key
                if commander_memory_service is not None
                else None
            ),
            notify=self.push_event,
        )
        from omnicovas.features.notification_shadow import NotificationShadow

        self.notification_shadow = NotificationShadow(
            state_manager,
            session_factory,
            self._vault,
            self.galactic_intelligence,
            lambda: (
                commander_memory_service.active_profile_key
                if commander_memory_service
                else None
            ),
        )
        from omnicovas.features.mining_prospector import MiningProspector

        self.mining_prospector = MiningProspector(
            self.operations_objectives, self.notification_shadow, notify=self.push_event
        )
        self.notification_shadow.mining_prospector = self.mining_prospector
        self._confirmation_activity_log.observe(self.mining_prospector.observe_activity)
        self._confirmation_activity_log.observe(
            self.notification_shadow.observe_activity
        )
        if commander_memory_service is not None:
            # Forgetting a commander in Commander Memory also forgets their
            # Galactic Intelligence preferences, briefings and encounters.
            commander_memory_service.add_forget_hook(
                purge=self.galactic_intelligence.purge_profile,
                after=self.galactic_intelligence.after_forget,
            )
        # GKI-06: Galactic Expeditions reuse Galactic Intelligence's preferences and
        # commander checks; the dispatcher feeds them via expedition_service.register().
        self.expeditions = ExpeditionService(
            state_manager,
            session_factory,
            self.galactic_intelligence,
            profile_provider=lambda: (
                commander_memory_service.active_profile_key
                if commander_memory_service is not None
                else None
            ),
            notify=self.push_event,
        )
        if commander_memory_service is not None:
            # Forgetting a commander also deletes their expeditions and history.
            commander_memory_service.add_forget_hook(
                purge=self.expeditions.purge_profile,
                after=self.expeditions.after_forget,
            )
        # GKI-07: the Commander Chronicle reads Commander Memory and the
        # expeditions, and supplies evidence to Galactic Intelligence's briefings;
        # the dispatcher feeds it via commander_chronicle.register().
        self.chronicle = ChronicleService(
            state_manager,
            session_factory,
            self.galactic_intelligence,
            expeditions=self.expeditions,
            profile_provider=lambda: (
                commander_memory_service.active_profile_key
                if commander_memory_service is not None
                else None
            ),
            notify=self.push_event,
        )
        self.galactic_intelligence.set_history(self.chronicle.briefing_history)
        if commander_memory_service is not None:
            # Forgetting a commander also deletes their Chronicle.
            commander_memory_service.add_forget_hook(
                purge=self.chronicle.purge_profile,
                after=self.chronicle.after_forget,
            )
        if commander_memory_service is not None:
            commander_memory_service.add_forget_hook(
                purge=self.notification_shadow.purge_profile,
                after=self.notification_shadow.after_forget,
            )
            commander_memory_service.add_forget_hook(
                after=self.mining_prospector.after_forget
            )
        self.notification_shadow.opportunity_providers = (
            self.galactic_intelligence.recent_opportunities,
            self.expeditions.opportunities,
        )
        # Director-owned presentation snapshots reach the overlay and desktop
        # over the existing /ws/events stream; a dead socket cannot fail arbitration.
        self.notification_shadow.publish = self._publish_presentation
        self._profile_provider = lambda: (
            commander_memory_service.active_profile_key
            if commander_memory_service is not None
            else None
        )
        self._app = self._build_app()
        self._broadcaster = WebSocketBroadcaster()
        self._activity_log: deque[dict[str, Any]] = deque(maxlen=ACTIVITY_LOG_CAPACITY)
        self._server_task: asyncio.Task[None] | None = None
        self._started_at: float | None = None
        self._events_counter = 0
        self._ready_event = asyncio.Event()

    async def _publish_presentation(self, message: dict[str, Any]) -> None:
        await self._broadcaster.broadcast(message)

    @property
    def port(self) -> int:
        """The port this bridge is configured to bind to."""
        return self._port

    @property
    def host(self) -> str:
        """The host this bridge is bound to (default 127.0.0.1)."""
        return self._host

    def _build_app(self) -> FastAPI:
        """Build the FastAPI application with routes and middleware."""
        app = FastAPI(
            title="OmniCOVAS Core API",
            description="Internal bridge between Python core and Tauri UI",
            version="0.1.0",
        )
        from omnicovas.api import notification_shadow as notification_shadow_router

        notification_shadow_router.set_service(self.notification_shadow)
        app.include_router(notification_shadow_router.router)
        from omnicovas.api import notifications as notifications_router

        notifications_router.set_service(
            self.notification_shadow, self._profile_provider
        )
        app.include_router(notifications_router.router)

        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
        )

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Phase 3: Pillar 1 endpoint router (Week 11 Part B)
        pillar1_router.set_state_manager(self._state)
        pillar1_router.set_config_vault(self._vault)
        app.include_router(pillar1_router.router)

        # Phase 3 Week 13: Onboarding, Privacy, Settings, Confirmations
        week13_router.set_config_vault(self._vault)
        week13_router.set_activity_log(self._confirmation_activity_log)
        app.include_router(week13_router.router)

        # Phase 4: Combat Target & Threat snapshot
        combat_router.set_state_manager(self._state)
        app.include_router(combat_router.router)

        # Phase 5: Intel KnownFact snapshot seam
        intel_router.set_state_manager(self._state)
        app.include_router(intel_router.router)

        # Phase 13 Intel terminal core: journal search + visit catalogs over
        # the local flight recorder (read-only bounded queries).
        intel_history_router.set_session_factory(self._session_factory)
        app.include_router(intel_history_router.router)

        # Phase 13: workflow-scoped curated reference library (read-only).
        app.include_router(intel_reference_router.router)

        # Phase 13 (PB13-03/LNA-039): campaign facts and their local evidence.
        # Read-only — Operations keeps campaign execution.
        intel_campaign_router.set_session_factory(self._session_factory)
        app.include_router(intel_campaign_router.router)

        # Phase 6: Local economic fact snapshot seam
        local_economic_router.set_state_manager(self._state)
        app.include_router(local_economic_router.router)

        # Phase 6 extension: field-rich local context backplane snapshot
        local_context_router.set_state_manager(self._state)
        local_context_router.set_commander_memory_service(self._commander_memory)
        app.include_router(local_context_router.router)

        # Phase 11: private local observed-history service and privacy lifecycle.
        commander_memory_router.set_commander_memory_service(self._commander_memory)
        app.include_router(commander_memory_router.router)

        # LNA-004: Commander-authored system notes. Separate from Memory on
        # purpose — a Memory rebuild must never destroy authored text.
        if self._session_factory is not None:
            system_note_service = SystemNoteService(
                self._session_factory, self._confirmation_activity_log
            )
            system_notes_router.set_system_note_service(system_note_service)
            intel_history_router.set_system_note_service(system_note_service)
            knowledge_graph_router.set_system_note_service(system_note_service)
        app.include_router(system_notes_router.router)

        # LNA-028 / LNA-022: one readiness computation for Operations,
        # Dashboard, and Engineering, so no surface grows a rival derivation.
        readiness_router.set_state_manager(self._state)
        app.include_router(readiness_router.router)

        # LNA-006: read-only traversal over what the recorder already holds.
        knowledge_graph_router.set_session_factory(self._session_factory)
        app.include_router(knowledge_graph_router.router)

        # Phase 5 PB05-02: Source routing API seam
        app.include_router(source_api.router)

        # Phase 5 PB05-04: Navigation active-route snapshot seam
        navigation_router.set_state_manager(self._state)
        navigation_router.set_activity_log(self._confirmation_activity_log)
        app.include_router(navigation_router.router)

        # Phase 5 PB05-09: Navigation bookmarks and saved routes
        navigation_bookmarks_router.set_session_factory(self._session_factory)
        navigation_bookmarks_router.set_activity_log(self._confirmation_activity_log)
        app.include_router(navigation_bookmarks_router.router)

        # Phase 15 slice: commander-observed jump timeline (read-only).
        navigation_history_router.set_session_factory(self._session_factory)
        app.include_router(navigation_history_router.router)

        # GKI-06: Galactic Expeditions in Navigation's Plan mode.
        expeditions_router.set_service(self.expeditions)
        app.include_router(expeditions_router.router)

        # Phase 5 PB05-08: Operations exploration/exobiology active objectives
        # PB09-03: Phase 9 campaign persistence injections
        # PB14-R1: Commander objective lifecycle persistence
        operations_router.set_state_manager(self._state)
        operations_router.set_session_factory(self._session_factory)
        operations_router.set_activity_log(self._confirmation_activity_log)
        operations_router.set_confirmation_gate(self._gate)
        if self._session_factory is not None:
            operations_router.set_objective_service(self.operations_objectives)
        operations_router.set_mining_prospector(self.mining_prospector)
        app.include_router(operations_router.router)

        # Phase 4 (PB04-06): Combat session, mission, rewards/rank, loadout readiness
        combat_session_router.set_state_manager(self._state)
        app.include_router(combat_session_router.router)

        # Phase 4: PvP encounter local storage/API foundation
        pvp_router.set_session_factory(self._session_factory)
        pvp_router.set_activity_log(self._confirmation_activity_log)
        app.include_router(pvp_router.router)

        # Phase 7: Squadrons local-only foundation + write proof (PB07-07)
        # PB09-05: Phase 9 local campaign note DB persistence injection
        squadrons_router.set_state_manager(self._state)
        squadrons_router.set_activity_log(self._confirmation_activity_log)
        squadrons_router.set_session_factory(self._session_factory)
        app.include_router(squadrons_router.router)

        # Phase 8: Engineering local-only planning baseline
        engineering_router.set_state_manager(self._state)
        engineering_router.set_session_factory(self._session_factory)
        engineering_router.set_activity_log(self._confirmation_activity_log)
        app.include_router(engineering_router.router)

        # GKI-01: read-only Galactic Knowledge Core and technology unlock planner
        galactic_knowledge_router.set_state_manager(self._state)
        galactic_knowledge_router.set_session_factory(self._session_factory)
        # GKI-04: Commander Context, preferences and briefings (one service)
        galactic_knowledge_router.set_intelligence(self.galactic_intelligence)
        app.include_router(galactic_knowledge_router.router)

        # GKI-07: the Living Galactic Historian and the Commander Chronicle.
        galactic_historian_router.set_service(self.chronicle)
        galactic_historian_router.set_intelligence(self.galactic_intelligence)
        app.include_router(galactic_historian_router.router)

        # Activity Log export authorization + staged export proof.
        activity_log_router.set_activity_log(self._confirmation_activity_log)
        app.include_router(activity_log_router.router)

        # Public, unpersonalized news has its own consent and bounded cache.
        # It never blocks local telemetry and never enables another provider.
        from omnicovas.api import galaxy_today as galaxy_today_router
        from omnicovas.api import source as source_router_api
        from omnicovas.core.source_registry import SourceRegistry
        from omnicovas.features.galnet import GalnetReader

        news_registry = source_router_api.get_source_registry()
        if news_registry is None:
            news_registry = SourceRegistry()
            source_router_api.set_source_registry(news_registry)
        self._galnet_reader = GalnetReader(
            cache_path=Path(os.environ.get("APPDATA", str(Path.home())))
            / "OmniCOVAS"
            / "cache"
            / "galnet-news-v1.json",
            enabled=lambda: self._vault.get("privacy_galnet_news") == "true",
            registry=news_registry,
            activity_log=self._confirmation_activity_log,
        )
        galaxy_today_router.set_reader(self._galnet_reader)
        app.include_router(galaxy_today_router.router)

        @app.get("/health")  # type: ignore[misc,untyped-decorator,unused-ignore]
        async def health() -> dict[str, Any]:
            """Liveness probe + runtime stats."""
            uptime = 0.0
            if self._started_at is not None:
                uptime = time.monotonic() - self._started_at
            return {
                "status": "ok",
                # Identity fields. The native launcher will only adopt an
                # already-listening local bridge when `app` and
                # `bridge_protocol` match, so a foreign or incompatible
                # listener on a recycled port is never silently adopted.
                "app": BRIDGE_APP_IDENTITY,
                "bridge_protocol": BRIDGE_PROTOCOL_VERSION,
                "version": "0.1.0",
                "uptime_seconds": int(uptime),
                "events_processed": self._events_counter,
                "websocket_clients": self._broadcaster.client_count,
            }

        @app.get("/state")  # type: ignore[misc,untyped-decorator,unused-ignore]
        async def get_state() -> dict[str, Any]:
            """Current StateManager snapshot."""
            return self._state.public_snapshot()

        @app.get("/activity-log")  # type: ignore[misc,untyped-decorator,unused-ignore]
        async def get_activity_log() -> dict[str, Any]:
            """Shared Activity Log proof entries."""
            entries = self._shared_activity_log_entries()
            return {
                "total": len(entries),
                "entries": entries,
            }

        @app.get("/rebuy")  # type: ignore[misc,untyped-decorator,unused-ignore]
        async def get_rebuy() -> dict[str, Any]:
            """Rebuy Calculator (Feature 11) -- estimated rebuy cost for current ship.

            Returns:
                rebuy_cost: estimated credits, or null when data unavailable
                ship_type: current ship internal type string
                hull_value: hull insured value in credits
                modules_value: total module insured value in credits
                insurance_percent: rate used (always 5.0 for standard insurance)
                calculated_at: ISO-8601 UTC timestamp of this calculation
            """
            from omnicovas.features.rebuy import rebuy_api_payload

            return rebuy_api_payload(self._state)

        @app.get("/fuel")  # type: ignore[misc,untyped-decorator,unused-ignore]
        async def get_fuel() -> dict[str, Any]:
            """Current fuel state (Feature 5) -- main tank, reservoir, and capacity.

            Returns:
                current: fuel_main in tons, or null
                capacity: fuel_capacity_main in tons, or null
                percentage: current/capacity * 100, or null when either is absent
                reservoir: fuel_reservoir in tons, or null
            """
            snap = self._state.snapshot
            current = snap.fuel_main
            capacity = snap.fuel_capacity_main
            percentage: float | None = None
            if current is not None and capacity is not None and capacity > 0:
                percentage = round(current / capacity * 100, 1)
            return {
                "current": current,
                "capacity": capacity,
                "percentage": percentage,
                "reservoir": snap.fuel_reservoir,
            }

        @app.get("/jump_range")  # type: ignore[misc,untyped-decorator,unused-ignore]
        async def get_jump_range() -> dict[str, Any]:
            """Jump range (Feature 5) -- max jump range from most recent Loadout.

            The value is sourced directly from Loadout.MaxJumpRange (zero cargo,
            enough fuel for one jump per the Journal manual) and is NOT
            recomputed from physics. First-principles jump math is Pillar 3
            (Exploration, Phase 5) work.

            Returns:
                max_ly: maximum jump range in light-years, or null
                ship_type: current ship internal type string
                loadout_hash: SHA-256 hash of current loadout configuration
            """
            snap = self._state.snapshot
            return {
                "max_ly": snap.jump_range_ly,
                "ship_type": snap.current_ship_type,
                "loadout_hash": snap.loadout_hash,
            }

        @app.get("/resources")  # type: ignore[misc,untyped-decorator,unused-ignore]
        async def get_resources() -> dict[str, Any]:
            """Live resource usage snapshot (Principle 10)."""
            if self._resource_monitor is None:
                return {"enabled": False}

            latest = self._resource_monitor.latest
            budget = self._resource_monitor.budget
            return {
                "enabled": True,
                "snapshot": (
                    {
                        "memory_used_mb": round(latest.memory_used_mb, 1),
                        "memory_total_mb": round(latest.memory_total_mb, 1),
                        "cpu_percent": round(latest.cpu_percent, 1),
                        "disk_free_gb": round(latest.disk_free_gb, 1),
                        "disk_total_gb": round(latest.disk_total_gb, 1),
                    }
                    if latest is not None
                    else None
                ),
                "budget": {
                    "max_cache_size_mb": budget.max_cache_size_mb,
                    "max_galaxy_dump_size_gb": budget.max_galaxy_dump_size_gb,
                    "max_background_task_cpu_percent": (
                        budget.max_background_task_cpu_percent
                    ),
                    "max_api_calls_per_minute_total": (
                        budget.max_api_calls_per_minute_total
                    ),
                },
            }

        @app.websocket("/ws/events")  # type: ignore[misc,untyped-decorator,unused-ignore]
        async def ws_events(websocket: WebSocket) -> None:
            """Push live events to connected clients."""
            await self._broadcaster.connect(websocket)
            try:
                await websocket.send_json(
                    {"type": "initial_state", "state": self._state.public_snapshot()}
                )
                # Reconnecting clients learn the current owner and slot before
                # any event, so they never double-render a migrated alert.
                await websocket.send_json(
                    self.notification_shadow.presentation_snapshot()
                )
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.debug("WebSocket closed: %s", e)
            finally:
                await self._broadcaster.disconnect(websocket)

        return app

    def _shared_activity_log_entries(self) -> list[dict[str, Any]]:
        """Return merged entries from shared ActivityLog + ring buffer."""
        shared = [
            self._serialize_activity_entry(entry)
            for entry in self._confirmation_activity_log.entries()
        ]
        ring = self._ring_buffer_entries_as_route_dicts()
        return self._merge_and_dedupe(shared, ring)

    @staticmethod
    def _derive_category(event_type: str) -> str:
        """Return the UI-compatible category for an event type."""
        t = event_type.upper() if event_type else ""
        if not t:
            return "telemetry"
        # ai checked before CRITICAL so PROPOSAL/CONFIRMATION/TIER_3 events
        # are not misclassified by the CRITICAL keyword they contain.
        if any(k in t for k in ("TIER_3", "CONFIRMATION", "PROPOSAL")):
            return "ai"
        if t in _CATEGORY_CRITICAL_TYPES or "CRITICAL" in t or "DESTROYED" in t:
            return "critical"
        if t in _CATEGORY_EXTENDED_TYPES or any(
            k in t for k in ("DOCKED", "WANTED", "FSD")
        ):
            return "extended"
        if (
            t in _CATEGORY_SOURCE_TYPES
            or t.startswith("SOURCE_")
            or t.startswith("EXTERNAL_REQUEST_")
        ):
            return "source"
        if t.startswith("ENGINEERING."):
            return "engineering"
        return "telemetry"

    @staticmethod
    def _serialize_activity_entry(entry: ActivityEntry) -> dict[str, Any]:
        source = getattr(entry, "source", None)
        if not isinstance(source, str) or not source:
            source = "activity_log"
        event_type = entry.event_type
        payload = getattr(entry, "payload", None)
        source_chain = getattr(entry, "source_chain", None)
        redaction_state = getattr(entry, "redaction_state", None)
        linked_entity_refs = getattr(entry, "linked_entity_refs", None)
        surface_origin = getattr(entry, "surface_origin", None)
        correlation_id = getattr(entry, "correlation_id", None)
        event_id = getattr(entry, "event_id", None)
        result: dict[str, Any] = {
            "timestamp": entry.timestamp,
            "event_type": event_type,
            "summary": entry.summary,
            "source": source,
            "category": ApiBridge._derive_category(event_type),
        }
        include_engineering_metadata = event_type.upper().startswith("ENGINEERING.")
        if payload is not None:
            result["payload"] = payload
        if source_chain is not None:
            result["source_chain"] = source_chain
        if redaction_state is not None:
            result["redaction_state"] = redaction_state
        is_fact = bool(getattr(entry, "is_fact", True))
        if include_engineering_metadata or not is_fact:
            result["is_fact"] = is_fact
        if linked_entity_refs is not None:
            result["linked_entity_refs"] = linked_entity_refs
        if surface_origin is not None:
            result["surface_origin"] = surface_origin
        if correlation_id is not None:
            result["correlation_id"] = correlation_id
        if event_id is not None:
            result["event_id"] = event_id
        return result

    def _ring_buffer_entries_as_route_dicts(self) -> list[dict[str, Any]]:
        """Convert ring-buffer entries to route-compatible dicts with category."""
        result: list[dict[str, Any]] = []
        for raw in self._activity_log:
            entry = dict(raw)
            entry["category"] = self._derive_category(str(raw.get("event_type", "")))
            result.append(entry)
        return result

    @staticmethod
    def _merge_and_dedupe(
        shared: list[dict[str, Any]],
        ring: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge shared ActivityLog and ring-buffer entries with safe deduplication.

        Dedupe rule:
          1. Exact key (timestamp + event_type + summary + source) → always collapse.
          2. Cross-source: same (timestamp + event_type + summary) from different
             sources → collapse (same event serialized through both paths).
          3. Same timestamp + event_type but different summary → preserve both.
        """
        seen_exact: set[tuple[str, str, str, str]] = set()
        seen_cross: set[tuple[str, str, str]] = set()
        result: list[dict[str, Any]] = []

        for entry in [*shared, *ring]:
            ts = str(entry.get("timestamp") or "")
            etype = str(entry.get("event_type") or "")
            summary = str(entry.get("summary") or "")
            source = str(entry.get("source") or "")

            exact_key = (ts, etype, summary, source)
            if exact_key in seen_exact:
                continue
            seen_exact.add(exact_key)

            cross_key = (ts, etype, summary)
            if cross_key in seen_cross:
                continue
            seen_cross.add(cross_key)

            result.append(entry)

        return result

    async def push_event(self, event: dict[str, Any]) -> None:
        """Record a raw journal event and broadcast it to WebSocket clients.

        Also accepts ShipStateEvent-shaped dicts (from the Phase 2 broadcaster)
        keyed by 'event_type' instead of 'event'.  Both shapes are normalised
        into the activity log and forwarded to the UI.

        The WebSocket payload shape is:
            {type: 'event', event_type: str, timestamp: str, payload: dict,
             source: str, summary: str}
        This is consumed by shell.js and each Dashboard card subscriber.
        """
        # Normalise both journal events ('event' key) and broadcaster events
        # ('event_type' key) into a common shape.
        event_type = event.get("event_type") or event.get("event", "Unknown")
        timestamp = event.get("timestamp")
        payload = event.get("payload", {})
        source = event.get("source", "journal")
        summary = self._summarize_typed(event_type, payload, event)

        category = self._derive_category(event_type)
        entry: dict[str, Any] = {
            "timestamp": timestamp,
            "event_type": event_type,
            "summary": summary,
            "source": source,
        }
        if event_type not in (COMBAT_STATE_CHANGED, COMBAT_SESSION_STATE_CHANGED):
            self._activity_log.append(entry)
        self._events_counter += 1

        await self._broadcaster.broadcast(
            {
                "type": "event",
                "event_type": event_type,
                "timestamp": timestamp,
                "payload": payload,
                "source": source,
                "summary": summary,
                "category": category,
            }
        )
        # Pure observational enqueue after the unchanged production broadcast.
        # A failed observer cannot fail an otherwise successful production push.
        try:
            self.notification_shadow.observe_bridge(event)
        except Exception:
            logger.warning("Notification shadow bridge observer failed")

    def _summarize_typed(
        self,
        event_type: str,
        payload: dict[str, Any],
        raw: dict[str, Any],
    ) -> str:
        """Build a short human-readable summary for the activity log.

        Handles both raw journal events and Phase 2 ShipStateEvent payloads.

        Args:
            event_type: normalised event type string
            payload: ShipStateEvent payload dict (may be empty for journal events)
            raw: original event dict for journal-field fallback
        """
        # Phase 2 broadcaster event types
        if event_type == "FSD_JUMP":
            return f"Jump → {payload.get('system', raw.get('StarSystem', '?'))}"
        if event_type == "DOCKED":
            return f"Docked at {payload.get('station', raw.get('StationName', '?'))}"
        if event_type == "UNDOCKED":
            station = payload.get("station", raw.get("StationName", "?"))
            return f"Undocked from {station}"
        if event_type == "HULL_DAMAGE":
            hp = payload.get("hull_health")
            return f"Hull damage → {hp:.1f}%" if hp is not None else "Hull damage"
        if event_type in ("HULL_CRITICAL_25", "HULL_CRITICAL_10"):
            hp = payload.get("hull_health")
            threshold = "25%" if "25" in event_type else "10%"
            if hp is not None:
                return f"Hull critical ({threshold}) → {hp:.1f}%"
            return f"Hull critical ({threshold})"
        if event_type == "SHIELDS_DOWN":
            return "Shields down"
        if event_type == "SHIELDS_UP":
            return "Shields restored"
        if event_type == "FUEL_LOW":
            pct = payload.get("fuel_pct")
            return f"Fuel low → {pct:.1f}%" if pct is not None else "Fuel low"
        if event_type == "FUEL_CRITICAL":
            pct = payload.get("fuel_pct")
            return f"Fuel critical → {pct:.1f}%" if pct is not None else "Fuel critical"
        if event_type == "HEAT_WARNING":
            heat = payload.get("heat")
            return (
                f"Heat warning → {heat * 100:.0f}%"
                if heat is not None
                else "Heat warning"
            )
        if event_type == "PIPS_CHANGED":
            sys = payload.get("sys_pips", "?")
            eng = payload.get("eng_pips", "?")
            wep = payload.get("wep_pips", "?")
            return f"Pips → SYS:{sys} ENG:{eng} WEP:{wep}"
        if event_type == "SHIP_STATE_CHANGED":
            ship = payload.get("ship_type", raw.get("Ship", "?"))
            return f"Ship state → {ship}"
        if event_type == "LOADOUT_CHANGED":
            return f"Loadout → {payload.get('ship_type', '?')}"
        if event_type == "CARGO_CHANGED":
            count = payload.get("cargo_count")
            return f"Cargo → {count} units" if count is not None else "Cargo changed"
        if event_type == "MODULE_DAMAGED":
            slot = payload.get("slot", "?")
            hp = payload.get("health_pct", "")
            return f"Module damaged: {slot} {hp}"
        if event_type == "MODULE_CRITICAL":
            return f"Module critical: {payload.get('slot', '?')}"
        if event_type == "WANTED":
            return f"Wanted in {payload.get('system', '?')}"
        if event_type == "DESTROYED":
            return "Ship destroyed"
        if event_type == "RESERVOIR_REPLENISHED":
            return "Fuel reservoir replenished"
        if event_type == COMBAT_STATE_CHANGED:
            return "Combat state changed"
        if event_type == COMBAT_SESSION_STATE_CHANGED:
            return "Combat session state changed"
        if event_type == BRIEFING_EVENT:
            return f"Galactic Intelligence briefing: {payload.get('title', '?')}"
        if event_type == CLEARED_EVENT:
            return "Galactic Intelligence cleared for a forgotten commander"
        if event_type == commander_chronicle.RECORDED_EVENT:
            return "Commander Chronicle updated"
        if event_type == commander_chronicle.CLEARED_EVENT:
            return "Commander Chronicle cleared for a forgotten commander"

        # Raw journal event fallbacks
        if event_type == "FSDJump":
            return f"Jump → {raw.get('StarSystem', '?')}"
        if event_type == "HullDamage":
            hp = raw.get("Health", 0.0)
            return f"Hull damage → {float(hp) * 100:.1f}%"
        if event_type == "Status":
            return "Status update"

        return str(event_type)

    async def start(self) -> None:
        """Launch the uvicorn server in the background."""
        await self.notification_shadow.start()
        import uvicorn

        config = uvicorn.Config(
            app=self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)

        async def run() -> None:
            await server.serve()

        self._server_task = asyncio.create_task(run())
        self._started_at = time.monotonic()

        for _ in range(50):
            await asyncio.sleep(0.1)
            if server.started:
                self._ready_event.set()
                logger.info("ApiBridge ready at http://%s:%d", self._host, self._port)
                return

        logger.error("ApiBridge failed to start within 5s")

    async def wait_until_ready(self, timeout: float = 5.0) -> bool:
        """Block until the server has bound, or timeout expires."""
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def stop(self) -> None:
        """Stop the server gracefully."""
        await self.notification_shadow.stop()
        if self._server_task is not None:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None
            logger.info("ApiBridge stopped.")

    @property
    def activity_log(self) -> list[dict[str, Any]]:
        """Read-only view of the activity log ring buffer."""
        return list(self._activity_log)
