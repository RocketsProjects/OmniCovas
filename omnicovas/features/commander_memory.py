"""Private, local-only Commander Memory for Phase 11 reconciliation.

Commander Memory is observed history, never current truth. It stores only an
allowlisted projection of local Journal and companion-snapshot facts. Raw Journal
JSON, chat/social/message content, filesystem paths, credentials, and provider
data are deliberately excluded.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.event_types import (
    COMMANDER_MEMORY_CATEGORY_DELETED,
    COMMANDER_MEMORY_CLEARED,
    COMMANDER_MEMORY_EXPORT_STAGED,
    COMMANDER_MEMORY_PAUSED,
    COMMANDER_MEMORY_PROFILE_FORGOTTEN,
    COMMANDER_MEMORY_PROFILE_PAUSED,
    COMMANDER_MEMORY_PROFILE_RESUMED,
    COMMANDER_MEMORY_REBUILT,
    COMMANDER_MEMORY_RESUMED,
)
from omnicovas.db.models import (
    CommanderMemoryObservation,
    CommanderMemoryProfile,
    CommanderMemoryRecord,
    CommanderMemorySettings,
    JournalEvent,
    Session,
)
from omnicovas.features import galactic_historian

logger = logging.getLogger(__name__)

MEMORY_CATEGORIES = frozenset(
    {"systems", "stations", "market", "outfitting", "shipyard"}
)
PROFILE_EVENTS = frozenset({"LoadGame", "Commander", "NewCommander"})
SYSTEM_EVENTS = frozenset({"FSDJump", "CarrierJump", "Location"})
STATION_EVENTS = frozenset({"Docked"})
DEFAULT_PROFILE_KEY = "local-default"
# Other per-commander stores join the forget workflow: a purge runs inside the
# forget transaction, a listener after it commits (GKI-04 Galactic Intelligence).
ForgetPurge = Callable[[AsyncSession, str], Awaitable[None]]
ForgetListener = Callable[[str], Awaitable[None]]
MEMORY_FRESHNESS = "remembered"
MEMORY_CAVEAT = (
    "Remembered from local observed history. It may be incomplete or stale and never "
    "outranks current Journal, Status, or current local snapshot state."
)
REBUILD_BATCH_SIZE = 500
MAX_MARKET_ITEMS = 5000
MAX_OUTFITTING_ITEMS = 5000
MAX_SHIPYARD_ITEMS = 1000


@dataclass(frozen=True, slots=True)
class MemoryObservationSpec:
    """Sanitized fact ready for persistent Memory aggregation."""

    category: str
    entity_key: str
    display_name: str
    parent_key: str | None
    parent_name: str | None
    observed_at: datetime
    visit_increment: int
    source_type: str
    source_event: str | None
    source_file: str | None
    payload: dict[str, Any]
    fingerprint: str


def _utcnow() -> datetime:
    """Return timezone-naive UTC for SQLite DateTime consistency."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_timestamp(value: object, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            parsed = fallback or _utcnow()
    else:
        parsed = fallback or _utcnow()
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: object, *, limit: int = 256) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    if not result:
        return None
    return result[:limit]


def _source_file_name(value: object) -> str | None:
    """Keep only a basename-like source class, never an absolute path."""
    text = _text(value, limit=1024)
    if text is None:
        return None
    return re.split(r"[\\/]", text)[-1][:128]


def profile_key_for_event(event: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return a stable pseudonymous profile key plus optional display name.

    Only the identity events (:data:`PROFILE_EVENTS`) name the Commander.  In any
    other event ``Name`` is a settlement, a material, a mission or a friend, and
    reading it switched the active commander to a phantom profile (GKI-06).
    """
    kind = event.get("event")
    if kind is not None and kind not in PROFILE_EVENTS:
        return None, None
    fid = _text(event.get("FID"), limit=128)
    commander = _text(
        event.get("Commander") or (event.get("Name") if kind else None), limit=64
    )
    identity = (
        f"fid:{fid}"
        if fid
        else (f"commander:{commander.casefold()}" if commander else None)
    )
    if identity is None:
        return None, commander
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return f"profile-{digest}", commander


def _canonical_fingerprint(parts: dict[str, Any]) -> str:
    encoded = json.dumps(
        parts, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _system_key(event: dict[str, Any]) -> str | None:
    address = event.get("SystemAddress")
    if isinstance(address, int):
        return f"address:{address}"
    name = _text(event.get("StarSystem"), limit=128)
    return f"name:{name.casefold()}" if name else None


def _station_key(event: dict[str, Any]) -> str | None:
    market_id = event.get("MarketID")
    if isinstance(market_id, int):
        return f"market:{market_id}"
    station = _text(event.get("StationName"), limit=128)
    system = _text(event.get("StarSystem"), limit=128)
    if not station:
        return None
    return f"name:{(system or 'unknown').casefold()}::{station.casefold()}"


def _system_payload(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "system_address": event.get("SystemAddress"),
        "star_pos": event.get("StarPos")
        if isinstance(event.get("StarPos"), list)
        else None,
        "allegiance": _text(event.get("SystemAllegiance"), limit=64),
        "economy": _text(
            event.get("SystemEconomy_Localised") or event.get("SystemEconomy"),
            limit=128,
        ),
        "second_economy": _text(
            event.get("SystemSecondEconomy_Localised")
            or event.get("SystemSecondEconomy"),
            limit=128,
        ),
        "government": _text(
            event.get("SystemGovernment_Localised") or event.get("SystemGovernment"),
            limit=128,
        ),
        "security": _text(
            event.get("SystemSecurity_Localised") or event.get("SystemSecurity"),
            limit=128,
        ),
        "population": event.get("Population")
        if isinstance(event.get("Population"), int)
        else None,
        "powers": [str(value)[:128] for value in event.get("Powers", [])[:20]]
        if isinstance(event.get("Powers"), list)
        else [],
        "powerplay_state": _text(event.get("PowerplayState"), limit=64),
    }


def _station_payload(event: dict[str, Any]) -> dict[str, Any]:
    faction = event.get("StationFaction")
    faction_name = (
        _text(faction.get("Name"), limit=128) if isinstance(faction, dict) else None
    )
    services = event.get("StationServices")
    return {
        "market_id": event.get("MarketID"),
        "station_type": _text(event.get("StationType"), limit=64),
        "faction": faction_name,
        "government": _text(
            event.get("StationGovernment_Localised") or event.get("StationGovernment"),
            limit=128,
        ),
        "allegiance": _text(event.get("StationAllegiance"), limit=64),
        "economy": _text(
            event.get("StationEconomy_Localised") or event.get("StationEconomy"),
            limit=128,
        ),
        "services": [str(value)[:64] for value in services[:100]]
        if isinstance(services, list)
        else [],
        "landing_pads": event.get("LandingPads")
        if isinstance(event.get("LandingPads"), dict)
        else None,
        "distance_from_star_ls": event.get("DistFromStarLS"),
    }


def observation_from_event(
    event: dict[str, Any],
    *,
    profile_key: str,
    source_file: str | None = None,
) -> MemoryObservationSpec | None:
    """Convert one allowlisted Journal event into sanitized Memory input."""
    event_type = _text(event.get("event"), limit=64)
    observed_at = _parse_timestamp(event.get("timestamp"))
    source_file = _source_file_name(source_file)

    if event_type in SYSTEM_EVENTS:
        display_name = _text(event.get("StarSystem"), limit=128)
        entity_key = _system_key(event)
        if not display_name or not entity_key:
            return None
        payload = _system_payload(event)
        category = "systems"
        parent_key = None
        parent_name = None
        visit_increment = 1
    elif event_type in STATION_EVENTS:
        display_name = _text(event.get("StationName"), limit=128)
        entity_key = _station_key(event)
        if not display_name or not entity_key:
            return None
        payload = _station_payload(event)
        category = "stations"
        parent_key = _system_key(event)
        parent_name = _text(event.get("StarSystem"), limit=128)
        visit_increment = 1
    else:
        return None

    # Identity is the observation itself, never the path that carried it. The
    # live watcher and a rebuild from retained history both see the same
    # physical Journal event; if the file name took part in identity they would
    # produce two fingerprints and double every visit count. `source_file` is
    # recorded as provenance metadata below.
    fingerprint = _canonical_fingerprint(
        {
            "profile": profile_key,
            "category": category,
            "entity": entity_key,
            "event": event_type,
            "timestamp": _iso(observed_at),
            "payload": payload,
        }
    )
    return MemoryObservationSpec(
        category=category,
        entity_key=entity_key,
        display_name=display_name,
        parent_key=parent_key,
        parent_name=parent_name,
        observed_at=observed_at,
        visit_increment=visit_increment,
        source_type="local_journal",
        source_event=event_type,
        source_file=source_file,
        payload=payload,
        fingerprint=fingerprint,
    )


def _snapshot_entity_key(
    snapshot: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    market_id = snapshot.get("market_id")
    station = _text(snapshot.get("station_name"), limit=128)
    system = _text(snapshot.get("star_system"), limit=128)
    if isinstance(market_id, int):
        return f"market:{market_id}", station, system
    if station:
        return (
            f"name:{(system or 'unknown').casefold()}::{station.casefold()}",
            station,
            system,
        )
    return None, station, system


def _market_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items = snapshot.get("items")
    if not isinstance(items, list):
        return []
    result: list[dict[str, Any]] = []
    for item in items[:MAX_MARKET_ITEMS]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "id": item.get("id"),
                "name": _text(
                    item.get("name_localised") or item.get("name"), limit=128
                ),
                "buy_price": item.get("buy_price"),
                "sell_price": item.get("sell_price"),
                "mean_price": item.get("mean_price"),
                "stock": item.get("stock"),
                "demand": item.get("demand"),
                "prohibited": item.get("prohibited"),
            }
        )
    return result


def _outfitting_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    items = snapshot.get("items")
    if not isinstance(items, list):
        return []
    return [
        {
            "id": item.get("id"),
            "name": _text(item.get("name"), limit=160),
            "buy_price": item.get("buy_price"),
        }
        for item in items[:MAX_OUTFITTING_ITEMS]
        if isinstance(item, dict)
    ]


def _shipyard_items(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    ships = snapshot.get("ships")
    if not isinstance(ships, list):
        return []
    return [
        {
            "id": ship.get("id"),
            "ship_type": _text(ship.get("ship_type"), limit=128),
            "ship_price": ship.get("ship_price"),
        }
        for ship in ships[:MAX_SHIPYARD_ITEMS]
        if isinstance(ship, dict)
    ]


def observations_from_local_context(
    snapshot: dict[str, Any],
    *,
    profile_key: str,
) -> list[MemoryObservationSpec]:
    """Return sanitized companion-snapshot observations from local context."""
    specs: list[MemoryObservationSpec] = []
    definitions = (
        ("market", "market_snapshot", _market_items),
        ("outfitting", "outfitting_snapshot", _outfitting_items),
        ("shipyard", "shipyard_snapshot", _shipyard_items),
    )
    for category, key, item_builder in definitions:
        candidate = snapshot.get(key)
        if not isinstance(candidate, dict):
            continue
        if candidate.get("freshness") == "not_loaded" or candidate.get("fallback"):
            continue
        items = item_builder(candidate)
        if not items:
            continue
        entity_key, station, system = _snapshot_entity_key(candidate)
        if entity_key is None:
            continue
        observed_at = _parse_timestamp(
            candidate.get("observed_at") or candidate.get("event_timestamp"),
            fallback=_utcnow(),
        )
        source_file = _source_file_name(
            candidate.get("source_file") or f"{category}.json"
        )
        payload = {
            "market_id": candidate.get("market_id"),
            "station_name": station,
            "star_system": system,
            "items": items,
            "item_count": len(items),
            "source_item_count": candidate.get("item_count"),
        }
        fingerprint = _canonical_fingerprint(
            {
                "profile": profile_key,
                "category": category,
                "entity": entity_key,
                "observed_at": _iso(observed_at),
                "payload": payload,
            }
        )
        specs.append(
            MemoryObservationSpec(
                category=category,
                entity_key=entity_key,
                display_name=station or f"Observed {category}",
                parent_key=None,
                parent_name=system,
                observed_at=observed_at,
                visit_increment=0,
                source_type="local_companion_snapshot",
                source_event=_text(candidate.get("source_event"), limit=64),
                source_file=source_file,
                payload=payload,
                fingerprint=fingerprint,
            )
        )
    return specs


class CommanderMemoryService:
    """Single local persistence owner for Commander Memory."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        activity_log: ActivityLog | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._activity_log = activity_log
        self._lock = asyncio.Lock()
        self._rebuilding = False
        self._active_profile_key: str | None = None
        self._current_journal_file: str | None = None
        self._forget_purges: list[ForgetPurge] = []
        self._forget_listeners: list[ForgetListener] = []

    def add_forget_hook(
        self,
        *,
        purge: ForgetPurge | None = None,
        after: ForgetListener | None = None,
    ) -> None:
        """Let another per-commander store take part in forgetting a profile.

        ``purge`` deletes that store's rows for the profile in the same transaction
        as Memory's own deletion, so a failed forget leaves both untouched.
        ``after`` runs once the forget has committed, for state outside the
        database (configuration, in-memory caches, open UI).
        """
        if purge is not None:
            self._forget_purges.append(purge)
        if after is not None:
            self._forget_listeners.append(after)

    @property
    def active_profile_key(self) -> str | None:
        """The commander profile the Journal last identified in this run, if any."""
        return self._active_profile_key

    def set_current_journal_file(self, journal_filename: str | None) -> None:
        """Name the Journal the live watcher is tailing, for record provenance.

        A rebuild reads the file name from the retained session, so without
        this the same observation would carry a file name or None depending on
        which path stored it first.
        """
        self._current_journal_file = _source_file_name(journal_filename)

    async def _settings(self, db: AsyncSession) -> CommanderMemorySettings:
        settings = await db.get(CommanderMemorySettings, 1)
        if settings is None:
            now = _utcnow()
            settings = CommanderMemorySettings(
                id=1,
                paused=False,
                active_profile_key=None,
                last_rebuild_at=None,
                created_at=now,
                updated_at=now,
            )
            db.add(settings)
            await db.flush()
        return settings

    async def _profile(
        self,
        db: AsyncSession,
        profile_key: str,
        *,
        display_name: str | None = None,
        observed_at: datetime | None = None,
    ) -> CommanderMemoryProfile:
        profile = await db.get(CommanderMemoryProfile, profile_key)
        when = observed_at or _utcnow()
        if profile is None:
            profile = CommanderMemoryProfile(
                profile_key=profile_key,
                display_name=display_name,
                paused=False,
                forgotten_at=None,
                first_seen_at=when,
                last_seen_at=when,
                created_at=_utcnow(),
                updated_at=_utcnow(),
            )
            db.add(profile)
            await db.flush()
            return profile
        if profile.forgotten_at is None:
            if display_name:
                profile.display_name = display_name
            if when < profile.first_seen_at:
                profile.first_seen_at = when
            if when > profile.last_seen_at:
                profile.last_seen_at = when
            profile.updated_at = _utcnow()
        return profile

    async def _store(
        self,
        db: AsyncSession,
        *,
        profile: CommanderMemoryProfile,
        spec: MemoryObservationSpec,
    ) -> bool:
        if profile.paused or profile.forgotten_at is not None:
            return False
        if await db.get(CommanderMemoryObservation, spec.fingerprint) is not None:
            return False

        db.add(
            CommanderMemoryObservation(
                fingerprint=spec.fingerprint,
                profile_key=profile.profile_key,
                category=spec.category,
                entity_key=spec.entity_key,
                observed_at=spec.observed_at,
                source_event=spec.source_event,
                source_file=spec.source_file,
            )
        )
        record = await db.scalar(
            select(CommanderMemoryRecord).where(
                CommanderMemoryRecord.profile_key == profile.profile_key,
                CommanderMemoryRecord.category == spec.category,
                CommanderMemoryRecord.entity_key == spec.entity_key,
            )
        )
        now = _utcnow()
        payload_json = json.dumps(spec.payload, sort_keys=True, ensure_ascii=False)
        # A Location is where a login found the Commander: it can show a first stay
        # in a system, but it is no arrival, so a relog adds no visit.  The ledger
        # row above still keeps it as an observation.
        relog = spec.source_event == "Location"
        if record is None:
            db.add(
                CommanderMemoryRecord(
                    profile_key=profile.profile_key,
                    category=spec.category,
                    entity_key=spec.entity_key,
                    display_name=spec.display_name,
                    parent_key=spec.parent_key,
                    parent_name=spec.parent_name,
                    first_seen_at=spec.observed_at,
                    last_seen_at=spec.observed_at,
                    observation_count=1,
                    visit_count=spec.visit_increment,
                    source_type=spec.source_type,
                    source_event=spec.source_event,
                    source_file=spec.source_file,
                    freshness=MEMORY_FRESHNESS,
                    caveat=MEMORY_CAVEAT,
                    payload_json=payload_json,
                    latest_fingerprint=spec.fingerprint,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            record.observation_count += 1
            record.visit_count += 0 if relog else spec.visit_increment
            if spec.observed_at < record.first_seen_at:
                record.first_seen_at = spec.observed_at
            if spec.observed_at >= record.last_seen_at:
                record.display_name = spec.display_name
                record.parent_key = spec.parent_key
                record.parent_name = spec.parent_name
                record.last_seen_at = spec.observed_at
                record.source_type = spec.source_type
                record.source_event = spec.source_event
                record.source_file = spec.source_file
                record.payload_json = payload_json
                record.latest_fingerprint = spec.fingerprint
            record.updated_at = now
        return True

    async def observe_event(self, event: dict[str, Any], raw_line: str = "") -> bool:
        """Observe one Journal event; raw_line is deliberately never persisted."""
        del raw_line
        async with self._lock, self._session_factory() as db:
            settings = await self._settings(db)
            event_profile, display_name = profile_key_for_event(event)
            if event_profile:
                self._active_profile_key = event_profile
                settings.active_profile_key = event_profile
                settings.updated_at = _utcnow()
            active_key = (
                self._active_profile_key
                or settings.active_profile_key
                or DEFAULT_PROFILE_KEY
            )
            if settings.paused:
                await db.commit()
                return False

            spec = observation_from_event(
                event,
                profile_key=active_key,
                source_file=self._current_journal_file,
            )
            # A profile row is the Commander's own entry in the privacy
            # controls, so only identity or something worth remembering may
            # create one. Every session opens with events that are neither
            # (Fileheader first of all); creating a row for those put an empty
            # unnamed profile, with live pause and forget controls, in front of
            # every Commander.
            stored = False
            if spec is not None or event_profile:
                profile = await self._profile(
                    db,
                    active_key,
                    display_name=display_name if event_profile else None,
                    observed_at=_parse_timestamp(event.get("timestamp")),
                )
                if spec is not None:
                    stored = await self._store(db, profile=profile, spec=spec)
            await db.commit()
            return stored

    async def ensure_initialized(self) -> dict[str, int] | None:
        """Perform the one-time backfill for an adopted pre-Memory database.

        A completed rebuild timestamp is retained even when the flight recorder
        is empty. Clear/delete actions therefore remain cleared across restart
        and are never silently undone by this bootstrap.
        """
        async with self._session_factory() as db:
            settings = await self._settings(db)
            initialized = settings.last_rebuild_at is not None
            await db.commit()
        if initialized:
            return None
        return await self.rebuild()

    async def observe_local_context(self, snapshot: dict[str, Any]) -> int:
        """Observe current companion snapshots with fingerprint deduplication."""
        async with self._lock, self._session_factory() as db:
            settings = await self._settings(db)
            if settings.paused:
                # _settings() may have created the singleton on first use.
                # Commit it even though acquisition is paused so this path
                # never discards durable control state on context exit.
                await db.commit()
                return 0
            active_key = (
                self._active_profile_key
                or settings.active_profile_key
                or DEFAULT_PROFILE_KEY
            )
            profile = await self._profile(db, active_key)
            stored = 0
            for spec in observations_from_local_context(
                snapshot, profile_key=active_key
            ):
                stored += int(await self._store(db, profile=profile, spec=spec))
            await db.commit()
            return stored

    async def status(self) -> dict[str, Any]:
        async with self._session_factory() as db:
            settings = await self._settings(db)
            category_rows = (
                await db.execute(
                    select(CommanderMemoryRecord.category, func.count())
                    .group_by(CommanderMemoryRecord.category)
                    .order_by(CommanderMemoryRecord.category)
                )
            ).all()
            profiles = (
                await db.scalars(
                    select(CommanderMemoryProfile).order_by(
                        CommanderMemoryProfile.last_seen_at.desc()
                    )
                )
            ).all()
            await db.commit()
        categories = {str(category): int(count) for category, count in category_rows}
        return {
            "paused": settings.paused,
            "rebuilding": self._rebuilding,
            "active_profile_key": settings.active_profile_key,
            "last_rebuild_at": _iso(settings.last_rebuild_at),
            "total_records": sum(categories.values()),
            "categories": {
                category: categories.get(category, 0)
                for category in sorted(MEMORY_CATEGORIES)
            },
            "profiles": [self._profile_payload(profile) for profile in profiles],
            "source": "commander_memory_local_db",
            "freshness": MEMORY_FRESHNESS,
            "truth_class": "local_observed_history",
            "caveat": MEMORY_CAVEAT,
            "nullprovider_safe": True,
        }

    @staticmethod
    def _profile_payload(profile: CommanderMemoryProfile) -> dict[str, Any]:
        return {
            "profile_key": profile.profile_key,
            "display_name": profile.display_name,
            "paused": profile.paused,
            "forgotten": profile.forgotten_at is not None,
            "first_seen_at": _iso(profile.first_seen_at),
            "last_seen_at": _iso(profile.last_seen_at),
        }

    @staticmethod
    def _familiarity(record: CommanderMemoryRecord, visits: int | None) -> str:
        count = visits or record.observation_count
        if count >= 10:
            return "Well known locally"
        if count >= 5:
            return "Familiar"
        if count >= 2 or record.observation_count >= 2:
            return "Known"
        return "Observed once"

    @staticmethod
    async def _system_visits(
        db: AsyncSession, records: Sequence[CommanderMemoryRecord]
    ) -> dict[int, int | None]:
        """Supported visits for system records, read from their own ledger.

        A stored system ``visit_count`` is not read: older rows counted every
        ``Location``, and nothing has to rewrite them for this to be true.  The
        ledger holds one row per observation, so if it no longer itemizes a record's
        observations its old total cannot be split into arrivals and logins, and the
        record has no supported total (None), never a minimum.
        """
        systems = [record for record in records if record.category == "systems"]
        if not systems:
            return {}
        rows = await db.execute(
            select(
                CommanderMemoryObservation.profile_key,
                CommanderMemoryObservation.entity_key,
                CommanderMemoryObservation.source_event,
                CommanderMemoryObservation.observed_at,
            ).where(
                CommanderMemoryObservation.category == "systems",
                CommanderMemoryObservation.profile_key.in_(
                    {record.profile_key for record in systems}
                ),
                CommanderMemoryObservation.entity_key.in_(
                    {record.entity_key for record in systems}
                ),
            )
        )
        ledger: dict[tuple[str, str], list[list[Any]]] = {}
        for profile_key, entity_key, event, observed_at in rows:
            ledger.setdefault((profile_key, entity_key), []).append(
                [event, _iso(observed_at)]
            )
        visits: dict[int, int | None] = {}
        for record in systems:
            occasions = ledger.get((record.profile_key, record.entity_key), [])
            visits[record.id] = (
                galactic_historian.visit_tally([{"occasions": occasions}])[0]
                if len(occasions) >= record.observation_count
                else None
            )
        return visits

    @classmethod
    def _record_payload(
        cls, record: CommanderMemoryRecord, visits: int | None
    ) -> dict[str, Any]:
        try:
            payload = json.loads(record.payload_json)
        except json.JSONDecodeError:
            payload = {}
        return {
            "id": record.id,
            "profile_key": record.profile_key,
            "category": record.category,
            "entity_key": record.entity_key,
            "display_name": record.display_name,
            "parent_key": record.parent_key,
            "parent_name": record.parent_name,
            "first_seen_at": _iso(record.first_seen_at),
            "last_seen_at": _iso(record.last_seen_at),
            "observation_count": record.observation_count,
            # None: the retained evidence does not establish a visit total.
            "visit_count": visits,
            "familiarity": cls._familiarity(record, visits),
            "source_type": record.source_type,
            "source_event": record.source_event,
            "source_file": record.source_file,
            "freshness": record.freshness,
            "truth_class": "local_observed_history",
            "caveat": record.caveat,
            "payload": payload,
        }

    async def list_records(
        self,
        *,
        category: str | None = None,
        profile_key: str | None = None,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 500))
        bounded_offset = max(0, int(offset))
        conditions: list[Any] = []
        if category:
            if category not in MEMORY_CATEGORIES:
                raise ValueError(f"Unsupported Commander Memory category: {category}")
            conditions.append(CommanderMemoryRecord.category == category)
        if profile_key:
            conditions.append(CommanderMemoryRecord.profile_key == profile_key)
        if query and query.strip():
            pattern = f"%{query.strip()[:128]}%"
            conditions.append(
                or_(
                    CommanderMemoryRecord.display_name.ilike(pattern),
                    CommanderMemoryRecord.parent_name.ilike(pattern),
                )
            )
        statement = select(CommanderMemoryRecord)
        count_statement = select(func.count()).select_from(CommanderMemoryRecord)
        if conditions:
            statement = statement.where(*conditions)
            count_statement = count_statement.where(*conditions)
        statement = (
            statement.order_by(
                CommanderMemoryRecord.last_seen_at.desc(),
                CommanderMemoryRecord.id.desc(),
            )
            .limit(bounded_limit)
            .offset(bounded_offset)
        )
        async with self._session_factory() as db:
            records = (await db.scalars(statement)).all()
            total = int((await db.scalar(count_statement)) or 0)
            system_visits = await self._system_visits(db, records)
        return {
            "records": [
                self._record_payload(
                    record, system_visits.get(record.id, record.visit_count)
                )
                for record in records
            ],
            "returned": len(records),
            "total": total,
            "limit": bounded_limit,
            "offset": bounded_offset,
            "source": "commander_memory_local_db",
            "freshness": MEMORY_FRESHNESS,
            "truth_class": "local_observed_history",
            "caveat": MEMORY_CAVEAT,
            "nullprovider_safe": True,
        }

    async def set_paused(self, paused: bool) -> dict[str, Any]:
        async with self._lock, self._session_factory() as db:
            settings = await self._settings(db)
            settings.paused = bool(paused)
            settings.updated_at = _utcnow()
            await db.commit()
        self._log_action(
            COMMANDER_MEMORY_PAUSED if paused else COMMANDER_MEMORY_RESUMED,
            "Commander Memory paused" if paused else "Commander Memory resumed",
            {"paused": bool(paused)},
        )
        return await self.status()

    async def set_profile_paused(self, profile_key: str, paused: bool) -> bool:
        async with self._lock, self._session_factory() as db:
            profile = await db.get(CommanderMemoryProfile, profile_key)
            if profile is None or profile.forgotten_at is not None:
                return False
            profile.paused = bool(paused)
            profile.updated_at = _utcnow()
            await db.commit()
        self._log_action(
            COMMANDER_MEMORY_PROFILE_PAUSED
            if paused
            else COMMANDER_MEMORY_PROFILE_RESUMED,
            "Commander Memory profile paused"
            if paused
            else "Commander Memory profile resumed",
            {"profile_key": profile_key, "paused": bool(paused)},
        )
        return True

    async def clear(self) -> int:
        async with self._lock, self._session_factory() as db:
            count = int(
                (
                    await db.scalar(
                        select(func.count()).select_from(CommanderMemoryRecord)
                    )
                )
                or 0
            )
            await db.execute(delete(CommanderMemoryObservation))
            await db.execute(delete(CommanderMemoryRecord))
            await db.commit()
        self._log_action(
            COMMANDER_MEMORY_CLEARED,
            "Commander Memory records cleared",
            {"deleted_records": count},
        )
        return count

    async def delete_category(self, category: str) -> int:
        if category not in MEMORY_CATEGORIES:
            raise ValueError(f"Unsupported Commander Memory category: {category}")
        async with self._lock, self._session_factory() as db:
            count = int(
                (
                    await db.scalar(
                        select(func.count())
                        .select_from(CommanderMemoryRecord)
                        .where(CommanderMemoryRecord.category == category)
                    )
                )
                or 0
            )
            await db.execute(
                delete(CommanderMemoryObservation).where(
                    CommanderMemoryObservation.category == category
                )
            )
            await db.execute(
                delete(CommanderMemoryRecord).where(
                    CommanderMemoryRecord.category == category
                )
            )
            await db.commit()
        self._log_action(
            COMMANDER_MEMORY_CATEGORY_DELETED,
            "Commander Memory category deleted",
            {"category": category, "deleted_records": count},
        )
        return count

    async def forget_profile(self, profile_key: str) -> int | None:
        async with self._lock, self._session_factory() as db:
            profile = await db.get(CommanderMemoryProfile, profile_key)
            if profile is None:
                return None
            count = int(
                (
                    await db.scalar(
                        select(func.count())
                        .select_from(CommanderMemoryRecord)
                        .where(CommanderMemoryRecord.profile_key == profile_key)
                    )
                )
                or 0
            )
            await db.execute(
                delete(CommanderMemoryObservation).where(
                    CommanderMemoryObservation.profile_key == profile_key
                )
            )
            await db.execute(
                delete(CommanderMemoryRecord).where(
                    CommanderMemoryRecord.profile_key == profile_key
                )
            )
            now = _utcnow()
            profile.display_name = None
            profile.paused = True
            profile.forgotten_at = now
            profile.updated_at = now
            settings = await self._settings(db)
            if settings.active_profile_key == profile_key:
                # Keep the pseudonymous tombstone active so subsequent events
                # from the still-running game session remain blocked instead of
                # falling through to the anonymous default profile.
                settings.active_profile_key = profile_key
                settings.updated_at = now
            for purge in self._forget_purges:
                await purge(db, profile_key)
            await db.commit()
        self._log_action(
            COMMANDER_MEMORY_PROFILE_FORGOTTEN,
            "Commander Memory profile forgotten and paused",
            {"profile_key": profile_key, "deleted_records": count},
        )
        for listener in self._forget_listeners:
            try:
                await listener(profile_key)
            except Exception:
                logger.exception("Commander Memory forget listener failed")
        return count

    async def export_payload(self) -> dict[str, Any]:
        status_payload = await self.status()
        records_payload = await self.list_records(limit=500, offset=0)
        all_records = list(records_payload["records"])
        offset = len(all_records)
        while offset < int(records_payload["total"]):
            page = await self.list_records(limit=500, offset=offset)
            all_records.extend(page["records"])
            offset += len(page["records"])
            if not page["records"]:
                break
        payload = {
            "exported_at": _iso(_utcnow()),
            "format": "omnicovas_commander_memory_v1",
            "posture": "local_private_observed_history",
            "settings": {
                "paused": status_payload["paused"],
                "last_rebuild_at": status_payload["last_rebuild_at"],
            },
            "profiles": status_payload["profiles"],
            "records": all_records,
            "caveat": MEMORY_CAVEAT,
            "nullprovider_safe": True,
        }
        self._log_action(
            COMMANDER_MEMORY_EXPORT_STAGED,
            "Commander Memory export payload staged for local download",
            {"record_count": len(all_records), "file_write_confirmed": False},
        )
        return payload

    async def rebuild(self) -> dict[str, int]:
        """Rebuild Memory deterministically from retained Journal history."""
        if self._rebuilding:
            raise RuntimeError("Commander Memory rebuild already in progress")
        async with self._lock:
            self._rebuilding = True
            try:
                async with self._session_factory() as db:
                    await db.execute(delete(CommanderMemoryObservation))
                    await db.execute(delete(CommanderMemoryRecord))
                    await db.commit()

                active_key = DEFAULT_PROFILE_KEY
                processed = 0
                stored = 0
                last_id = 0
                while True:
                    async with self._session_factory() as db:
                        rows = (
                            await db.execute(
                                select(JournalEvent, Session.journal_filename)
                                .join(Session, JournalEvent.session_id == Session.id)
                                .where(JournalEvent.id > last_id)
                                .order_by(JournalEvent.id.asc())
                                .limit(REBUILD_BATCH_SIZE)
                            )
                        ).all()
                        if not rows:
                            break
                        for event_row, journal_filename in rows:
                            last_id = int(event_row.id)
                            processed += 1
                            try:
                                event = json.loads(event_row.raw_json)
                            except json.JSONDecodeError:
                                continue
                            event_profile, display_name = profile_key_for_event(event)
                            if event_profile:
                                active_key = event_profile
                            spec = observation_from_event(
                                event,
                                profile_key=active_key,
                                source_file=journal_filename,
                            )
                            # Same rule as the live path: identity or an actual
                            # observation, never bookkeeping events.
                            if spec is None and not event_profile:
                                continue
                            profile = await self._profile(
                                db,
                                active_key,
                                display_name=display_name if event_profile else None,
                                observed_at=event_row.timestamp,
                            )
                            if spec is not None:
                                stored += int(
                                    await self._store(db, profile=profile, spec=spec)
                                )
                        await db.commit()

                async with self._session_factory() as db:
                    settings = await self._settings(db)
                    settings.active_profile_key = active_key
                    settings.last_rebuild_at = _utcnow()
                    settings.updated_at = _utcnow()
                    await db.commit()
                self._active_profile_key = active_key
                # The summary must describe the rebuild that actually ran. A
                # fixed "from retained local Journal history" claimed a source
                # that had been read even when nothing was: on a first launch
                # with no Elite folder, this was the only entry in the
                # Commander's Activity Log and on the Dashboard's Recent
                # Activity, asserting journal history that did not exist. The
                # counts were already in hand here and only reached the
                # payload (Law 5 — Zero Hallucination).
                self._log_action(
                    COMMANDER_MEMORY_REBUILT,
                    (
                        "Commander Memory rebuilt from retained local Journal history"
                        if processed
                        else (
                            "Commander Memory rebuilt; no retained local Journal "
                            "history was available to read"
                        )
                    ),
                    {"events_scanned": processed, "records_observed": stored},
                )
                return {"events_scanned": processed, "records_observed": stored}
            finally:
                self._rebuilding = False

    def _log_action(
        self, event_type: str, summary: str, payload: dict[str, Any]
    ) -> None:
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
                        "source": "commander_memory_local_db",
                        "freshness": MEMORY_FRESHNESS,
                        "truth_class": "local_observed_history",
                    }
                ],
                redaction_state="redacted",
                is_fact=True,
                surface_origin="privacy",
                source="commander_memory_local_db",
            )
        )

    @property
    def proof_available(self) -> bool:
        """Whether protected actions can write to the shared proof sink."""
        return self._activity_log is not None

    def record_proof(
        self, event_type: str, summary: str, payload: dict[str, Any]
    ) -> None:
        """Append a redacted Commander Memory lifecycle proof entry."""
        self._log_action(event_type, summary, payload)
