"""Technology unlock readiness: reference requirements against observed Commander data.

The Galactic Knowledge Core says what an unlock needs and how each item is obtained.
This module compares that with what the Commander's own data can actually show,
keeping the two authorities apart:

* Materials come from the existing Journal inventory projection
  (``engineering_progression.horizons_inventory``).  Without a complete ``Materials``
  baseline every material quantity is unknown, never zero.
* Commodities come from the current ship's cargo snapshot.  Only a cargo record that
  lists items can show a count; anything else is unknown.  Cargo held elsewhere
  (another ship, a fleet carrier) is not visible here and is said so.
* Unlock state comes only from stored Journal evidence.  A missing record never means
  "locked": the history on this machine may simply not reach back far enough.

Nothing here writes data or changes observed inventory.  Commander-confirmed checklist
progress lives on an ordinary Engineering goal and is reported separately from
observations.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.state_manager import CargoHoldSnapshot
from omnicovas.db.models import JournalEvent
from omnicovas.features import engineering_progression
from omnicovas.features.engineering import EngineeringGoalRecord
from omnicovas.features.galactic_knowledge import KnowledgeIndex

JsonDict = dict[str, Any]

VERSION = "technology-unlock-readiness-v2"
# Per-item purchases are planned for a requested number of items; one hand-in each.
MAX_ITEMS = 20
GOAL_KINDS = frozenset({"guardian_tech", "tech_broker_unlock"})
# Events that can show a module was owned.  Buying one requires the unlock first.
_MODULE_EVIDENCE = {
    "Loadout": ("Modules", "Item"),
    "StoredModules": ("Items", "Name"),
    "ModuleBuy": (None, "BuyItem"),
    "ModuleRetrieve": (None, "RetrievedItem"),
    "ModuleStore": (None, "StoredItem"),
}


def _symbol(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().strip("$").removesuffix("_name;").casefold()


def _payload(row: JournalEvent) -> JsonDict:
    try:
        value = json.loads(row.raw_json)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def material_row(requirement: JsonDict, inventory: JsonDict) -> JsonDict:
    """Owned, missing and freshness for one material requirement."""
    symbol = requirement["inventory"]["symbol"]
    state = inventory.get("state")
    origin = {
        "source": "Journal Materials",
        "scope": "Ship engineering materials",
        "observed_at": inventory.get("last_event_at") or inventory.get("observed_at"),
        "truth_class": "commander_observed",
    }
    if state not in {"verified_local", "partial_inconsistent"}:
        return {
            "owned": None,
            "missing": None,
            "quantity_state": "unknown",
            "reason": "No complete Materials record from your Journal is stored yet. "
            "Log in to Elite Dangerous with OmniCOVAS running to record one.",
            "origin": {**origin, "observed_at": None},
        }
    row = next(
        (
            item
            for item in inventory.get("materials", [])
            if str(item.get("material_id")) == symbol
        ),
        None,
    )
    if row is not None and row.get("quantity_state") != "observed":
        return {
            "owned": None,
            "missing": None,
            "quantity_state": "unknown",
            "reason": "Your Journal history for this material does not reconcile. "
            "A fresh Materials record (relog) will settle it.",
            "origin": origin,
        }
    # A complete Materials baseline lists every material held, so an absent
    # material is an observed zero, exactly as the Materials workspace treats it.
    owned = int(row["count"]) if row is not None else 0
    return {
        "owned": owned,
        "missing": max(requirement["quantity"] - owned, 0),
        "quantity_state": "observed",
        "reason": None,
        "origin": origin,
    }


def cargo_row(requirement: JsonDict, cargo: CargoHoldSnapshot | None) -> JsonDict:
    """Owned, missing and freshness for one commodity requirement."""
    origin = {
        "source": "Journal Cargo",
        "scope": "Current ship's cargo hold",
        "observed_at": None,
        "truth_class": "commander_observed",
    }
    if cargo is None:
        return {
            "owned": None,
            "missing": None,
            "quantity_state": "unknown",
            "reason": "No cargo record for your current ship is stored yet.",
            "origin": origin,
        }
    origin["source"] = "Cargo.json" if cargo.source == "Cargo.json" else "Journal Cargo"
    origin["observed_at"] = cargo.event_timestamp
    if not cargo.inventory_complete:
        return {
            "owned": None,
            "missing": None,
            "quantity_state": "unknown",
            "reason": "The latest cargo record gave a total but not the items.",
            "origin": origin,
        }
    symbol = requirement["inventory"]["symbol"]
    matches = [item for item in cargo.inventory if _symbol(item.name) == symbol]
    owned = sum(item.count for item in matches)
    caveats = ["Cargo on other ships or a fleet carrier is not counted."]
    stolen = sum(item.stolen or 0 for item in matches)
    if stolen:
        caveats.append(f"{stolen} of these are marked stolen.")
    if any(item.mission_id for item in matches):
        caveats.append("Some of these are mission cargo.")
    return {
        "owned": owned,
        "missing": max(requirement["quantity"] - owned, 0),
        "quantity_state": "observed",
        "reason": None,
        "caveats": caveats,
        "origin": origin,
    }


def _broker_items(event: JsonDict) -> list[str]:
    items = event.get("ItemsUnlocked")
    if isinstance(items, (str, dict)):
        items = [items]
    if not isinstance(items, list):
        return []
    return [
        _symbol(item.get("Name") if isinstance(item, dict) else item) for item in items
    ]


def _module_items(event_type: str, event: JsonDict) -> list[str]:
    container, key = _MODULE_EVIDENCE[event_type]
    if container is None:
        return [_symbol(event.get(key))]
    rows = event.get(container)
    if not isinstance(rows, list):
        return []
    return [_symbol(row.get(key)) for row in rows if isinstance(row, dict)]


async def observed_unlock_state(
    session_factory: async_sessionmaker[AsyncSession], item_symbols: list[str]
) -> JsonDict:
    """What stored Journal history shows about an unlock.  Never infers 'locked'.

    Only the exact equipment symbols of this offering count, so one weapon size or
    mount is never mistaken for another, nor for a modified per-item variant.
    """
    wanted = {_symbol(symbol) for symbol in item_symbols}
    # A coarse text filter keeps the scan cheap; exact symbols decide below.
    needles = {
        symbol.removeprefix("int_").removeprefix("hpt_").split("_size")[0]
        for symbol in wanted
    }
    async with session_factory() as db:
        earliest, latest, total = (
            await db.execute(
                select(
                    func.min(JournalEvent.timestamp),
                    func.max(JournalEvent.timestamp),
                    func.count(JournalEvent.id),
                )
            )
        ).one()
        rows = (
            (
                await db.execute(
                    select(JournalEvent)
                    .where(
                        JournalEvent.event_type.in_(
                            {"TechnologyBroker", *_MODULE_EVIDENCE}
                        )
                    )
                    .where(
                        or_(
                            *(
                                JournalEvent.raw_json.ilike(f"%{needle}%")
                                for needle in sorted(needles)
                            )
                        )
                    )
                    .order_by(JournalEvent.timestamp.asc(), JournalEvent.id.asc())
                )
            )
            .scalars()
            .all()
        )
    history = {
        "earliest": _iso(earliest),
        "latest": _iso(latest),
        "event_count": int(total or 0),
    }
    unlocked: JournalEvent | None = None
    owned: JournalEvent | None = None
    broker_type: str | None = None
    for row in rows:
        event = _payload(row)
        if row.event_type == "TechnologyBroker":
            if wanted & set(_broker_items(event)):
                unlocked = row
                value = event.get("BrokerType")
                broker_type = value if isinstance(value, str) else None
        elif wanted & set(_module_items(row.event_type, event)):
            owned = owned or row
    if unlocked is not None:
        return {
            "state": "observed_unlocked",
            "observed_at": _iso(unlocked.timestamp),
            "evidence_event": "TechnologyBroker",
            "evidence_event_id": unlocked.id,
            "broker_type": broker_type,
            "history": history,
        }
    if owned is not None:
        return {
            "state": "module_observed",
            "observed_at": _iso(owned.timestamp),
            "evidence_event": owned.event_type,
            "evidence_event_id": owned.id,
            "history": history,
        }
    return {
        "state": "not_observed" if history["event_count"] else "no_history",
        "observed_at": None,
        "evidence_event": None,
        "history": history,
    }


def _tracking(goals: list[EngineeringGoalRecord], unlock_id: str) -> JsonDict | None:
    for goal in goals:
        reference = goal.target_reference or {}
        if (
            goal.target_kind in GOAL_KINDS
            and goal.state != "archived"
            and reference.get("knowledge_unlock_id") == unlock_id
        ):
            checklist = reference.get("checklist")
            return {
                "goal_id": goal.goal_id,
                "title": goal.title,
                "state": goal.state,
                "priority": goal.priority,
                "target_reference": reference,
                "checklist": {
                    str(key): value is True
                    for key, value in (
                        checklist if isinstance(checklist, dict) else {}
                    ).items()
                },
                "truth_class": "commander_entered",
            }
    return None


def _contexts(method_rows: list[JsonDict]) -> set[str]:
    return {str(m["attributes"].get("context")) for m in method_rows}


def _expedition(
    knowledge: KnowledgeIndex, rows: list[JsonDict], broker_id: str | None
) -> JsonDict:
    """A Guardian-site brief built only from the knowledge graph and the rows above."""
    site_rows = [r for r in rows if "guardian_site" in r["acquisition_contexts"]]
    other_rows = [r for r in rows if "guardian_site" not in r["acquisition_contexts"]]
    site_methods: dict[str, JsonDict] = {}
    for row in site_rows:
        for method in knowledge.acquisition(row["entity_id"])["methods"]:
            if method["attributes"].get("context") == "guardian_site":
                site_methods.setdefault(method["id"], method)
    destinations: list[JsonDict] = []
    # Places stay with the activity they serve: module, weapon and vessel
    # blueprint sites (and obelisk ruins) are different places.
    destination_groups: list[JsonDict] = []
    seen: set[str] = set()
    procedure: list[JsonDict] = []
    preparations: list[JsonDict] = []
    needs_queue = list(site_methods.values())
    for method in site_methods.values():
        places = [p for p in method["locations"] if p["kind"] == "location"]
        if places:
            destination_groups.append(
                {"activity_id": method["id"], "name": method["name"], "places": places}
            )
        for place in places:
            if place["id"] not in seen:
                seen.add(place["id"])
                destinations.append(place)
        if method["steps"] and not any(
            p["steps"] == method["steps"] for p in procedure
        ):
            procedure.append(
                {
                    "activity_id": method["id"],
                    "name": method["name"],
                    "steps": method["steps"],
                }
            )
    for method in needs_queue:
        for need in method["needs"]:
            if any(p["id"] == need["id"] for p in preparations):
                continue
            entity = knowledge.entity(need["id"]) or {}
            preparations.append(
                {
                    "id": need["id"],
                    "name": need["name"],
                    "required": need["required"],
                    "text": entity.get("summary"),
                    "claims": entity.get("claims", []),
                    "sources": need["sources"],
                }
            )
            # Something needed on site that must itself be fetched first (an
            # Ancient Key from a beacon) brings its own places and procedure.
            for fetch in knowledge.acquisition(need["id"])["methods"]:
                if (
                    fetch["attributes"].get("context") == "guardian_site"
                    and fetch["id"] not in site_methods
                ):
                    site_methods[fetch["id"]] = fetch
                    places = [p for p in fetch["locations"] if p["kind"] == "location"]
                    if places:
                        destination_groups.append(
                            {
                                "activity_id": fetch["id"],
                                "name": fetch["name"],
                                "places": places,
                            }
                        )
                    if fetch["steps"]:
                        procedure.append(
                            {
                                "activity_id": fetch["id"],
                                "name": fetch["name"],
                                "steps": fetch["steps"],
                            }
                        )
    salvage = [
        {"activity_id": m["id"], "name": m["name"], "summary": m["summary"]}
        for m in site_methods.values()
        if not m["steps"]
    ]
    region = [
        place["attributes"]["distance_from_sol_ly"]
        for place in destinations
        if isinstance(place["attributes"].get("distance_from_sol_ly"), (int, float))
    ]

    def still_needed(row: JsonDict) -> bool:
        return row["quantity_state"] != "observed" or (row["missing"] or 0) > 0

    structure = knowledge.entity("small-guardian-structure")
    return {
        "applicable": bool(site_rows),
        "region": {
            "nearest_from_sol_ly": min(region) if region else None,
            "farthest_from_sol_ly": max(region) if region else None,
            "basis": "Community-listed distance from Sol; your position is not used.",
        },
        "destinations": destinations,
        "destination_groups": destination_groups,
        "site_notes": structure["claims"] if structure else [],
        "preparations": preparations,
        "procedure": procedure,
        "salvage": salvage,
        "collect": [
            {
                "entity_id": r["entity_id"],
                "name": r["name"],
                "missing": r["missing"],
                "quantity": r["quantity"],
                "quantity_state": r["quantity_state"],
            }
            for r in site_rows
            if still_needed(r)
        ],
        "outstanding_after": [
            {
                "entity_id": r["entity_id"],
                "name": r["name"],
                "missing": r["missing"],
                "quantity": r["quantity"],
                "quantity_state": r["quantity_state"],
            }
            for r in other_rows
            if still_needed(r)
        ],
        "broker_stations": knowledge.locations(broker_id) if broker_id else [],
    }


def _checklist(
    rows: list[JsonDict], expedition: JsonDict, transaction: str
) -> list[JsonDict]:
    """Commander-confirmed steps.  Their ids are stable so saved progress survives."""
    items = [
        {
            "id": f"prepare:{prep['id']}",
            "group": "Before you leave",
            "text": (
                f"{prep['name']} ready"
                if prep["required"]
                else f"{prep['name']} fitted (recommended)"
            ),
        }
        for prep in expedition["preparations"]
    ]
    for row in rows:
        at_site = "guardian_site" in row["acquisition_contexts"]
        items.append(
            {
                "id": f"collect:{row['entity_id']}",
                "group": "At the Guardian site" if at_site else "Elsewhere",
                "text": f"{row['quantity']} {row['name']} in hand",
            }
        )
    per_item = transaction == "per_item_purchase"
    items.append(
        {
            "id": "handin:broker",
            "group": "Exchange" if per_item else "Unlock",
            "text": (
                "Each item exchanged at the broker, one full hand-in per item"
                if per_item
                else "Everything handed in together at a Guardian Technology Broker"
            ),
        }
    )
    return items


def _unlock_state_for(transaction: str, evidence: JsonDict | None) -> JsonDict | None:
    """The fixed answer when Journal evidence cannot or must not be read."""
    if transaction == "per_item_purchase":
        # Owning a modified weapon never means more can be bought: every copy is
        # a new exchange, so no unlock state is derived from any observation.
        return {
            "state": "not_applicable",
            "observed_at": None,
            "evidence_event": None,
            "history": None,
        }
    if not evidence:
        return {
            "state": "evidence_unsupported",
            "observed_at": None,
            "evidence_event": None,
            "history": None,
        }
    return None


async def plan(
    session_factory: async_sessionmaker[AsyncSession],
    knowledge: KnowledgeIndex,
    unlock_id: str,
    *,
    cargo: CargoHoldSnapshot | None,
    goals: list[EngineeringGoalRecord],
    recipe: str | None = None,
    quantity: int = 1,
) -> JsonDict:
    """The full readiness view for one offering.

    Raises ``KeyError`` for an unknown offering or recipe and ``ValueError`` for a
    quantity a permanent unlock cannot take or a per-item purchase cannot reach.
    """
    unlock = knowledge.entity(unlock_id)
    if unlock is None or unlock["kind"] != "technology_unlock":
        raise KeyError(unlock_id)
    attributes = unlock["attributes"]
    transaction = attributes["transaction"]
    if transaction == "permanent_unlock" and quantity != 1:
        raise ValueError("A permanent unlock is made once; quantity must be 1")
    if not 1 <= quantity <= MAX_ITEMS:
        raise ValueError(f"Quantity must be between 1 and {MAX_ITEMS}")
    recipes = knowledge.recipes(unlock_id)
    chosen = recipe or (recipes[0]["id"] if recipes else None)
    requirements = knowledge.requirements(unlock_id, chosen)
    inventory = await engineering_progression.horizons_inventory(session_factory)

    rows: list[JsonDict] = []
    for requirement in requirements:
        # A per-item purchase costs the full recipe for every item requested.
        requirement = {**requirement, "per_item": requirement["quantity"]}
        requirement["quantity"] = requirement["per_item"] * quantity
        store = requirement["inventory"]["store"]
        observed = (
            material_row(requirement, inventory)
            if store == "materials"
            else cargo_row(requirement, cargo)
        )
        acquisition = knowledge.acquisition(requirement["id"])
        entity = knowledge.entity(requirement["id"]) or {}
        rows.append(
            {
                "entity_id": requirement["id"],
                "name": requirement["name"],
                "aliases": entity.get("aliases", []),
                "kind": requirement["kind"],
                "resource_type": (
                    f"{requirement['inventory']['category'].title()} material"
                    if store == "materials"
                    else f"Commodity ({requirement['inventory']['category']})"
                ),
                "store": store,
                "symbol": requirement["inventory"]["symbol"],
                "quantity": requirement["quantity"],
                "per_item": requirement["per_item"],
                **observed,
                "material_trader": bool(
                    entity.get("attributes", {}).get("material_trader")
                ),
                "acquisition_contexts": sorted(_contexts(acquisition["methods"])),
                "acquisition": acquisition["methods"],
                "claims": entity.get("claims", []),
                "sources": requirement["sources"],
            }
        )

    evidence = attributes.get("journal_unlock")
    unlock_state = _unlock_state_for(
        transaction, evidence
    ) or await observed_unlock_state(session_factory, evidence["item_symbols"])
    related = knowledge.related(unlock_id)
    module_link = next((r for r in related if r["type"] == "unlocks"), None)
    module = knowledge.entity(module_link["entity"]["id"]) if module_link else None
    equipment_needs = (
        [
            knowledge.entity(r["entity"]["id"])
            for r in knowledge.related(module["id"])
            if r["type"] == "requires" and r["direction"] == "outgoing"
        ]
        if module
        else []
    )
    broker_link = next(
        (
            r
            for r in related
            if r["type"] == "obtained_from"
            and r["entity"]["kind"] == "technology_broker"
        ),
        None,
    )
    broker_id = broker_link["entity"]["id"] if broker_link else None

    known = [r for r in rows if r["quantity_state"] == "observed"]
    expedition = _expedition(knowledge, rows, broker_id)
    pack = next(p for p in knowledge.packs if p["pack_id"] == unlock["pack_id"])
    return {
        "version": VERSION,
        "state": "available",
        "network_access": "none",
        "pack": {
            "pack_id": pack["pack_id"],
            "version": pack["version"],
            "reviewed_at": pack["reviewed_at"],
            "game_version": pack["game_version"],
            "distribution": pack["distribution"],
        },
        "unlock": {
            "id": unlock["id"],
            "name": unlock["name"],
            "summary": unlock["summary"],
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
            "claims": unlock["claims"],
            "broker": knowledge.entity(broker_id) if broker_id else None,
        },
        "transaction": transaction,
        "quantity": quantity,
        "max_quantity": MAX_ITEMS if transaction == "per_item_purchase" else 1,
        "recipes": recipes,
        "recipe": chosen,
        "module": module,
        "equipment_needs": equipment_needs,
        "unlock_state": unlock_state,
        "requirements": rows,
        "readiness": {
            "requirement_count": len(rows),
            "ready": sum(1 for r in known if r["missing"] == 0),
            "short": sum(1 for r in known if (r["missing"] or 0) > 0),
            "unknown": len(rows) - len(known),
            "all_ready": len(known) == len(rows)
            and all(r["missing"] == 0 for r in rows),
            "inventory_state": inventory.get("state"),
        },
        "expedition": expedition,
        "checklist": _checklist(rows, expedition, transaction),
        "tracking": _tracking(goals, unlock_id),
        # Every source the pack declares, so each cited id in this payload resolves.
        "sources": pack["sources"],
        "unlock_sources": [s["id"] for s in knowledge.sources_for(unlock_id)],
        "unsupported": pack["unsupported"],
        "truth_boundary": (
            "Requirements and acquisition guidance are community reference data. "
            "Owned quantities come only from your local Journal. Nothing here changes "
            "your inventory or performs a game action."
        ),
    }
