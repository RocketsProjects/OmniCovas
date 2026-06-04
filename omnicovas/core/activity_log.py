# omnicovas/core/activity_log.py
"""omnicovas/core/activity_log

Activity Log — in-memory ring buffer for critical Pillar 1 events.
Used by Feature 7 (Critical Event Broadcaster).
subscribe_critical_events() registers one subscriber per critical event type.
ActivityLog is instantiated once in main() and shared; do not create inside handlers.
Ref: Phase 2 Development Guide Week 9, Part B
Ref: Master Blueprint v4.2 — Pillar 1, Feature 7
Law 8: every critical event must be visible to the commander.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final

from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import (
    CRITICAL_EVENT_TYPES,
    EXTERNAL_REQUEST_BLOCKED,
    EXTERNAL_REQUEST_QUEUED,
    PHASE_9_SOURCE_ATTEMPT_BLOCKED,
    SOURCE_CACHE_HIT,
    SOURCE_CHAIN_RESOLVED,
    SOURCE_RATE_LIMITED,
    SOURCE_STALE_CACHE_USE,
)
from omnicovas.core.provenance import FreshnessLabel

logger = logging.getLogger(__name__)

PHASE_9_SOURCE_ATTEMPT_BLOCKED_REASONS: Final[frozenset[str]] = frozenset(
    {"disabled", "requires_auth", "unsupported", "no_verified_source"}
)

PHASE_9_FALLBACK_WORDING: Final[dict[str, str]] = {
    "disabled": "Disabled",
    "requires_auth": "Requires Authorization",
    "unsupported": "Unsupported",
    "no_verified_source": "No Verified Source",
}

_PHASE_9_FORBIDDEN_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "raw_journal",
        "journal_json",
        "journal_payload",
        "provider_payload",
        "provider_response",
        "credentials",
        "credential",
        "token",
        "oauth_token",
        "api_key",
        "authorization",
        "title",
        "description",
        "blockers",
        "next_actions",
        "commander_notes",
        "commander_note",
        "note_text",
        "system_name",
        "draft_text",
        "cmdr",
        "commander_name",
        "squadron_member_id",
        "external_handle",
    }
)


@dataclass(frozen=True)
class ActivityEntry:
    """Single entry in the activity log.

    Attributes:
        event_type: One of the string constants in
            ``omnicovas.core.event_types``.
        timestamp: ISO datetime string from
            ``ShipStateEvent.timestamp.isoformat()``.
    summary: Human-readable summary of the event.
    """

    event_type: str
    timestamp: str
    summary: str
    payload: dict[str, Any] | None = None
    source_chain: list[dict[str, Any]] | None = None
    redaction_state: str | None = None
    is_fact: bool = True
    linked_entity_refs: dict[str, Any] | None = None
    surface_origin: str | None = None
    correlation_id: str | None = None
    event_id: str | None = None
    source: str | None = None


class ActivityLog:
    """Ring buffer for critical Pillar 1 events.

    Construction:
        One instance per process, created in ``main()`` alongside the
        ``StateManager`` and ``ShipStateBroadcaster``. Every critical
        event subscriber appends to the same instance.

    Example:
        >>> log = ActivityLog(maxlen=100)
        >>> subscribe_critical_events(log, broadcaster)
    """

    def __init__(self, maxlen: int = 100) -> None:
        self._entries: deque[ActivityEntry] = deque(maxlen=maxlen)

    def append(self, entry: ActivityEntry) -> None:
        """Append *entry* to the log.

        The deque automatically discards the oldest entry when the
        maxlen is reached.
        """
        self._entries.append(entry)

    def entries(self) -> list[ActivityEntry]:
        """Return a copy of all entries in order (oldest first)."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


def _phase9_payload_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_")


def _strip_forbidden_phase9_keys(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_forbidden_phase9_keys(item)
            for key, item in value.items()
            if _phase9_payload_key(key) not in _PHASE_9_FORBIDDEN_PAYLOAD_KEYS
        }
    if isinstance(value, list):
        return [_strip_forbidden_phase9_keys(item) for item in value]
    return value


def _redact_phase9_secret_text(value: object) -> str:
    text = str(value)
    lowered = text.lower()
    secret_markers = (
        "api_key",
        "apikey",
        "authorization",
        "oauth",
        "token",
        "credential",
    )
    if any(marker in lowered for marker in secret_markers):
        return "[redacted]"
    return text


def normalize_phase9_payload(
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a redacted Phase 9 payload with forbidden raw fields removed."""
    normalized = _strip_forbidden_phase9_keys(dict(payload or {}))
    if not isinstance(normalized, dict):
        normalized = {}
    normalized["redacted"] = True
    return normalized


def build_phase9_source_attempt_blocked_payload(
    *,
    workflow_type: str,
    requested_fact: str,
    candidate_sources: list[str],
    blocked_reason: str,
    fallback_wording_shown: str | None = None,
    source_chain: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build PB09-07 source-attempt blocked proof payload without provider calls."""
    if blocked_reason not in PHASE_9_SOURCE_ATTEMPT_BLOCKED_REASONS:
        allowed = ", ".join(sorted(PHASE_9_SOURCE_ATTEMPT_BLOCKED_REASONS))
        raise ValueError(f"blocked_reason must be one of: {allowed}")

    safe_source_chain = source_chain or [
        {
            "source": "source_routing",
            "truth_class": "blocked_source_attempt",
            "freshness": "not_loaded",
            "workflow_type": workflow_type,
            "blocked_reason": blocked_reason,
        }
    ]
    return normalize_phase9_payload(
        {
            "workflow_type": workflow_type,
            "requested_fact": _redact_phase9_secret_text(requested_fact),
            "candidate_sources": [
                _redact_phase9_secret_text(source) for source in candidate_sources
            ],
            "blocked_reason": blocked_reason,
            "fallback_wording_shown": fallback_wording_shown
            or PHASE_9_FALLBACK_WORDING[blocked_reason],
            "source_chain": safe_source_chain,
            "redaction_state": "redacted",
        }
    )


def log_phase9_source_attempt_blocked(
    activity_log: ActivityLog | None,
    *,
    workflow_type: str,
    requested_fact: str,
    candidate_sources: list[str],
    blocked_reason: str,
    fallback_wording_shown: str | None = None,
    source_chain: list[dict[str, Any]] | None = None,
) -> None:
    """Record a redacted Phase 9 source-attempt blocked proof entry."""
    if activity_log is None:
        return
    payload = build_phase9_source_attempt_blocked_payload(
        workflow_type=workflow_type,
        requested_fact=requested_fact,
        candidate_sources=candidate_sources,
        blocked_reason=blocked_reason,
        fallback_wording_shown=fallback_wording_shown,
        source_chain=source_chain,
    )
    entry_source_chain = payload.get("source_chain")
    activity_log.append(
        ActivityEntry(
            event_type=PHASE_9_SOURCE_ATTEMPT_BLOCKED,
            timestamp=_source_timestamp(),
            summary=(
                "Phase 9 source attempt blocked"
                f" | workflow_type={workflow_type}"
                f" | requested_fact={requested_fact}"
                f" | blocked_reason={blocked_reason}"
                f" | fallback={payload['fallback_wording_shown']}"
                " | redacted=True"
            ),
            payload=payload,
            source_chain=entry_source_chain
            if isinstance(entry_source_chain, list)
            else None,
            redaction_state="redacted",
            is_fact=False,
            surface_origin="activity_log",
            source="external_disabled",
        )
    )


def subscribe_critical_events(
    activity_log: ActivityLog,
    broadcaster: ShipStateBroadcaster,
) -> None:
    """Register activity_log as subscriber for all CRITICAL_EVENT_TYPES.

    Args:
        activity_log: Shared ActivityLog instance.
        broadcaster: Shared ShipStateBroadcaster instance.
    """

    async def _log_critical(event: ShipStateEvent) -> None:
        activity_log.append(
            ActivityEntry(
                event_type=event.event_type,
                timestamp=event.timestamp.isoformat(),
                summary=event.event_type,
            )
        )
        logger.warning(
            "critical_event: %s",
            event.event_type,
            extra={"event_type": event.event_type, "category": "critical"},
        )

    for event_type in CRITICAL_EVENT_TYPES:
        broadcaster.subscribe(event_type, _log_critical)
    logger.info(
        "Critical Event Broadcaster: activity_log subscribed to %d critical types",
        len(CRITICAL_EVENT_TYPES),
    )


# ---------------------------------------------------------------------------
# Phase 5 — source-chain proof record helpers (PB05-02 Stage D)
#
# Each helper appends one ActivityEntry to an optional ActivityLog.
# All are no-ops when activity_log is None (optional dependency pattern).
# Summaries are generic source-chain proof records — no provider specifics.
# ---------------------------------------------------------------------------


def _source_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_source_chain_resolved(
    activity_log: ActivityLog | None,
    *,
    source_id: str,
    call_type: str,
    workflow_id: str,
    freshness_label: FreshnessLabel,
) -> None:
    """Record that a source chain was resolved for a workflow."""
    if activity_log is None:
        return
    activity_log.append(
        ActivityEntry(
            event_type=SOURCE_CHAIN_RESOLVED,
            timestamp=_source_timestamp(),
            summary=(
                f"Source chain resolved: source={source_id}, call_type={call_type}, "
                f"workflow_id={workflow_id}, freshness={freshness_label.value}"
            ),
        )
    )


def log_external_request_queued(
    activity_log: ActivityLog | None,
    *,
    source_id: str,
    call_type: str,
    workflow_id: str,
) -> None:
    """Record that an external request was queued (no outbound call yet)."""
    if activity_log is None:
        return
    activity_log.append(
        ActivityEntry(
            event_type=EXTERNAL_REQUEST_QUEUED,
            timestamp=_source_timestamp(),
            summary=(
                f"External request queued: source={source_id}, call_type={call_type}, "
                f"workflow_id={workflow_id}"
            ),
        )
    )


def log_external_request_blocked(
    activity_log: ActivityLog | None,
    *,
    source_id: str,
    call_type: str,
    workflow_id: str,
    blocked_reason: str,
) -> None:
    """Record that an external request was blocked before dispatch."""
    if activity_log is None:
        return
    activity_log.append(
        ActivityEntry(
            event_type=EXTERNAL_REQUEST_BLOCKED,
            timestamp=_source_timestamp(),
            summary=(
                f"External request blocked: source={source_id}, call_type={call_type}, "
                f"workflow_id={workflow_id}, reason={blocked_reason}"
            ),
        )
    )


def log_source_rate_limited(
    activity_log: ActivityLog | None,
    *,
    source_id: str,
    call_type: str,
    workflow_id: str,
) -> None:
    """Record that a source request was rate-limited."""
    if activity_log is None:
        return
    activity_log.append(
        ActivityEntry(
            event_type=SOURCE_RATE_LIMITED,
            timestamp=_source_timestamp(),
            summary=(
                f"Source rate-limited: source={source_id}, call_type={call_type}, "
                f"workflow_id={workflow_id}"
            ),
        )
    )


def log_cache_hit(
    activity_log: ActivityLog | None,
    *,
    source_id: str,
    call_type: str,
    workflow_id: str,
    freshness_label: FreshnessLabel,
) -> None:
    """Record a cache hit for commander-relevant freshness tracking."""
    if activity_log is None:
        return
    activity_log.append(
        ActivityEntry(
            event_type=SOURCE_CACHE_HIT,
            timestamp=_source_timestamp(),
            summary=(
                f"Cache hit: source={source_id}, call_type={call_type}, "
                f"workflow_id={workflow_id}, freshness={freshness_label.value}"
            ),
        )
    )


def log_stale_cache_use(
    activity_log: ActivityLog | None,
    *,
    source_id: str,
    call_type: str,
    workflow_id: str,
    freshness_label: FreshnessLabel,
) -> None:
    """Record that a stale cache entry was used — commander-relevant."""
    if activity_log is None:
        return
    activity_log.append(
        ActivityEntry(
            event_type=SOURCE_STALE_CACHE_USE,
            timestamp=_source_timestamp(),
            summary=(
                f"Stale cache used: source={source_id}, call_type={call_type}, "
                f"workflow_id={workflow_id}, freshness={freshness_label.value}"
            ),
        )
    )
