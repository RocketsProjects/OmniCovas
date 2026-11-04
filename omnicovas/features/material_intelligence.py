"""Material acquisition intelligence (GKI-05): shortage → method → place → next step.

Pure derivation; nothing is stored and nothing is recalculated that another module
owns:

* **Shortages** are the portfolio's (``engineering_progression.portfolio``): its
  per-build ``required``, ``reserved`` and ``deficit`` in priority order.  An
  unknown inventory stays unknown; no shortage is guessed.
* **Trading** is the Material Trader's own plan for the same scope
  (``material_trader.payload``), which never spends stock any active build has
  reserved.  This module only reads which planned trades feed a material and what
  remains to collect.  Without the development-only trader rules it names the
  trader for the category and states that no rates are included.
* **Collecting** is the knowledge index's documented ``obtained_from`` methods,
  with their conditions, equipment, steps and places.

Recommendations are deterministic and explained.  Methods are never ranked by
speed or yield, because no reliable source documents collection rates; activities
are ordered by how many of the Commander's current shortages they serve.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from omnicovas.features import commander_context
from omnicovas.features.galactic_knowledge import KnowledgeIndex

JsonDict = dict[str, Any]

VERSION = "material-intelligence-v1"
GUIDE_NOT_RANKED = (
    "Collection rates are not documented, so methods are not ranked by speed or yield."
)
NOT_RANKED = (
    f"{GUIDE_NOT_RANKED} Activities are ordered by how many of your shortages "
    "they serve."
)
# Methods a Commander cannot choose to perform for a particular material.
UNPLANNABLE = {"mission-rewards"}
CATEGORY_LABEL = {"raw": "Raw", "manufactured": "Manufactured", "encoded": "Encoded"}


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ── Material identity ───────────────────────────────────────────────────────


def material_record(knowledge: KnowledgeIndex | None, symbol: str) -> JsonDict | None:
    if knowledge is None:
        return None
    return knowledge.find_by_symbol("materials", symbol)


def _identity(record: JsonDict | None, symbol: str, fallback_name: str) -> JsonDict:
    inventory = (record or {}).get("inventory") or {}
    return {
        "material_id": symbol,
        "entity_id": record["id"] if record else None,
        "name": record["name"] if record else fallback_name,
        "category": inventory.get("category"),
        "grade": inventory.get("grade"),
    }


# ── High Grade Emissions fit, from the Commander's own observed system ─────


ALIGNED = ("Federation", "Empire")


def _states(faction: JsonDict) -> set[str]:
    states = {
        str(row.get("State"))
        for row in faction.get("ActiveStates") or []
        if isinstance(row, dict)
    }
    if faction.get("FactionState"):
        states.add(str(faction["FactionState"]))
    return states - {"", "None"}


def _words(state: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", state)


def hge_fit(rules: list[JsonDict], system: JsonDict | None, now: datetime) -> JsonDict:
    """Which very rare materials this system's High Grade Emissions could hold.

    Reads the Journal-projected ``local_system_context`` (FSDJump or Location).
    Each signal belongs to one minor faction:

    * allegiance materials follow the system's allegiance (its controlling
      faction's); an aligned faction in a system of another allegiance is only
      ``uncertain``, because sources differ on whose allegiance counts;
    * state materials follow a faction's own states.  A Federation or Empire
      faction never gives them, and in a Federation or Empire system they are
      ``uncertain``, since signals there are reported to carry no state.

    With only the controlling faction recorded, other factions are not checked.
    It never claims a signal is present.  Freshness is the GKI-04 Commander
    Context classification, never ``current``: the last observed system may not
    be where the Commander is.
    """
    system = system or {}
    name = system.get("star_system")
    allegiance = system.get("system_allegiance") or None
    factions = [f for f in system.get("factions") or [] if isinstance(f, dict)]
    coverage = "factions"
    controlling = system.get("system_faction")
    if not factions and isinstance(controlling, dict) and controlling.get("Name"):
        # System-level information only: the controlling faction and its state.
        factions = [{**controlling, "Allegiance": allegiance}]
        coverage = "controlling_faction"
    if not name or (not factions and not allegiance):
        return {
            "state": "not_observed",
            "explanation": "No faction details from your current or last system are "
            "recorded, so High Grade Emissions cannot be checked against it.",
        }
    population = system.get("population")
    lead = (controlling or {}).get("Name") if isinstance(controlling, dict) else None
    found: dict[str, list[JsonDict]] = {}

    def add(rule: JsonDict, faction: Any, because: str, confidence: str) -> None:
        for symbol in rule["materials"]:
            found.setdefault(symbol, []).append(
                {"faction": faction, "because": because, "confidence": confidence}
            )

    for rule in rules:
        if rule.get("allegiance"):
            if allegiance in rule["allegiance"]:
                add(rule, lead, f"the system is {allegiance}-aligned", "possible")
                continue
            for faction in factions:
                if faction.get("Allegiance") in rule["allegiance"]:
                    who = faction.get("Name")
                    add(
                        rule,
                        who,
                        f"{who} is {faction['Allegiance']}-aligned, but the system "
                        f"is {allegiance or 'of unrecorded allegiance'}",
                        "uncertain",
                    )
            continue
        minimum = rule.get("min_population")
        for faction in factions:
            if faction.get("Allegiance") in ALIGNED:
                continue  # Federation and Empire factions give only their own.
            matched = sorted(_states(faction) & set(rule.get("states") or []))
            if not matched:
                continue
            because = f"{faction.get('Name')} is in {_words(matched[0])}"
            confidence = "possible"
            if minimum and not isinstance(population, int):
                because += ", but the population is not recorded"
                confidence = "uncertain"
            elif minimum and population < minimum:
                continue
            if allegiance in ALIGNED:
                because += (
                    f", but signals in {allegiance} systems are reported to carry "
                    "the allegiance material"
                )
                confidence = "uncertain"
            add(rule, faction.get("Name"), because, confidence)
    limits = [
        "Each signal belongs to one faction, and which one is only known once "
        "you drop in."
    ]
    if coverage == "controlling_faction":
        limits.append(
            "Only the controlling faction was recorded, so other factions' states "
            "are unknown."
        )
    return {
        "state": "evaluated",
        "system": name,
        "system_allegiance": allegiance,
        "coverage": coverage,
        "population": population,
        "observed_at": system.get("event_timestamp"),
        "source_event": system.get("source_event"),
        "freshness": commander_context.classify(
            _parse(system.get("event_timestamp")), live=False, now=now
        ),
        "materials": found,
        "limits": limits,
        "explanation": "From the allegiance and factions recorded when you arrived. "
        "Faction states change, so this says what is possible there, not what "
        "is present.",
    }


# ── Methods ─────────────────────────────────────────────────────────────────


def _places(
    knowledge: KnowledgeIndex, method: JsonDict, material_name: str
) -> list[JsonDict]:
    rows = []
    for place in method.get("locations") or []:
        attributes = place.get("attributes") or {}
        reported = attributes.get("reported_materials")
        # A shard site is only listed for the materials reported there.
        if reported and material_name not in reported:
            continue
        # The index resolves both Atlas locations and older site records.
        where = knowledge.identity(place["id"]) or {}
        surface = (
            f"{where['latitude']}, {where['longitude']}"
            if where.get("latitude") is not None and where.get("longitude") is not None
            else attributes.get("coordinates")
        )
        rows.append(
            {
                "id": place["id"],
                "kind": place["kind"],
                "name": place["name"],
                "system": where.get("system"),
                "body": where.get("body"),
                "coordinates": surface,
                "evidence": attributes.get("evidence"),
                "reported_materials": reported,
                # Atlas places keep their history (GKI-03).
                "atlas": place["kind"] != "location",
            }
        )
    return rows


def _claims(knowledge: KnowledgeIndex, method: JsonDict, name: str) -> list[JsonDict]:
    """The activity's claims that apply to this material.

    An activity record shared with another pack can carry claims about particular
    materials (the Guardian pack's "A known source of Focus Crystals").  A claim
    naming materials the activity gives is shown only for those materials; a
    general claim is shown for every one.
    """
    gives = {
        row["entity"]["name"]
        for row in knowledge.related(method["id"])
        if row["type"] == "obtained_from" and row["direction"] == "incoming"
    }
    kept = []
    for claim in method.get("claims") or []:
        named = {
            other
            for other in gives
            if re.search(rf"\b{re.escape(other)}\b", claim["text"])
        }
        if named and name not in named:
            continue
        kept.append({"text": claim["text"], "evidence": claim["evidence"]})
    return kept


def _method(
    knowledge: KnowledgeIndex,
    method: JsonDict,
    material: JsonDict,
    fit: JsonDict | None,
) -> JsonDict:
    entity = knowledge.entity(method["id"]) or {}
    places = _places(knowledge, method, material["name"])
    view: JsonDict = {
        "id": method["id"],
        "name": method["name"],
        "summary": method["summary"],
        "note": method.get("note"),
        "certainty": method.get("certainty", "documented"),
        "steps": [step["text"] for step in method.get("steps") or []],
        "equipment": [
            {"id": need["id"], "name": need["name"], "required": need["required"]}
            for need in method.get("needs") or []
        ],
        "places": places,
        "claims": _claims(knowledge, method, material["name"]),
        "sources": list(dict.fromkeys(method.get("sources") or [])),
        "plannable": method["id"] not in UNPLANNABLE,
    }
    rules = (entity.get("attributes") or {}).get("hge_rules")
    if rules and fit is not None:
        found = (fit.get("materials") or {}).get(material["material_id"], [])
        possible = [f for f in found if f["confidence"] == "possible"]
        uncertain = [f for f in found if f["confidence"] == "uncertain"]
        if fit.get("state") != "evaluated":
            state = "not_observed"
        elif possible:
            state = "possible"
        elif uncertain:
            state = "uncertain"
        elif fit.get("coverage") == "controlling_faction":
            state = "unchecked"  # other factions were not recorded
        else:
            state = "not_here"
        view["here"] = {
            "state": state,
            "system": fit.get("system"),
            "observed_at": fit.get("observed_at"),
            "freshness": fit.get("freshness"),
            "factions": possible or uncertain,
        }
    return view


def guide(
    knowledge: KnowledgeIndex | None,
    symbol: str,
    *,
    fallback_name: str | None = None,
    system: JsonDict | None = None,
    now: datetime | None = None,
) -> JsonDict:
    """Every documented way to obtain one material, for any material."""
    now = now or datetime.now(timezone.utc)
    record = material_record(knowledge, symbol)
    material = _identity(record, symbol, fallback_name or symbol)
    if knowledge is None or record is None:
        return {
            "version": VERSION,
            "material": material,
            "state": "knowledge_unavailable" if knowledge is None else "undocumented",
            "methods": [],
        }
    rules = _hge_rules(knowledge)
    fit = hge_fit(rules, system, now) if rules else None
    methods = [
        _method(knowledge, method, material, fit)
        for method in knowledge.acquisition(record["id"])["methods"]
        if method["id"] != "material-trader-exchange"
    ]
    methods.sort(key=lambda m: (not m["plannable"], m["certainty"] != "documented"))
    return {
        "version": VERSION,
        "material": material,
        "state": "documented" if methods else "undocumented",
        "methods": methods,
        "trader": f"{CATEGORY_LABEL.get(material['category'] or '', 'Material')} "
        "Material Trader",
        "ranking": GUIDE_NOT_RANKED,
    }


def _hge_rules(knowledge: KnowledgeIndex) -> list[JsonDict]:
    entity = knowledge.entity("high-grade-emissions")
    return list(((entity or {}).get("attributes") or {}).get("hge_rules") or [])


# ── Shortages, trading and recommendations ─────────────────────────────────


def _shortages(builds: list[JsonDict], scope: str) -> list[JsonDict]:
    rows: dict[str, JsonDict] = {}
    for build in builds:
        if scope != "all" and build["build_plan_id"] != scope:
            continue
        for row in build.get("materials") or []:
            symbol = str(row["material_id"])
            entry = rows.setdefault(
                symbol,
                {
                    "material_id": symbol,
                    "display_name": row.get("display_name") or symbol,
                    "required": 0,
                    "reserved": 0,
                    "short": 0,
                    "unknown": False,
                    "builds": [],
                },
            )
            deficit = row.get("deficit")
            entry["required"] += int(row.get("required") or 0)
            entry["reserved"] += int(row.get("reserved") or 0)
            if deficit is None:
                entry["unknown"] = True
            else:
                entry["short"] += int(deficit)
            entry["builds"].append(
                {
                    "build_plan_id": build["build_plan_id"],
                    "title": build["title"],
                    "priority": build.get("priority"),
                    "required": row.get("required"),
                    "reserved": row.get("reserved"),
                    "deficit": deficit,
                }
            )
    return [row for row in rows.values() if row["unknown"] or row["short"] > 0]


def _trade(
    trader: JsonDict, scope: str, symbol: str, category: str | None, known: bool
) -> JsonDict:
    label = f"{CATEGORY_LABEL.get(category or '', 'Material')} Material Trader"
    if trader.get("state") != "available":
        return {
            "state": "rates_unavailable",
            "trader": label,
            "explanation": f"A {label} can exchange {category or 'these'} materials "
            "within its category, but exchange rates are not included in this build, "
            "so OmniCOVAS cannot plan or price a trade.",
        }
    if not known:
        return {
            "state": "inventory_unknown",
            "trader": label,
            "explanation": "Your material stock is not known, so OmniCOVAS cannot say "
            "what you could spare for a trade.",
        }
    plan = (trader.get("plans") or {}).get(scope) or {}
    trades = [t for t in plan.get("trades") or [] if t.get("for_material") == symbol]
    remaining = next(
        (r for r in plan.get("remaining") or [] if r.get("material_id") == symbol),
        None,
    )
    steps = [
        {
            "give": t["give_name"],
            "give_id": t["give"],
            "pay": t["pay_total"],
            "receive": t["receive_total"],
            "take": t["take_name"],
            "chain": t.get("chain", False),
            "why": t.get("why"),
        }
        for t in trades
    ]
    left = int(remaining["collect"]) if remaining else 0
    if trades and not left:
        state = "covers"
    elif trades:
        state = "partial"
    else:
        state = "none"
    return {
        "state": state,
        "trader": label,
        "trades": steps,
        "still_to_collect": left,
        "reason": (remaining or {}).get("reason"),
        "explanation": {
            "covers": "Your spare stock covers this shortage at a Material Trader. "
            "Only stock no active build has reserved is used.",
            "partial": "Spare stock covers part of this shortage; the rest must be "
            "collected.",
            "none": "No spare stock can be traded for this without taking stock an "
            "active build has reserved.",
        }[state],
    }


def _recommend(row: JsonDict, trade: JsonDict, methods: list[JsonDict]) -> JsonDict:
    plannable = [m for m in methods if m["plannable"]]
    reasons: list[str] = []
    if row["unknown"]:
        strategy = "inventory_unknown"
        headline = "Stock unknown"
        reasons.append(
            "Your Materials record is not complete, so the shortage is not known. "
            "These are the documented ways to get it."
        )
    elif trade["state"] == "covers":
        strategy = "trade"
        headline = "Trade spare stock"
        reasons.append(trade["explanation"])
        if plannable:
            reasons.append("Collecting is listed as an alternative.")
    elif trade["state"] == "partial":
        strategy = "trade_then_collect"
        headline = "Trade, then collect the rest"
        reasons.append(trade["explanation"])
    elif plannable:
        strategy = "collect"
        headline = "Collect"
        if trade["state"] == "none":
            reasons.append(trade["explanation"])
    elif methods:
        strategy = "unplannable"
        headline = "Only from mission rewards"
        reasons.append(
            "The only documented source cannot be chosen in advance. Watch mission "
            "rewards, or trade for it."
        )
    else:
        strategy = "no_documented_source"
        headline = "No documented source"
        reasons.append("No source is documented for this material.")
    best = max(plannable, key=lambda m: len(m.get("serves", [])), default=None)
    if best and best.get("serves"):
        names = ", ".join(s["name"] for s in best["serves"])
        reasons.append(f"{best['name']} also gives {names}, which you are short of.")
    here = [m for m in plannable if (m.get("here") or {}).get("state") == "possible"]
    if here:
        reasons.append(
            f"High Grade Emissions in {here[0]['here']['system']}, your last known "
            "system, can carry it, from the factions recorded on arrival."
        )
    if trade["state"] == "rates_unavailable":
        reasons.append(trade["explanation"])
    return {"strategy": strategy, "headline": headline, "reasons": reasons}


def _destinations(materials: list[JsonDict]) -> list[JsonDict]:
    """Documented places that serve current shortages (for a GKI-06 planner).

    Built from each material's own methods, so a shard site lists only the
    materials reported there.  Places are documented, never visited or current.
    """
    by_place: dict[str, JsonDict] = {}
    for material in materials:
        for method in material["methods"]:
            if not method["plannable"]:
                continue
            for place in method["places"]:
                entry = by_place.setdefault(
                    place["id"],
                    {
                        **{k: v for k, v in place.items() if k != "reported_materials"},
                        "activities": [],
                        "materials": [],
                    },
                )
                if method["id"] not in entry["activities"]:
                    entry["activities"].append(method["id"])
                if all(
                    m["material_id"] != material["material_id"]
                    for m in entry["materials"]
                ):
                    entry["materials"].append(
                        {
                            "material_id": material["material_id"],
                            "name": material["name"],
                            "short": material["short"],
                        }
                    )
    return sorted(
        by_place.values(), key=lambda p: (-len(p["materials"]), p["name"].casefold())
    )


def build(
    knowledge: KnowledgeIndex | None,
    builds: list[JsonDict],
    inventory: JsonDict,
    trader: JsonDict,
    *,
    system: JsonDict | None = None,
    scope: str = "all",
    now: datetime | None = None,
) -> JsonDict:
    """The acquisition intelligence for the active builds in ``scope``."""
    now = now or datetime.now(timezone.utc)
    known = inventory.get("state") == "verified_local"
    base: JsonDict = {
        "version": VERSION,
        "scope": scope,
        "inventory_state": inventory.get("state", "unknown"),
        "ranking": NOT_RANKED,
    }
    if knowledge is None:
        return {
            **base,
            "state": "knowledge_unavailable",
            "materials": [],
            "activities": [],
            "destinations": [],
        }
    rules = _hge_rules(knowledge)
    fit = hge_fit(rules, system, now) if rules else None
    rows = _shortages(builds, scope)
    short_symbols = {row["material_id"] for row in rows}
    materials: list[JsonDict] = []
    by_activity: dict[str, JsonDict] = {}
    for row in rows:
        record = material_record(knowledge, row["material_id"])
        identity = _identity(record, row["material_id"], row["display_name"])
        methods = (
            [
                _method(knowledge, method, identity, fit)
                for method in knowledge.acquisition(record["id"])["methods"]
                if method["id"] != "material-trader-exchange"
            ]
            if record
            else []
        )
        for method in methods:
            entry = by_activity.setdefault(
                method["id"],
                {
                    "id": method["id"],
                    "name": method["name"],
                    "summary": method["summary"],
                    "plannable": method["plannable"],
                    "equipment": method["equipment"],
                    "places": {},
                    "materials": [],
                    "units": 0,
                    "unknown_units": False,
                },
            )
            entry["materials"].append(
                {
                    "material_id": row["material_id"],
                    "name": identity["name"],
                    "short": None if row["unknown"] else row["short"],
                    "note": method["note"],
                    "certainty": method["certainty"],
                    "here": method.get("here"),
                }
            )
            if row["unknown"]:
                entry["unknown_units"] = True
            else:
                entry["units"] += row["short"]
            for place in method["places"]:
                entry["places"].setdefault(place["id"], place)
        trade = _trade(trader, scope, row["material_id"], identity["category"], known)
        materials.append(
            {
                **identity,
                "required": row["required"],
                "reserved": row["reserved"],
                "short": None if row["unknown"] else row["short"],
                "builds": row["builds"],
                "trade": trade,
                "methods": methods,
            }
        )
    # Which other shortages each method also serves (multi-objective).
    for material in materials:
        for method in material["methods"]:
            others = by_activity[method["id"]]["materials"]
            method["serves"] = [
                {"material_id": o["material_id"], "name": o["name"]}
                for o in others
                if o["material_id"] != material["material_id"]
            ]
        material["methods"].sort(
            key=lambda m: (
                not m["plannable"],
                -len(m["serves"]),
                # A documented destination is something to act on now.
                not m["places"],
                m["certainty"] != "documented",
                m["name"],
            )
        )
        material["recommendation"] = _recommend(
            {"unknown": material["short"] is None},
            material["trade"],
            material["methods"],
        )
    activities = sorted(
        (
            {**entry, "places": list(entry["places"].values())}
            for entry in by_activity.values()
        ),
        key=lambda a: (
            not a["plannable"],
            -len(a["materials"]),
            -a["units"],
            not a["places"],
            a["name"],
        ),
    )
    materials.sort(
        key=lambda m: (m["short"] is None, -(m["short"] or 0), m["name"].casefold())
    )
    return {
        **base,
        "state": "available" if materials else "no_shortages",
        "short_materials": sorted(short_symbols),
        "materials": materials,
        "activities": activities,
        "destinations": _destinations(materials),
        "high_grade_emissions": fit,
        "caveats": [
            "Sources and conditions are community-documented and can change with "
            "game updates; each method lists its sources.",
            "Drops are not guaranteed amounts; shortfalls are shown, not promised.",
        ],
    }


def scopes(
    knowledge: KnowledgeIndex | None,
    builds: list[JsonDict],
    inventory: JsonDict,
    trader: JsonDict,
    *,
    system: JsonDict | None = None,
    now: datetime | None = None,
) -> JsonDict:
    """Intelligence for all active builds and for each build on its own."""
    ids = ["all", *(str(b["build_plan_id"]) for b in builds)]
    return {
        scope: build(
            knowledge, builds, inventory, trader, system=system, scope=scope, now=now
        )
        for scope in ids
    }
