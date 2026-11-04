"""Galactic Knowledge Core: curated, attributable Elite Dangerous reference records.

Game knowledge (what an unlock needs, where an item comes from, which sites are
documented) lives in versioned JSON packs under ``omnicovas/data/galactic_knowledge``.
Each pack is validated on load and answers deterministic, read-only queries.  It is
*reference* information, kept apart from the Commander's own observations: it never
says what the Commander holds or has unlocked, and observations never change it.

Every claim, procedure step and relationship cites at least one declared source that
was actually read; a source recorded as ``not_retrieved`` can be listed for
transparency but can never be a claim's only support.  Nothing is fetched at runtime,
so every query works offline.  The developer-governance Authority RAG is a separate
system and is not used here.

Distribution is decided per pack from what the pack actually stores, not from where
its facts were researched (docs/gki-01-guardian-knowledge-20261029.md).  Original
records of game facts ship in every build with their sources credited; content
carrying its own licence ships with that licence; restricted or unresolved content
lives only in ``galactic_knowledge_restricted``, which no outward channel includes.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

SCHEMA = "galactic-knowledge-v1"
PACK_DIR = Path(__file__).resolve().parent.parent / "data" / "galactic_knowledge"
RESTRICTED_DIR = PACK_DIR.with_name("galactic_knowledge_restricted")

ENTITY_KINDS = (
    "material",
    "commodity",
    "module",
    "fighter",
    "equipment",
    "technology_unlock",
    "technology_broker",
    "structure",
    "location",
    "activity",
    # Galactic Atlas subjects (GKI-03).
    "star_system",
    "body",
    "station",
    "settlement",
    "landmark",
    "vessel",
    "person",
    "organization",
    "event",
    "discovery",
    # A legend or unsolved riddle with no location of its own (GKI-07).
    "mystery",
)
# Atlas places carry a validated location identity; every Atlas subject says why it
# matters and labels each claim with what kind of statement it is.
PLACE_KINDS = ("star_system", "body", "station", "settlement", "landmark")
ATLAS_KINDS = (
    *PLACE_KINDS,
    "vessel",
    "person",
    "organization",
    "event",
    "discovery",
    "mystery",
)
RELATIONSHIP_TYPES = (
    "requires",
    "unlocks",
    "obtained_from",
    "located_at",
    "used_for",
    "related_to",
    "located_in",
    "named_after",
    "associated_with",
    "discovered_by",
    "participated_in",
    "member_of",
    "historically_controlled_by",
    "occurred_at",
    # GKI-07: who founded something, a place's part in a historical expedition,
    # and what connects to an unsolved mystery.
    "founded_by",
    "part_of_expedition",
    "related_to_mystery",
)
# Relationship types that carry Atlas meaning (history and geography), as
# opposed to acquisition mechanics such as "requires" or "obtained_from".
ATLAS_RELATIONSHIPS = frozenset(
    (*RELATIONSHIP_TYPES[RELATIONSHIP_TYPES.index("located_in") :], "related_to")
)
# Which kinds each Atlas relationship may join, so a typo cannot make, say, a
# person "located in" an event.  Older relationship types are unconstrained.
_PLACE_LIKE = {*PLACE_KINDS, "vessel"}
RELATIONSHIP_ENDS: dict[str, tuple[set[str], set[str]]] = {
    "located_in": (_PLACE_LIKE, set(PLACE_KINDS)),
    "named_after": (_PLACE_LIKE, {"person", "organization"}),
    "discovered_by": ({*_PLACE_LIKE, "discovery"}, {"person"}),
    "participated_in": ({"person", "organization", "vessel"}, {"event"}),
    "member_of": ({"person"}, {"organization"}),
    "historically_controlled_by": (set(PLACE_KINDS), {"organization"}),
    "occurred_at": ({"event", "discovery"}, _PLACE_LIKE),
    "founded_by": ({*_PLACE_LIKE, "organization"}, {"person", "organization"}),
    "part_of_expedition": ({*_PLACE_LIKE, "person", "organization"}, {"event"}),
    "related_to_mystery": (set(ATLAS_KINDS) - {"mystery"}, {"mystery"}),
}
# Historical record, gameplay guidance and community-reported efficiency are kept
# apart so the Atlas never presents one as another.  GKI-07 adds the source's or
# community's reading of the record (``interpretation``) and unproven community
# ideas (``theory``), so lore, reporting, interpretation and theory never blur.
CLAIM_TOPICS = (
    "history",
    "identity",
    "service",
    "gameplay",
    "community_report",
    "uncertainty",
    "interpretation",
    "theory",
)
CERTAINTY = ("documented", "uncertain", "disputed")
# What kind of historical event an Atlas event is, where a source says.  GKI-03
# records used these values freely; GKI-07 fixes the list so "expedition" can be
# relied on by ``part_of_expedition``.
EVENT_TYPES = (
    "attack",
    "campaign",
    "conflict",
    "discovery",
    "expedition",
    "incident",
    "mission",
)
# GKI-06 storytelling and journey planning content.
TEASER_MAX_LENGTH = 100
REQUIREMENT_KINDS = ("permit", "equipment", "access")
THEME_SELECTORS = (
    "kinds",
    "landmark_types",
    "related_to",
    "narratives",
    "places",
    "activity_contexts",
)
# How precisely a place's position is known.  Only ``exact`` positions can ever be
# matched to a Commander's surface position.
LOCATION_PRECISION = ("exact", "approximate", "historical", "system_only")
# A landing is *at* an exactly placed site only within SITE_ARRIVAL_KM of it, even
# allowing for how coarsely its position is documented; within SITE_NEARBY_KM it is
# only nearby, which is never a visit.  Great-circle distances on the documented
# body radius: 0.5 degrees, the earlier rule, is 5.0 to 7.9 km on these bodies.
SITE_ARRIVAL_KM = 1.0
SITE_NEARBY_KM = 10.0
EVIDENCE_CLASSES = (
    "frontier_documentation",
    "community_corroborated",
    "community_reference",
    "cross_check_only",
    "app_reference",
)
SOURCE_KINDS = (
    "community_wiki",
    "frontier_documentation",
    "community_dataset",
    "community_research",
    "omnicovas_reference",
)
SOURCE_REUSE = (
    "facts_restated",
    "event_shape_only",
    "cross_check_only",
    "internal_reference",
    "not_retrieved",
)
INVENTORY_STORES = ("materials", "ship_cargo")
ACTIVITY_CONTEXTS = ("guardian_site", "human_space", "surface_site")
# A broker offering either unlocks equipment for good (bought with credits after)
# or exchanges resources for one item each time; the two are never interchangeable.
TRANSACTIONS = ("permanent_unlock", "per_item_purchase")
OFFERING_CATEGORIES = ("module", "weapon", "fighter")
# Distribution class -> whether the pack ships.  A shipped class must sit in PACK_DIR
# and a restricted one in RESTRICTED_DIR; a pack in the wrong place fails to load,
# so restricted content cannot reach a build by being filed in the wrong folder.
DISTRIBUTION_CLASSES = {
    "original_facts": True,
    "licensed_content": True,
    "development_only": False,
    "pending_review": False,
}


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _choice(value: Any, allowed: tuple[str, ...], field: str) -> str:
    if value not in allowed:
        raise ValueError(f"{field} must be one of {', '.join(allowed)}")
    return str(value)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return int(value)


def _cited(value: Any, field: str, sources: dict[str, JsonDict]) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} needs at least one source")
    cited = [str(item) for item in value]
    unknown = [item for item in cited if item not in sources]
    if unknown:
        raise ValueError(f"{field} cites unknown source {unknown[0]}")
    if all(sources[item]["reuse"] == "not_retrieved" for item in cited):
        raise ValueError(f"{field} rests only on sources that were not retrieved")
    return cited


def _source(raw: Any, index: int) -> JsonDict:
    if not isinstance(raw, dict):
        raise ValueError(f"sources[{index}] must be an object")
    label = f"sources[{index}]"
    row: JsonDict = {
        key: _text(raw.get(key), f"{label}.{key}")
        for key in ("id", "name", "url", "licence", "accessed", "role")
    }
    row["kind"] = _choice(raw.get("kind"), SOURCE_KINDS, f"{label}.kind")
    row["reuse"] = _choice(raw.get("reuse"), SOURCE_REUSE, f"{label}.reuse")
    revision = raw.get("revision")
    if revision is not None:
        if not isinstance(revision, dict):
            raise ValueError(f"{label}.revision must be an object")
        row["revision"] = {
            "page_id": _positive_int(revision.get("page_id"), f"{label}.page_id"),
            "revision_id": _positive_int(
                revision.get("revision_id"), f"{label}.revision_id"
            ),
            "timestamp": _text(revision.get("timestamp"), f"{label}.timestamp"),
        }
    return row


def _claims(raw: Any, label: str, sources: dict[str, JsonDict]) -> list[JsonDict]:
    claims: list[JsonDict] = []
    seen: set[str] = set()
    for index, claim in enumerate(raw or []):
        if not isinstance(claim, dict):
            raise ValueError(f"{label}.claims[{index}] must be an object")
        claim_id = _text(claim.get("id"), f"{label}.claims[{index}].id")
        if claim_id in seen:
            raise ValueError(f"{label} repeats claim {claim_id}")
        seen.add(claim_id)
        row: JsonDict = {
            "id": claim_id,
            "text": _text(claim.get("text"), f"{label}.{claim_id}.text"),
            "evidence": _choice(
                claim.get("evidence"), EVIDENCE_CLASSES, f"{label}.{claim_id}"
            ),
            "sources": _cited(claim.get("sources"), f"{label}.{claim_id}", sources),
        }
        if claim.get("topic") is not None:
            row["topic"] = _choice(
                claim.get("topic"), CLAIM_TOPICS, f"{label}.{claim_id}.topic"
            )
        # A spoiler is a narrative revelation (GKI-04): shown when asked for, held
        # back from unsolicited briefings while Spoiler Protection is on.
        if claim.get("spoiler") is not None:
            if claim.get("spoiler") is not True:
                raise ValueError(f"{label}.{claim_id}.spoiler must be true when set")
            row["spoiler"] = True
        claims.append(row)
    return claims


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field} must be a number")
    return float(value)


def _location(
    raw: Any, label: str, kind: str, sources: dict[str, JsonDict]
) -> JsonDict:
    """Validate a place's identity: only the identifiers a source actually gives.

    Identifiers follow the Player Journal (``SystemAddress``, ``StarPos``,
    ``MarketID``, ``BodyID``, surface ``Latitude``/``Longitude``) so later features
    can match real observations.  Nothing is assumed: a station without a MarketID
    can only ever match by name inside its system, and a surface position counts
    only when the source gives one precisely.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{label} is a {kind} and needs a location")
    where = f"{label}.location"
    row: JsonDict = {
        "system": _text(raw.get("system"), f"{where}.system"),
        "precision": _choice(raw.get("precision"), LOCATION_PRECISION, f"{where}"),
        "sources": _cited(raw.get("sources"), where, sources),
    }
    if raw.get("system_address") is not None:
        row["system_address"] = _positive_int(
            raw.get("system_address"), f"{where}.system_address"
        )
    if raw.get("star_pos") is not None:
        star_pos = raw.get("star_pos")
        if not isinstance(star_pos, list) or len(star_pos) != 3:
            raise ValueError(f"{where}.star_pos must be [x, y, z]")
        row["star_pos"] = [_number(v, f"{where}.star_pos") for v in star_pos]
    for name, ident in (("body", "body_id"), ("station", "market_id")):
        if raw.get(name) is not None:
            row[name] = _text(raw.get(name), f"{where}.{name}")
        if raw.get(ident) is not None:
            if name not in row:
                raise ValueError(f"{where}.{ident} needs the {name} name it identifies")
            value = raw.get(ident)
            # BodyID 0 is the main star, so only MarketID must be positive.
            if ident == "body_id" and value == 0:
                row[ident] = 0
            else:
                row[ident] = _positive_int(value, f"{where}.{ident}")
    if (raw.get("latitude") is None) != (raw.get("longitude") is None):
        raise ValueError(f"{where} needs both latitude and longitude")
    if raw.get("latitude") is not None:
        if "body" not in row:
            raise ValueError(f"{where} gives a surface position without a body")
        latitude = _number(raw.get("latitude"), f"{where}.latitude")
        longitude = _number(raw.get("longitude"), f"{where}.longitude")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError(f"{where} surface position is out of range")
        row["latitude"], row["longitude"] = latitude, longitude
    if kind == "station" and "station" not in row:
        raise ValueError(f"{where} is a station without a station name")
    if kind == "body" and "body" not in row:
        raise ValueError(f"{where} is a body without a body name")
    if row["precision"] == "exact" and kind in {"landmark", "settlement"}:
        if "latitude" not in row:
            raise ValueError(f"{where} is exact but gives no surface position")
    # A landing's distance from a site needs the body's size and the resolution of
    # the documented coordinates (two decimal places is 0.01 degrees).
    for field, upper in (
        ("body_radius_km", 100_000.0),
        ("surface_resolution_deg", 1.0),
    ):
        if raw.get(field) is None:
            continue
        if "latitude" not in row:
            raise ValueError(f"{where}.{field} needs the surface position it measures")
        value = _number(raw.get(field), f"{where}.{field}")
        if not 0 < value <= upper:
            raise ValueError(f"{where}.{field} is out of range")
        row[field] = value
    if (
        row["precision"] == "exact"
        and "latitude" in row
        and not {"body_radius_km", "surface_resolution_deg"} <= row.keys()
    ):
        raise ValueError(
            f"{where} is exact but gives no body_radius_km and surface_resolution_deg, "
            "so a landing's distance from it cannot be measured"
        )
    if raw.get("note") is not None:
        row["note"] = _text(raw.get("note"), f"{where}.note")
    return row


def _offering(entity: JsonDict, label: str, sources: dict[str, JsonDict]) -> None:
    """Validate a broker offering's transaction, category, recipes and evidence."""
    attributes = entity["attributes"]
    transaction = _choice(
        attributes.get("transaction"), TRANSACTIONS, f"{label}.transaction"
    )
    _choice(attributes.get("category"), OFFERING_CATEGORIES, f"{label}.category")
    recipes = attributes.get("recipes")
    if recipes is not None:
        if not isinstance(recipes, list) or len(recipes) < 2:
            raise ValueError(f"{label}.recipes lists the alternatives of a conflict")
        attributes["recipes"] = [
            {
                "id": _text(r.get("id"), f"{label}.recipes[{n}].id"),
                "label": _text(r.get("label"), f"{label}.recipes[{n}].label"),
                "note": _text(r.get("note"), f"{label}.recipes[{n}].note"),
                "sources": _cited(r.get("sources"), f"{label}.recipes[{n}]", sources),
            }
            for n, r in enumerate(recipes)
            if isinstance(r, dict)
        ]
    evidence = attributes.get("journal_unlock")
    if evidence is not None:
        # A per-item purchase never establishes access to further copies, so it
        # must not carry anything the planner could read as unlock evidence.
        if transaction == "per_item_purchase":
            raise ValueError(f"{label} is a per-item purchase with unlock evidence")
        symbols = evidence.get("item_symbols") if isinstance(evidence, dict) else None
        if (
            not isinstance(symbols, list)
            or not symbols
            or any(not isinstance(s, str) or s != s.casefold() for s in symbols)
        ):
            raise ValueError(f"{label}.journal_unlock needs lower-case item_symbols")


# ── Narratives, themes, requirements and the system gazetteer (GKI-06) ─────


def _basis(raw: Any, label: str, known: dict[str, JsonDict]) -> list[JsonDict]:
    """The documented claims a narrative passage rests on.

    Each item names an entity and one of its claim ids; the index checks that the
    claim exists, so a story can only retell what the knowledge records.
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{label}.basis must name the claims it rests on")
    rows: list[JsonDict] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{label}.basis[{index}] must be an object")
        entity = _text(item.get("entity"), f"{label}.basis[{index}].entity")
        if entity not in known:
            raise ValueError(f"{label}.basis[{index}] names unknown entity {entity}")
        claim = _text(item.get("claim"), f"{label}.basis[{index}].claim")
        rows.append({"entity": entity, "claim": claim})
    return rows


def _passage(raw: Any, label: str, known: dict[str, JsonDict]) -> JsonDict:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    row: JsonDict = {
        "text": _text(raw.get("text"), f"{label}.text"),
        "basis": _basis(raw.get("basis"), label, known),
    }
    if raw.get("title") is not None:
        row["title"] = _text(raw.get("title"), f"{label}.title")
    return row


def _teaser(value: Any, label: str) -> str:
    teaser = _text(value, label)
    if len(teaser) > TEASER_MAX_LENGTH:
        raise ValueError(f"{label} must be {TEASER_MAX_LENGTH} characters or fewer")
    return teaser


def _place_ref(value: Any, label: str, known: dict[str, JsonDict]) -> str:
    place = _text(value, label)
    if place not in known:
        raise ValueError(f"{label} names unknown entity {place}")
    if known[place]["kind"] not in (*PLACE_KINDS, "location"):
        raise ValueError(f"{label} must be a place")
    return place


def _narrative(raw: Any, index: int, known: dict[str, JsonDict]) -> JsonDict:
    """An authored story arc over documented places (GKI-06)."""
    if not isinstance(raw, dict):
        raise ValueError(f"narratives[{index}] must be an object")
    narrative_id = _text(raw.get("id"), f"narratives[{index}].id")
    label = f"narrative {narrative_id}"
    chapters: list[JsonDict] = []
    seen: set[str] = set()
    for c_index, chapter in enumerate(raw.get("chapters") or []):
        where = f"{label}.chapters[{c_index}]"
        if not isinstance(chapter, dict):
            raise ValueError(f"{where} must be an object")
        chapter_id = _text(chapter.get("id"), f"{where}.id")
        if chapter_id in seen:
            raise ValueError(f"{label} repeats chapter {chapter_id}")
        seen.add(chapter_id)
        row: JsonDict = {
            "id": chapter_id,
            "place": _place_ref(chapter.get("place"), f"{where}.place", known),
            "title": _text(chapter.get("title"), f"{where}.title"),
            "teaser": _teaser(chapter.get("teaser"), f"{where}.teaser"),
            **_passage(chapter, where, known),
        }
        if chapter.get("spoiler") is not None:
            if chapter.get("spoiler") is not True:
                raise ValueError(f"{where}.spoiler must be true when set")
            row["spoiler"] = True
        connections = []
        for k, link in enumerate(chapter.get("connections") or []):
            if not isinstance(link, dict):
                raise ValueError(f"{where}.connections[{k}] must be an object")
            entity = _text(link.get("entity"), f"{where}.connections[{k}].entity")
            if entity not in known:
                raise ValueError(f"{where}.connections[{k}] names unknown {entity}")
            connections.append(
                {
                    "entity": entity,
                    "text": _text(link.get("text"), f"{where}.connections[{k}].text"),
                }
            )
        row["connections"] = connections
        chapters.append(row)
    if not chapters:
        raise ValueError(f"{label} needs at least one chapter")
    discoveries = []
    for d_index, item in enumerate(raw.get("discoveries") or []):
        where = f"{label}.discoveries[{d_index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be an object")
        discoveries.append(
            {
                "place": _place_ref(item.get("place"), f"{where}.place", known),
                **_passage(item, where, known),
            }
        )
    row = {
        "id": narrative_id,
        "title": _text(raw.get("title"), f"{label}.title"),
        "summary": _text(raw.get("summary"), f"{label}.summary"),
        "teaser": _teaser(raw.get("teaser"), f"{label}.teaser"),
        "introduction": _passage(
            raw.get("introduction"), f"{label}.introduction", known
        ),
        "chapters": chapters,
        "discoveries": discoveries,
        "conclusion": _passage(raw.get("conclusion"), f"{label}.conclusion", known),
    }
    if raw.get("theme") is not None:
        row["theme"] = _text(raw.get("theme"), f"{label}.theme")
    return row


def _theme(
    raw: Any, index: int, known: dict[str, JsonDict], narratives: set[str]
) -> JsonDict:
    """A planning theme: selectors over the existing graph, no content of its own."""
    if not isinstance(raw, dict):
        raise ValueError(f"themes[{index}] must be an object")
    theme_id = _text(raw.get("id"), f"themes[{index}].id")
    label = f"theme {theme_id}"
    select = raw.get("select")
    if not isinstance(select, dict) or not select:
        raise ValueError(f"{label}.select needs at least one selector")
    selectors: JsonDict = {}
    for key, value in select.items():
        if key == "acquisition":
            if value is not True:
                raise ValueError(f"{label}.select.acquisition must be true when set")
            selectors[key] = True
            continue
        if key not in THEME_SELECTORS:
            raise ValueError(f"{label}.select.{key} is not a known selector")
        if not isinstance(value, list) or not value:
            raise ValueError(f"{label}.select.{key} must be a non-empty list")
        items = [_text(item, f"{label}.select.{key}") for item in value]
        for item in items:
            if key == "kinds" and item not in ENTITY_KINDS:
                raise ValueError(f"{label}.select.kinds has unknown kind {item}")
            if key == "activity_contexts" and item not in ACTIVITY_CONTEXTS:
                raise ValueError(f"{label}.select has unknown context {item}")
            if key in {"related_to", "places"} and item not in known:
                raise ValueError(f"{label}.select.{key} names unknown {item}")
            if key == "narratives" and item not in narratives:
                raise ValueError(f"{label}.select names unknown narrative {item}")
        selectors[key] = items
    return {
        "id": theme_id,
        "label": _text(raw.get("label"), f"{label}.label"),
        "summary": _text(raw.get("summary"), f"{label}.summary"),
        "select": selectors,
    }


def _requirement(raw: Any, index: int, known: dict[str, JsonDict]) -> JsonDict:
    """Something documented as needed to reach a place, such as a permit."""
    if not isinstance(raw, dict):
        raise ValueError(f"requirements[{index}] must be an object")
    requirement_id = _text(raw.get("id"), f"requirements[{index}].id")
    label = f"requirement {requirement_id}"
    return {
        "id": requirement_id,
        "place": _place_ref(raw.get("place"), f"{label}.place", known),
        "kind": _choice(raw.get("kind"), REQUIREMENT_KINDS, f"{label}.kind"),
        **_passage(raw, label, known),
    }


def _system_record(raw: Any, index: int, sources: dict[str, JsonDict]) -> JsonDict:
    """One gazetteer row: a system's identifiers and position at curation time."""
    if not isinstance(raw, dict):
        raise ValueError(f"systems[{index}] must be an object")
    name = _text(raw.get("name"), f"systems[{index}].name")
    position = raw.get("star_pos")
    if not isinstance(position, list) or len(position) != 3:
        raise ValueError(f"system {name}.star_pos must be three numbers")
    return {
        "name": name,
        "system_address": _positive_int(
            raw.get("system_address"), f"system {name}.system_address"
        ),
        "star_pos": [_number(v, f"system {name}.star_pos") for v in position],
        "sources": _cited(raw.get("sources"), f"system {name}", sources),
    }


def _entity(raw: Any, index: int, sources: dict[str, JsonDict]) -> JsonDict:
    if not isinstance(raw, dict):
        raise ValueError(f"entities[{index}] must be an object")
    entity_id = _text(raw.get("id"), f"entities[{index}].id")
    label = f"entity {entity_id}"
    kind = _choice(raw.get("kind"), ENTITY_KINDS, f"{label}.kind")
    entity: JsonDict = {
        "id": entity_id,
        "kind": kind,
        "name": _text(raw.get("name"), f"{label}.name"),
        "aliases": [
            _text(alias, f"{label}.alias") for alias in raw.get("aliases") or []
        ],
        "summary": _text(raw.get("summary"), f"{label}.summary"),
        "attributes": dict(raw.get("attributes") or {}),
        "claims": _claims(raw.get("claims"), label, sources),
    }
    if not entity["claims"]:
        raise ValueError(f"{label} has no sourced claims")
    inventory = raw.get("inventory")
    if inventory is not None:
        if kind not in {"material", "commodity"}:
            raise ValueError(f"{label} is a {kind} and cannot map to inventory")
        store = _choice(inventory.get("store"), INVENTORY_STORES, f"{label}.store")
        # Materials live in the Journal material inventory, commodities in cargo:
        # the two are observed differently and must never be confused.
        if (kind == "material") != (store == "materials"):
            raise ValueError(f"{label} maps a {kind} to the {store} store")
        symbol = _text(inventory.get("symbol"), f"{label}.symbol")
        if symbol != symbol.casefold():
            raise ValueError(f"{label}.symbol must be the lower-case Journal symbol")
        entity["inventory"] = {
            "store": store,
            "symbol": symbol,
            "category": _text(inventory.get("category"), f"{label}.category"),
        }
        if inventory.get("grade") is not None:
            entity["inventory"]["grade"] = _positive_int(
                inventory.get("grade"), f"{label}.grade"
            )
    steps = raw.get("steps")
    if steps is not None:
        if kind != "activity":
            raise ValueError(f"{label} has steps but is not an activity")
        entity["steps"] = [
            {
                "id": _text(step.get("id"), f"{label}.steps[{n}].id"),
                "text": _text(step.get("text"), f"{label}.steps[{n}].text"),
                "sources": _cited(step.get("sources"), f"{label}.steps[{n}]", sources),
            }
            for n, step in enumerate(steps)
            if isinstance(step, dict)
        ]
    if kind == "activity":
        _choice(
            entity["attributes"].get("context"), ACTIVITY_CONTEXTS, f"{label}.context"
        )
    if kind == "technology_unlock":
        _offering(entity, label, sources)
    if kind == "location":
        _choice(
            entity["attributes"].get("evidence"),
            EVIDENCE_CLASSES,
            f"{label}.attributes.evidence",
        )
        _text(entity["attributes"].get("system"), f"{label}.system")
    if kind == "event" and entity["attributes"].get("event_type") is not None:
        _choice(entity["attributes"]["event_type"], EVENT_TYPES, f"{label}.event_type")
    if kind in ATLAS_KINDS:
        _text(entity["attributes"].get("significance"), f"{label}.significance")
        if entity["attributes"].get("significance_spoiler") not in (None, True):
            raise ValueError(f"{label}.significance_spoiler must be true when set")
        if any("topic" not in claim for claim in entity["claims"]):
            raise ValueError(f"{label} has an Atlas claim without a topic")
    if kind in PLACE_KINDS or raw.get("location") is not None:
        if kind not in PLACE_KINDS:
            raise ValueError(f"{label} is a {kind} and cannot carry a location")
        entity["location"] = _location(raw.get("location"), label, kind, sources)
    return entity


def _relationship(
    raw: Any, index: int, entities: dict[str, JsonDict], sources: dict[str, JsonDict]
) -> JsonDict:
    if not isinstance(raw, dict):
        raise ValueError(f"relationships[{index}] must be an object")
    label = f"relationships[{index}]"
    kind = _choice(raw.get("type"), RELATIONSHIP_TYPES, f"{label}.type")
    source_id = _text(raw.get("from"), f"{label}.from")
    target_id = _text(raw.get("to"), f"{label}.to")
    for end in (source_id, target_id):
        if end not in entities:
            raise ValueError(f"{label} refers to unknown entity {end}")
    row: JsonDict = {
        "type": kind,
        "from": source_id,
        "to": target_id,
        "sources": _cited(raw.get("sources"), label, sources),
    }
    if raw.get("quantity") is not None:
        row["quantity"] = _positive_int(raw.get("quantity"), f"{label}.quantity")
    if kind == "requires" and entities[source_id]["kind"] == "technology_unlock":
        if "quantity" not in row:
            raise ValueError(f"{label} unlock requirement needs a quantity")
        if "inventory" not in entities[target_id]:
            raise ValueError(
                f"{label} requires {target_id}, which has no inventory link"
            )
    if raw.get("note") is not None:
        row["note"] = _text(raw.get("note"), f"{label}.note")
    if raw.get("recipe") is not None:
        row["recipe"] = _text(raw.get("recipe"), f"{label}.recipe")
    ends = RELATIONSHIP_ENDS.get(kind)
    if ends is not None:
        if (
            entities[source_id]["kind"] not in ends[0]
            or entities[target_id]["kind"] not in ends[1]
        ):
            raise ValueError(
                f"{label} cannot join a {entities[source_id]['kind']} to a "
                f"{entities[target_id]['kind']} as {kind}"
            )
    if ends is not None or kind == "associated_with" or raw.get("certainty"):
        row["certainty"] = _choice(
            raw.get("certainty", "documented"), CERTAINTY, f"{label}.certainty"
        )
    for key in ("role", "period"):
        if raw.get(key) is not None:
            row[key] = _text(raw.get(key), f"{label}.{key}")
    # A namesake is a documented naming, never a guess from similar names, so it
    # must say what the source establishes.  Control is always historical: the
    # Atlas has no live faction data, so the record states the period it covers.
    if kind == "named_after" and "note" not in row:
        raise ValueError(f"{label} namesake needs a note on what is documented")
    if kind == "historically_controlled_by" and "period" not in row:
        raise ValueError(f"{label} control needs the period it was documented for")
    # A founding is a dated historical fact: say when, or what exactly is meant.
    if kind == "founded_by" and "period" not in row and "note" not in row:
        raise ValueError(f"{label} founding needs a period or a note")
    return row


def _check_offerings(
    entities: dict[str, JsonDict], relationships: list[JsonDict]
) -> None:
    """Recipes must match their requirement edges; procedures must have steps."""
    for entity in entities.values():
        label = f"entity {entity['id']}"
        procedure = entity["attributes"].get("procedure")
        if procedure is not None and not entities.get(procedure, {}).get("steps"):
            raise ValueError(f"{label} refers to a procedure without steps")
        if entity["kind"] != "technology_unlock":
            continue
        edges = [
            r
            for r in relationships
            if r["from"] == entity["id"] and r["type"] == "requires"
        ]
        if not edges:
            raise ValueError(f"{label} has no requirements")
        declared = {r["id"] for r in entity["attributes"].get("recipes") or []}
        used = {r.get("recipe") for r in edges}
        if declared:
            if used != declared:
                raise ValueError(f"{label} recipes and requirement edges disagree")
        elif used != {None}:
            raise ValueError(f"{label} names a recipe it does not declare")


def validate_pack(raw: Any) -> JsonDict:
    """Return the pack in its normalised shape, or raise ``ValueError``."""
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise ValueError("Unsupported galactic knowledge schema")
    sources: dict[str, JsonDict] = {}
    for index, source in enumerate(raw.get("sources") or []):
        row = _source(source, index)
        if row["id"] in sources:
            raise ValueError(f"Duplicate source id {row['id']}")
        sources[row["id"]] = row
    if not sources:
        raise ValueError("sources are required")

    entities: dict[str, JsonDict] = {}
    for index, entity in enumerate(raw.get("entities") or []):
        row = _entity(entity, index, sources)
        if row["id"] in entities:
            raise ValueError(f"Duplicate entity id {row['id']}")
        entities[row["id"]] = row
    stories = ("narratives", "themes", "requirements", "systems")
    if not entities and not any(raw.get(key) for key in stories):
        raise ValueError("The pack has no entities")

    symbols: dict[tuple[str, str], str] = {}
    for entity in entities.values():
        link = entity.get("inventory")
        if link:
            key = (link["store"], link["symbol"])
            if key in symbols:
                raise ValueError(
                    f"{entity['id']} and {symbols[key]} map to the same "
                    "inventory record"
                )
            symbols[key] = entity["id"]

    # An Atlas profile for a place another pack already records (for example a
    # Guardian broker station), so one place keeps one identifier everywhere.
    extensions: dict[str, JsonDict] = {}
    for index, extension in enumerate(raw.get("extends") or []):
        row = _entity(extension, index, sources)
        if row["kind"] not in ATLAS_KINDS:
            raise ValueError(f"extends[{index}] must be an Atlas subject")
        if "inventory" in row or "steps" in row:
            raise ValueError(f"extends[{index}] can only add Atlas information")
        if row["id"] in entities or row["id"] in extensions:
            raise ValueError(f"Duplicate entity id {row['id']}")
        extensions[row["id"]] = row

    # Records another pack owns that this pack's relationships may point at
    # (GKI-05): the material acquisition pack reuses the Guardian pack's
    # activities and the Atlas pack's materials instead of recording them twice.
    # The kind is declared so relationship rules apply; the index checks that the
    # record exists with that kind.
    references: dict[str, JsonDict] = {}
    for index, reference in enumerate(raw.get("references") or []):
        if not isinstance(reference, dict):
            raise ValueError(f"references[{index}] must be an object")
        ref_id = _text(reference.get("id"), f"references[{index}].id")
        if ref_id in entities or ref_id in extensions or ref_id in references:
            raise ValueError(f"references[{index}] repeats entity id {ref_id}")
        references[ref_id] = {
            "id": ref_id,
            "kind": _choice(
                reference.get("kind"), ENTITY_KINDS, f"references.{ref_id}"
            ),
        }

    relationships = [
        _relationship(row, index, {**entities, **extensions, **references}, sources)
        for index, row in enumerate(raw.get("relationships") or [])
    ]
    seen_edges: set[tuple[str, str, str, str | None]] = set()
    for row in relationships:
        edge = (row["type"], row["from"], row["to"], row.get("recipe"))
        if edge in seen_edges:
            raise ValueError(f"Duplicate relationship {edge}")
        seen_edges.add(edge)
    _check_offerings(entities, relationships)

    # GKI-06: stories, themes, requirements and positions over known entities.
    known = {**entities, **extensions, **references}
    narratives: dict[str, JsonDict] = {}
    for index, item in enumerate(raw.get("narratives") or []):
        row = _narrative(item, index, known)
        if row["id"] in narratives:
            raise ValueError(f"Duplicate narrative id {row['id']}")
        narratives[row["id"]] = row
    themes: dict[str, JsonDict] = {}
    for index, item in enumerate(raw.get("themes") or []):
        row = _theme(item, index, known, set(narratives))
        if row["id"] in themes:
            raise ValueError(f"Duplicate theme id {row['id']}")
        themes[row["id"]] = row
    for row in narratives.values():
        if row.get("theme") and row["theme"] not in themes:
            raise ValueError(
                f"narrative {row['id']} names unknown theme {row['theme']}"
            )
    requirements = [
        _requirement(item, index, known)
        for index, item in enumerate(raw.get("requirements") or [])
    ]
    if len({row["id"] for row in requirements}) != len(requirements):
        raise ValueError("Duplicate requirement id")
    systems = [
        _system_record(item, index, sources)
        for index, item in enumerate(raw.get("systems") or [])
    ]

    distribution = raw.get("distribution")
    if not isinstance(distribution, dict):
        raise ValueError("The pack must declare its distribution class")
    distribution_class = _choice(
        distribution.get("class"),
        tuple(DISTRIBUTION_CLASSES),
        "distribution.class",
    )
    declared: JsonDict = {
        "class": distribution_class,
        "shipped": DISTRIBUTION_CLASSES[distribution_class],
        "basis": _text(distribution.get("basis"), "distribution.basis"),
        "decision_record": _text(
            distribution.get("decision_record"), "distribution.decision_record"
        ),
    }
    if distribution_class == "licensed_content":
        # Licensed expression ships only with its licence and notice attached.
        terms = distribution.get("content_license")
        if not isinstance(terms, dict):
            raise ValueError("licensed_content needs distribution.content_license")
        declared["content_license"] = {
            key: _text(terms.get(key), f"distribution.content_license.{key}")
            for key in ("id", "name", "url", "notice")
        }

    unsupported = [
        {
            "subject": _text(row.get("subject"), "unsupported.subject"),
            "reason": _text(row.get("reason"), "unsupported.reason"),
        }
        for row in raw.get("unsupported") or []
        if isinstance(row, dict)
    ]
    return {
        "schema": SCHEMA,
        "pack_id": _text(raw.get("pack_id"), "pack_id"),
        "version": _text(raw.get("version"), "version"),
        "reviewed_at": _text(raw.get("reviewed_at"), "reviewed_at"),
        "title": _text(raw.get("title"), "title"),
        "scope": _text(raw.get("scope"), "scope"),
        "game_version": _text(raw.get("game_version"), "game_version"),
        "rights_basis": _text(raw.get("rights_basis"), "rights_basis"),
        "distribution": declared,
        "sources": list(sources.values()),
        "entities": list(entities.values()),
        "extends": list(extensions.values()),
        "references": list(references.values()),
        "relationships": relationships,
        "narratives": list(narratives.values()),
        "themes": list(themes.values()),
        "requirements": requirements,
        "systems": systems,
        "unsupported": unsupported,
    }


@dataclass(frozen=True)
class _Edge:
    type: str
    source: str
    target: str
    quantity: int | None
    note: str | None
    sources: tuple[str, ...]
    recipe: str | None = None
    certainty: str | None = None
    role: str | None = None
    period: str | None = None


def _normal(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def _angular_distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle separation in degrees between two latitude/longitude pairs."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    cosine = math.sin(lat1) * math.sin(lat2) + math.cos(lat1) * math.cos(
        lat2
    ) * math.cos(lon1 - lon2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def position_uncertainty_km(identity: JsonDict) -> float:
    """How far the true site may lie from its documented, rounded position."""
    half = identity["surface_resolution_deg"] / 2
    across = half * math.cos(math.radians(identity["latitude"]))
    return float(identity["body_radius_km"] * math.radians(math.hypot(half, across)))


def surface_proximity(
    identity: JsonDict, latitude: float, longitude: float
) -> JsonDict:
    """How close a surface observation is to an exactly placed site.

    ``at_site`` only when even the far edge of the documented position's rounding
    lies within :data:`SITE_ARRIVAL_KM`; ``nearby`` when the observation may be
    within :data:`SITE_NEARBY_KM`; otherwise ``far``.  The Journal's own latitude
    and longitude are far finer than any documented site position, so that rounding
    is the only uncertainty allowed for.
    """
    separation = _angular_distance(
        (latitude, longitude), (identity["latitude"], identity["longitude"])
    )
    distance = identity["body_radius_km"] * math.radians(separation)
    uncertainty = position_uncertainty_km(identity)
    if distance + uncertainty <= SITE_ARRIVAL_KM:
        state = "at_site"
    elif distance - uncertainty <= SITE_NEARBY_KM:
        state = "nearby"
    else:
        state = "far"
    return {
        "state": state,
        "distance_km": round(distance, 2),
        "uncertainty_km": round(uncertainty, 2),
    }


class KnowledgeIndex:
    """Deterministic, read-only lookups over one or more validated packs."""

    def __init__(self, packs: list[JsonDict]) -> None:
        self.packs = packs
        self._entities: dict[str, JsonDict] = {}
        self._profiles: dict[str, JsonDict] = {}
        self._sources: dict[str, JsonDict] = {}
        self._edges: list[_Edge] = []
        for pack in packs:
            for source in pack["sources"]:
                existing = self._sources.get(source["id"])
                if existing is not None and existing != source:
                    raise ValueError(f"Source {source['id']} differs between packs")
                self._sources[source["id"]] = source
            for entity in pack["entities"]:
                if entity["id"] in self._entities:
                    raise ValueError(f"Entity {entity['id']} is defined twice")
                self._entities[entity["id"]] = {**entity, "pack_id": pack["pack_id"]}
            self._edges.extend(
                _Edge(
                    row["type"],
                    row["from"],
                    row["to"],
                    row.get("quantity"),
                    row.get("note"),
                    tuple(row["sources"]),
                    row.get("recipe"),
                    row.get("certainty"),
                    row.get("role"),
                    row.get("period"),
                )
                for row in pack["relationships"]
            )
        for pack in packs:
            for profile in pack.get("extends") or []:
                base = self._entities.get(profile["id"])
                if base is None or base["pack_id"] == pack["pack_id"]:
                    raise ValueError(f"{profile['id']} extends a record no pack has")
                if base["kind"] != "location" or _normal(base["name"]) != _normal(
                    profile["name"]
                ):
                    raise ValueError(f"{profile['id']} extends a different place")
                if profile["id"] in self._profiles:
                    raise ValueError(f"{profile['id']} has two Atlas profiles")
                self._profiles[profile["id"]] = {**profile, "pack_id": pack["pack_id"]}
        for pack in packs:
            for reference in pack.get("references") or []:
                found = self._entities.get(reference["id"])
                if (
                    found is None
                    or found["pack_id"] == pack["pack_id"]
                    or found["kind"] != reference["kind"]
                ):
                    raise ValueError(
                        f"{pack['pack_id']} references {reference['id']} as a "
                        f"{reference['kind']}, which no other pack records"
                    )
        for edge in self._edges:
            for end in (edge.source, edge.target):
                if end not in self._entities:
                    raise ValueError(f"A relationship refers to unknown entity {end}")
            # Checked here, not per pack: the expedition may live in another pack.
            if edge.type == "part_of_expedition" and (
                self._entities[edge.target]["attributes"].get("event_type")
                != "expedition"
            ):
                raise ValueError(
                    f"{edge.source} is part of {edge.target}, which is not an "
                    "expedition"
                )
        self._check_identities()
        self._load_stories(packs)

    # GKI-06 ------------------------------------------------------------------

    def _load_stories(self, packs: list[JsonDict]) -> None:
        """Narratives, themes, requirements and the system gazetteer.

        A narrative may only retell claims the knowledge records, and a chapter
        resting on a spoiler claim must itself be marked as a spoiler.
        """
        self._narratives: dict[str, JsonDict] = {}
        self._themes: dict[str, JsonDict] = {}
        self._requirements: list[JsonDict] = []
        self._gazetteer: dict[int, JsonDict] = {}
        self._gazetteer_names: dict[str, int] = {}
        # Built on first use; the index never changes after construction.
        self._documented_systems: (
            tuple[dict[int, JsonDict], dict[str, JsonDict]] | None
        ) = None
        self._places: dict[str, JsonDict] | None = None
        for pack in packs:
            for row in pack.get("narratives") or []:
                if row["id"] in self._narratives:
                    raise ValueError(f"Narrative {row['id']} is defined twice")
                self._narratives[row["id"]] = {**row, "pack_id": pack["pack_id"]}
            for row in pack.get("themes") or []:
                if row["id"] in self._themes:
                    raise ValueError(f"Theme {row['id']} is defined twice")
                self._themes[row["id"]] = {**row, "pack_id": pack["pack_id"]}
            self._requirements.extend(pack.get("requirements") or [])
            for row in pack.get("systems") or []:
                address, name = row["system_address"], _normal(row["name"])
                if self._gazetteer_names.setdefault(name, address) != address:
                    raise ValueError(f"{row['name']} has two SystemAddress values")
                found = self._gazetteer.setdefault(address, row)
                if found is not row and found["star_pos"] != row["star_pos"]:
                    raise ValueError(f"{row['name']} has two positions")
        for entity_id in self._entities:
            where = self.identity(entity_id) or {}
            address = where.get("system_address")
            if address in self._gazetteer and where.get("star_pos"):
                gazetteer = self._gazetteer[address]["star_pos"]
                if math.dist(gazetteer, where["star_pos"]) > 0.05:
                    raise ValueError(
                        f"{where['system']} has a gazetteer position that differs "
                        "from its documented one"
                    )
        for narrative in self._narratives.values():
            for passage in self._passages(narrative):
                spoiler = False
                for item in passage["basis"]:
                    claim = self._claim(item["entity"], item["claim"])
                    if claim is None:
                        raise ValueError(
                            f"narrative {narrative['id']} rests on unknown claim "
                            f"{item['entity']}.{item['claim']}"
                        )
                    spoiler = spoiler or bool(claim.get("spoiler"))
                if spoiler and passage.get("chapter") and not passage.get("spoiler"):
                    raise ValueError(
                        f"narrative {narrative['id']} chapter {passage['id']} retells "
                        "a spoiler and must be marked as one"
                    )
            for chapter in narrative["chapters"]:
                if self.identity(chapter["place"]) is None:
                    raise ValueError(
                        f"narrative {narrative['id']} chapter {chapter['id']} is "
                        "set at a place with no location"
                    )
        for requirement in self._requirements:
            for item in requirement["basis"]:
                if self._claim(item["entity"], item["claim"]) is None:
                    raise ValueError(
                        f"requirement {requirement['id']} rests on unknown claim "
                        f"{item['entity']}.{item['claim']}"
                    )

    @staticmethod
    def _passages(narrative: JsonDict) -> list[JsonDict]:
        return [
            narrative["introduction"],
            *({**chapter, "chapter": True} for chapter in narrative["chapters"]),
            *narrative["discoveries"],
            narrative["conclusion"],
        ]

    def _claim(self, entity_id: str, claim_id: str) -> JsonDict | None:
        if entity_id not in self._entities:
            return None
        for record in (self._entities[entity_id], self._view(entity_id)):
            for claim in record.get("claims") or []:
                if claim["id"] == claim_id:
                    found: JsonDict = claim
                    return found
        return None

    def _resolve_basis(self, basis: list[JsonDict]) -> JsonDict:
        """Evidence, spoiler and sources a passage inherits from its claims."""
        ranks = {kind: n for n, kind in enumerate(EVIDENCE_CLASSES)}
        claims = [self._claim(i["entity"], i["claim"]) or {} for i in basis]
        weakest = max(
            (c.get("evidence", "community_reference") for c in claims),
            key=lambda kind: ranks.get(kind, 0),
        )
        sources = sorted({s for c in claims for s in c.get("sources") or []})
        return {
            "evidence": weakest,
            "spoiler": any(c.get("spoiler") for c in claims),
            "uncertain": any(c.get("topic") == "uncertainty" for c in claims),
            "sources": [
                {"id": s, "name": self._sources[s]["name"]}
                for s in sources
                if s in self._sources
            ],
            "basis": [
                {**i, "subject": self._brief(i["entity"])["name"]} for i in basis
            ],
        }

    def narratives(self) -> list[JsonDict]:
        """Every story arc, briefly, in pack order."""
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "summary": row["summary"],
                "teaser": row["teaser"],
                "theme": row.get("theme"),
                "chapters": len(row["chapters"]),
                "places": [chapter["place"] for chapter in row["chapters"]],
            }
            for row in self._narratives.values()
        ]

    def narrative(self, narrative_id: str) -> JsonDict:
        """One arc with each passage's inherited evidence, spoilers and sources."""
        row = self._narratives.get(narrative_id)
        if row is None:
            raise KeyError(narrative_id)

        def passage(item: JsonDict) -> JsonDict:
            return {**item, **self._resolve_basis(item["basis"])}

        chapters = []
        for chapter in row["chapters"]:
            resolved = passage(chapter)
            resolved["spoiler"] = bool(chapter.get("spoiler"))
            resolved["place_name"] = self._brief(chapter["place"])["name"]
            resolved["connections"] = [
                {**link, "subject": self._brief(link["entity"])}
                for link in chapter["connections"]
            ]
            chapters.append(resolved)
        return {
            "id": row["id"],
            "title": row["title"],
            "summary": row["summary"],
            "teaser": row["teaser"],
            "theme": row.get("theme"),
            "introduction": passage(row["introduction"]),
            "chapters": chapters,
            "discoveries": [
                {
                    **passage(item),
                    "place_name": self._brief(item["place"])["name"],
                }
                for item in row["discoveries"]
            ],
            "conclusion": passage(row["conclusion"]),
            "pack_id": row["pack_id"],
        }

    def themes(self) -> list[JsonDict]:
        return [
            {key: row[key] for key in ("id", "label", "summary", "select")}
            for row in self._themes.values()
        ]

    def requirements_for(self, place_id: str) -> list[JsonDict]:
        """Documented requirements (permits and similar) for reaching a place."""
        return [
            {
                "id": row["id"],
                "kind": row["kind"],
                "text": row["text"],
                **self._resolve_basis(row["basis"]),
            }
            for row in self._requirements
            if row["place"] == place_id
        ]

    def _systems(self) -> tuple[dict[int, JsonDict], dict[str, JsonDict]]:
        """Star positions documented by place identities, by address and by name."""
        if self._documented_systems is None:
            by_address: dict[int, JsonDict] = {}
            by_name: dict[str, JsonDict] = {}
            for entity_id in self._entities:
                where = self.identity(entity_id) or {}
                if not where.get("star_pos"):
                    continue
                row = {
                    "system": where["system"],
                    "system_address": where.get("system_address"),
                    "star_pos": list(where["star_pos"]),
                    "basis": "documented",
                    "sources": list(where.get("sources") or []),
                }
                if where.get("system_address") is not None:
                    by_address.setdefault(where["system_address"], row)
                by_name.setdefault(_normal(where["system"]), row)
            self._documented_systems = (by_address, by_name)
        return self._documented_systems

    def system_position(
        self, *, system: str | None = None, system_address: int | None = None
    ) -> JsonDict | None:
        """A star system's documented position: Atlas identities, then the gazetteer."""
        by_address, by_name = self._systems()
        found = by_address.get(system_address) if system_address is not None else None
        if found is None and system:
            found = by_name.get(_normal(system))
        if found is not None:
            return {**found, "star_pos": list(found["star_pos"])}
        address = system_address
        if address is None and system:
            address = self._gazetteer_names.get(_normal(system))
        row = self._gazetteer.get(address) if address is not None else None
        if row is None:
            return None
        return {
            "system": row["name"],
            "system_address": row["system_address"],
            "star_pos": list(row["star_pos"]),
            "basis": "gazetteer",
            "sources": list(row["sources"]),
        }

    def position(self, entity_id: str) -> JsonDict | None:
        """Where a place's star system is, for spatial planning, or why it is unknown.

        Never changes :meth:`identity` or location matching: a gazetteer position
        places a system in space and proves nothing about a visit.
        """
        where = self.identity(entity_id)
        if where is None:
            return None
        found = self.system_position(
            system=where.get("system"), system_address=where.get("system_address")
        )
        return {
            "system": where.get("system"),
            "system_address": (found or {}).get("system_address")
            or where.get("system_address"),
            "star_pos": (found or {}).get("star_pos"),
            "basis": (found or {}).get("basis"),
            "precision": where.get("precision"),
        }

    def places(self) -> dict[str, JsonDict]:
        """Every place with a location, as planning records (GKI-06), in pack order.

        ``kind`` is the Atlas kind where a profile gives one, so a Guardian broker
        station reads as a station; ``reached_at`` is the level an observation must
        reach (:meth:`match_support`), ``site`` meaning no observation confirms it.
        ``confirmable`` needs an exact identifier at that level, so ``identity`` is
        ``exact``, ``name_only`` or ``approximate``.
        """
        if self._places is None:
            rows: dict[str, JsonDict] = {}
            for entity_id in self._entities:
                where = self.identity(entity_id)
                if where is None:
                    continue
                view = self._view(entity_id)
                support = self.match_support(entity_id)
                position = self.position(entity_id) or {}
                needed, levels = support["reached_at"], support["levels"]
                # Confirmable only by an exact identifier at the level needed: a
                # station known by name alone can never be confirmed by docking.
                exact = (
                    needed != "site"
                    and levels.get(needed) == "exact"
                    and (needed != "surface" or levels.get("body") == "exact")
                )
                rows[entity_id] = {
                    "id": entity_id,
                    "name": self._entities[entity_id]["name"],
                    "kind": view["kind"],
                    "atlas": view["kind"] in ATLAS_KINDS,
                    "landmark_type": (view.get("attributes") or {}).get(
                        "landmark_type"
                    ),
                    "system": where.get("system"),
                    "system_address": position.get("system_address"),
                    "body": where.get("body"),
                    "station": where.get("station"),
                    "precision": where["precision"],
                    "reached_at": needed,
                    "confirmable": exact,
                    "identity": "approximate"
                    if needed == "site"
                    else ("exact" if exact else "name_only"),
                    "star_pos": position.get("star_pos"),
                    "position_basis": position.get("basis"),
                    # Where on the body, to find it in the game: exact documented
                    # coordinates, or a community-reported position as written.
                    "surface": (
                        f"{where['latitude']}, {where['longitude']}"
                        if where.get("latitude") is not None
                        and where.get("longitude") is not None
                        else (self._entities[entity_id].get("attributes") or {}).get(
                            "coordinates"
                        )
                    ),
                }
            self._places = rows
        return self._places

    def place(self, entity_id: str) -> JsonDict | None:
        found = self.places().get(entity_id)
        return dict(found) if found is not None else None

    def _view(self, entity_id: str) -> JsonDict:
        """The Atlas record for an entity: its own, or its Atlas profile."""
        return self._profiles.get(entity_id) or self._entities[entity_id]

    def _kind(self, entity_id: str) -> str:
        return str(self._view(entity_id)["kind"])

    def _check_identities(self) -> None:
        """Identifiers must agree across every pack, or lookups would contradict."""
        symbols: dict[tuple[str, str], str] = {}
        addresses: dict[str, int] = {}
        names: dict[int, str] = {}
        markets: dict[int, tuple[str, str]] = {}
        bodies: dict[tuple[int, int], str] = {}
        for entity in self._entities.values():
            link = entity.get("inventory")
            if link:
                key = (link["store"], link["symbol"])
                if key in symbols:
                    raise ValueError(
                        f"{entity['id']} and {symbols[key]} map to the same "
                        "inventory record"
                    )
                symbols[key] = entity["id"]
            where = self._view(entity["id"]).get("location")
            if not where:
                continue
            system = _normal(where["system"])
            address = where.get("system_address")
            if address is not None:
                if addresses.setdefault(system, address) != address:
                    raise ValueError(f"{where['system']} has two SystemAddress values")
                if names.setdefault(address, system) != system:
                    raise ValueError(f"SystemAddress {address} names two systems")
            market = where.get("market_id")
            if market is not None:
                station = (system, _normal(where["station"]))
                if markets.setdefault(market, station) != station:
                    raise ValueError(f"MarketID {market} identifies two stations")
            if address is not None and where.get("body_id") is not None:
                body = _normal(where["body"])
                if bodies.setdefault((address, where["body_id"]), body) != body:
                    raise ValueError(f"BodyID {where['body_id']} names two bodies")

    def entity(self, entity_id: str) -> JsonDict | None:
        found = self._entities.get(entity_id)
        return json.loads(json.dumps(found)) if found is not None else None

    def _require(self, entity_id: str, kind: str | None = None) -> JsonDict:
        found = self._entities.get(entity_id)
        if found is None or (kind is not None and found["kind"] != kind):
            raise KeyError(entity_id)
        return found

    def _brief(self, entity_id: str) -> JsonDict:
        entity = self._entities[entity_id]
        return {"id": entity_id, "kind": entity["kind"], "name": entity["name"]}

    def brief(self, entity_id: str) -> JsonDict:
        """Id, Atlas kind (a profile's kind where one exists) and name (GKI-07)."""
        self._require(entity_id)
        return {
            "id": entity_id,
            "kind": self._kind(entity_id),
            "name": self._entities[entity_id]["name"],
        }

    def _out(self, entity_id: str, edge_type: str) -> list[_Edge]:
        return [e for e in self._edges if e.source == entity_id and e.type == edge_type]

    def _in(self, entity_id: str, edge_type: str) -> list[_Edge]:
        return [e for e in self._edges if e.target == entity_id and e.type == edge_type]

    def unlocks(self) -> list[JsonDict]:
        """Every broker offering, in pack order, with what a catalogue lists."""
        rows = []
        for entity in self._entities.values():
            if entity["kind"] != "technology_unlock":
                continue
            attributes = entity["attributes"]
            rows.append(
                {
                    **self._brief(entity["id"]),
                    "summary": entity["summary"],
                    **{
                        key: attributes.get(key)
                        for key in (
                            "category",
                            "family",
                            "variant",
                            "size",
                            "mount",
                            "transaction",
                            "broker_type",
                            "blueprint",
                        )
                    },
                    "recipe_conflict": bool(attributes.get("recipes")),
                }
            )
        return rows

    def recipes(self, unlock_id: str) -> list[JsonDict]:
        """Alternative recipes when sources disagree; empty when there is one."""
        entity = self._require(unlock_id, "technology_unlock")
        return [dict(r) for r in entity["attributes"].get("recipes") or []]

    def requirements(self, unlock_id: str, recipe: str | None = None) -> list[JsonDict]:
        """What an offering consumes, in pack order, with each inventory record.

        Where sources disagree the offering declares alternative recipes; ``recipe``
        picks one (default: the first listed).  An unknown recipe raises KeyError.
        """
        alternatives = [r["id"] for r in self.recipes(unlock_id)]
        if alternatives:
            recipe = recipe or alternatives[0]
            if recipe not in alternatives:
                raise KeyError(recipe)
        elif recipe is not None:
            raise KeyError(recipe)
        rows = []
        for edge in self._out(unlock_id, "requires"):
            if edge.recipe != recipe:
                continue
            entity = self._entities[edge.target]
            rows.append(
                {
                    **self._brief(edge.target),
                    "quantity": edge.quantity,
                    "inventory": dict(entity["inventory"]),
                    "sources": list(edge.sources),
                }
            )
        return rows

    def acquisition(self, entity_id: str) -> JsonDict:
        """Every documented way to obtain an entity, with procedures and places."""
        self._require(entity_id)
        methods = []
        for edge in self._out(entity_id, "obtained_from"):
            activity = self._entities[edge.target]
            # A shared procedure (e.g. the data terminal) is written once and
            # referenced by every activity that uses it.
            procedure = self._entities.get(activity["attributes"].get("procedure", ""))
            steps = activity.get("steps") or (procedure or {}).get("steps") or []
            methods.append(
                {
                    **self._brief(edge.target),
                    "summary": activity["summary"],
                    "attributes": dict(activity["attributes"]),
                    "steps": list(steps),
                    "procedure": self._brief(procedure["id"]) if procedure else None,
                    "claims": list(activity["claims"]),
                    "needs": [
                        {
                            **self._brief(need.target),
                            "quantity": need.quantity,
                            "required": True,
                            "sources": list(need.sources),
                        }
                        for need in self._out(edge.target, "requires")
                    ]
                    + [
                        {
                            **self._brief(hint.target),
                            "quantity": hint.quantity,
                            "required": False,
                            "note": hint.note,
                            "sources": list(hint.sources),
                        }
                        for hint in self._out(edge.target, "related_to")
                        if self._entities[hint.target]["kind"]
                        in {"equipment", "commodity"}
                    ],
                    "locations": self.locations(edge.target),
                    # Conditions specific to this material (GKI-05), and whether
                    # the sources disagree about them.
                    "note": edge.note,
                    "certainty": edge.certainty or "documented",
                    "sources": list(edge.sources),
                }
            )
        return {
            "entity": self.entity(entity_id),
            "methods": methods,
            "documented": bool(methods),
        }

    def locations(self, entity_id: str) -> list[JsonDict]:
        """Documented places for an activity or broker, best-supported first."""
        self._require(entity_id)
        rank = {kind: n for n, kind in enumerate(EVIDENCE_CLASSES)}
        rows = []
        for edge in self._out(entity_id, "located_at"):
            place = self._entities[edge.target]
            rows.append(
                {
                    **self._brief(edge.target),
                    "summary": place["summary"],
                    "attributes": dict(place["attributes"]),
                    "claims": list(place["claims"]),
                    "sources": list(edge.sources),
                }
            )
        return sorted(
            rows,
            key=lambda row: (
                row["kind"] != "location",
                rank.get(row["attributes"].get("evidence"), len(rank)),
                row["attributes"].get("distance_from_sol_ly", float("inf")),
                row["name"],
            ),
        )

    def related(self, entity_id: str) -> list[JsonDict]:
        """Every direct relationship, both ways; ``requires`` reads back as used_for."""
        self._require(entity_id)
        rows = []
        for edge in self._edges:
            if entity_id not in (edge.source, edge.target):
                continue
            outgoing = edge.source == entity_id
            row: JsonDict = {
                "type": edge.type
                if outgoing or edge.type != "requires"
                else "used_for",
                "direction": "outgoing" if outgoing else "incoming",
                "entity": self._brief(edge.target if outgoing else edge.source),
                "quantity": edge.quantity,
                "sources": list(edge.sources),
            }
            for key in ("certainty", "role", "period", "note"):
                if getattr(edge, key):
                    row[key] = getattr(edge, key)
            rows.append(row)
        return rows

    def sources_for(self, entity_id: str) -> list[JsonDict]:
        """The declared sources behind an entity's claims, steps and relationships."""
        entity = self._require(entity_id)
        profile = self._profiles.get(entity_id) or {}
        cited: set[str] = set()
        for claim in [*entity["claims"], *profile.get("claims", [])]:
            cited.update(claim["sources"])
        for step in entity.get("steps") or []:
            cited.update(step["sources"])
        cited.update((self._view(entity_id).get("location") or {}).get("sources") or [])
        for edge in self._edges:
            if entity_id in (edge.source, edge.target):
                cited.update(edge.sources)
        return [source for sid, source in self._sources.items() if sid in cited]

    def source(self, source_id: str) -> JsonDict | None:
        return self._sources.get(source_id)

    def find_by_symbol(self, store: str, symbol: str) -> JsonDict | None:
        key = symbol.casefold()
        for entity in self._entities.values():
            link = entity.get("inventory")
            if link and link["store"] == store and link["symbol"] == key:
                return self.entity(entity["id"])
        return None

    # ── Galactic Atlas (GKI-03) ─────────────────────────────────────────────

    def identity(self, entity_id: str) -> JsonDict | None:
        """Where a place is, in Journal terms, or None for something that is not.

        Atlas places carry a validated ``location``.  Guardian site records from
        earlier packs give a system, a relative body and sometimes a surface position
        from community sources, so they are treated as approximate.
        """
        entity = self._require(entity_id)
        if self._view(entity_id).get("location"):
            return dict(self._view(entity_id)["location"])
        if entity["kind"] != "location":
            return None
        attributes = entity["attributes"]
        row: JsonDict = {
            "system": attributes["system"],
            "precision": "approximate",
            "sources": sorted({s for c in entity["claims"] for s in c["sources"]}),
        }
        if attributes.get("body"):
            row["body"] = f"{attributes['system']} {attributes['body']}"
        if attributes.get("station"):
            row["station"] = attributes["station"]
        return row

    def _granularity(self, identity: JsonDict, kind: str) -> str:
        """The level a Commander has to reach to actually be at this place.

        A site (a landmark, a settlement, a Guardian site) is reached only at its
        exact documented surface position.  Without one it needs ``site``, a level
        no observation confirms: arriving in its system or on its body is never
        reaching an approximately or historically placed site.
        """
        if kind == "station" or (kind == "location" and identity.get("station")):
            return "station"
        if kind == "star_system":
            return "system"
        if kind == "body":
            return "body"
        if identity.get("latitude") is not None and identity["precision"] == "exact":
            return "surface"
        return "site"

    def match_support(self, entity_id: str) -> JsonDict:
        """Which observation levels could ever match this place, and how surely."""
        identity = self.identity(entity_id)
        if identity is None:
            return {"place": False, "levels": {}, "reached_at": None}
        kind = self._kind(entity_id)
        levels = {
            "system": "exact" if identity.get("system_address") else "name_only",
        }
        if identity.get("station"):
            levels["station"] = "exact" if identity.get("market_id") else "name_only"
        if identity.get("body"):
            levels["body"] = (
                "exact"
                if identity.get("body_id") is not None
                and identity.get("system_address")
                else "name_only"
            )
        if identity.get("latitude") is not None:
            levels["surface"] = (
                "exact" if identity["precision"] == "exact" else "unsupported"
            )
        reached_at = self._granularity(identity, kind)
        support: JsonDict = {
            "place": True,
            "precision": identity["precision"],
            "levels": levels,
            "reached_at": reached_at,
            "confirmable": reached_at != "site",
        }
        if reached_at == "surface":
            support["surface"] = {
                "at_site_km": SITE_ARRIVAL_KM,
                "nearby_km": SITE_NEARBY_KM,
                "uncertainty_km": round(position_uncertainty_km(identity), 2),
                "body_radius_km": identity["body_radius_km"],
            }
        return support

    def _system_match(self, identity: JsonDict, seen: JsonDict) -> str | None:
        """``exact`` by SystemAddress, ``name`` by name only, or None."""
        address = seen.get("system_address")
        if address is not None and identity.get("system_address") is not None:
            return "exact" if address == identity["system_address"] else None
        if seen.get("system") and _normal(seen["system"]) == _normal(
            identity["system"]
        ):
            return "name"
        return None

    def match_location(self, observation: JsonDict) -> JsonDict:
        """Every place an observed position matches, and how deeply and surely.

        ``observation`` uses Journal field meanings: ``system_address``, ``system``,
        ``market_id``, ``station``, ``body_id``, ``body``, ``latitude``,
        ``longitude`` and ``player_controlled`` (a Touchdown's ``PlayerControlled``:
        false for a ship recalled without the Commander at the controls, which is
        never more than nearby).  Each match reports the deepest ``level`` confirmed
        (system, body, station, surface), whether that level was matched by an
        exact identifier, and ``reached``: true only when the observation reaches
        the level the place needs.  Arriving in a system never reaches a station,
        body or surface site; a station name alone never matches without its
        system; a site is reached only within :data:`SITE_ARRIVAL_KM` of an exact
        documented position, so one placed approximately or historically is never
        ``reached``.  A surface position on a site's body adds ``surface`` (see
        :func:`surface_proximity`): a landing nearby stays at the body level.
        """
        matches = []
        for entity_id, entity in self._entities.items():
            identity = self.identity(entity_id)
            if identity is None:
                continue
            system = self._system_match(identity, observation)
            if system is None:
                continue
            level, exact, basis = "system", system == "exact", [f"system_{system}"]
            needed = self._granularity(identity, self._kind(entity_id))
            surface: JsonDict | None = None
            if identity.get("station") and (
                observation.get("market_id") is not None or observation.get("station")
            ):
                market = observation.get("market_id")
                if market is not None and identity.get("market_id") is not None:
                    # A different MarketID is a different station, even when the
                    # names agree; the place still counts as in this system.
                    if market == identity["market_id"]:
                        level, exact = "station", True
                        basis = [*basis, "market_id"]
                elif observation.get("station") and _normal(
                    observation["station"]
                ) == _normal(identity["station"]):
                    level, exact, basis = "station", False, [*basis, "station_name"]
            if (
                level != "station"
                and identity.get("body")
                and (observation.get("body_id") is not None or observation.get("body"))
            ):
                body_id = observation.get("body_id")
                if (
                    body_id is not None
                    and identity.get("body_id") is not None
                    and system == "exact"
                ):
                    if body_id == identity["body_id"]:
                        level, exact = "body", True
                        basis = [*basis, "body_id"]
                elif observation.get("body") and _normal(
                    observation["body"]
                ) == _normal(identity["body"]):
                    level, exact, basis = "body", False, [*basis, "body_name"]
                if (
                    level == "body"
                    and needed == "surface"
                    and observation.get("latitude") is not None
                    and observation.get("longitude") is not None
                ):
                    surface = surface_proximity(
                        identity, observation["latitude"], observation["longitude"]
                    )
                    if (
                        surface["state"] == "at_site"
                        and observation.get("player_controlled") is False
                    ):
                        # A ship recalled to the Commander's SRV lands where it is
                        # sent, not where the Commander is: near, never a visit.
                        surface = {**surface, "state": "nearby", "ship_only": True}
                    if surface["state"] == "at_site":
                        level, basis = "surface", [*basis, "surface_position"]
            match: JsonDict = {
                **self._brief(entity_id),
                "level": level,
                "exact": exact,
                "basis": basis,
                "reached": level == needed,
                "needs": needed,
            }
            if surface is not None:
                match["surface"] = surface
            matches.append(match)
        order = {"surface": 0, "station": 1, "body": 2, "system": 3}
        matches.sort(key=lambda m: (not m["reached"], order[m["level"]], m["name"]))
        return {
            "observation": {k: v for k, v in observation.items() if v is not None},
            "matches": matches,
            "surface_policy": {
                "at_site_km": SITE_ARRIVAL_KM,
                "nearby_km": SITE_NEARBY_KM,
                "measure": "great-circle distance on the documented body radius, "
                "allowing for the documented position's rounding",
            },
        }

    def knowledge_for_system(
        self, *, system_address: int | None = None, system: str | None = None
    ) -> JsonDict:
        """Documented places in a system and the subjects directly tied to them."""
        found = self.match_location(
            {"system_address": system_address, "system": system}
        )["matches"]
        place_ids = {m["id"] for m in found}
        associated: dict[str, JsonDict] = {}
        for edge in self._edges:
            for here, there in ((edge.target, edge.source), (edge.source, edge.target)):
                if here in place_ids and there not in place_ids:
                    associated.setdefault(there, self._brief(there))
        return {
            "places": found,
            "associated": sorted(associated.values(), key=lambda row: row["name"]),
        }

    def atlas(self) -> list[JsonDict]:
        """Every Atlas subject with what a browser lists, in pack order."""
        rows = []
        for entity_id in self._entities:
            entity = self._view(entity_id)
            if entity["kind"] not in ATLAS_KINDS:
                continue
            identity = self.identity(entity_id)
            rows.append(
                {
                    **self._brief(entity_id),
                    "kind": entity["kind"],
                    "category": atlas_category(entity["kind"]),
                    "aliases": list(entity["aliases"]),
                    "summary": entity["summary"],
                    "significance": entity["attributes"]["significance"],
                    "period": entity["attributes"].get("period"),
                    "system": (identity or {}).get("system")
                    or self._context_system(entity_id),
                    "topics": sorted({c["topic"] for c in entity["claims"]}),
                    "destination": bool(identity),
                    "practical": bool(self._opportunities(entity_id)),
                }
            )
        return rows

    def _context_system(self, entity_id: str) -> str | None:
        """The system a non-place subject is tied to through its first place edge."""
        for edge in self._edges:
            for here, there in ((edge.source, edge.target), (edge.target, edge.source)):
                if here == entity_id and self._view(there).get("location"):
                    return str(self._view(there)["location"]["system"])
        return None

    def _opportunities(self, place_id: str) -> list[_Edge]:
        """Activities documented at a place (``located_at`` edges into it)."""
        return [
            edge
            for edge in self._in(place_id, "located_at")
            if self._entities[edge.source]["kind"] == "activity"
        ]

    def _parents(self, entity_id: str) -> list[JsonDict]:
        """The ``located_in`` chain upward, nearest first."""
        chain: list[JsonDict] = []
        current, seen = entity_id, {entity_id}
        while True:
            parent = next(iter(self._out(current, "located_in")), None)
            if parent is None or parent.target in seen:
                return chain
            seen.add(parent.target)
            chain.append(self._brief(parent.target))
            current = parent.target

    def atlas_entry(self, entity_id: str) -> JsonDict:
        """Everything the Atlas inspector shows for one subject."""
        self._require(entity_id)
        entity = self._view(entity_id)
        practical = []
        for edge in self._opportunities(entity_id):
            activity = self._entities[edge.source]
            practical.append(
                {
                    **self._brief(edge.source),
                    "summary": activity["summary"],
                    "attributes": dict(activity["attributes"]),
                    "steps": list(activity.get("steps") or []),
                    "claims": list(activity["claims"]),
                    "materials": [
                        {
                            **self._brief(item.source),
                            "inventory": dict(
                                self._entities[item.source].get("inventory") or {}
                            ),
                            "sources": list(item.sources),
                        }
                        for item in self._in(edge.source, "obtained_from")
                    ],
                    "sources": list(edge.sources),
                }
            )
        practical_ids = {row["id"] for row in practical}
        connections = [
            {
                **row,
                "entity": {
                    **row["entity"],
                    "kind": self._kind(row["entity"]["id"]),
                    "category": atlas_category(self._kind(row["entity"]["id"])),
                    "atlas": self._kind(row["entity"]["id"]) in ATLAS_KINDS,
                },
            }
            for row in self.related(entity_id)
            if row["entity"]["id"] not in practical_ids
        ]
        identity = self.identity(entity_id)
        base = self._entities[entity_id]
        return {
            "entity": json.loads(json.dumps(entity)),
            # A profile adds Atlas information to a record another pack keeps, such
            # as a Guardian broker station; that record is shown as reference.
            "reference": {
                "pack_id": base["pack_id"],
                "summary": base["summary"],
                "claims": list(base["claims"]),
            }
            if entity_id in self._profiles
            else None,
            "category": atlas_category(entity["kind"]),
            "parents": self._parents(entity_id),
            "connections": connections,
            "practical": practical,
            "location": identity,
            "match_support": self.match_support(entity_id),
            "sources": self.sources_for(entity_id),
        }

    def related_destinations(self, entity_id: str) -> list[JsonDict]:
        """Places reachable within two documented Atlas relationships, nearest first.

        Only Atlas relationship types are followed, so a shared technology broker
        does not make every broker station a "related" destination.
        """
        self._require(entity_id)
        frontier, seen, rows = [entity_id], {entity_id}, []
        for hops in (1, 2):
            following = []
            for current in frontier:
                for edge in self._edges:
                    if current not in (edge.source, edge.target):
                        continue
                    if edge.type not in ATLAS_RELATIONSHIPS:
                        continue
                    other = edge.target if edge.source == current else edge.source
                    if other in seen:
                        continue
                    seen.add(other)
                    following.append(other)
                    identity = self.identity(other)
                    if identity is not None:
                        rows.append(
                            {
                                **self._brief(other),
                                "hops": hops,
                                "via": edge.type,
                                # The subject a second-hop place is reached through,
                                # so the link is never mistaken for a direct one.
                                "through": None
                                if current == entity_id
                                else self._brief(current),
                                "system": identity["system"],
                                "precision": identity["precision"],
                            }
                        )
            frontier = following
        return rows


def atlas_category(kind: str) -> str:
    """The browsing group an entity kind belongs to."""
    if kind in {*PLACE_KINDS, "vessel", "location"}:
        return "place"
    if kind in {"event", "discovery"}:
        return "event"
    if kind in {"person", "organization", "mystery"}:
        return kind
    return "reference"


def _read(path: Path) -> JsonDict:
    return validate_pack(json.loads(path.read_text(encoding="utf-8")))


def load_packs(
    directory: Path = PACK_DIR, restricted: Path = RESTRICTED_DIR
) -> list[JsonDict]:
    """Shipped packs, plus development-only packs where the restricted folder exists.

    ``pending_review`` packs are never loaded.  Builds without the restricted folder
    (every public, preview and release build) simply have the shipped packs.
    """
    packs: list[JsonDict] = []
    for path in sorted(directory.glob("*.json")):
        pack = _read(path)
        if not pack["distribution"]["shipped"]:
            raise ValueError(f"{path.name} is restricted but filed with shipped packs")
        packs.append(pack)
    for path in sorted(restricted.glob("*.json")) if restricted.is_dir() else []:
        pack = _read(path)
        if pack["distribution"]["shipped"]:
            raise ValueError(f"{path.name} is shippable but filed as restricted")
        if pack["distribution"]["class"] == "development_only":
            packs.append(pack)
    if not packs:
        raise FileNotFoundError(directory)
    return packs


def notice_markdown(directory: Path = PACK_DIR) -> list[str]:
    """Attribution lines for THIRD_PARTY_NOTICES, built from the shipped packs only."""
    lines = ["## Game knowledge sources", ""]
    lines.append(
        "Galactic knowledge packs hold original OmniCOVAS records of Elite Dangerous "
        "game facts. The facts were researched from the references below, which are "
        "credited for transparency. Unless a pack states a content licence, no text, "
        "images, tables or code from these references are included."
    )
    for path in sorted(directory.glob("*.json")):
        pack = _read(path)
        if not pack["distribution"]["shipped"]:
            continue
        lines += ["", f"### {pack['title']} ({pack['pack_id']} {pack['version']})", ""]
        terms = pack["distribution"].get("content_license")
        if terms:
            lines += [f"Includes content under {terms['name']} ({terms['url']}).", ""]
            lines += [terms["notice"], ""]
        for source in pack["sources"]:
            if source["kind"] == "omnicovas_reference":
                continue
            revision = source.get("revision")
            detail = [
                f"revision {revision['revision_id']}" if revision else None,
                f"reviewed {source['accessed']}",
                source["licence"],
                "not retrieved" if source["reuse"] == "not_retrieved" else None,
            ]
            lines.append(
                f"- {source['name']}: <{source['url']}> "
                f"({'; '.join(d for d in detail if d)})"
            )
    lines.append("")
    return lines


@lru_cache(maxsize=1)
def index() -> KnowledgeIndex:
    """The bundled knowledge, validated once per process."""
    return KnowledgeIndex(load_packs())


def catalog() -> JsonDict:
    """Pack-level summary for the UI, or an explicit 'unavailable' state.

    ``reason`` separates a missing pack (``not_included``: nothing to load, e.g. a
    stripped install) from a defect (``invalid``: a pack is present but fails
    validation or is filed in the wrong folder).
    """
    try:
        knowledge = index()
    except FileNotFoundError:
        return {
            "state": "unavailable",
            "reason": "not_included",
            "packs": [],
            "unlocks": [],
        }
    except (OSError, ValueError):
        return {"state": "unavailable", "reason": "invalid", "packs": [], "unlocks": []}
    return {
        "state": "available",
        "network_access": "none",
        "packs": [
            {
                key: pack[key]
                for key in (
                    "pack_id",
                    "version",
                    "reviewed_at",
                    "title",
                    "scope",
                    "game_version",
                    "rights_basis",
                    "distribution",
                    "unsupported",
                )
            }
            | {
                "coverage": {
                    "entities": len(pack["entities"]),
                    "relationships": len(pack["relationships"]),
                    "sources": len(pack["sources"]),
                }
            }
            for pack in knowledge.packs
        ],
        "unlocks": knowledge.unlocks(),
    }
