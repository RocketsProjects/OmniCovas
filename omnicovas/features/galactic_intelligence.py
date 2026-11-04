"""Galactic Intelligence: documented knowledge for where the Commander is (GKI-04).

Three parts, all deterministic and offline:

* **Relevance** — :func:`documented_here` answers "what documented information is
  relevant to this Commander, at this location, right now?" by combining
  :mod:`commander_context` with the Galactic Knowledge index and its GKI-03 location
  matching.  A system association is never a visit: each result keeps the match level,
  whether it was identified exactly, and what reaching the place would need.
* **Preferences** — :class:`PreferenceStore` keeps one record per Commander Memory
  profile in the existing configuration vault.  Automatic intelligence is off by
  default; manual Atlas and Intel reading never depends on it.
* **Briefings** — :class:`GalacticIntelligence` turns a Journal ``FSDJump``,
  ``CarrierJump``, ``Location``, ``Docked`` or (GKI-07) ``Touchdown`` observation,
  after the existing handlers have projected it into state, into at most one small,
  dismissible briefing.  GKI-07's Historian (:mod:`galactic_historian`) enriches it
  from the Commander Chronicle's evidence, and every composed briefing is also kept
  as a ``narrative-opportunity-v1`` moment for the future Notification Director.

Briefing eligibility, in order (each refusal is a recorded ``reason``):

1. ``startup_replay`` — the event was dispatched by the watcher's startup
   catch-up (:func:`journal_watcher.is_startup_replay`): it was in the Journal
   before OmniCOVAS started, however recent, so it rebuilds state but is not an
   observed arrival.
   ``out_of_order`` — older than a location event already processed.
   ``replay`` — the Journal event is older (or newer) than
   :data:`REPLAY_WINDOW_SECONDS` against the clock (a delayed delivery, or a
   rollover catch-up of an old file).
   ``commander_unknown`` / ``commander_forgotten`` — no commander identified yet,
   or the commander was forgotten in Commander Memory: nothing is announced or
   stored for them.
2. ``disabled`` — automatic intelligence is off, or frequency is ``off``.
3. ``knowledge_unavailable`` — no knowledge pack.
4. ``no_documented_place`` / ``ambiguous_station`` / ``ambiguous_system`` — a station
   briefing needs the observed MarketID to equal the documented one; a system notice
   needs the SystemAddress.  Names alone never brief.  ``not_at_site`` — a landing
   near a documented site but not at it (or a ship recalled to an SRV) is no arrival.
5. ``arrival_disabled`` (GKI-07) — arrival briefings are off and no documented site
   is nearby; ``visited_before`` — "first visit only" is on and the Chronicle
   already has the Commander there.
   ``content_disabled`` — every section the briefing could carry is switched off.
6. ``quiet_mode`` — Quiet Mode keeps only recommendations tied to an active build.
7. ``not_important`` — frequency ``important`` and the subject is not important
   (importance: an Atlas event or discovery is documented at the place).
8. ``duplicate_event`` — this profile was already briefed for this Journal event
   (event identity: event type, timestamp, SystemAddress, MarketID).
9. ``already_briefed`` (``first`` and ``important``) or ``cooldown`` (``all``,
   :data:`COOLDOWN_SECONDS`) — per profile and documented place.

"First" means the first eligible encounter OmniCOVAS observed, never a first visit.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core import journal_watcher
from omnicovas.core.dispatcher import EventHandler, RawRecorder
from omnicovas.core.state_manager import StateManager
from omnicovas.db.models import (
    CommanderMemoryProfile,
    GalacticIntelligenceBriefing,
    GalacticIntelligenceEncounter,
)
from omnicovas.features import (
    commander_context,
    engineering,
    galactic_atlas,
    galactic_historian,
    galactic_knowledge,
    local_context_facts,
)
from omnicovas.features.galactic_knowledge import KnowledgeIndex

logger = logging.getLogger(__name__)

JsonDict = dict[str, Any]

VERSION = "galactic-intelligence-v1"
BRIEFING_EVENT = "GALACTIC_INTELLIGENCE_BRIEFING"
# Pushed when a commander's intelligence state is erased, so open UIs drop it.
CLEARED_EVENT = "GALACTIC_INTELLIGENCE_CLEARED"
# GKI-07 adds Touchdown: landing at an exactly documented site is an arrival.
BRIEFING_EVENTS = ("FSDJump", "CarrierJump", "Location", "Docked", "Touchdown")
MAX_OPPORTUNITIES = 50
DEFAULT_PROFILE_KEY = "local-default"
VAULT_KEY = "settings_galactic_intelligence"

REPLAY_WINDOW_SECONDS = 5 * 60
COOLDOWN_SECONDS = 6 * 60 * 60
ACTIVE_BRIEFING_SECONDS = 4 * 60 * 60
MAX_ACTIVE_BRIEFINGS = 3
RETENTION_DAYS = 30
MAX_BRIEFINGS_PER_PROFILE = 200
MAX_ENCOUNTERS_PER_PROFILE = 2000
RECENT_DECISIONS = 25
SEEN_EVENTS = 512

CATEGORIES = (
    "station_history",
    "figures_events",
    "factions_politics",
    "discoveries",
    "practical",
    "recommendations",
    # GKI-06: whether expedition stories may ever be offered automatically.
    "expedition_stories",
    # GKI-07: connected places to explore next, with straight-line distances.
    "suggestions",
)
CATEGORY_LABELS = {
    "station_history": "Station and location history",
    "figures_events": "Historical figures and events",
    "factions_politics": "Factions and political history",
    "discoveries": "Scientific and exploration discoveries",
    "practical": "Material farming and practical opportunities",
    "recommendations": "Contextual recommendations",
    "expedition_stories": "Expedition stories and arrival teasers",
    "suggestions": "Discovery suggestions: where to explore next",
}
FREQUENCIES = ("off", "important", "first", "all")
DEFAULT_PREFERENCES: JsonDict = {
    "enabled": False,
    "content": {category: True for category in CATEGORIES},
    "frequency": "first",
    "quiet_mode": False,
    "spoiler_protection": True,
    # GKI-07: arrival briefings (a documented station, system or site reached)
    # may be switched off on their own, leaving "nearby" discovery briefings.
    "arrival_briefings": True,
    # GKI-07: only places with no earlier record of the Commander being there.
    # An empty record is never read as "never visited", only as "no record".
    "first_visit_only": False,
}
CATEGORY_BY_KIND = {
    "star_system": "station_history",
    "body": "station_history",
    "station": "station_history",
    "settlement": "station_history",
    "location": "station_history",
    "landmark": "discoveries",
    "vessel": "discoveries",
    "discovery": "discoveries",
    "person": "figures_events",
    "event": "figures_events",
    "organization": "factions_politics",
    "mystery": "discoveries",
}
RELATION_LABELS = {
    "located_in": "Located in",
    "named_after": "Named after",
    "associated_with": "Associated with",
    "discovered_by": "Discovered by",
    "participated_in": "Took part in",
    "member_of": "Member of",
    "historically_controlled_by": "Historically controlled by",
    "occurred_at": "Took place here",
    "related_to": "Related to",
    "founded_by": "Founded by",
    "part_of_expedition": "Part of the expedition",
    "related_to_mystery": "Connected mystery",
}

Notify = Callable[[JsonDict], Awaitable[None]]
# GKI-07: the Commander Chronicle's evidence for a briefing (records by place id,
# expedition chapters set here, the Commander's star position).  Injected so the
# one context engine stays here and the Chronicle stays a reader of evidence.
HistoryProvider = Callable[
    [str, KnowledgeIndex, JsonDict, JsonDict], Awaitable[JsonDict | None]
]


# ── Preferences ──────────────────────────────────────────────────────────────


def default_preferences() -> JsonDict:
    prefs: JsonDict = json.loads(json.dumps(DEFAULT_PREFERENCES))
    return prefs


def normalize_preferences(raw: Any, *, strict: bool = False) -> JsonDict:
    """A complete preference record; unknown or invalid values fall back.

    With ``strict`` an invalid value raises ``ValueError`` instead (API input).
    """
    prefs = default_preferences()
    if not isinstance(raw, dict):
        if strict:
            raise ValueError("preferences must be an object")
        return prefs

    def flag(value: Any, field: str, fallback: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is not None and strict:
            raise ValueError(f"{field} must be true or false")
        return fallback

    prefs["enabled"] = flag(raw.get("enabled"), "enabled", prefs["enabled"])
    prefs["quiet_mode"] = flag(raw.get("quiet_mode"), "quiet_mode", False)
    prefs["spoiler_protection"] = flag(
        raw.get("spoiler_protection"), "spoiler_protection", True
    )
    prefs["arrival_briefings"] = flag(
        raw.get("arrival_briefings"), "arrival_briefings", True
    )
    prefs["first_visit_only"] = flag(
        raw.get("first_visit_only"), "first_visit_only", False
    )
    frequency = raw.get("frequency")
    if frequency in FREQUENCIES:
        prefs["frequency"] = frequency
    elif frequency is not None and strict:
        raise ValueError(f"frequency must be one of {', '.join(FREQUENCIES)}")
    content = raw.get("content")
    if isinstance(content, dict):
        for category in CATEGORIES:
            prefs["content"][category] = flag(
                content.get(category), f"content.{category}", True
            )
        unknown = sorted(set(content) - set(CATEGORIES))
        if unknown and strict:
            raise ValueError(f"unknown content control {unknown[0]}")
    elif content is not None and strict:
        raise ValueError("content must be an object")
    return prefs


class PreferenceStore:
    """Per-profile preferences in the existing configuration vault.

    One vault key holds ``{"version": 1, "profiles": {profile_key: preferences}}``.
    A profile without its own record reads the ``local-default`` record (what was
    set before any commander was observed), then the built-in defaults.
    """

    def __init__(self, vault: Any) -> None:
        self._vault = vault

    def _all(self) -> JsonDict:
        raw = self._vault.get(VAULT_KEY) if self._vault is not None else None
        try:
            data = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            data = {}
        profiles = data.get("profiles") if isinstance(data, dict) else None
        return profiles if isinstance(profiles, dict) else {}

    def get(self, profile_key: str) -> JsonDict:
        profiles = self._all()
        raw = profiles.get(profile_key, profiles.get(DEFAULT_PROFILE_KEY))
        return normalize_preferences(raw)

    def has_own(self, profile_key: str) -> bool:
        return profile_key in self._all()

    def set(self, profile_key: str, preferences: Any) -> JsonDict:
        prefs = normalize_preferences(preferences, strict=True)
        profiles = self._all()
        profiles[profile_key] = prefs
        if self._vault is None or not self._vault.set(
            VAULT_KEY, json.dumps({"version": 1, "profiles": profiles})
        ):
            raise OSError("Galactic Intelligence preferences could not be saved")
        return prefs

    def reset(self, profile_key: str) -> JsonDict:
        profiles = self._all()
        profiles.pop(profile_key, None)
        if self._vault is not None:
            self._vault.set(VAULT_KEY, json.dumps({"version": 1, "profiles": profiles}))
        return self.get(profile_key)


# ── Relevance ────────────────────────────────────────────────────────────────


def _brief(entity: JsonDict) -> JsonDict:
    return {key: entity[key] for key in ("id", "kind", "name")}


def _claims(entity: JsonDict, topic: str, *, spoilers: bool) -> tuple[list[str], int]:
    shown, hidden = [], 0
    for claim in entity.get("claims", []):
        if claim.get("topic") != topic:
            continue
        if claim.get("spoiler") and not spoilers:
            hidden += 1
            continue
        shown.append(claim["text"])
    return shown, hidden


def _significance(entity: JsonDict, *, spoilers: bool) -> tuple[str | None, int]:
    attributes = entity.get("attributes") or {}
    if attributes.get("significance_spoiler") and not spoilers:
        return None, 1
    return attributes.get("significance"), 0


def _sources(entry: JsonDict, limit: int = 4) -> list[JsonDict]:
    return [{"id": s["id"], "name": s["name"]} for s in entry["sources"][:limit]]


def importance(knowledge: KnowledgeIndex, place_ids: list[str]) -> str:
    """``major`` when an Atlas event or discovery is documented at any of the places.

    Deterministic and taken from the graph, never a judgement: it is what the
    ``important`` frequency briefs about.
    """
    for place_id in place_ids:
        for row in knowledge.related(place_id):
            if row["type"] == "occurred_at" and row["direction"] == "incoming":
                return "major"
    return "minor"


def _connection(row: JsonDict) -> JsonDict:
    entity = row["entity"]
    out: JsonDict = {
        "relation": row["type"],
        "label": RELATION_LABELS.get(row["type"], row["type"].replace("_", " ")),
        "entity": {"id": entity["id"], "kind": entity["kind"], "name": entity["name"]},
        "category": CATEGORY_BY_KIND.get(entity["kind"], "station_history"),
        "certainty": row.get("certainty") or "documented",
        "sources": list(row.get("sources") or []),
    }
    for key in ("note", "period", "role"):
        if row.get(key):
            out[key] = row[key]
    if row["type"] == "historically_controlled_by":
        out["historical_only"] = True
    return out


def _associations(entry: JsonDict) -> list[JsonDict]:
    """People, organizations, events and discoveries tied directly to a place."""
    return [
        _connection(row)
        for row in entry["connections"]
        if row["entity"].get("atlas")
        and row["entity"]["kind"] not in galactic_knowledge.PLACE_KINDS
    ]


def _practical(entry: JsonDict) -> list[JsonDict]:
    return [
        {
            "activity": {"id": row["id"], "name": row["name"]},
            "summary": row["summary"],
            "materials": [
                {
                    "id": m["id"],
                    "name": m["name"],
                    "symbol": (m.get("inventory") or {}).get("symbol"),
                }
                for m in row["materials"]
            ],
            "sources": list(row["sources"]),
        }
        for row in entry["practical"]
    ]


def _place_result(
    knowledge: KnowledgeIndex,
    match: JsonDict,
    *,
    relation: str,
    spoilers: bool,
) -> JsonDict:
    entry = knowledge.atlas_entry(match["id"])
    entity = entry["entity"]
    significance, hidden = _significance(entity, spoilers=spoilers)
    uncertainty, hidden_uncertain = _claims(entity, "uncertainty", spoilers=spoilers)
    if relation == "this_station":
        reason = (
            "You are docked here; the station was identified by its MarketID."
            if match["exact"]
            else "A station of this name in this system; identified by name only."
        )
    elif relation == "this_system":
        reason = (
            "You are in this system; identified by its SystemAddress."
            if match["exact"]
            else "A system of this name; identified by name only."
        )
    elif entity["kind"] == "body":
        reason = "A documented body in this system."
    else:
        reason = "Documented in this system. Being in the system is not a visit to it."
    return {
        "entity": _brief(entity),
        "category": CATEGORY_BY_KIND.get(entity["kind"], "station_history"),
        "relation": relation,
        "reason": reason,
        "summary": entity["summary"],
        "significance": significance,
        "uncertainty": uncertainty,
        "spoilers_hidden": hidden + hidden_uncertain,
        "match": {
            key: match[key]
            for key in ("level", "exact", "reached", "needs", "basis", "surface")
            if key in match
        },
        "precision": (entry["location"] or {}).get("precision"),
        "associations": _associations(entry)
        if relation in {"this_station", "this_system"}
        else [],
        "practical": _practical(entry),
        "sources": _sources(entry),
        "actions": [{"type": "open_atlas", "entity_id": entity["id"]}],
    }


def documented_here(
    knowledge: KnowledgeIndex, observation: JsonDict, *, spoilers: bool = True
) -> JsonDict:
    """Documented Atlas places for an observed position, and how they relate to it.

    ``station`` holds a documented station at the observed dock (exact by MarketID,
    or by name only and labelled so); ``system`` holds the system itself and every
    other documented place in it, none of which the observation reaches unless the
    match says so.  Read-only.
    """
    if not observation.get("system") and observation.get("system_address") is None:
        return {"system": [], "station": [], "observation": observation}
    atlas_ids = {row["id"] for row in knowledge.atlas()}
    matches = [
        m
        for m in knowledge.match_location(observation)["matches"]
        if m["id"] in atlas_ids
    ]
    station: list[JsonDict] = []
    system: list[JsonDict] = []
    for match in matches:
        kind = knowledge.atlas_entry(match["id"])["entity"]["kind"]
        if match["level"] == "station":
            station.append(
                _place_result(
                    knowledge, match, relation="this_station", spoilers=spoilers
                )
            )
        elif kind == "star_system":
            system.insert(
                0,
                _place_result(
                    knowledge, match, relation="this_system", spoilers=spoilers
                ),
            )
        else:
            system.append(
                _place_result(knowledge, match, relation="in_system", spoilers=spoilers)
            )
    return {"system": system, "station": station, "observation": observation}


# ── Briefings ────────────────────────────────────────────────────────────────


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def event_key(profile_key: str, event: JsonDict) -> str:
    """Stable identity of one Journal observation for one commander."""
    parts = [
        profile_key,
        str(event.get("event")),
        str(event.get("timestamp")),
        str(event.get("SystemAddress")),
        str(event.get("MarketID")),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def location_key(observation: JsonDict) -> str:
    """The system an observation is in, as an opaque comparison key."""
    address = observation.get("system_address")
    if address is not None:
        return f"system:{address}"
    system = observation.get("system")
    return f"name:{str(system).strip().casefold()}" if system else ""


def presence_key(observation: JsonDict, *, docked: bool) -> str:
    """Where a briefing's moment happened, at the level it describes.

    A docked arrival belongs to its station (by MarketID, else by name in its
    system); everything else to its system.  No existing projection keeps a
    surface position, so a landing is judged at the system level.
    """
    system = location_key(observation)
    if docked:
        if observation.get("market_id") is not None:
            return f"station:{observation['market_id']}"
        if observation.get("station") and system:
            name = str(observation["station"]).strip().casefold()
            return f"station:{system}:{name}"
    return system


def presence_keys(context: JsonDict) -> set[str] | None:
    """Every place key the Commander Context shows as current, or None.

    None means the current location is not known (nothing observed, or only an
    old or not-live observation): that proves neither presence nor departure.
    """
    system = context.get("system") or {}
    station = context.get("station") or {}
    docked = station.get("state") == "current" and bool(station.get("docked"))
    if system.get("state") != "current" and not docked:
        return None
    seen = commander_context.observation(context)
    keys: set[str] = set()
    if system.get("state") == "current" or docked:
        # A current docking also places the Commander in the station's system.
        keys.add(location_key(seen))
    if docked:
        keys.add(presence_key(seen, docked=True))
    return (keys - {""}) or None


def event_observation(event: JsonDict) -> JsonDict:
    """The observed position, built by the same projections the state handlers use."""
    name = event.get("event")
    seen: JsonDict = {}
    if name in {"FSDJump", "CarrierJump", "Location"}:
        system = local_context_facts.build_local_system_context(
            event, source_event=str(name)
        )
        seen.update(
            system=system.star_system,
            system_address=system.system_address,
            body=system.body,
            body_id=system.body_id,
        )
    docked = name == "Docked" or (name == "Location" and event.get("Docked") is True)
    if docked:
        station = local_context_facts.build_local_station_context(
            event, source_event=str(name)
        )
        seen.update(
            station=station.station_name,
            market_id=station.market_id,
            system=station.star_system or seen.get("system"),
            system_address=station.system_address
            if station.system_address is not None
            else seen.get("system_address"),
        )
    if name == "Touchdown":
        seen.update(
            system=event.get("StarSystem"),
            system_address=event.get("SystemAddress"),
            body=event.get("Body"),
            body_id=event.get("BodyID"),
            player_controlled=player_controlled(event),
        )
    # A surface position (GKI-07): Touchdown, or a Location logged on the surface.
    if (name == "Touchdown" or (name == "Location" and not docked)) and all(
        isinstance(event.get(field), int | float) for field in ("Latitude", "Longitude")
    ):
        seen.update(
            latitude=float(event["Latitude"]), longitude=float(event["Longitude"])
        )
    return {key: value for key, value in seen.items() if value is not None}


def player_controlled(event: JsonDict) -> bool | None:
    """A Touchdown's ``PlayerControlled``: false for a ship recalled to an SRV."""
    value = event.get("PlayerControlled")
    return value if isinstance(value, bool) else None


def is_landed(event: JsonDict) -> bool:
    """A Touchdown, or a Location logged on a planet's surface (GKI-07)."""
    name = event.get("event")
    if name == "Touchdown":
        return True
    return (
        name == "Location"
        and event.get("Docked") is not True
        and isinstance(event.get("Latitude"), int | float)
        and isinstance(event.get("Longitude"), int | float)
    )


def compose_briefing(
    knowledge: KnowledgeIndex,
    observation: JsonDict,
    prefs: JsonDict,
    *,
    docked: bool,
    relevance: dict[str, JsonDict] | None = None,
    landed: bool = False,
    history: JsonDict | None = None,
    event: JsonDict | None = None,
) -> tuple[JsonDict | None, str]:
    """The briefing an observation earns under these preferences, or a refusal.

    Pure: the lifecycle (replay, frequency, deduplication) is applied by the caller.
    ``relevance`` maps place ids to :func:`galactic_atlas.relevance` results.

    GKI-07: ``landed`` makes a surface observation a site arrival, reached only at
    an exactly documented position.  A briefing is an ``arrival`` (a documented
    station, site, or the documented system itself) or ``nearby`` (documented
    places in a system the Commander entered, none of them visited by arriving).
    ``arrival_briefings`` off turns a system arrival with documented sites into a
    nearby briefing and refuses the rest (``arrival_disabled``); ``first_visit_only``
    refuses places the Chronicle (``history``) already saw the Commander at
    (``visited_before``).  The Historian adds namesakes, founders, faction history
    beside the faction the Journal reports now, mysteries, expedition chapters set
    here and what to explore next, each under its own content control.
    """
    spoilers = not prefs["spoiler_protection"]
    content = prefs["content"]
    found = documented_here(knowledge, observation, spoilers=spoilers)
    exact_station = [row for row in found["station"] if row["match"]["exact"]]
    here: list[JsonDict] = []
    if landed:
        sites = [
            row
            for row in found["system"]
            if row["match"]["level"] == "surface"
            and row["match"]["reached"]
            and row["match"]["exact"]
        ]
        if not sites:
            # Landing near a documented site, or a recalled ship touching down at
            # it, is not arriving there.
            near = any(row["match"].get("surface") for row in found["system"])
            return None, "not_at_site" if near else "no_documented_place"
        kind, subject = "site", sites[0]
        here = places = [subject]
        primary = subject["category"]
        headline = "Landed at a documented site"
        location_note = (
            "The Journal shows you landed within "
            f"{galactic_knowledge.SITE_ARRIVAL_KM:g} km of its documented position."
        )
    elif docked and found["station"] and not exact_station:
        return None, "ambiguous_station"
    elif exact_station:
        kind, subject = "station", exact_station[0]
        here = places = [subject]
        primary = subject["category"]
        headline = "Docked at a documented starport"
        location_note = subject["reason"]
    else:
        if docked:
            return None, "no_documented_place"
        here = [row for row in found["system"] if row["relation"] == "this_system"]
        others = [row for row in found["system"] if row["relation"] == "in_system"]
        if not found["system"]:
            return None, "no_documented_place"
        if not all(row["match"]["exact"] for row in found["system"]):
            return None, "ambiguous_system"
        subject = here[0] if here else others[0]
        kind = "system"
        places = others
        landmarks = [
            row for row in others if row["entity"]["kind"] in {"landmark", "settlement"}
        ]
        primary = "discoveries" if landmarks else subject["category"]
        headline = (
            "This system contains documented landmarks"
            if landmarks
            else "This system is documented in the Galactic Atlas"
        )
        location_note = (
            f"You arrived in {observation.get('system') or subject['entity']['name']}. "
            "Arriving in the system is not a visit to any place listed here."
        )
    moment = "arrival" if here else "nearby"
    if moment == "arrival" and not prefs.get("arrival_briefings", True):
        sites = [
            row
            for row in places
            if row is not subject
            and row["entity"]["kind"] in {"landmark", "settlement"}
        ]
        if kind != "system" or not sites:
            return None, "arrival_disabled"
        # Only the documented sites nearby: the system's own story is an arrival.
        moment, subject, places, primary = "nearby", sites[0], sites, "discoveries"
        headline = "Documented sites nearby"
    records = (history or {}).get("records") or {}
    observed_at = (event or {}).get("timestamp")
    if prefs.get("first_visit_only"):
        if moment == "arrival" and galactic_historian.visited_before(
            records.get(subject["entity"]["id"]), observed_at
        ):
            return None, "visited_before"
        if moment == "nearby":
            places = [
                row
                for row in places
                if not galactic_historian.visited_before(
                    records.get(row["entity"]["id"]), observed_at
                )
            ]
            if not places:
                return None, "visited_before"
            if subject not in places:
                subject = places[0]

    lore = bool(content.get(primary)) and not prefs["quiet_mode"]
    sections: JsonDict = {
        "summary": None,
        "significance": None,
        "history": [],
        "uncertainty": [],
        "associations": [],
        "places": [],
        "practical": [],
        "recommendation": None,
    }
    hidden = 0
    if lore:
        entity = knowledge.atlas_entry(subject["entity"]["id"])["entity"]
        sections["summary"] = subject["summary"]
        sections["significance"] = subject["significance"]
        sections["uncertainty"] = subject["uncertainty"][:2]
        hidden += subject["spoilers_hidden"]
        story, hidden_history = _claims(entity, "history", spoilers=spoilers)
        sections["history"] = story[:2]
        hidden += hidden_history
        sections["associations"] = [
            row for row in subject["associations"] if content.get(row["category"])
        ]
        sections["places"] = [
            {
                "entity": row["entity"],
                "summary": row["summary"],
                "significance": row["significance"],
                "note": row["reason"],
                "needs": row["match"]["needs"],
                # GKI-07: whether the Chronicle has the Commander at this place.
                "record": (records.get(row["entity"]["id"]) or {}).get(
                    "class", "unknown"
                ),
            }
            for row in places
            if row is not subject
        ]
        hidden += sum(row["spoilers_hidden"] for row in places if row is not subject)
    if content.get("practical") and not prefs["quiet_mode"]:
        sections["practical"] = [
            {"place": row["entity"], **activity}
            for row in places
            for activity in row["practical"]
        ]
    if content.get("recommendations") and relevance:
        relevant = [
            {"place": row["entity"], **relevance[row["entity"]["id"]]}
            for row in places
            if relevance.get(row["entity"]["id"], {}).get("state") == "relevant"
        ]
        if relevant:
            sections["recommendation"] = {
                "explanation": relevant[0]["explanation"],
                "reasons": [
                    {"place": item["place"], **reason}
                    for item in relevant
                    for reason in item["reasons"]
                ],
            }
    place_ids = [subject["entity"]["id"], *(row["entity"]["id"] for row in places)]
    extras: JsonDict = {
        "namesake": [],
        "founders": [],
        "faction": None,
        "mysteries": [],
        "chapters": [],
        "next": [],
    }
    if not prefs["quiet_mode"]:
        extras = galactic_historian.briefing_sections(
            knowledge,
            subject["entity"]["id"],
            prefs=prefs,
            history=history,
            event=event,
            origin_pos=(history or {}).get("origin_pos"),
            # Never the place itself or anything documented where you are.
            exclude={
                *place_ids,
                *(row["entity"]["id"] for row in found["system"] + found["station"]),
            },
        )
    # Suggestions and expedition chapters accompany a briefing; on their own they
    # would brief about a place whose history the Commander switched off.
    told = [
        key
        for key, value in extras.items()
        if value and key not in {"next", "chapters"}
    ]
    if (
        not lore
        and not sections["practical"]
        and not sections["recommendation"]
        and not told
    ):
        if prefs["quiet_mode"]:
            return None, "quiet_mode"
        return None, "content_disabled"
    if lore:
        category = primary
    elif sections["practical"]:
        category = "practical"
    elif sections["recommendation"]:
        category = "recommendations"
    elif extras["faction"]:
        category = "factions_politics"
    elif extras["chapters"]:
        category = "expedition_stories"
    elif extras["next"]:
        category = "suggestions"
    else:
        category = "discoveries"
    # Commander Memory records this very event before the briefing reads it, so
    # only evidence older than the observation says "you have been here before".
    prior = records.get(subject["entity"]["id"])
    if not galactic_historian.visited_before(prior, observed_at):
        prior = None
    actions: list[JsonDict] = [
        {"type": "open_atlas", "entity_id": subject["entity"]["id"]}
    ]
    actions += [
        {"type": "open_atlas", "entity_id": row["entity"]["id"]}
        for row in places
        if row is not subject
    ]
    actions.append({"type": "open_chronicle", "entity_id": subject["entity"]["id"]})
    for chapter in extras["chapters"][:1]:
        actions.append(
            {
                "type": "read_chapter",
                "expedition_id": chapter["expedition"]["id"],
                "narrative_id": chapter["narrative"]["id"],
                "chapter_id": chapter["chapter"]["id"],
            }
        )
    return (
        {
            "version": VERSION,
            "kind": kind,
            "moment": moment,
            "category": category,
            "category_label": CATEGORY_LABELS[category],
            "importance": importance(knowledge, place_ids),
            "subject": subject["entity"],
            # How the observation relates to the subject: a system notice never
            # reaches a site, and the UI says so from this, not from wording.
            "subject_match": subject["match"],
            "title": subject["entity"]["name"],
            "headline": headline,
            "location_note": location_note,
            **sections,
            **extras,
            # GKI-07: the Chronicle's earlier record of the subject, if any.
            "record": {
                key: prior.get(key) for key in ("class", "label", "first_at", "count")
            }
            if prior
            else None,
            "spoilers_hidden": hidden,
            "sources": subject["sources"],
            "actions": actions,
            "encounter_key": f"{kind}:{subject['entity']['id']}",
        },
        "eligible",
    )


class GalacticIntelligence:
    """Commander Context, documented-here relevance and the briefing lifecycle.

    Owns no Journal reader: the dispatcher hands it each event after the existing
    handlers have updated state (see :func:`register`).
    """

    def __init__(
        self,
        state: StateManager,
        session_factory: async_sessionmaker[AsyncSession] | None,
        vault: Any,
        *,
        profile_provider: Callable[[], str | None] | None = None,
        notify: Notify | None = None,
        knowledge_provider: Callable[[], KnowledgeIndex] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state = state
        self._session_factory = session_factory
        self.preferences = PreferenceStore(vault)
        self._profile_provider = profile_provider or (lambda: None)
        self._notify = notify
        self._knowledge_provider = knowledge_provider or galactic_knowledge.index
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._last_event_at: datetime | None = None
        self._latest_location_at: datetime | None = None
        # Location events already handled this run, whatever the outcome: a
        # re-delivery is never a new arrival, even if it was first seen while
        # automatic intelligence was off.  Bounded; restarts rely on the startup
        # replay marker and the persisted briefing keys.
        self._seen_events: deque[str] = deque(maxlen=SEEN_EVENTS)
        self._lock = asyncio.Lock()
        self.decisions: deque[JsonDict] = deque(maxlen=RECENT_DECISIONS)
        # GKI-07: Chronicle evidence for briefings, and Historian moments offered
        # to the future Notification Director (in memory, per commander).
        self._history_provider: HistoryProvider | None = None
        self.opportunities: deque[JsonDict] = deque(maxlen=MAX_OPPORTUNITIES)

    def set_notify(self, notify: Notify | None) -> None:
        self._notify = notify

    def set_history(self, provider: HistoryProvider | None) -> None:
        """Let the Commander Chronicle supply evidence to briefings (GKI-07)."""
        self._history_provider = provider

    async def _history(
        self,
        profile: str,
        knowledge: KnowledgeIndex,
        observation: JsonDict,
        event: JsonDict,
    ) -> JsonDict | None:
        if self._history_provider is None:
            return None
        try:
            return await self._history_provider(profile, knowledge, observation, event)
        except Exception:
            logger.exception("Chronicle evidence for a briefing is unavailable")
            return None

    def _offer(
        self,
        briefing: JsonDict,
        prefs: JsonDict,
        event: JsonDict,
        *,
        profile: str,
        eligible: bool,
        reason: str,
    ) -> str:
        """Keep the Historian moment a briefing represents, newest per subject."""
        from omnicovas.features import expeditions  # GKI-06 imports this module

        item = galactic_historian.opportunity(
            {
                **briefing,
                "source_event": event.get("event"),
                "observed_at": event.get("timestamp"),
            },
            profile_key=profile,
            event_key=event_key(profile, event),
            eligible=eligible,
            reason=reason,
            mode=expeditions.storytelling_mode(prefs),
            now=self._clock(),
        )
        self.opportunities = deque(
            (o for o in self.opportunities if o["dedup_key"] != item["dedup_key"]),
            maxlen=MAX_OPPORTUNITIES,
        )
        self.opportunities.appendleft(item)
        return str(item["opportunity_id"])

    def recent_opportunities(self) -> list[JsonDict]:
        """Historian moments for the current commander, newest first (GKI-07)."""
        profile = self.profile_key()
        return [o for o in self.opportunities if o["profile_key"] == profile]

    # Commander Context ------------------------------------------------------

    def profile_key(self) -> str:
        return self._profile_provider() or DEFAULT_PROFILE_KEY

    def note_activity(self, event: JsonDict) -> None:
        """Journal liveness: the newest event timestamp seen (cheap, every event)."""
        when = commander_context.parse_timestamp(event.get("timestamp"))
        if when is not None and (
            self._last_event_at is None or when > self._last_event_at
        ):
            self._last_event_at = when

    def knowledge(self) -> KnowledgeIndex | None:
        if galactic_knowledge.catalog()["state"] != "available":
            return None
        return self._knowledge_provider()

    def context(self, *, navigation: JsonDict | None = None) -> JsonDict:
        return commander_context.build(
            self._state,
            profile_key=self.profile_key(),
            last_journal_event_at=self._last_event_at,
            navigation=navigation,
            now=self._clock(),
        )

    def documented(self, context: JsonDict) -> JsonDict:
        """Documented-here results for the Commander's context (manual reading)."""
        knowledge = self.knowledge()
        if knowledge is None:
            return {"state": "unavailable", "system": [], "station": []}
        prefs = self.preferences.get(self.profile_key())
        found = documented_here(
            knowledge,
            commander_context.observation(context),
            spoilers=not prefs["spoiler_protection"],
        )
        return {"state": "available", **found}

    # Briefings --------------------------------------------------------------

    def _decide(
        self, outcome: str, reason: str, event: JsonDict, **extra: Any
    ) -> JsonDict:
        decision = {
            "outcome": outcome,
            "reason": reason,
            "event": event.get("event"),
            "timestamp": event.get("timestamp"),
            "decided_at": commander_context.iso(self._clock()),
            # Diagnostics are per commander: only the current one's are served,
            # and a forgotten commander's are dropped.
            "profile_key": self.profile_key(),
            **extra,
        }
        self.decisions.appendleft(decision)
        return decision

    async def _relevance(
        self, knowledge: KnowledgeIndex, observation: JsonDict
    ) -> dict[str, JsonDict]:
        if self._session_factory is None:
            return {}
        found = documented_here(knowledge, observation)
        place_ids = {
            row["entity"]["id"]
            for row in found["system"] + found["station"]
            if row["practical"]
        }
        if not place_ids:
            return {}
        builds = await engineering.list_build_plans(self._session_factory)
        goals = await engineering.list_goals(self._session_factory)
        live = self._state.public_snapshot()
        return {
            place_id: await galactic_atlas.relevance(
                self._session_factory,
                knowledge,
                place_id,
                builds=builds,
                goals=goals,
                live_state=live,
            )
            for place_id in sorted(place_ids)
        }

    async def observe(self, event: JsonDict) -> JsonDict:
        """Decide, persist and announce at most one briefing for a Journal event."""
        name = event.get("event")
        if name not in BRIEFING_EVENTS:
            return self._decide("ignored", "not_a_location_event", event)
        now = self._clock()
        observed_at = commander_context.parse_timestamp(event.get("timestamp"))
        if observed_at is None:
            return self._decide("suppressed", "no_timestamp", event)
        identity = event_key("", event)
        if identity in self._seen_events:
            return self._decide("suppressed", "duplicate_event", event)
        self._seen_events.append(identity)
        # Replayed events still advance the newest position seen, so a stale line
        # delivered after them cannot pass as an arrival.
        latest = self._latest_location_at
        if latest is None or observed_at > latest:
            self._latest_location_at = observed_at
        if journal_watcher.is_startup_replay():
            return self._decide("suppressed", "startup_replay", event)
        if latest is not None and observed_at < latest:
            return self._decide("suppressed", "out_of_order", event)
        if abs((now - observed_at).total_seconds()) > REPLAY_WINDOW_SECONDS:
            return self._decide("suppressed", "replay", event)
        if self._profile_provider() is None:
            return self._decide("suppressed", "commander_unknown", event)
        profile = self.profile_key()
        if await self.is_forgotten(profile):
            return self._decide("suppressed", "commander_forgotten", event)
        prefs = self.preferences.get(profile)
        enabled = prefs["enabled"] and prefs["frequency"] != "off"
        knowledge = self.knowledge()
        if knowledge is None:
            return self._decide(
                "suppressed", "knowledge_unavailable" if enabled else "disabled", event
            )
        observation = event_observation(event)
        docked = name == "Docked" or (
            name == "Location" and event.get("Docked") is True
        )
        landed = is_landed(event)
        # Engineering relevance reads the database; only an enabled briefing uses it.
        relevance = (
            await self._relevance(knowledge, observation)
            if enabled and prefs["content"]["recommendations"]
            else {}
        )
        # Chronicle evidence reads the database too: only for a briefing that can
        # be shown.  A disabled commander's moments are offered without it.
        history = (
            await self._history(profile, knowledge, observation, event)
            if enabled
            else None
        )
        briefing, reason = compose_briefing(
            knowledge,
            observation,
            prefs,
            docked=docked,
            relevance=relevance,
            landed=landed,
            history=history,
            event=event,
        )
        if name == "Location" and (docked or landed) and briefing is None:
            # Logging in docked somewhere undocumented still arrives in a system.
            briefing, reason = compose_briefing(
                knowledge,
                observation,
                prefs,
                docked=False,
                relevance=relevance,
                history=history,
                event=event,
            )
        if briefing is None:
            return self._decide("suppressed", reason if enabled else "disabled", event)
        composed: JsonDict = briefing

        def suppress(why: str) -> JsonDict:
            # A composed briefing is still a Historian moment the future
            # Notification Director may weigh; it is offered as not eligible.
            opportunity_id = self._offer(
                composed, prefs, event, profile=profile, eligible=False, reason=why
            )
            return self._decide("suppressed", why, event, opportunity_id=opportunity_id)

        if not enabled:
            return suppress("disabled")
        if prefs["frequency"] == "important" and briefing["importance"] != "major":
            return suppress("not_important")
        if self._session_factory is None:
            return suppress("no_persistence")
        key = event_key(profile, event)
        async with self._lock, self._session_factory() as db:
            if await db.scalar(
                select(GalacticIntelligenceBriefing.briefing_id).where(
                    GalacticIntelligenceBriefing.profile_key == profile,
                    GalacticIntelligenceBriefing.event_key == key,
                )
            ):
                return self._decide("suppressed", "duplicate_event", event)
            encounter = await db.scalar(
                select(GalacticIntelligenceEncounter).where(
                    GalacticIntelligenceEncounter.profile_key == profile,
                    GalacticIntelligenceEncounter.encounter_key
                    == briefing["encounter_key"],
                )
            )
            stamp = _utc_naive(now)
            if encounter is not None:
                if prefs["frequency"] in {"first", "important"}:
                    return suppress("already_briefed")
                since = (stamp - encounter.last_briefed_at).total_seconds()
                if since < COOLDOWN_SECONDS:
                    return suppress("cooldown")
                encounter.last_briefed_at = stamp
                encounter.briefing_count += 1
            else:
                db.add(
                    GalacticIntelligenceEncounter(
                        profile_key=profile,
                        encounter_key=briefing["encounter_key"],
                        first_briefed_at=stamp,
                        last_briefed_at=stamp,
                        briefing_count=1,
                    )
                )
            briefing_id = uuid4().hex
            briefing = {
                **briefing,
                "briefing_id": briefing_id,
                "observed_at": commander_context.iso(observed_at),
                "source_event": name,
                # GKI-08: the system this moment belongs to, so a presenter can
                # retire a held briefing once the commander has moved on.
                "location_key": location_key(observation),
                # GKI-08 closeout: the place the moment is about (a station only
                # for a docked station briefing), compared with the Commander
                # Context so a briefing never outlives the place it describes.
                "presence_key": presence_key(
                    observation, docked=briefing.get("kind") == "station"
                ),
                "created_at": commander_context.iso(now),
                "encounter_note": "First time OmniCOVAS has briefed you about this "
                "place."
                if encounter is None
                else "OmniCOVAS has briefed you about this place before.",
                # The same moment, offered to the future Notification Director.
                "opportunity_id": self._offer(
                    briefing,
                    prefs,
                    event,
                    profile=profile,
                    eligible=True,
                    reason="eligible",
                ),
            }
            db.add(
                GalacticIntelligenceBriefing(
                    briefing_id=briefing_id,
                    profile_key=profile,
                    event_key=key,
                    encounter_key=briefing["encounter_key"],
                    observed_at=_utc_naive(observed_at),
                    created_at=stamp,
                    dismissed_at=None,
                    payload_json=json.dumps(briefing, ensure_ascii=False),
                )
            )
            await db.flush()
            await self._compact(db, profile, stamp)
            await db.commit()
        decision = self._decide("briefed", "eligible", event, briefing_id=briefing_id)
        if self._notify is not None:
            try:
                await self._notify(
                    {
                        "event_type": BRIEFING_EVENT,
                        "timestamp": briefing["created_at"],
                        "payload": briefing,
                        "source": "galactic_intelligence",
                    }
                )
            except Exception:
                logger.exception("Galactic Intelligence briefing push failed")
        return decision

    @staticmethod
    async def _compact(db: AsyncSession, profile: str, now: datetime) -> None:
        """Bounded retention: 30 days or 200 briefings, 2,000 encounters."""
        await db.execute(
            delete(GalacticIntelligenceBriefing).where(
                GalacticIntelligenceBriefing.profile_key == profile,
                GalacticIntelligenceBriefing.created_at
                < now - timedelta(days=RETENTION_DAYS),
            )
        )
        for model, order, limit in (
            (
                GalacticIntelligenceBriefing,
                GalacticIntelligenceBriefing.created_at,
                MAX_BRIEFINGS_PER_PROFILE,
            ),
            (
                GalacticIntelligenceEncounter,
                GalacticIntelligenceEncounter.last_briefed_at,
                MAX_ENCOUNTERS_PER_PROFILE,
            ),
        ):
            stale = (
                select(order)
                .where(model.profile_key == profile)
                .order_by(order.desc())
                .offset(limit)
                .limit(1)
            )
            cutoff = await db.scalar(stale)
            if cutoff is not None:
                await db.execute(
                    delete(model).where(
                        model.profile_key == profile,
                        order <= cutoff,
                    )
                )

    # Commander lifecycle --------------------------------------------------

    async def is_forgotten(self, profile_key: str) -> bool:
        """Whether Commander Memory forgot this commander (a permanent tombstone)."""
        if self._session_factory is None or profile_key == DEFAULT_PROFILE_KEY:
            return False
        async with self._session_factory() as db:
            profile = await db.get(CommanderMemoryProfile, profile_key)
            return profile is not None and profile.forgotten_at is not None

    async def preferences_for(self, profile_key: str) -> JsonDict:
        """A forgotten commander has no preferences: only the built-in defaults."""
        if await self.is_forgotten(profile_key):
            return default_preferences()
        return self.preferences.get(profile_key)

    async def purge_profile(self, db: AsyncSession, profile_key: str) -> None:
        """Forget-workflow purge, inside Commander Memory's forget transaction.

        Removes the commander's briefings (with their dismissals and the event
        keys that deduplicate them) and encounters (first-briefed and cooldown
        state).  Other commanders' rows are untouched.
        """
        await db.execute(
            delete(GalacticIntelligenceBriefing).where(
                GalacticIntelligenceBriefing.profile_key == profile_key
            )
        )
        await db.execute(
            delete(GalacticIntelligenceEncounter).where(
                GalacticIntelligenceEncounter.profile_key == profile_key
            )
        )

    async def after_forget(self, profile_key: str) -> None:
        """After the forget commits: the commander's preference record, their
        in-memory decisions, and any briefing still on screen."""
        self.preferences.reset(profile_key)
        self.decisions = deque(
            (d for d in self.decisions if d.get("profile_key") != profile_key),
            maxlen=RECENT_DECISIONS,
        )
        self.opportunities = deque(
            (o for o in self.opportunities if o["profile_key"] != profile_key),
            maxlen=MAX_OPPORTUNITIES,
        )
        if self._notify is not None:
            try:
                await self._notify(
                    {
                        "event_type": CLEARED_EVENT,
                        "timestamp": commander_context.iso(self._clock()),
                        "payload": {"reason": "commander_forgotten"},
                        "source": "galactic_intelligence",
                    }
                )
            except Exception:
                logger.exception("Galactic Intelligence clear push failed")

    def recent_decisions(self) -> list[JsonDict]:
        profile = self.profile_key()
        return [d for d in self.decisions if d.get("profile_key") == profile]

    async def active_briefings(self) -> list[JsonDict]:
        """Undismissed briefings for the current commander, newest first."""
        if self._session_factory is None:
            return []
        since = _utc_naive(self._clock()) - timedelta(seconds=ACTIVE_BRIEFING_SECONDS)
        async with self._session_factory() as db:
            rows = await db.scalars(
                select(GalacticIntelligenceBriefing)
                .where(
                    GalacticIntelligenceBriefing.profile_key == self.profile_key(),
                    GalacticIntelligenceBriefing.dismissed_at.is_(None),
                    GalacticIntelligenceBriefing.created_at >= since,
                )
                .order_by(GalacticIntelligenceBriefing.created_at.desc())
                .limit(MAX_ACTIVE_BRIEFINGS)
            )
            return [json.loads(row.payload_json) for row in rows]

    async def dismiss(self, briefing_id: str) -> bool:
        """Dismiss one briefing for the current commander; settings are untouched."""
        if self._session_factory is None:
            return False
        async with self._lock, self._session_factory() as db:
            row = await db.get(GalacticIntelligenceBriefing, briefing_id)
            if row is None or row.profile_key != self.profile_key():
                return False
            if row.dismissed_at is None:
                row.dismissed_at = _utc_naive(self._clock())
                await db.commit()
            return True


def register(
    register_handler: Callable[[str, EventHandler], None],
    register_recorder: Callable[[RawRecorder], None],
    service: GalacticIntelligence,
) -> None:
    """Attach the service to the existing dispatcher.

    Register after the state handlers: the dispatcher runs handlers in order, so
    the briefing sees the state the Journal event produced.
    """

    async def note(event: JsonDict, raw_line: str) -> None:
        del raw_line
        service.note_activity(event)

    async def observe(event: JsonDict) -> None:
        await service.observe(event)

    register_recorder(note)
    for name in BRIEFING_EVENTS:
        register_handler(name, observe)
