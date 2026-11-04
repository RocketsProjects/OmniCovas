"""Personal Commander knowledge graph — LNA-006 foundation slice.

The graph the Commander already has, made walkable. Every edge here is
derived from data the app already stores: `journal_events.session_id` ties a
sitting to what happened in it, recorded Docked events tie a station to its
system, MarketID ties a snapshot to a station, and the flight recorder holds
the events that prove each link.

Nothing is materialised. This is a read-only projection over existing tables,
because the alternative — a second store of the same facts — is exactly the
parallel-ingest the Backend Blueprint forbids, and it would drift from the
recorder the moment either side changed.

Scope boundary (Phase 11 foundation): entity identity, derived edges, source
event chains, and notes. Dedicated entity pages and graph-wide search belong
to the Phase 13 Intel terminal, which PB13-00 gates behind Phase 12 source and
freshness stability. This module deliberately stops short of that.

Truth posture: recorded local observation only. An entity absent here was
never recorded on this machine, which is never proof it does not exist.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import CommanderMemoryRecord, JournalEvent, Session

logger = logging.getLogger(__name__)

TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
SOURCE_FLIGHT_RECORDER = "Local session database (flight recorder)"

ENTITY_SYSTEM = "system"
ENTITY_STATION = "station"
ENTITY_SESSION = "session"
ENTITY_TYPES: tuple[str, ...] = (ENTITY_SYSTEM, ENTITY_STATION, ENTITY_SESSION)

SOURCE_CHAIN_DEFAULT = 25
SOURCE_CHAIN_MAX = 100
EDGE_LIMIT = 100

_SYSTEM_VISIT_EVENTS = ("FSDJump", "CarrierJump", "Location")
_STATION_VISIT_EVENTS = ("Docked",)
_SNAPSHOT_CATEGORIES = ("market", "outfitting", "shipyard")

_GRAPH_CAVEAT = (
    "Connections derived from what this machine recorded. Every edge is "
    "backed by recorded events, and an entity or link absent here was never "
    "recorded — which is not proof it never happened."
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _clamp(value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default
    return max(1, min(maximum, value))


def _edge(
    relation: str,
    entity_type: str,
    key: str,
    display_name: str,
    **extra: Any,
) -> dict[str, Any]:
    """One traversable link. `key` is what the caller passes back in to walk."""
    return {
        "relation": relation,
        "type": entity_type,
        "key": key,
        "display_name": display_name,
        **extra,
    }


async def resolve_entity(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    entity_type: str,
    key: str,
    source_chain_limit: int | None = None,
    notes_service: Any = None,
) -> dict[str, Any]:
    """Return one entity, its derived edges, and the events proving them.

    Raises ValueError for an unknown entity type so the caller refuses rather
    than inventing an empty node for a type the graph does not model.
    """
    kind = (entity_type or "").strip().lower()
    if kind not in ENTITY_TYPES:
        raise ValueError(f"Unknown entity type: {entity_type}")
    identity = (key or "").strip()
    if not identity:
        raise ValueError("key is required")

    chain_limit = _clamp(source_chain_limit, SOURCE_CHAIN_DEFAULT, SOURCE_CHAIN_MAX)

    if kind == ENTITY_SYSTEM:
        payload = await _resolve_system(session_factory, identity, chain_limit)
    elif kind == ENTITY_STATION:
        payload = await _resolve_station(session_factory, identity, chain_limit)
    else:
        payload = await _resolve_session(session_factory, identity, chain_limit)

    notes: list[dict[str, Any]] = []
    if notes_service is not None and kind == ENTITY_SYSTEM and payload["found"]:
        stored = await notes_service.notes_for([identity])
        entry = stored.get(identity)
        if entry:
            notes.append({**entry, "star_system": identity})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _GRAPH_CAVEAT,
        **payload,
        # Authored text is the Commander's own and is never an observed fact;
        # it rides alongside the derived graph rather than inside it.
        "notes": notes,
        "nullprovider_safe": True,
    }


async def _source_chain(
    db: AsyncSession, where: Any, limit: int
) -> list[dict[str, Any]]:
    """The recorded events behind an entity, newest first and bounded."""
    rows = (
        await db.execute(
            select(
                JournalEvent.id,
                JournalEvent.session_id,
                JournalEvent.timestamp,
                JournalEvent.event_type,
            )
            .where(where)
            .order_by(JournalEvent.timestamp.desc(), JournalEvent.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": int(row.id),
            "session_id": int(row.session_id),
            "timestamp": _iso(row.timestamp),
            "event_type": row.event_type,
        }
        for row in rows
    ]


async def _resolve_system(
    session_factory: async_sessionmaker[AsyncSession], name: str, chain_limit: int
) -> dict[str, Any]:
    star_system = func.json_extract(JournalEvent.raw_json, "$.StarSystem")
    station_name = func.json_extract(JournalEvent.raw_json, "$.StationName")
    arrivals = (
        JournalEvent.event_type.in_(_SYSTEM_VISIT_EVENTS),
        star_system == name,
    )

    async with session_factory() as db:
        summary = (
            await db.execute(
                select(
                    func.count().label("observed_events"),
                    func.min(JournalEvent.timestamp).label("first_seen"),
                    func.max(JournalEvent.timestamp).label("last_seen"),
                ).where(*arrivals)
            )
        ).one()
        found = int(summary.observed_events or 0) > 0

        edges: list[dict[str, Any]] = []
        if found:
            for row in (
                await db.execute(
                    select(
                        station_name.label("station_name"),
                        func.count().label("docked_count"),
                        func.max(JournalEvent.timestamp).label("last_docked"),
                    )
                    .where(
                        JournalEvent.event_type.in_(_STATION_VISIT_EVENTS),
                        star_system == name,
                        station_name.is_not(None),
                    )
                    .group_by(station_name)
                    .order_by(func.max(JournalEvent.timestamp).desc())
                    .limit(EDGE_LIMIT)
                )
            ).all():
                edges.append(
                    _edge(
                        "docked_at",
                        ENTITY_STATION,
                        row.station_name,
                        row.station_name,
                        observed_count=int(row.docked_count),
                        last_observed=_iso(row.last_docked),
                    )
                )

            for row in (
                await db.execute(
                    select(
                        JournalEvent.session_id,
                        Session.journal_filename,
                        func.count().label("arrivals"),
                        func.max(JournalEvent.timestamp).label("last_seen"),
                    )
                    .join(Session, Session.id == JournalEvent.session_id)
                    .where(*arrivals)
                    .group_by(JournalEvent.session_id, Session.journal_filename)
                    .order_by(func.max(JournalEvent.timestamp).desc())
                    .limit(EDGE_LIMIT)
                )
            ).all():
                edges.append(
                    _edge(
                        "visited_in",
                        ENTITY_SESSION,
                        str(int(row.session_id)),
                        row.journal_filename,
                        observed_count=int(row.arrivals),
                        last_observed=_iso(row.last_seen),
                    )
                )

        chain = await _source_chain(db, and_all(arrivals), chain_limit) if found else []

    return {
        "found": found,
        "entity": {
            "type": ENTITY_SYSTEM,
            "key": name,
            "display_name": name,
            "attributes": {
                "observed_events": int(summary.observed_events or 0),
                "first_seen": _iso(summary.first_seen),
                "last_seen": _iso(summary.last_seen),
            },
        },
        "edges": edges,
        "source_chain": chain,
    }


async def _resolve_station(
    session_factory: async_sessionmaker[AsyncSession], name: str, chain_limit: int
) -> dict[str, Any]:
    star_system = func.json_extract(JournalEvent.raw_json, "$.StarSystem")
    station_name = func.json_extract(JournalEvent.raw_json, "$.StationName")
    dockings = (
        JournalEvent.event_type.in_(_STATION_VISIT_EVENTS),
        station_name == name,
    )

    async with session_factory() as db:
        summary = (
            await db.execute(
                select(
                    func.count().label("docked_count"),
                    func.min(JournalEvent.timestamp).label("first_docked"),
                    func.max(JournalEvent.timestamp).label("last_docked"),
                ).where(*dockings)
            )
        ).one()
        found = int(summary.docked_count or 0) > 0

        edges: list[dict[str, Any]] = []
        systems: list[str] = []
        if found:
            for row in (
                await db.execute(
                    select(
                        star_system.label("star_system"),
                        func.count().label("docked_count"),
                        func.max(JournalEvent.timestamp).label("last_docked"),
                    )
                    .where(*dockings, star_system.is_not(None))
                    .group_by(star_system)
                    .order_by(func.max(JournalEvent.timestamp).desc())
                    .limit(EDGE_LIMIT)
                )
            ).all():
                systems.append(row.star_system)
                edges.append(
                    _edge(
                        "in_system",
                        ENTITY_SYSTEM,
                        row.star_system,
                        row.star_system,
                        observed_count=int(row.docked_count),
                        last_observed=_iso(row.last_docked),
                    )
                )

            for row in (
                await db.execute(
                    select(
                        JournalEvent.session_id,
                        Session.journal_filename,
                        func.count().label("dockings"),
                        func.max(JournalEvent.timestamp).label("last_docked"),
                    )
                    .join(Session, Session.id == JournalEvent.session_id)
                    .where(*dockings)
                    .group_by(JournalEvent.session_id, Session.journal_filename)
                    .order_by(func.max(JournalEvent.timestamp).desc())
                    .limit(EDGE_LIMIT)
                )
            ).all():
                edges.append(
                    _edge(
                        "docked_in",
                        ENTITY_SESSION,
                        str(int(row.session_id)),
                        row.journal_filename,
                        observed_count=int(row.dockings),
                        last_observed=_iso(row.last_docked),
                    )
                )

            # Companion snapshots are remembered observations rather than
            # recorded events, so they are labelled as such and are simply
            # absent when Memory is paused or cleared — never an error.
            for row in (
                await db.execute(
                    select(
                        CommanderMemoryRecord.category,
                        CommanderMemoryRecord.display_name,
                        CommanderMemoryRecord.entity_key,
                        CommanderMemoryRecord.last_seen_at,
                    )
                    .where(
                        CommanderMemoryRecord.category.in_(_SNAPSHOT_CATEGORIES),
                        CommanderMemoryRecord.display_name == name,
                    )
                    .limit(EDGE_LIMIT)
                )
            ).all():
                edges.append(
                    _edge(
                        "observed_snapshot",
                        row.category,
                        row.entity_key,
                        f"{row.display_name} {row.category}",
                        last_observed=_iso(row.last_seen_at),
                        freshness="remembered",
                    )
                )

        chain = await _source_chain(db, and_all(dockings), chain_limit) if found else []

    return {
        "found": found,
        "entity": {
            "type": ENTITY_STATION,
            "key": name,
            "display_name": name,
            "attributes": {
                "docked_count": int(summary.docked_count or 0),
                "first_docked": _iso(summary.first_docked),
                "last_docked": _iso(summary.last_docked),
                "star_systems": systems,
            },
        },
        "edges": edges,
        "source_chain": chain,
    }


async def _resolve_session(
    session_factory: async_sessionmaker[AsyncSession], key: str, chain_limit: int
) -> dict[str, Any]:
    try:
        session_id = int(key)
    except (TypeError, ValueError) as exc:
        raise ValueError("session key must be a session id") from exc

    star_system = func.json_extract(JournalEvent.raw_json, "$.StarSystem")
    station_name = func.json_extract(JournalEvent.raw_json, "$.StationName")

    async with session_factory() as db:
        row = await db.get(Session, session_id)
        found = row is not None
        edges: list[dict[str, Any]] = []
        attributes: dict[str, Any] = {}

        if found and row is not None:
            summary = (
                await db.execute(
                    select(
                        func.count().label("event_count"),
                        func.min(JournalEvent.timestamp).label("first_event"),
                        func.max(JournalEvent.timestamp).label("last_event"),
                    ).where(JournalEvent.session_id == session_id)
                )
            ).one()
            attributes = {
                "journal_filename": row.journal_filename,
                "commander_name": row.commander_name,
                "ship_type": row.ship_type,
                "event_count": int(summary.event_count or 0),
                "first_event_at": _iso(summary.first_event),
                "last_event_at": _iso(summary.last_event),
            }

            for visited in (
                await db.execute(
                    select(
                        star_system.label("star_system"),
                        func.count().label("arrivals"),
                        func.max(JournalEvent.timestamp).label("last_seen"),
                    )
                    .where(
                        JournalEvent.session_id == session_id,
                        JournalEvent.event_type.in_(_SYSTEM_VISIT_EVENTS),
                        star_system.is_not(None),
                    )
                    .group_by(star_system)
                    .order_by(func.max(JournalEvent.timestamp).desc())
                    .limit(EDGE_LIMIT)
                )
            ).all():
                edges.append(
                    _edge(
                        "visited",
                        ENTITY_SYSTEM,
                        visited.star_system,
                        visited.star_system,
                        observed_count=int(visited.arrivals),
                        last_observed=_iso(visited.last_seen),
                    )
                )

            for docked in (
                await db.execute(
                    select(
                        station_name.label("station_name"),
                        func.count().label("dockings"),
                        func.max(JournalEvent.timestamp).label("last_docked"),
                    )
                    .where(
                        JournalEvent.session_id == session_id,
                        JournalEvent.event_type.in_(_STATION_VISIT_EVENTS),
                        station_name.is_not(None),
                    )
                    .group_by(station_name)
                    .order_by(func.max(JournalEvent.timestamp).desc())
                    .limit(EDGE_LIMIT)
                )
            ).all():
                edges.append(
                    _edge(
                        "docked_at",
                        ENTITY_STATION,
                        docked.station_name,
                        docked.station_name,
                        observed_count=int(docked.dockings),
                        last_observed=_iso(docked.last_docked),
                    )
                )

        chain = (
            await _source_chain(db, JournalEvent.session_id == session_id, chain_limit)
            if found
            else []
        )

    return {
        "found": found,
        "entity": {
            "type": ENTITY_SESSION,
            "key": key,
            "display_name": attributes.get("journal_filename") or f"Session {key}",
            "attributes": attributes,
        },
        "edges": edges,
        "source_chain": chain,
    }


def and_all(conditions: tuple[Any, ...]) -> Any:
    """Combine WHERE conditions already expressed as a tuple."""
    combined = conditions[0]
    for condition in conditions[1:]:
        combined = combined & condition
    return combined
