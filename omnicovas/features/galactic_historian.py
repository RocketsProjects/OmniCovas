"""Living Galactic Historian (GKI-07): what a place's history means to the Commander.

Pure, deterministic functions over the Galactic Knowledge index and the evidence
the services gather.  The Historian owns no Journal reader, persistence or
presentation: GKI-04 Galactic Intelligence calls it to enrich its briefings, and
the Commander Chronicle and the API call it to answer five questions:

1. Where is the Commander?  GKI-04 Commander Context, unchanged.
2. What is historically significant here?  :func:`subject_view`.
3. Which people, factions and events are connected?  :func:`connections`.
4. Has the Commander actually been here?  :func:`record`, from evidence.
5. What could they explore next?  :func:`explore_next` and :func:`stories_here`.

Evidence classes (:func:`record`):

* ``observed`` — the Journal showed the Commander at the place, by an exact
  identifier at the level the place needs.
* ``commander_confirmed`` — the Commander said so; OmniCOVAS did not observe it.
* ``suggested`` — OmniCOVAS suggests going there, and says why.
* ``unknown`` — no record either way.  Missing history never means "not visited".

A namesake is shown only from a documented ``named_after`` relationship, never
from similar names, and historical control is never presented as current control.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import Any

from omnicovas.features import commander_context
from omnicovas.features.galactic_knowledge import PLACE_KINDS, KnowledgeIndex

JsonDict = dict[str, Any]

VERSION = "galactic-historian-v1"
# The GKI-06 contract, extended with Historian stages (see :func:`opportunity`).
CONTRACT = "narrative-opportunity-v1"
EVIDENCE = ("observed", "commander_confirmed", "suggested", "unknown")
EVIDENCE_LABELS = {
    "observed": "Observed",
    "commander_confirmed": "Commander-confirmed",
    "suggested": "Suggested",
    "unknown": "Unknown",
}
EVIDENCE_TEXT = {
    "observed": "The Journal showed you here.",
    "commander_confirmed": "You confirmed this visit. OmniCOVAS did not observe it.",
    "suggested": "Suggested by OmniCOVAS. This is not a record of a visit.",
    "unknown": "No record either way. OmniCOVAS only knows what it saw in your "
    "Journal while it was running.",
}
STAGES = {
    "historical_arrival": "Historical arrival",
    "nearby_site": "Nearby, not visited",
}
NEXT_LIMIT = 8
BRIEFING_NEXT = 3
TOPIC_ORDER = (
    "history",
    "uncertainty",
    "interpretation",
    "theory",
    "community_report",
    "identity",
    "service",
    "gameplay",
)
# How each relationship reads from the subject's side.
LABELS: dict[tuple[str, str], str] = {
    ("located_in", "outgoing"): "Located in",
    ("located_in", "incoming"): "Contains",
    ("named_after", "outgoing"): "Named after",
    ("named_after", "incoming"): "Namesake of",
    ("founded_by", "outgoing"): "Founded by",
    ("founded_by", "incoming"): "Founded",
    ("historically_controlled_by", "outgoing"): "Historically controlled by",
    ("historically_controlled_by", "incoming"): "Historically controlled",
    ("occurred_at", "outgoing"): "Took place at",
    ("occurred_at", "incoming"): "Events here",
    ("participated_in", "outgoing"): "Took part in",
    ("participated_in", "incoming"): "Participants",
    ("member_of", "outgoing"): "Member of",
    ("member_of", "incoming"): "Members",
    ("discovered_by", "outgoing"): "Discovered by",
    ("discovered_by", "incoming"): "Credited with",
    ("part_of_expedition", "outgoing"): "Part of the expedition",
    ("part_of_expedition", "incoming"): "Places and people of the expedition",
    ("related_to_mystery", "outgoing"): "Connected mystery",
    ("related_to_mystery", "incoming"): "Connected to this mystery",
    ("associated_with", "outgoing"): "Associated with",
    ("associated_with", "incoming"): "Associated with",
    ("related_to", "outgoing"): "Related to",
    ("related_to", "incoming"): "Related to",
}
# Named groups a Historian reads first, then everything else by kind.
SPECIAL = (
    ("namesake", "named_after", "outgoing"),
    ("founders", "founded_by", "outgoing"),
    ("founded", "founded_by", "incoming"),
    ("faction_history", "historically_controlled_by", "outgoing"),
    ("expeditions", "part_of_expedition", "outgoing"),
    ("mysteries", "related_to_mystery", "outgoing"),
)
KIND_GROUPS = {
    "person": "people",
    "organization": "organizations",
    "event": "events",
    "discovery": "events",
    "mystery": "mysteries",
    "vessel": "places",
    **{kind: "places" for kind in PLACE_KINDS},
}
FACTION_NOTE = (
    "Historical records are not current control. Current control comes only from "
    "your own Journal."
)


def distance(a: list[float] | None, b: list[float] | None) -> float | None:
    """Straight-line light years between two star positions, or None if unknown."""
    if not a or not b:
        return None
    return math.dist(a, b)


# ── Connections ──────────────────────────────────────────────────────────────


def connections(knowledge: KnowledgeIndex, entity_id: str) -> JsonDict:
    """Every Atlas relationship of a subject, in the groups a Historian reads.

    ``namesake`` holds only documented ``named_after`` relationships: two names
    that happen to match are never a namesake.  ``faction_history`` is always
    historical, never the place's current controller.
    """
    groups: JsonDict = {name: [] for name, _, _ in SPECIAL}
    groups.update(people=[], organizations=[], events=[], places=[])
    for row in knowledge.related(entity_id):
        other = row["entity"]["id"]
        kind = knowledge.brief(other)["kind"]
        label = LABELS.get((row["type"], row["direction"]))
        if label is None:
            continue  # acquisition mechanics belong to the practical view
        item: JsonDict = {
            "relation": row["type"],
            "direction": row["direction"],
            "label": label,
            "entity": {"id": other, "kind": kind, "name": row["entity"]["name"]},
            "certainty": row.get("certainty") or "documented",
            "sources": list(row.get("sources") or []),
        }
        for key in ("note", "role", "period"):
            if row.get(key):
                item[key] = row[key]
        if row["type"] == "historically_controlled_by":
            item["historical_only"] = True
        special = next(
            (
                name
                for name, relation, direction in SPECIAL
                if row["type"] == relation and row["direction"] == direction
            ),
            None,
        )
        group = special or KIND_GROUPS.get(kind)
        if group is not None:
            groups[group].append(item)
    return groups


def current_faction(event: JsonDict | None) -> JsonDict | None:
    """The controlling faction a Journal event reports, labelled as the Journal's.

    Only ``Docked`` (``StationFaction``) and jump or location events
    (``SystemFaction``) carry one.  It is the Commander's own observation of the
    present, kept apart from any documented history.
    """
    if not event:
        return None
    name = event.get("event")
    field, scope = (
        ("StationFaction", "station")
        if name in {"Docked", "Location"} and event.get("StationFaction")
        else ("SystemFaction", "system")
    )
    raw = event.get(field)
    faction = raw.get("Name") if isinstance(raw, dict) else None
    if not isinstance(faction, str) or not faction.strip():
        return None
    return {
        "name": faction.strip()[:128],
        "scope": scope,
        "source": "journal",
        "source_event": name,
        "observed_at": event.get("timestamp"),
    }


# ── What is significant ──────────────────────────────────────────────────────


def subject_view(
    knowledge: KnowledgeIndex, entity_id: str, *, spoilers: bool
) -> JsonDict:
    """A subject as a Historian tells it: record, readings and theories apart.

    Spoiler claims are counted, not shown, unless ``spoilers``.  Practical
    opportunities (material gathering) are a separate list, so a farming site's
    history and its practical role never blur.
    """
    entry = knowledge.atlas_entry(entity_id)
    entity = entry["entity"]
    attributes = entity.get("attributes") or {}
    hidden = 0
    significance = attributes.get("significance")
    if attributes.get("significance_spoiler") and not spoilers:
        significance, hidden = None, 1
    topics: dict[str, list[JsonDict]] = {topic: [] for topic in TOPIC_ORDER}
    for claim in entity.get("claims") or []:
        topic = claim.get("topic") or "identity"
        if claim.get("spoiler") and not spoilers:
            hidden += 1
            continue
        topics.setdefault(topic, []).append(
            {
                "id": claim["id"],
                "text": claim["text"],
                "evidence": claim["evidence"],
                "sources": list(claim["sources"]),
            }
        )
    return {
        "entity": {"id": entity["id"], "kind": entity["kind"], "name": entity["name"]},
        "category": entry["category"],
        "summary": entity["summary"],
        "significance": significance,
        "period": attributes.get("period"),
        "aliases": list(entity.get("aliases") or []),
        "topics": {topic: rows for topic, rows in topics.items() if rows},
        "spoilers_hidden": hidden,
        "practical": [
            {
                "activity": {"id": row["id"], "name": row["name"]},
                "summary": row["summary"],
                "materials": [m["name"] for m in row["materials"]],
            }
            for row in entry["practical"]
        ],
        "location": entry["location"],
        "match_support": entry["match_support"],
        "sources": [
            {"id": s["id"], "name": s["name"], "url": s["url"]}
            for s in entry["sources"][:8]
        ],
    }


# ── Has the Commander been here ──────────────────────────────────────────────


def tally(observed: list[JsonDict]) -> tuple[int, bool]:
    """How many Journal observations of a place are on record, and if that is a floor.

    Commander Memory, the Chronicle and expedition progress overlap without any
    one holding the rest: a docking on an expedition is in both Memory and the
    expedition, while a docking made with Memory paused is only in the expedition
    and a docked login only in the Chronicle.  So an occasion is identified the
    way the Journal does, by its event and timestamp (``occasions``), and the
    sources are united on that.  A source counting more than it itemizes cannot
    be correlated: those occasions may or may not be ones already counted, so the
    result is then the least the evidence shows, and says so.
    """
    union: set[tuple[Any, ...]] = set()
    sources: list[tuple[int, int]] = []
    for item in observed:
        own = {tuple(occasion) for occasion in item.get("occasions") or ()}
        union |= own
        sources.append((len(own), max(0, int(item.get("count") or 1) - len(own))))
    least = max([len(union), *(held + spare for held, spare in sources)])
    return least, least < len(union) + sum(spare for _, spare in sources)


# Events that prove the Commander arrived.  ``Location`` is not one: it reports where
# a login found them, so it can show a stay but never a new arrival.
ARRIVAL_EVENTS = frozenset(
    {"Docked", "FSDJump", "CarrierJump", "Touchdown", "ApproachBody"}
)


def visit_tally(
    observed: list[JsonDict], departures: list[str] | None = None
) -> tuple[int | None, bool]:
    """Distinct supported visits to a place, and whether that is only a floor.

    A visit is an observed arrival, or a stay seen with no arrival to explain it:
    the first login found there, or a login after an observed departure.  A login
    during an open stay re-observes that stay, however long the gap, because an
    unobserved gap proves no departure.  Separate arrivals stay separate.

    A count the sources cannot itemize keeps its unit only if it counted arrivals
    (``unit`` is ``arrivals``).  Otherwise it says nothing about visits: the result
    is the itemized visits as a floor, or None when there are none, and the caller
    words the record as observations instead of inventing a number.
    """
    occasions: set[tuple[str, str]] = set()
    arrivals_by_source: list[tuple[int, int]] = []
    unknown = False
    for item in observed:
        own = {tuple(o) for o in item.get("occasions") or ()}
        occasions |= own
        spare = max(0, int(item.get("count") or 1) - len(own))
        if spare and item.get("unit") == "arrivals":
            held = sum(1 for event, _ in own if event in ARRIVAL_EVENTS)
            arrivals_by_source.append((held, spare))
        elif spare:
            unknown = True
    # Ties sort a departure last, so an arrival in the same second opens first.
    timeline = sorted(
        [(at, 0 if event in ARRIVAL_EVENTS else 1) for event, at in occasions]
        + [(at, 2) for at in departures or ()]
    )
    visits = 0
    in_stay = False
    for _, kind in timeline:
        if kind == 2:
            in_stay = False
        elif kind == 0 or not in_stay:
            visits, in_stay = visits + 1, True
    arrivals = sum(1 for event, _ in occasions if event in ARRIVAL_EVENTS)
    least = visits
    floor = False
    for held, spare in arrivals_by_source:
        # Its uncounted arrivals may or may not be ones already held elsewhere.
        least = max(least, held + spare)
        floor = floor or arrivals > held or visits > arrivals
    if unknown:
        return (least, True) if least else (None, True)
    return least, floor


def record(
    place: JsonDict,
    *,
    observed: list[JsonDict],
    commander: list[JsonDict],
    presence: JsonDict | None = None,
    approached: JsonDict | None = None,
    departures: list[str] | None = None,
) -> JsonDict:
    """A place's Chronicle state from its evidence, strongest first.

    ``observed`` items come from the Journal at the level the place needs
    (Commander Memory, the Chronicle or expedition progress); ``commander`` items
    are the Commander's own word.  ``presence`` (in the system) and ``approached``
    are kept as context and never make a place visited.
    """
    observed = sorted(observed, key=lambda item: str(item["at"]))
    count, count_is_minimum = tally(observed)
    visits, visits_is_minimum = visit_tally(observed, departures)
    if observed:
        state = "observed"
    elif commander:
        state = "commander_confirmed"
    else:
        state = "unknown"
    landed_km = (approached or {}).get("distance_km")
    if state == "unknown" and landed_km is not None:
        note = (
            f"You landed about {landed_km:.1f} km from {place['name']}. That is "
            "nearby, not a visit to it: if you went there, you can confirm it."
        )
    elif state == "unknown" and presence and place["reached_at"] != "system":
        note = (
            "You were in its system. Being in a system is not a visit to "
            f"{place['name']}."
        )
    elif state == "unknown" and not place["confirmable"]:
        note = (
            "Its position is not documented exactly, so the Journal cannot confirm a "
            "visit. You can confirm it yourself."
        )
    else:
        note = EVIDENCE_TEXT[state]
    return {
        "class": state,
        "label": EVIDENCE_LABELS[state],
        "note": note,
        "first_at": observed[0]["at"] if observed else None,
        "last_at": max(str(i.get("last_at") or i["at"]) for i in observed)
        if observed
        else None,
        # Journal observations of the place, and the visits they support: a login
        # during a stay is another observation, not another visit.
        "count": count,
        "count_is_minimum": count_is_minimum,
        "visits": visits,
        "visits_is_minimum": visits_is_minimum,
        "observations": [
            {
                key: item[key]
                for key in ("at", "how", "source", "event", "count", "last_at")
                if item.get(key) is not None
            }
            for item in observed[-5:]
        ],
        "confirmation": commander[0] if commander else None,
        "in_system": presence,
        "approached": approached,
        "reached_at": place["reached_at"],
        "confirmable": place["confirmable"],
    }


def visited_before(record_row: JsonDict | None, observed_at: str | None) -> bool:
    """Whether a record shows the Commander here before this observation.

    Commander Memory records the same Journal event before Galactic Intelligence
    reads it, so only evidence strictly earlier than ``observed_at`` counts.
    """
    if not record_row or record_row["class"] != "observed":
        return False
    first = record_row.get("first_at")
    return bool(first and (observed_at is None or str(first) < str(observed_at)))


# ── What to explore next ─────────────────────────────────────────────────────


def explore_next(
    knowledge: KnowledgeIndex,
    subject_ids: list[str],
    *,
    records: dict[str, JsonDict],
    origin_pos: list[float] | None = None,
    exclude: set[str] | None = None,
    limit: int = NEXT_LIMIT,
) -> list[JsonDict]:
    """Connected documented places, unvisited first, then nearest connection.

    Only places with a documented identity are offered; a person, an event or a
    mystery is never a destination, whatever system it is associated with.  A
    place whose position is not exact can be planned, but says that only the
    Commander can confirm reaching it.
    """
    skip = set(exclude or ()) | set(subject_ids)
    found: dict[str, JsonDict] = {}
    for subject_id in subject_ids:
        for row in knowledge.related_destinations(subject_id):
            place = knowledge.place(row["id"])
            if place is None or row["id"] in skip:
                continue
            previous = found.get(row["id"])
            if previous is not None and previous["hops"] <= row["hops"]:
                continue
            state = (records.get(row["id"]) or {}).get("class") or "unknown"
            if state == "unknown":
                state = "suggested"
            ly = distance(origin_pos, place["star_pos"])
            origin = knowledge.brief(subject_id)
            through = row.get("through")
            found[row["id"]] = {
                "place": {
                    "id": place["id"],
                    "name": place["name"],
                    "kind": place["kind"],
                },
                "system": place["system"],
                "via": row["via"],
                "via_label": LABELS.get((row["via"], "outgoing"), "Related to"),
                "hops": row["hops"],
                "from": origin,
                "through": through,
                "reason": (
                    f"Connected to {origin['name']} through {through['name']}"
                    if through
                    else f"Connected to {origin['name']}"
                ),
                "distance_ly": round(ly, 1) if ly is not None else None,
                "precision": place["precision"],
                "confirmable": place["confirmable"],
                "record": {"class": state, "label": EVIDENCE_LABELS[state]},
                "plannable": True,
                "plan_note": None
                if place["confirmable"]
                else "Its position is not documented exactly; only you can confirm "
                "reaching it.",
            }
    rows = list(found.values())
    rows.sort(
        key=lambda r: (
            r["record"]["class"] == "observed",
            r["hops"],
            r["distance_ly"] is None,
            r["distance_ly"] or 0.0,
            r["place"]["name"],
        )
    )
    return rows[:limit]


def stories_here(
    knowledge: KnowledgeIndex, place_ids: list[str], *, spoilers: bool
) -> list[JsonDict]:
    """Story chapters set at these places (GKI-06 narratives), titles only."""
    wanted = set(place_ids)
    rows: list[JsonDict] = []
    for summary in knowledge.narratives():
        if not wanted & set(summary["places"]):
            continue
        narrative = knowledge.narrative(summary["id"])
        count = len(narrative["chapters"])
        for position, chapter in enumerate(narrative["chapters"], start=1):
            if chapter["place"] not in wanted:
                continue
            hidden = bool(chapter.get("spoiler")) and not spoilers
            rows.append(
                {
                    "narrative": {"id": narrative["id"], "title": narrative["title"]},
                    "chapter": {
                        "id": chapter["id"],
                        "title": chapter["title"],
                        "position": position,
                        "count": count,
                        "teaser": chapter["teaser"],
                        "spoiler_hidden": hidden,
                    },
                    "place_id": chapter["place"],
                }
            )
    return rows


# ── Briefings (GKI-04) ───────────────────────────────────────────────────────


def briefing_sections(
    knowledge: KnowledgeIndex,
    subject_id: str,
    *,
    prefs: JsonDict,
    history: JsonDict | None,
    event: JsonDict | None,
    origin_pos: list[float] | None,
    exclude: set[str],
) -> JsonDict:
    """What a Historian adds to a GKI-04 briefing about ``subject_id``.

    Each section obeys the content control that governs it, and a section with
    nothing documented is left empty rather than filled with guesses.
    """
    content = prefs["content"]
    links = connections(knowledge, subject_id)
    records = (history or {}).get("records") or {}
    sections: JsonDict = {
        "namesake": [],
        "founders": [],
        "faction": None,
        "mysteries": [],
        "chapters": [],
        "next": [],
    }
    # A namesake is part of a place's own history; founders are historical figures.
    if content.get("station_history"):
        sections["namesake"] = links["namesake"]
    if content.get("figures_events"):
        sections["founders"] = links["founders"]
    if content.get("factions_politics") and links["faction_history"]:
        sections["faction"] = {
            "historical": links["faction_history"],
            "current": current_faction(event),
            "note": FACTION_NOTE,
        }
    if content.get("discoveries"):
        sections["mysteries"] = links["mysteries"]
    if content.get("expedition_stories"):
        sections["chapters"] = list((history or {}).get("chapters") or [])
    if content.get("suggestions"):
        sections["next"] = explore_next(
            knowledge,
            [subject_id],
            records=records,
            origin_pos=origin_pos,
            exclude=exclude,
            limit=BRIEFING_NEXT,
        )
    return sections


def opportunity(
    briefing: JsonDict,
    *,
    profile_key: str,
    event_key: str,
    eligible: bool,
    reason: str,
    mode: JsonDict,
    now: datetime,
) -> JsonDict:
    """A Historian moment in the ``narrative-opportunity-v1`` shape.

    The GKI-06 contract with a Historian extension: stages ``historical_arrival``
    and ``nearby_site``, ``source: historian`` and ``subject``.  ``expedition``,
    ``stop`` and ``narrative`` are null unless an expedition chapter is set at
    the place.  Built for the future Notification Director; nothing is presented
    from here, and ``presentation.automatic`` is always false.

    ``presentation.surfaces`` keeps three things apart.  The content controls
    only shape what the moment says.  ``desktop`` is whether the commander's
    opt-in preferences let the existing desktop briefing stack show it (the same
    as ``eligible``).  ``in_game_overlay`` is never eligible: the overlay shows
    only critical ship alerts, and history is never one.
    """
    stage = (
        "nearby_site" if briefing.get("moment") == "nearby" else "historical_arrival"
    )
    subject = briefing["subject"]
    dedup = "|".join([profile_key, "historian", stage, subject["id"]])
    chapter = (briefing.get("chapters") or [None])[0]
    match = briefing.get("subject_match") or {}
    text = briefing.get("significance") or briefing.get("summary")
    return {
        "contract": CONTRACT,
        "version": VERSION,
        "source": "historian",
        "opportunity_id": hashlib.sha256(f"{dedup}|{event_key}".encode()).hexdigest()[
            :24
        ],
        "dedup_key": dedup,
        "profile_key": profile_key,
        "stage": stage,
        "stage_label": STAGES[stage],
        "created_at": commander_context.iso(now),
        "trigger": {
            "event": briefing.get("source_event"),
            "observed_at": briefing.get("observed_at"),
            "level": match.get("level"),
            "exact": match.get("exact"),
            "basis": match.get("basis"),
            "replayed": False,
            "source": "journal",
        },
        "evidence_requirement": {
            "needs": match.get("needs"),
            "met": stage == "historical_arrival" and bool(match.get("reached")),
            "explanation": "The Journal showed you at the place."
            if stage == "historical_arrival" and match.get("reached")
            else "Arriving in a system is not a visit to the places documented in it.",
        },
        "subject": subject,
        "expedition": chapter["expedition"] if chapter else None,
        "stop": {"stop_id": chapter["stop_id"], "place_id": subject["id"]}
        if chapter
        else None,
        "narrative": chapter["narrative"] if chapter else None,
        "chapter": chapter["chapter"] if chapter else None,
        "teaser": briefing.get("headline"),
        "passage": {
            "kind": "significance",
            "title": subject["name"],
            "text": text,
            "spoiler": False,
            "spoiler_hidden": bool(briefing.get("spoilers_hidden")),
            "uncertain": bool(briefing.get("uncertainty")),
        },
        "related": [
            {"entity": row["entity"], "text": row["label"]}
            for row in (briefing.get("associations") or [])[:5]
        ],
        "sources": [s["id"] for s in briefing.get("sources") or []],
        "evidence": None,
        "next": (briefing.get("next") or [None])[0],
        "actions": [
            {"type": "open_atlas", "entity_id": subject["id"]},
            {"type": "open_chronicle", "entity_id": subject["id"]},
            {"type": "dismiss"},
        ],
        "preferences": {
            "mode": mode["mode"],
            "category": briefing.get("category"),
            "spoiler_protection": mode["spoiler_protection"],
        },
        "presentation": {
            "owner": "notification_director",
            "automatic": False,
            "eligible": eligible,
            "reason": reason,
            "surfaces": {
                "desktop": {"eligible": eligible, "reason": reason},
                "in_game_overlay": {
                    "eligible": False,
                    "reason": "critical_alerts_only",
                },
            },
        },
    }
