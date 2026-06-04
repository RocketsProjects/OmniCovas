"""Local-first PvP encounter storage helpers.

This module owns durable commander-entered PvP encounter notes for PB04-05 E1A.
It does not infer facts, call external providers, or write UI-facing wording.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, Literal, TypedDict, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.event_types import (
    PVP_ENCOUNTER_BLOCKED,
    PVP_ENCOUNTER_CREATED,
    PVP_ENCOUNTER_DELETED,
    PVP_ENCOUNTER_LINKED,
    PVP_ENCOUNTER_UPDATED,
)
from omnicovas.db.models import PvpEncounter

PvpSourceLabel = Literal["journal", "status", "commander_entered"]
PvpEncounterType = Literal[
    "unknown",
    "interdicted_by",
    "killed_by",
    "killed",
    "witnessed",
    "commander_entered",
]

MAX_COMMANDER_NAME_LENGTH: Final[int] = 64
MAX_SYSTEM_LENGTH: Final[int] = 128
MAX_NOTE_LENGTH: Final[int] = 4000
MAX_RISK_EXPLANATION_LENGTH: Final[int] = 1000
MAX_BLOCK_REASON_LENGTH: Final[int] = 80
DEFAULT_LIMIT: Final[int] = 100
MAX_LIMIT: Final[int] = 500

VALID_SOURCE_LABELS: Final[frozenset[str]] = frozenset(
    {"journal", "status", "commander_entered"}
)
VALID_ENCOUNTER_TYPES: Final[frozenset[str]] = frozenset(
    {
        "unknown",
        "interdicted_by",
        "killed_by",
        "killed",
        "witnessed",
        "commander_entered",
    }
)


@dataclass(frozen=True)
class PvpEncounterCreate:
    """Input for creating a local PvP encounter record."""

    note: str
    timestamp: datetime | None = None
    commander_name: str | None = None
    system: str | None = None
    source_label: PvpSourceLabel = "commander_entered"
    encounter_type: PvpEncounterType = "commander_entered"
    risk_explanation: str | None = None
    provenance_event_type: str | None = None


class PvpEncounterUpdate(TypedDict, total=False):
    """Allowed partial update fields for a local PvP encounter record."""

    timestamp: datetime
    commander_name: str | None
    system: str | None
    note: str
    encounter_type: PvpEncounterType
    risk_explanation: str | None


@dataclass(frozen=True)
class PvpEncounterRecord:
    """Typed read model returned by the local store helpers."""

    id: int
    timestamp: datetime
    created_at: datetime
    updated_at: datetime
    commander_name: str | None
    system: str | None
    source_label: PvpSourceLabel
    encounter_type: PvpEncounterType
    note: str
    risk_explanation: str | None
    provenance_event_type: str | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _activity_timestamp() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _clean_required_text(value: str, *, field_name: str, max_length: int) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    if len(text) > max_length:
        raise ValueError(f"{field_name} is too long")
    return text


def _clean_optional_text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ValueError(f"{field_name} is too long")
    return text


def _clean_source_label(value: str) -> PvpSourceLabel:
    if value not in VALID_SOURCE_LABELS:
        raise ValueError("source_label is unsupported")
    return cast(PvpSourceLabel, value)


def _clean_encounter_type(value: str) -> PvpEncounterType:
    if value not in VALID_ENCOUNTER_TYPES:
        raise ValueError("encounter_type is unsupported")
    return cast(PvpEncounterType, value)


def _to_record(row: PvpEncounter) -> PvpEncounterRecord:
    return PvpEncounterRecord(
        id=int(row.id),
        timestamp=row.timestamp,
        created_at=row.created_at,
        updated_at=row.updated_at,
        commander_name=row.commander_name,
        system=row.system,
        source_label=_clean_source_label(row.source_label),
        encounter_type=_clean_encounter_type(row.encounter_type),
        note=row.note,
        risk_explanation=row.risk_explanation,
        provenance_event_type=row.provenance_event_type,
    )


def _append_activity(
    activity_log: ActivityLog | None,
    *,
    event_type: str,
    action: str,
    encounter_id: int | None,
    source_label: str,
) -> None:
    if activity_log is None:
        return

    id_part = f"id={encounter_id}" if encounter_id is not None else "id=unavailable"
    activity_log.append(
        ActivityEntry(
            event_type=event_type,
            timestamp=_activity_timestamp(),
            summary=f"Encounter note {action} ({id_part}, source={source_label})",
        )
    )


async def create_encounter(
    session_factory: async_sessionmaker[AsyncSession],
    payload: PvpEncounterCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> PvpEncounterRecord:
    """Create a local PvP encounter note and audit the write."""
    now = _utc_now()
    source_label = _clean_source_label(payload.source_label)
    encounter_type = _clean_encounter_type(payload.encounter_type)
    row = PvpEncounter(
        timestamp=payload.timestamp or now,
        created_at=now,
        updated_at=now,
        commander_name=_clean_optional_text(
            payload.commander_name,
            field_name="commander_name",
            max_length=MAX_COMMANDER_NAME_LENGTH,
        ),
        system=_clean_optional_text(
            payload.system,
            field_name="system",
            max_length=MAX_SYSTEM_LENGTH,
        ),
        source_label=source_label,
        encounter_type=encounter_type,
        note=_clean_required_text(
            payload.note,
            field_name="note",
            max_length=MAX_NOTE_LENGTH,
        ),
        risk_explanation=_clean_optional_text(
            payload.risk_explanation,
            field_name="risk_explanation",
            max_length=MAX_RISK_EXPLANATION_LENGTH,
        ),
        provenance_event_type=payload.provenance_event_type or PVP_ENCOUNTER_CREATED,
    )

    async with session_factory() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)

    _append_activity(
        activity_log,
        event_type=PVP_ENCOUNTER_CREATED,
        action="created",
        encounter_id=int(row.id),
        source_label=source_label,
    )
    return _to_record(row)


async def list_encounters(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[PvpEncounterRecord]:
    """Return local PvP encounter records, newest first."""
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError("limit is out of range")

    async with session_factory() as db:
        result = await db.execute(
            select(PvpEncounter)
            .order_by(PvpEncounter.timestamp.desc(), PvpEncounter.id.desc())
            .limit(limit)
        )
        rows = cast(list[PvpEncounter], result.scalars().all())

    return [_to_record(row) for row in rows]


async def get_encounter(
    session_factory: async_sessionmaker[AsyncSession],
    encounter_id: int,
) -> PvpEncounterRecord | None:
    """Return a local PvP encounter record by id, if it exists."""
    async with session_factory() as db:
        row = await db.get(PvpEncounter, encounter_id)

    return _to_record(row) if row is not None else None


async def update_encounter(
    session_factory: async_sessionmaker[AsyncSession],
    encounter_id: int,
    changes: PvpEncounterUpdate,
    *,
    activity_log: ActivityLog | None = None,
) -> PvpEncounterRecord | None:
    """Update allowed fields on a local PvP encounter note and audit the write."""
    async with session_factory() as db:
        row = await db.get(PvpEncounter, encounter_id)
        if row is None:
            return None

        if "timestamp" in changes:
            row.timestamp = changes["timestamp"]
        if "commander_name" in changes:
            row.commander_name = _clean_optional_text(
                changes["commander_name"],
                field_name="commander_name",
                max_length=MAX_COMMANDER_NAME_LENGTH,
            )
        if "system" in changes:
            row.system = _clean_optional_text(
                changes["system"],
                field_name="system",
                max_length=MAX_SYSTEM_LENGTH,
            )
        if "note" in changes:
            row.note = _clean_required_text(
                changes["note"],
                field_name="note",
                max_length=MAX_NOTE_LENGTH,
            )
        if "encounter_type" in changes:
            row.encounter_type = _clean_encounter_type(changes["encounter_type"])
        if "risk_explanation" in changes:
            row.risk_explanation = _clean_optional_text(
                changes["risk_explanation"],
                field_name="risk_explanation",
                max_length=MAX_RISK_EXPLANATION_LENGTH,
            )

        row.updated_at = _utc_now()
        row.provenance_event_type = PVP_ENCOUNTER_UPDATED
        source_label = row.source_label
        await db.commit()
        await db.refresh(row)

    _append_activity(
        activity_log,
        event_type=PVP_ENCOUNTER_UPDATED,
        action="updated",
        encounter_id=int(row.id),
        source_label=source_label,
    )
    return _to_record(row)


async def link_encounter_note(
    session_factory: async_sessionmaker[AsyncSession],
    encounter_id: int,
    note: str,
    *,
    activity_log: ActivityLog | None = None,
) -> PvpEncounterRecord | None:
    """Link or replace the commander note on an encounter and audit the write."""
    async with session_factory() as db:
        row = await db.get(PvpEncounter, encounter_id)
        if row is None:
            return None

        row.note = _clean_required_text(
            note,
            field_name="note",
            max_length=MAX_NOTE_LENGTH,
        )
        row.updated_at = _utc_now()
        row.provenance_event_type = PVP_ENCOUNTER_LINKED
        source_label = row.source_label
        await db.commit()
        await db.refresh(row)

    _append_activity(
        activity_log,
        event_type=PVP_ENCOUNTER_LINKED,
        action="linked",
        encounter_id=int(row.id),
        source_label=source_label,
    )
    return _to_record(row)


async def delete_encounter(
    session_factory: async_sessionmaker[AsyncSession],
    encounter_id: int,
    *,
    activity_log: ActivityLog | None = None,
) -> bool:
    """Delete a local PvP encounter record and audit the write."""
    async with session_factory() as db:
        row = await db.get(PvpEncounter, encounter_id)
        if row is None:
            return False

        source_label = row.source_label
        await db.delete(row)
        await db.commit()

    _append_activity(
        activity_log,
        event_type=PVP_ENCOUNTER_DELETED,
        action="deleted",
        encounter_id=encounter_id,
        source_label=source_label,
    )
    return True


def record_blocked_encounter(
    activity_log: ActivityLog | None,
    *,
    reason: str,
) -> None:
    """Audit a blocked PvP encounter write without storing private note text."""
    _clean_required_text(
        reason,
        field_name="reason",
        max_length=MAX_BLOCK_REASON_LENGTH,
    )
    _append_activity(
        activity_log,
        event_type=PVP_ENCOUNTER_BLOCKED,
        action="blocked",
        encounter_id=None,
        source_label="commander_entered",
    )


async def ensure_journal_pvp_encounter(
    session_factory: async_sessionmaker[AsyncSession],
    payload: PvpEncounterCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> PvpEncounterRecord:
    """Check for an existing journal-derived PvP record before creating.

    Deduplication key:
        - timestamp
        - commander_name
        - encounter_type
        - source_label
        - provenance_event_type

    If found, returns the existing record without writing a new Activity Log entry.
    If not found, creates a new record via create_encounter.
    """
    if payload.provenance_event_type is None:
        raise ValueError("provenance_event_type is required for journal encounters")

    source_label = _clean_source_label(payload.source_label)
    encounter_type = _clean_encounter_type(payload.encounter_type)
    ts = payload.timestamp or _utc_now()

    async with session_factory() as db:
        stmt = (
            select(PvpEncounter)
            .where(PvpEncounter.timestamp == ts)
            .where(PvpEncounter.commander_name == payload.commander_name)
            .where(PvpEncounter.encounter_type == encounter_type)
            .where(PvpEncounter.source_label == source_label)
            .where(PvpEncounter.provenance_event_type == payload.provenance_event_type)
            .limit(1)
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

    if existing:
        return _to_record(existing)

    return await create_encounter(
        session_factory,
        payload,
        activity_log=activity_log,
    )
