"""Galactic Expeditions service: persistence, Journal progress and lifecycle (GKI-06).

Owns no Journal reader: the dispatcher hands it each event after the state
handlers and Galactic Intelligence (see :func:`register`).  Preferences, the
active commander and the forgotten check are Galactic Intelligence's (GKI-04).

Progress rules, each refusal a recorded ``reason`` in :attr:`decisions`:

* Only an **active** expedition of the **active commander** records progress,
  never one Commander Memory forgot (``commander_unknown`` /
  ``commander_forgotten``), and only from events at or after the expedition
  became active and the stop was planned: an expedition never claims a visit from
  before it existed.
* A **replayed** event (the watcher's startup catch-up, an event older than one
  already processed, or one outside :data:`REPLAY_WINDOW_SECONDS` of the clock)
  still records evidence, marked ``replayed``, so travel while OmniCOVAS was closed
  is not lost.  It never creates a narrative opportunity.
* The same Journal event is applied once (``duplicate_event``), and evidence only
  deepens.  What evidence means is :func:`expeditions.stop_evidence`'s.

Narrative opportunities (``narrative-opportunity-v1``) are kept in a small
in-memory list for the expedition workspace and the future Notification Director.
Nothing here pushes, pops up or speaks.
"""

from __future__ import annotations

import asyncio
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
from omnicovas.db.models import Expedition, ExpeditionStop
from omnicovas.features import (
    commander_context,
    expeditions,
    galactic_intelligence,
    galactic_knowledge,
    navigation,
    readiness,
)
from omnicovas.features.galactic_intelligence import GalacticIntelligence
from omnicovas.features.galactic_knowledge import KnowledgeIndex

logger = logging.getLogger(__name__)

JsonDict = dict[str, Any]
Notify = Callable[[JsonDict], Awaitable[None]]

# Pushed when a commander's expeditions are erased, so open UIs drop them.
CLEARED_EVENT = "EXPEDITIONS_CLEARED"
DEFAULT_PROFILE_KEY = galactic_intelligence.DEFAULT_PROFILE_KEY
REPLAY_WINDOW_SECONDS = galactic_intelligence.REPLAY_WINDOW_SECONDS
OPEN_STATUSES = ("planning", "active")
MAX_EXPEDITIONS = 50
MAX_OPPORTUNITIES = 50
OFFERED_LIMIT = 200
SEEN_EVENTS = 512
RECENT_DECISIONS = 25
JUMP_EVENTS = frozenset({"FSDJump", "CarrierJump"})
TRANSITIONS = {
    "planning": {"active", "archived"},
    "active": {"planning", "completed", "archived"},
    "completed": {"active", "archived"},
    "archived": {"planning", "active"},
}


class ExpeditionError(Exception):
    """Base for refusals the API maps to HTTP errors."""


class ExpeditionNotFound(ExpeditionError):
    """No such expedition or stop for this commander (404)."""


class ExpeditionConflict(ExpeditionError):
    """Refused in the current state (409): a forgotten commander, a limit."""


def _now_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _whole_second(value: datetime) -> datetime:
    return value.replace(microsecond=0)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return commander_context.iso(value.replace(tzinfo=timezone.utc))


def _loads(raw: str | None, fallback: Any) -> Any:
    try:
        return json.loads(raw) if raw else fallback
    except ValueError:
        return fallback


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _row(stop: ExpeditionStop) -> JsonDict:
    return {
        "stop_id": stop.stop_id,
        "position": stop.position,
        "place_id": stop.place_id,
        "system_name": stop.system_name,
        "system_address": stop.system_address,
        "purposes": _loads(stop.purposes_json, []),
        "manual_state": stop.manual_state,
        "manual_at": _iso(stop.manual_at),
        "note": stop.note,
        "evidence": _loads(stop.evidence_json, {}),
        "created_at": _iso(stop.created_at),
    }


class ExpeditionService:
    """Expeditions for the active commander, their progress and their stories."""

    def __init__(
        self,
        state: StateManager,
        session_factory: async_sessionmaker[AsyncSession] | None,
        intelligence: GalacticIntelligence,
        *,
        profile_provider: Callable[[], str | None] | None = None,
        notify: Notify | None = None,
        knowledge_provider: Callable[[], KnowledgeIndex] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state = state
        self._session_factory = session_factory
        self._intelligence = intelligence
        self._profile_provider = profile_provider or (lambda: None)
        self._notify = notify
        self._knowledge_provider = knowledge_provider or galactic_knowledge.index
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = asyncio.Lock()
        self._seen_events: deque[str] = deque(maxlen=SEEN_EVENTS)
        self._latest_at: datetime | None = None
        # Last observed Rank per commander: a permit hint, never a permit.
        self._ranks: dict[str, JsonDict] = {}
        self._opportunities: deque[JsonDict] = deque(maxlen=MAX_OPPORTUNITIES)
        self._dismissed: set[str] = set()
        self.decisions: deque[JsonDict] = deque(maxlen=RECENT_DECISIONS)

    # Commander ---------------------------------------------------------------

    def profile_key(self) -> str:
        return self._profile_provider() or DEFAULT_PROFILE_KEY

    async def profile(self) -> JsonDict:
        key = self.profile_key()
        return {
            "profile_key": key,
            "commander_known": self._profile_provider() is not None,
            "forgotten": await self._intelligence.is_forgotten(key),
        }

    async def _writable(self) -> str:
        key = self.profile_key()
        if await self._intelligence.is_forgotten(key):
            raise ExpeditionConflict(
                "This commander was forgotten in Commander Memory; expeditions "
                "are not kept for them."
            )
        return key

    def knowledge(self) -> KnowledgeIndex | None:
        if galactic_knowledge.catalog()["state"] != "available":
            return None
        return self._knowledge_provider()

    def _factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            raise ExpeditionConflict("Expedition persistence is not initialized")
        return self._session_factory

    async def _mode(self, profile: str) -> JsonDict:
        prefs = await self._intelligence.preferences_for(profile)
        return expeditions.storytelling_mode(prefs)

    async def storytelling(self) -> JsonDict:
        """The current commander's storytelling mode (from GKI-04 preferences)."""
        return await self._mode(self.profile_key())

    def _origin(self, knowledge: KnowledgeIndex | None) -> JsonDict | None:
        return expeditions.origin_from(self._state.public_snapshot(), knowledge)

    async def _acquisition(self) -> dict[str, JsonDict] | None:
        """GKI-05 acquisition intelligence for every active-build scope.

        The full portfolio, as the Engineering workspace computes it: acquisition
        intelligence rests on its reservations and Material Trader plan, which the
        lighter ``include_workbenches=False`` form does not build.
        """
        if self._session_factory is None:
            return None
        from omnicovas.features import engineering, engineering_progression

        factory = self._session_factory
        progression = await engineering_progression.portfolio(
            factory,
            await engineering.list_build_plans(factory),
            await engineering.list_goals(factory),
            self._state.public_snapshot(),
        )
        found = progression.get("acquisition_intelligence")
        return found if isinstance(found, dict) else None

    # Reading -----------------------------------------------------------------

    async def _get(self, db: AsyncSession, expedition_id: str) -> Expedition:
        row = await db.get(Expedition, expedition_id)
        if row is None or row.profile_key != self.profile_key():
            raise ExpeditionNotFound(expedition_id)
        return row

    @staticmethod
    async def _stops(db: AsyncSession, expedition_id: str) -> list[ExpeditionStop]:
        rows = await db.scalars(
            select(ExpeditionStop)
            .where(ExpeditionStop.expedition_id == expedition_id)
            .order_by(ExpeditionStop.position)
        )
        return list(rows)

    def _narratives(
        self,
        knowledge: KnowledgeIndex | None,
        expedition: Expedition,
        rows: list[JsonDict],
    ) -> dict[str, JsonDict]:
        if knowledge is None:
            return {}
        wanted = {expedition.narrative_id} if expedition.narrative_id else set()
        for row in rows:
            wanted |= {p["narrative"] for p in row["purposes"] if p.get("narrative")}
        found = {}
        for narrative_id in sorted(wanted):
            try:
                found[narrative_id] = knowledge.narrative(narrative_id)
            except KeyError:
                continue
        return found

    def _describe(
        self,
        knowledge: KnowledgeIndex | None,
        expedition: Expedition,
        stops: list[ExpeditionStop],
    ) -> tuple[list[JsonDict], dict[str, JsonDict]]:
        rows = [_row(stop) for stop in stops]
        narratives = self._narratives(knowledge, expedition, rows)
        themes = {t["id"]: t for t in knowledge.themes()} if knowledge else {}
        return [
            expeditions.describe_stop(
                knowledge, row, narratives=narratives, themes=themes
            )
            for row in rows
        ], narratives

    @staticmethod
    def _brief(expedition: Expedition, described: list[JsonDict]) -> JsonDict:
        following = next(
            (
                s
                for s in described
                if s["status"] in {"planned", "in_system", "approached"}
            ),
            None,
        )
        return {
            "id": expedition.expedition_id,
            "name": expedition.name,
            "entry": expedition.entry,
            "status": expedition.status,
            "theme_id": expedition.theme_id,
            "narrative_id": expedition.narrative_id,
            "goal_scope": expedition.goal_scope,
            "stops": len(described),
            "done": sum(
                1 for s in described if s["status"] in {"reached", "completed"}
            ),
            "next": {"stop_id": following["stop_id"], "name": following["name"]}
            if following
            else None,
            "created_at": _iso(expedition.created_at),
            "updated_at": _iso(expedition.updated_at),
            "started_at": _iso(expedition.started_at),
            "completed_at": _iso(expedition.completed_at),
        }

    async def list_all(self) -> JsonDict:
        profile = await self.profile()
        knowledge = self.knowledge()
        rows: list[JsonDict] = []
        unassigned = 0
        if self._session_factory is not None:
            async with self._session_factory() as db:
                found = await db.scalars(
                    select(Expedition)
                    .where(Expedition.profile_key == profile["profile_key"])
                    .order_by(Expedition.updated_at.desc())
                )
                for expedition in found:
                    stops = await self._stops(db, expedition.expedition_id)
                    described, _ = self._describe(knowledge, expedition, stops)
                    rows.append(self._brief(expedition, described))
                if profile["commander_known"] and not profile["forgotten"]:
                    unassigned = int(
                        await db.scalar(
                            select(func.count())
                            .select_from(Expedition)
                            .where(Expedition.profile_key == DEFAULT_PROFILE_KEY)
                        )
                        or 0
                    )
        return {
            "version": expeditions.VERSION,
            "profile": profile,
            "expeditions": [] if profile["forgotten"] else rows,
            "unassigned": unassigned,
            "knowledge": galactic_knowledge.catalog()["state"],
        }

    async def detail(self, expedition_id: str) -> JsonDict:
        factory = self._factory()
        knowledge = self.knowledge()
        async with factory() as db:
            expedition = await self._get(db, expedition_id)
            stops = await self._stops(db, expedition_id)
            described, narratives = self._describe(knowledge, expedition, stops)
            story_data = _loads(expedition.story_json, {})
            history = _loads(expedition.history_json, [])
        profile = self.profile_key()
        prefs = await self._intelligence.preferences_for(profile)
        mode = expeditions.storytelling_mode(prefs)
        spoilers = not prefs["spoiler_protection"]
        if any(p["type"] == "acquisition" for s in described for p in s["purposes"]):
            intelligence = await self._acquisition()
            for stop in described:
                for purpose in stop["purposes"]:
                    if purpose["type"] == "acquisition":
                        scope = (intelligence or {}).get(purpose.get("scope") or "all")
                        purpose["relevance"] = expeditions.acquisition_relevance(
                            purpose, scope or (intelligence or {}).get("all")
                        )
                        if intelligence is not None and scope is None:
                            purpose["relevance"]["note"] = (
                                "The build this stop was planned for is no longer "
                                "active; checked against all active builds."
                            )
        origin = self._origin(knowledge)
        narrative = narratives.get(expedition.narrative_id or "")
        story = (
            expeditions.story_state(
                narrative,
                described,
                self._read(story_data, narrative["id"]),
                spoilers=spoilers,
            )
            if narrative
            else None
        )
        snapshot = self._state.public_snapshot()
        ship = expeditions.ship_checks(snapshot, readiness.role_fit(self._state))
        spatial = expeditions.spatial(described, origin)
        following = spatial["next"]
        return {
            "version": expeditions.VERSION,
            "expedition": {
                **self._brief(expedition, described),
                "theme": next(
                    (
                        t
                        for t in (knowledge.themes() if knowledge else [])
                        if t["id"] == expedition.theme_id
                    ),
                    None,
                ),
            },
            "stops": described,
            "spatial": spatial,
            "orders": {
                "shortest": expeditions.suggest_order(described, origin),
                "story": expeditions.story_order(described, narrative),
            },
            "preflight": expeditions.preflight(
                knowledge, described, ship, self._ranks.get(profile)
            ),
            "story": story,
            "storytelling": mode,
            "opportunities": [
                o
                for o in self.opportunities()
                if o["expedition"]["id"] == expedition_id
            ],
            "next_leg": self._next_leg(origin, following),
            "history": history[-20:],
        }

    @staticmethod
    def _next_leg(
        origin: JsonDict | None, following: JsonDict | None
    ) -> JsonDict | None:
        """The Spansh plotter link for the next leg, unless you are already there."""
        if following is None:
            return None
        here = (origin or {}).get("system")
        same = (
            bool(here) and str(here).casefold() == str(following["system"]).casefold()
        )
        return {
            "from": here,
            "to": following["system"],
            "same_system": same,
            "spansh_url": None
            if same
            else navigation.build_spansh_url(here, following["system"]),
        }

    @staticmethod
    def _read(story: JsonDict, narrative_id: str) -> list[str]:
        prefix = f"{narrative_id}/"
        return [
            key[len(prefix) :]
            for key in story.get("read", [])
            if key.startswith(prefix)
        ]

    # Writing -----------------------------------------------------------------

    def _validate_purposes(
        self, knowledge: KnowledgeIndex | None, place_id: str | None, raw: Any
    ) -> list[JsonDict]:
        purposes = [expeditions.normalize_purpose(p) for p in (raw or [])]
        for purpose in purposes:
            if purpose["type"] not in {"story", "discovery"}:
                continue
            if knowledge is None:
                raise ValueError("stories need the bundled galactic knowledge")
            try:
                narrative = knowledge.narrative(purpose["narrative"])
            except KeyError as exc:
                raise ValueError(f"unknown narrative {purpose['narrative']}") from exc
            items = (
                [c for c in narrative["chapters"] if c["id"] == purpose["chapter"]]
                if purpose["type"] == "story"
                else narrative["discoveries"]
            )
            if not any(item["place"] == place_id for item in items):
                raise ValueError(
                    "a story purpose must be the place its chapter or discovery is set"
                )
        return purposes or [{"type": "custom"}]

    async def create(self, payload: JsonDict) -> JsonDict:
        profile = await self._writable()
        factory = self._factory()
        knowledge = self.knowledge()
        entry = payload.get("entry") or "custom"
        if entry not in expeditions.ENTRY_POINTS:
            raise ValueError(
                f"entry must be one of {', '.join(expeditions.ENTRY_POINTS)}"
            )
        theme_id = payload.get("theme_id")
        themes = {t["id"]: t for t in knowledge.themes()} if knowledge else {}
        if theme_id is not None and theme_id not in themes:
            raise ValueError(f"unknown theme {theme_id}")
        narrative_id = payload.get("narrative_id")
        narrative = None
        if narrative_id is not None:
            if knowledge is None:
                raise ValueError("stories need the bundled galactic knowledge")
            try:
                narrative = knowledge.narrative(str(narrative_id))
            except KeyError as exc:
                raise ValueError(f"unknown narrative {narrative_id}") from exc
        seeds: list[JsonDict] = []
        if narrative is not None:
            seeds += [
                {
                    "place_id": chapter["place"],
                    "purposes": [
                        {
                            "type": "story",
                            "narrative": narrative["id"],
                            "chapter": chapter["id"],
                        }
                    ],
                }
                for chapter in narrative["chapters"]
            ]
        if payload.get("place_id") or payload.get("system"):
            seeds.insert(
                0,
                {
                    "place_id": payload.get("place_id"),
                    "system": payload.get("system"),
                    "purposes": [{"type": "destination"}],
                },
            )
        seeds += [s for s in payload.get("stops") or [] if isinstance(s, dict)]
        name = payload.get("name")
        if name is None:
            first = seeds[0] if seeds else {}
            first_name = None
            if first.get("place_id") and knowledge is not None:
                first_name = (knowledge.place(first["place_id"]) or {}).get("name")
            journey = (
                f"Journey to {first_name or first.get('system')}" if first else None
            )
            # A destination names the trip; a story or theme names the rest.
            name = (
                (narrative or {}).get("title")
                or (journey if entry == "destination" else None)
                or (themes.get(theme_id or "") or {}).get("label")
                or journey
                or ("Materials run" if entry == "goal" else "New expedition")
            )
        name = expeditions.clean_text(name, "name", expeditions.NAME_MAX)
        now = self._clock()
        stamp = _now_naive(now)
        async with self._lock, factory() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(Expedition)
                .where(Expedition.profile_key == profile)
            )
            if int(count or 0) >= MAX_EXPEDITIONS:
                raise ExpeditionConflict(
                    f"A commander keeps at most {MAX_EXPEDITIONS} expeditions; "
                    "delete or archive one first."
                )
            expedition = Expedition(
                expedition_id=uuid4().hex,
                profile_key=profile,
                name=name,
                entry=entry,
                theme_id=theme_id,
                narrative_id=narrative["id"] if narrative else None,
                goal_scope=str(payload["goal_scope"])[:64]
                if payload.get("goal_scope")
                else None,
                status="planning",
                story_json=_dumps({"read": [], "offered": [], "continued": []}),
                history_json=_dumps(
                    [
                        expeditions.history_entry(
                            "created",
                            now,
                            entry=entry,
                            theme=theme_id,
                            narrative=narrative["id"] if narrative else None,
                        )
                    ]
                ),
                created_at=stamp,
                updated_at=stamp,
                started_at=None,
                completed_at=None,
            )
            db.add(expedition)
            await db.flush()
            for seed in seeds:
                await self._add(db, knowledge, expedition, seed, now, record=False)
            await db.commit()
            expedition_id = expedition.expedition_id
        return await self.detail(expedition_id)

    async def _add(
        self,
        db: AsyncSession,
        knowledge: KnowledgeIndex | None,
        expedition: Expedition,
        payload: JsonDict,
        now: datetime,
        *,
        record: bool = True,
    ) -> JsonDict:
        """Add one stop, or merge its purposes into the stop already there."""
        try:
            target = expeditions.resolve_target(
                knowledge,
                place_id=payload.get("place_id"),
                system=payload.get("system"),
            )
        except KeyError as exc:
            raise ValueError(f"unknown place {exc.args[0]}") from exc
        purposes = self._validate_purposes(
            knowledge, target["place_id"], payload.get("purposes")
        )
        key = expeditions.stop_key(
            target["place_id"], target["system_address"], target["system_name"]
        )
        stops = await self._stops(db, expedition.expedition_id)
        stamp = _now_naive(now)
        existing = next((s for s in stops if s.stop_key == key), None)
        if existing is not None:
            merged = expeditions.merge_purposes(
                _loads(existing.purposes_json, []), purposes
            )
            existing.purposes_json = _dumps(
                [p for p in merged if p["type"] != "custom"] or merged
            )
            existing.updated_at = stamp
            return {"stop_id": existing.stop_id, "merged": True}
        if len(stops) >= expeditions.MAX_STOPS:
            raise ExpeditionConflict(
                f"An expedition keeps at most {expeditions.MAX_STOPS} stops."
            )
        position = payload.get("position")
        if not isinstance(position, int) or not 0 <= position <= len(stops):
            position = len(stops)
        for stop in stops[position:]:
            stop.position += 1
        note = payload.get("note")
        stop = ExpeditionStop(
            stop_id=uuid4().hex,
            expedition_id=expedition.expedition_id,
            profile_key=expedition.profile_key,
            stop_key=key,
            position=position,
            place_id=target["place_id"],
            system_name=target["system_name"],
            system_address=target["system_address"],
            purposes_json=_dumps(purposes),
            manual_state="planned",
            manual_at=None,
            note=expeditions.clean_text(note, "note", expeditions.NOTE_MAX)
            if note
            else None,
            evidence_json="{}",
            created_at=stamp,
            updated_at=stamp,
        )
        db.add(stop)
        if record:
            self._append_history(
                expedition,
                expeditions.history_entry(
                    "stop_added",
                    now,
                    stop={**_row(stop), "name": self._name(knowledge, stop)},
                ),
            )
        expedition.updated_at = stamp
        await db.flush()
        return {"stop_id": stop.stop_id, "merged": False}

    @staticmethod
    def _name(knowledge: KnowledgeIndex | None, stop: ExpeditionStop) -> str:
        if stop.place_id and knowledge is not None:
            place = knowledge.place(stop.place_id)
            if place is not None:
                return str(place["name"])
        return stop.system_name or stop.place_id or "Unknown"

    @staticmethod
    def _append_history(expedition: Expedition, *entries: JsonDict) -> None:
        history = _loads(expedition.history_json, [])
        history.extend(entries)
        expedition.history_json = _dumps(history[-expeditions.HISTORY_LIMIT :])

    async def update(self, expedition_id: str, changes: JsonDict) -> JsonDict:
        await self._writable()
        knowledge = self.knowledge()
        now = self._clock()
        stamp = _now_naive(now)
        async with self._lock, self._factory()() as db:
            expedition = await self._get(db, expedition_id)
            if "name" in changes:
                expedition.name = expeditions.clean_text(
                    changes["name"], "name", expeditions.NAME_MAX
                )
            if "theme_id" in changes:
                theme_id = changes["theme_id"]
                if theme_id is not None and (
                    knowledge is None
                    or theme_id not in {t["id"] for t in knowledge.themes()}
                ):
                    raise ValueError(f"unknown theme {theme_id}")
                expedition.theme_id = theme_id
            if "narrative_id" in changes:
                narrative_id = changes["narrative_id"]
                if narrative_id is not None:
                    if knowledge is None:
                        raise ValueError("stories need the bundled galactic knowledge")
                    try:
                        knowledge.narrative(str(narrative_id))
                    except KeyError as exc:
                        raise ValueError(f"unknown narrative {narrative_id}") from exc
                expedition.narrative_id = narrative_id
            status = changes.get("status")
            if status is not None and status != expedition.status:
                if status not in TRANSITIONS.get(expedition.status, set()):
                    raise ValueError(
                        f"an expedition cannot go from {expedition.status} to {status}"
                    )
                kind = {
                    "active": "started" if expedition.started_at is None else "resumed",
                    "planning": "paused",
                    "completed": "completed",
                    "archived": "archived",
                }[status]
                expedition.status = status
                if status == "active":
                    # Progress counts from here: travel before this is not the trip.
                    expedition.started_at = stamp
                # A reopened expedition is no longer complete.
                expedition.completed_at = stamp if status == "completed" else None
                self._append_history(expedition, expeditions.history_entry(kind, now))
            expedition.updated_at = stamp
            await db.commit()
        return await self.detail(expedition_id)

    async def delete(self, expedition_id: str) -> None:
        await self._writable()
        async with self._lock, self._factory()() as db:
            await self._get(db, expedition_id)
            await db.execute(
                delete(ExpeditionStop).where(
                    ExpeditionStop.expedition_id == expedition_id
                )
            )
            await db.execute(
                delete(Expedition).where(Expedition.expedition_id == expedition_id)
            )
            await db.commit()
        self._opportunities = deque(
            (o for o in self._opportunities if o["expedition"]["id"] != expedition_id),
            maxlen=MAX_OPPORTUNITIES,
        )

    async def add_stop(self, expedition_id: str, payload: JsonDict) -> JsonDict:
        await self._writable()
        knowledge = self.knowledge()
        now = self._clock()
        async with self._lock, self._factory()() as db:
            expedition = await self._get(db, expedition_id)
            added = await self._add(db, knowledge, expedition, payload, now)
            await db.commit()
        return {**added, "expedition": await self.detail(expedition_id)}

    async def update_stop(
        self, expedition_id: str, stop_id: str, changes: JsonDict
    ) -> JsonDict:
        await self._writable()
        knowledge = self.knowledge()
        now = self._clock()
        stamp = _now_naive(now)
        async with self._lock, self._factory()() as db:
            expedition = await self._get(db, expedition_id)
            stop = await db.get(ExpeditionStop, stop_id)
            if stop is None or stop.expedition_id != expedition_id:
                raise ExpeditionNotFound(stop_id)
            if "manual_state" in changes:
                state = changes["manual_state"]
                if state not in expeditions.MANUAL_STATES:
                    raise ValueError(
                        "manual_state must be one of "
                        + ", ".join(expeditions.MANUAL_STATES)
                    )
                if state != stop.manual_state:
                    stop.manual_state = state
                    stop.manual_at = stamp if state != "planned" else None
                    self._append_history(
                        expedition,
                        expeditions.history_entry(
                            {
                                "completed": "marked_complete",
                                "skipped": "skipped",
                                "planned": "replanned",
                            }[state],
                            now,
                            stop={**_row(stop), "name": self._name(knowledge, stop)},
                        ),
                    )
            if "note" in changes:
                note = changes["note"]
                stop.note = (
                    expeditions.clean_text(note, "note", expeditions.NOTE_MAX)
                    if note
                    else None
                )
            stop.updated_at = stamp
            expedition.updated_at = stamp
            await db.commit()
        return await self.detail(expedition_id)

    async def remove_stop(self, expedition_id: str, stop_id: str) -> JsonDict:
        """Remove one stop: only ever on the Commander's request."""
        await self._writable()
        knowledge = self.knowledge()
        now = self._clock()
        async with self._lock, self._factory()() as db:
            expedition = await self._get(db, expedition_id)
            stop = await db.get(ExpeditionStop, stop_id)
            if stop is None or stop.expedition_id != expedition_id:
                raise ExpeditionNotFound(stop_id)
            self._append_history(
                expedition,
                expeditions.history_entry(
                    "stop_removed",
                    now,
                    stop={**_row(stop), "name": self._name(knowledge, stop)},
                ),
            )
            await db.delete(stop)
            await db.flush()
            for position, row in enumerate(await self._stops(db, expedition_id)):
                row.position = position
            expedition.updated_at = _now_naive(now)
            await db.commit()
        return await self.detail(expedition_id)

    async def reorder(self, expedition_id: str, payload: JsonDict) -> JsonDict:
        """Apply the Commander's order, or a suggested order they chose."""
        await self._writable()
        knowledge = self.knowledge()
        now = self._clock()
        async with self._lock, self._factory()() as db:
            expedition = await self._get(db, expedition_id)
            stops = await self._stops(db, expedition_id)
            ids = payload.get("stop_ids")
            apply = payload.get("apply")
            if apply is not None:
                described, narratives = self._describe(knowledge, expedition, stops)
                if apply == "shortest":
                    ids = expeditions.suggest_order(described, self._origin(knowledge))[
                        "stop_ids"
                    ]
                elif apply == "story":
                    order = expeditions.story_order(
                        described, narratives.get(expedition.narrative_id or "")
                    )
                    if order is None:
                        raise ValueError("this expedition follows no story")
                    ids = order["stop_ids"]
                else:
                    raise ValueError("apply must be shortest or story")
            if not isinstance(ids, list) or sorted(ids) != sorted(
                s.stop_id for s in stops
            ):
                raise ValueError("stop_ids must list every stop exactly once")
            by_id = {s.stop_id: s for s in stops}
            for position, stop_id in enumerate(ids):
                by_id[stop_id].position = position
            self._append_history(
                expedition,
                expeditions.history_entry("reordered", now, order=apply or "manual"),
            )
            expedition.updated_at = _now_naive(now)
            await db.commit()
        return await self.detail(expedition_id)

    async def mark_chapter(
        self, expedition_id: str, narrative_id: str, chapter_id: str, *, read: bool
    ) -> JsonDict:
        await self._writable()
        knowledge = self.knowledge()
        if knowledge is None:
            raise ValueError("stories need the bundled galactic knowledge")
        try:
            narrative = knowledge.narrative(narrative_id)
        except KeyError as exc:
            raise ExpeditionNotFound(narrative_id) from exc
        if chapter_id not in {c["id"] for c in narrative["chapters"]}:
            raise ExpeditionNotFound(chapter_id)
        now = self._clock()
        async with self._lock, self._factory()() as db:
            expedition = await self._get(db, expedition_id)
            story = _loads(expedition.story_json, {})
            keys = list(story.get("read", []))
            key = f"{narrative_id}/{chapter_id}"
            if read and key not in keys:
                keys.append(key)
                self._append_history(
                    expedition,
                    expeditions.history_entry(
                        "chapter_read", now, narrative=narrative_id, chapter=chapter_id
                    ),
                )
            elif not read and key in keys:
                keys.remove(key)
            story["read"] = keys
            expedition.story_json = _dumps(story)
            expedition.updated_at = _now_naive(now)
            await db.commit()
        return await self.detail(expedition_id)

    async def claim(self, expedition_id: str) -> JsonDict:
        """Move an expedition planned before any commander was known to this one."""
        profile = await self._writable()
        if self._profile_provider() is None:
            raise ExpeditionConflict("No commander is identified yet.")
        async with self._lock, self._factory()() as db:
            expedition = await db.get(Expedition, expedition_id)
            if expedition is None or expedition.profile_key != DEFAULT_PROFILE_KEY:
                raise ExpeditionNotFound(expedition_id)
            expedition.profile_key = profile
            for stop in await self._stops(db, expedition_id):
                stop.profile_key = profile
            self._append_history(
                expedition, expeditions.history_entry("claimed", self._clock())
            )
            await db.commit()
        return await self.detail(expedition_id)

    async def unassigned(self) -> list[JsonDict]:
        """Expeditions planned before a commander was identified (to claim)."""
        if self._session_factory is None or self._profile_provider() is None:
            return []
        knowledge = self.knowledge()
        async with self._session_factory() as db:
            found = await db.scalars(
                select(Expedition).where(Expedition.profile_key == DEFAULT_PROFILE_KEY)
            )
            rows = []
            for expedition in found:
                described, _ = self._describe(
                    knowledge,
                    expedition,
                    await self._stops(db, expedition.expedition_id),
                )
                rows.append(self._brief(expedition, described))
            return rows

    # Finding stops -------------------------------------------------------------

    async def catalog(self) -> JsonDict:
        """Stories and themes to start from, with how far the nearest stop is."""
        knowledge = self.knowledge()
        profile = self.profile_key()
        mode = await self._mode(profile)
        origin = self._origin(knowledge)
        if knowledge is None:
            return {
                "state": galactic_knowledge.catalog()["state"],
                "narratives": [],
                "themes": [],
                "storytelling": mode,
                "origin": origin,
            }
        here = (origin or {}).get("star_pos")
        places = knowledge.places()
        narratives = []
        for row in knowledge.narratives():
            chapters = [places[p] for p in row["places"] if p in places]
            nearest = min(
                (
                    d
                    for d in (
                        expeditions.distance(here, c["star_pos"]) for c in chapters
                    )
                    if d is not None
                ),
                default=None,
            )
            narratives.append(
                {
                    **row,
                    "systems": list(dict.fromkeys(c["system"] for c in chapters)),
                    "nearest_ly": round(nearest, 1) if nearest is not None else None,
                }
            )
        themes = []
        for theme in knowledge.themes():
            acquisition = bool(theme["select"].get("acquisition"))
            count = len(expeditions.theme_places(knowledge, theme, acquisition=[]))
            themes.append(
                {
                    **theme,
                    "places": count,
                    "needs_shortages": acquisition,
                }
            )
        return {
            "state": "available",
            "narratives": narratives,
            "themes": themes,
            "storytelling": mode,
            "origin": origin,
        }

    async def _stop_keys(
        self, expedition_id: str | None
    ) -> tuple[set[str], list[JsonDict], Expedition | None]:
        if expedition_id is None:
            return set(), [], None
        knowledge = self.knowledge()
        async with self._factory()() as db:
            expedition = await self._get(db, expedition_id)
            stops = await self._stops(db, expedition_id)
            described, _ = self._describe(knowledge, expedition, stops)
        return {s.stop_key for s in stops}, described, expedition

    async def theme_candidates(
        self, theme_id: str, expedition_id: str | None = None
    ) -> JsonDict:
        knowledge = self.knowledge()
        if knowledge is None:
            raise ExpeditionConflict(
                "Galactic knowledge is not included in this build."
            )
        theme = next((t for t in knowledge.themes() if t["id"] == theme_id), None)
        if theme is None:
            raise ExpeditionNotFound(theme_id)
        keys, _, _ = await self._stop_keys(expedition_id)
        acquisition = None
        if theme["select"].get("acquisition"):
            intelligence = await self._acquisition()
            acquisition = ((intelligence or {}).get("all") or {}).get("destinations")
        picked = expeditions.theme_places(knowledge, theme, acquisition=acquisition)
        origin = self._origin(knowledge)
        rows = [
            expeditions.candidate(
                knowledge, place_id, reasons, origin=origin, stop_keys=keys
            )
            for place_id, reasons in picked.items()
        ]
        rows.sort(
            key=lambda r: (
                r["distance_ly"] is None,
                r["distance_ly"] or 0,
                r["place"]["name"],
            )
        )
        return {
            "theme": theme,
            "candidates": rows,
            "shortages_checked": acquisition is not None,
            "origin": origin,
        }

    async def materials(
        self, scope: str = "all", expedition_id: str | None = None
    ) -> JsonDict:
        """Goal-first: GKI-05 acquisition destinations for one build or all."""
        knowledge = self.knowledge()
        if knowledge is None:
            raise ExpeditionConflict(
                "Galactic knowledge is not included in this build."
            )
        keys, _, _ = await self._stop_keys(expedition_id)
        intelligence = await self._acquisition()
        scopes = sorted(k for k in (intelligence or {}) if k != "all")
        found = expeditions.goal_candidates(
            knowledge,
            (intelligence or {}).get(scope),
            origin=self._origin(knowledge),
        )
        for row in found["destinations"]:
            row["in_expedition"] = (
                expeditions.stop_key(row["place"]["id"], None, None) in keys
            )
        return {**found, "scope": scope, "scopes": ["all", *scopes]}

    async def suggestions(self, expedition_id: str) -> JsonDict:
        """Stories along the way, story places not yet added and related places."""
        knowledge = self.knowledge()
        if knowledge is None:
            raise ExpeditionConflict(
                "Galactic knowledge is not included in this build."
            )
        keys, described, expedition = await self._stop_keys(expedition_id)
        assert expedition is not None
        selected: dict[str, list[str]] = {}
        theme = next(
            (t for t in knowledge.themes() if t["id"] == expedition.theme_id), None
        )
        acquisition = None
        if theme is not None:
            if theme["select"].get("acquisition"):
                intelligence = await self._acquisition()
                acquisition = ((intelligence or {}).get("all") or {}).get(
                    "destinations"
                )
            selected = expeditions.theme_places(
                knowledge, theme, acquisition=acquisition
            )
        story_places: list[JsonDict] = []
        if expedition.narrative_id:
            narrative = knowledge.narrative(expedition.narrative_id)
            for item in [*narrative["chapters"], *narrative["discoveries"]]:
                selected.setdefault(item["place"], []).append(
                    f"Part of {narrative['title']}"
                )
            origin = self._origin(knowledge)
            for chapter in narrative["chapters"]:
                if expeditions.stop_key(chapter["place"], None, None) not in keys:
                    story_places.append(
                        {
                            **expeditions.candidate(
                                knowledge,
                                chapter["place"],
                                [f"Chapter: {chapter['title']}"],
                                origin=origin,
                                stop_keys=keys,
                            ),
                            "purpose": {
                                "type": "story",
                                "narrative": narrative["id"],
                                "chapter": chapter["id"],
                            },
                        }
                    )
            for item in narrative["discoveries"]:
                if expeditions.stop_key(item["place"], None, None) not in keys:
                    story_places.append(
                        {
                            **expeditions.candidate(
                                knowledge,
                                item["place"],
                                [
                                    "Optional discovery"
                                    + (
                                        f": {item['title']}"
                                        if item.get("title")
                                        else ""
                                    )
                                ],
                                origin=origin,
                                stop_keys=keys,
                            ),
                            "purpose": {
                                "type": "discovery",
                                "narrative": narrative["id"],
                            },
                        }
                    )
        related: list[JsonDict] = []
        seen_related: set[str] = set()
        # The system or body a stop is in is where it is, not another place.
        containers = {
            str(s["location"].get("system") or "").casefold() for s in described
        }
        for stop in described:
            if not stop.get("place_id") or not stop["available"]:
                continue
            for row in knowledge.related_destinations(stop["place_id"]):
                if row["id"] in seen_related or (
                    expeditions.stop_key(row["id"], None, None) in keys
                ):
                    continue
                place = knowledge.place(row["id"]) or {}
                if (
                    place.get("kind") in {"star_system", "body"}
                    and str(place.get("system") or "").casefold() in containers
                ):
                    continue
                seen_related.add(row["id"])
                through = (row.get("through") or {}).get("name")
                related.append(
                    {
                        **expeditions.candidate(
                            knowledge,
                            row["id"],
                            [
                                f"Connected to {stop['name']}"
                                + (f" through {through}" if through else "")
                            ],
                            origin=self._origin(knowledge),
                            stop_keys=keys,
                        ),
                        "hops": row["hops"],
                    }
                )
        return {
            "along_the_way": expeditions.along_the_way(
                knowledge, described, self._origin(knowledge), selected=selected
            ),
            "story": story_places,
            "related": related[: expeditions.SUGGESTION_LIMIT],
        }

    def search(self, query: str, limit: int = 20) -> JsonDict:
        """Documented places by name or system, and the system itself if known."""
        knowledge = self.knowledge()
        text = " ".join((query or "").split()).casefold()
        if len(text) < 2:
            return {"query": query, "places": [], "system": None}
        places = []
        if knowledge is not None:
            origin = self._origin(knowledge)
            for place_id, place in knowledge.places().items():
                haystack = f"{place['name']} {place['system'] or ''}".casefold()
                if text in haystack:
                    places.append(
                        expeditions.candidate(
                            knowledge,
                            place_id,
                            [
                                f"{place['kind'].replace('_', ' ').capitalize()} in "
                                f"{place['system']}"
                            ],
                            origin=origin,
                            stop_keys=set(),
                        )
                    )
            places.sort(key=lambda r: (not r["place"]["atlas"], r["place"]["name"]))
        system = knowledge.system_position(system=query.strip()) if knowledge else None
        return {
            "query": query,
            "places": places[:limit],
            "system": {
                "name": system["system"],
                "system_address": system["system_address"],
                "documented_position": True,
            }
            if system
            else {"name": " ".join(query.split()), "documented_position": False},
        }

    async def recap(self, expedition_id: str) -> JsonDict:
        knowledge = self.knowledge()
        async with self._factory()() as db:
            expedition = await self._get(db, expedition_id)
            stops = await self._stops(db, expedition_id)
            described, narratives = self._describe(knowledge, expedition, stops)
            story_data = _loads(expedition.story_json, {})
            history = _loads(expedition.history_json, [])
        prefs = await self._intelligence.preferences_for(self.profile_key())
        narrative = narratives.get(expedition.narrative_id or "")
        story = (
            expeditions.story_state(
                narrative,
                described,
                self._read(story_data, narrative["id"]),
                spoilers=not prefs["spoiler_protection"],
            )
            if narrative
            else None
        )
        return expeditions.recap(
            self._brief(expedition, described),
            described,
            history,
            narrative=narrative,
            story=story,
            spoilers=not prefs["spoiler_protection"],
        )

    # Commander Chronicle (GKI-07, read-only) -----------------------------------

    async def chronicle(self, profile_key: str) -> JsonDict:
        """One commander's expeditions as the Chronicle reads them.

        Each expedition's summary, chapters read and recent history, and every stop
        at a documented place with what the Journal showed (``reached`` only by an
        exact identifier) kept apart from what the Commander marked.
        """
        if self._session_factory is None:
            return {"expeditions": [], "stops": []}
        knowledge = self.knowledge()
        expeditions_out: list[JsonDict] = []
        stops_out: list[JsonDict] = []
        async with self._session_factory() as db:
            found = await db.scalars(
                select(Expedition)
                .where(Expedition.profile_key == profile_key)
                .order_by(Expedition.updated_at.desc())
            )
            for expedition in found:
                stops = await self._stops(db, expedition.expedition_id)
                described, _ = self._describe(knowledge, expedition, stops)
                story = _loads(expedition.story_json, {})
                brief = self._brief(expedition, described)
                expeditions_out.append(
                    {
                        **brief,
                        "chapters_read": len(story.get("read", [])),
                        "history": _loads(expedition.history_json, [])[-50:],
                    }
                )
                for stop in described:
                    if not stop["place_id"]:
                        continue
                    evidence = stop["evidence"]
                    stops_out.append(
                        {
                            "expedition": {
                                "id": expedition.expedition_id,
                                "name": expedition.name,
                                "status": expedition.status,
                            },
                            "stop_id": stop["stop_id"],
                            "place_id": stop["place_id"],
                            "reached": bool(
                                evidence.get("reached") and evidence.get("exact")
                            ),
                            "reached_at": evidence.get("reached_at"),
                            "reached_event": evidence.get("reached_event"),
                            "manual_state": stop["manual_state"],
                            "manual_at": stop["manual_at"],
                        }
                    )
        return {"expeditions": expeditions_out, "stops": stops_out}

    async def chapters_at(
        self, profile_key: str, place_ids: list[str]
    ) -> list[JsonDict]:
        """Story chapters of the commander's active expeditions set at these places.

        For a briefing to point back to the expedition; GKI-06 keeps the
        opportunity, the reader and the record of what was read.
        """
        knowledge = self.knowledge()
        if self._session_factory is None or knowledge is None or not place_ids:
            return []
        wanted = set(place_ids)
        rows: list[JsonDict] = []
        async with self._session_factory() as db:
            active = await db.scalars(
                select(Expedition).where(
                    Expedition.profile_key == profile_key,
                    Expedition.status == "active",
                )
            )
            for expedition in active:
                story = _loads(expedition.story_json, {})
                for stop in await self._stops(db, expedition.expedition_id):
                    if stop.place_id not in wanted:
                        continue
                    for purpose in _loads(stop.purposes_json, []):
                        if purpose.get("type") != "story":
                            continue
                        try:
                            narrative = knowledge.narrative(purpose["narrative"])
                        except KeyError:
                            continue
                        position, chapter = next(
                            (
                                (n, c)
                                for n, c in enumerate(narrative["chapters"], start=1)
                                if c["id"] == purpose.get("chapter")
                            ),
                            (None, None),
                        )
                        if chapter is None:
                            continue
                        rows.append(
                            {
                                "expedition": {
                                    "id": expedition.expedition_id,
                                    "name": expedition.name,
                                },
                                "stop_id": stop.stop_id,
                                "place_id": stop.place_id,
                                "narrative": {
                                    "id": narrative["id"],
                                    "title": narrative["title"],
                                },
                                "chapter": {
                                    "id": chapter["id"],
                                    "title": chapter["title"],
                                    "position": position,
                                    "count": len(narrative["chapters"]),
                                    "teaser": chapter["teaser"],
                                    "spoiler": bool(chapter.get("spoiler")),
                                },
                                "read": chapter["id"]
                                in self._read(story, narrative["id"]),
                            }
                        )
        return rows

    # Narrative opportunities ---------------------------------------------------

    def opportunities(self) -> list[JsonDict]:
        """Undismissed opportunities for the current commander, newest first."""
        profile = self.profile_key()
        return [
            o
            for o in self._opportunities
            if o["profile_key"] == profile
            and o["opportunity_id"] not in self._dismissed
        ]

    def dismiss(self, opportunity_id: str) -> bool:
        profile = self.profile_key()
        if not any(
            o["opportunity_id"] == opportunity_id and o["profile_key"] == profile
            for o in self._opportunities
        ):
            return False
        self._dismissed.add(opportunity_id)
        # Only ids still in the bounded list need remembering.
        self._dismissed &= {o["opportunity_id"] for o in self._opportunities}
        return True

    # Journal progress ------------------------------------------------------------

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

    def _current_system(self) -> JsonDict | None:
        context = self._state.public_snapshot().get("local_system_context")
        if not isinstance(context, dict):
            return None
        return {
            "system": context.get("star_system"),
            "system_address": context.get("system_address"),
            "star_pos": context.get("star_pos"),
        }

    def note_rank(self, event: JsonDict) -> None:
        """Remember the last Rank event per commander (a permit hint, in memory)."""
        if self._profile_provider() is None:
            return
        ranks = {
            career: event[career]
            for career in expeditions.CAREERS
            if isinstance(event.get(career), int)
        }
        if ranks:
            self._ranks[self.profile_key()] = {
                **ranks,
                "observed_at": event.get("timestamp"),
            }

    async def observe(self, event: JsonDict) -> JsonDict:
        """Apply one Journal event to the active commander's active expeditions."""
        if event.get("event") == "Rank":
            self.note_rank(event)
            return self._decide("noted", "rank", event)
        seen = expeditions.progress_observation(event, self._current_system())
        if seen is None:
            return self._decide("ignored", "not_a_progress_event", event)
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
        knowledge = self.knowledge()
        matches = (
            {
                m["id"]: m
                for m in knowledge.match_location(seen["observation"])["matches"]
            }
            if knowledge is not None
            else {}
        )
        key = galactic_intelligence.event_key(profile, event)
        stamp = _now_naive(observed_at)
        at = commander_context.iso(observed_at)
        mode = await self._mode(profile)
        offers: list[JsonDict] = []
        updated = 0
        async with self._lock, self._session_factory() as db:
            active = await db.scalars(
                select(Expedition).where(
                    Expedition.profile_key == profile, Expedition.status == "active"
                )
            )
            for expedition in list(active):
                # Journal timestamps are whole seconds: an event in the second the
                # expedition started belongs to it.
                if expedition.started_at is None or stamp < _whole_second(
                    expedition.started_at
                ):
                    continue
                stops = await self._stops(db, expedition.expedition_id)
                transitions: list[tuple[ExpeditionStop, JsonDict, list[str]]] = []
                for stop in stops:
                    if stamp < _whole_second(stop.created_at):
                        continue
                    found = expeditions.stop_evidence(_row(stop), seen, matches)
                    if found is None:
                        continue
                    before = _loads(stop.evidence_json, {})
                    evidence, changes = expeditions.merge_evidence(
                        before,
                        found,
                        event=seen["event"],
                        at=str(at),
                        key=key,
                        replayed=replay is not None,
                    )
                    if not changes:
                        if evidence.get("landed_km") != before.get("landed_km"):
                            # A nearer landing says how near; it is no new stage.
                            stop.evidence_json = _dumps(evidence)
                            stop.updated_at = _now_naive(now)
                        continue
                    stop.evidence_json = _dumps(evidence)
                    stop.updated_at = _now_naive(now)
                    transitions.append((stop, found, changes))
                story = _loads(expedition.story_json, {})
                departed = (
                    self._departure(expedition, stops, seen, story)
                    if replay is None
                    else None
                )
                if not transitions and departed is None:
                    continue
                updated += 1
                described, narratives = self._describe(knowledge, expedition, stops)
                by_id = {s["stop_id"]: s for s in described}
                for stop, found, changes in transitions:
                    most = next(
                        c
                        for c in ("reached", "approached", "in_system")
                        if c in changes
                    )
                    self._append_history(
                        expedition,
                        expeditions.history_entry(
                            most,
                            at,
                            stop=by_id[stop.stop_id],
                            source="journal",
                            event=seen["event"],
                            basis=found["basis"],
                            replay=replay,
                        ),
                    )
                expedition.updated_at = _now_naive(now)
                if replay is None:
                    offers += self._offers(
                        profile,
                        expedition,
                        described,
                        narratives,
                        story,
                        transitions,
                        departed,
                        seen,
                        at=str(at),
                        mode=mode,
                        now=now,
                    )
                    expedition.story_json = _dumps(story)
            await db.commit()
        for offer in offers:
            self._opportunities.appendleft(offer)
        return self._decide(
            "recorded" if updated else "no_change",
            replay or ("progress" if updated else "no_matching_stop"),
            event,
            expeditions=updated,
            opportunities=len(offers),
        )

    @staticmethod
    def _departure(
        expedition: Expedition,
        stops: list[ExpeditionStop],
        seen: JsonDict,
        story: JsonDict,
    ) -> ExpeditionStop | None:
        """The reached story stop a jump just left, once per stop (stage C)."""
        if seen["event"] not in JUMP_EVENTS:
            return None
        address = seen["observation"].get("system_address")
        reached = [
            s
            for s in stops
            if _loads(s.evidence_json, {}).get("reached")
            and any(p["type"] == "story" for p in _loads(s.purposes_json, []))
            and s.stop_id not in story.get("continued", [])
        ]
        if not reached:
            return None
        last = max(
            reached, key=lambda s: str(_loads(s.evidence_json, {}).get("reached_at"))
        )
        if last.system_address is not None and last.system_address == address:
            return None
        return last

    def _offers(
        self,
        profile: str,
        expedition: Expedition,
        described: list[JsonDict],
        narratives: dict[str, JsonDict],
        story: JsonDict,
        transitions: list[tuple[ExpeditionStop, JsonDict, list[str]]],
        departed: ExpeditionStop | None,
        seen: JsonDict,
        *,
        at: str,
        mode: JsonDict,
        now: datetime,
    ) -> list[JsonDict]:
        """Stage A/B/C/D opportunities a live event earned, each offered once."""
        by_id = {s["stop_id"]: s for s in described}
        brief = {"id": expedition.expedition_id, "name": expedition.name}
        offered = list(story.get("offered", []))
        found: list[JsonDict] = []

        def offer(**kwargs: Any) -> None:
            item = expeditions.opportunity(
                profile_key=profile, expedition=brief, mode=mode, now=now, **kwargs
            )
            if item["dedup_key"] in offered:
                return
            offered.append(item["dedup_key"])
            found.append(item)

        # One event, one approach teaser per story: the earliest chapter it
        # neared.  Arrivals are rare and each is offered.
        approached: set[str] = set()
        offered_chapters: set[str] = set()
        ordered = sorted(
            transitions,
            key=lambda t: min(
                (
                    p.get("chapter_position") or 99
                    for p in by_id[t[0].stop_id]["purposes"]
                    if p["type"] == "story"
                ),
                default=99,
            ),
        )
        for stop, evidence, changes in ordered:
            view = by_id[stop.stop_id]
            trigger = {
                "event": seen["event"],
                "observed_at": at,
                "level": evidence["level"],
                "exact": evidence["exact"],
                "basis": evidence["basis"],
                "replayed": False,
                "source": "journal",
            }
            for purpose in view["purposes"]:
                if purpose["type"] != "story" or purpose["narrative"] not in narratives:
                    continue
                narrative = narratives[purpose["narrative"]]
                chapter = next(
                    (c for c in narrative["chapters"] if c["id"] == purpose["chapter"]),
                    None,
                )
                # Arriving in a system is not approaching a station or a site in
                # it: a teaser needs approach evidence (a docking request, a body
                # or settlement approach), and only the place reached is briefed.
                if "reached" in changes:
                    stage = "arrival"
                elif "approached" in changes:
                    stage = "approach"
                    if narrative["id"] in approached:
                        continue
                    approached.add(narrative["id"])
                else:
                    continue
                offered_chapters.add(f"{narrative['id']}/{purpose['chapter']}")
                offer(
                    stage=stage,
                    stop=view,
                    narrative=narrative,
                    chapter=chapter,
                    trigger=trigger,
                )
        arc = narratives.get(expedition.narrative_id or "")
        if arc is not None:
            state = expeditions.story_state(
                arc,
                described,
                self._read(story, arc["id"]),
                spoilers=not mode["spoiler_protection"],
            )
            if state["complete"] and any("reached" in t[2] for t in transitions):
                offer(
                    stage="recap",
                    stop=None,
                    narrative=arc,
                    chapter=None,
                    trigger={
                        "event": seen["event"],
                        "observed_at": at,
                        "source": "journal",
                        "replayed": False,
                    },
                )
            if departed is not None:
                story["continued"] = [*story.get("continued", []), departed.stop_id]
                following = next(
                    (
                        c
                        for c in state["chapters"]
                        if not c["read"]
                        and c["stop_status"] not in {"reached", "completed", "skipped"}
                    ),
                    None,
                )
                # Already offered at its own place in this event: no need to
                # point to it as the next chapter as well.
                if f"{arc['id']}/{(following or {}).get('id')}" in offered_chapters:
                    following = None
                if following is not None:
                    chapter = next(
                        c for c in arc["chapters"] if c["id"] == following["id"]
                    )
                    target = by_id.get(following["stop_id"] or "")
                    away = expeditions.distance(
                        (self._current_system() or {}).get("star_pos"),
                        (target or {}).get("location", {}).get("star_pos"),
                    )
                    offer(
                        stage="continue",
                        stop=target,
                        narrative=arc,
                        chapter=chapter,
                        trigger={
                            "event": seen["event"],
                            "observed_at": at,
                            "left": by_id[departed.stop_id]["name"],
                            "source": "journal",
                            "replayed": False,
                        },
                        following={
                            "stop_id": following["stop_id"],
                            "place_name": following["place_name"],
                            "distance_ly": round(away, 1) if away is not None else None,
                        },
                    )
        story["offered"] = offered[-OFFERED_LIMIT:]
        return found

    # Commander lifecycle -----------------------------------------------------

    async def purge_profile(self, db: AsyncSession, profile_key: str) -> None:
        """Forget-workflow purge, inside Commander Memory's forget transaction.

        Removes the commander's expeditions, stops, story progress and history.
        Other commanders' rows are untouched.
        """
        await db.execute(
            delete(ExpeditionStop).where(ExpeditionStop.profile_key == profile_key)
        )
        await db.execute(
            delete(Expedition).where(Expedition.profile_key == profile_key)
        )

    async def after_forget(self, profile_key: str) -> None:
        """After the forget commits: in-memory ranks, opportunities and decisions."""
        self._ranks.pop(profile_key, None)
        self._opportunities = deque(
            (o for o in self._opportunities if o["profile_key"] != profile_key),
            maxlen=MAX_OPPORTUNITIES,
        )
        self.decisions = deque(
            (d for d in self.decisions if d.get("profile_key") != profile_key),
            maxlen=RECENT_DECISIONS,
        )
        if self._notify is not None:
            try:
                await self._notify(
                    {
                        "event_type": CLEARED_EVENT,
                        "timestamp": commander_context.iso(self._clock()),
                        "payload": {"reason": "commander_forgotten"},
                        "source": "expeditions",
                    }
                )
            except Exception:
                logger.exception("Expedition clear push failed")


def register(
    register_handler: Callable[[str, EventHandler], None],
    service: ExpeditionService,
) -> None:
    """Attach the service to the existing dispatcher, after the state handlers.

    The dispatcher runs handlers in order, so a docking event without a system
    name is read against the system the state handlers just recorded.
    """

    async def observe(event: JsonDict) -> None:
        await service.observe(event)

    for name in (*expeditions.PROGRESS_EVENTS, "Rank"):
        register_handler(name, observe)
