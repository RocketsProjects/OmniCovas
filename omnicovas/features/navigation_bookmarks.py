"""Local Navigation bookmark and saved route persistence helpers.

This module owns durable commander-managed Navigation artifacts for PB05-09.
It does not infer facts, call external providers, or execute game actions.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final, TypedDict, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import (
    ActivityEntry,
    ActivityLog,
    normalize_phase9_payload,
)
from omnicovas.core.event_types import (
    NAVIGATION_BOOKMARK_CREATED,
    NAVIGATION_BOOKMARK_DELETED,
    NAVIGATION_BOOKMARK_UPDATED,
    NAVIGATION_SAVED_ROUTE_CREATED,
    NAVIGATION_SAVED_ROUTE_DELETED,
    NAVIGATION_SAVED_ROUTE_UPDATED,
    PHASE_9_NAVIGATION_BOOKMARK_TAGGED,
)
from omnicovas.db.models import BookmarkRef, SavedRouteRef

MAX_LABEL_LENGTH: Final[int] = 64
MAX_TARGET_NAME_LENGTH: Final[int] = 128
MAX_SYSTEM_NAME_LENGTH: Final[int] = 128
MAX_NOTE_LENGTH: Final[int] = 4000
DEFAULT_LIMIT: Final[int] = 100
MAX_LIMIT: Final[int] = 500

# Phase 9 bookmark tag vocabulary — local-only metadata.
VALID_BOOKMARK_TAGS: Final[frozenset[str]] = frozenset(
    {"bgs_target", "powerplay_target"}
)


@dataclass(frozen=True)
class BookmarkCreate:
    """Input for creating a local Navigation bookmark."""

    label: str
    entity_type: str
    target_name: str
    target_system_address: int | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    commander_note: str | None = None
    tags: list[str] | None = None


class BookmarkUpdate(TypedDict, total=False):
    """Allowed partial update fields for a local Navigation bookmark."""

    label: str
    commander_note: str | None
    tags: list[str]


@dataclass(frozen=True)
class BookmarkRecord:
    """Typed read model for a local Navigation bookmark."""

    id: int
    label: str
    entity_type: str
    target_name: str
    target_system_address: int | None
    x: float | None
    y: float | None
    z: float | None
    commander_note: str | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class SavedRouteCreate:
    """Input for creating a local saved route record."""

    label: str
    origin: str
    destination: str
    hop_count: int
    source_id: str
    commander_note: str | None = None


class SavedRouteUpdate(TypedDict, total=False):
    """Allowed partial update fields for a local saved route record."""

    label: str
    commander_note: str | None


@dataclass(frozen=True)
class SavedRouteRecord:
    """Typed read model for a local saved route record."""

    id: int
    label: str
    origin: str
    destination: str
    hop_count: int
    source_id: str
    commander_note: str | None
    created_at: datetime
    updated_at: datetime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _activity_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


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


def _parse_tags(tags_json: str | None) -> list[str]:
    if not tags_json:
        return []
    try:
        raw = json.loads(tags_json)
        return [str(t) for t in raw] if isinstance(raw, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _validate_tags(tags: list[str]) -> list[str]:
    for tag in tags:
        if tag not in VALID_BOOKMARK_TAGS:
            raise ValueError(
                f"tag {tag!r} is not a valid bookmark tag; "
                f"valid tags: {sorted(VALID_BOOKMARK_TAGS)}"
            )
    return list(dict.fromkeys(tags))  # deduplicate, preserve order


def _to_bookmark_record(row: BookmarkRef) -> BookmarkRecord:
    return BookmarkRecord(
        id=int(row.id),
        label=row.label,
        entity_type=row.entity_type,
        target_name=row.target_name,
        target_system_address=row.target_system_address,
        x=row.x,
        y=row.y,
        z=row.z,
        commander_note=row.commander_note,
        tags=_parse_tags(getattr(row, "tags_json", None)),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_route_record(row: SavedRouteRef) -> SavedRouteRecord:
    return SavedRouteRecord(
        id=int(row.id),
        label=row.label,
        origin=row.origin,
        destination=row.destination,
        hop_count=row.hop_count,
        source_id=row.source_id,
        commander_note=row.commander_note,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _append_activity(
    activity_log: ActivityLog | None,
    *,
    event_type: str,
    summary: str,
    payload: dict[str, object] | None = None,
    source_chain: list[dict[str, object]] | None = None,
) -> None:
    if activity_log is None:
        return

    activity_log.append(
        ActivityEntry(
            event_type=event_type,
            timestamp=_activity_timestamp(),
            summary=summary,
            payload=normalize_phase9_payload(payload) if payload is not None else None,
            source_chain=source_chain,
            redaction_state="redacted_summary_only" if payload is not None else None,
            is_fact=False if payload is not None else True,
            surface_origin="navigation" if payload is not None else None,
            source="commander_entered" if payload is not None else None,
        )
    )


def _workflow_type_for_bookmark_tag(tag: str) -> str:
    return "powerplay" if tag == "powerplay_target" else "bgs"


def _source_chain_for_bookmark_tag(tag: str) -> list[dict[str, object]]:
    return [
        {
            "source": "commander_entered",
            "source_type": "local_navigation_bookmark",
            "truth_class": "commander_entered",
            "freshness": "manual",
            "workflow_type": _workflow_type_for_bookmark_tag(tag),
        }
    ]


def _append_bookmark_tag_activity(
    activity_log: ActivityLog | None,
    *,
    bookmark_id: int,
    tag: str,
) -> None:
    _append_activity(
        activity_log,
        event_type=PHASE_9_NAVIGATION_BOOKMARK_TAGGED,
        summary=(
            "bookmark_tagged: "
            f"bookmark_id={bookmark_id} "
            f"workflow_type={_workflow_type_for_bookmark_tag(tag)} "
            f"tag={tag} source_label=commander_entered redacted=True"
        ),
        payload={
            "bookmark_id": bookmark_id,
            "workflow_type": _workflow_type_for_bookmark_tag(tag),
            "tag": tag,
            "source_label": "commander_entered",
        },
        source_chain=_source_chain_for_bookmark_tag(tag),
    )


# --- Bookmark CRUD ----------------------------------------------------------


async def create_bookmark(
    session_factory: async_sessionmaker[AsyncSession],
    payload: BookmarkCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> BookmarkRecord:
    """Create a local Navigation bookmark and audit the write."""
    now = _utc_now()
    validated_tags = _validate_tags(list(payload.tags or []))
    row = BookmarkRef(
        label=_clean_required_text(
            payload.label, field_name="label", max_length=MAX_LABEL_LENGTH
        ),
        entity_type=_clean_required_text(
            payload.entity_type, field_name="entity_type", max_length=32
        ),
        target_name=_clean_required_text(
            payload.target_name,
            field_name="target_name",
            max_length=MAX_TARGET_NAME_LENGTH,
        ),
        target_system_address=payload.target_system_address,
        x=payload.x,
        y=payload.y,
        z=payload.z,
        commander_note=_clean_optional_text(
            payload.commander_note,
            field_name="commander_note",
            max_length=MAX_NOTE_LENGTH,
        ),
        tags_json=json.dumps(validated_tags),
        created_at=now,
        updated_at=now,
    )

    async with session_factory() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)

    _append_activity(
        activity_log,
        event_type=NAVIGATION_BOOKMARK_CREATED,
        summary=f"Navigation bookmark created: {row.label} ({row.target_name})",
    )
    for tag in validated_tags:
        _append_bookmark_tag_activity(activity_log, bookmark_id=int(row.id), tag=tag)
    return _to_bookmark_record(row)


async def list_bookmarks(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[BookmarkRecord]:
    """Return local Navigation bookmarks, newest first."""
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError("limit is out of range")

    async with session_factory() as db:
        result = await db.execute(
            select(BookmarkRef).order_by(BookmarkRef.updated_at.desc()).limit(limit)
        )
        rows = cast(list[BookmarkRef], result.scalars().all())

    return [_to_bookmark_record(row) for row in rows]


async def get_bookmark(
    session_factory: async_sessionmaker[AsyncSession],
    bookmark_id: int,
) -> BookmarkRecord | None:
    """Return a local Navigation bookmark by id, if it exists."""
    async with session_factory() as db:
        row = await db.get(BookmarkRef, bookmark_id)

    return _to_bookmark_record(row) if row is not None else None


async def update_bookmark(
    session_factory: async_sessionmaker[AsyncSession],
    bookmark_id: int,
    changes: BookmarkUpdate,
    *,
    activity_log: ActivityLog | None = None,
) -> BookmarkRecord | None:
    """Update label/note on a local Navigation bookmark and audit the write."""
    async with session_factory() as db:
        row = await db.get(BookmarkRef, bookmark_id)
        if row is None:
            return None
        previous_tags = _parse_tags(getattr(row, "tags_json", None))

        if "label" in changes:
            row.label = _clean_required_text(
                changes["label"], field_name="label", max_length=MAX_LABEL_LENGTH
            )
        if "commander_note" in changes:
            row.commander_note = _clean_optional_text(
                changes["commander_note"],
                field_name="commander_note",
                max_length=MAX_NOTE_LENGTH,
            )
        if "tags" in changes:
            validated = _validate_tags(list(changes["tags"]))
            row.tags_json = json.dumps(validated)

        row.updated_at = _utc_now()
        await db.commit()
        await db.refresh(row)

    _append_activity(
        activity_log,
        event_type=NAVIGATION_BOOKMARK_UPDATED,
        summary=f"Navigation bookmark updated: {row.label}",
    )
    if "tags" in changes:
        for tag in _parse_tags(getattr(row, "tags_json", None)):
            if tag not in previous_tags:
                _append_bookmark_tag_activity(
                    activity_log,
                    bookmark_id=int(row.id),
                    tag=tag,
                )
    return _to_bookmark_record(row)


async def delete_bookmark(
    session_factory: async_sessionmaker[AsyncSession],
    bookmark_id: int,
    *,
    activity_log: ActivityLog | None = None,
) -> bool:
    """Delete a local Navigation bookmark and audit the write."""
    async with session_factory() as db:
        row = await db.get(BookmarkRef, bookmark_id)
        if row is None:
            return False

        label = row.label
        await db.delete(row)
        await db.commit()

    _append_activity(
        activity_log,
        event_type=NAVIGATION_BOOKMARK_DELETED,
        summary=f"Navigation bookmark deleted: {label}",
    )
    return True


# --- Saved Route CRUD -------------------------------------------------------


async def create_saved_route(
    session_factory: async_sessionmaker[AsyncSession],
    payload: SavedRouteCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> SavedRouteRecord:
    """Create a local saved route record and audit the write."""
    now = _utc_now()
    row = SavedRouteRef(
        label=_clean_required_text(
            payload.label, field_name="label", max_length=MAX_LABEL_LENGTH
        ),
        origin=_clean_required_text(
            payload.origin, field_name="origin", max_length=MAX_SYSTEM_NAME_LENGTH
        ),
        destination=_clean_required_text(
            payload.destination,
            field_name="destination",
            max_length=MAX_SYSTEM_NAME_LENGTH,
        ),
        hop_count=payload.hop_count,
        source_id=_clean_required_text(
            payload.source_id, field_name="source_id", max_length=32
        ),
        commander_note=_clean_optional_text(
            payload.commander_note,
            field_name="commander_note",
            max_length=MAX_NOTE_LENGTH,
        ),
        created_at=now,
        updated_at=now,
    )

    async with session_factory() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)

    _append_activity(
        activity_log,
        event_type=NAVIGATION_SAVED_ROUTE_CREATED,
        summary=f"Saved route created: {row.label} ({row.origin} → {row.destination})",
    )
    return _to_route_record(row)


async def list_saved_routes(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[SavedRouteRecord]:
    """Return local saved route records, newest first."""
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError("limit is out of range")

    async with session_factory() as db:
        result = await db.execute(
            select(SavedRouteRef).order_by(SavedRouteRef.updated_at.desc()).limit(limit)
        )
        rows = cast(list[SavedRouteRef], result.scalars().all())

    return [_to_route_record(row) for row in rows]


async def get_saved_route(
    session_factory: async_sessionmaker[AsyncSession],
    route_id: int,
) -> SavedRouteRecord | None:
    """Return a local saved route record by id, if it exists."""
    async with session_factory() as db:
        row = await db.get(SavedRouteRef, route_id)

    return _to_route_record(row) if row is not None else None


async def update_saved_route(
    session_factory: async_sessionmaker[AsyncSession],
    route_id: int,
    changes: SavedRouteUpdate,
    *,
    activity_log: ActivityLog | None = None,
) -> SavedRouteRecord | None:
    """Update label/note on a local saved route and audit the write."""
    async with session_factory() as db:
        row = await db.get(SavedRouteRef, route_id)
        if row is None:
            return None

        if "label" in changes:
            row.label = _clean_required_text(
                changes["label"], field_name="label", max_length=MAX_LABEL_LENGTH
            )
        if "commander_note" in changes:
            row.commander_note = _clean_optional_text(
                changes["commander_note"],
                field_name="commander_note",
                max_length=MAX_NOTE_LENGTH,
            )

        row.updated_at = _utc_now()
        await db.commit()
        await db.refresh(row)

    _append_activity(
        activity_log,
        event_type=NAVIGATION_SAVED_ROUTE_UPDATED,
        summary=f"Saved route updated: {row.label}",
    )
    return _to_route_record(row)


async def delete_saved_route(
    session_factory: async_sessionmaker[AsyncSession],
    route_id: int,
    *,
    activity_log: ActivityLog | None = None,
) -> bool:
    """Delete a local saved route record and audit the write."""
    async with session_factory() as db:
        row = await db.get(SavedRouteRef, route_id)
        if row is None:
            return False

        label = row.label
        await db.delete(row)
        await db.commit()

    _append_activity(
        activity_log,
        event_type=NAVIGATION_SAVED_ROUTE_DELETED,
        summary=f"Saved route deleted: {label}",
    )
    return True


# --- Bookmark tag filter (Phase 9 PB09-04) ----------------------------------


async def list_bookmarks_by_tag(
    session_factory: async_sessionmaker[AsyncSession],
    tag: str,
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[BookmarkRecord]:
    """Return local bookmarks that include the given tag in their tags_json list.

    Only tags in VALID_BOOKMARK_TAGS are accepted; unknown tags raise ValueError.
    """
    if tag not in VALID_BOOKMARK_TAGS:
        raise ValueError(
            f"tag {tag!r} is not a valid bookmark tag; "
            f"valid tags: {sorted(VALID_BOOKMARK_TAGS)}"
        )
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError("limit is out of range")

    async with session_factory() as db:
        result = await db.execute(
            select(BookmarkRef).order_by(BookmarkRef.updated_at.desc()).limit(limit)
        )
        all_rows = cast(list[BookmarkRef], result.scalars().all())

    return [
        _to_bookmark_record(row)
        for row in all_rows
        if tag in _parse_tags(getattr(row, "tags_json", None))
    ]
