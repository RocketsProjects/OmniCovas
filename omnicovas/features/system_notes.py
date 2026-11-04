"""Commander-authored system notes — LNA-004 notes slice.

The rest of the visited-system history is derived: arrivals, dockings, and
source events are all read back out of the flight recorder. This is the one
part a Commander writes themselves, which changes what the service owes it.

Law 8 (Sovereignty & Transparency):
    Authored text is the Commander's own data. It is stored locally, exported
    on demand, and destroyed on demand — and destroying all of it is a
    protected action, because nothing else in the app can reconstruct it.

Deliberately outside Commander Memory. Memory is derived and a rebuild
deletes and re-derives every record; a note attached there would be erased by
a routine maintenance action the Commander was told is safe.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.event_types import (
    SYSTEM_NOTE_CLEARED_ALL,
    SYSTEM_NOTE_DELETED,
    SYSTEM_NOTE_EXPORTED,
    SYSTEM_NOTE_WRITTEN,
)
from omnicovas.db.models import CommanderSystemNote

logger = logging.getLogger(__name__)

NOTE_MAX_LENGTH = 4000
SYSTEM_NAME_MAX_LENGTH = 128
SOURCE_SYSTEM_NOTES = "commander_authored_local_db"
TRUTH_COMMANDER_AUTHORED = "commander_authored"
NOTE_CAVEAT = (
    "Written by the Commander on this machine. Authored text, never observed "
    "telemetry: it is not a source of game fact and never outranks live local "
    "state."
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def normalize_system(value: Any) -> str:
    """Return a usable system name, or "" when the input cannot identify one."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:SYSTEM_NAME_MAX_LENGTH]


def normalize_note(value: Any) -> str:
    """Return the note text bounded to a storable length."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:NOTE_MAX_LENGTH]


class SystemNoteService:
    """Single owner of Commander-authored system notes."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        activity_log: ActivityLog | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._activity_log = activity_log

    def _log(self, event_type: str, summary: str, payload: dict[str, Any]) -> None:
        """Record proof without ever copying the authored text into the log."""
        if self._activity_log is None:
            return
        self._activity_log.append(
            ActivityEntry(
                event_type=event_type,
                timestamp=_iso(_utcnow()) or "",
                summary=summary,
                payload={**payload, "redacted": True},
                source_chain=[
                    {
                        "source": SOURCE_SYSTEM_NOTES,
                        "truth_class": TRUTH_COMMANDER_AUTHORED,
                    }
                ],
                redaction_state="redacted",
                surface_origin="intel",
                source=SOURCE_SYSTEM_NOTES,
            )
        )

    async def notes_for(self, systems: list[str]) -> dict[str, dict[str, Any]]:
        """Return notes keyed by system for the given names (bounded lookup)."""
        if not systems:
            return {}
        async with self._session_factory() as db:
            rows = (
                await db.execute(
                    select(CommanderSystemNote).where(
                        CommanderSystemNote.star_system.in_(systems)
                    )
                )
            ).scalars()
            return {
                row.star_system: {
                    "note": row.note,
                    "created_at": _iso(row.created_at),
                    "updated_at": _iso(row.updated_at),
                }
                for row in rows
            }

    async def list_notes(self) -> dict[str, Any]:
        async with self._session_factory() as db:
            rows = (
                (
                    await db.execute(
                        select(CommanderSystemNote).order_by(
                            CommanderSystemNote.updated_at.desc()
                        )
                    )
                )
                .scalars()
                .all()
            )
        return {
            "generated_at": _iso(_utcnow()),
            "source": SOURCE_SYSTEM_NOTES,
            "truth_class": TRUTH_COMMANDER_AUTHORED,
            "caveat": NOTE_CAVEAT,
            "returned": len(rows),
            "notes": [
                {
                    "star_system": row.star_system,
                    "note": row.note,
                    "created_at": _iso(row.created_at),
                    "updated_at": _iso(row.updated_at),
                }
                for row in rows
            ],
            "nullprovider_safe": True,
        }

    async def write(self, star_system: str, note: str) -> dict[str, Any]:
        """Create or replace the note for *star_system*.

        Empty text removes the note: clearing the box is how a Commander
        deletes their own sentence, and leaving an empty row behind would
        misreport the system as annotated.
        """
        system = normalize_system(star_system)
        if not system:
            raise ValueError("star_system is required")
        text = normalize_note(note)
        if not text:
            return await self.delete(system)

        async with self._session_factory() as db:
            row = await db.scalar(
                select(CommanderSystemNote).where(
                    CommanderSystemNote.star_system == system
                )
            )
            now = _utcnow()
            created = row is None
            if row is None:
                db.add(
                    CommanderSystemNote(
                        star_system=system,
                        note=text,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                row.note = text
                row.updated_at = now
            await db.commit()

        self._log(
            SYSTEM_NOTE_WRITTEN,
            "Commander system note saved",
            {
                "star_system": system,
                "created": created,
                # Length only: the text itself is the Commander's, and proof
                # does not need to repeat it to prove the write happened.
                "note_length": len(text),
            },
        )
        return {
            "star_system": system,
            "note": text,
            "created": created,
            "deleted": False,
        }

    async def delete(self, star_system: str) -> dict[str, Any]:
        """Remove the note for one system. Absent is not an error."""
        system = normalize_system(star_system)
        if not system:
            raise ValueError("star_system is required")
        async with self._session_factory() as db:
            existing = await db.scalar(
                select(func.count())
                .select_from(CommanderSystemNote)
                .where(CommanderSystemNote.star_system == system)
            )
            await db.execute(
                delete(CommanderSystemNote).where(
                    CommanderSystemNote.star_system == system
                )
            )
            await db.commit()
        removed = int(existing or 0)
        if removed:
            self._log(
                SYSTEM_NOTE_DELETED,
                "Commander system note deleted",
                {"star_system": system},
            )
        return {
            "star_system": system,
            "note": None,
            "created": False,
            "deleted": bool(removed),
        }

    async def count(self) -> int:
        async with self._session_factory() as db:
            return int(
                await db.scalar(select(func.count()).select_from(CommanderSystemNote))
                or 0
            )

    async def clear_all(self) -> int:
        """Destroy every authored note. Protected: nothing can rebuild these."""
        async with self._session_factory() as db:
            existing = await db.scalar(
                select(func.count()).select_from(CommanderSystemNote)
            )
            await db.execute(delete(CommanderSystemNote))
            await db.commit()
        removed = int(existing or 0)
        self._log(
            SYSTEM_NOTE_CLEARED_ALL,
            "All Commander system notes cleared",
            {"deleted_notes": removed},
        )
        return removed

    async def export_payload(self) -> dict[str, Any]:
        """Return every note for local download, and record that it happened."""
        payload = await self.list_notes()
        self._log(
            SYSTEM_NOTE_EXPORTED,
            "Commander system notes export staged for local download",
            {"note_count": payload["returned"], "destination": "local_file"},
        )
        return payload
