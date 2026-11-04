"""Local exploration history — Phase 13 Intel exploration fact domain.

Serves LNA-034 (exploration session journal) and LNA-035 (scan/discovery
history) as read-only, bounded queries over the flight recorder's existing
JournalEvent rows. No new persistence, no migrations, no handler
registration, no providers: `EventRecorder.record_event` already stores every
journal event verbatim (Law 8), so scan evidence is already on disk and only
needs deriving.

Why this is a survey record and not a body tally
------------------------------------------------
Elite reports how many bodies a system *has* (`FSSDiscoveryScan.BodyCount`)
separately from the ones the Commander actually scanned. That makes honest
coverage possible: "8 of 34 bodies scanned" is a fact, "8 bodies" is a tally
that quietly implies completeness. Where no FSSDiscoveryScan was recorded the
total is **unknown** and is reported as unknown — the scanned count is never
promoted into a total, because a partially surveyed system would then read as
fully surveyed (the LNA-027 / B10 failure shape).

Truth class is local_event_history: this machine's recorded sessions only.
The absence of a body is never proof it does not exist.

See: Elite Local Data Surface Reference v1.0 (LIVE_SESSION_EVENT_HISTORY)
See: PB13-00 / PB13-01 planning scope; LNA overlay Phase 13 rows
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import JournalEvent
from omnicovas.db.models import Session as SessionModel
from omnicovas.features import exploration_value

TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
SOURCE_FLIGHT_RECORDER = "Local session database (flight recorder)"

EXPLORATION_DEFAULT_LIMIT = 100
EXPLORATION_MAX_LIMIT = 500
BODIES_DEFAULT_LIMIT = 200
BODIES_MAX_LIMIT = 1000
TRIPS_DEFAULT_LIMIT = 25
TRIPS_MAX_LIMIT = 200

# Frontier-native event names only. Nothing here is invented.
BODY_SCAN_EVENTS = ("Scan",)
SYSTEM_SURVEY_EVENTS = ("FSSDiscoveryScan",)
ALL_BODIES_EVENTS = ("FSSAllBodiesFound",)
SURFACE_MAP_EVENTS = ("SAAScanComplete",)
ORGANIC_SCAN_EVENTS = ("ScanOrganic",)
TRAVEL_EVENTS = ("FSDJump", "CarrierJump")
# Frontier reports real credits on sale. These are the only exploration and
# exobiology values this module treats as fact; everything predictive is an
# estimate and lives behind a KB reference, never here.
EXPLORATION_SALE_EVENTS = ("SellExplorationData", "MultiSellExplorationData")
ORGANIC_SALE_EVENTS = ("SellOrganicData",)

_SYSTEMS_CAVEAT = (
    "Commander-observed exploration history from recorded Scan, "
    "FSSDiscoveryScan, FSSAllBodiesFound, and SAAScanComplete events on this "
    "machine. Recorded sessions only — a system absent here may still have "
    "been visited before recording began. Body totals come from the system "
    "honk (FSSDiscoveryScan); where no honk was recorded the total is unknown "
    "and coverage cannot be judged."
)
_EARNINGS_CAVEAT = (
    "Credits actually received, read from recorded SellExplorationData, "
    "MultiSellExplorationData, and SellOrganicData events on this machine. "
    "Recorded sessions only — data sold before recording began is not counted, "
    "and this is not a wallet balance. Unsold scans are not valued here: any "
    "estimate of what they might fetch is a separate, clearly-labelled "
    "reference estimate and is never added to money already received."
)
_TRIPS_CAVEAT = (
    "Exploration activity grouped by recorded session. A session is the only "
    "trip boundary the flight recorder knows — it opens when the game writes "
    "a new journal and closes when the game stops — so a real expedition may "
    "span several rows here. Credits are reported as sold DURING a trip, "
    "never earned by it: Frontier's sale events do not say which trip "
    "gathered the data. Sessions with no exploration activity are excluded "
    "and counted separately, so this is a view of exploration sessions rather "
    "than of every session recorded."
)
_BODIES_CAVEAT = (
    "Commander-observed body scans from recorded Scan and SAAScanComplete "
    "events. A body scanned more than once (auto then detailed) is listed "
    "once, keeping its most complete recorded observation. First-discovery "
    "and first-mapped flags are read from the journal's WasDiscovered and "
    "WasMapped fields; when the journal did not report them they stay unknown."
)


def _clamp_limit(value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default
    return max(1, min(int(value), maximum))


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json(path: str) -> Any:
    return func.json_extract(JournalEvent.raw_json, path)


def _tri_state(value: Any) -> bool | None:
    """SQLite json_extract yields 1/0 for JSON booleans, NULL when absent.

    Absent must stay unknown rather than collapsing to False: older journals
    omit WasDiscovered entirely, and reading that as "not discovered by
    anyone" would manufacture first-discovery credit.
    """
    if value is None:
        return None
    return bool(value)


async def exploration_trips(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Exploration trip timeline, one row per recorded session (LNA-034).

    A "trip" here is **one recorded session**, and the surface says so. That
    is the only boundary the flight recorder actually knows: it opens a
    session when the game writes a new journal file and closes it when the
    game stops. A real expedition may span several sessions, and a single
    session may hold none of one — calling a session a journey would be an
    inference dressed as a fact, so the payload names the unit instead.

    Two attribution traps this deliberately avoids.

    Credits are reported as **sold during** the trip, never earned by it.
    Frontier's sale events say what was sold and for how much, not where the
    data came from; a Commander who spends four sessions surveying and sells
    on the fifth would otherwise see one enormous trip and four empty ones.

    Sessions with no exploration activity are excluded — a trade run is not
    an exploration trip — but the count of what was excluded is reported, so
    the timeline is never silently narrowed into looking like the whole
    history.
    """
    bounded_limit = _clamp_limit(limit, TRIPS_DEFAULT_LIMIT, TRIPS_MAX_LIMIT)
    star_system = _json("$.StarSystem")
    body_name = _json("$.BodyName")

    async with session_factory() as db:
        sessions = (
            await db.execute(
                select(
                    SessionModel.id,
                    SessionModel.journal_filename,
                    SessionModel.start_time,
                    SessionModel.end_time,
                    SessionModel.commander_name,
                    SessionModel.ship_type,
                ).order_by(SessionModel.start_time.desc())
            )
        ).all()

        trips: list[dict[str, Any]] = []
        sessions_without_exploration = 0

        for row in sessions:
            counts = (
                await db.execute(
                    select(
                        func.count(func.distinct(body_name))
                        .filter(JournalEvent.event_type.in_(BODY_SCAN_EVENTS))
                        .label("bodies_scanned"),
                        func.count()
                        .filter(JournalEvent.event_type.in_(SYSTEM_SURVEY_EVENTS))
                        .label("systems_honked"),
                        func.count()
                        .filter(JournalEvent.event_type.in_(SURFACE_MAP_EVENTS))
                        .label("surface_maps"),
                        func.count()
                        .filter(JournalEvent.event_type.in_(ORGANIC_SCAN_EVENTS))
                        .label("organic_scans"),
                        func.count()
                        .filter(JournalEvent.event_type.in_(TRAVEL_EVENTS))
                        .label("jumps"),
                        func.count(func.distinct(star_system))
                        .filter(JournalEvent.event_type.in_(TRAVEL_EVENTS))
                        .label("systems_visited"),
                        func.sum(_json("$.JumpDist"))
                        .filter(JournalEvent.event_type == "FSDJump")
                        .label("jump_distance_ly"),
                        func.min(JournalEvent.timestamp).label("first_event"),
                        func.max(JournalEvent.timestamp).label("last_event"),
                    ).where(JournalEvent.session_id == row.id)
                )
            ).one()

            explored = (
                int(counts.bodies_scanned or 0)
                + int(counts.systems_honked or 0)
                + int(counts.surface_maps or 0)
                + int(counts.organic_scans or 0)
            )
            if explored == 0:
                sessions_without_exploration += 1
                continue

            # First discoveries: WasDiscovered explicitly false. An absent
            # flag stays out of the count rather than being read as a first.
            firsts = (
                await db.execute(
                    select(func.count(func.distinct(body_name))).where(
                        JournalEvent.session_id == row.id,
                        JournalEvent.event_type.in_(BODY_SCAN_EVENTS),
                        _json("$.WasDiscovered") == 0,
                    )
                )
            ).scalar_one()

            surveyed = [
                name
                for (name,) in (
                    await db.execute(
                        select(func.distinct(star_system)).where(
                            JournalEvent.session_id == row.id,
                            JournalEvent.event_type.in_(BODY_SCAN_EVENTS),
                            star_system.is_not(None),
                        )
                    )
                ).all()
                if name
            ]

            sold = (
                await db.execute(
                    select(
                        func.sum(_json("$.TotalEarnings")).label("exploration"),
                        func.count().label("sales"),
                    ).where(
                        JournalEvent.session_id == row.id,
                        JournalEvent.event_type.in_(EXPLORATION_SALE_EVENTS),
                    )
                )
            ).one()

            trips.append(
                {
                    "session_id": int(row.id),
                    "journal_filename": row.journal_filename,
                    "commander_name": row.commander_name,
                    "ship_type": row.ship_type,
                    "started_at": _iso_or_none(row.start_time),
                    "ended_at": _iso_or_none(row.end_time),
                    # A session the recorder never saw close is still a real
                    # session; it is reported as unclosed, not as ongoing.
                    "end_recorded": row.end_time is not None,
                    "first_event_at": _iso_or_none(counts.first_event),
                    "last_event_at": _iso_or_none(counts.last_event),
                    "systems_visited": int(counts.systems_visited or 0),
                    "systems_honked": int(counts.systems_honked or 0),
                    "systems_surveyed": sorted(surveyed),
                    "bodies_scanned": int(counts.bodies_scanned or 0),
                    "first_discoveries": int(firsts or 0),
                    "surface_maps": int(counts.surface_maps or 0),
                    "organic_scans": int(counts.organic_scans or 0),
                    "jumps": int(counts.jumps or 0),
                    "jump_distance_ly": (
                        round(float(counts.jump_distance_ly), 2)
                        if counts.jump_distance_ly is not None
                        else None
                    ),
                    # Named "sold during", never "earned by": the sale events
                    # do not say which trip gathered the data.
                    "credits_sold_during_trip": (
                        int(sold.exploration) if sold.sales else None
                    ),
                    "sales_recorded": int(sold.sales or 0),
                }
            )
            if len(trips) >= bounded_limit:
                break

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _TRIPS_CAVEAT,
        "trip_unit": "recorded_session",
        "source_events": [
            *TRAVEL_EVENTS,
            *BODY_SCAN_EVENTS,
            *SYSTEM_SURVEY_EVENTS,
            *SURFACE_MAP_EVENTS,
            *ORGANIC_SCAN_EVENTS,
            *EXPLORATION_SALE_EVENTS,
        ],
        "returned": len(trips),
        "limit": bounded_limit,
        "sessions_without_exploration": sessions_without_exploration,
        "trips": trips,
        "nullprovider_safe": True,
    }


async def explored_systems(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int | None = None,
    star_system: str | None = None,
) -> dict[str, Any]:
    """Per-system survey record (LNA-035).

    Reports scanned-body count against the system's actual body count where
    the honk was recorded, plus first discoveries, surface maps, and whether
    the system was completely discovered.

    `star_system` narrows the record to one system. Operations asks that
    question for the system the Commander is standing in, and asking it here
    keeps one reader of these events rather than growing a second one beside
    it (Phase 14 R5-1).
    """
    bounded_limit = _clamp_limit(
        limit, EXPLORATION_DEFAULT_LIMIT, EXPLORATION_MAX_LIMIT
    )
    star_system_col = _json("$.StarSystem")
    body_name = _json("$.BodyName")
    system_name_fss = _json("$.SystemName")

    async with session_factory() as db:
        scan_rows = (
            await db.execute(
                select(
                    star_system_col.label("star_system"),
                    func.count(func.distinct(body_name)).label("bodies_scanned"),
                    func.min(JournalEvent.timestamp).label("first_scan"),
                    func.max(JournalEvent.timestamp).label("last_scan"),
                )
                .where(
                    JournalEvent.event_type.in_(BODY_SCAN_EVENTS),
                    star_system_col.is_not(None),
                    body_name.is_not(None),
                    *(
                        [star_system_col == star_system]
                        if star_system is not None
                        else []
                    ),
                )
                .group_by(star_system_col)
                .order_by(func.max(JournalEvent.timestamp).desc())
                .limit(bounded_limit)
            )
        ).all()

        names = [row.star_system for row in scan_rows if row.star_system]
        totals: dict[str, int] = {}
        complete: set[str] = set()
        first_discoveries: dict[str, int] = {}
        discovery_flagged: dict[str, int] = {}
        mapped: dict[str, int] = {}

        if names:
            # System honk: how many bodies the system actually holds.
            for row in (
                await db.execute(
                    select(
                        system_name_fss.label("system_name"),
                        func.max(_json("$.BodyCount")).label("body_count"),
                    )
                    .where(
                        JournalEvent.event_type.in_(SYSTEM_SURVEY_EVENTS),
                        system_name_fss.in_(names),
                    )
                    .group_by(system_name_fss)
                )
            ).all():
                if row.body_count is not None:
                    totals[row.system_name] = int(row.body_count)

            for row in (
                await db.execute(
                    select(system_name_fss.label("system_name")).where(
                        JournalEvent.event_type.in_(ALL_BODIES_EVENTS),
                        system_name_fss.in_(names),
                    )
                )
            ).all():
                if row.system_name:
                    complete.add(row.system_name)

            # Bodies whose journal reported the flag at all. Needed to tell
            # "every scanned body was undiscovered" (a real first-footfall
            # claim) apart from "the journal never said" — without it, a
            # system of unflagged scans would masquerade as virgin territory.
            for row in (
                await db.execute(
                    select(
                        star_system_col.label("star_system"),
                        func.count(func.distinct(body_name)).label("flagged"),
                    )
                    .where(
                        JournalEvent.event_type.in_(BODY_SCAN_EVENTS),
                        star_system_col.in_(names),
                        _json("$.WasDiscovered").is_not(None),
                    )
                    .group_by(star_system_col)
                )
            ).all():
                discovery_flagged[row.star_system] = int(row.flagged)

            # First discoveries: WasDiscovered false means nobody had scanned
            # this body before. Absent stays unknown and is not counted.
            for row in (
                await db.execute(
                    select(
                        star_system_col.label("star_system"),
                        func.count(func.distinct(body_name)).label("firsts"),
                    )
                    .where(
                        JournalEvent.event_type.in_(BODY_SCAN_EVENTS),
                        star_system_col.in_(names),
                        _json("$.WasDiscovered") == 0,
                    )
                    .group_by(star_system_col)
                )
            ).all():
                first_discoveries[row.star_system] = int(row.firsts)

            # Surface maps are recorded against the body, not the system, so
            # they are counted from the body name's system prefix match via a
            # separate grouping on the mapping event's own StarSystem field.
            for row in (
                await db.execute(
                    select(
                        star_system_col.label("star_system"),
                        func.count(func.distinct(body_name)).label("mapped"),
                    )
                    .where(
                        JournalEvent.event_type.in_(SURFACE_MAP_EVENTS),
                        star_system_col.in_(names),
                    )
                    .group_by(star_system_col)
                )
            ).all():
                mapped[row.star_system] = int(row.mapped)

    systems = []
    for row in scan_rows:
        name = row.star_system
        scanned = int(row.bodies_scanned)
        total = totals.get(name)
        firsts = first_discoveries.get(name, 0)
        flagged = discovery_flagged.get(name, 0)
        # First footfall is claimed only when the journal actually flagged
        # every scanned body and every one came back undiscovered. Silence is
        # not evidence of virgin territory.
        untouched = bool(scanned and flagged == scanned and firsts == scanned)
        systems.append(
            {
                "star_system": name,
                "bodies_scanned": scanned,
                "bodies_with_discovery_flag": flagged,
                "no_prior_discovery_recorded": untouched,
                # None means the honk was never recorded here. Callers must
                # render this as unknown, never as "scanned == total".
                "bodies_in_system": total,
                "body_count_known": total is not None,
                "survey_complete": name in complete,
                "first_discoveries": firsts,
                "bodies_surface_mapped": mapped.get(name, 0),
                "first_scan_at": _iso_or_none(row.first_scan),
                "last_scan_at": _iso_or_none(row.last_scan),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _SYSTEMS_CAVEAT,
        "source_events": [
            *BODY_SCAN_EVENTS,
            *SYSTEM_SURVEY_EVENTS,
            *ALL_BODIES_EVENTS,
            *SURFACE_MAP_EVENTS,
        ],
        "returned": len(systems),
        "limit": bounded_limit,
        "systems": systems,
        "nullprovider_safe": True,
    }


async def exploration_earnings(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """Credits actually received for exploration and exobiology data.

    Read from the sale events Frontier stamps with real values —
    SellExplorationData / MultiSellExplorationData (TotalEarnings) and
    SellOrganicData (per-entry Value plus Bonus). Nothing here is predicted.

    This is deliberately separate from any estimate of what unsold scans
    *might* fetch: one is money the Commander received, the other is a guess
    from community-derived formulas that Frontier rebalances. Adding them into
    a single figure would turn an estimate into an account balance, which is
    the exact shape Law 5 forbids.
    """
    async with session_factory() as db:
        exploration_rows = (
            await db.execute(
                select(
                    func.count().label("sales"),
                    func.sum(_json("$.TotalEarnings")).label("earned"),
                    func.min(JournalEvent.timestamp).label("first_sale"),
                    func.max(JournalEvent.timestamp).label("last_sale"),
                ).where(
                    JournalEvent.event_type.in_(EXPLORATION_SALE_EVENTS),
                    _json("$.TotalEarnings").is_not(None),
                )
            )
        ).one()

        organic_rows = (
            await db.execute(
                select(
                    func.count().label("sales"),
                    func.min(JournalEvent.timestamp).label("first_sale"),
                    func.max(JournalEvent.timestamp).label("last_sale"),
                ).where(JournalEvent.event_type.in_(ORGANIC_SALE_EVENTS))
            )
        ).one()

        # SellOrganicData carries a BioData[] array; sum its Value and Bonus
        # members rather than assuming a flat top-level total.
        organic_value = (
            await db.execute(
                select(
                    func.sum(
                        func.coalesce(
                            func.json_extract(
                                JournalEvent.raw_json, "$.BioData[0].Value"
                            ),
                            0,
                        )
                        + func.coalesce(
                            func.json_extract(
                                JournalEvent.raw_json, "$.BioData[0].Bonus"
                            ),
                            0,
                        )
                    ).label("earned")
                ).where(JournalEvent.event_type.in_(ORGANIC_SALE_EVENTS))
            )
        ).scalar()

        organic_samples = (
            await db.execute(
                select(
                    func.count().label("scans"),
                    func.count(func.distinct(_json("$.Species"))).label("species"),
                ).where(
                    JournalEvent.event_type.in_(ORGANIC_SCAN_EVENTS),
                )
            )
        ).one()

    exploration_sales = int(exploration_rows.sales or 0)
    organic_sales = int(organic_rows.sales or 0)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _EARNINGS_CAVEAT,
        "source_events": [
            *EXPLORATION_SALE_EVENTS,
            *ORGANIC_SALE_EVENTS,
            *ORGANIC_SCAN_EVENTS,
        ],
        "exploration": {
            # None, not 0: no recorded sale is "never sold here", which is not
            # the same claim as "sold for nothing".
            "credits_earned": (
                int(exploration_rows.earned) if exploration_sales else None
            ),
            "sales_recorded": exploration_sales,
            "first_sale_at": _iso_or_none(exploration_rows.first_sale),
            "last_sale_at": _iso_or_none(exploration_rows.last_sale),
        },
        "exobiology": {
            "credits_earned": int(organic_value) if organic_sales else None,
            "sales_recorded": organic_sales,
            "samples_recorded": int(organic_samples.scans or 0),
            "distinct_species_sampled": int(organic_samples.species or 0),
            "first_sale_at": _iso_or_none(organic_rows.first_sale),
            "last_sale_at": _iso_or_none(organic_rows.last_sale),
        },
        "nullprovider_safe": True,
    }


async def scanned_bodies(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    star_system: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Per-body scan detail (LNA-035), newest observation first."""
    bounded_limit = _clamp_limit(limit, BODIES_DEFAULT_LIMIT, BODIES_MAX_LIMIT)
    system_col = _json("$.StarSystem")
    body_col = _json("$.BodyName")

    async with session_factory() as db:
        conditions = [
            JournalEvent.event_type.in_(BODY_SCAN_EVENTS),
            body_col.is_not(None),
        ]
        if star_system:
            conditions.append(system_col == star_system)

        rows = (
            await db.execute(
                select(
                    body_col.label("body_name"),
                    system_col.label("star_system"),
                    func.max(JournalEvent.timestamp).label("last_scan"),
                    func.min(JournalEvent.timestamp).label("first_scan"),
                    func.max(_json("$.PlanetClass")).label("planet_class"),
                    func.max(_json("$.StarType")).label("star_type"),
                    func.max(_json("$.TerraformState")).label("terraform_state"),
                    func.max(_json("$.Landable")).label("landable"),
                    func.max(_json("$.DistanceFromArrivalLS")).label("distance_ls"),
                    func.max(_json("$.ScanType")).label("scan_type"),
                    func.min(_json("$.WasDiscovered")).label("was_discovered"),
                    func.min(_json("$.WasMapped")).label("was_mapped"),
                    func.count().label("scan_events"),
                )
                .where(*conditions)
                .group_by(body_col, system_col)
                .order_by(func.max(JournalEvent.timestamp).desc())
                .limit(bounded_limit)
            )
        ).all()

        mapped_bodies: set[tuple[str, str]] = set()
        if rows:
            for row in (
                await db.execute(
                    select(
                        body_col.label("body_name"),
                        system_col.label("star_system"),
                    ).where(
                        JournalEvent.event_type.in_(SURFACE_MAP_EVENTS),
                        body_col.is_not(None),
                    )
                )
            ).all():
                mapped_bodies.add((row.star_system, row.body_name))

    bodies = []
    for row in rows:
        discovered = _tri_state(row.was_discovered)
        mapped_flag = _tri_state(row.was_mapped)
        entry = {
            "body_name": row.body_name,
            "star_system": row.star_system,
            # Star or planet — whichever the journal reported.
            "planet_class": row.planet_class,
            "star_type": row.star_type,
            "terraform_state": row.terraform_state or None,
            "landable": _tri_state(row.landable),
            "distance_from_arrival_ls": row.distance_ls,
            "scan_type": row.scan_type,
            # "Was already discovered/mapped by someone" inverted into the
            # Commander-facing fact, with unknown preserved.
            "first_discovered_by_commander": (
                None if discovered is None else not discovered
            ),
            "first_mapped_by_commander": (
                None if mapped_flag is None else not mapped_flag
            ),
            "surface_mapped_by_commander": (
                row.star_system,
                row.body_name,
            )
            in mapped_bodies,
            "scan_events_recorded": int(row.scan_events),
            "first_scan_at": _iso_or_none(row.first_scan),
            "last_scan_at": _iso_or_none(row.last_scan),
        }
        # Reference estimate, clearly fenced from the observed fields above.
        # None when the class was never recorded: unclassified is unknown,
        # not worthless, and a caller must be able to tell those apart.
        entry["value_estimate"] = exploration_value.estimate_body_value(entry)
        bodies.append(entry)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _BODIES_CAVEAT,
        "source_events": [*BODY_SCAN_EVENTS, *SURFACE_MAP_EVENTS],
        "star_system": star_system,
        "returned": len(bodies),
        "limit": bounded_limit,
        "bodies": bodies,
        "value_estimate_summary": exploration_value.summarise_estimates(bodies),
        "nullprovider_safe": True,
    }
