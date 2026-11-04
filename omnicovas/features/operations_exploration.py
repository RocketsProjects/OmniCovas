"""Read-only Operations exploration/exobiology objectives snapshot for PB05-08.

Operations owns active objectives only. Intel owns facts. Navigation owns routes.
This module does not duplicate Intel fact tables or Navigation route tables.
All exobiology value/species/body/first-footfall/bio-scan facts are No Verified Source.
No outbound calls. No AI. No second state manager.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
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


# ---------------------------------------------------------------------------
# Deterministic workflow identity (R1-3)
# ---------------------------------------------------------------------------
#
# Objectives and blockers here are DERIVED workflow items, not persisted domain
# records: each one is recomputed from NavRoute.json on every read. Their
# identity must therefore represent the thing, not the request that rendered it.
# `uuid.uuid4()` per call made every objective a new entity one second later, so
# nothing could reference, resume, complete or prove one.
#
# The rule:
#   * identity = kind + the semantic condition or target that defines the item;
#   * progress is NOT identity - hop counts, timestamps and freshness labels are
#     deliberately excluded, so "Transit to Colonia" keeps one identity for the
#     whole trip;
#   * a materially different condition IS a different item - a NavRoute.json
#     that cannot be read is not the same blocker as one that reads cleanly and
#     holds no route, so the two carry different identities;
#   * identities are readable, stable strings rather than opaque UUIDs. The
#     payload contract is already `str` and already shipped a non-UUID literal
#     ("empty"), so nothing downstream depends on UUID shape.

_OBJECTIVE_ID_PREFIX = "exploration.objective"
_BLOCKER_ID_PREFIX = "exploration.blocker"
_IDENTITY_UNKNOWN = "unknown"
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _identity_slug(value: str | None) -> str:
    """Reduce a semantic target to a stable, readable identity component."""
    slug = _SLUG_STRIP.sub("-", str(value or "").strip().lower()).strip("-")
    return slug or _IDENTITY_UNKNOWN


def objective_identity(kind: str, target: str | None = None) -> str:
    """Deterministic identity for a derived exploration objective."""
    parts = [_OBJECTIVE_ID_PREFIX, _identity_slug(kind)]
    if target is not None:
        parts.append(_identity_slug(target))
    return ".".join(parts)


def blocker_identity(kind: str, condition: str | None = None) -> str:
    """Deterministic identity for a derived exploration blocker."""
    parts = [_BLOCKER_ID_PREFIX, _identity_slug(kind)]
    if condition is not None:
        parts.append(_identity_slug(condition))
    return ".".join(parts)


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
    # Phase 14 R5: what advanced this row, and which journal event can advance
    # it. A row with no evidence is Unknown and says why.
    evidence: str | None = None
    source_event: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "label": self.label,
            "state": self.state,
            "caveat": self.caveat,
            "evidence": self.evidence,
            "source_event": self.source_event,
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
    # Phase 14 R5-3: this is a DERIVED workflow step, never Commander intent.
    # It is stated on the payload so no surface can mistake the two, and so the
    # Commander objective (commander_entered, persisted, gated) stays the only
    # thing labelled as the Commander's own.
    owner: str = "derived"
    target: str | None = None
    target_kind: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "objective_id": self.objective_id,
            "kind": self.kind,
            "label": self.label,
            "state": self.state,
            "fallback": self.fallback,
            "source_id": self.source_id,
            "owner": self.owner,
            "target": self.target,
            "target_kind": self.target_kind,
        }


@dataclass(frozen=True)
class OperationsExplorationBlocker:
    """A blocker preventing objective completion or reliable status display."""

    blocker_id: str
    label: str
    kind: str
    source_id: str | None
    detail: str | None = None
    # Phase 14 R5-9: the stable condition this blocker represents, so the one
    # Operations outlook card can decide relevance from a declared identity
    # rather than from the wording of a label.
    condition_id: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "blocker_id": self.blocker_id,
            "label": self.label,
            "kind": self.kind,
            "source_id": self.source_id,
            "detail": self.detail,
            "condition_id": self.condition_id,
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
    # Phase 14 R5: the workflow depth layer — stage, progress, work remaining,
    # completion readiness and value. None when this snapshot was built without
    # access to the local exploration history (the PB05-08 route-only path).
    workflow: dict[str, Any] | None = None

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
            "workflow": self.workflow,
        }


# ---------------------------------------------------------------------------
# Exobiology checklist scaffold
# ---------------------------------------------------------------------------


def _build_checklist() -> tuple[ExobiologyChecklistItem, ...]:
    """The checklist as it reads with no exploration history to advance it.

    PB05-08 shipped five rows permanently hardcoded to `unknown`, and its own
    docstring admitted no bio-scan journal event was ever parsed — a scaffold
    that could never change state. Phase 14 R5 parses those events; this
    function now only supplies the honest empty form used when the local
    exploration history is unreachable, and it says so instead of implying the
    Commander has done nothing.

    Two of the original rows are deliberately gone rather than left permanently
    Unknown: exobiology valuation has no verified source, and first footfall has
    no local signal at all. Both survive where they can be stated truthfully —
    in the workflow `value` and `footfall` blocks — instead of masquerading as
    workflow steps that will one day tick.
    """
    unreadable = (
        "Local exploration history not read, so this row is Unknown rather "
        "than incomplete."
    )
    items = (
        ("system_survey", "System survey recorded", "FSSDiscoveryScan"),
        ("bodies_scanned", "Bodies scanned", "Scan / FSSAllBodiesFound"),
        ("surface_map", "Surface map recorded", "SAAScanComplete"),
        ("biology_signals", "Biological signals detected", "SAASignalsFound"),
        ("bio_log", "First bio sample logged", "ScanOrganic"),
        ("bio_sample", "Second bio sample taken", "ScanOrganic"),
        ("bio_analyse", "Bio sample analysed", "ScanOrganic"),
    )
    return tuple(
        ExobiologyChecklistItem(
            item_id=item_id,
            label=label,
            state=_SESSION_UNKNOWN,
            caveat=unreadable,
            evidence=None,
            source_event=source_event,
        )
        for item_id, label, source_event in items
    )


def _checklist_from_workflow(
    workflow: dict[str, Any],
) -> tuple[ExobiologyChecklistItem, ...]:
    """Map the workflow's evidence-advanced checklist onto the payload shape."""
    return tuple(
        ExobiologyChecklistItem(
            item_id=str(entry.get("item_id")),
            label=str(entry.get("label")),
            state=str(entry.get("state")),
            caveat=entry.get("caveat"),
            evidence=entry.get("evidence"),
            source_event=entry.get("source_event"),
        )
        for entry in workflow.get("checklist") or ()
    )


def _objectives_from_workflow(
    workflow: dict[str, Any],
) -> tuple[ExplorationObjective, ...]:
    """The derived workflow step, expressed as the snapshot's objective entry.

    Exactly one, because there is exactly one current step. PB05-08 emitted a
    second entry that was not an objective at all — a caveat about exobiology
    valuation wearing an objective's shape — and it is gone.
    """
    step = workflow.get("step")
    if not step:
        return ()
    return (
        ExplorationObjective(
            objective_id=str(step["objective_id"]),
            kind=str(step["kind"]),
            label=str(step["label"]),
            state=str(step["state"]),
            fallback=None,
            source_id=str(step.get("source_id") or _SOURCE_UNKNOWN),
            owner=str(step.get("owner") or "derived"),
            target=step.get("target"),
            target_kind=step.get("target_kind"),
        ),
    )


def _blockers_from_workflow(
    workflow: dict[str, Any],
) -> tuple[OperationsExplorationBlocker, ...]:
    return tuple(
        OperationsExplorationBlocker(
            blocker_id=str(entry["blocker_id"]),
            label=str(entry["label"]),
            kind=str(entry["kind"]),
            source_id=entry.get("source_id"),
            detail=entry.get("detail"),
            condition_id=entry.get("condition_id"),
        )
        for entry in workflow.get("blockers") or ()
    )


def apply_workflow(
    snapshot: OperationsExplorationSnapshot,
    workflow: dict[str, Any] | None,
) -> OperationsExplorationSnapshot:
    """Fold the R5 workflow layer into a route-derived PB05-08 snapshot.

    The workflow is the deeper reading of the same session, so where it can
    speak it becomes the snapshot's objective, blocker and checklist source —
    one owner per field, never two lists of the same thing side by side. Where
    it could not read the local history, the route-derived snapshot stands and
    the workflow's own `source_unavailable` blocker is added to it, so the
    Commander is told the history is unreadable rather than shown an empty
    workflow.
    """
    if workflow is None:
        return snapshot

    if not workflow.get("available"):
        return replace(
            snapshot,
            blockers=snapshot.blockers + _blockers_from_workflow(workflow),
            workflow=workflow,
        )

    return replace(
        snapshot,
        objectives=_objectives_from_workflow(workflow),
        checklist=_checklist_from_workflow(workflow),
        blockers=_blockers_from_workflow(workflow),
        workflow=workflow,
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
                    blocker_id=blocker_identity("no_route", "navroute_not_loaded"),
                    label="No active route — NavRoute.json not found",
                    kind="no_route",
                    source_id=_SOURCE_LOCAL_NAVROUTE,
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
                    objective_id=objective_identity("destination_transit", "unplotted"),
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
                    blocker_id=blocker_identity("no_route", "none_plotted"),
                    label="No active route plotted",
                    kind="no_route",
                    source_id=_SOURCE_LOCAL_NAVROUTE,
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
            # Identity is the destination, never the hop count: hops fall as
            # the Commander flies, and that is progress on one objective, not a
            # new objective at every jump.
            objective_id=objective_identity(
                "destination_transit", active_route.destination
            ),
            kind="destination_transit",
            label=(
                f"Transit to {active_route.destination or UNKNOWN}"
                f" ({total_hops if total_hops is not None else UNKNOWN} hops)"
            ),
            state="active",
            fallback=None,
            source_id=_SOURCE_LOCAL_NAVROUTE,
        ),
    ]
    return OperationsExplorationSnapshot(
        generated_at=generated_at,
        session_status=_SESSION_ROUTE_LOADED,
        active_route_ref=route_ref,
        objectives=tuple(objectives),
        checklist=checklist,
        blockers=(),
        handoffs=handoffs,
        unsupported_notes=_UNSUPPORTED_NOTES,
    )


def snapshot_payload(navroute_path: Path | None = None) -> dict[str, Any]:
    """Return the current Operations exploration snapshot as a serialisable dict."""
    return build_snapshot(navroute_path).payload()


async def workflow_snapshot_payload(
    session_factory: Any,
    *,
    star_system: str | None,
    navroute_path: Path | None = None,
) -> dict[str, Any]:
    """The full Phase 14 R5 exploration snapshot: route context plus workflow.

    One endpoint, one payload, one owner per field. The route half is PB05-08
    unchanged; the workflow half reads the Commander's own journal history for
    the system they are actually standing in.
    """
    from omnicovas.features import operations_exploration_workflow as workflow_mod

    snapshot = build_snapshot(navroute_path)
    route_ref = snapshot.active_route_ref
    workflow = await workflow_mod.build_workflow(
        session_factory,
        star_system=star_system,
        route_destination=route_ref.destination if route_ref else None,
        route_active=snapshot.session_status == _SESSION_ROUTE_LOADED,
        navroute_loaded=snapshot.session_status != _SESSION_NO_ROUTE,
    )
    return apply_workflow(snapshot, workflow).payload()


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
                blocker_id=blocker_identity("source_unavailable", "no_local_data"),
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
