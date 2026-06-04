"""Ship-state broadcaster — Pillar 1 pub/sub backbone.

Architectural weight (Phase 2 Development Guide, Week 7 Part A):
    Every feature added after Week 7 — Module Health, Hull Triggers,
    Heat Management, Rebuy — consumes the broadcaster defined here.
    Design flaws compound for the rest of the phase.

Invariants (CLAUDE.md Pattern 1 — Event Broadcasting):
    1. Broadcast is async fire-and-forget. One slow subscriber must
       never block another. Sequential ``await`` is forbidden.
    2. Subscriber exceptions are caught inside ``_safe_dispatch``
       (Principle 5 — Graceful Failure). They never propagate to the
       publisher and never prevent sibling subscribers from running.
    3. Task references are retained in ``self._tasks`` to prevent the
       asyncio event loop from garbage-collecting mid-flight dispatches.
       A ``done_callback`` removes each task once it completes.
    4. Event types are the string constants in
       ``omnicovas.core.event_types``. No magic strings in handlers.

Seven-Layer Debugging Vocabulary:
    This file is layer 5 — broadcaster. It sits between layer 4 (state)
    and layer 6 (subscriber). Bugs here tend to surface as "the handler
    updated state but no subscriber reacted" — trace subscribe()
    registration order and event-type string identity first.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from omnicovas.core.logging_config import get_logger

logger = get_logger(__name__)


# --- Public types -----------------------------------------------------------


@dataclass(frozen=True)
class ShipStateEvent:
    """Typed envelope for every broadcast.

    Frozen to keep subscribers honest — the event object a subscriber
    receives is the same object every other subscriber receives.

    Attributes:
        event_type: One of the string constants in
            ``omnicovas.core.event_types``.
        timestamp: UTC instant the broadcast was constructed.
        payload: Event-specific data. Shape is documented per event
            type in the feature module that publishes it.
        source: Telemetry source of the underlying data.
            One of ``'journal'`` or ``'status_json'``. Obeys the
            Phase 1 source-priority order (journal > status_json >
            capi > eddn) when set by handlers.
    """

    event_type: str
    timestamp: datetime
    payload: dict[str, Any]
    source: str

    @classmethod
    def now(
        cls,
        event_type: str,
        payload: dict[str, Any],
        source: str,
    ) -> ShipStateEvent:
        """Construct an event stamped with the current UTC time.

        Convenience for handlers so that ``datetime.now(timezone.utc)``
        appears once here rather than in every feature module.
        """
        return cls(
            event_type=event_type,
            timestamp=datetime.now(timezone.utc),
            payload=payload,
            source=source,
        )


# Handlers are async callables that accept a single event and return None.
# Named alias keeps ``subscribe`` signatures readable and mypy-strict clean.
Subscriber = Callable[[ShipStateEvent], Awaitable[None]]


# --- Broadcaster ------------------------------------------------------------


class ShipStateBroadcaster:
    """Async pub/sub broadcaster for Pillar 1 derived events.

    Construction:
        One instance per process, created in ``main()`` alongside the
        ``StateManager``. Every handler receives the same reference via
        dependency injection. Constructing a broadcaster inside a
        handler is a bug — it creates a parallel pub/sub tree whose
        subscribers will never see broadcasts from any other handler.

    Example:
        >>> broadcaster = ShipStateBroadcaster()
        >>> broadcaster.subscribe(HULL_CRITICAL_25, activity_log_sink)
        >>> event = ShipStateEvent.now(
        ...     HULL_CRITICAL_25, {"hull": 22.5}, source="journal"
        ... )
        >>> await broadcaster.publish(HULL_CRITICAL_25, event)
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Subscriber]] = {}
        # Retain task references — otherwise the loop may GC an
        # in-flight dispatch before it completes.
        self._tasks: set[asyncio.Task[None]] = set()

    def subscribe(self, event_type: str, handler: Subscriber) -> None:
        """Register *handler* for *event_type*.

        Subscribers should be registered before the first journal event
        arrives — typically in ``main()`` wiring. There is no replay
        buffer; registrations after the first broadcast silently miss
        earlier events. This is deliberate and documented.
        """
        self._subscribers.setdefault(event_type, []).append(handler)
        logger.debug(
            "subscriber_registered",
            event_type=event_type,
            subscriber=_name_of(handler),
            total_for_event=len(self._subscribers[event_type]),
        )

    async def publish(self, event_type: str, event: ShipStateEvent) -> None:
        """Fire-and-forget broadcast of *event* to every subscriber.

        Returns as soon as every dispatch task is *scheduled*, not when
        it completes. Subscribers run concurrently. A slow or crashing
        subscriber cannot delay or break another.

        Publish with no subscribers is a no-op — this is valid and
        expected (e.g. publishing WANTED before any UI has wired up).
        """
        subscribers = self._subscribers.get(event_type, [])
        if not subscribers:
            return

        for subscriber in subscribers:
            task = asyncio.create_task(
                self._safe_dispatch(subscriber, event),
                name=f"broadcast:{event_type}:{_name_of(subscriber)}",
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _safe_dispatch(
        self,
        subscriber: Subscriber,
        event: ShipStateEvent,
    ) -> None:
        """Invoke *subscriber* with *event*, isolating any exception.

        Principle 5 — Graceful Failure. A subscriber raising is logged
        with full traceback via ``logger.exception`` but never
        re-raised. Sibling subscribers are unaffected because each runs
        in its own task.

        The broad ``except Exception`` is deliberate — this is the
        subscriber-isolation boundary. Do not narrow it.
        """
        try:
            await subscriber(event)
        except Exception:
            logger.exception(
                "subscriber_failed",
                subscriber=_name_of(subscriber),
                event_type=event.event_type,
                event_source=event.source,
            )


# --- Internal helpers -------------------------------------------------------


def _name_of(handler: Subscriber) -> str:
    """Best-effort readable name for logs. Works for functions, methods,
    and partials without raising on exotic callables."""
    name = getattr(handler, "__qualname__", None) or getattr(handler, "__name__", None)
    return str(name) if name is not None else repr(handler)
