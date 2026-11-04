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

import hashlib
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
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


def _event_fingerprint(timestamp: datetime, event_type: str, raw_line: str) -> str:
    """Identity of one recorded journal line within its session.

    The raw line is included so two genuinely distinct events sharing a
    timestamp and type stay distinct; only a byte-identical replay of the same
    line is treated as already recorded.
    """
    # Live events carry UTC tzinfo while the column returns naive datetimes, so
    # normalise before hashing or a replay never matches what it replays.
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
    payload = f"{timestamp.isoformat()}|{event_type}|{raw_line}"
    return hashlib.sha256(payload.encode("utf-8", "replace")).hexdigest()


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
        # How many copies of each already-persisted line the resumed session
        # holds. The watcher catches a journal up from the beginning on every
        # attach, so a replayed line must be reconciled against what is stored
        # rather than inserted again. It is a budget, not a permanent filter:
        # a journal may legitimately contain the same line more than once, and
        # once the stored copies are accounted for, further occurrences record
        # normally.
        self._already_stored: Counter[str] = Counter()

    async def start_session(self, journal_filename: str) -> int:
        """
        Open the session for *journal_filename*, resuming it when it exists.

        Elite writes one journal per play session, so the journal file — not
        the app launch — is what identifies a session. Relaunching OmniCOVAS
        while the same journal is current resumes that session instead of
        forking a second one; otherwise every restart added a duplicate
        session whose events were re-read from the top of the file, inflating
        every recorded count by the number of restarts.

        Args:
            journal_filename: Name of the journal file for this session

        Returns:
            The session ID assigned by the database
        """
        async with self._session_factory() as db:
            session_row = await db.scalar(
                select(Session)
                .where(Session.journal_filename == journal_filename)
                .order_by(Session.start_time.desc(), Session.id.desc())
                .limit(1)
            )
            resumed = session_row is not None
            if session_row is None:
                session_row = Session(
                    start_time=datetime.now(timezone.utc),
                    journal_filename=journal_filename,
                )
                db.add(session_row)
                await db.commit()
                await db.refresh(session_row)
            session_id = int(session_row.id)

            self._current_session_id = session_id
            self._already_stored = Counter()
            if resumed:
                # A resumed session is about to be caught up from the top of
                # the file; count what is already stored so the replay adds
                # only genuinely new lines.
                for timestamp, event_type, raw_json in (
                    await db.execute(
                        select(
                            JournalEvent.timestamp,
                            JournalEvent.event_type,
                            JournalEvent.raw_json,
                        ).where(JournalEvent.session_id == session_id)
                    )
                ).all():
                    self._already_stored[
                        _event_fingerprint(timestamp, event_type, raw_json)
                    ] += 1
                # A resumed session is live again, so a previously stamped end
                # is no longer true.
                if session_row.end_time is not None:
                    session_row.end_time = None
                    await db.commit()

            logger.info(
                "%s DB session id=%d for %s (%d events already recorded)",
                "Resumed" if resumed else "Started",
                session_id,
                journal_filename,
                sum(self._already_stored.values()),
            )
            return session_id

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

        fingerprint = _event_fingerprint(timestamp, event_type, raw_line)
        if self._already_stored.get(fingerprint, 0) > 0:
            # A catch-up replay of a line this session already holds. Spend one
            # stored copy rather than inserting a duplicate.
            self._already_stored[fingerprint] -= 1
            return

        async with self._session_factory() as db:
            event_row = JournalEvent(
                session_id=self._current_session_id,
                timestamp=timestamp,
                event_type=event_type,
                raw_json=raw_line,
            )
            db.add(event_row)
            if event_type in {"LoadGame", "Commander", "NewCommander"}:
                session_row = await db.get(Session, self._current_session_id)
                if session_row is not None:
                    commander_name = event.get("Commander") or event.get("Name")
                    ship_type = event.get("Ship")
                    if isinstance(commander_name, str) and commander_name.strip():
                        session_row.commander_name = commander_name.strip()[:64]
                    if isinstance(ship_type, str) and ship_type.strip():
                        session_row.ship_type = ship_type.strip()[:64]
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
