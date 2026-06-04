"""
omnicovas.core.dispatcher

Central async event dispatcher for OmniCOVAS.

Routes journal events from the JournalWatcher to registered module handlers.
Also supports "raw recorders" that see every parsed event regardless of type
(used by the database persistence layer).

Architecture:
    JournalWatcher → raw JSONL line
    → EventDispatcher.dispatch() parses JSON
    → Routes to type-specific handlers (combat, navigation, etc.)
    → Also calls ALL registered raw recorders (database, logging)

Law 7 (Telemetry Rigidity):
    Every state update flows through this dispatcher.
    No assumptions. Only what telemetry confirms.

Law 6 (Performance Priority):
    Dispatcher never blocks. All handlers are async coroutines.
    Handler exceptions are caught and logged — never crash the loop.

Law 8 (Sovereignty & Transparency):
    Raw recorders see every event. Enables the black-box flight recorder.

See: Master Blueprint v4.0 Section 2 (Data Pipeline)
See: Phase 1 Development Guide Week 2-3
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

# Type-specific handler: receives parsed event dict
EventHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

# Raw recorder: receives parsed event dict AND original raw JSON line
RawRecorder = Callable[[dict[str, Any], str], Coroutine[Any, Any, None]]


class EventDispatcher:
    """
    Routes journal events to registered async handlers.

    Supports two kinds of subscribers:
    - Type-specific handlers (register) — fire only for matching event types
    - Raw recorders (register_recorder) — fire for every parsed event

    Handler exceptions are caught and logged — never crash the dispatcher.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._raw_recorders: list[RawRecorder] = []
        self._events_processed = 0

    def register(self, event_type: str, handler: EventHandler) -> None:
        """
        Register an async handler for a specific journal event type.

        Args:
            event_type: Journal event type string (e.g. 'FSDJump', 'Docked')
            handler: Async coroutine that accepts the full event dict
        """
        self._handlers[event_type].append(handler)
        logger.debug("Registered handler for event type: %s", event_type)

    def register_recorder(self, recorder: RawRecorder) -> None:
        """
        Register a raw recorder that receives every parsed event.

        Used by the database persistence layer to record the full event stream.

        Args:
            recorder: Async coroutine accepting (event_dict, raw_line)
        """
        self._raw_recorders.append(recorder)
        logger.debug("Registered raw recorder.")

    async def dispatch(self, raw_line: str) -> None:
        """
        Parse a raw JSONL line and route to registered handlers.

        Args:
            raw_line: Raw JSON string from the journal file

        Behavior:
            - Malformed JSON: logged as warning, silently skipped
            - Unknown event type: type handlers skipped (recorders still fire)
            - Handler exception: logged as error, dispatcher continues
        """
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed journal line: %s", raw_line[:120])
            return

        event_type = event.get("event", "Unknown")
        self._events_processed += 1

        logger.debug("Dispatching event #%d: %s", self._events_processed, event_type)

        # Fire raw recorders first (they record everything)
        for recorder in self._raw_recorders:
            try:
                await recorder(event, raw_line)
            except Exception as e:
                logger.error(
                    "Recorder error for event '%s': %s: %s",
                    event_type,
                    type(e).__name__,
                    e,
                    exc_info=True,
                )

        # Fire type-specific handlers
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error(
                    "Handler error for event '%s': %s: %s",
                    event_type,
                    type(e).__name__,
                    e,
                    exc_info=True,
                )

    @property
    def events_processed(self) -> int:
        """Total number of events dispatched since startup."""
        return self._events_processed
