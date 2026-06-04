"""Read-only Navigation snapshot helpers for PB05-04.

Navigation owns movement and routes only. This first-wave seam reads
NavRoute.json (companion JSON) from the local Elite Dangerous save directory.
No outbound calls. No AI. No second state manager.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.confirmation_gate import ActionType, ConfirmationGate
from omnicovas.core.provenance import FreshnessLabel, TruthClass
from omnicovas.core.state_manager import StateManager

logger = logging.getLogger(__name__)

_SOURCE_ID = "local_navroute"

# Accepted fallback wording from Source Capability Routing Reference v1
UNKNOWN = "Unknown"
NOT_LOADED = "Not Loaded"
NO_VERIFIED_SOURCE = "No Verified Source"

# Navigation gate lifecycle event type strings (defined locally — no core edit)
_ROUTE_ACTIVATION_PROPOSAL_CREATED = "ROUTE_ACTIVATION_PROPOSAL_CREATED"
_ROUTE_ACTIVATION_PROPOSAL_DECISION = "ROUTE_ACTIVATION_PROPOSAL_DECISION"


@dataclass(frozen=True)
class RouteHop:
    """Single hop in an active route sourced from NavRoute.json."""

    star_system: str
    star_class: str | None
    star_pos: tuple[float, float, float] | None

    def payload(self) -> dict[str, Any]:
        return {
            "star_system": self.star_system,
            "star_class": self.star_class,
            "star_pos": list(self.star_pos) if self.star_pos is not None else None,
        }


@dataclass(frozen=True)
class ActiveRouteState:
    """Current active route sourced from the NavRoute.json companion JSON.

    Navigation owns movement/routes. This shape does not carry Intel facts.
    nullprovider_safe is always True — no AI provider is required.
    """

    origin: str | None
    destination: str | None
    next_hop: str | None
    total_hops: int | None
    route_state: str
    hops: tuple[RouteHop, ...]
    freshness_label: FreshnessLabel
    truth_class: TruthClass
    source_id: str
    observed_at: datetime | None
    fallback: str | None
    caveat: str | None
    nullprovider_safe: bool = True

    def payload(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "next_hop": self.next_hop,
            "total_hops": self.total_hops,
            "route_state": self.route_state,
            "hops": [h.payload() for h in self.hops],
            "freshness_label": self.freshness_label.value,
            "truth_class": self.truth_class.value,
            "source_id": self.source_id,
            "observed_at": (
                self.observed_at.isoformat() if self.observed_at is not None else None
            ),
            "fallback": self.fallback,
            "caveat": self.caveat,
            "nullprovider_safe": self.nullprovider_safe,
        }


@dataclass(frozen=True)
class RouteCandidate:
    """Proposed route option — minimal first-wave shape for Phase 5."""

    source_id: str
    destination: str | None
    total_hops: int
    freshness_label: FreshnessLabel
    caveat: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "destination": self.destination,
            "total_hops": self.total_hops,
            "freshness_label": self.freshness_label.value,
            "caveat": self.caveat,
        }


@dataclass(frozen=True)
class RouteIntent:
    """Commander's intended route — gate proposal wrapper (review-only in PB05-04).

    Even when decision == 'approved', no in-game action is performed by this
    playbook. The accepted decision records Commander intent only.
    """

    workflow_id: str
    destination: str | None
    proposed_at: datetime
    active_route: ActiveRouteState
    caveat: str
    decision: str | None
    decision_recorded_at: datetime | None

    def payload(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "destination": self.destination,
            "proposed_at": self.proposed_at.isoformat(),
            "active_route": self.active_route.payload(),
            "caveat": self.caveat,
            "decision": self.decision,
            "decision_recorded_at": (
                self.decision_recorded_at.isoformat()
                if self.decision_recorded_at is not None
                else None
            ),
        }


@dataclass(frozen=True)
class NavigationSnapshot:
    """Read-only first-wave Navigation snapshot."""

    generated_at: datetime
    active_route: ActiveRouteState
    spansh_url: str | None
    current_system: str | None = None
    current_station: str | None = None
    nullprovider_safe: bool = True

    def payload(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "active_route": self.active_route.payload(),
            "spansh_url": self.spansh_url,
            "current_system": self.current_system,
            "current_station": self.current_station,
            "nullprovider_safe": self.nullprovider_safe,
        }


# ---------------------------------------------------------------------------
# NavRoute.json local reader
# ---------------------------------------------------------------------------


def _default_navroute_path() -> Path | None:
    """Try to discover NavRoute.json from the default Elite Dangerous save location.

    Local file access only. No outbound call.
    """
    profile = os.environ.get("USERPROFILE", "")
    if not profile:
        return None
    candidate = (
        Path(profile)
        / "Saved Games"
        / "Frontier Developments"
        / "Elite Dangerous"
        / "NavRoute.json"
    )
    return candidate if candidate.exists() else None


def read_navroute(navroute_path: Path | None = None) -> dict[str, Any] | None:
    """Read and parse NavRoute.json from the given path.

    Falls back to the default Elite Dangerous save location when path is None.
    Returns None if the file is missing, unreadable, or not valid JSON.
    No outbound call. No exception propagated to caller.
    """
    path = navroute_path
    if path is None:
        path = _default_navroute_path()
    if path is None or not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return data
    except Exception as exc:
        logger.debug("NavRoute.json read failed: %s", exc)
        return None


def _parse_hop(raw: dict[str, Any]) -> RouteHop | None:
    star_system = raw.get("StarSystem")
    if not isinstance(star_system, str) or not star_system:
        return None
    star_class = raw.get("StarClass")
    if not isinstance(star_class, str):
        star_class = None
    raw_pos = raw.get("StarPos")
    star_pos: tuple[float, float, float] | None = None
    if isinstance(raw_pos, list) and len(raw_pos) == 3:
        try:
            star_pos = (float(raw_pos[0]), float(raw_pos[1]), float(raw_pos[2]))
        except (TypeError, ValueError):
            star_pos = None
    return RouteHop(star_system=star_system, star_class=star_class, star_pos=star_pos)


def _parse_navroute_timestamp(data: dict[str, Any]) -> datetime | None:
    ts = data.get("timestamp")
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Snapshot builders
# ---------------------------------------------------------------------------


def build_active_route(navroute_data: dict[str, Any] | None) -> ActiveRouteState:
    """Build ActiveRouteState from parsed NavRoute.json data.

    Returns an honest fallback state when data is None or empty.
    """
    if navroute_data is None:
        return ActiveRouteState(
            origin=None,
            destination=None,
            next_hop=None,
            total_hops=None,
            route_state="not_loaded",
            hops=(),
            freshness_label=FreshnessLabel.UNKNOWN_FRESHNESS,
            truth_class=TruthClass.UNKNOWN,
            source_id=_SOURCE_ID,
            observed_at=None,
            fallback=NOT_LOADED,
            caveat="NavRoute.json not found",
        )

    raw_route = navroute_data.get("Route")
    if not isinstance(raw_route, list) or len(raw_route) == 0:
        return ActiveRouteState(
            origin=None,
            destination=None,
            next_hop=None,
            total_hops=None,
            route_state="no_route",
            hops=(),
            freshness_label=FreshnessLabel.LOCAL_ONLY,
            truth_class=TruthClass.LOCAL_TELEMETRY,
            source_id=_SOURCE_ID,
            observed_at=_parse_navroute_timestamp(navroute_data),
            fallback="No route plotted",
            caveat="Route array is empty — no active route in NavRoute.json",
        )

    hops: list[RouteHop] = []
    for raw_hop in raw_route:
        if isinstance(raw_hop, dict):
            hop = _parse_hop(raw_hop)
            if hop is not None:
                hops.append(hop)

    origin = hops[0].star_system if hops else None
    if len(hops) < 2:
        return ActiveRouteState(
            origin=None,
            destination=None,
            next_hop=None,
            total_hops=None,
            route_state="no_route",
            hops=(),
            freshness_label=FreshnessLabel.LOCAL_ONLY,
            truth_class=TruthClass.LOCAL_TELEMETRY,
            source_id=_SOURCE_ID,
            observed_at=_parse_navroute_timestamp(navroute_data),
            fallback="No route plotted",
            caveat="Route array does not contain a plotted destination.",
        )
    destination = hops[-1].star_system
    next_hop = hops[1].star_system

    return ActiveRouteState(
        origin=origin,
        destination=destination,
        next_hop=next_hop,
        total_hops=len(hops) - 1,
        route_state="active",
        hops=tuple(hops),
        freshness_label=FreshnessLabel.LOCAL_ONLY,
        truth_class=TruthClass.LOCAL_TELEMETRY,
        source_id=_SOURCE_ID,
        observed_at=_parse_navroute_timestamp(navroute_data),
        fallback=None,
        caveat=None,
    )


def build_spansh_url(origin: str | None, destination: str | None) -> str | None:
    """Build a Spansh route plotter link-out URL from origin and destination.

    No network call. URL constructed locally via urllib.parse.
    Returns None when either endpoint is absent.
    """
    if not origin or not destination:
        return None
    params = urlencode({"source": origin, "destination": destination})
    return f"https://spansh.co.uk/plotter?{params}"


def build_snapshot(
    navroute_path: Path | None = None,
    state: StateManager | None = None,
) -> NavigationSnapshot:
    """Build the typed Navigation snapshot from local NavRoute.json."""
    generated_at = datetime.now(timezone.utc)
    navroute_data = read_navroute(navroute_path)
    active_route = build_active_route(navroute_data)
    spansh_url = build_spansh_url(active_route.origin, active_route.destination)
    snap = state.snapshot if state is not None else None
    return NavigationSnapshot(
        generated_at=generated_at,
        active_route=active_route,
        spansh_url=spansh_url,
        current_system=snap.current_system if snap is not None else None,
        current_station=snap.current_station if snap is not None else None,
    )


def snapshot_payload(
    navroute_path: Path | None = None,
    state: StateManager | None = None,
) -> dict[str, Any]:
    """Return the current Navigation snapshot as a serialisable dict."""
    return build_snapshot(navroute_path, state).payload()


def empty_snapshot_payload() -> dict[str, Any]:
    """Return an honest Navigation snapshot when no local data is available."""
    return NavigationSnapshot(
        generated_at=datetime.now(timezone.utc),
        active_route=build_active_route(None),
        spansh_url=None,
        current_system=None,
        current_station=None,
    ).payload()


# ---------------------------------------------------------------------------
# Confirmation Gate proposal — review-only scaffold (PB05-04)
# ---------------------------------------------------------------------------


async def create_route_activation_proposal(
    active_route: ActiveRouteState,
    gate: ConfirmationGate,
    activity_log: ActivityLog | None = None,
) -> RouteIntent:
    """Wrap a route-activation proposal through the existing Confirmation Gate.

    Review-only in PB05-04. Even when gate returns approved, no in-game action
    is performed. The decision records Commander intent only via Activity Log.

    Law 1 compliance: gate.require_confirmation() is always called; no bypass.
    """
    workflow_id = str(uuid.uuid4())
    proposed_at = datetime.now(timezone.utc)
    destination_label = active_route.destination or UNKNOWN
    hops_label = (
        str(active_route.total_hops) if active_route.total_hops is not None else UNKNOWN
    )

    if activity_log is not None:
        activity_log.append(
            ActivityEntry(
                event_type=_ROUTE_ACTIVATION_PROPOSAL_CREATED,
                timestamp=proposed_at.isoformat(),
                summary=(
                    f"Route activation proposal created: workflow={workflow_id}, "
                    f"destination={destination_label}, "
                    f"total_hops={hops_label}"
                ),
            )
        )

    approved = await gate.require_confirmation(
        action_type=ActionType.PLOT_ROUTE,
        summary=(
            f"Review route to {destination_label} "
            f"({hops_label} hops) — review only, no game action"
        ),
        details={
            "destination": active_route.destination,
            "total_hops": active_route.total_hops,
            "caveat": "Review only — no in-game action is performed by this playbook.",
            "workflow_id": workflow_id,
        },
    )

    decision = "approved" if approved else "rejected"
    decision_recorded_at = datetime.now(timezone.utc)

    if activity_log is not None:
        activity_log.append(
            ActivityEntry(
                event_type=_ROUTE_ACTIVATION_PROPOSAL_DECISION,
                timestamp=decision_recorded_at.isoformat(),
                summary=(
                    f"Route activation proposal {decision}: "
                    f"workflow={workflow_id}, destination={destination_label}"
                ),
            )
        )

    return RouteIntent(
        workflow_id=workflow_id,
        destination=active_route.destination,
        proposed_at=proposed_at,
        active_route=active_route,
        caveat="Review only — no in-game action is performed.",
        decision=decision,
        decision_recorded_at=decision_recorded_at,
    )
