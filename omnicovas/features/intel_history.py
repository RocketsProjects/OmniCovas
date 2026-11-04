"""Local flight-recorder history queries — Phase 13 Intel terminal core.

Read-only, bounded queries over the local session database written by the
EventRecorder (JournalEvent / Session tables). Truth class is
local_event_history ("Commander-observed"): this machine's recorded
sessions only — never a complete galaxy history, and the absence of a row
is never proof that a system or station was not visited.

No new persistence, no migrations, no journal handler registration, no
providers. Serves PB13-01/PB13-02 planning scope and LNA-002 (journal
search terminal), LNA-003 (flight history), LNA-004 (system visit
history), LNA-005 (station visit history).

See: Elite Local Data Surface Reference v1.0 (LIVE_SESSION_EVENT_HISTORY)
See: Backend Blueprint v1.0 (extend existing services; no duplicates)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import JournalEvent, Session

TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
SOURCE_FLIGHT_RECORDER = "Local session database (flight recorder)"

SEARCH_DEFAULT_LIMIT = 50
SEARCH_MAX_LIMIT = 200
HISTORY_DEFAULT_LIMIT = 100
HISTORY_MAX_LIMIT = 500
EVENT_TYPES_DEFAULT_LIMIT = 100
EVENT_TYPES_MAX_LIMIT = 200
SESSIONS_DEFAULT_LIMIT = 25
SESSIONS_MAX_LIMIT = 200

# Operation classes for the session timeline filter. Every name is a
# Frontier-native event already recorded by the flight recorder and already
# handled by omnicovas.core.handlers — no event name is invented here, and a
# recorded type outside these tuples is reported under "other" rather than
# dropped, so a session's observed activity is never silently narrowed.
OPERATION_CLASSES: dict[str, tuple[str, ...]] = {
    "travel": ("FSDJump", "CarrierJump", "Location"),
    "station": ("Docked", "Undocked", "DockingGranted"),
    "combat": (
        "Bounty",
        "FactionKillBond",
        "HullDamage",
        "ShieldDown",
        "Interdicted",
        "BeingInterdicted",
        "EscapeInterdiction",
        "Died",
    ),
    "missions": (
        "MissionAccepted",
        "MissionCompleted",
        "MissionFailed",
        "MissionAbandoned",
        "MissionRedirected",
    ),
    "trade": ("Market", "MarketBuy", "MarketSell"),
    "powerplay": (
        "PowerplayJoin",
        "PowerplayLeave",
        "PowerplayCollect",
        "PowerplayDeliver",
        "PowerplayVote",
        "PowerplayVoucher",
        "PowerplayDefect",
        "PowerplayFastTrack",
        "PowerplaySalary",
    ),
}
OPERATION_OTHER = "other"

_OPERATION_BY_EVENT: dict[str, str] = {
    event_name: operation
    for operation, event_names in OPERATION_CLASSES.items()
    for event_name in event_names
}

_SESSIONS_CAVEAT = (
    "Commander sessions recorded by the local flight recorder on this "
    "machine. Recorded sessions only — a session absent here was never "
    "recorded, which is not proof it never happened. Counts describe "
    "recorded rows, not complete in-game activity."
)

_SEARCH_CAVEAT = (
    "Commander-observed journal events recorded by the local flight "
    "recorder on this machine. Recorded sessions only — not a complete "
    "history, and absence of an event here is not proof it never happened."
)
_SYSTEMS_CAVEAT = (
    "Commander-observed systems derived from recorded FSDJump, "
    "CarrierJump, and Location events on this machine. Recorded sessions "
    "only — not a complete travel history, and absence is not proof of "
    "non-visit."
)
_STATIONS_CAVEAT = (
    "Commander-observed stations derived from recorded Docked events on "
    "this machine. Recorded sessions only — not a complete docking "
    "history, and absence is not proof of non-visit."
)
_EVENT_TYPES_CAVEAT = (
    "Distinct event types recorded by the local flight recorder on this "
    "machine, taken verbatim from recorded rows. Never a complete catalog "
    "of game events, and absence here is not proof an event type never "
    "occurs."
)

# Frontier-native event names already recorded by the flight recorder and
# already handled by omnicovas.core.handlers. No new event names are
# introduced here (names are matched verbatim against recorded rows).
_SYSTEM_VISIT_EVENTS = ("FSDJump", "CarrierJump", "Location")
_STATION_VISIT_EVENTS = ("Docked",)


def parse_iso_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp (journal 'Z' suffix supported).

    Raises ValueError for unparseable input — callers surface this as a
    request error rather than guessing.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _clamp_limit(limit: int | None, default: int, maximum: int) -> int:
    if limit is None:
        return default
    return max(1, min(maximum, limit))


def _iso_or_none(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def search_journal_events(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    event_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    contains: str | None = None,
    session_id: int | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Bounded newest-first search over recorded journal events."""
    bounded_limit = _clamp_limit(limit, SEARCH_DEFAULT_LIMIT, SEARCH_MAX_LIMIT)

    filters = []
    if event_type:
        filters.append(JournalEvent.event_type == event_type)
    if since is not None:
        filters.append(JournalEvent.timestamp >= since)
    if until is not None:
        filters.append(JournalEvent.timestamp <= until)
    if contains:
        filters.append(JournalEvent.raw_json.contains(contains, autoescape=True))
    if session_id is not None:
        filters.append(JournalEvent.session_id == session_id)

    async with session_factory() as db:
        total = await db.scalar(
            select(func.count()).select_from(JournalEvent).where(*filters)
        )
        rows = (
            await db.execute(
                select(JournalEvent)
                .where(*filters)
                .order_by(JournalEvent.timestamp.desc(), JournalEvent.id.desc())
                .limit(bounded_limit)
            )
        ).scalars()
        events = [
            {
                "id": row.id,
                "session_id": row.session_id,
                "timestamp": _iso_or_none(row.timestamp),
                "event_type": row.event_type,
                "raw_json": row.raw_json,
            }
            for row in rows
        ]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _SEARCH_CAVEAT,
        "filters_applied": {
            "event_type": event_type,
            "since": _iso_or_none(since),
            "until": _iso_or_none(until),
            "contains": contains,
            "session_id": session_id,
            "limit": bounded_limit,
        },
        "total_matched": int(total or 0),
        "returned": len(events),
        "events": events,
        "nullprovider_safe": True,
    }


async def visited_systems(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Commander-observed system visit history (LNA-004).

    Per system: when it was first and last seen, how many arrivals were
    recorded, which recorded event types produced them, and which stations
    were docked at there. The station list is what makes this a history of a
    place rather than a bare arrival tally — it is derived from recorded
    Docked events, so a system visited but never docked at correctly reports
    no stations rather than omitting the system.
    """
    bounded_limit = _clamp_limit(limit, HISTORY_DEFAULT_LIMIT, HISTORY_MAX_LIMIT)
    system_name = func.json_extract(JournalEvent.raw_json, "$.StarSystem")
    station_name = func.json_extract(JournalEvent.raw_json, "$.StationName")

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(
                    system_name.label("star_system"),
                    func.count().label("observed_events"),
                    func.min(JournalEvent.timestamp).label("first_seen"),
                    func.max(JournalEvent.timestamp).label("last_seen"),
                )
                .where(
                    JournalEvent.event_type.in_(_SYSTEM_VISIT_EVENTS),
                    system_name.is_not(None),
                )
                .group_by(system_name)
                .order_by(func.max(JournalEvent.timestamp).desc())
                .limit(bounded_limit)
            )
        ).all()

        names = [row.star_system for row in rows if row.star_system]
        arrivals_by_system: dict[str, dict[str, int]] = {}
        stations_by_system: dict[str, list[dict[str, Any]]] = {}
        if names:
            for kind in (
                await db.execute(
                    select(
                        system_name.label("star_system"),
                        JournalEvent.event_type,
                        func.count().label("recorded"),
                    )
                    .where(
                        JournalEvent.event_type.in_(_SYSTEM_VISIT_EVENTS),
                        system_name.in_(names),
                    )
                    .group_by(system_name, JournalEvent.event_type)
                )
            ).all():
                bucket = arrivals_by_system.setdefault(kind.star_system, {})
                bucket[kind.event_type] = int(kind.recorded)

            for dock in (
                await db.execute(
                    select(
                        system_name.label("star_system"),
                        station_name.label("station_name"),
                        func.count().label("docked_count"),
                        func.max(JournalEvent.timestamp).label("last_docked"),
                    )
                    .where(
                        JournalEvent.event_type.in_(_STATION_VISIT_EVENTS),
                        system_name.in_(names),
                        station_name.is_not(None),
                    )
                    .group_by(system_name, station_name)
                    .order_by(func.max(JournalEvent.timestamp).desc())
                )
            ).all():
                stations_by_system.setdefault(dock.star_system, []).append(
                    {
                        "station_name": dock.station_name,
                        "docked_count": int(dock.docked_count),
                        "last_docked": _iso_or_none(dock.last_docked),
                    }
                )

    systems = [
        {
            "star_system": row.star_system,
            "observed_events": int(row.observed_events),
            "first_seen": _iso_or_none(row.first_seen),
            "last_seen": _iso_or_none(row.last_seen),
            # Which recorded event types produced the arrivals for this
            # system, so the count can be traced to its sources.
            "source_events": [
                {"event_type": event_type, "recorded": recorded}
                for event_type, recorded in sorted(
                    arrivals_by_system.get(row.star_system, {}).items()
                )
            ],
            "docked_stations": stations_by_system.get(row.star_system, []),
        }
        for row in rows
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _SYSTEMS_CAVEAT,
        "source_events": list(_SYSTEM_VISIT_EVENTS),
        "returned": len(systems),
        "limit": bounded_limit,
        "systems": systems,
        "nullprovider_safe": True,
    }


async def visited_stations(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Commander-observed station docking catalog (LNA-005 first slice)."""
    bounded_limit = _clamp_limit(limit, HISTORY_DEFAULT_LIMIT, HISTORY_MAX_LIMIT)
    station_name = func.json_extract(JournalEvent.raw_json, "$.StationName")
    star_system = func.json_extract(JournalEvent.raw_json, "$.StarSystem")
    station_type = func.json_extract(JournalEvent.raw_json, "$.StationType")

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(
                    station_name.label("station_name"),
                    star_system.label("star_system"),
                    # Representative observed value from the grouped rows;
                    # rendered as observed data, not asserted as constant.
                    func.max(station_type).label("station_type"),
                    func.count().label("docked_count"),
                    func.min(JournalEvent.timestamp).label("first_docked"),
                    func.max(JournalEvent.timestamp).label("last_docked"),
                )
                .where(
                    JournalEvent.event_type.in_(_STATION_VISIT_EVENTS),
                    station_name.is_not(None),
                )
                .group_by(station_name, star_system)
                .order_by(func.max(JournalEvent.timestamp).desc())
                .limit(bounded_limit)
            )
        ).all()

    stations = [
        {
            "station_name": row.station_name,
            "star_system": row.star_system,
            "station_type": row.station_type,
            "docked_count": int(row.docked_count),
            "first_docked": _iso_or_none(row.first_docked),
            "last_docked": _iso_or_none(row.last_docked),
        }
        for row in rows
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _STATIONS_CAVEAT,
        "source_events": list(_STATION_VISIT_EVENTS),
        "returned": len(stations),
        "limit": bounded_limit,
        "stations": stations,
        "nullprovider_safe": True,
    }


async def session_timeline(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int | None = None,
    operation: str | None = None,
) -> dict[str, Any]:
    """Commander session timeline explorer (LNA-001).

    The journal search terminal answers "which events match"; this answers
    "which sittings happened, and what did each one consist of". Sessions are
    the rows the EventRecorder already writes, so nothing new is persisted.

    Each session carries its observed span, recorded event count, distinct
    systems and stations, and the operation classes actually seen — enough for
    the Commander to recognise a sitting and open it. `session_id` is returned
    so the existing journal-search filter becomes reachable: without an
    enumeration the filter cannot be used, because ids are not discoverable.

    Raises ValueError for an unknown operation class so the caller can refuse
    rather than silently returning an unfiltered timeline.
    """
    bounded_limit = _clamp_limit(limit, SESSIONS_DEFAULT_LIMIT, SESSIONS_MAX_LIMIT)
    requested = (operation or "").strip().lower() or None
    if requested is not None and requested not in OPERATION_CLASSES:
        raise ValueError(f"Unknown operation class: {operation}")

    star_system = func.json_extract(JournalEvent.raw_json, "$.StarSystem")
    station_name = func.json_extract(JournalEvent.raw_json, "$.StationName")

    async with session_factory() as db:
        total = int(await db.scalar(select(func.count()).select_from(Session)) or 0)
        # The newest recorded session regardless of the active filter, so
        # "most recent" stays a fact about the recorder rather than about the
        # current view.
        newest_id = await db.scalar(
            select(Session.id)
            .order_by(Session.start_time.desc(), Session.id.desc())
            .limit(1)
        )

        listing = select(
            Session.id,
            Session.start_time,
            Session.end_time,
            Session.commander_name,
            Session.ship_type,
            Session.journal_filename,
        ).order_by(Session.start_time.desc(), Session.id.desc())
        if requested is not None:
            listing = listing.where(
                Session.id.in_(
                    select(JournalEvent.session_id).where(
                        JournalEvent.event_type.in_(OPERATION_CLASSES[requested])
                    )
                )
            )
        rows = (await db.execute(listing.limit(bounded_limit))).all()
        session_ids = [int(row.id) for row in rows]

        spans: dict[int, Any] = {}
        systems: dict[int, int] = {}
        stations: dict[int, int] = {}
        operations: dict[int, dict[str, int]] = {}
        if session_ids:
            for span in (
                await db.execute(
                    select(
                        JournalEvent.session_id,
                        func.count().label("event_count"),
                        func.min(JournalEvent.timestamp).label("first_event"),
                        func.max(JournalEvent.timestamp).label("last_event"),
                    )
                    .where(JournalEvent.session_id.in_(session_ids))
                    .group_by(JournalEvent.session_id)
                )
            ).all():
                spans[int(span.session_id)] = span

            for visit in (
                await db.execute(
                    select(
                        JournalEvent.session_id,
                        func.count(func.distinct(star_system)).label("seen"),
                    )
                    .where(
                        JournalEvent.session_id.in_(session_ids),
                        JournalEvent.event_type.in_(_SYSTEM_VISIT_EVENTS),
                        star_system.is_not(None),
                    )
                    .group_by(JournalEvent.session_id)
                )
            ).all():
                systems[int(visit.session_id)] = int(visit.seen)

            for dock in (
                await db.execute(
                    select(
                        JournalEvent.session_id,
                        func.count(func.distinct(station_name)).label("seen"),
                    )
                    .where(
                        JournalEvent.session_id.in_(session_ids),
                        JournalEvent.event_type.in_(_STATION_VISIT_EVENTS),
                        station_name.is_not(None),
                    )
                    .group_by(JournalEvent.session_id)
                )
            ).all():
                stations[int(dock.session_id)] = int(dock.seen)

            for kind in (
                await db.execute(
                    select(
                        JournalEvent.session_id,
                        JournalEvent.event_type,
                        func.count().label("recorded"),
                    )
                    .where(JournalEvent.session_id.in_(session_ids))
                    .group_by(JournalEvent.session_id, JournalEvent.event_type)
                )
            ).all():
                bucket = operations.setdefault(int(kind.session_id), {})
                name = _OPERATION_BY_EVENT.get(kind.event_type, OPERATION_OTHER)
                bucket[name] = bucket.get(name, 0) + int(kind.recorded)

    sessions: list[dict[str, Any]] = []
    for row in rows:
        session_id = int(row.id)
        recorded_span = spans.get(session_id)
        first_event = getattr(recorded_span, "first_event", None)
        last_event = getattr(recorded_span, "last_event", None)
        # Measured across recorded events only. `Session.start_time` is the
        # wall clock when the recorder opened the row, while event timestamps
        # come from the Journal; subtracting one from the other compares two
        # different clocks and produced a nonsense span on a catch-up ingest of
        # an older Journal. The event span is the one interval both ends of
        # which the recorder actually observed.
        duration = None
        if isinstance(first_event, datetime) and isinstance(last_event, datetime):
            duration = max(0, int((last_event - first_event).total_seconds()))
        counts = operations.get(session_id, {})
        sessions.append(
            {
                "session_id": session_id,
                "journal_filename": row.journal_filename,
                "commander_name": row.commander_name,
                "ship_type": row.ship_type,
                "started_at": _iso_or_none(row.start_time),
                "ended_at": _iso_or_none(row.end_time),
                "first_event_at": _iso_or_none(first_event),
                "last_event_at": _iso_or_none(last_event),
                "observed_duration_seconds": duration,
                "end_recorded": row.end_time is not None,
                "event_count": int(getattr(recorded_span, "event_count", 0) or 0),
                "systems_visited": systems.get(session_id, 0),
                "stations_docked": stations.get(session_id, 0),
                "operations": [
                    {"operation": name, "recorded": counts[name]}
                    for name in sorted(counts, key=lambda key: (-counts[key], key))
                ],
                "is_most_recent": newest_id is not None
                and session_id == int(newest_id),
                # Memory is "remembered"; a recorded sitting is observed history
                # this machine wrote down. Neither outranks live local state.
                "freshness": "recorded",
                "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _SESSIONS_CAVEAT,
        "operation": requested,
        "operation_classes": sorted(OPERATION_CLASSES),
        "returned": len(sessions),
        "total": total,
        "limit": bounded_limit,
        "sessions": sessions,
        "nullprovider_safe": True,
    }


async def recorded_event_types(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Distinct recorded event types with counts (PB13-02 search presets).

    Data-driven from recorded rows only: event-type strings are taken
    verbatim from the local database, so no event name is ever invented
    or asserted beyond "this machine recorded it".
    """
    bounded_limit = _clamp_limit(
        limit, EVENT_TYPES_DEFAULT_LIMIT, EVENT_TYPES_MAX_LIMIT
    )

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(
                    JournalEvent.event_type.label("event_type"),
                    func.count().label("recorded"),
                    func.max(JournalEvent.timestamp).label("last_recorded"),
                )
                .group_by(JournalEvent.event_type)
                .order_by(func.count().desc(), JournalEvent.event_type.asc())
                .limit(bounded_limit)
            )
        ).all()

    event_types = [
        {
            "event_type": row.event_type,
            "recorded": int(row.recorded),
            "last_recorded": _iso_or_none(row.last_recorded),
        }
        for row in rows
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _EVENT_TYPES_CAVEAT,
        "returned": len(event_types),
        "limit": bounded_limit,
        "event_types": event_types,
        "nullprovider_safe": True,
    }
