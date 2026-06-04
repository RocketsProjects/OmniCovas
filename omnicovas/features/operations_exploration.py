"""Read-only Operations exploration/exobiology objectives snapshot for PB05-08.

Operations owns active objectives only. Intel owns facts. Navigation owns routes.
This module does not duplicate Intel fact tables or Navigation route tables.
All exobiology value/species/body/first-footfall/bio-scan facts are No Verified Source.
No outbound calls. No AI. No second state manager.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omnicovas.features.navigation import build_active_route, read_navroute

# Accepted fallback wording from Source Capability Routing Reference v1
UNKNOWN = "Unknown"
NOT_LOADED = "Not Loaded"
NO_VERIFIED_SOURCE = "No Verified Source"
UNSUPPORTED = "Unsupported"

_SOURCE_LOCAL_NAVROUTE = "local_navroute"
_SOURCE_UNKNOWN = "unknown"

# Handoff paths — references only, no data duplication
_INTEL_HANDOFF_PATH = "/intel/snapshot"
_NAVIGATION_HANDOFF_PATH = "/navigation/snapshot"
_ACTIVITY_LOG_HANDOFF_PATH = "/activity-log"

# Session status values
_SESSION_ROUTE_LOADED = "route_loaded"
_SESSION_NO_ROUTE_PLOTTED = "no_route_plotted"
_SESSION_NO_ROUTE = "no_route"
_SESSION_UNKNOWN = "unknown"

# Unsupported exobiology fact notes (honest degradation — no verified provider)
_UNSUPPORTED_NOTES: tuple[str, ...] = (
    "Exobiology valuation: No Verified Source. No verified provider access.",
    "Biological species / body facts: No Verified Source.",
    "First footfall status: Unknown — no verified local source.",
    "EDAstro / EDSM exobiology call: Disabled. Provider access not enabled.",
    "Bio-scan completion state: Unknown — Journal parsing not in this slice.",
)


@dataclass(frozen=True)
class ExobiologyChecklistItem:
    """Commander-local exobiology workflow scaffold.

    Every item carries an explicit No Verified Source caveat.
    This is scaffolding only — no verified exobiology facts are stored here.
    """

    item_id: str
    label: str
    state: str
    caveat: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "state": self.state,
            "caveat": self.caveat,
        }


@dataclass(frozen=True)
class ExplorationObjective:
    """Active exploration objective derived from local data only."""

    objective_id: str
    kind: str
    label: str
    state: str
    fallback: str | None
    source_id: str

    def payload(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "kind": self.kind,
            "label": self.label,
            "state": self.state,
            "fallback": self.fallback,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class OperationsExplorationBlocker:
    """A blocker preventing objective completion or reliable status display."""

    blocker_id: str
    label: str
    kind: str
    source_id: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "blocker_id": self.blocker_id,
            "label": self.label,
            "kind": self.kind,
            "source_id": self.source_id,
        }


@dataclass(frozen=True)
class ActiveRouteRef:
    """Minimal reference to the Navigation active route.

    Navigation owns the full route data. Operations references only the
    fields needed to show session context. Full hop table stays at
    /navigation/snapshot.
    """

    destination: str | None
    total_hops: int | None
    freshness_label: str
    fallback: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "total_hops": self.total_hops,
            "freshness_label": self.freshness_label,
            "fallback": self.fallback,
        }


@dataclass(frozen=True)
class OperationsExplorationSnapshot:
    """Read-only Phase 5 PB05-08 Operations exploration/exobiology snapshot."""

    generated_at: datetime
    session_status: str
    active_route_ref: ActiveRouteRef | None
    objectives: tuple[ExplorationObjective, ...]
    checklist: tuple[ExobiologyChecklistItem, ...]
    blockers: tuple[OperationsExplorationBlocker, ...]
    handoffs: dict[str, str]
    unsupported_notes: tuple[str, ...]
    nullprovider_safe: bool = True
    fallback: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "session_status": self.session_status,
            "active_route_ref": (
                self.active_route_ref.payload()
                if self.active_route_ref is not None
                else None
            ),
            "objectives": [o.payload() for o in self.objectives],
            "checklist": [c.payload() for c in self.checklist],
            "blockers": [b.payload() for b in self.blockers],
            "handoffs": dict(self.handoffs),
            "unsupported_notes": list(self.unsupported_notes),
            "nullprovider_safe": self.nullprovider_safe,
            "fallback": self.fallback,
        }


# ---------------------------------------------------------------------------
# Exobiology checklist scaffold
# ---------------------------------------------------------------------------


def _build_checklist() -> tuple[ExobiologyChecklistItem, ...]:
    """Build commander-local exobiology checklist scaffold.

    All items carry No Verified Source caveat — this is workflow scaffolding,
    not a verified fact table. Bio-scan Journal events are not parsed in PB05-08.
    """
    items = [
        ("log_first_scan", "Log first bio scan", "No Verified Source"),
        ("sample_second_organism", "Sample second organism", "No Verified Source"),
        (
            "complete_third_sample",
            "Complete third sample for payout",
            "No Verified Source",
        ),
        (
            "exobiology_valuation",
            "Exobiology valuation",
            "Exobiology valuation: No Verified Source. No verified provider.",
        ),
        (
            "first_footfall_status",
            "First footfall status",
            "First footfall: Unknown — no verified local source.",
        ),
    ]
    return tuple(
        ExobiologyChecklistItem(
            item_id=item_id,
            label=label,
            state=_SESSION_UNKNOWN,
            caveat=caveat,
        )
        for item_id, label, caveat in items
    )


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------


def build_snapshot(navroute_path: Path | None = None) -> OperationsExplorationSnapshot:
    """Build the Operations exploration snapshot from local data only.

    Navigation owns the NavRoute.json reader. This function calls
    navigation.read_navroute() and navigation.build_active_route() directly —
    no second reader, no duplication.

    Operations owns the session status derivation and the objective/checklist/
    blocker/handoff assembly from that route data.
    """
    generated_at = datetime.now(timezone.utc)
    handoffs: dict[str, str] = {
        "intel": _INTEL_HANDOFF_PATH,
        "navigation": _NAVIGATION_HANDOFF_PATH,
        "activity_log": _ACTIVITY_LOG_HANDOFF_PATH,
    }
    checklist = _build_checklist()

    navroute_data = read_navroute(navroute_path)
    active_route = build_active_route(navroute_data)

    if navroute_data is None:
        # NavRoute.json not found or unreadable
        route_ref = ActiveRouteRef(
            destination=None,
            total_hops=None,
            freshness_label=active_route.freshness_label.value,
            fallback=NOT_LOADED,
        )
        return OperationsExplorationSnapshot(
            generated_at=generated_at,
            session_status=_SESSION_NO_ROUTE,
            active_route_ref=route_ref,
            objectives=(),
            checklist=checklist,
            blockers=(
                OperationsExplorationBlocker(
                    blocker_id=str(uuid.uuid4()),
                    label="No active route — NavRoute.json not found",
                    kind="no_route",
                    source_id=_SOURCE_LOCAL_NAVROUTE,
                ),
                OperationsExplorationBlocker(
                    blocker_id=str(uuid.uuid4()),
                    label="Exobiology valuation: No Verified Source",
                    kind="unsupported_fact",
                    source_id=None,
                ),
            ),
            handoffs=handoffs,
            unsupported_notes=_UNSUPPORTED_NOTES,
            fallback=NOT_LOADED,
        )

    if active_route.route_state != "active":
        # File found but no active route plotted
        route_ref = ActiveRouteRef(
            destination=None,
            total_hops=None,
            freshness_label=active_route.freshness_label.value,
            fallback="No route plotted",
        )
        return OperationsExplorationSnapshot(
            generated_at=generated_at,
            session_status=_SESSION_NO_ROUTE_PLOTTED,
            active_route_ref=route_ref,
            objectives=(
                ExplorationObjective(
                    objective_id=str(uuid.uuid4()),
                    kind="destination_transit",
                    label="No route plotted — plot a route in Navigation to begin",
                    state="blocked",
                    fallback="No route plotted",
                    source_id=_SOURCE_LOCAL_NAVROUTE,
                ),
            ),
            checklist=checklist,
            blockers=(
                OperationsExplorationBlocker(
                    blocker_id=str(uuid.uuid4()),
                    label="No active route plotted",
                    kind="no_route",
                    source_id=_SOURCE_LOCAL_NAVROUTE,
                ),
                OperationsExplorationBlocker(
                    blocker_id=str(uuid.uuid4()),
                    label="Exobiology valuation: No Verified Source",
                    kind="unsupported_fact",
                    source_id=None,
                ),
            ),
            handoffs=handoffs,
            unsupported_notes=_UNSUPPORTED_NOTES,
        )

    # Active route present
    total_hops = active_route.total_hops
    route_ref = ActiveRouteRef(
        destination=active_route.destination,
        total_hops=total_hops,
        freshness_label=active_route.freshness_label.value,
        fallback=None,
    )
    objectives: list[ExplorationObjective] = [
        ExplorationObjective(
            objective_id=str(uuid.uuid4()),
            kind="destination_transit",
            label=(
                f"Transit to {active_route.destination or UNKNOWN}"
                f" ({total_hops if total_hops is not None else UNKNOWN} hops)"
            ),
            state="active",
            fallback=None,
            source_id=_SOURCE_LOCAL_NAVROUTE,
        ),
        ExplorationObjective(
            objective_id=str(uuid.uuid4()),
            kind="exobiology_checklist",
            label="Exobiology checklist: No Verified Source — local scaffold only",
            state=_SESSION_UNKNOWN,
            fallback=NO_VERIFIED_SOURCE,
            source_id=_SOURCE_UNKNOWN,
        ),
    ]
    return OperationsExplorationSnapshot(
        generated_at=generated_at,
        session_status=_SESSION_ROUTE_LOADED,
        active_route_ref=route_ref,
        objectives=tuple(objectives),
        checklist=checklist,
        blockers=(
            OperationsExplorationBlocker(
                blocker_id=str(uuid.uuid4()),
                label="Exobiology valuation: No Verified Source",
                kind="unsupported_fact",
                source_id=None,
            ),
        ),
        handoffs=handoffs,
        unsupported_notes=_UNSUPPORTED_NOTES,
    )


def snapshot_payload(navroute_path: Path | None = None) -> dict[str, Any]:
    """Return the current Operations exploration snapshot as a serialisable dict."""
    return build_snapshot(navroute_path).payload()


def empty_snapshot_payload() -> dict[str, Any]:
    """Return an honest Operations exploration snapshot when no local data is available.

    NullProvider-safe — no StateManager or NavRoute.json required.
    """
    return OperationsExplorationSnapshot(
        generated_at=datetime.now(timezone.utc),
        session_status=_SESSION_UNKNOWN,
        active_route_ref=None,
        objectives=(),
        checklist=_build_checklist(),
        blockers=(
            OperationsExplorationBlocker(
                blocker_id="empty",
                label="No local data available",
                kind="source_unavailable",
                source_id=None,
            ),
        ),
        handoffs={
            "intel": _INTEL_HANDOFF_PATH,
            "navigation": _NAVIGATION_HANDOFF_PATH,
            "activity_log": _ACTIVITY_LOG_HANDOFF_PATH,
        },
        unsupported_notes=_UNSUPPORTED_NOTES,
        fallback=NOT_LOADED,
    ).payload()
