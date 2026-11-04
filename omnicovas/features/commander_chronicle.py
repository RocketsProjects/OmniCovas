"""Commander Chronicle (GKI-07): where the Commander has been, by evidence class.

The Chronicle reads evidence other stores already keep, and adds one small
commander-keyed table (:class:`~omnicovas.db.models.ChronicleEntry`) for what none
of them records:

* **Commander Memory**, read in place and never copied: star systems by
  SystemAddress and stations by MarketID.  A record known by name alone never
  matches a documented place.
* **Expeditions** (GKI-06, through :meth:`ExpeditionService.chronicle`): stops the
  Journal showed reached, stops the Commander marked complete, chapters read and
  the journey history.
* **Chronicle entries**: documented bodies and sites reached (``ApproachBody``,
  ``Touchdown``, a ``Location`` logged on the surface), documented stations and
  settlements approached (``DockingGranted``, ``ApproachSettlement``), departures
  from documented stations (``Undocked``), Codex registrations (``CodexEntry``),
  visits the Commander confirms and stories the Commander saves.

Journal rules, each refusal a recorded ``reason`` in :attr:`decisions`:

* Nothing is recorded for an unknown or forgotten commander, or while Commander
  Memory is paused: pausing Memory is the Commander's "stop remembering" switch.
* A site is reached only by a landing within 1 km of its exact documented
  position (:data:`galactic_knowledge.SITE_ARRIVAL_KM`, allowing for the
  position's rounding), a body only by SystemAddress and BodyID, a station only
  by MarketID.  A landing within 10 km of a site, or a ship recalled to the
  Commander's SRV, is ``site_nearby``: an approach.  An approach is never a
  visit, and a Codex registration is context, never a visit.
* A replayed event (the watcher's startup catch-up, an event older than one
  already processed, or one outside the replay window) is recorded silently and
  marked; the same Journal line is recorded once, by fingerprint, however often
  it arrives.  Nothing here notifies, pops up or speaks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core import journal_watcher
from omnicovas.core.dispatcher import EventHandler
from omnicovas.core.state_manager import StateManager
from omnicovas.db.models import (
    ChronicleEntry,
    CommanderMemoryObservation,
    CommanderMemoryProfile,
    CommanderMemoryRecord,
    CommanderMemorySettings,
)
from omnicovas.features import (
    commander_context,
    galactic_historian,
    galactic_intelligence,
    galactic_knowledge,
)
from omnicovas.features.galactic_intelligence import GalacticIntelligence
from omnicovas.features.galactic_knowledge import KnowledgeIndex

logger = logging.getLogger(__name__)

JsonDict = dict[str, Any]
Notify = Callable[[JsonDict], Awaitable[None]]

VERSION = "commander-chronicle-v1"
# Pushed when a commander's Chronicle is erased, so open UIs drop it.
CLEARED_EVENT = "CHRONICLE_CLEARED"
# Pushed when a live event or the Commander adds to the Chronicle.
RECORDED_EVENT = "CHRONICLE_RECORDED"
OBSERVED_EVENTS = (
    "Touchdown",
    "Location",
    "Undocked",
    "ApproachBody",
    "ApproachSettlement",
    "DockingGranted",
    "CodexEntry",
)
# ``station_docked``: a Location logged while docked.  Commander Memory records a
# station only from ``Docked``, so a login at a historic starport is kept here.
REACHED_KINDS = ("site_reached", "body_reached", "station_docked")
# ``site_nearby``: landed near an exactly placed site, with the distance measured.
APPROACH_KINDS = ("station_approached", "settlement_approached", "site_nearby")
# ``station_left``: an observed departure.  Never a visit; it closes a stay, so a later
# login at the station is a new stay rather than another look at the old one.
JOURNAL_KINDS = (*REACHED_KINDS, *APPROACH_KINDS, "codex", "station_left")
SAVE_TYPES = ("atlas", "narrative", "chapter")
DEFAULT_PROFILE_KEY = galactic_intelligence.DEFAULT_PROFILE_KEY
REPLAY_WINDOW_SECONDS = galactic_intelligence.REPLAY_WINDOW_SECONDS
MAX_JOURNAL_ENTRIES = 10_000
MAX_SAVED = 500
MAX_CONFIRMED = 1_000
NOTE_MAX = 200
TEXT_MAX = 128
TIMELINE_LIMIT = 100
SUGGESTED_LIMIT = 12
SEEN_EVENTS = 512
RECENT_DECISIONS = 25
# Timeline titles for approaches; visits are titled from their record's "how".
HOW = {
    "station_approached": "Docking granted at",
    "settlement_approached": "Approached",
    "site_nearby": "Landed near",
}
CAVEAT = (
    "The Chronicle holds what your Journal showed while OmniCOVAS was running and "
    "what you told it. A place without a record may still be somewhere you have "
    "been; nothing here is proof that you never went."
)


class ChronicleError(Exception):
    """Base for refusals the API maps to HTTP errors."""


class ChronicleNotFound(ChronicleError):
    """No such place, story or entry for this commander (404)."""


class ChronicleConflict(ChronicleError):
    """Refused in the current state (409): no commander, forgotten, a limit."""


class ChronicleUnavailable(ChronicleError):
    """The bundled knowledge or the database is unavailable (503)."""


# ── Journal evidence (pure) ──────────────────────────────────────────────────


def _text(value: Any, limit: int = TEXT_MAX) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:limit] or None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return commander_context.iso(value.replace(tzinfo=timezone.utc))


def _loads(raw: str | None) -> JsonDict:
    try:
        value = json.loads(raw) if raw else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _nearest_km(entries: list[ChronicleEntry]) -> float | None:
    """The closest measured landing among Chronicle entries, if any was measured."""
    found = [_loads(entry.payload_json).get("distance_km") for entry in entries]
    measured = [float(d) for d in found if isinstance(d, int | float)]
    return min(measured) if measured else None


def _digest(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def codex_record(event: JsonDict) -> JsonDict | None:
    """The fields of a ``CodexEntry`` the Chronicle keeps, or None if malformed.

    Field meanings follow the Journal (confirmed against the EDDN ``codexentry``
    schema and two independent parsers, 2026-10-31).  ``IsNewEntry`` means the
    Journal marked the entry new to the Commander's Codex, never a galaxy first.
    """
    entry_id = _int(event.get("EntryID"))
    address = _int(event.get("SystemAddress"))
    if entry_id is None or address is None:
        return None
    name = _text(event.get("Name_Localised")) or _text(event.get("Name"))
    if not name or name.startswith("$"):
        name = f"Codex entry {entry_id}"
    nearest = _text(event.get("NearestDestination_Localised")) or _text(
        event.get("NearestDestination")
    )
    return {
        "entry_id": entry_id,
        "name": name,
        "category": _text(event.get("Category_Localised"))
        or _text(event.get("Category")),
        "subcategory": _text(event.get("SubCategory_Localised"))
        or _text(event.get("SubCategory")),
        "region": _text(event.get("Region_Localised")) or _text(event.get("Region")),
        "system": _text(event.get("System")),
        "system_address": address,
        "body_id": _int(event.get("BodyID")),
        "latitude": _number(event.get("Latitude")),
        "longitude": _number(event.get("Longitude")),
        # A navigation-panel name near the scan: context only, never an identity.
        "nearest": nearest if nearest and not nearest.startswith("$") else None,
        "new_entry": event.get("IsNewEntry") is True,
        "new_traits": event.get("NewTraitsDiscovered") is True,
        "voucher": _int(event.get("VoucherAmount")),
    }


def journal_findings(
    event: JsonDict,
    knowledge: KnowledgeIndex | None,
    current: JsonDict | None = None,
) -> list[JsonDict]:
    """The Chronicle entries one Journal event earns; empty for anything else.

    ``current`` is the system in state, for events that name none (a docking
    grant).  Every match goes through the knowledge index's location matching, so
    a place is reached only by an exact identifier at the level it needs.
    """
    name = event.get("event")
    if name == "CodexEntry":
        codex = codex_record(event)
        return (
            [{"kind": "codex", "subject_id": None, "payload": codex}] if codex else []
        )
    if knowledge is None:
        return []
    address = _int(event.get("SystemAddress"))
    system = _text(event.get("StarSystem"))
    if address is None and current:
        address = current.get("system_address")
        system = system or current.get("system")
    if address is None and not system:
        return []
    seen: JsonDict = {"system_address": address, "system": system}
    if name == "Location" and event.get("Docked") is True:
        seen.update(
            market_id=_int(event.get("MarketID")),
            station=_text(event.get("StationName")),
        )
        wanted = {"station": "station_docked"}
    elif name in {"Touchdown", "Location"}:
        if not galactic_intelligence.is_landed(event):
            return []
        seen.update(
            body=_text(event.get("Body")),
            body_id=_int(event.get("BodyID")),
            latitude=_number(event.get("Latitude")),
            longitude=_number(event.get("Longitude")),
            player_controlled=galactic_intelligence.player_controlled(event),
        )
        wanted = {"surface": "site_reached", "body": "body_reached"}
    elif name == "ApproachBody":
        seen.update(body=_text(event.get("Body")), body_id=_int(event.get("BodyID")))
        wanted = {"body": "body_reached"}
    elif name == "DockingGranted":
        seen.update(
            market_id=_int(event.get("MarketID")),
            station=_text(event.get("StationName")),
        )
        wanted = {"station": "station_approached"}
    elif name == "Undocked":
        seen.update(
            market_id=_int(event.get("MarketID")),
            station=_text(event.get("StationName")),
        )
        wanted = {"station": "station_left"}
    elif name == "ApproachSettlement":
        seen.update(
            body=_text(event.get("BodyName")),
            body_id=_int(event.get("BodyID")),
            market_id=_int(event.get("MarketID")),
            station=_text(event.get("Name")),
        )
        wanted = {"station": "station_approached", "body": "settlement_approached"}
    else:
        return []
    observation = {k: v for k, v in seen.items() if v is not None}
    rows: list[JsonDict] = []
    for match in knowledge.match_location(observation)["matches"]:
        kind = wanted.get(match["level"])
        surface = match.get("surface")
        if (
            kind == "body_reached"
            and match["needs"] == "surface"
            and surface
            and surface["state"] == "nearby"
        ):
            # Landed near an exactly placed site: proximity, measured, not a visit.
            kind = "site_nearby"
        if kind is None or not match["exact"]:
            continue
        if kind in REACHED_KINDS and not match["reached"]:
            continue
        if kind in {"station_approached", "station_left"} and (
            match["needs"] != "station"
        ):
            continue
        if kind == "settlement_approached":
            # Near the settlement the event names, by body and by name: never
            # every place that happens to be on the same body.
            if match["kind"] != "settlement" or (
                (_text(event.get("Name")) or "").casefold()
                != str(match["name"]).casefold()
            ):
                continue
        rows.append(
            {
                "kind": kind,
                "subject_id": match["id"],
                "payload": {
                    "level": match["level"],
                    "basis": match["basis"],
                    "system": system,
                    "system_address": address,
                    **{
                        key: observation[key]
                        for key in ("body", "body_id", "latitude", "longitude")
                        if key in observation
                    },
                    **(
                        {
                            "distance_km": surface["distance_km"],
                            "ship_only": bool(surface.get("ship_only")),
                        }
                        if surface and kind in {"site_reached", "site_nearby"}
                        else {}
                    ),
                },
            }
        )
    return rows


def fingerprint(profile_key: str, finding: JsonDict, event: JsonDict) -> str:
    """One identity per commander, observation and place: replays dedupe on it."""
    payload = finding.get("payload") or {}
    return _digest(
        profile_key,
        finding["kind"],
        finding.get("subject_id") or "-",
        event.get("event"),
        event.get("timestamp"),
        event.get("SystemAddress"),
        event.get("BodyID"),
        event.get("MarketID"),
        payload.get("entry_id"),
    )


# ── Service ──────────────────────────────────────────────────────────────────


class ChronicleService:
    """The current commander's Chronicle, its Journal evidence and lifecycle.

    Owns no Journal reader: the dispatcher hands it events after the state
    handlers, Galactic Intelligence and the expeditions (see :func:`register`).
    The active commander, the forgotten check and preferences are Galactic
    Intelligence's (GKI-04); expedition progress is the expeditions' (GKI-06).
    """

    def __init__(
        self,
        state: StateManager,
        session_factory: async_sessionmaker[AsyncSession] | None,
        intelligence: GalacticIntelligence,
        *,
        expeditions: Any = None,
        profile_provider: Callable[[], str | None] | None = None,
        notify: Notify | None = None,
        knowledge_provider: Callable[[], KnowledgeIndex] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state = state
        self._session_factory = session_factory
        self._intelligence = intelligence
        self._expeditions = expeditions
        self._profile_provider = profile_provider or (lambda: None)
        self._notify = notify
        self._knowledge_provider = knowledge_provider or galactic_knowledge.index
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = asyncio.Lock()
        self._seen_events: deque[str] = deque(maxlen=SEEN_EVENTS)
        self._latest_at: datetime | None = None
        self.decisions: deque[JsonDict] = deque(maxlen=RECENT_DECISIONS)

    # Commander ---------------------------------------------------------------

    def profile_key(self) -> str:
        return self._profile_provider() or DEFAULT_PROFILE_KEY

    async def profile(self) -> JsonDict:
        key = self.profile_key()
        paused = False
        if self._session_factory is not None:
            async with self._session_factory() as db:
                paused = await self._paused(db, key)
        return {
            "profile_key": key,
            "commander_known": self._profile_provider() is not None,
            "forgotten": await self._intelligence.is_forgotten(key),
            "memory_paused": paused,
        }

    async def _writable(self) -> str:
        if self._profile_provider() is None:
            raise ChronicleConflict(
                "No commander identified yet. The Chronicle starts once the Journal "
                "names your commander."
            )
        key = self.profile_key()
        if await self._intelligence.is_forgotten(key):
            raise ChronicleConflict(
                "This commander was forgotten in Commander Memory; nothing is kept "
                "for them."
            )
        return key

    def knowledge(self) -> KnowledgeIndex | None:
        if galactic_knowledge.catalog()["state"] != "available":
            return None
        return self._knowledge_provider()

    def _required_knowledge(self) -> KnowledgeIndex:
        knowledge = self.knowledge()
        if knowledge is None:
            raise ChronicleUnavailable("Galactic knowledge is not available")
        return knowledge

    def _factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise ChronicleUnavailable("Chronicle persistence is not initialized")
        return self._session_factory

    def _current_system(self) -> JsonDict | None:
        context = self._state.public_snapshot().get("local_system_context")
        if not isinstance(context, dict):
            return None
        return {
            "system": context.get("star_system"),
            "system_address": context.get("system_address"),
            "star_pos": context.get("star_pos"),
        }

    @staticmethod
    async def _paused(db: AsyncSession, profile_key: str) -> bool:
        """Whether Commander Memory is paused, globally or for this commander."""
        settings = await db.get(CommanderMemorySettings, 1)
        if settings is not None and settings.paused:
            return True
        profile = await db.get(CommanderMemoryProfile, profile_key)
        return bool(profile is not None and profile.paused)

    # Journal evidence --------------------------------------------------------

    def _decide(
        self, outcome: str, reason: str, event: JsonDict, **extra: Any
    ) -> JsonDict:
        decision = {
            "outcome": outcome,
            "reason": reason,
            "event": event.get("event"),
            "timestamp": event.get("timestamp"),
            "decided_at": commander_context.iso(self._clock()),
            "profile_key": self.profile_key(),
            **extra,
        }
        self.decisions.appendleft(decision)
        return decision

    def recent_decisions(self) -> list[JsonDict]:
        profile = self.profile_key()
        return [d for d in self.decisions if d.get("profile_key") == profile]

    async def observe(self, event: JsonDict) -> JsonDict:
        """Record what one Journal event shows about documented places or the Codex."""
        name = event.get("event")
        if name not in OBSERVED_EVENTS:
            return self._decide("ignored", "not_a_chronicle_event", event)
        now = self._clock()
        observed_at = commander_context.parse_timestamp(event.get("timestamp"))
        if observed_at is None:
            return self._decide("suppressed", "no_timestamp", event)
        identity = galactic_intelligence.event_key("", event)
        if identity in self._seen_events:
            return self._decide("suppressed", "duplicate_event", event)
        self._seen_events.append(identity)
        latest = self._latest_at
        if latest is None or observed_at > latest:
            self._latest_at = observed_at
        if journal_watcher.is_startup_replay():
            replay = "startup_replay"
        elif latest is not None and observed_at < latest:
            replay = "out_of_order"
        elif abs((now - observed_at).total_seconds()) > REPLAY_WINDOW_SECONDS:
            replay = "replay"
        else:
            replay = None
        if self._profile_provider() is None:
            return self._decide("suppressed", "commander_unknown", event)
        profile = self.profile_key()
        if await self._intelligence.is_forgotten(profile):
            return self._decide("suppressed", "commander_forgotten", event)
        if self._session_factory is None:
            return self._decide("suppressed", "no_persistence", event)
        findings = journal_findings(event, self.knowledge(), self._current_system())
        if not findings:
            return self._decide("ignored", "nothing_documented", event)
        stored: list[JsonDict] = []
        async with self._lock, self._session_factory() as db:
            if await self._paused(db, profile):
                return self._decide("suppressed", "memory_paused", event)
            stamp = _naive(observed_at)
            for finding in findings:
                key = fingerprint(profile, finding, event)
                if await db.scalar(
                    select(ChronicleEntry.entry_id).where(
                        ChronicleEntry.profile_key == profile,
                        ChronicleEntry.fingerprint == key,
                    )
                ):
                    continue
                db.add(
                    ChronicleEntry(
                        entry_id=uuid4().hex,
                        profile_key=profile,
                        kind=finding["kind"],
                        evidence="observed",
                        subject_id=finding["subject_id"],
                        fingerprint=key,
                        observed_at=stamp,
                        created_at=_naive(now),
                        source_event=str(name),
                        replayed=replay is not None,
                        payload_json=_dumps(finding["payload"] or {}),
                    )
                )
                stored.append(finding)
            if stored:
                await db.flush()
                await self._prune(db, profile)
                await db.commit()
        if stored and replay is None:
            await self._push(
                RECORDED_EVENT,
                {
                    "kinds": sorted({f["kind"] for f in stored}),
                    "subjects": [f["subject_id"] for f in stored if f["subject_id"]],
                },
            )
        return self._decide(
            "recorded" if stored else "no_change",
            replay or ("observed" if stored else "already_recorded"),
            event,
            entries=len(stored),
        )

    @staticmethod
    async def _prune(db: AsyncSession, profile: str) -> None:
        """Keep the newest Journal entries per commander; never the Commander's own."""
        cutoff = await db.scalar(
            select(ChronicleEntry.observed_at)
            .where(
                ChronicleEntry.profile_key == profile,
                ChronicleEntry.evidence == "observed",
            )
            .order_by(ChronicleEntry.observed_at.desc())
            .offset(MAX_JOURNAL_ENTRIES)
            .limit(1)
        )
        if cutoff is not None:
            await db.execute(
                delete(ChronicleEntry).where(
                    ChronicleEntry.profile_key == profile,
                    ChronicleEntry.evidence == "observed",
                    ChronicleEntry.observed_at <= cutoff,
                )
            )

    async def _push(self, event_type: str, payload: JsonDict) -> None:
        if self._notify is None:
            return
        try:
            await self._notify(
                {
                    "event_type": event_type,
                    "timestamp": commander_context.iso(self._clock()),
                    "payload": payload,
                    "source": "commander_chronicle",
                }
            )
        except Exception:
            logger.exception("Chronicle push failed")

    # Reading -----------------------------------------------------------------

    @staticmethod
    async def _rows(db: AsyncSession, profile: str) -> list[ChronicleEntry]:
        found = await db.scalars(
            select(ChronicleEntry)
            .where(ChronicleEntry.profile_key == profile)
            .order_by(ChronicleEntry.observed_at)
        )
        return list(found)

    async def _journeys(self, profile: str) -> JsonDict:
        if self._expeditions is None:
            return {"expeditions": [], "stops": []}
        try:
            found: JsonDict = await self._expeditions.chronicle(profile)
            return found
        except Exception:
            logger.exception("Expedition evidence for the Chronicle is unavailable")
            return {"expeditions": [], "stops": []}

    @staticmethod
    async def _records(
        db: AsyncSession,
        profile: str,
        knowledge: KnowledgeIndex,
        rows: list[ChronicleEntry],
        stops: list[JsonDict],
    ) -> dict[str, JsonDict]:
        """Every documented place's Chronicle state for one commander.

        Commander Memory is matched by the place's own identifiers only (never by
        the gazetteer, never by name); arriving in a system is presence, kept apart
        from a visit to anything in it.
        """
        places = knowledge.places()
        by_address: dict[int, list[str]] = {}
        by_market: dict[int, str] = {}
        for place_id, place in places.items():
            identity = knowledge.identity(place_id) or {}
            address = identity.get("system_address")
            if address is not None:
                by_address.setdefault(address, []).append(place_id)
            market = identity.get("market_id")
            if place["reached_at"] == "station" and market is not None:
                by_market[market] = place_id
        memory: dict[tuple[str, str], CommanderMemoryRecord] = {}
        keys = [f"address:{a}" for a in by_address] + [f"market:{m}" for m in by_market]
        if keys:
            found = await db.scalars(
                select(CommanderMemoryRecord).where(
                    CommanderMemoryRecord.profile_key == profile,
                    CommanderMemoryRecord.category.in_(("systems", "stations")),
                    CommanderMemoryRecord.entity_key.in_(keys),
                )
            )
            memory = {(r.category, r.entity_key): r for r in found}
        # Memory's ledger holds one row per counted observation, written and
        # deleted with the record, so its visits can be united with other evidence.
        ledger: dict[tuple[str, str], list[list[Any]]] = {}
        if memory:
            rows_seen = await db.execute(
                select(
                    CommanderMemoryObservation.category,
                    CommanderMemoryObservation.entity_key,
                    CommanderMemoryObservation.source_event,
                    CommanderMemoryObservation.observed_at,
                ).where(
                    CommanderMemoryObservation.profile_key == profile,
                    CommanderMemoryObservation.category.in_(("systems", "stations")),
                    CommanderMemoryObservation.entity_key.in_(keys),
                )
            )
            for category, entity, event, at in rows_seen:
                ledger.setdefault((category, entity), []).append([event, _iso(at)])
        observed: dict[str, list[JsonDict]] = {}
        commander: dict[str, list[JsonDict]] = {}
        presence: dict[str, JsonDict] = {}
        approached: dict[str, JsonDict] = {}
        for address, ids in by_address.items():
            row = memory.get(("systems", f"address:{address}"))
            if row is None:
                continue
            seen = {
                "first_at": _iso(row.first_seen_at),
                "last_at": _iso(row.last_seen_at),
                "count": row.visit_count,
            }
            for place_id in ids:
                if places[place_id]["reached_at"] == "system":
                    observed.setdefault(place_id, []).append(
                        {
                            "at": seen["first_at"],
                            "last_at": seen["last_at"],
                            "count": row.visit_count,
                            "how": "Arrived in the system",
                            "source": "commander_memory",
                            "event": row.source_event,
                            "occasions": ledger.get(
                                ("systems", f"address:{address}"), []
                            ),
                            # Older aggregates also counted logins.
                            "unit": "observations",
                        }
                    )
                else:
                    presence[place_id] = seen
        for market, place_id in by_market.items():
            row = memory.get(("stations", f"market:{market}"))
            if row is not None:
                observed.setdefault(place_id, []).append(
                    {
                        "at": _iso(row.first_seen_at),
                        "last_at": _iso(row.last_seen_at),
                        "count": row.visit_count,
                        "how": "Docked",
                        "source": "commander_memory",
                        "event": "Docked",
                        "occasions": ledger.get(("stations", f"market:{market}"), []),
                        "unit": "arrivals",
                    }
                )
        grouped: dict[tuple[str, str], list[ChronicleEntry]] = {}
        for entry in rows:
            if entry.subject_id in places and entry.kind != "saved":
                grouped.setdefault((entry.kind, entry.subject_id), []).append(entry)
        departures: dict[str, list[str]] = {}
        for (kind, place_id), entries in grouped.items():
            first, last = entries[0], entries[-1]
            nearest = _nearest_km(entries)
            if kind == "station_left":
                departures[place_id] = [
                    str(_iso(entry.observed_at)) for entry in entries
                ]
                continue
            if kind in REACHED_KINDS:
                observed.setdefault(place_id, []).append(
                    {
                        "at": _iso(first.observed_at),
                        "last_at": _iso(last.observed_at),
                        "count": len(entries),
                        "how": {
                            "site_reached": "Landed within "
                            f"{galactic_knowledge.SITE_ARRIVAL_KM:g} km of its "
                            "documented position",
                            "body_reached": "Reached the body",
                            "station_docked": "Docked (the Journal showed you docked "
                            "here)",
                        }[kind],
                        "source": "chronicle",
                        "event": last.source_event,
                        "occasions": [
                            [entry.source_event, _iso(entry.observed_at)]
                            for entry in entries
                        ],
                    }
                )
            elif kind in APPROACH_KINDS:
                if kind != "site_nearby" and place_id in approached:
                    continue  # a measured nearby landing says more
                approached[place_id] = {
                    "first_at": _iso(first.observed_at),
                    "last_at": _iso(last.observed_at),
                    "count": len(entries),
                    "how": {
                        "station_approached": "Docking granted",
                        "settlement_approached": "Approached the settlement",
                        "site_nearby": f"Landed about {nearest:.1f} km from it"
                        if nearest is not None
                        else "Landed nearby",
                    }[kind],
                    **({"distance_km": nearest} if kind == "site_nearby" else {}),
                }
            elif kind == "confirmed":
                commander.setdefault(place_id, []).append(
                    {
                        "at": _iso(first.observed_at),
                        "note": _loads(first.payload_json).get("note"),
                        "via": "chronicle",
                    }
                )
        for stop in stops:
            stop_place = stop.get("place_id")
            if not isinstance(stop_place, str) or stop_place not in places:
                continue
            if stop.get("reached") and stop.get("reached_at"):
                observed.setdefault(stop_place, []).append(
                    {
                        "at": stop["reached_at"],
                        "how": "Reached on the expedition "
                        f"{stop['expedition']['name']}",
                        "source": "expedition",
                        "event": stop.get("reached_event"),
                        "occasions": [[stop.get("reached_event"), stop["reached_at"]]]
                        if stop.get("reached_event")
                        else [],
                    }
                )
            if stop.get("manual_state") == "completed":
                commander.setdefault(stop_place, []).append(
                    {
                        "at": stop.get("manual_at"),
                        "note": None,
                        "via": "expedition",
                        "expedition": stop["expedition"]["name"],
                    }
                )
        return {
            place_id: galactic_historian.record(
                place,
                observed=observed.get(place_id, []),
                commander=commander.get(place_id, []),
                presence=presence.get(place_id),
                approached=approached.get(place_id),
                departures=departures.get(place_id),
            )
            for place_id, place in places.items()
        }

    async def records_for(self, profile: str) -> dict[str, JsonDict]:
        """Every documented place's state for one commander (empty if unknown)."""
        knowledge = self.knowledge()
        if knowledge is None or self._session_factory is None:
            return {}
        journeys = await self._journeys(profile)
        async with self._session_factory() as db:
            rows = await self._rows(db, profile)
            return await self._records(db, profile, knowledge, rows, journeys["stops"])

    async def briefing_history(
        self,
        profile: str,
        knowledge: KnowledgeIndex,
        observation: JsonDict,
        event: JsonDict,
    ) -> JsonDict | None:
        """Evidence for a GKI-04 briefing: records, chapters set here, position.

        Read before this event's own Chronicle entry is written; Commander Memory
        has already recorded the event, which :func:`visited_before` allows for.
        """
        del event
        if self._session_factory is None:
            return None
        journeys = await self._journeys(profile)
        async with self._session_factory() as db:
            rows = await self._rows(db, profile)
            records = await self._records(
                db, profile, knowledge, rows, journeys["stops"]
            )
        matched = [m["id"] for m in knowledge.match_location(observation)["matches"]]
        chapters: list[JsonDict] = []
        if self._expeditions is not None and matched:
            chapters = await self._expeditions.chapters_at(profile, matched)
        return {
            "records": records,
            "chapters": chapters,
            "origin_pos": (self._current_system() or {}).get("star_pos"),
        }

    async def chronicle(self) -> JsonDict:
        """The current commander's Chronicle: places, Codex, journeys, timeline."""
        profile = await self.profile()
        knowledge = self.knowledge()
        result: JsonDict = {
            "version": VERSION,
            "profile": profile,
            "knowledge": "available" if knowledge is not None else "unavailable",
            "caveat": CAVEAT,
            "counts": {
                "observed": 0,
                "commander_confirmed": 0,
                "suggested": 0,
                "unknown": 0,
                "codex": 0,
                "saved": 0,
                "expeditions": 0,
            },
            "memory": {"systems": 0, "stations": 0},
            "places": [],
            "codex": [],
            "expeditions": [],
            "saved": [],
            "suggested": [],
            "timeline": [],
        }
        if (
            profile["forgotten"]
            or not profile["commander_known"]
            or self._session_factory is None
        ):
            return result
        key = profile["profile_key"]
        journeys = await self._journeys(key)
        async with self._session_factory() as db:
            rows = await self._rows(db, key)
            records = (
                await self._records(db, key, knowledge, rows, journeys["stops"])
                if knowledge is not None
                else {}
            )
            counted = await db.execute(
                select(CommanderMemoryRecord.category, func.count())
                .where(
                    CommanderMemoryRecord.profile_key == key,
                    CommanderMemoryRecord.category.in_(("systems", "stations")),
                )
                .group_by(CommanderMemoryRecord.category)
            )
            totals: dict[str, int] = {
                str(category): int(count) for category, count in counted.all()
            }
        places = knowledge.places() if knowledge is not None else {}
        listed = []
        for place_id, state in records.items():
            if state["class"] not in {"observed", "commander_confirmed"}:
                continue
            place = places[place_id]
            listed.append(
                {
                    "place": {
                        "id": place_id,
                        "name": place["name"],
                        "kind": place["kind"],
                    },
                    "atlas": place["atlas"],
                    "system": place["system"],
                    "precision": place["precision"],
                    "record": state,
                }
            )
        listed.sort(
            key=lambda row: str(
                row["record"]["last_at"]
                or (row["record"]["confirmation"] or {}).get("at")
                or ""
            ),
            reverse=True,
        )
        visited = [row["place"]["id"] for row in listed]
        current = self._current_system()
        suggested = (
            galactic_historian.explore_next(
                knowledge,
                visited,
                records=records,
                origin_pos=(current or {}).get("star_pos"),
                exclude=set(visited),
                limit=SUGGESTED_LIMIT,
            )
            if knowledge is not None and visited
            else []
        )
        codex = self._codex_view(rows, knowledge)
        saved = self._saved_view(rows, knowledge)
        result.update(
            places=listed,
            codex=codex,
            saved=saved,
            suggested=suggested,
            expeditions=[
                {key: row[key] for key in row if key != "history"}
                for row in journeys["expeditions"]
            ],
            memory={
                "systems": int(totals.get("systems", 0)),
                "stations": int(totals.get("stations", 0)),
            },
            timeline=self._timeline(records, places, rows, journeys["expeditions"]),
        )
        result["counts"] = {
            "observed": sum(1 for r in listed if r["record"]["class"] == "observed"),
            "commander_confirmed": sum(
                1 for r in listed if r["record"]["class"] == "commander_confirmed"
            ),
            "suggested": len(suggested),
            "unknown": sum(1 for r in records.values() if r["class"] == "unknown"),
            "codex": len(codex),
            "saved": len(saved),
            "expeditions": len(journeys["expeditions"]),
        }
        return result

    @staticmethod
    def _codex_view(
        rows: list[ChronicleEntry], knowledge: KnowledgeIndex | None
    ) -> list[JsonDict]:
        """Codex registrations, one row per entry and place, newest first.

        A documented place in the same system is named as context; a Codex scan
        there is not a visit to it.
        """
        grouped: dict[tuple[Any, Any, Any], list[ChronicleEntry]] = {}
        payloads: dict[str, JsonDict] = {}
        for entry in rows:
            if entry.kind != "codex":
                continue
            payload = _loads(entry.payload_json)
            payloads[entry.entry_id] = payload
            group = (
                payload.get("entry_id"),
                payload.get("system_address"),
                payload.get("body_id"),
            )
            grouped.setdefault(group, []).append(entry)
        documented: dict[int, list[JsonDict]] = {}
        if knowledge is not None:
            for place_id, place in knowledge.places().items():
                identity = knowledge.identity(place_id) or {}
                if place["atlas"] and identity.get("system_address") is not None:
                    documented.setdefault(identity["system_address"], []).append(
                        {"id": place_id, "name": place["name"], "kind": place["kind"]}
                    )
        out = []
        for (_, address, body_id), entries in grouped.items():
            latest = payloads[entries[-1].entry_id]
            here = documented.get(address, []) if isinstance(address, int) else []
            out.append(
                {
                    **{
                        key: latest.get(key)
                        for key in (
                            "entry_id",
                            "name",
                            "category",
                            "subcategory",
                            "region",
                            "system",
                            "system_address",
                            "nearest",
                        )
                    },
                    "body_id": body_id,
                    "first_at": _iso(entries[0].observed_at),
                    "last_at": _iso(entries[-1].observed_at),
                    "count": len(entries),
                    "new_entry": any(
                        payloads[e.entry_id].get("new_entry") for e in entries
                    ),
                    "voucher": max(
                        (payloads[e.entry_id].get("voucher") or 0 for e in entries),
                        default=0,
                    )
                    or None,
                    "evidence": "observed",
                    "documented_here": here,
                    "note": "Recorded in a documented system. A Codex entry is not "
                    "a visit to the places documented there."
                    if here
                    else None,
                }
            )
        out.sort(key=lambda row: str(row["last_at"]), reverse=True)
        return out

    @staticmethod
    def _saved_view(
        rows: list[ChronicleEntry], knowledge: KnowledgeIndex | None
    ) -> list[JsonDict]:
        out = []
        for entry in rows:
            if entry.kind != "saved":
                continue
            payload = _loads(entry.payload_json)
            target = payload.get("target") or {}
            available = knowledge is not None and _saved_target(knowledge, target)
            out.append(
                {
                    "entry_id": entry.entry_id,
                    "type": target.get("type"),
                    "target_id": target.get("id"),
                    "chapter_id": target.get("chapter"),
                    "title": payload.get("title"),
                    "kind": payload.get("kind"),
                    "at": _iso(entry.observed_at),
                    "available": bool(available),
                }
            )
        out.sort(key=lambda row: str(row["at"]), reverse=True)
        return out

    @staticmethod
    def _timeline(
        records: dict[str, JsonDict],
        places: dict[str, JsonDict],
        rows: list[ChronicleEntry],
        journeys: list[JsonDict],
    ) -> list[JsonDict]:
        """What happened, newest first: visits, discoveries, journeys, choices."""
        items: list[JsonDict] = []
        for place_id, state in records.items():
            if state["class"] != "observed":
                continue
            latest = state["observations"][-1]
            items.append(
                {
                    "at": state["last_at"],
                    "type": "visit",
                    "evidence": "observed",
                    "title": f"{latest['how']}: {places[place_id]['name']}",
                    "detail": f"First observed {state['first_at']}; "
                    f"{state['count']} observation(s)",
                    "subject": {
                        "id": place_id,
                        "name": places[place_id]["name"],
                        "kind": places[place_id]["kind"],
                    },
                }
            )
        for entry in rows:
            payload = _loads(entry.payload_json)
            place = places.get(entry.subject_id or "")
            subject = (
                {"id": entry.subject_id, "name": place["name"], "kind": place["kind"]}
                if place
                else None
            )
            if entry.kind == "codex":
                title, evidence = f"Codex: {payload.get('name')}", "observed"
                detail = " · ".join(
                    str(v)
                    for v in (payload.get("category"), payload.get("system"))
                    if v
                )
            elif entry.kind in APPROACH_KINDS and place:
                title, evidence = f"{HOW[entry.kind]} {place['name']}", "observed"
                distance = payload.get("distance_km")
                detail = (
                    f"About {float(distance):.1f} km from its documented position: "
                    "nearby, not a visit."
                    if isinstance(distance, int | float)
                    else "An approach, not a visit."
                )
            elif entry.kind == "confirmed" and place:
                title = f"You confirmed visiting {place['name']}"
                evidence, detail = "commander_confirmed", payload.get("note") or ""
            elif entry.kind == "saved":
                title = f"Saved to your Chronicle: {payload.get('title')}"
                evidence, detail = "commander_confirmed", ""
            else:
                continue
            items.append(
                {
                    "at": _iso(entry.observed_at),
                    "type": entry.kind,
                    "evidence": evidence,
                    "title": title,
                    "detail": detail,
                    "subject": subject,
                    "replayed": bool(entry.replayed),
                }
            )
        for journey in journeys:
            for history in journey.get("history") or []:
                if history.get("type") not in {
                    "created",
                    "started",
                    "completed",
                    "reached",
                    "marked_complete",
                    "chapter_read",
                }:
                    continue
                stop = history.get("stop") or {}
                items.append(
                    {
                        "at": history.get("at"),
                        "type": "expedition",
                        "evidence": "observed"
                        if history.get("source") == "journal"
                        else "commander_confirmed",
                        "title": f"{journey['name']}: "
                        f"{str(history['type']).replace('_', ' ')}"
                        + (f" — {stop.get('name')}" if stop.get("name") else ""),
                        "detail": "",
                        "subject": {
                            "id": stop.get("place_id"),
                            "name": stop.get("name"),
                            "kind": None,
                        }
                        if stop.get("place_id")
                        else None,
                        "expedition": {"id": journey["id"], "name": journey["name"]},
                    }
                )
        items.sort(key=lambda item: str(item.get("at") or ""), reverse=True)
        return items[:TIMELINE_LIMIT]

    async def subject(self, entity_id: str, *, reveal: bool = False) -> JsonDict:
        """The Historian's reading of one Atlas subject, and the Commander's record."""
        knowledge = self._required_knowledge()
        if knowledge.entity(entity_id) is None:
            raise ChronicleNotFound(entity_id)
        profile = await self.profile()
        prefs = await self._intelligence.preferences_for(profile["profile_key"])
        spoilers = reveal or not prefs["spoiler_protection"]
        known = profile["commander_known"] and not profile["forgotten"]
        journeys = (
            await self._journeys(profile["profile_key"])
            if known
            else {"expeditions": [], "stops": []}
        )
        rows: list[ChronicleEntry] = []
        records: dict[str, JsonDict] = {}
        if known and self._session_factory is not None:
            async with self._session_factory() as db:
                rows = await self._rows(db, profile["profile_key"])
                records = await self._records(
                    db, profile["profile_key"], knowledge, rows, journeys["stops"]
                )
        place = knowledge.place(entity_id)
        current = self._current_system()
        saved = next(
            (
                entry.entry_id
                for entry in rows
                if entry.kind == "saved"
                and (_loads(entry.payload_json).get("target") or {})
                == {"type": "atlas", "id": entity_id}
            ),
            None,
        )
        return {
            "version": galactic_historian.VERSION,
            "profile": profile,
            "subject": galactic_historian.subject_view(
                knowledge, entity_id, spoilers=spoilers
            ),
            "connections": galactic_historian.connections(knowledge, entity_id),
            # Only a documented place can be planned: a person, an event or a
            # mystery never becomes a stop, whatever system it is tied to.
            "plannable": place is not None,
            "place": {
                key: place[key]
                for key in (
                    "id",
                    "name",
                    "kind",
                    "system",
                    "precision",
                    "reached_at",
                    "confirmable",
                    "identity",
                )
            }
            if place
            else None,
            "record": records.get(entity_id) if place else None,
            "next": galactic_historian.explore_next(
                knowledge,
                [entity_id],
                records=records,
                origin_pos=(current or {}).get("star_pos"),
            ),
            "stories": galactic_historian.stories_here(
                knowledge, [entity_id], spoilers=spoilers
            ),
            "in_expeditions": [
                {"expedition": stop["expedition"], "stop_id": stop["stop_id"]}
                for stop in journeys["stops"]
                if stop["place_id"] == entity_id
            ],
            "saved": saved,
            "spoilers_shown": spoilers,
        }

    async def context(self, *, reveal: bool = False) -> JsonDict:
        """The five Historian questions for where the Commander is now."""
        where = self._intelligence.context()
        profile = await self.profile()
        prefs = await self._intelligence.preferences_for(profile["profile_key"])
        spoilers = reveal or not prefs["spoiler_protection"]
        knowledge = self.knowledge()
        base: JsonDict = {
            "version": galactic_historian.VERSION,
            "profile": profile,
            "where": where,
            "spoilers_shown": spoilers,
            "here": [],
            "subject": None,
            "connections": None,
            "current_faction": None,
            "nearby": [],
            "next": [],
            "stories": [],
            "chapters": [],
            "caveat": CAVEAT,
        }
        if knowledge is None:
            return {**base, "state": "unavailable"}
        observation = commander_context.observation(where)
        if not observation:
            return {**base, "state": "no_location"}
        found = galactic_intelligence.documented_here(
            knowledge, observation, spoilers=spoilers
        )
        known = profile["commander_known"] and not profile["forgotten"]
        records: dict[str, JsonDict] = {}
        chapters: list[JsonDict] = []
        here_rows = [
            *found["station"],
            *(r for r in found["system"] if r["relation"] == "this_system"),
        ]
        nearby_rows = [r for r in found["system"] if r["relation"] == "in_system"]
        subject_ids = [r["entity"]["id"] for r in [*here_rows, *nearby_rows]]
        if known:
            records = await self.records_for(profile["profile_key"])
            if self._expeditions is not None and subject_ids:
                chapters = await self._expeditions.chapters_at(
                    profile["profile_key"], subject_ids
                )
        if not subject_ids:
            return {**base, "state": "nothing_documented"}
        primary = (here_rows or nearby_rows)[0]["entity"]["id"]

        def state(place_id: str) -> JsonDict | None:
            found_record = records.get(place_id)
            if found_record is None:
                return None
            return {
                key: found_record.get(key)
                for key in (
                    "class",
                    "label",
                    "note",
                    "first_at",
                    "last_at",
                    "count",
                    "count_is_minimum",
                    "visits",
                    "visits_is_minimum",
                )
            }

        return {
            **base,
            "state": "available",
            "here": [
                {
                    "entity": row["entity"],
                    "relation": row["relation"],
                    "reason": row["reason"],
                    "match": row["match"],
                    "record": state(row["entity"]["id"]),
                }
                for row in here_rows
            ],
            "subject": galactic_historian.subject_view(
                knowledge, primary, spoilers=spoilers
            ),
            "connections": galactic_historian.connections(knowledge, primary),
            "current_faction": self._current_faction(where),
            "nearby": [
                {
                    "entity": row["entity"],
                    "summary": row["summary"],
                    "significance": row["significance"],
                    "reason": row["reason"],
                    "match": row["match"],
                    "record": state(row["entity"]["id"]),
                }
                for row in nearby_rows
            ],
            "next": galactic_historian.explore_next(
                knowledge,
                subject_ids,
                records=records,
                origin_pos=where["system"].get("star_pos"),
                exclude=set(subject_ids),
            ),
            "stories": galactic_historian.stories_here(
                knowledge, subject_ids, spoilers=spoilers
            ),
            "chapters": chapters,
        }

    def _current_faction(self, where: JsonDict) -> JsonDict | None:
        """The controlling faction the Journal last reported here, labelled so."""
        snapshot = self._state.snapshot
        station = where.get("station") or {}
        if station.get("state") != "unknown" and station.get("docked"):
            port = snapshot.local_station_context
            raw = getattr(port, "station_faction", None) if port else None
            scope, observed = "station", station.get("observed_at")
        else:
            system = snapshot.local_system_context
            raw = getattr(system, "system_faction", None) if system else None
            scope, observed = "system", (where.get("system") or {}).get("observed_at")
        name = raw.get("Name") if isinstance(raw, dict) else None
        if not isinstance(name, str) or not name.strip():
            return None
        return {
            "name": name.strip()[:TEXT_MAX],
            "scope": scope,
            "source": "journal",
            "observed_at": observed,
        }

    # The Commander's own word --------------------------------------------------

    async def confirm(self, place_id: str, note: Any = None) -> JsonDict:
        """Record that the Commander says they visited a documented place."""
        profile = await self._writable()
        knowledge = self._required_knowledge()
        place = knowledge.place(place_id)
        if place is None:
            raise ChronicleNotFound(place_id)
        if note is not None and not isinstance(note, str):
            raise ValueError("note must be text")
        text = _text(note, NOTE_MAX) if note else None
        key = _digest(profile, "confirmed", place_id)
        now = _naive(self._clock())
        payload = _dumps({"note": text, "commander_reported": True})
        async with self._lock, self._factory()() as db:
            row = await db.scalar(
                select(ChronicleEntry).where(
                    ChronicleEntry.profile_key == profile,
                    ChronicleEntry.fingerprint == key,
                )
            )
            if row is None:
                count = await db.scalar(
                    select(func.count())
                    .select_from(ChronicleEntry)
                    .where(
                        ChronicleEntry.profile_key == profile,
                        ChronicleEntry.kind == "confirmed",
                    )
                )
                if int(count or 0) >= MAX_CONFIRMED:
                    raise ChronicleConflict(
                        "The Chronicle holds the most visits it can."
                    )
                db.add(
                    ChronicleEntry(
                        entry_id=uuid4().hex,
                        profile_key=profile,
                        kind="confirmed",
                        evidence="commander",
                        subject_id=place_id,
                        fingerprint=key,
                        observed_at=now,
                        created_at=now,
                        source_event=None,
                        replayed=False,
                        payload_json=payload,
                    )
                )
            else:
                row.payload_json = payload
            await db.commit()
        await self._push(
            RECORDED_EVENT, {"kinds": ["confirmed"], "subjects": [place_id]}
        )
        return {
            "place_id": place_id,
            "record": (await self.records_for(profile))[place_id],
        }

    async def unconfirm(self, place_id: str) -> JsonDict:
        """Withdraw the Commander's own confirmation; Journal evidence stays."""
        profile = await self._writable()
        knowledge = self._required_knowledge()
        if knowledge.place(place_id) is None:
            raise ChronicleNotFound(place_id)
        async with self._lock, self._factory()() as db:
            result = await db.execute(
                delete(ChronicleEntry).where(
                    ChronicleEntry.profile_key == profile,
                    ChronicleEntry.fingerprint
                    == _digest(profile, "confirmed", place_id),
                )
            )
            await db.commit()
        if not getattr(result, "rowcount", 0):
            raise ChronicleNotFound(place_id)
        await self._push(
            RECORDED_EVENT, {"kinds": ["confirmed"], "subjects": [place_id]}
        )
        return {
            "place_id": place_id,
            "record": (await self.records_for(profile))[place_id],
        }

    async def save(self, payload: JsonDict) -> JsonDict:
        """Save an Atlas entry, a story or one chapter to the Chronicle."""
        profile = await self._writable()
        knowledge = self._required_knowledge()
        if not isinstance(payload, dict):
            raise ValueError("A saved story must be an object")
        kind = payload.get("type")
        if kind not in SAVE_TYPES:
            raise ValueError(f"type must be one of {', '.join(SAVE_TYPES)}")
        target_id = payload.get("id")
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("id must be text")
        chapter = payload.get("chapter") if kind == "chapter" else None
        target = {"type": kind, "id": target_id}
        if chapter is not None:
            target["chapter"] = chapter
        found = _saved_target(knowledge, target)
        if not found:
            raise ChronicleNotFound(target_id)
        key = _digest(profile, "saved", kind, target_id, chapter or "-")
        now = _naive(self._clock())
        async with self._lock, self._factory()() as db:
            row = await db.scalar(
                select(ChronicleEntry).where(
                    ChronicleEntry.profile_key == profile,
                    ChronicleEntry.fingerprint == key,
                )
            )
            if row is None:
                count = await db.scalar(
                    select(func.count())
                    .select_from(ChronicleEntry)
                    .where(
                        ChronicleEntry.profile_key == profile,
                        ChronicleEntry.kind == "saved",
                    )
                )
                if int(count or 0) >= MAX_SAVED:
                    raise ChronicleConflict(
                        "The Chronicle holds the most saved stories it can."
                    )
                row = ChronicleEntry(
                    entry_id=uuid4().hex,
                    profile_key=profile,
                    kind="saved",
                    evidence="commander",
                    subject_id=target_id if kind == "atlas" else None,
                    fingerprint=key,
                    observed_at=now,
                    created_at=now,
                    source_event=None,
                    replayed=False,
                    payload_json=_dumps({"target": target, **found}),
                )
                db.add(row)
                await db.commit()
            entry_id = row.entry_id
        await self._push(RECORDED_EVENT, {"kinds": ["saved"], "subjects": [target_id]})
        return {"entry_id": entry_id, "target": target, **found}

    async def unsave(self, entry_id: str) -> None:
        profile = await self._writable()
        async with self._lock, self._factory()() as db:
            result = await db.execute(
                delete(ChronicleEntry).where(
                    ChronicleEntry.profile_key == profile,
                    ChronicleEntry.entry_id == entry_id,
                    ChronicleEntry.kind == "saved",
                )
            )
            await db.commit()
        if not getattr(result, "rowcount", 0):
            raise ChronicleNotFound(entry_id)
        await self._push(RECORDED_EVENT, {"kinds": ["saved"], "subjects": []})

    # Commander lifecycle -----------------------------------------------------

    async def purge_profile(self, db: AsyncSession, profile_key: str) -> None:
        """Forget-workflow purge, inside Commander Memory's forget transaction."""
        await db.execute(
            delete(ChronicleEntry).where(ChronicleEntry.profile_key == profile_key)
        )

    async def after_forget(self, profile_key: str) -> None:
        """After the forget commits: diagnostics, and any Chronicle on screen."""
        self.decisions = deque(
            (d for d in self.decisions if d.get("profile_key") != profile_key),
            maxlen=RECENT_DECISIONS,
        )
        await self._push(CLEARED_EVENT, {"reason": "commander_forgotten"})


def _saved_target(knowledge: KnowledgeIndex, target: JsonDict) -> JsonDict | None:
    """Title and kind of a saved story's target, or None if it no longer exists."""
    kind, target_id = target.get("type"), target.get("id")
    if kind == "atlas":
        if target_id not in {row["id"] for row in knowledge.atlas()}:
            return None
        brief = knowledge.brief(str(target_id))
        return {"title": brief["name"], "kind": brief["kind"]}
    try:
        narrative = knowledge.narrative(str(target_id))
    except KeyError:
        return None
    if kind == "narrative":
        return {"title": narrative["title"], "kind": "narrative"}
    chapter = next(
        (c for c in narrative["chapters"] if c["id"] == target.get("chapter")), None
    )
    if chapter is None:
        return None
    return {"title": f"{narrative['title']}: {chapter['title']}", "kind": "chapter"}


def register(
    register_handler: Callable[[str, EventHandler], None],
    service: ChronicleService,
) -> None:
    """Attach the service to the existing dispatcher, after the state handlers.

    Registered after Galactic Intelligence, so a briefing reads the Chronicle as it
    was before the event it describes.
    """

    async def observe(event: JsonDict) -> None:
        await service.observe(event)

    for name in OBSERVED_EVENTS:
        register_handler(name, observe)
