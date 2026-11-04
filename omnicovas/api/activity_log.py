"""
omnicovas.api.activity_log

Activity Log export confirmation and export proof endpoints.

Mounted under the prefix /activity-log by ApiBridge._build_app(). The read-only
`GET /activity-log` feed remains owned by ApiBridge; this module owns the
commander-initiated export flow only.

Law 1 (Confirmation Gate) / Engineering Standards §15:
    An export of commander data is a protected action. It is proposed into the
    one Week 13 pending-confirmation queue and waits for a commander POST.
    There is no local Boolean, no `confirmed: true` field, and no fast path:
    the only thing that authorizes an export is a server-held CONFIRMED
    decision, consumed exactly once.

Law 8 (Sovereignty & Transparency) / Master §11.5:
    The export is visible in the Activity Log at every stage.

Law 5 (Zero Hallucination) — truthful proof semantics:
    Five distinct facts are recorded, and none is allowed to imply another:

      1. ACTIVITY_LOG_EXPORT_PROPOSAL_SHOWN
         An export was proposed to the commander. Nothing is authorized.

      2. ACTIVITY_LOG_EXPORT_PROPOSAL_CONFIRMED / _CANCELED / _BLOCKED
         The commander confirmed, declined, or the proposal expired.

      3. ACTIVITY_LOG_EXPORT_REQUESTED
         A confirmed decision was consumed and the backend authorized the
         export. Evidence class: commander_confirmed. Still no file.

      4. ACTIVITY_LOG_EXPORT_DOWNLOAD_INITIATED / _FAILED
         The client reported whether it handed a file to the browser.
         Evidence class: client_reported_initiation / client_reported_failure.

    "Initiated" is deliberately never "completed": nothing in this
    architecture can observe bytes reaching disk, so no stage claims it.

Counts:
    `backend_observed_log_entries` is measured here. Any count supplied by the
    caller is recorded separately as `client_reported_scope_count` and is never
    treated as backend-observed proof.

See: Engineering Standards §12 (API surface), §14 (one shared Activity Log),
     §15 (Confirmation Gate standards); Backend Blueprint — Activity Log owns
     export records; Confirmation Gate states PROPOSED/CONFIRMED/CANCELED/BLOCKED.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from omnicovas.api import week13
from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.event_types import (
    ACTIVITY_LOG_EXPORT_ABANDONED,
    ACTIVITY_LOG_EXPORT_DOWNLOAD_INITIATED,
    ACTIVITY_LOG_EXPORT_FAILED,
    ACTIVITY_LOG_EXPORT_PROPOSAL_BLOCKED,
    ACTIVITY_LOG_EXPORT_PROPOSAL_CANCELED,
    ACTIVITY_LOG_EXPORT_PROPOSAL_CONFIRMED,
    ACTIVITY_LOG_EXPORT_PROPOSAL_SHOWN,
    ACTIVITY_LOG_EXPORT_REQUESTED,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/activity-log", tags=["activity-log"])

# Injected by ApiBridge._build_app(); never constructed here. There is exactly
# one ActivityLog per process (Engineering Standards §14).
_activity_log: ActivityLog | None = None

# This feature's protected action type. Registering it opts the Week 13 queue
# into retaining its decisions; the queue itself is unchanged and remains the
# only commander-confirmation surface.
ACTIVITY_LOG_EXPORT_ACTION_TYPE = "activity_log_export_proposal"
# Registering the event mapping is what makes the queue audit the commander's
# decision the instant it happens, rather than when (or if) this module is
# called back. The gate owns those three events now; nothing below re-emits.
week13.register_outcome_action_type(
    ACTIVITY_LOG_EXPORT_ACTION_TYPE,
    confirmed_event=ACTIVITY_LOG_EXPORT_PROPOSAL_CONFIRMED,
    canceled_event=ACTIVITY_LOG_EXPORT_PROPOSAL_CANCELED,
    blocked_event=ACTIVITY_LOG_EXPORT_PROPOSAL_BLOCKED,
)

# How long a commander has to answer an export proposal.
_PROPOSAL_TTL_SECONDS = 300

# Bounded ticket registry correlating an authorized export to its outcome
# report. This is export state, not a confirmation queue.
#
# The bound covers the whole operation lifecycle — pending proposals plus
# issued tickets — so repeated proposals cannot grow unbounded work. Tickets
# also age out, so an abandoned export cannot permanently exhaust capacity.
_MAX_PENDING_EXPORTS = 32
_TICKET_TTL_SECONDS = 900
_pending_exports: OrderedDict[str, dict[str, Any]] = OrderedDict()

_DEFAULT_EXPORT_SCOPE = "filtered_view"
_EXPORT_SCOPES: frozenset[str] = frozenset({"filtered_view", "full_view"})

_OUTCOME_DOWNLOAD_INITIATED = "download_initiated"
_OUTCOME_FAILED = "failed"
_EXPORT_OUTCOMES: frozenset[str] = frozenset(
    {_OUTCOME_DOWNLOAD_INITIATED, _OUTCOME_FAILED}
)


def set_activity_log(activity_log: ActivityLog | None) -> None:
    """Inject the one shared ActivityLog into this router."""
    global _activity_log  # noqa: PLW0603
    _activity_log = activity_log


def reset_pending_exports() -> None:
    """Clear the ticket registry. Test seam; not an HTTP surface."""
    _pending_exports.clear()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_reported_count(value: object) -> int | None:
    """Return a caller-reported count, or None when it is not a usable int."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _normalize_scope(value: object) -> str:
    scope = str(value or _DEFAULT_EXPORT_SCOPE)
    return scope if scope in _EXPORT_SCOPES else _DEFAULT_EXPORT_SCOPE


def _append(entry: ActivityEntry) -> None:
    """Append to the one shared Activity Log.

    Raises when no log is wired, so callers that must not proceed without a
    durable audit record can refuse rather than silently losing proof.
    """
    if _activity_log is None:
        raise RuntimeError("Activity Log is not available")
    _activity_log.append(entry)


def _backend_observed_entries() -> int:
    return len(_activity_log) if _activity_log is not None else 0


def _expire_abandoned_tickets() -> None:
    """Canonical ticket-expiry sweep.

    Every ticket-consuming boundary runs this before it looks a ticket up —
    propose, authorize, and result — so an expired ticket is never usable and
    never depends on some other endpoint happening to sweep first.

    Each expiry records a truthful terminal event: the backend authorized an
    export and then never learned what happened, which is not the same as a
    failure and not the same as a download. Removing the ticket in the same
    step is what keeps that event to exactly one per ticket.
    """
    now = datetime.now(timezone.utc)
    for export_id, ticket in list(_pending_exports.items()):
        # A ticket with no deadline is treated as due: nothing may hold
        # capacity indefinitely, whatever shape it arrived in.
        expires_at = ticket.get("expires_at")
        if expires_at is not None and expires_at > now:
            continue
        del _pending_exports[export_id]
        try:
            _append(
                ActivityEntry(
                    event_type=ACTIVITY_LOG_EXPORT_ABANDONED,
                    timestamp=_now(),
                    summary=(
                        "Activity Log export was authorized but never reported an"
                        " outcome; whether a file was written is unknown"
                        f" | scope={ticket['scope']}"
                        " | evidence=none | completion_observed=False"
                    ),
                    payload={
                        "export_id": export_id,
                        "confirmation_id": ticket["confirmation_id"],
                        "scope": ticket["scope"],
                        "stage": "abandoned",
                        "evidence_class": "no_outcome_reported",
                        "completion_observed": False,
                        "requested_at": ticket["requested_at"],
                        "redacted": True,
                    },
                    redaction_state="redacted",
                    surface_origin="activity_log",
                    source="commander_action",
                )
            )
        except RuntimeError:
            # No audit sink; the ticket is still released so capacity recovers.
            logger.warning("activity_log_export_abandoned_unrecorded")


def _live_export_operations() -> int:
    """Pending proposals plus issued tickets — the whole bounded lifecycle."""
    _expire_abandoned_tickets()
    return len(_pending_exports) + week13.count_pending_by_action_type(
        ACTIVITY_LOG_EXPORT_ACTION_TYPE
    )


@router.post("/export/propose")
async def propose_export(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Propose an export to the commander through the Week 13 queue.

    Authorizes nothing. The proposal appears in the globally mounted
    Confirmation Gate and waits for a commander POST.
    """
    payload = dict(body or {})
    scope = _normalize_scope(payload.get("scope"))
    reported_count = _coerce_reported_count(payload.get("entry_count"))

    # A live unresolved operation is never evicted to make room (Principle 10
    # is about bounded resources, not about silently dropping commander work).
    if _live_export_operations() >= _MAX_PENDING_EXPORTS:
        raise HTTPException(
            status_code=503,
            detail=(
                "Too many Activity Log exports are already awaiting a decision "
                "or an audit result. Resolve or retry those before starting "
                "another."
            ),
        )

    described = (
        f"{reported_count} events from the current filtered view"
        if reported_count is not None
        else "the current filtered view"
    )
    timeout_at = (
        datetime.utcnow() + timedelta(seconds=_PROPOSAL_TTL_SECONDS)
    ).isoformat() + "Z"

    confirmation_id = week13.enqueue_confirmation(
        suggestion_text=(
            f"Export {described} of the Activity Log to a local JSON file?"
        ),
        why_text=(
            "Exporting commander data is a protected action. The file is "
            "written locally on this machine and nothing is sent anywhere."
        ),
        timeout_at=timeout_at,
        action_type=ACTIVITY_LOG_EXPORT_ACTION_TYPE,
        metadata={"scope": scope},
    )

    _append(
        ActivityEntry(
            event_type=ACTIVITY_LOG_EXPORT_PROPOSAL_SHOWN,
            timestamp=_now(),
            summary=(
                "Activity Log export proposed for commander confirmation"
                f" | scope={scope}"
                " | authorized=False"
            ),
            payload={
                "confirmation_id": confirmation_id,
                "scope": scope,
                "stage": "proposal_shown",
                "action_type": ACTIVITY_LOG_EXPORT_ACTION_TYPE,
                "client_reported_scope_count": reported_count,
                "redacted": True,
            },
            redaction_state="redacted",
            surface_origin="activity_log",
            source="commander_action",
        )
    )
    logger.info(
        "activity_log_export_proposed",
        extra={"event_type": ACTIVITY_LOG_EXPORT_PROPOSAL_SHOWN, "scope": scope},
    )
    return {
        "status": "pending_commander_confirmation",
        "confirmation_id": confirmation_id,
        "authorized": False,
        "timeout_at": timeout_at,
    }


@router.post("/export/authorize")
async def authorize_export(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Consume a commander decision and, only if CONFIRMED, issue a ticket.

    Declined, expired, unknown, mismatched, and already-consumed decisions all
    refuse. There is no path here that authorizes without a genuine confirmed
    decision recorded by the Week 13 queue.
    """
    payload = dict(body or {})
    confirmation_id = payload.get("confirmation_id")
    if not isinstance(confirmation_id, str) or not confirmation_id:
        raise HTTPException(status_code=409, detail="Unknown confirmation.")

    # Read without consuming. A decision is only spent once this call is
    # certain it can succeed, so a retriable refusal below leaves the
    # commander's confirmation intact and usable.
    outcome = week13.peek_confirmation_outcome(
        confirmation_id,
        expected_action_type=ACTIVITY_LOG_EXPORT_ACTION_TYPE,
    )

    if outcome is None:
        # Still awaiting the commander is a normal, non-authorizing state.
        # Correlated by action type so an unrelated pending confirmation is
        # never reported as this export's decision.
        pending = week13.peek_pending_confirmation(
            confirmation_id,
            expected_action_type=ACTIVITY_LOG_EXPORT_ACTION_TYPE,
        )
        if pending is not None:
            return {"status": "pending_commander_confirmation", "authorized": False}
        raise HTTPException(
            status_code=409,
            detail="No consumable commander decision for this confirmation.",
        )

    # Terminal decisions are spent here; the gate already audited them.
    if outcome == week13.CONFIRMATION_OUTCOME_CANCELED:
        week13.consume_confirmation_outcome(
            confirmation_id, expected_action_type=ACTIVITY_LOG_EXPORT_ACTION_TYPE
        )
        raise HTTPException(status_code=409, detail="Commander declined the export.")

    if outcome == week13.CONFIRMATION_OUTCOME_BLOCKED:
        week13.consume_confirmation_outcome(
            confirmation_id, expected_action_type=ACTIVITY_LOG_EXPORT_ACTION_TYPE
        )
        raise HTTPException(
            status_code=409,
            detail="The export proposal expired without a commander decision.",
        )

    if outcome != week13.CONFIRMATION_OUTCOME_CONFIRMED:
        raise HTTPException(status_code=409, detail="Export was not confirmed.")

    # Capacity is checked BEFORE the decision is spent, so a 503 is retriable.
    if _live_export_operations() >= _MAX_PENDING_EXPORTS:
        raise HTTPException(
            status_code=503,
            detail=(
                "Export ticket capacity reached; no ticket was issued and your "
                "confirmation is still valid. Retry once capacity frees."
            ),
        )

    scope = _DEFAULT_EXPORT_SCOPE
    reported_count = _coerce_reported_count(payload.get("entry_count"))
    backend_observed = _backend_observed_entries()
    export_id = uuid4().hex
    requested_at = _now()

    # The commander's confirmation was already audited by the gate at decision
    # time (ACTIVITY_LOG_EXPORT_PROPOSAL_CONFIRMED); do not duplicate it here.
    # Appending first means a failure leaves the decision unspent and retriable.
    _append(
        ActivityEntry(
            event_type=ACTIVITY_LOG_EXPORT_REQUESTED,
            timestamp=requested_at,
            summary=(
                "Activity Log export authorized after commander confirmation"
                f" | scope={scope}"
                f" | backend_observed_entries={backend_observed}"
                " | evidence=commander_confirmed"
                " | outbound=False"
            ),
            payload={
                "export_id": export_id,
                "confirmation_id": confirmation_id,
                "scope": scope,
                "stage": "requested",
                "evidence_class": "commander_confirmed",
                "backend_observed_log_entries": backend_observed,
                "client_reported_scope_count": reported_count,
                "destination": "local_file",
                "outbound": False,
                "redacted": True,
            },
            redaction_state="redacted",
            surface_origin="activity_log",
            source="commander_action",
        )
    )

    _pending_exports[export_id] = {
        "scope": scope,
        "confirmation_id": confirmation_id,
        "requested_at": requested_at,
        "expires_at": datetime.now(timezone.utc)
        + timedelta(seconds=_TICKET_TTL_SECONDS),
        "client_reported_scope_count": reported_count,
        "backend_observed_log_entries": backend_observed,
    }

    # Spend the decision only now that the proof entry is durable and the
    # ticket exists. Replay protection begins from this point.
    week13.consume_confirmation_outcome(
        confirmation_id, expected_action_type=ACTIVITY_LOG_EXPORT_ACTION_TYPE
    )
    logger.info(
        "activity_log_export_authorized",
        extra={"event_type": ACTIVITY_LOG_EXPORT_REQUESTED, "scope": scope},
    )
    return {
        "authorized": True,
        "export_id": export_id,
        "event_type": ACTIVITY_LOG_EXPORT_REQUESTED,
        "requested_at": requested_at,
        "scope": scope,
        "backend_observed_log_entries": backend_observed,
    }


@router.post("/export/result")
async def report_export_result(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Record the client-reported outcome of an authorized export.

    The ticket is consumed only after the proof entry is appended, so a failed
    append leaves the ticket intact and the client can safely retry instead of
    losing the audit record.
    """
    payload = dict(body or {})
    export_id = payload.get("export_id")
    outcome = str(payload.get("outcome") or "")

    # Enforce the ticket TTL at this boundary too, before any lookup. Without
    # this, a late result could resurrect an abandoned ticket simply because
    # no other endpoint had swept it yet.
    _expire_abandoned_tickets()

    if not isinstance(export_id, str) or export_id not in _pending_exports:
        raise HTTPException(
            status_code=409,
            detail="Unknown, expired, or already-reported export_id.",
        )
    if outcome not in _EXPORT_OUTCOMES:
        raise HTTPException(
            status_code=400,
            detail="outcome must be 'download_initiated' or 'failed'.",
        )

    ticket = _pending_exports[export_id]
    reported_at = _now()
    initiated = outcome == _OUTCOME_DOWNLOAD_INITIATED
    event_type = (
        ACTIVITY_LOG_EXPORT_DOWNLOAD_INITIATED
        if initiated
        else ACTIVITY_LOG_EXPORT_FAILED
    )
    evidence_class = (
        "client_reported_initiation" if initiated else "client_reported_failure"
    )
    summary = (
        "Activity Log export download initiated by the commander's browser"
        if initiated
        else "Activity Log export failed before any file was written"
    )

    # Append first. Only a durable proof entry may consume the ticket.
    _append(
        ActivityEntry(
            event_type=event_type,
            timestamp=reported_at,
            summary=(
                f"{summary}"
                f" | scope={ticket['scope']}"
                f" | evidence={evidence_class}"
                " | completion_observed=False"
                " | outbound=False"
            ),
            payload={
                "export_id": export_id,
                "confirmation_id": ticket["confirmation_id"],
                "scope": ticket["scope"],
                "stage": "download_initiated" if initiated else "failed",
                "evidence_class": evidence_class,
                # The backend cannot observe a browser download reaching disk.
                "completion_observed": False,
                "requested_at": ticket["requested_at"],
                "backend_observed_log_entries": ticket["backend_observed_log_entries"],
                "client_reported_scope_count": ticket["client_reported_scope_count"],
                "destination": "local_file",
                "outbound": False,
                "redacted": True,
            },
            redaction_state="redacted",
            surface_origin="activity_log",
            source="commander_action",
        )
    )
    del _pending_exports[export_id]  # single use, only after a durable record

    logger.info(
        "activity_log_export_result",
        extra={"event_type": event_type, "outcome": outcome},
    )
    return {
        "recorded": True,
        "event_type": event_type,
        "evidence_class": evidence_class,
        "completion_observed": False,
        "reported_at": reported_at,
    }
