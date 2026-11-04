"""Galactic Expeditions: journeys, stories and progress, planned offline (GKI-06).

Pure functions over the Galactic Knowledge index; :mod:`expedition_service` keeps
the Commander's expeditions and feeds them the Journal.

* **Stops** — one canonical stop per documented place (or star system), carrying
  every purpose it serves: a story chapter, an optional discovery, sightseeing, the
  material shortages it advances.  A stop is never removed because a purpose
  lapses; :func:`acquisition_relevance` says so instead.
* **Space** — straight-line distances between documented star positions only.  A
  distance is never a jump count, a route, a travel time or a promise that a ship,
  fuel or permit can get there (FSD boosts alone make any jump estimate unsafe),
  and a stop with no documented position says so rather than being placed by
  guesswork.
* **Stories** — narrative arcs from the knowledge packs, readable in any order,
  with spoilers marked.  :func:`opportunity` describes a moment a story could be
  told (``narrative-opportunity-v1``) for the future Notification Director; GKI-06
  never presents one by itself.
* **Progress** — :func:`stop_evidence` reads one Journal observation against a stop
  with the GKI-03 location rules: a docking request is not docking, arriving in a
  system is not visiting a station, body or site in it, a name alone never
  confirms a documented place, and a site placed approximately is never reached
  by evidence.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from datetime import datetime
from typing import Any

from omnicovas.features import commander_context, galactic_intelligence
from omnicovas.features.galactic_knowledge import ATLAS_RELATIONSHIPS, KnowledgeIndex

JsonDict = dict[str, Any]

VERSION = "galactic-expeditions-v1"
CONTRACT = "narrative-opportunity-v1"
HISTORY_VERSION = "expedition-history-v1"
ENTRY_POINTS = ("destination", "theme", "goal", "custom")
STATUSES = ("planning", "active", "completed", "archived")
MANUAL_STATES = ("planned", "skipped", "completed")
PURPOSE_TYPES = (
    "destination",
    "story",
    "discovery",
    "sightseeing",
    "acquisition",
    "custom",
)
STAGES = ("approach", "arrival", "continue", "recap")
STAGE_LABELS = {
    "approach": "Approach teaser",
    "arrival": "Arrival briefing",
    "continue": "Continue the story",
    "recap": "Journey recap",
}
# The Galactic Intelligence content control that governs expedition stories.
STORY_CATEGORY = "expedition_stories"
MODES: dict[str, JsonDict] = {
    "quiet": {
        "label": "Quiet",
        "stages": [],
        "description": "Stories wait in your expedition until you open them.",
    },
    "discoverer": {
        "label": "Discoverer",
        "stages": ["arrival", "recap"],
        "description": "Arrival briefings and the journey recap may be offered.",
    },
    "storyteller": {
        "label": "Storyteller",
        "stages": list(STAGES),
        "description": "Approach teasers, arrival briefings, the next chapter and "
        "the recap may be offered.",
    },
}
PROGRESS_EVENTS = (
    "FSDJump",
    "CarrierJump",
    "Location",
    "Docked",
    "DockingRequested",
    "DockingGranted",
    "SupercruiseExit",
    "ApproachBody",
    "ApproachSettlement",
    "Touchdown",
)
# Near a place, never at it: asking to dock is not docking, and ApproachSettlement
# carries the settlement's coordinates, not the ship's.
APPROACH_EVENTS = frozenset(
    {"DockingRequested", "DockingGranted", "ApproachSettlement"}
)
LEVEL_RANK = {"system": 1, "body": 2, "station": 3, "surface": 3}
STATUS_LABELS = {
    "planned": "Planned",
    "in_system": "In the system, not yet at the place",
    "approached": "Approached, not yet reached",
    "reached": "Reached",
    "completed": "Marked complete",
    "skipped": "Skipped",
}
# Journal Rank values: 8 is Elite in each career (Frontier Journal manual).
CAREERS = {
    "Combat": "Combat",
    "Trade": "Trade",
    "Explore": "Exploration",
    "Soldier": "Mercenary",
    "Exobiologist": "Exobiology",
    "CQC": "CQC",
}
ELITE_RANK = 8

NAME_MAX = 80
NOTE_MAX = 500
MAX_STOPS = 60
MAX_PURPOSES = 12
HISTORY_LIMIT = 300
EVIDENCE_KEYS = 12
DETOUR_MIN_LY = 20.0
DETOUR_FRACTION = 0.10
SUGGESTION_LIMIT = 12

SPATIAL_CAVEAT = (
    "Straight-line distances between documented star positions. They are not jump "
    "counts, routes or travel times, and they do not show whether a ship, its fuel "
    "or a permit can reach a place."
)
ORDER_EXPLANATION = (
    "Orders stops to shorten the total straight-line distance, keeping stops in the "
    "same system together. It ignores jumps, fuel, permits and FSD boosts, and stops "
    "without a documented position stay at the end in your order."
)


def _normal(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _ly(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def distance(a: list[float] | None, b: list[float] | None) -> float | None:
    """Straight-line light years between two star positions, or None if unknown."""
    if not a or not b:
        return None
    return math.dist(a, b)


# ── Purposes and stop identity ──────────────────────────────────────────────


def clean_text(value: Any, field: str, limit: int = 120) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be text")
    text = " ".join(value.split())
    if len(text) > limit:
        raise ValueError(f"{field} must be {limit} characters or fewer")
    return text


def normalize_purpose(raw: Any) -> JsonDict:
    """One validated purpose (API input); raises ``ValueError``."""
    if not isinstance(raw, dict):
        raise ValueError("a purpose must be an object")
    kind = raw.get("type")
    if kind not in PURPOSE_TYPES:
        raise ValueError(f"purpose type must be one of {', '.join(PURPOSE_TYPES)}")
    row: JsonDict = {"type": kind}
    if kind in {"story", "discovery"}:
        row["narrative"] = clean_text(raw.get("narrative"), "purpose.narrative", 64)
    if kind == "story":
        row["chapter"] = clean_text(raw.get("chapter"), "purpose.chapter", 64)
    if kind == "sightseeing" and raw.get("theme") is not None:
        row["theme"] = clean_text(raw.get("theme"), "purpose.theme", 64)
    if kind == "acquisition":
        materials = raw.get("materials")
        if not isinstance(materials, list) or not materials:
            raise ValueError("an acquisition purpose names the materials it serves")
        row["materials"] = [
            {
                "material_id": clean_text(m.get("material_id"), "material_id", 64),
                "name": clean_text(m.get("name"), "material name", 80),
            }
            for m in materials[:30]
            if isinstance(m, dict)
        ]
        row["activities"] = [
            clean_text(a, "activity", 96) for a in (raw.get("activities") or [])[:12]
        ]
        row["scope"] = clean_text(raw.get("scope") or "all", "purpose.scope", 64)
    return row


def _purpose_key(purpose: JsonDict) -> tuple[Any, ...]:
    return (
        purpose["type"],
        purpose.get("narrative"),
        purpose.get("chapter"),
        purpose.get("theme"),
        purpose.get("scope"),
    )


def merge_purposes(existing: list[JsonDict], added: list[JsonDict]) -> list[JsonDict]:
    """One stop, every reason: equal purposes merge, acquisitions pool materials."""
    merged = [dict(p) for p in existing]
    for purpose in added:
        same = next(
            (p for p in merged if _purpose_key(p) == _purpose_key(purpose)), None
        )
        if same is None:
            if len(merged) >= MAX_PURPOSES:
                raise ValueError(f"a stop keeps at most {MAX_PURPOSES} purposes")
            merged.append(dict(purpose))
            continue
        if purpose["type"] == "acquisition":
            ids = {m["material_id"] for m in same["materials"]}
            same["materials"] = [
                *same["materials"],
                *(m for m in purpose["materials"] if m["material_id"] not in ids),
            ]
            same["activities"] = list(
                dict.fromkeys([*same["activities"], *purpose["activities"]])
            )
    return merged


def stop_key(
    place_id: str | None, system_address: int | None, system_name: str | None
) -> str:
    """The canonical identity a stop is deduplicated by."""
    if place_id:
        return f"place:{place_id}"
    if system_address is not None:
        return f"system:{system_address}"
    return f"system-name:{_normal(system_name)}"


def resolve_target(
    knowledge: KnowledgeIndex | None,
    *,
    place_id: str | None = None,
    system: str | None = None,
) -> JsonDict:
    """A documented place, or a star system by name, as a canonical stop target.

    A system that is itself a documented place resolves to that place, so the same
    system is never two stops.  An undocumented system keeps the Commander's name and
    an unknown position.  Raises ``KeyError`` for an unknown place.
    """
    if place_id:
        place = knowledge.place(place_id) if knowledge is not None else None
        if place is None:
            raise KeyError(place_id)
        return {
            "place_id": place_id,
            "system_name": place["system"],
            "system_address": place["system_address"],
        }
    name = clean_text(system, "system", 128)
    if knowledge is not None:
        found = knowledge.system_position(system=name)
        for row in knowledge.places().values():
            if row["kind"] == "star_system" and (
                (
                    found is not None
                    and row["system_address"] is not None
                    and row["system_address"] == found["system_address"]
                )
                or _normal(row["system"]) == _normal(name)
            ):
                return {
                    "place_id": row["id"],
                    "system_name": row["system"],
                    "system_address": row["system_address"],
                }
        if found is not None:
            return {
                "place_id": None,
                "system_name": found["system"],
                "system_address": found["system_address"],
            }
    return {"place_id": None, "system_name": name, "system_address": None}


# ── Stops ───────────────────────────────────────────────────────────────────


def stop_status(manual_state: str, evidence: JsonDict) -> str:
    """What the stop is now: the Commander's word, then the Journal's evidence."""
    if manual_state == "completed":
        return "completed"
    if evidence.get("reached"):
        return "reached"
    if manual_state == "skipped":
        return "skipped"
    if evidence.get("approached"):
        return "approached"
    if evidence.get("in_system_at"):
        return "in_system"
    return "planned"


def _purpose_view(
    purpose: JsonDict,
    narratives: dict[str, JsonDict],
    themes: dict[str, JsonDict],
    knowledge: KnowledgeIndex | None = None,
) -> JsonDict:
    view = dict(purpose)
    # GKI-08: the method the commander chose in Materials, named for reading.
    if purpose["type"] == "acquisition" and knowledge is not None:
        view["methods"] = [
            {"id": a, "name": (knowledge.entity(a) or {}).get("name") or a}
            for a in purpose.get("activities") or []
            if knowledge.entity(a) is not None
        ]
    narrative = narratives.get(purpose.get("narrative") or "")
    if narrative is not None:
        view["narrative_title"] = narrative["title"]
        for position, chapter in enumerate(narrative["chapters"], start=1):
            if chapter["id"] == purpose.get("chapter"):
                view["chapter_title"] = chapter["title"]
                view["chapter_position"] = position
    theme = themes.get(purpose.get("theme") or "")
    if theme is not None:
        view["theme_label"] = theme["label"]
    return view


def describe_stop(
    knowledge: KnowledgeIndex | None,
    row: JsonDict,
    *,
    narratives: dict[str, JsonDict] | None = None,
    themes: dict[str, JsonDict] | None = None,
) -> JsonDict:
    """A stored stop with where it is, how it is confirmed and what it is for."""
    place = (
        knowledge.place(row["place_id"])
        if knowledge is not None and row.get("place_id")
        else None
    )
    if place is not None:
        location: JsonDict = {
            "system": place["system"],
            "system_address": place["system_address"],
            "body": place["body"],
            "station": place["station"],
            "surface": place["surface"],
            "star_pos": place["star_pos"],
            "basis": place["position_basis"],
            "precision": place["precision"],
            "reached_at": place["reached_at"],
            "confirmable": place["confirmable"],
            "identity": place["identity"],
        }
        name, kind = place["name"], place["kind"]
    else:
        found = (
            knowledge.system_position(
                system=row.get("system_name"), system_address=row.get("system_address")
            )
            if knowledge is not None
            else None
        )
        location = {
            "system": row.get("system_name"),
            "system_address": row.get("system_address"),
            "body": None,
            "station": None,
            "surface": None,
            "star_pos": (found or {}).get("star_pos"),
            "basis": (found or {}).get("basis"),
            "precision": "system_only",
            "reached_at": "system",
            # A system the Commander named is confirmed by arriving in it.
            "confirmable": True,
            "identity": "exact"
            if row.get("system_address") is not None
            else "name_only",
        }
        name = row.get("system_name") or row.get("place_id") or "Unknown system"
        kind = "unavailable" if row.get("place_id") else "star_system"
    evidence = row.get("evidence") or {}
    status = stop_status(row["manual_state"], evidence)
    if row.get("place_id") and place is None:
        note = "This place is no longer in the bundled knowledge."
    elif not location["confirmable"] and location["identity"] == "name_only":
        note = (
            "Known by name only, so the Journal cannot confirm arriving here: a name "
            "alone is not an identity. Mark it complete when you get there."
        )
    elif not location["confirmable"]:
        note = (
            "No Journal event can confirm this place: its position is not documented "
            "exactly. Mark it complete when you find it."
        )
    elif location["star_pos"] is None:
        note = "No documented position: distances to this stop are unknown."
    else:
        note = None
    return {
        "stop_id": row["stop_id"],
        "position": row["position"],
        "place_id": row.get("place_id"),
        "name": name,
        "kind": kind,
        "atlas": bool(place and place["atlas"]),
        "available": not (row.get("place_id") and place is None),
        "location": location,
        "purposes": [
            _purpose_view(p, narratives or {}, themes or {}, knowledge)
            for p in row.get("purposes") or []
        ],
        "manual_state": row["manual_state"],
        "manual_at": row.get("manual_at"),
        "note": row.get("note"),
        "evidence": {k: v for k, v in evidence.items() if k != "keys"},
        "status": status,
        "status_label": STATUS_LABELS[status],
        "location_note": note,
    }


# ── Journal progress ─────────────────────────────────────────────────────────


def progress_observation(
    event: JsonDict, current: JsonDict | None = None
) -> JsonDict | None:
    """Where one Journal event places the Commander, for expedition progress.

    Reuses the GKI-04 projection for jumps, locations and docking.  ``approach``
    marks an event that comes near a place without reaching it.  ``current`` is
    the system in state, for docking events that name no system.
    """
    name = event.get("event")
    if name not in PROGRESS_EVENTS:
        return None
    approach = name in APPROACH_EVENTS
    if name in {"FSDJump", "CarrierJump", "Location", "Docked"}:
        seen = galactic_intelligence.event_observation(event)
        if name == "Location":
            for key, field in (("latitude", "Latitude"), ("longitude", "Longitude")):
                if isinstance(event.get(field), int | float):
                    seen[key] = float(event[field])
    else:
        seen = {
            "system": event.get("StarSystem"),
            "system_address": event.get("SystemAddress"),
        }
        if seen["system_address"] is None and current:
            seen["system"] = seen["system"] or current.get("system")
            seen["system_address"] = current.get("system_address")
        if name in {"DockingRequested", "DockingGranted"}:
            seen.update(
                market_id=event.get("MarketID"), station=event.get("StationName")
            )
        elif name == "ApproachSettlement":
            seen.update(
                body=event.get("BodyName"),
                body_id=event.get("BodyID"),
                market_id=event.get("MarketID"),
                station=event.get("Name"),
            )
        elif name == "SupercruiseExit" and event.get("BodyType") == "Station":
            # Dropping out at a station is arriving near it, not docking.
            seen["station"] = event.get("Body")
            approach = True
        else:
            seen.update(body=event.get("Body"), body_id=event.get("BodyID"))
            if name == "Touchdown":
                for key, field in (
                    ("latitude", "Latitude"),
                    ("longitude", "Longitude"),
                ):
                    if isinstance(event.get(field), int | float):
                        seen[key] = float(event[field])
                seen["player_controlled"] = galactic_intelligence.player_controlled(
                    event
                )
    observation = {k: v for k, v in seen.items() if v is not None}
    if not observation.get("system") and observation.get("system_address") is None:
        return None
    return {"event": name, "approach": approach, "observation": observation}


def stop_evidence(
    stop: JsonDict, seen: JsonDict, matches: dict[str, JsonDict]
) -> JsonDict | None:
    """How far one observation reaches toward a stop, or None if it does not touch it.

    ``matches`` is the knowledge index's :meth:`match_location` for the observation,
    keyed by place id.  A documented place is reached only by an exact identifier at
    the level it needs; a system the Commander named is reached by arriving in it.
    """
    observation = seen["observation"]
    if stop.get("place_id"):
        match = matches.get(stop["place_id"])
        if match is None:
            return None
        reached = bool(match["reached"] and match["exact"] and not seen["approach"])
        found: JsonDict = {
            "level": match["level"],
            "exact": match["exact"],
            "reached": reached,
            # Near this place only when the observation matched it beyond its
            # system: a docking request at one station approaches no other.
            "approached": not reached and match["level"] != "system",
            "needs": match["needs"],
            "basis": match["basis"],
        }
        surface = match.get("surface")
        if surface and surface["state"] == "nearby" and match["exact"]:
            # A landing near a site, kept so the stop can say how near.
            found["landed_km"] = surface["distance_km"]
        return found
    address = stop.get("system_address")
    if address is not None and observation.get("system_address") is not None:
        if address != observation["system_address"]:
            return None
        exact, basis = True, ["system_exact"]
    elif stop.get("system_name") and _normal(observation.get("system")) == _normal(
        stop["system_name"]
    ):
        exact, basis = False, ["system_name"]
    else:
        return None
    return {
        "level": "system",
        "exact": exact,
        "reached": True,
        "approached": False,
        "needs": "system",
        "basis": basis,
    }


def merge_evidence(
    before: JsonDict, found: JsonDict, *, event: str, at: str, key: str, replayed: bool
) -> tuple[JsonDict, list[str]]:
    """Fold one finding into a stop's evidence; returns it and what is new.

    Evidence only ever deepens: a later system arrival never undoes a docking.
    """
    if key in (before.get("keys") or []):
        return before, []
    after = dict(before)
    after["keys"] = [*(before.get("keys") or []), key][-EVIDENCE_KEYS:]
    after["last_at"] = at
    changes: list[str] = []
    if not after.get("in_system_at"):
        after["in_system_at"] = at
        after["in_system_event"] = event
        changes.append("in_system")
    if LEVEL_RANK[found["level"]] > LEVEL_RANK.get(after.get("level") or "", 0):
        after["level"] = found["level"]
    if found["approached"] and not after.get("approached") and not after.get("reached"):
        after.update(approached=True, approached_at=at, approach_event=event)
        changes.append("approached")
    landed = found.get("landed_km")
    if landed is not None and (
        after.get("landed_km") is None or landed < after["landed_km"]
    ):
        after["landed_km"] = landed
    if found["reached"] and not after.get("reached"):
        after.update(
            reached=True,
            reached_at=at,
            reached_event=event,
            reached_basis=found["basis"],
            exact=found["exact"],
            replayed=replayed,
        )
        changes.append("reached")
    return after, changes


def history_entry(
    kind: str,
    at: datetime | str | None,
    *,
    stop: JsonDict | None = None,
    source: str = "commander",
    **detail: Any,
) -> JsonDict:
    """One Chronicle-ready record of something that happened on the journey."""
    entry: JsonDict = {
        "version": HISTORY_VERSION,
        "type": kind,
        "at": at if isinstance(at, str) or at is None else commander_context.iso(at),
        "source": source,
    }
    if stop is not None:
        entry["stop"] = {
            "stop_id": stop["stop_id"],
            "place_id": stop.get("place_id"),
            "name": stop.get("name") or stop.get("system_name"),
            "system": (stop.get("location") or {}).get("system")
            or stop.get("system_name"),
        }
    entry.update({k: v for k, v in detail.items() if v is not None})
    return entry


# ── Space ───────────────────────────────────────────────────────────────────


def origin_from(
    snapshot: JsonDict, knowledge: KnowledgeIndex | None
) -> JsonDict | None:
    """The Commander's last known star system as a planning origin, if any."""
    context = snapshot.get("local_system_context")
    if not isinstance(context, dict):
        return None
    system, address = context.get("star_system"), context.get("system_address")
    if not system and address is None:
        return None
    position = context.get("star_pos")
    basis: str | None = "journal"
    if not position and knowledge is not None:
        found = knowledge.system_position(system=system, system_address=address)
        position, basis = (found or {}).get("star_pos"), (found or {}).get("basis")
    return {
        "system": system,
        "system_address": address,
        "star_pos": list(position) if position else None,
        "basis": basis if position else None,
        "observed_at": context.get("event_timestamp"),
    }


def _point(stop: JsonDict) -> JsonDict:
    return {
        "stop_id": stop["stop_id"],
        "name": stop["name"],
        "system": stop["location"]["system"],
    }


def _system_of(stop: JsonDict) -> str:
    location = stop["location"]
    if location.get("system_address") is not None:
        return f"address:{location['system_address']}"
    return f"name:{_normal(location.get('system'))}"


def spatial(stops: list[JsonDict], origin: JsonDict | None) -> JsonDict:
    """Straight-line legs through the stops in order, from the origin when known."""
    legs: list[JsonDict] = []
    for previous, current in zip(stops, stops[1:], strict=False):
        between = distance(
            previous["location"]["star_pos"], current["location"]["star_pos"]
        )
        legs.append(
            {
                "from": _point(previous),
                "to": _point(current),
                "distance_ly": _ly(between),
                "same_system": _system_of(previous) == _system_of(current),
                "known": between is not None,
            }
        )
    remaining = [
        s for s in stops if s["status"] in {"planned", "in_system", "approached"}
    ]
    here = (origin or {}).get("star_pos")
    remaining_ly: float | None = None
    if here and remaining and all(s["location"]["star_pos"] for s in remaining):
        path = [here, *(s["location"]["star_pos"] for s in remaining)]
        remaining_ly = sum(
            math.dist(a, b) for a, b in zip(path, path[1:], strict=False)
        )
    next_stop = remaining[0] if remaining else None
    known = [leg["distance_ly"] for leg in legs if leg["known"]]
    return {
        "origin": origin,
        "legs": legs,
        "planned_ly": _ly(sum(known)) if known else None,
        "unknown_legs": sum(1 for leg in legs if not leg["known"]),
        "stops_without_position": [
            s["stop_id"] for s in stops if not s["location"]["star_pos"]
        ],
        "remaining_ly": _ly(remaining_ly),
        "next": {
            **_point(next_stop),
            "distance_ly": _ly(
                distance(here, next_stop["location"]["star_pos"]) if here else None
            ),
        }
        if next_stop
        else None,
        "caveat": SPATIAL_CAVEAT,
    }


def _path_length(points: list[list[float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


def suggest_order(stops: list[JsonDict], origin: JsonDict | None) -> JsonDict:
    """A shorter straight-line order: nearest neighbour, then 2-opt.

    Stops in one system move together in the Commander's relative order; the
    route starts at the origin when it is known, otherwise at the current first
    stop.  Only a suggestion: nothing is reordered until the Commander applies it.
    """
    groups: dict[str, list[JsonDict]] = {}
    unplaced: list[JsonDict] = []
    for stop in stops:
        if stop["location"]["star_pos"]:
            groups.setdefault(_system_of(stop), []).append(stop)
        else:
            unplaced.append(stop)
    nodes = list(groups.values())
    start = (origin or {}).get("star_pos")
    fixed = 0 if start else 1
    if not nodes:
        order: list[list[JsonDict]] = []
    else:
        position = start or nodes[0][0]["location"]["star_pos"]
        pending = nodes if start else nodes[1:]
        order = [] if start else [nodes[0]]
        while pending:
            nearest = min(
                pending,
                key=lambda group: math.dist(position, group[0]["location"]["star_pos"]),
            )
            pending = [g for g in pending if g is not nearest]
            order.append(nearest)
            position = nearest[0]["location"]["star_pos"]
        # 2-opt on the open path; the start (origin or first stop) never moves.
        prefix = [start] if start else []

        def path(sequence: list[list[JsonDict]]) -> float:
            return _path_length(
                prefix + [g[0]["location"]["star_pos"] for g in sequence]
            )

        best, improved = path(order), True
        while improved:
            improved = False
            for i in range(fixed, len(order) - 1):
                for j in range(i + 1, len(order)):
                    trial = order[:i] + order[i : j + 1][::-1] + order[j + 1 :]
                    trial_length = path(trial)
                    if trial_length + 1e-9 < best:
                        order, best, improved = trial, trial_length, True
    suggested = [stop for group in order for stop in group] + unplaced

    def length(sequence: list[JsonDict]) -> float | None:
        points = [
            s["location"]["star_pos"] for s in sequence if s["location"]["star_pos"]
        ]
        if start:
            points = [start, *points]
        return _path_length(points) if len(points) > 1 else None

    current_ly, suggested_ly = length(stops), length(suggested)
    ids = [s["stop_id"] for s in suggested]
    return {
        "stop_ids": ids,
        "changed": ids != [s["stop_id"] for s in stops],
        "current_ly": _ly(current_ly),
        "suggested_ly": _ly(suggested_ly),
        "saves_ly": _ly(current_ly - suggested_ly)
        if current_ly is not None and suggested_ly is not None
        else None,
        "from_origin": bool(start),
        "unplaced": [s["stop_id"] for s in unplaced],
        "explanation": ORDER_EXPLANATION,
    }


def story_order(stops: list[JsonDict], narrative: JsonDict | None) -> JsonDict | None:
    """The story's chapter order: chapters first, then discoveries, then the rest."""
    if narrative is None:
        return None
    rank: dict[str, int] = {}
    for position, chapter in enumerate(narrative["chapters"]):
        rank.setdefault(chapter["place"], position)
    for position, item in enumerate(narrative["discoveries"]):
        rank.setdefault(item["place"], len(narrative["chapters"]) + position)
    ordered = sorted(
        stops,
        key=lambda s: (rank.get(s.get("place_id") or "", len(rank)), s["position"]),
    )
    ids = [s["stop_id"] for s in ordered]
    return {"stop_ids": ids, "changed": ids != [s["stop_id"] for s in stops]}


# ── Finding stops ────────────────────────────────────────────────────────────


KIND_REASONS = {
    "station": "A documented starport",
    "settlement": "A documented settlement",
    "landmark": "A documented landmark",
    "body": "A documented world",
    "star_system": "A documented star system",
}
CONTEXT_REASONS = {
    "guardian_site": "A Guardian site",
    "surface_site": "A documented surface site",
    "human_space": "A documented site in human space",
}


def theme_places(
    knowledge: KnowledgeIndex,
    theme: JsonDict,
    *,
    acquisition: list[JsonDict] | None = None,
) -> dict[str, list[str]]:
    """Places a theme selects, each with why: the union of its selectors."""
    select = theme["select"]
    places = knowledge.places()
    picked: dict[str, list[str]] = {}

    def add(place_id: str, reason: str) -> None:
        if place_id in places and reason not in picked.setdefault(place_id, []):
            picked[place_id].append(reason)

    for place_id, place in places.items():
        if place["atlas"] and place["kind"] in select.get("kinds", []):
            add(place_id, KIND_REASONS.get(place["kind"], "A documented place"))
        if place["landmark_type"] and place["landmark_type"] in select.get(
            "landmark_types", []
        ):
            add(place_id, f"A documented {place['landmark_type'].replace('_', ' ')}")
    contexts = set(select.get("activity_contexts", []))
    if contexts:
        for place_id in places:
            for row in knowledge.related(place_id):
                if row["type"] != "located_at" or row["direction"] != "incoming":
                    continue
                activity = knowledge.entity(row["entity"]["id"]) or {}
                context = (activity.get("attributes") or {}).get("context")
                if context in contexts:
                    add(
                        place_id, CONTEXT_REASONS.get(str(context), "A documented site")
                    )
    for subject in select.get("related_to", []):
        name = (knowledge.entity(subject) or {}).get("name", subject)
        for row in knowledge.related(subject):
            if row["type"] in ATLAS_RELATIONSHIPS:
                add(row["entity"]["id"], f"Tied to {name}")
    for narrative_id in select.get("narratives", []):
        story = knowledge.narrative(narrative_id)
        for item in [*story["chapters"], *story["discoveries"]]:
            add(item["place"], f"Part of {story['title']}")
    for place_id in select.get("places", []):
        add(place_id, theme["label"])
    if select.get("acquisition"):
        for row in acquisition or []:
            names = ", ".join(m["name"] for m in row["materials"][:4])
            add(row["id"], f"Advances your shortages: {names}")
    return picked


def candidate(
    knowledge: KnowledgeIndex,
    place_id: str,
    reasons: list[str],
    *,
    origin: JsonDict | None,
    stop_keys: set[str],
) -> JsonDict:
    """One place offered for an expedition, with where it is and why."""
    place = knowledge.places()[place_id]
    here = (origin or {}).get("star_pos")
    return {
        "place": {
            k: place[k]
            for k in (
                "id",
                "name",
                "kind",
                "atlas",
                "system",
                "precision",
                "reached_at",
            )
        },
        "confirmable": place["confirmable"],
        "star_pos": place["star_pos"],
        "distance_ly": _ly(distance(here, place["star_pos"])) if here else None,
        "why": list(reasons),
        "requirements": len(knowledge.requirements_for(place_id)),
        "in_expedition": stop_key(place_id, None, None) in stop_keys,
    }


def along_the_way(
    knowledge: KnowledgeIndex,
    stops: list[JsonDict],
    origin: JsonDict | None,
    *,
    selected: dict[str, list[str]],
    limit: int = SUGGESTION_LIMIT,
) -> JsonDict:
    """Documented places close to the straight line between consecutive stops.

    A place qualifies when going through it adds at most ``max(20 ly, 10% of the
    leg)`` of straight-line distance; places with no documented position never
    qualify.  ``selected`` holds the places that fit the expedition's theme or
    story, kept apart from places that are merely nearby.
    """
    points: list[JsonDict] = []
    if origin and origin.get("star_pos"):
        points.append(
            {
                "name": "Your last known position",
                "system": origin["system"],
                "star_pos": origin["star_pos"],
            }
        )
    unchecked = 0
    for stop in stops:
        if stop["status"] in {"completed", "skipped"}:
            continue
        if stop["location"]["star_pos"]:
            points.append(
                {
                    "name": stop["name"],
                    "system": stop["location"]["system"],
                    "star_pos": stop["location"]["star_pos"],
                }
            )
        else:
            unchecked += 1
    legs = list(zip(points, points[1:], strict=False))
    taken = {s.get("place_id") for s in stops if s.get("place_id")}
    # The star system or body a stop is already in is not a further stop.
    systems = {_normal(s["location"].get("system")) for s in stops}
    found: list[JsonDict] = []
    for place_id, place in knowledge.places().items():
        if place_id in taken or not place["star_pos"]:
            continue
        if (
            place["kind"] in {"star_system", "body"}
            and _normal(place["system"]) in systems
        ):
            continue
        best: tuple[float, JsonDict, JsonDict] | None = None
        for a, b in legs:
            leg = math.dist(a["star_pos"], b["star_pos"])
            detour = (
                math.dist(a["star_pos"], place["star_pos"])
                + math.dist(place["star_pos"], b["star_pos"])
                - leg
            )
            if detour <= max(DETOUR_MIN_LY, DETOUR_FRACTION * leg) and (
                best is None or detour < best[0]
            ):
                best = (max(detour, 0.0), a, b)
        if best is None:
            continue
        detour, a, b = best
        same = place["system"] in {a["system"], b["system"]}
        found.append(
            {
                "place": {
                    k: place[k]
                    for k in ("id", "name", "kind", "atlas", "system", "precision")
                },
                "detour_ly": _ly(detour),
                "same_system": bool(same),
                "leg": {"from": a["name"], "to": b["name"]},
                "why": selected.get(place_id)
                or (["Also in this system"] if same else ["Close to your route"]),
                "thematic": place_id in selected,
                "atlas": place["atlas"],
            }
        )
    found.sort(
        key=lambda r: (
            not r["same_system"],
            not r["atlas"],
            r["detour_ly"],
            r["place"]["name"],
        )
    )
    return {
        "thematic": [r for r in found if r["thematic"]][:limit],
        "geographic": [r for r in found if not r["thematic"]][:limit],
        "legs_checked": len(legs),
        "stops_without_position": unchecked,
        "rule": f"Adds at most {DETOUR_MIN_LY:g} ly, or {DETOUR_FRACTION:.0%} of the "
        "leg, to the straight-line distance between two stops.",
        "caveat": SPATIAL_CAVEAT,
    }


def goal_candidates(
    knowledge: KnowledgeIndex, intelligence: JsonDict | None, *, origin: JsonDict | None
) -> JsonDict:
    """GKI-05's acquisition destinations for an expedition, consolidated by system.

    Conditional sources with no fixed place, such as High Grade Emissions, are
    listed apart: they are conditions to watch for, never stops.
    """
    if not intelligence or intelligence.get("state") != "available":
        return {
            "state": (intelligence or {}).get("state", "unavailable"),
            "destinations": [],
            "systems": [],
            "conditional": [],
            "inventory_state": (intelligence or {}).get("inventory_state"),
        }
    here = (origin or {}).get("star_pos")
    places = knowledge.places()
    destinations = []
    for row in intelligence.get("destinations") or []:
        place = places.get(row["id"])
        if place is None:
            continue
        destinations.append(
            {
                "place": {
                    k: place[k]
                    for k in ("id", "name", "kind", "atlas", "system", "precision")
                },
                "materials": row["materials"],
                "activities": row["activities"],
                "distance_ly": _ly(distance(here, place["star_pos"])) if here else None,
                "why": [
                    "Advances "
                    + ", ".join(m["name"] for m in row["materials"][:5])
                    + ("" if len(row["materials"]) <= 5 else ", and more")
                ],
            }
        )
    systems: dict[str, JsonDict] = {}
    for row in destinations:
        entry = systems.setdefault(
            row["place"]["system"] or row["place"]["name"],
            {"system": row["place"]["system"], "places": [], "materials": []},
        )
        entry["places"].append(row["place"]["id"])
        known = {m["material_id"] for m in entry["materials"]}
        entry["materials"] += [
            m for m in row["materials"] if m["material_id"] not in known
        ]
    conditional = []
    for activity in intelligence.get("activities") or []:
        if not activity["plannable"] or activity["places"]:
            continue
        rules = ((knowledge.entity(activity["id"]) or {}).get("attributes") or {}).get(
            "hge_rules"
        )
        conditional.append(
            {
                "id": activity["id"],
                "name": activity["name"],
                "summary": activity["summary"],
                "materials": activity["materials"],
                # High Grade Emissions depend on system state; other methods can
                # be done in many places.  Neither is ever a stop.
                "kind": "conditional" if rules else "anywhere",
                "note": "Depends on system conditions that change, so it is a "
                "condition to watch for, never a stop."
                if rules
                else "Not tied to one documented place, so it is not added as a stop.",
            }
        )
    conditional.sort(key=lambda row: (row["kind"] != "conditional", row["name"]))
    return {
        "state": "available",
        "scope": intelligence.get("scope"),
        "inventory_state": intelligence.get("inventory_state"),
        "destinations": destinations,
        "systems": sorted(
            systems.values(), key=lambda s: (-len(s["materials"]), str(s["system"]))
        ),
        "conditional": conditional,
        "high_grade_emissions": intelligence.get("high_grade_emissions"),
        "caveats": intelligence.get("caveats") or [],
    }


def acquisition_relevance(purpose: JsonDict, intelligence: JsonDict | None) -> JsonDict:
    """Whether an acquisition stop still serves current shortages.  Never removes it."""
    if not intelligence or intelligence.get("state") == "knowledge_unavailable":
        return {
            "state": "unknown",
            "explanation": "Acquisition knowledge is unavailable in this build.",
        }
    if intelligence.get("inventory_state") != "verified_local":
        return {
            "state": "unknown",
            "explanation": "Your Materials record is incomplete, so OmniCOVAS cannot "
            "tell whether these are still short.",
        }
    short = set(intelligence.get("short_materials") or [])
    still = [m for m in purpose["materials"] if m["material_id"] in short]
    if len(still) == len(purpose["materials"]):
        state, text = (
            "relevant",
            "Still short of " + ", ".join(m["name"] for m in still),
        )
    elif still:
        state = "partly"
        text = "Still short of " + ", ".join(m["name"] for m in still) + "; the rest "
        text += "are covered now."
    else:
        state = "no_longer_needed"
        text = (
            "You are no longer short of anything this stop was for. It stays in your "
            "expedition until you remove it."
        )
    return {"state": state, "still_short": still, "explanation": text + "."}


# ── Preflight ───────────────────────────────────────────────────────────────


def rank_hint(ranks: JsonDict | None) -> str:
    if not ranks:
        return "No Rank event has been observed yet."
    elite = [
        label for key, label in CAREERS.items() if (ranks.get(key) or 0) >= ELITE_RANK
    ]
    if not elite:
        return "Your last observed Rank event shows no Elite rank."
    return "Your last observed Rank event shows Elite in " + ", ".join(elite) + "."


def _assess(requirement: JsonDict, ranks: JsonDict | None) -> JsonDict:
    row = {
        k: requirement[k]
        for k in ("id", "kind", "text", "evidence", "sources", "uncertain")
    }
    if requirement["kind"] == "permit":
        row.update(
            status="unknown",
            status_label="Permit not confirmed",
            note="The Journal does not record permits, so OmniCOVAS cannot confirm "
            "whether you hold this one.",
            hint=rank_hint(ranks),
        )
    elif requirement["kind"] == "equipment":
        row.update(
            status="unverified",
            status_label="Not checked",
            note="OmniCOVAS cannot confirm this from your loadout.",
        )
    else:
        row.update(status="advice", status_label="Good to know", note=None)
    return row


def ship_checks(snapshot: JsonDict, role_fit: JsonDict) -> JsonDict:
    """The observed ship as preflight context, from the existing readiness evidence."""
    exploration: JsonDict = next(
        (r for r in role_fit.get("roles", []) if r["role"] == "exploration"), {}
    )
    observed = bool(role_fit.get("loadout_observed"))
    if "fuel_scoop" in exploration.get("fitted", []):
        scoop, label = "fitted", "Fitted"
    elif observed:
        scoop, label = "not_seen", "Not seen in the loadout OmniCOVAS observed"
    else:
        scoop, label = "unknown", "Unknown: no loadout observed"
    jump = snapshot.get("jump_range_ly")
    return {
        "ship_type": snapshot.get("current_ship_type"),
        "loadout_observed": observed,
        "fuel_scoop": {"status": scoop, "label": label},
        "max_jump_range_ly": round(float(jump), 2)
        if isinstance(jump, int | float) and jump > 0
        else None,
        "caveat": role_fit.get("caveat"),
    }


def preflight(
    knowledge: KnowledgeIndex | None,
    stops: list[JsonDict],
    ship: JsonDict,
    ranks: JsonDict | None,
) -> JsonDict:
    """What is documented as needed for each stop, and what can be confirmed.

    A requirement documented for a star system applies to every stop in it.  A
    permit is never confirmed (the Journal does not record permits) and equipment
    is never reported missing from an absent module reading.
    """
    systems: dict[str, list[JsonDict]] = {}
    if knowledge is not None:
        for place in knowledge.places().values():
            if place["kind"] == "star_system":
                systems.setdefault(_normal(place["system"]), []).append(place)
    rows = []
    for stop in stops:
        requirements: list[JsonDict] = []
        if knowledge is not None:
            if stop.get("place_id") and stop["available"]:
                requirements += [
                    _assess(r, ranks)
                    for r in knowledge.requirements_for(stop["place_id"])
                ]
            for system in systems.get(_normal(stop["location"]["system"]), []):
                if system["id"] == stop.get("place_id"):
                    continue
                requirements += [
                    {**_assess(r, ranks), "applies_from": system["name"]}
                    for r in knowledge.requirements_for(system["id"])
                ]
        rows.append(
            {
                "stop_id": stop["stop_id"],
                "name": stop["name"],
                "status": stop["status"],
                "confirmable": stop["location"]["confirmable"],
                "requirements": requirements,
            }
        )
    counts = Counter(r["status"] for row in rows for r in row["requirements"])
    return {
        "stops": rows,
        "ship": ship,
        "summary": {
            "permits_unconfirmed": counts.get("unknown", 0),
            "equipment_unchecked": counts.get("unverified", 0),
            "advice": counts.get("advice", 0),
            "manual_stops": sum(1 for row in rows if not row["confirmable"]),
        },
        "caveat": "Preflight lists what is documented. OmniCOVAS cannot see permits, "
        "and reads equipment only from a loadout it has observed.",
    }


# ── Stories ──────────────────────────────────────────────────────────────────


def storytelling_mode(prefs: JsonDict) -> JsonDict:
    """Quiet, Discoverer or Storyteller, from the Galactic Intelligence preferences."""
    if not prefs["enabled"] or prefs["frequency"] == "off" or prefs["quiet_mode"]:
        mode = "quiet"
    elif prefs["frequency"] == "all":
        mode = "storyteller"
    else:
        mode = "discoverer"
    stories = bool(prefs["content"].get(STORY_CATEGORY, True))
    return {
        "mode": mode,
        "label": MODES[mode]["label"],
        "description": MODES[mode]["description"],
        "stages": list(MODES[mode]["stages"]) if stories else [],
        "stories_enabled": stories,
        "spoiler_protection": bool(prefs["spoiler_protection"]),
        "automatic_presentation": False,
        "note": "OmniCOVAS does not present expedition stories on its own yet. The "
        "mode decides what a future in-game presenter may offer; reading in the "
        "expedition always works.",
    }


def story_state(
    narrative: JsonDict, stops: list[JsonDict], read: list[str], *, spoilers: bool
) -> JsonDict:
    """Where each chapter stands: read, reached, skipped or not in the expedition.

    Chapters are readable in any order; ``complete`` means every chapter was read
    or its stop reached, completed or skipped, which earns the conclusion and the
    recap stage.
    """
    by_place = {s["place_id"]: s for s in stops if s.get("place_id")}
    chapters = []
    for position, chapter in enumerate(narrative["chapters"], start=1):
        stop = by_place.get(chapter["place"])
        chapters.append(
            {
                "id": chapter["id"],
                "position": position,
                "title": chapter["title"],
                "teaser": chapter["teaser"],
                "place_id": chapter["place"],
                "place_name": chapter["place_name"],
                "stop_id": stop["stop_id"] if stop else None,
                "stop_status": stop["status"] if stop else "not_in_expedition",
                "read": chapter["id"] in read,
                "spoiler": bool(chapter.get("spoiler")),
                "spoiler_hidden": bool(chapter.get("spoiler")) and not spoilers,
            }
        )
    resolved = {"reached", "completed", "skipped"}
    complete = all(c["read"] or c["stop_status"] in resolved for c in chapters)
    following = next(
        (c for c in chapters if not c["read"] and c["stop_status"] not in resolved),
        None,
    )
    return {
        "id": narrative["id"],
        "title": narrative["title"],
        "summary": narrative["summary"],
        "teaser": narrative["teaser"],
        "chapters": chapters,
        "discoveries": [
            {
                "place_id": item["place"],
                "place_name": item["place_name"],
                "title": item.get("title"),
                "stop_id": by_place[item["place"]]["stop_id"]
                if item["place"] in by_place
                else None,
            }
            for item in narrative["discoveries"]
        ],
        "read": sum(1 for c in chapters if c["read"]),
        "count": len(chapters),
        "complete": complete,
        "next": following,
    }


def reader_view(narrative: JsonDict, *, spoilers: bool) -> JsonDict:
    """A story for reading: spoiler passages withheld unless spoilers are shown."""

    def view(item: JsonDict) -> JsonDict:
        hidden = bool(item.get("spoiler")) and not spoilers
        out = {**item, "spoiler_hidden": hidden}
        if hidden:
            out["text"] = None
            out["connections"] = []
        return out

    return {
        **narrative,
        "introduction": view(narrative["introduction"]),
        "chapters": [view(c) for c in narrative["chapters"]],
        "discoveries": [view(d) for d in narrative["discoveries"]],
        "conclusion": view(narrative["conclusion"]),
        "spoilers_shown": spoilers,
    }


def _passage(item: JsonDict, *, kind: str, hidden: bool) -> JsonDict:
    return {
        "kind": kind,
        "title": item.get("title"),
        "text": None if hidden else item["text"],
        "spoiler": bool(item.get("spoiler")),
        "spoiler_hidden": hidden,
        "uncertain": bool(item.get("uncertain")),
    }


def opportunity(
    stage: str,
    *,
    profile_key: str,
    expedition: JsonDict,
    stop: JsonDict | None,
    narrative: JsonDict,
    chapter: JsonDict | None,
    trigger: JsonDict,
    mode: JsonDict,
    now: datetime,
    following: JsonDict | None = None,
) -> JsonDict:
    """A moment a story could be told (``narrative-opportunity-v1``).

    Built for the future Notification Director: everything a presenter needs to
    decide and to show, and nothing presented here.  ``presentation.automatic`` is
    always false in GKI-06.  The same stage at the same stop has the same
    ``dedup_key``, so it is never offered twice.
    """
    chapter_id = (chapter or {}).get("id")
    dedup = "|".join(
        [
            profile_key,
            expedition["id"],
            (stop or {}).get("stop_id") or "-",
            stage,
            chapter_id or "-",
        ]
    )
    if stage == "recap":
        item, kind = narrative["conclusion"], "conclusion"
    elif chapter is not None:
        item, kind = chapter, "chapter"
    else:
        item, kind = narrative["introduction"], "introduction"
    spoiler = bool(item.get("spoiler"))
    hidden = spoiler and mode["spoiler_protection"]
    if not mode["stories_enabled"]:
        eligible, reason = False, "stories_disabled"
    elif mode["mode"] == "quiet":
        eligible, reason = False, "quiet_mode"
    elif stage not in mode["stages"]:
        eligible, reason = False, "stage_not_in_mode"
    else:
        eligible, reason = True, "eligible"
    reached = stage in {"arrival", "recap"}
    count = len(narrative["chapters"])
    position = next(
        (n for n, c in enumerate(narrative["chapters"], 1) if c["id"] == chapter_id),
        None,
    )
    actions: list[JsonDict] = [
        {
            "type": "open_expedition",
            "expedition_id": expedition["id"],
            "stop_id": (stop or {}).get("stop_id"),
        }
    ]
    if chapter_id:
        actions.append(
            {
                "type": "read_chapter",
                "expedition_id": expedition["id"],
                "narrative_id": narrative["id"],
                "chapter_id": chapter_id,
            }
        )
    if stop is not None and stop.get("place_id"):
        actions.append({"type": "open_atlas", "entity_id": stop["place_id"]})
    actions.append({"type": "dismiss"})
    return {
        "contract": CONTRACT,
        "version": VERSION,
        "opportunity_id": hashlib.sha256(dedup.encode("utf-8")).hexdigest()[:24],
        "dedup_key": dedup,
        "profile_key": profile_key,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "created_at": commander_context.iso(now),
        "trigger": trigger,
        "evidence_requirement": {
            "needs": (stop or {}).get("location", {}).get("reached_at"),
            "met": reached,
            "explanation": "The Journal showed you at the place."
            if stage == "arrival"
            else "Arriving in the system or near the place is not a visit."
            if stage == "approach"
            else "Offered after leaving a stop you reached."
            if stage == "continue"
            else "Every chapter was read, skipped or reached.",
        },
        "expedition": {"id": expedition["id"], "name": expedition["name"]},
        "stop": {
            "stop_id": stop["stop_id"],
            "place_id": stop.get("place_id"),
            "name": stop["name"],
            "system": stop["location"]["system"],
        }
        if stop
        else None,
        "narrative": {"id": narrative["id"], "title": narrative["title"]},
        "chapter": {
            "id": chapter_id,
            "title": chapter["title"],
            "position": position,
            "count": count,
        }
        if chapter
        else None,
        "teaser": (chapter or {}).get("teaser") or narrative["teaser"],
        "passage": _passage(item, kind=kind, hidden=hidden),
        "related": [
            {"entity": link["subject"], "text": link["text"]}
            for link in (chapter or {}).get("connections") or []
        ],
        "sources": list(item.get("sources") or []),
        "evidence": item.get("evidence"),
        "next": following,
        "actions": actions,
        "preferences": {
            "mode": mode["mode"],
            "category": STORY_CATEGORY,
            "spoiler_protection": mode["spoiler_protection"],
        },
        "presentation": {
            "owner": "notification_director",
            "automatic": False,
            "eligible": eligible,
            "reason": reason,
        },
    }


# ── Recap ───────────────────────────────────────────────────────────────────


def recap(
    expedition: JsonDict,
    stops: list[JsonDict],
    history: list[JsonDict],
    *,
    narrative: JsonDict | None,
    story: JsonDict | None,
    spoilers: bool,
) -> JsonDict:
    """The journey so far, from the expedition's own structured history."""
    counts = Counter(stop["status"] for stop in stops)

    def when(stop: JsonDict) -> str:
        evidence = stop["evidence"]
        return str(evidence.get("reached_at") or stop.get("manual_at") or "")

    done = sorted(
        (s for s in stops if s["status"] in {"reached", "completed"}), key=when
    )
    points = [s["location"]["star_pos"] for s in done if s["location"]["star_pos"]]
    conclusion = None
    if narrative is not None:
        item = narrative["conclusion"]
        hidden = bool(item.get("spoiler")) and not spoilers
        conclusion = {
            **_passage(item, kind="conclusion", hidden=hidden),
            "earned": bool(story and story["complete"]),
            "sources": list(item.get("sources") or []),
        }
    return {
        "expedition": expedition,
        "counts": {status: counts.get(status, 0) for status in STATUS_LABELS},
        "stops": len(stops),
        "reached_in_order": [
            {
                "stop_id": s["stop_id"],
                "name": s["name"],
                "system": s["location"]["system"],
                "how": "journal" if s["evidence"].get("reached") else "marked",
                "at": when(s) or None,
            }
            for s in done
        ],
        "straight_line_ly": _ly(_path_length(points)) if len(points) > 1 else None,
        "chapters_read": story["read"] if story else 0,
        "chapters": story["count"] if story else 0,
        "timeline": history,
        "conclusion": conclusion,
        "caveat": "Reached means a Journal event showed you at the place; marked "
        "means you said so. Distances are straight lines between the places, in "
        "the order you reached them.",
    }
