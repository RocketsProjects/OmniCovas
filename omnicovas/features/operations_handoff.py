"""Cross-route workflow handoff proof for Operations (Phase 14 R8).

R6 turned on context-carrying handoffs for Trade and left `P14-G08` partial
because no Activity Log proof was emitted. R7 met the same question for Combat
and declined to settle it inside one slice: whether a cross-route handoff is a
provable event spans every route, so deciding it from a Trade or Combat surface
would have set a precedent by accident. R8 owns the answer.

The doctrine
------------

**A purposeful workflow handoff is proof-worthy. Ordinary navigation is not.**

A Commander who hands a commodity from Operations to Intel, or a campaign to
Navigation, has made a workflow decision — later they may need to know it
happened, and when. Clicking a top tab is not that. The Activity Log is a record
of application actions, not a clickstream, and the distinction is enforced here
by construction: only an explicit `startRouteTransfer` dispatch reaches this
module. Tab clicks, browser back, hash changes and mode selection never call it.

**Emitted once, at dispatch.** The event records that a handoff was *made*, so
it is written when the intent is committed to the shell — never on destination
render, arrival highlight, refresh, or banner re-render, each of which can
happen many times for one decision.

**A handoff needs no confirmation.** Logging proof does not make navigation
destructive. Nothing is mutated, nothing leaves the machine, and the Commander
can simply navigate back.

Taxonomy
--------

Existing event authority already defines domain-specific handoff proof, so this
module reuses it rather than forking:

* Phase 9 campaign handoffs emit `PHASE_9_CAMPAIGN_HANDOFF_TO_*`, which
  PB09-07 declared and which nothing had ever emitted;
* every other Operations workflow handoff emits one canonical
  `OPERATIONS_WORKFLOW_HANDOFF`, rather than each workflow inventing
  `trade_handoff`, `combat_handoff` and so on.

Privacy
-------

The payload is a **whitelist of structured slugs and ids**. It cannot carry
Commander-authored objective text, campaign titles or notes, AI prompt or
response text, or Squadron notes — not because callers are trusted to leave them
out, but because any field not on the whitelist is dropped and every value that
survives must match a conservative slug pattern. PB09-04 set this precedent for
campaign proof payloads ("No raw private text in payloads"); this generalises it.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Final

from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.event_types import (
    OPERATIONS_WORKFLOW_HANDOFF,
    PHASE_9_CAMPAIGN_HANDOFF_TO_ACTIVITY_LOG,
    PHASE_9_CAMPAIGN_HANDOFF_TO_INTEL,
    PHASE_9_CAMPAIGN_HANDOFF_TO_NAVIGATION,
    PHASE_9_CAMPAIGN_HANDOFF_TO_SQUADRONS,
)

#: Routes a purposeful Operations handoff may target. Mirrors the shell's own
#: route table; a target outside it is not a handoff this app can make.
TARGET_ROUTES: Final[frozenset[str]] = frozenset(
    {
        "/intel",
        "/navigation",
        "/engineering",
        "/squadrons",
        "/activity-log",
        "/operations",
    }
)

#: Campaign handoffs reuse the Phase 9 taxonomy PB09-07 already declared.
CAMPAIGN_EVENT_BY_ROUTE: Final[dict[str, str]] = {
    "/intel": PHASE_9_CAMPAIGN_HANDOFF_TO_INTEL,
    "/navigation": PHASE_9_CAMPAIGN_HANDOFF_TO_NAVIGATION,
    "/squadrons": PHASE_9_CAMPAIGN_HANDOFF_TO_SQUADRONS,
    "/activity-log": PHASE_9_CAMPAIGN_HANDOFF_TO_ACTIVITY_LOG,
}

#: Operations modes a handoff may originate from.
ORIGIN_PACKAGES: Final[frozenset[str]] = frozenset(
    {
        "idle",
        "mining",
        "trading",
        "combat",
        "exploration",
        "travel",
        "station",
        "squadron",
        "bgs",
        "powerplay",
    }
)

#: Campaign workflow types, which select the Phase 9 taxonomy above.
CAMPAIGN_PACKAGES: Final[frozenset[str]] = frozenset({"bgs", "powerplay"})

#: The ONLY fields that may reach the Activity Log. Anything else is dropped.
PAYLOAD_FIELDS: Final[tuple[str, ...]] = (
    "origin_route",
    "origin_package",
    "origin_section_id",
    "target_route",
    "target_section_id",
    "target_entity_kind",
    "target_entity_id",
    "handoff_kind",
    "workflow_id",
    #: Required of every ACTIVE `phase_9.*` payload by the Activity Log payload
    #: contract, and truthful here: this payload is redacted by construction.
    #: The whitelist is in fact STRICTER than `normalize_phase9_payload`, which
    #: removes known-bad keys; this admits only known-good ones.
    "redacted",
)

#: Conservative: slugs, dotted ids and route paths only. Deliberately excludes
#: whitespace, so a sentence cannot masquerade as an id and reach the log.
_SLUG: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")

MAX_FIELD_LENGTH: Final[int] = 128


class HandoffError(ValueError):
    """A handoff that cannot be proved as described."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: Any, *, field: str, required: bool = False) -> str | None:
    """One payload value, or None. Free text never survives this.

    A value that is not a slug is DROPPED rather than logged, because a handoff
    that really happened should still be provable even if a caller passed
    something unloggable. The one exception is a required field: without it the
    event would describe nothing, so the caller is refused instead.
    """
    if value is None:
        if required:
            raise HandoffError(f"{field} is required")
        return None
    text = str(value).strip()
    if not text:
        if required:
            raise HandoffError(f"{field} is required")
        return None
    if len(text) > MAX_FIELD_LENGTH or not _SLUG.match(text):
        if required:
            raise HandoffError(f"{field} is not a safe workflow identifier")
        return None
    return text


def build_payload(
    *,
    origin_package: str,
    target_route: str,
    origin_section_id: Any = None,
    target_section_id: Any = None,
    target_entity_kind: Any = None,
    target_entity_id: Any = None,
    handoff_kind: Any = None,
    workflow_id: Any = None,
) -> dict[str, Any]:
    """The safe workflow metadata for one handoff.

    Origin route is fixed rather than accepted: this module proves handoffs made
    *from* Operations, and letting a caller name a different origin would let it
    describe a handoff it did not make.
    """
    # Both are CLOSED SETS, so membership is the whole validation. Running them
    # through the slug pattern first would be weaker, not stronger, and it
    # rejects route paths for beginning with "/".
    package = str(origin_package or "").strip()
    if package not in ORIGIN_PACKAGES:
        raise HandoffError("origin_package is not an Operations mode")
    route = str(target_route or "").strip()
    if route not in TARGET_ROUTES:
        raise HandoffError("target_route is not a handoff destination")

    payload: dict[str, Any] = {
        "origin_route": "/operations",
        "origin_package": package,
        "target_route": route,
        "redacted": True,
    }
    optional = {
        "origin_section_id": origin_section_id,
        "target_section_id": target_section_id,
        "target_entity_kind": target_entity_kind,
        "target_entity_id": target_entity_id,
        "handoff_kind": handoff_kind,
        "workflow_id": workflow_id,
    }
    for field, raw in optional.items():
        cleaned = _slug(raw, field=field)
        if cleaned is not None:
            payload[field] = cleaned

    # Belt and braces: nothing outside the whitelist may exist on the payload.
    return {key: payload[key] for key in PAYLOAD_FIELDS if key in payload}


def event_type_for(origin_package: str, target_route: str) -> str:
    """The event a handoff should carry.

    Campaign handoffs reuse the Phase 9 taxonomy. Everything else uses the one
    canonical Operations workflow event, so a new workflow does not need a new
    event type to be provable.
    """
    if origin_package in CAMPAIGN_PACKAGES:
        campaign_event = CAMPAIGN_EVENT_BY_ROUTE.get(target_route)
        if campaign_event is not None:
            return campaign_event
    return OPERATIONS_WORKFLOW_HANDOFF


def summary_for(payload: dict[str, Any]) -> str:
    """A summary built only from already-validated slugs.

    Deliberately assembled here rather than accepted from the caller: a
    caller-supplied summary is free text, and free text is what this module
    exists to keep out of the log.
    """
    origin = payload["origin_package"]
    target = payload["target_route"].lstrip("/")
    return f"Operations {origin} workflow handoff to {target}"


def record_handoff(
    activity_log: ActivityLog | None,
    *,
    origin_package: str,
    target_route: str,
    origin_section_id: Any = None,
    target_section_id: Any = None,
    target_entity_kind: Any = None,
    target_entity_id: Any = None,
    handoff_kind: Any = None,
    workflow_id: Any = None,
) -> dict[str, Any]:
    """Prove one purposeful workflow handoff. Exactly one event.

    Raises `HandoffError` for a handoff that cannot be described safely, which
    the API turns into a 422. No event is written in that case: an unprovable
    handoff must not leave a half-true record.
    """
    payload = build_payload(
        origin_package=origin_package,
        target_route=target_route,
        origin_section_id=origin_section_id,
        target_section_id=target_section_id,
        target_entity_kind=target_entity_kind,
        target_entity_id=target_entity_id,
        handoff_kind=handoff_kind,
        workflow_id=workflow_id,
    )
    event_type = event_type_for(payload["origin_package"], payload["target_route"])
    event_id = uuid.uuid4().hex

    if activity_log is not None:
        activity_log.append(
            ActivityEntry(
                event_type=event_type,
                timestamp=_now(),
                summary=summary_for(payload),
                payload=payload,
                source_chain=[
                    {
                        "source": "Operations",
                        "source_type": "commander_action",
                        "source_event": "route_transfer_intent",
                    }
                ],
                redaction_state="redacted_summary_only",
                # A handoff is a Commander action, not an observed fact about
                # the galaxy. R0's truth classes stay intact.
                is_fact=False,
                linked_entity_refs={
                    key: payload[key]
                    for key in ("target_entity_id", "workflow_id")
                    if key in payload
                },
                surface_origin="operations",
                correlation_id=event_id,
                event_id=event_id,
                source="commander_entered",
            )
        )

    return {
        "event_id": event_id,
        "event_type": event_type,
        "payload": payload,
        "logged": activity_log is not None,
    }
