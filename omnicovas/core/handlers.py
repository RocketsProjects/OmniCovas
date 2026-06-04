# omnicovas/core/handlers.py
"""
omnicovas.core.handlers

Journal and Status event handlers for Phase 1 + Phase 2.

These handlers update StateManager with source priority enforcement (Law 7).
Phase 2 adds the broadcaster parameter to make_handlers so Pillar 1 feature
handlers (ship_state.py, fuel.py, etc.) can publish ShipStateEvents.

Law 5 (Zero Hallucination):
    Handlers only write fields when the event actually contains them.
    Missing fields stay None -- never fabricated.

Law 7 (Telemetry Rigidity):
    Every update declares its source. StateManager enforces priority.

See: Phase 1 Development Guide Week 2, Part B
See: Phase 2 Development Guide Week 7, Part B (broadcaster wiring)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.api import week13
from omnicovas.core.activity_log import (
    ActivityEntry,
    ActivityLog,
    normalize_phase9_payload,
)
from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import (
    COMBAT_RANK_UPDATED,
    COMBAT_REWARD_SUMMARY_UPDATED,
    INTERDICTION_ENDED,
    INTERDICTION_STARTED,
    LOCAL_CONFLICT_CONTEXT_UPDATED,
    MISSION_ABANDONED,
    MISSION_ADDED,
    MISSION_COMPLETED,
    MISSION_FAILED,
    MISSION_REDIRECTED,
    MISSION_SNAPSHOT_LOADED,
    PHASE_9_BGS_FACTS_PROJECTED,
    PHASE_9_POWERPLAY_FACTS_PROJECTED,
    SHIELDS_DOWN,
)
from omnicovas.core.state_manager import StateManager, TelemetrySource
from omnicovas.features import (
    combat_session,
    combat_state,
    local_context_facts,
    pvp_encounter,
)

logger = logging.getLogger(__name__)

_CRITICAL_HULL_THRESHOLD = 0.10  # Matches hull_triggers 10% critical threshold.
_CRITICAL_RESPONSE_SUGGESTION_TEXT = (
    "Critical hull damage during active interdiction. Review emergency response."
)
_CRITICAL_RESPONSE_WHY_TEXT = (
    "Source: local telemetry. Hull health is at or below the existing 10% critical "
    "threshold while interdiction is active. Confirmation records commander review "
    "only; no game action will be executed."
)


def make_handlers(
    state: StateManager,
    broadcaster: ShipStateBroadcaster | None = None,
    activity_log: ActivityLog | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict[str, Any]:
    """
    Build the set of handler coroutines bound to a StateManager instance.

    Using a factory avoids global state and makes handlers testable in
    isolation. The broadcaster and activity_log parameters are optional so
    Phase 1 tests that call make_handlers(state) without them continue to
    work -- they just won't publish events or write Activity Log entries.

    Args:
        state: The StateManager to update when events arrive.
        broadcaster: The ShipStateBroadcaster to publish derived events to.
                     None is acceptable during Phase 1 tests; Phase 2 feature
                     handlers must always receive a real broadcaster via main().
        activity_log: The ActivityLog to append entries to. None is acceptable;
                      no Activity Log writes occur when None.
        session_factory: Optional session factory for DB-backed feature logic
                         (e.g., E1B PvP journal auto-create).

    Returns:
        Dict mapping journal event type string -> async handler coroutine.
    """
    critical_response_proposal_id: str | None = None

    if activity_log is not None:
        week13.set_activity_log(activity_log)

    def _clear_critical_response_guard() -> None:
        nonlocal critical_response_proposal_id
        critical_response_proposal_id = None

    def _maybe_enqueue_critical_response_proposal(ts: str | None) -> None:
        nonlocal critical_response_proposal_id
        if critical_response_proposal_id is not None:
            return
        if state.snapshot.combat.workflow.interdiction_active.value is not True:
            return

        hull_health = state.snapshot.hull_health
        if hull_health is None or hull_health > _CRITICAL_HULL_THRESHOLD:
            return

        critical_response_proposal_id = week13.enqueue_confirmation(
            suggestion_text=_CRITICAL_RESPONSE_SUGGESTION_TEXT,
            why_text=_CRITICAL_RESPONSE_WHY_TEXT,
            action_type=week13.CRITICAL_RESPONSE_ACTION_TYPE,
            metadata={
                "trigger": "BeingInterdicted",
                "hull_health": hull_health,
                "threshold": _CRITICAL_HULL_THRESHOLD,
                "timestamp": ts,
            },
        )

    def _phase9_local_journal_source_chain(
        *, workflow_type: str, source_event: object, timestamp: object
    ) -> list[dict[str, Any]]:
        return [
            {
                "source": "Journal",
                "source_type": "local_event_history",
                "source_event": str(source_event or "Unknown"),
                "workflow_type": workflow_type,
                "timestamp": str(timestamp or ""),
                "truth_class": "local_event_history",
                "freshness": "last_known",
            }
        ]

    def _phase9_projected_field_names(event: dict[str, Any]) -> list[str]:
        return sorted(
            str(key)
            for key in event
            if key not in {"event", "timestamp"}
            and not str(key).lower().endswith("_localised")
        )

    async def _clear_interdiction_at_boundary(
        event: dict[str, Any], ts: str | None
    ) -> None:
        update = combat_state.record_interdiction_boundary_clear(event, state)
        await combat_state.publish_update(update, broadcaster)
        if update is not None:
            _clear_critical_response_guard()
        if update is not None and broadcaster is not None:
            await broadcaster.publish(
                INTERDICTION_ENDED,
                ShipStateEvent.now(
                    INTERDICTION_ENDED,
                    {"escape_outcome": "unknown", "reason": "session_boundary"},
                    source="journal",
                ),
            )
        if update is not None and activity_log is not None:
            activity_log.append(
                ActivityEntry(
                    event_type=INTERDICTION_ENDED,
                    timestamp=str(ts or ""),
                    summary="Interdiction cleared at session boundary",
                )
            )

    async def _publish_combat_session_change(reason: str) -> None:
        await combat_session.publish_session_state_changed(state, broadcaster, reason)

    async def _publish_phase9_bgs_projection(event: dict[str, Any]) -> None:
        ts = event.get("timestamp")
        source_event = event.get("event")
        if broadcaster is not None:
            await broadcaster.publish(
                PHASE_9_BGS_FACTS_PROJECTED,
                ShipStateEvent.now(
                    PHASE_9_BGS_FACTS_PROJECTED,
                    {
                        "source_event": source_event,
                        "timestamp": ts,
                        "source": "journal",
                    },
                    source="journal",
                ),
            )
        if activity_log is not None:
            source_chain = _phase9_local_journal_source_chain(
                workflow_type="bgs",
                source_event=source_event,
                timestamp=ts,
            )
            projected_fields = _phase9_projected_field_names(event)
            activity_log.append(
                ActivityEntry(
                    event_type=PHASE_9_BGS_FACTS_PROJECTED,
                    timestamp=str(ts or ""),
                    summary="Phase 9 BGS facts projected from local Journal",
                    payload=normalize_phase9_payload(
                        {
                            "workflow_type": "bgs",
                            "source_chain": source_chain,
                            "source_type": "local_event_history",
                            "source_label": "Journal",
                            "projected_fields": projected_fields,
                            "field_count": len(projected_fields),
                        }
                    ),
                    source_chain=source_chain,
                    redaction_state="redacted",
                    is_fact=True,
                    source="local_event_history",
                )
            )

    async def _publish_phase9_powerplay_projection(event: dict[str, Any]) -> None:
        ts = event.get("timestamp")
        source_event = event.get("event")
        if broadcaster is not None:
            await broadcaster.publish(
                PHASE_9_POWERPLAY_FACTS_PROJECTED,
                ShipStateEvent.now(
                    PHASE_9_POWERPLAY_FACTS_PROJECTED,
                    {
                        "source_event": source_event,
                        "timestamp": ts,
                        "source": "journal",
                    },
                    source="journal",
                ),
            )
        if activity_log is not None:
            source_chain = _phase9_local_journal_source_chain(
                workflow_type="powerplay",
                source_event=source_event,
                timestamp=ts,
            )
            projected_fields = _phase9_projected_field_names(event)
            activity_log.append(
                ActivityEntry(
                    event_type=PHASE_9_POWERPLAY_FACTS_PROJECTED,
                    timestamp=str(ts or ""),
                    summary="Phase 9 Powerplay facts projected from local Journal",
                    payload=normalize_phase9_payload(
                        {
                            "workflow_type": "powerplay",
                            "source_chain": source_chain,
                            "source_type": "local_event_history",
                            "source_label": "Journal",
                            "projected_fields": projected_fields,
                            "field_count": len(projected_fields),
                            "is_fact_source": True,
                        }
                    ),
                    source_chain=source_chain,
                    redaction_state="redacted",
                    is_fact=True,
                    source="local_event_history",
                )
            )

    def _has_phase9_system_bgs_fields(event: dict[str, Any]) -> bool:
        return isinstance(event.get("SystemFaction"), dict) or isinstance(
            event.get("Factions"), list
        )

    def _has_phase9_station_bgs_fields(event: dict[str, Any]) -> bool:
        return isinstance(event.get("StationFaction"), dict)

    async def _record_local_conflict_from_event(
        event: dict[str, Any], reason: str
    ) -> None:
        if not combat_session.record_local_conflict_context(event, state):
            return
        await _publish_combat_session_change(reason)
        if activity_log is not None:
            ts = event.get("timestamp")
            value = state.snapshot.combat.cz_missions.local_conflict_context.value
            summary = (
                f"Local conflict context updated: {value}"
                if value
                else "Local conflict context cleared"
            )
            activity_log.append(
                ActivityEntry(
                    event_type=LOCAL_CONFLICT_CONTEXT_UPDATED,
                    timestamp=str(ts or ""),
                    summary=summary,
                )
            )

    async def handle_fsd_jump(event: dict[str, Any]) -> None:
        """Handle FSDJump -- commander jumped to a new system."""
        system = event.get("StarSystem")
        ts = event.get("timestamp")
        if system is not None:
            state.update_field("current_system", system, TelemetrySource.JOURNAL, ts)
            state.update_field("is_in_supercruise", True, TelemetrySource.JOURNAL, ts)
        # Phase 6 extension: preserve field-rich system context alongside the
        # scalar current_system (SystemGovernment/Security/Allegiance/Economy
        # /Population/StarPos/Factions/Conflicts). Separate from the scalar
        # update above to preserve PB04-06 F1 ownership semantics.
        system_context_changed = state.update_field(
            "local_system_context",
            local_context_facts.build_local_system_context(
                event, source_event="FSDJump"
            ),
            TelemetrySource.JOURNAL,
            ts,
        )
        if system_context_changed and _has_phase9_system_bgs_fields(event):
            await _publish_phase9_bgs_projection(event)
        await combat_state.publish_update(
            combat_state.record_session_boundary(event, state),
            broadcaster,
        )
        await _clear_interdiction_at_boundary(event, ts)
        # PB04-06 F1: read Conflicts[] only; do NOT touch system/station/BGS state
        await _record_local_conflict_from_event(event, "FSDJump")
        logger.info("[STATE] FSDJump -> %s", system or "Unknown")
        print(f"[EVENT] FSDJump -> {system or 'Unknown'}")

    async def handle_carrier_jump(event: dict[str, Any]) -> None:
        """Handle CarrierJump -- commander's fleet carrier jumped to a new system.

        Mirrors the FSDJump local_system_context update without clearing station
        context (commander may remain docked aboard the carrier) and without
        setting is_in_supercruise (carrier transit is not normal supercruise).
        """
        system = event.get("StarSystem")
        ts = event.get("timestamp")
        if system is not None:
            state.update_field("current_system", system, TelemetrySource.JOURNAL, ts)
        state.update_field(
            "local_system_context",
            local_context_facts.build_local_system_context(
                event, source_event="CarrierJump"
            ),
            TelemetrySource.JOURNAL,
            ts,
        )
        logger.info("[STATE] CarrierJump -> %s", system or "Unknown")

    async def handle_location(event: dict[str, Any]) -> None:
        """Handle Location -- login/entry journal context.

        Location is source-backed journal evidence for last-known system,
        station, and docked state. It also carries Conflicts[] for the combat
        context. FSDJump/Docked/Undocked still update the same fields when
        those explicit transition events are present.
        """
        await _record_local_conflict_from_event(event, "Location")
        ts = event.get("timestamp")
        system = event.get("StarSystem")
        station = event.get("StationName")
        bgs_context_changed = False
        if system is not None:
            state.update_field("current_system", system, TelemetrySource.JOURNAL, ts)
        docked = event.get("Docked")
        if docked is True:
            state.update_field("is_docked", True, TelemetrySource.JOURNAL, ts)
            state.update_field("is_in_supercruise", False, TelemetrySource.JOURNAL, ts)
            if station is not None:
                state.update_field(
                    "current_station", station, TelemetrySource.JOURNAL, ts
                )
            station_context_changed = state.update_field(
                "local_station_context",
                local_context_facts.build_local_station_context(
                    event, source_event="Location"
                ),
                TelemetrySource.JOURNAL,
                ts,
            )
            bgs_context_changed = (
                station_context_changed and _has_phase9_station_bgs_fields(event)
            )
        elif docked is False:
            state.update_field("is_docked", False, TelemetrySource.JOURNAL, ts)
            state.update_field("current_station", None, TelemetrySource.JOURNAL, ts)
            state.update_field(
                "local_station_context",
                None,
                TelemetrySource.JOURNAL,
                ts,
            )
        existing_system_ctx = state.snapshot.local_system_context
        if local_context_facts.should_apply_location_system_context(
            existing_system_ctx, event
        ):
            system_context_changed = state.update_field(
                "local_system_context",
                local_context_facts.build_local_system_context(
                    event, source_event="Location"
                ),
                TelemetrySource.JOURNAL,
                ts,
            )
            bgs_context_changed = bgs_context_changed or (
                system_context_changed and _has_phase9_system_bgs_fields(event)
            )
        if bgs_context_changed:
            await _publish_phase9_bgs_projection(event)
        logger.debug("[STATE] Location -> conflicts processed")

    async def handle_docked(event: dict[str, Any]) -> None:
        """Handle Docked -- commander docked at a station."""
        station = event.get("StationName")
        system = event.get("StarSystem")
        ts = event.get("timestamp")
        state.update_field("is_docked", True, TelemetrySource.JOURNAL, ts)
        state.update_field("is_in_supercruise", False, TelemetrySource.JOURNAL, ts)
        if station is not None:
            state.update_field("current_station", station, TelemetrySource.JOURNAL, ts)
        if system is not None:
            state.update_field("current_system", system, TelemetrySource.JOURNAL, ts)
        # Phase 6 extension: preserve field-rich station context with
        # StationServices, StationEconomies, LandingPads, StationFaction,
        # StationGovernment, StationAllegiance, StationEconomy, DistFromStarLS.
        station_context_changed = state.update_field(
            "local_station_context",
            local_context_facts.build_local_station_context(
                event, source_event="Docked"
            ),
            TelemetrySource.JOURNAL,
            ts,
        )
        if station_context_changed and _has_phase9_station_bgs_fields(event):
            await _publish_phase9_bgs_projection(event)
        await combat_state.publish_update(
            combat_state.record_session_boundary(event, state),
            broadcaster,
        )
        await _clear_interdiction_at_boundary(event, ts)
        logger.info(
            "[STATE] Docked -> %s in %s",
            station or "Unknown",
            system or "Unknown",
        )
        print(f"[EVENT] Docked -> {station or 'Unknown'} in {system or 'Unknown'}")

    async def handle_undocked(event: dict[str, Any]) -> None:
        """Handle Undocked -- commander left a station."""
        station = event.get("StationName")
        ts = event.get("timestamp")
        state.update_field("is_docked", False, TelemetrySource.JOURNAL, ts)
        state.update_field("current_station", None, TelemetrySource.JOURNAL, ts)
        # Phase 6 extension: invalidate the field-rich station context to
        # match scalar current_station=None semantics. Freshness against any
        # subsequent Market.json read will then surface as "stale" / not
        # bound to a live station.
        state.update_field(
            "local_station_context",
            None,
            TelemetrySource.JOURNAL,
            ts,
        )
        logger.info("[STATE] Undocked from %s", station or "Unknown")
        print(f"[EVENT] Undocked from {station or 'Unknown'}")

    async def handle_hull_damage(event: dict[str, Any]) -> None:
        """Handle HullDamage -- ship took hull damage.

        The journal HullDamage.Health field is 0.0-1.0 (NOT percent).
        We store it as-is. Week 9 Hull Triggers compare against 0.0-1.0 KB thresholds.
        Do not multiply by 100 here -- only multiply for display purposes.
        """
        health = event.get("Health")
        ts = event.get("timestamp")
        if health is not None:
            state.update_field(
                "hull_health", float(health), TelemetrySource.JOURNAL, ts
            )
        await combat_state.publish_update(
            combat_state.record_hull_damage(event, state),
            broadcaster,
        )
        logger.info(
            "[STATE] HullDamage -> hull at %.1f%%",
            (health or 0.0) * 100,
        )
        print(f"[EVENT] HullDamage -> hull at {(health or 0.0) * 100:.1f}%")

    async def handle_ship_targeted(event: dict[str, Any]) -> None:
        """Handle ShipTargeted -- commander targeted another ship."""
        ship = event.get("Ship")
        pilot_name = event.get("PilotName_Localised") or event.get("PilotName")
        ts = event.get("timestamp")
        if ship is not None:
            state.update_field("target_ship", ship, TelemetrySource.JOURNAL, ts)
        if pilot_name is not None:
            state.update_field("target_cmdr", pilot_name, TelemetrySource.JOURNAL, ts)
        await combat_state.publish_update(
            combat_state.record_ship_targeted(event, state),
            broadcaster,
        )
        logger.info("[STATE] ShipTargeted -> %s", ship or "Unknown")
        print(f"[EVENT] ShipTargeted -> {ship or 'Unknown'}")

    async def handle_docking_granted(event: dict[str, Any]) -> None:
        """Handle DockingGranted -- docking request approved."""
        station = event.get("StationName")
        logger.info("[STATE] DockingGranted -> %s", station or "Unknown")
        print(f"[EVENT] DockingGranted -> {station or 'Unknown'}")

    async def handle_status(event: dict[str, Any]) -> None:
        """Handle Status -- synthetic event from Status.json poll.

        Status.json provides fuel data mapped to our dual-field structure.
        """
        flags = event.get("Flags", 0)
        fuel: dict[str, Any] | None = event.get("Fuel")
        pips = event.get("Pips")
        ts = event.get("timestamp")
        balance = event.get("Balance")

        # Fuel: only update if Fuel object is present (Law 5 — Zero Hallucination)
        if fuel is not None:
            fuel_main = fuel.get("FuelMain")
            fuel_reservoir = fuel.get("FuelReservoir")

            if fuel_main is not None:
                state.update_field(
                    "fuel_main", float(fuel_main), TelemetrySource.STATUS_JSON, ts
                )
            if fuel_reservoir is not None:
                state.update_field(
                    "fuel_reservoir",
                    float(fuel_reservoir),
                    TelemetrySource.STATUS_JSON,
                    ts,
                )

        # Heat is 0.0-1.0+ from Status.json.
        # Only update if present in event (Law 5 — Zero Hallucination).
        heat = event.get("Heat")
        if heat is not None:
            state.update_field(
                "heat_level", float(heat), TelemetrySource.STATUS_JSON, ts
            )

        # Flags bit 3 is "Shields Up"
        SHIELDS_UP = 1 << 3
        state.update_field(
            "shield_up", bool(flags & SHIELDS_UP), TelemetrySource.STATUS_JSON, ts
        )

        # Flags bit 0 is "Docked"
        DOCKED = 1 << 0
        state.update_field(
            "is_docked", bool(flags & DOCKED), TelemetrySource.STATUS_JSON, ts
        )

        # Pips: [SYS, ENG, WEP] list. Absent when on-foot (Odyssey).
        # Only update if present and valid (Law 5 — Zero Hallucination).
        if isinstance(pips, list) and len(pips) == 3:
            state.update_field(
                "sys_pips", int(pips[0]), TelemetrySource.STATUS_JSON, ts
            )
            state.update_field(
                "eng_pips", int(pips[1]), TelemetrySource.STATUS_JSON, ts
            )
            state.update_field(
                "wep_pips", int(pips[2]), TelemetrySource.STATUS_JSON, ts
            )

        if isinstance(balance, (int, float)) and not isinstance(balance, bool):
            state.update_field(
                "credit_balance", int(balance), TelemetrySource.STATUS_JSON, ts
            )

        sub_events = event.get("SubEvents", [])
        logger.debug(
            "[STATE] Status -> flags=0x%x heat=%s fuel=%s subs=%s",
            flags,
            heat,
            state.snapshot.fuel_main,
            sub_events,
        )

    async def handle_fuel_low(event: dict[str, Any]) -> None:
        """Handle FuelLow -- synthetic sub-event from Status.json."""
        logger.warning("[STATE] FuelLow -> fuel dropped below 25%%")
        print("[EVENT] WARNING FuelLow -> fuel dropped below 25%")

    async def handle_heat_warning(event: dict[str, Any]) -> None:
        """Handle HeatWarning -- synthetic sub-event from Status.json."""
        logger.warning("[STATE] HeatWarning -> heat rising above 75%%")
        print("[EVENT] WARNING HeatWarning -> heat rising above 75%")

    async def handle_shield_down(event: dict[str, Any]) -> None:
        """Handle ShieldDown -- synthetic sub-event from Status.json."""
        ts = event.get("timestamp")
        state.update_field("shield_up", False, TelemetrySource.STATUS_JSON, ts)
        logger.warning("[STATE] ShieldDown -> shields collapsed")
        print("[EVENT] WARNING ShieldDown -> shields collapsed")
        if broadcaster is not None:
            await broadcaster.publish(
                SHIELDS_DOWN,
                ShipStateEvent.now(
                    SHIELDS_DOWN,
                    {"shields_down": True},
                    source="status_json",
                ),
            )

    async def handle_pips_changed(event: dict[str, Any]) -> None:
        """Handle PipsChanged -- synthetic sub-event from Status.json."""
        logger.debug("[STATE] PipsChanged")

    async def handle_being_interdicted(event: dict[str, Any]) -> None:
        """Handle BeingInterdicted -- Status.json Flags bit 23 rising edge."""
        ts = event.get("timestamp")
        update = combat_state.record_interdiction_started(event, state)
        await combat_state.publish_update(update, broadcaster)
        if update is not None and broadcaster is not None:
            await broadcaster.publish(
                INTERDICTION_STARTED,
                ShipStateEvent.now(
                    INTERDICTION_STARTED,
                    {"interdiction_active": True},
                    source="status",
                ),
            )
        if update is not None and activity_log is not None:
            activity_log.append(
                ActivityEntry(
                    event_type=INTERDICTION_STARTED,
                    timestamp=str(ts or ""),
                    summary="Interdiction detected via Status.json",
                )
            )
        if update is not None:
            _maybe_enqueue_critical_response_proposal(
                str(ts) if ts is not None else None
            )
        logger.warning("[STATE] BeingInterdicted -> interdiction active")
        print("[EVENT] WARNING BeingInterdicted -> interdiction active")

    async def _maybe_record_pvp_encounter(event: dict[str, Any]) -> None:
        if session_factory is None:
            return

        is_player = event.get("IsPlayer")
        interdictor = event.get("Interdictor")
        ts_str = event.get("timestamp")

        if is_player is not True:
            return
        if not isinstance(interdictor, str) or not interdictor.strip():
            return

        ts = None
        if ts_str:
            try:
                # Journal timestamps are usually "YYYY-MM-DDTHH:MM:SSZ"
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except ValueError:
                logger.warning(
                    "Failed to parse event timestamp for PvP record: %s", ts_str
                )

        try:
            await pvp_encounter.ensure_journal_pvp_encounter(
                session_factory,
                pvp_encounter.PvpEncounterCreate(
                    timestamp=ts,
                    commander_name=interdictor,
                    system=state.snapshot.current_system,
                    source_label="journal",
                    encounter_type="interdicted_by",
                    note="Local journal PvP encounter.",
                    risk_explanation=(
                        "Local journal encounter only. No global "
                        "reputation or external lookup."
                    ),
                    provenance_event_type=str(event.get("event")),
                ),
                activity_log=activity_log,
            )
        except Exception:
            # Law 6: Handler exceptions are caught and logged — never crash the loop.
            # We follow the existing handler style: catch-all for DB ops to ensure
            # combat workflow (state manager/broadcaster) is never blocked by DB.
            logger.exception("Failed to auto-create PvP encounter from journal")

    async def handle_escape_interdiction(event: dict[str, Any]) -> None:
        """Handle EscapeInterdiction -- commander escaped the supercruise pull."""
        ts = event.get("timestamp")
        update = combat_state.record_interdiction_ended(event, state, "escaped")
        await combat_state.publish_update(update, broadcaster)
        if broadcaster is not None:
            await broadcaster.publish(
                INTERDICTION_ENDED,
                ShipStateEvent.now(
                    INTERDICTION_ENDED,
                    {"escape_outcome": "escaped"},
                    source="journal",
                ),
            )
        if activity_log is not None:
            activity_log.append(
                ActivityEntry(
                    event_type=INTERDICTION_ENDED,
                    timestamp=str(ts or ""),
                    summary="Interdiction ended — escaped",
                )
            )
        _clear_critical_response_guard()
        logger.info("[STATE] EscapeInterdiction -> escaped")
        print("[EVENT] EscapeInterdiction -> escaped")

        # E1B: PvP journal auto-create
        await _maybe_record_pvp_encounter(event)

    async def handle_interdicted(event: dict[str, Any]) -> None:
        """Handle Interdicted -- commander was pulled from supercruise."""
        ts = event.get("timestamp")
        submitted = bool(event.get("Submitted", False))
        escape_outcome = "submitted" if submitted else "unknown"
        update = combat_state.record_interdiction_ended(event, state, escape_outcome)
        await combat_state.publish_update(update, broadcaster)
        if broadcaster is not None:
            await broadcaster.publish(
                INTERDICTION_ENDED,
                ShipStateEvent.now(
                    INTERDICTION_ENDED,
                    {"escape_outcome": escape_outcome},
                    source="journal",
                ),
            )
        if activity_log is not None:
            activity_log.append(
                ActivityEntry(
                    event_type=INTERDICTION_ENDED,
                    timestamp=str(ts or ""),
                    summary="Interdiction ended — submitted"
                    if submitted
                    else "Interdiction ended — unknown outcome",
                )
            )
        _clear_critical_response_guard()
        logger.info("[STATE] Interdicted -> submitted=%s", submitted)
        print(f"[EVENT] Interdicted -> submitted={submitted}")

        # E1B: PvP journal auto-create
        await _maybe_record_pvp_encounter(event)

    # ----- PB04-06 F1: Mission session handlers -----------------------------

    async def handle_missions(event: dict[str, Any]) -> None:
        """Handle Missions startup snapshot -- load Active[] into state.

        Active[] presence is a snapshot, not proof a session 'started';
        Activity Log records MISSION_SNAPSHOT_LOADED for that reason.
        """
        ts = event.get("timestamp")
        if not combat_session.record_missions_snapshot(event, state):
            return
        await _publish_combat_session_change("Missions")
        if activity_log is not None:
            count = len(state.snapshot.combat.active_missions)
            activity_log.append(
                ActivityEntry(
                    event_type=MISSION_SNAPSHOT_LOADED,
                    timestamp=str(ts or ""),
                    summary=f"Mission snapshot loaded: {count} active",
                )
            )
        logger.info(
            "[STATE] Missions snapshot -> %d active",
            len(state.snapshot.combat.active_missions),
        )

    async def handle_mission_accepted(event: dict[str, Any]) -> None:
        """Handle MissionAccepted -- append CombatMissionEntry."""
        ts = event.get("timestamp")
        if not combat_session.record_mission_accepted(event, state):
            return
        await _publish_combat_session_change("MissionAccepted")
        if activity_log is not None:
            mission_id = event.get("MissionID")
            activity_log.append(
                ActivityEntry(
                    event_type=MISSION_ADDED,
                    timestamp=str(ts or ""),
                    summary=f"Mission added (id={mission_id})",
                )
            )
        logger.info("[STATE] MissionAccepted -> id=%s", event.get("MissionID"))

    async def handle_mission_completed(event: dict[str, Any]) -> None:
        """Handle MissionCompleted -- mark complete and remove.

        MissionCompleted.Reward is intentionally NOT counted as a combat
        reward total. Combat reward totals derive only from RedeemVoucher.
        """
        ts = event.get("timestamp")
        bgs_changed = local_context_facts.record_phase9_bgs_mission_effects(
            event, state
        )
        if not combat_session.record_mission_completed(event, state):
            logger.debug(
                "MissionCompleted: no matching active mission for id=%s",
                event.get("MissionID"),
            )
            if bgs_changed:
                await _publish_phase9_bgs_projection(event)
            return
        await _publish_combat_session_change("MissionCompleted")
        if activity_log is not None:
            mission_id = event.get("MissionID")
            activity_log.append(
                ActivityEntry(
                    event_type=MISSION_COMPLETED,
                    timestamp=str(ts or ""),
                    summary=f"Mission completed (id={mission_id})",
                )
            )
        if bgs_changed:
            await _publish_phase9_bgs_projection(event)
        logger.info("[STATE] MissionCompleted -> id=%s", event.get("MissionID"))

    async def handle_mission_failed(event: dict[str, Any]) -> None:
        """Handle MissionFailed -- mark failed and remove."""
        ts = event.get("timestamp")
        if not combat_session.record_mission_failed(event, state):
            logger.debug(
                "MissionFailed: no matching active mission for id=%s",
                event.get("MissionID"),
            )
            return
        await _publish_combat_session_change("MissionFailed")
        if activity_log is not None:
            mission_id = event.get("MissionID")
            activity_log.append(
                ActivityEntry(
                    event_type=MISSION_FAILED,
                    timestamp=str(ts or ""),
                    summary=f"Mission failed (id={mission_id})",
                )
            )
        logger.info("[STATE] MissionFailed -> id=%s", event.get("MissionID"))

    async def handle_mission_abandoned(event: dict[str, Any]) -> None:
        """Handle MissionAbandoned -- mark abandoned and remove."""
        ts = event.get("timestamp")
        if not combat_session.record_mission_abandoned(event, state):
            logger.debug(
                "MissionAbandoned: no matching active mission for id=%s",
                event.get("MissionID"),
            )
            return
        await _publish_combat_session_change("MissionAbandoned")
        if activity_log is not None:
            mission_id = event.get("MissionID")
            activity_log.append(
                ActivityEntry(
                    event_type=MISSION_ABANDONED,
                    timestamp=str(ts or ""),
                    summary=f"Mission abandoned (id={mission_id})",
                )
            )
        logger.info("[STATE] MissionAbandoned -> id=%s", event.get("MissionID"))

    async def handle_mission_redirected(event: dict[str, Any]) -> None:
        """Handle MissionRedirected -- update destination on matching entry."""
        ts = event.get("timestamp")
        if not combat_session.record_mission_redirected(event, state):
            return
        await _publish_combat_session_change("MissionRedirected")
        if activity_log is not None:
            mission_id = event.get("MissionID")
            activity_log.append(
                ActivityEntry(
                    event_type=MISSION_REDIRECTED,
                    timestamp=str(ts or ""),
                    summary=f"Mission redirected (id={mission_id})",
                )
            )
        logger.info("[STATE] MissionRedirected -> id=%s", event.get("MissionID"))

    # ----- PB04-06 F3: Rewards / Rank handlers ------------------------------

    async def handle_redeem_voucher(event: dict[str, Any]) -> None:
        """Handle RedeemVoucher Type=bounty / Type=CombatBond only.

        All other Types are silently ignored. MissionCompleted.Reward is
        never counted here.
        """
        ts = event.get("timestamp")
        voucher_type = event.get("Type")
        bgs_changed = local_context_facts.record_phase9_bgs_reward_event(event, state)
        if not combat_session.record_redeem_voucher(event, state):
            if bgs_changed:
                await _publish_phase9_bgs_projection(event)
            return
        await _publish_combat_session_change("RedeemVoucher")
        if activity_log is not None:
            activity_log.append(
                ActivityEntry(
                    event_type=COMBAT_REWARD_SUMMARY_UPDATED,
                    timestamp=str(ts or ""),
                    summary=f"Combat reward summary updated ({voucher_type})",
                )
            )
        if bgs_changed:
            await _publish_phase9_bgs_projection(event)
        logger.info("[STATE] RedeemVoucher -> type=%s", voucher_type)

    async def handle_bgs_reward_event(event: dict[str, Any]) -> None:
        """Handle local Bounty / FactionKillBond as PB09-02 BGS history."""
        if local_context_facts.record_phase9_bgs_reward_event(event, state):
            await _publish_phase9_bgs_projection(event)
        logger.info("[STATE] %s -> Phase 9 BGS reward history", event.get("event"))

    async def handle_powerplay_event(event: dict[str, Any]) -> None:
        """Handle supported local Powerplay journal events for PB09-02."""
        if local_context_facts.record_phase9_powerplay_event(event, state):
            await _publish_phase9_powerplay_projection(event)
        logger.info("[STATE] %s -> Phase 9 Powerplay history", event.get("event"))

    async def handle_rank(event: dict[str, Any]) -> None:
        """Handle Rank startup -- record latest observed combat rank."""
        if not combat_session.record_rank(event, state):
            return
        await _publish_combat_session_change("Rank")
        logger.info("[STATE] Rank -> combat=%s", event.get("Combat"))

    async def handle_progress(event: dict[str, Any]) -> None:
        """Handle Progress startup -- record latest observed rank progress."""
        if not combat_session.record_progress(event, state):
            return
        await _publish_combat_session_change("Progress")
        logger.info("[STATE] Progress -> combat=%s", event.get("Combat"))

    async def handle_promotion(event: dict[str, Any]) -> None:
        """Handle Promotion -- session combat rank change.

        Non-combat promotions are silently skipped (no Combat field).
        """
        ts = event.get("timestamp")
        if not combat_session.record_promotion(event, state):
            return
        await _publish_combat_session_change("Promotion")
        if activity_log is not None:
            new_rank = event.get("Combat")
            activity_log.append(
                ActivityEntry(
                    event_type=COMBAT_RANK_UPDATED,
                    timestamp=str(ts or ""),
                    summary=f"Combat rank updated to {new_rank}",
                )
            )
        logger.info("[STATE] Promotion -> combat=%s", event.get("Combat"))

    return {
        "FSDJump": handle_fsd_jump,
        "CarrierJump": handle_carrier_jump,
        "Location": handle_location,
        "Docked": handle_docked,
        "Undocked": handle_undocked,
        "HullDamage": handle_hull_damage,
        "ShipTargeted": handle_ship_targeted,
        "DockingGranted": handle_docking_granted,
        "Status": handle_status,
        "FuelLow": handle_fuel_low,
        "HeatWarning": handle_heat_warning,
        "ShieldDown": handle_shield_down,
        "PipsChanged": handle_pips_changed,
        "BeingInterdicted": handle_being_interdicted,
        "EscapeInterdiction": handle_escape_interdiction,
        "Interdicted": handle_interdicted,
        "Missions": handle_missions,
        "MissionAccepted": handle_mission_accepted,
        "MissionCompleted": handle_mission_completed,
        "MissionFailed": handle_mission_failed,
        "MissionAbandoned": handle_mission_abandoned,
        "MissionRedirected": handle_mission_redirected,
        "RedeemVoucher": handle_redeem_voucher,
        "Bounty": handle_bgs_reward_event,
        "FactionKillBond": handle_bgs_reward_event,
        "Powerplay": handle_powerplay_event,
        "PowerplayJoin": handle_powerplay_event,
        "PowerplayLeave": handle_powerplay_event,
        "PowerplayDefect": handle_powerplay_event,
        "PowerplaySalary": handle_powerplay_event,
        "PowerplayCollect": handle_powerplay_event,
        "PowerplayDeliver": handle_powerplay_event,
        "PowerplayFastTrack": handle_powerplay_event,
        "PowerplayVote": handle_powerplay_event,
        "PowerplayVoucher": handle_powerplay_event,
        "PowerplayMerits": handle_powerplay_event,
        "PowerplayRank": handle_powerplay_event,
        "RequestPowerMicroResources": handle_powerplay_event,
        "DeliverPowerMicroResources": handle_powerplay_event,
        "Rank": handle_rank,
        "Progress": handle_progress,
        "Promotion": handle_promotion,
    }
