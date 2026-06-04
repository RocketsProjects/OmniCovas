"""
omnicovas.db.recorder

Persists journal events to the session database.

Every event that passes through the dispatcher gets a permanent record.
This is the black-box flight recorder — full replay/audit capability.

Law 8 (Sovereignty & Transparency):
    All events persisted locally. Nothing leaves the machine.
    Commander can delete the database at any time via the UI or File Explorer.

See: Phase 1 Development Guide Week 3, Part B
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import JournalEvent, Session

logger = logging.getLogger(__name__)


def _parse_timestamp(ts: str | None) -> datetime:
    """
    Parse a journal timestamp string into a datetime.

    Args:
        ts: ISO 8601 timestamp string (or None)

    Returns:
        Parsed datetime (UTC now if ts is None or malformed)
    """
    if ts is None:
        return datetime.now(timezone.utc)
    try:
        # Journal timestamps are UTC: "2026-04-18T13:41:44Z"
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


class EventRecorder:
    """
    Persists dispatched events to the session database.

    Usage:
        recorder = EventRecorder(session_factory)
        await recorder.start_session(journal_filename="Journal.abc.log")
        dispatcher.register_all_events(recorder.record_event)
        # ... events accumulate ...
        await recorder.end_session()

    See: Phase 1 Development Guide Week 3, Part B
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._current_session_id: int | None = None
        self._events_recorded = 0

    async def start_session(self, journal_filename: str) -> int:
        """
        Start a new session in the database.

        Args:
            journal_filename: Name of the journal file that started this session

        Returns:
            The session ID assigned by the database
        """
        async with self._session_factory() as db:
            session_row = Session(
                start_time=datetime.now(timezone.utc),
                journal_filename=journal_filename,
            )
            db.add(session_row)
            await db.commit()
            await db.refresh(session_row)
            self._current_session_id = int(session_row.id)
            logger.info(
                "Started DB session id=%d for %s",
                session_row.id,
                journal_filename,
            )
            return int(session_row.id)

    async def record_event(self, event: dict[str, Any], raw_line: str) -> None:
        """
        Persist a single event to the database.

        Args:
            event: Parsed event dict (must contain 'event' and 'timestamp')
            raw_line: Original raw JSON line for full fidelity replay

        Law 8: every event logged — this is the audit trail.
        """
        if self._current_session_id is None:
            logger.warning("record_event called with no active session — event dropped")
            return

        event_type = event.get("event", "Unknown")
        timestamp = _parse_timestamp(event.get("timestamp"))

        async with self._session_factory() as db:
            event_row = JournalEvent(
                session_id=self._current_session_id,
                timestamp=timestamp,
                event_type=event_type,
                raw_json=raw_line,
            )
            db.add(event_row)
            await db.commit()
            self._events_recorded += 1

    async def end_session(self) -> None:
        """
        Close the current session by stamping end_time.
        """
        if self._current_session_id is None:
            return

        async with self._session_factory() as db:
            session_row = await db.get(Session, self._current_session_id)
            if session_row is not None:
                session_row.end_time = datetime.now(timezone.utc)
                await db.commit()
                logger.info(
                    "Closed DB session id=%d (%d events recorded)",
                    self._current_session_id,
                    self._events_recorded,
                )

        self._current_session_id = None
        self._events_recorded = 0

    @property
    def events_recorded(self) -> int:
        """Number of events recorded in the current session."""
        return self._events_recorded
