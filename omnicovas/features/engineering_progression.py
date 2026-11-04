"""Deterministic Engineering progression derived from local Journal evidence.

This module deliberately does not bundle a global recipe catalogue.  It learns
the exact material bill for a blueprint grade from the Commander's own
``EngineerCraft.Ingredients`` events and reconstructs Horizons inventory from a
complete ``Materials`` baseline followed by supported inventory deltas.
Unknown inputs stay unknown.
Commander-enabled reference packs also supply version-pinned recipes and
explicitly conditional full-grade material budgets for planned replacements.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import JournalEvent
from omnicovas.features import (
    engineer_directory,
    engineering_catalog,
    engineering_workbench,
    galactic_knowledge,
    material_acquisition,
    material_intelligence,
    material_trader,
)
from omnicovas.features.engineering import BuildPlanRecord, EngineeringGoalRecord

JsonDict = dict[str, Any]

_INVENTORY_EVENTS = {
    "Materials",
    "MaterialCollected",
    "MaterialDiscarded",
    "MaterialTrade",
    "EngineerCraft",
    "Synthesis",
    "TechnologyBroker",
}

CATALOG_SCOPE = "commander_observed_loadout_and_recipes"
CATALOG_VERSION = "local-journal-v1"
CALCULATION_VERSION = "observed-grade-cost-and-performance-v2"


def _payload(row: JournalEvent) -> JsonDict:
    try:
        value = json.loads(row.raw_json)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _material_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    clean = value.strip().strip("$").removesuffix("_name;")
    return clean.casefold() or None


def _material_label(symbol: str, recorded: str | None) -> str:
    """A material's display name; the knowledge packs (GKI-05) name it when
    the recipe recorded only its Journal symbol."""
    if recorded and recorded.casefold() != symbol:
        return recorded
    if galactic_knowledge.catalog()["state"] == "available":
        record = galactic_knowledge.index().find_by_symbol("materials", symbol)
        if record:
            return str(record["name"])
    return recorded or symbol


def _documented_categories(results: list[JsonDict]) -> dict[str, str]:
    """Categories the knowledge packs record for the materials builds need (GKI-05)."""
    if galactic_knowledge.catalog()["state"] != "available":
        return {}
    knowledge = galactic_knowledge.index()
    found: dict[str, str] = {}
    for build in results:
        for row in build.get("materials", []):
            symbol = str(row["material_id"])
            record = knowledge.find_by_symbol("materials", symbol)
            category = ((record or {}).get("inventory") or {}).get("category")
            if category:
                found[symbol] = str(category)
    return found


def _display_name(entry: JsonDict, fallback: Any) -> str:
    for key in ("Name_Localised", "Material_Localised", "Name", "Material"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().strip("$").removesuffix("_name;")
    return str(fallback or "Unknown material")


def _quantity(entry: JsonDict) -> int | None:
    value = entry.get("Count", entry.get("Quantity"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    count = int(value)
    return count if count >= 0 else None


async def _journal_rows(
    session_factory: async_sessionmaker[AsyncSession],
    event_types: Iterable[str],
) -> list[JournalEvent]:
    async with session_factory() as db:
        result = await db.execute(
            select(JournalEvent)
            .where(JournalEvent.event_type.in_(set(event_types)))
            .order_by(JournalEvent.timestamp.asc(), JournalEvent.id.asc())
        )
        return list(result.scalars().all())


def _has_localised_name(entry: JsonDict) -> bool:
    return any(
        isinstance(entry.get(key), str) and entry[key].strip()
        for key in ("Name_Localised", "Material_Localised")
    )


def _pool_key(value: Any) -> str:
    """Key a reference-pack material id exactly as Journal inventory is keyed."""
    return _material_key(value) or str(value)


def _apply_delta(
    counts: dict[str, int],
    names: dict[str, str],
    entry: JsonDict,
    sign: int,
) -> bool:
    raw_name = entry.get("Name", entry.get("Material"))
    key = _material_key(raw_name)
    count = _quantity(entry)
    if key is None or count is None:
        return False
    # A later event that omits the localised name must not downgrade the
    # label an earlier event supplied.
    if key not in names or _has_localised_name(entry):
        names[key] = _display_name(entry, raw_name)
    counts[key] = counts.get(key, 0) + sign * count
    return True


def _record_category(categories: dict[str, str], entry: JsonDict) -> None:
    key = _material_key(entry.get("Name", entry.get("Material")))
    category = entry.get("Category")
    if key and isinstance(category, str) and category.strip():
        categories[key] = category.strip().casefold()


async def horizons_inventory(
    session_factory: async_sessionmaker[AsyncSession],
) -> JsonDict:
    """Reconstruct exact inventory only after a complete Materials baseline."""
    rows = await _journal_rows(session_factory, _INVENTORY_EVENTS)
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    categories: dict[str, str] = {}
    baseline_row: JournalEvent | None = None
    last_event_row: JournalEvent | None = None
    applied_event_ids: list[int] = []
    warnings: list[str] = []

    for row in rows:
        event = _payload(row)
        event_type = row.event_type
        if event_type == "Materials":
            next_counts: dict[str, int] = {}
            next_names: dict[str, str] = {}
            next_categories: dict[str, str] = {}
            valid = True
            for field, category in (
                ("Raw", "raw"),
                ("Manufactured", "manufactured"),
                ("Encoded", "encoded"),
            ):
                entries = event.get(field)
                if not isinstance(entries, list):
                    valid = False
                    break
                for item in entries:
                    if not isinstance(item, dict) or not _apply_delta(
                        next_counts, next_names, item, 1
                    ):
                        valid = False
                        break
                    key = _material_key(item.get("Name"))
                    if key:
                        next_categories[key] = category
                if not valid:
                    break
            if valid:
                counts, names, categories = next_counts, next_names, next_categories
                baseline_row = row
                last_event_row = row
                applied_event_ids = [row.id]
                warnings = []
            continue

        if baseline_row is None:
            continue

        changed = False
        if event_type == "MaterialCollected":
            changed = _apply_delta(counts, names, event, 1)
            _record_category(categories, event)
        elif event_type == "MaterialDiscarded":
            changed = _apply_delta(counts, names, event, -1)
        elif event_type == "MaterialTrade":
            paid = event.get("Paid")
            received = event.get("Received")
            if isinstance(paid, dict):
                changed = _apply_delta(counts, names, paid, -1) or changed
                _record_category(categories, paid)
            if isinstance(received, dict):
                changed = _apply_delta(counts, names, received, 1) or changed
                _record_category(categories, received)
        elif event_type in {"EngineerCraft", "Synthesis", "TechnologyBroker"}:
            ingredients = event.get("Ingredients", event.get("Materials"))
            if isinstance(ingredients, list):
                for item in ingredients:
                    if isinstance(item, dict):
                        changed = _apply_delta(counts, names, item, -1) or changed
        if changed:
            applied_event_ids.append(row.id)
            last_event_row = row

    if baseline_row is None:
        return {
            "state": "unknown",
            "observed_at": None,
            "materials": [],
            "source_chain": [],
            "caveats": [
                "No complete local Materials event is stored; inventory is "
                "unknown, not zero.",
                "Later collection or expenditure events cannot establish a "
                "complete balance without a baseline.",
            ],
        }

    # A balance that replays below zero contradicts the game: its true
    # quantity is unknown, so it is never reported as an observed zero.
    inconsistent = {key for key, count in counts.items() if count < 0}
    for key in sorted(inconsistent):
        warnings.append(
            f"{names.get(key, key)} reconciled below zero; a newer "
            "Materials baseline is required."
        )

    materials = [
        {
            "material_id": key,
            "display_name": names.get(key, key),
            "category": categories.get(key, "unknown"),
            "count": None if key in inconsistent else count,
            "quantity_state": (
                "unknown_inconsistent" if key in inconsistent else "observed"
            ),
        }
        for key, count in sorted(
            counts.items(), key=lambda item: names.get(item[0], item[0]).casefold()
        )
    ]
    last_event_row = last_event_row or baseline_row
    return {
        "state": "verified_local" if not warnings else "partial_inconsistent",
        "observed_at": baseline_row.timestamp.isoformat(),
        "last_event_at": last_event_row.timestamp.isoformat(),
        "materials": materials,
        "event_count": len(applied_event_ids),
        "source_chain": [
            {
                "source": "Journal",
                "event": "Materials + supported deltas",
                "truth_class": "commander_observed",
                "baseline_event_id": baseline_row.id,
            }
        ],
        "caveats": warnings,
    }


async def observed_recipes(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[JsonDict]:
    """Return the latest locally observed cost for each blueprint grade."""
    rows = await _journal_rows(session_factory, {"EngineerCraft"})
    recipes: dict[tuple[str, int], JsonDict] = {}
    for row in rows:
        event = _payload(row)
        blueprint = event.get("BlueprintName")
        level = event.get("Level")
        ingredients = event.get("Ingredients")
        if not isinstance(blueprint, str) or not isinstance(level, int):
            continue
        if not isinstance(ingredients, list) or not ingredients:
            continue
        material_rows: list[JsonDict] = []
        valid = True
        for item in ingredients:
            if not isinstance(item, dict):
                valid = False
                break
            key = _material_key(item.get("Name"))
            count = _quantity(item)
            if key is None or count is None:
                valid = False
                break
            material_rows.append(
                {
                    "material_id": key,
                    "display_name": _display_name(item, item.get("Name")),
                    "count": count,
                }
            )
        if not valid:
            continue
        recipes[(blueprint.casefold(), level)] = {
            "blueprint_id": blueprint,
            "blueprint_label": str(event.get("BlueprintName_Localised") or blueprint),
            "grade": level,
            "materials": material_rows,
            "engineer": event.get("Engineer"),
            "engineer_id": _engineer_id(event.get("EngineerID")),
            "experimental_effect": event.get("ExperimentalEffect"),
            "observed_at": row.timestamp.isoformat(),
            "journal_event_id": row.id,
            "source_chain": [
                {
                    "source": "Journal",
                    "event": "EngineerCraft",
                    "truth_class": "commander_observed",
                }
            ],
        }
    return sorted(
        recipes.values(), key=lambda row: (row["blueprint_label"], row["grade"])
    )


def _engineer_id(value: Any) -> int | None:
    """Frontier's numeric ``EngineerID``; anything else is not an identifier."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return int(value)


def _engineer_entries(event: JsonDict) -> list[JsonDict] | None:
    """Return the per-engineer entries of one ``EngineerProgress`` event.

    The Journal writes the full list under ``Engineers`` and, afterwards, one
    flat event per change.  Any other shape is unsupported, not guessed at.
    """
    engineers = event.get("Engineers")
    if isinstance(engineers, list):
        return [entry for entry in engineers if isinstance(entry, dict)]
    if "Engineer" in event or "EngineerID" in event:
        return [event]
    return None


def _engineer_observation(entry: JsonDict) -> JsonDict | None:
    """Normalise one entry, keeping only fields that are present and well formed.

    ``Progress`` is kept as the Journal's own token: the repository has no
    verified vocabulary for it, so nothing is translated or inferred.
    """
    engineer_id = _engineer_id(entry.get("EngineerID"))
    raw_name = entry.get("Engineer")
    name = raw_name.strip()[:128] if isinstance(raw_name, str) else ""
    if engineer_id is None and not name:
        return None
    progress = entry.get("Progress")
    rank = entry.get("Rank")
    rank_progress = entry.get("RankProgress")
    return {
        "engineer_id": engineer_id,
        "name": name or None,
        "progress": (
            progress.strip()[:32]
            if isinstance(progress, str) and progress.strip()
            else None
        ),
        "rank": (
            rank
            if isinstance(rank, int) and not isinstance(rank, bool) and rank >= 0
            else None
        ),
        "rank_progress": (
            rank_progress
            if isinstance(rank_progress, (int, float))
            and not isinstance(rank_progress, bool)
            and 0 <= rank_progress <= 100
            else None
        ),
    }


async def engineer_progress(
    session_factory: async_sessionmaker[AsyncSession],
) -> JsonDict:
    """Latest observed progression per engineer, from stored ``EngineerProgress``.

    Derived on read from the Journal rows the recorder already keeps, like the
    inventory and recipes above, so restart and replay need no extra state.
    Rows replay in timestamp order, so a late-arriving older line cannot
    overwrite a newer observation, and an identical line stored twice counts
    once.  An engineer the Journal never reported is simply absent: a missing
    event is not evidence that the engineer is locked.
    """
    rows = await _journal_rows(session_factory, {"EngineerProgress"})
    engineers: dict[str, JsonDict] = {}
    seen: set[tuple[str, str]] = set()
    event_count = 0
    unsupported = 0
    ignored_entries = 0
    last_event_at: str | None = None

    for row in rows:
        fingerprint = (row.timestamp.isoformat(), row.raw_json)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        entries = _engineer_entries(_payload(row))
        observations = [
            observation
            for entry in entries or []
            if (observation := _engineer_observation(entry)) is not None
        ]
        # An entry with neither Engineer nor EngineerID has no identity to attach
        # anything to: it is dropped and counted, never given an identity.
        ignored_entries += len(entries or []) - len(observations)
        if not observations:
            unsupported += 1
            continue
        event_count += 1
        observed_at = row.timestamp.isoformat()
        last_event_at = observed_at
        for observation in observations:
            engineer_id = observation["engineer_id"]
            key = (
                f"id:{engineer_id}"
                if engineer_id is not None
                else f"name:{str(observation['name']).casefold()}"
            )
            previous = engineers.get(key)
            progress = observation["progress"]
            rank = observation["rank"]
            rank_progress = observation["rank_progress"]
            progress_observed_at = observed_at if progress is not None else None
            if previous and progress is None:
                if rank is None and rank_progress is None:
                    continue  # identity only: nothing observed, nothing to record
                # The documented single-engineer update may carry only Rank and
                # RankProgress.  It says nothing about access, so the last
                # reported access state stands (with its own time); a rank
                # progress is carried only alongside the rank it belongs to.
                progress = previous["progress"]
                progress_observed_at = previous["progress_observed_at"]
                if rank is None:
                    rank = previous["rank"]
                    if rank_progress is None:
                        rank_progress = previous["rank_progress"]
            state = (progress, rank, rank_progress)
            history = list(previous["history"]) if previous else []
            if not previous or previous["_state"] != state:
                history.append(
                    {
                        "progress": progress,
                        "rank": rank,
                        "rank_progress": rank_progress,
                        "observed_at": observed_at,
                    }
                )
            engineers[key] = {
                "key": key,
                "engineer_id": engineer_id,
                "identity": "engineer_id" if engineer_id is not None else "name_only",
                "name": observation["name"] or (previous or {}).get("name"),
                "progress": progress,
                "progress_observed_at": progress_observed_at,
                "rank": rank,
                "rank_progress": rank_progress,
                "observed_at": observed_at,
                "first_observed_at": (
                    previous["first_observed_at"] if previous else observed_at
                ),
                "observation_count": (previous["observation_count"] if previous else 0)
                + 1,
                "journal_event_id": row.id,
                "history": history,
                "_state": state,
                "source_chain": [
                    {
                        "source": "Journal",
                        "event": "EngineerProgress",
                        "truth_class": "commander_observed",
                    }
                ],
            }

    result_rows = []
    for record in sorted(
        engineers.values(),
        key=lambda item: (str(item["name"] or "").casefold(), item["key"]),
    ):
        public = {key: value for key, value in record.items() if key != "_state"}
        public["history"] = list(reversed(record["history"]))[:10]
        result_rows.append(public)
    return {
        "state": "observed" if result_rows else "not_observed",
        "engineers": result_rows,
        "event_count": event_count,
        "unsupported_event_count": unsupported,
        "ignored_entry_count": ignored_entries,
        "last_event_at": last_event_at,
        "source_chain": [
            {
                "source": "Journal",
                "event": "EngineerProgress",
                "truth_class": "commander_observed",
            }
        ],
        "caveats": [
            "Progress and rank are as of the time each was observed; the game "
            "may have changed since.",
            "An engineer with no EngineerProgress observation is not observed, "
            "which does not mean the engineer is locked.",
            "The Journal does not report unlock requirements or locations.",
        ],
    }


def _contribution_item(event: JsonDict) -> tuple[str, str | None]:
    """Return (type, item) for one ``EngineerContribution``, or ('', None)."""
    kind = event.get("Type")
    if not isinstance(kind, str) or not kind.strip():
        return "", None
    kind = kind.strip()[:32]
    for field in ("Commodity", "Material"):
        value = event.get(field)
        if isinstance(value, str) and value.strip():
            return kind, value.strip()[:128]
    faction = event.get("Faction")
    if isinstance(faction, str) and faction.strip():
        return kind, faction.strip()[:128]
    return kind, None


def _count_value(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return int(value)


async def engineer_contributions(
    session_factory: async_sessionmaker[AsyncSession],
) -> JsonDict:
    """What the Journal recorded the Commander offering each engineer.

    ``EngineerContribution`` reports offers made toward an engineer's access.  It
    does not say which requirement an offer answered or whether the requirement
    is now met, so this is evidence only: the running total the game last
    reported for each kind of offer, never a verdict on unlocking.  Derived on
    read like the rest of the Journal projections; an identical line stored
    twice counts once.
    """
    rows = await _journal_rows(session_factory, {"EngineerContribution"})
    engineers: dict[str, JsonDict] = {}
    seen: set[tuple[str, str]] = set()
    event_count = 0
    unsupported = 0
    for row in rows:
        fingerprint = (row.timestamp.isoformat(), row.raw_json)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        event = _payload(row)
        engineer_id = _engineer_id(event.get("EngineerID"))
        raw_name = event.get("Engineer")
        name = raw_name.strip()[:128] if isinstance(raw_name, str) else ""
        kind, item = _contribution_item(event)
        if (engineer_id is None and not name) or not kind:
            unsupported += 1
            continue
        event_count += 1
        key = (
            f"id:{engineer_id}"
            if engineer_id is not None
            else f"name:{name.casefold()}"
        )
        record = engineers.setdefault(
            key,
            {
                "key": key,
                "engineer_id": engineer_id,
                "identity": "engineer_id" if engineer_id is not None else "name_only",
                "name": name or None,
                "contributions": {},
                "event_count": 0,
            },
        )
        record["name"] = name or record["name"]
        record["event_count"] += 1
        offered = _count_value(event.get("Quantity"))
        total = _count_value(event.get("TotalQuantity"))
        line_key = f"{kind.casefold()}|{(item or '').casefold()}"
        line = record["contributions"].get(line_key)
        record["contributions"][line_key] = {
            "type": kind,
            "item": item,
            "total_quantity": total,
            "last_quantity": offered,
            "observed_at": row.timestamp.isoformat(),
            "offer_count": (line["offer_count"] if line else 0) + 1,
        }
    result_rows = [
        {
            **{k: v for k, v in record.items() if k != "contributions"},
            "contributions": sorted(
                record["contributions"].values(),
                key=lambda line: (line["type"].casefold(), str(line["item"] or "")),
            ),
        }
        for record in sorted(
            engineers.values(),
            key=lambda item: (str(item["name"] or "").casefold(), item["key"]),
        )
    ]
    return {
        "state": "observed" if result_rows else "not_observed",
        "engineers": result_rows,
        "event_count": event_count,
        "unsupported_event_count": unsupported,
        "source_chain": [
            {
                "source": "Journal",
                "event": "EngineerContribution",
                "truth_class": "commander_observed",
            }
        ],
        "caveats": [
            "Totals are as the game last reported them for each kind of offer.",
            "The Journal does not say which requirement an offer answered or "
            "whether that requirement is now met.",
        ],
    }


def _actual_module(state: JsonDict, slot: str) -> JsonDict | None:
    modules = state.get("modules")
    if not isinstance(modules, dict):
        return None
    module = modules.get(slot)
    return module if isinstance(module, dict) else None


def _priority_rank(value: str) -> int:
    return {"high": 0, "normal": 1, "unsorted": 2, "low": 3}.get(value, 2)


def observed_loadout_catalog(live_state: JsonDict) -> JsonDict:
    """Expose the verified local subset usable by the build designer.

    This is intentionally not a universal Elite catalogue.  It contains only
    the current ship and module slots observed in the local Loadout projection.
    Blueprint-to-module compatibility remains unknown unless the same
    blueprint is already observed on that slot.
    """
    modules = live_state.get("modules")
    rows: list[JsonDict] = []
    if isinstance(modules, dict):
        for slot, raw in sorted(modules.items(), key=lambda item: item[0].casefold()):
            if not isinstance(raw, dict):
                continue
            engineering = raw.get("engineering")
            if not isinstance(engineering, dict):
                engineering = {}
            rows.append(
                {
                    "slot": slot,
                    "module_id": raw.get("item"),
                    "module_label": raw.get("item_localised")
                    or raw.get("item")
                    or slot,
                    "observed_blueprint": engineering.get("BlueprintName"),
                    "observed_grade": engineering.get("Level"),
                    "observed_experimental_effect": engineering.get(
                        "ExperimentalEffect"
                    ),
                    "truth_class": "commander_observed",
                }
            )
    ship_type = live_state.get("current_ship_type")
    ship_id = live_state.get("current_ship_id")
    return {
        "scope": CATALOG_SCOPE,
        "version": CATALOG_VERSION,
        "ship": {
            "ship_type": ship_type,
            "ship_id": ship_id,
            "truth_class": "commander_observed" if ship_type else "unknown",
        },
        "modules": rows,
        "state": "verified_local" if ship_type and rows else "unknown",
        "limitations": [
            "Only the current locally observed ship and fitted modules are available.",
            "Module swaps and universal slot legality are unavailable until a "
            "verified catalogue is approved.",
            "Blueprint compatibility is verified only when already observed on "
            "the same slot.",
        ],
    }


async def portfolio(
    session_factory: async_sessionmaker[AsyncSession],
    builds: list[BuildPlanRecord],
    goals: list[EngineeringGoalRecord],
    live_state: JsonDict,
    *,
    include_workbenches: bool = True,
) -> JsonDict:
    """Assess target modules and allocate one inventory pool across builds."""
    inventory = await horizons_inventory(session_factory)
    recipe_rows = await observed_recipes(session_factory)
    reference_catalog = await engineering_catalog.active_catalog(session_factory)
    retained_catalogs = await engineering_catalog.catalogs_by_version(session_factory)
    loadout_catalog = observed_loadout_catalog(live_state)
    observed_recipe_index = {
        (str(row["blueprint_id"]).casefold(), int(row["grade"])): row
        for row in recipe_rows
    }
    goal_by_build = {
        goal.linked_build_plan_id: goal
        for goal in goals
        if goal.linked_build_plan_id and goal.state not in {"complete", "archived"}
    }
    active_builds = [
        build for build in builds if build.state not in {"complete", "archived"}
    ]
    active_builds.sort(
        key=lambda build: (
            _priority_rank(goal_by_build[build.build_plan_id].priority)
            if build.build_plan_id in goal_by_build
            else 2,
            build.created_at,
        )
    )
    available = {
        row["material_id"]: row["count"] for row in inventory.get("materials", [])
    }
    inventory_known = inventory.get("state") == "verified_local"
    observed_pool = dict(available) if inventory_known else {}
    trade_rules: dict[str, tuple[str, list[JsonDict]]] = {}
    trade_rule_sets: dict[str, JsonDict | None] = {}
    results: list[JsonDict] = []

    for build in active_builds:
        summary = build.target_loadout_summary
        targets = summary.get("module_targets") if isinstance(summary, dict) else None
        if not isinstance(targets, list):
            targets = []
        required: dict[str, int] = defaultdict(int)
        material_names: dict[str, str] = {}
        modules: list[JsonDict] = []
        unknown_inputs: list[str] = []
        reference_build = (
            isinstance(summary, dict)
            and summary.get("catalog_scope") == "commander_supplied_reference_pack"
        )
        build_catalog = (
            retained_catalogs.get(str(summary.get("catalog_version") or ""))
            if isinstance(summary, dict)
            else None
        )
        uses_catalog = build_catalog is not None
        baseline = (
            summary.get("observed_baseline") if isinstance(summary, dict) else None
        )
        build_state = baseline if isinstance(baseline, dict) else live_state
        recipe_index = (
            engineering_catalog.recipe_index(build_catalog)
            if uses_catalog
            else observed_recipe_index
        )
        if reference_build and build_catalog is None:
            unknown_inputs.append(
                "The exact reference-pack version saved with this build is unavailable."
            )
        for target in targets:
            if not isinstance(target, dict):
                continue
            unknown_inputs.extend(target.get("cost_caveats", []))
            slot = str(target.get("slot") or "").strip()
            if target.get("target_state") in {"stock", "empty"}:
                actual = None if reference_build else _actual_module(build_state, slot)
                modules.append(
                    {
                        "slot": slot,
                        "module_label": target.get("module_label")
                        or (actual or {}).get("item_localised")
                        or (actual or {}).get("item")
                        or slot,
                        "blueprint_id": None,
                        "target_grade": None,
                        "experimental_effect": None,
                        "actual_blueprint": (
                            ((actual or {}).get("engineering") or {}).get(
                                "BlueprintName"
                            )
                            if isinstance((actual or {}).get("engineering"), dict)
                            else None
                        ),
                        "actual_grade": (
                            ((actual or {}).get("engineering") or {}).get("Level")
                            if isinstance((actual or {}).get("engineering"), dict)
                            else None
                        ),
                        "actual_experimental_effect": None,
                        "compatibility_state": "observed_module_stock_values",
                        "state": "planned_legal"
                        if actual is not None
                        else "unknown_actual",
                        "target_state": target.get("target_state"),
                    }
                )
                if (
                    actual is None
                    and not reference_build
                    and target.get("target_state") != "empty"
                ):
                    unknown_inputs.append(
                        "The observed module for stock comparison is unavailable: "
                        f"{slot}."
                    )
                continue
            blueprint = str(target.get("blueprint_id") or "").strip()
            target_grade = target.get("target_grade")
            if (
                not slot
                or not blueprint
                or not isinstance(target_grade, int)
                or not 1 <= target_grade <= 5
            ):
                unknown_inputs.append(
                    "A target module has incomplete slot, blueprint, or grade data."
                )
                continue
            actual = None if reference_build else _actual_module(build_state, slot)
            same_module = (
                actual is not None
                and str(actual.get("item") or "").casefold()
                == str(target.get("module_id") or actual.get("item") or "").casefold()
            )
            engineering = actual.get("engineering") if same_module and actual else None
            if not isinstance(engineering, dict):
                engineering = {}
            actual_blueprint = str(engineering.get("BlueprintName") or "")
            actual_grade = (
                engineering.get("Level")
                if actual_blueprint.casefold() == blueprint.casefold()
                else 0
            )
            actual_grade = actual_grade if isinstance(actual_grade, int) else 0
            reset_required = actual_grade > target_grade
            if reset_required:
                # A lower-grade planned article needs fresh/cleared engineering;
                # an already higher-grade module is not that target article.
                actual_grade = 0
                unknown_inputs.append(
                    "Lower-grade targets budget fresh/cleared engineering from G1."
                )
            desired_effect = target.get("experimental_effect")
            actual_effect = engineering.get("ExperimentalEffect")
            partial_grade = bool(
                uses_catalog
                and target.get("numerical_effects_verified")
                and actual_grade
                and engineering.get("Quality") != 1
            )
            grade_ready = actual_grade >= target_grade and not partial_grade
            effect_ready = not desired_effect or (
                actual_blueprint.casefold() == blueprint.casefold()
                and not reset_required
                and str(actual_effect).casefold() == str(desired_effect).casefold()
            )
            missing_grades: list[int] = []
            start_grade = actual_grade if partial_grade else actual_grade + 1
            for grade in range(start_grade, target_grade + 1):
                recipe = recipe_index.get((blueprint.casefold(), grade))
                if recipe is None:
                    missing_grades.append(grade)
                    continue
                for material in recipe["materials"]:
                    key = _pool_key(material["material_id"])
                    required[key] += material["count"] * (
                        grade
                        if uses_catalog and target.get("numerical_effects_verified")
                        else 1
                    )
                    material_names[key] = material["display_name"]
            if uses_catalog and target.get("numerical_effects_verified"):
                unknown_inputs.append(
                    "Material total assumes rank-5 engineer access "
                    "and full completion of every unfinished grade "
                    "(1/2/3/4/5 rolls). Engineer rank and "
                    "partial-grade progress must be checked before "
                    "crafting."
                )
            if missing_grades:
                source_label = (
                    "active reference pack" if reference_build else "locally observed"
                )
                unknown_inputs.append(
                    f"No {source_label} {blueprint} recipe for grade(s) "
                    f"{', '.join(map(str, missing_grades))}."
                )
            if desired_effect and not effect_ready:
                effect_materials = (
                    engineering_catalog.experimental_cost(
                        build_catalog, blueprint, str(desired_effect)
                    )
                    if uses_catalog
                    else None
                )
                if effect_materials is None:
                    unknown_inputs.append(
                        f"Experimental effect cost for {desired_effect} is not in "
                        "the supported source subset."
                    )
                else:
                    for material in effect_materials:
                        key = _pool_key(material["material_id"])
                        required[key] += material["count"]
                        material_names[key] = material["display_name"]
            compatibility_state = (
                "catalog_validated"
                if uses_catalog
                else (
                    "observed_on_slot"
                    if actual_blueprint
                    and actual_blueprint.casefold() == blueprint.casefold()
                    else "unverified"
                )
            )
            modules.append(
                {
                    "slot": slot,
                    "module_label": target.get("module_label")
                    or (actual or {}).get("item_localised")
                    or (actual or {}).get("item")
                    or slot,
                    "blueprint_id": blueprint,
                    "target_grade": target_grade,
                    "experimental_effect": desired_effect,
                    "actual_blueprint": actual_blueprint or None,
                    "actual_grade": actual_grade if actual is not None else None,
                    "actual_experimental_effect": actual_effect,
                    "compatibility_state": compatibility_state,
                    "state": "planned_legal"
                    if reference_build
                    else (
                        "verified_ready"
                        if grade_ready and effect_ready
                        else ("unknown_actual" if actual is None else "work_remaining")
                    ),
                }
            )

        allocations: list[JsonDict] = []
        for key, needed in sorted(
            required.items(),
            key=lambda item: _material_label(
                item[0], material_names.get(item[0])
            ).casefold(),
        ):
            # A complete Materials snapshot is authoritative for the whole
            # Horizons inventory: an omitted material is an observed zero,
            # not an unknown input.
            held = available.get(key, 0) if inventory_known else None
            allocated = min(held, needed) if held is not None else None
            deficit = max(needed - held, 0) if held is not None else None
            if allocated is not None:
                available[key] = held - allocated
            allocations.append(
                {
                    "material_id": key,
                    "display_name": _material_label(key, material_names.get(key)),
                    "required": needed,
                    "held_before_reservation": held,
                    "reserved": allocated,
                    "deficit": deficit,
                    "state": "ready"
                    if deficit == 0
                    else ("deficit" if deficit is not None else "unknown_inventory"),
                }
            )
        if reference_build and build_catalog is not None:
            pack_label = f"{build_catalog['catalog_id']}@{build_catalog['version']}"
            pack_rule_set = build_catalog.get("trader_rule_set")
            trade_rule_sets[pack_label] = pack_rule_set
            verification = (
                pack_rule_set["verification"]
                if pack_rule_set
                else "declared_unverified"
            )
            trade_rules[build.build_plan_id] = (
                pack_label,
                [
                    {
                        "rule_id": rule["id"],
                        "category": rule["category"],
                        "from_key": _pool_key(rule["from_material_id"]),
                        "from_display_name": rule["from_display_name"],
                        "to_key": _pool_key(rule["to_material_id"]),
                        "to_display_name": rule["to_display_name"],
                        "pay": rule["pay"],
                        "receive": rule["receive"],
                        "notes": rule.get("notes"),
                        "from_category": rule.get("from_category"),
                        "to_category": rule.get("to_category"),
                        "verification": verification,
                    }
                    for rule in build_catalog.get("trader_rules", [])
                ],
            )
        trade_alternatives: list[JsonDict] = []
        if reference_build and inventory_known and build_catalog is not None:
            deficits = {
                row["material_id"]: row["deficit"]
                for row in allocations
                if isinstance(row["deficit"], int) and row["deficit"] > 0
            }
            for rule in build_catalog.get("trader_rules", []):
                from_key = _pool_key(rule["from_material_id"])
                to_key = _pool_key(rule["to_material_id"])
                deficit = deficits.get(to_key)
                source_available = available.get(from_key, 0)
                possible = (source_available // rule["pay"]) * rule["receive"]
                if not deficit or possible <= 0:
                    continue
                trade_alternatives.append(
                    {
                        "rule_id": rule["id"],
                        "category": rule["category"],
                        "from_material_id": from_key,
                        "from_display_name": rule["from_display_name"],
                        "to_material_id": to_key,
                        "to_display_name": rule["to_display_name"],
                        "pay": rule["pay"],
                        "receive": rule["receive"],
                        "source_available_after_reservations": source_available,
                        "possible_receive": possible,
                        "useful_receive": min(possible, deficit),
                        "proposal_only": True,
                        "notes": rule.get("notes"),
                    }
                )
        costs_known = not unknown_inputs
        inventory_ready = inventory_known and all(
            row["deficit"] == 0 for row in allocations
        )
        complete = bool(modules) and (
            costs_known and inventory_ready
            if reference_build
            else all(row["state"] == "verified_ready" for row in modules)
        )
        results.append(
            {
                "build_plan_id": build.build_plan_id,
                "goal_id": goal_by_build[build.build_plan_id].goal_id
                if build.build_plan_id in goal_by_build
                else None,
                "title": build.title,
                "priority": goal_by_build[build.build_plan_id].priority
                if build.build_plan_id in goal_by_build
                else "unsorted",
                "modules": modules,
                "materials": allocations,
                "trade_alternatives": trade_alternatives,
                "unknown_inputs": unknown_inputs,
                "readiness": "verified_ready"
                if complete
                else ("unknown" if unknown_inputs else "blocked"),
                "next_action": (
                    (
                        "Planned build is legal in the active reference pack and "
                        "its assessed materials are available."
                        if reference_build
                        else "Target build is verified on the observed current loadout."
                    )
                    if complete
                    else unknown_inputs[0]
                    if unknown_inputs
                    else next(
                        (
                            f"Acquire {row['deficit']} {row['display_name']}."
                            for row in allocations
                            if row["deficit"]
                        ),
                        "Review the target against the current ship.",
                    )
                ),
                "catalog_version": summary.get("catalog_version", CATALOG_VERSION)
                if isinstance(summary, dict)
                else CATALOG_VERSION,
                "calculation_version": summary.get(
                    "calculation_version", CALCULATION_VERSION
                )
                if isinstance(summary, dict)
                else CALCULATION_VERSION,
                "performance": engineering_workbench.performance_comparison(
                    build_state,
                    targets,
                    build_catalog,
                    summary.get("power_plan"),
                    summary.get("operating_conditions"),
                )
                if not reference_build and include_workbenches
                else {
                    "version": engineering_workbench.PERFORMANCE_VERSION,
                    "metrics": [],
                    "module_changes": [],
                    "assumptions": (
                        "Performance is unavailable because this reference-pack "
                        "build does not include a verified performance model."
                    ),
                },
            }
        )

    if not include_workbenches:
        return {"inventory": inventory, "builds": results}

    trader_rules = material_trader.safe_rules()
    workbench = engineering_workbench.build_observed_workbench(
        live_state, recipe_rows, reference_catalog
    )
    saved_configurations: list[JsonDict] = []
    for build in active_builds:
        summary = build.target_loadout_summary
        if not isinstance(summary, dict) or summary.get("catalog_scope") == (
            "commander_supplied_reference_pack"
        ):
            continue
        saved_targets = summary.get("module_targets")
        if not isinstance(saved_targets, list):
            continue
        validation_error = None
        baseline = summary.get("observed_baseline")
        build_state = baseline if isinstance(baseline, dict) else live_state
        build_catalog = retained_catalogs.get(str(summary.get("catalog_version") or ""))
        saved_workbench = engineering_workbench.build_observed_workbench(
            build_state, recipe_rows, build_catalog
        )
        try:
            planned_targets = engineering_workbench.validate_observed_targets(
                saved_workbench,
                saved_targets,
                allow_empty=isinstance(summary.get("power_plan"), dict),
            )
            validation_state = "validated_current_loadout"
        except ValueError as exc:
            # Preserve legacy plans verbatim. They remain visible and
            # explainable, but are not silently rewritten into current-valid
            # targets after the compatibility rules become stricter.
            planned_targets = saved_targets
            validation_state = "legacy_unchecked"
            validation_error = str(exc)
        configuration = {
            "build_plan_id": build.build_plan_id,
            "title": build.title,
            "targets": planned_targets,
            "power_plan": summary.get("power_plan"),
            "operating_conditions": summary.get("operating_conditions"),
            "validation_state": validation_state,
            "baseline": baseline,
            "constraints": summary.get(
                "constraints", {"preserve_cargo_capacity": True}
            ),
            "validation_error": validation_error,
            "performance": engineering_workbench.performance_comparison(
                build_state,
                planned_targets,
                build_catalog,
                summary.get("power_plan"),
                summary.get("operating_conditions"),
            ),
        }
        fit_errors = (
            configuration["performance"]
            .get("configuration_check", {})
            .get("errors", [])
        )
        if fit_errors:
            configuration["validation_state"] = "legacy_invalid"
            configuration["validation_error"] = "; ".join(fit_errors)
        saved_workbench.pop("_catalog", None)
        saved_workbench["planned_configuration"] = configuration
        saved_configurations.append(
            {
                "build_plan_id": build.build_plan_id,
                "title": build.title,
                "workbench": saved_workbench,
            }
        )
    workbench.pop("_catalog", None)
    if saved_configurations:
        workbench["planned_configuration"] = saved_configurations[0]["workbench"][
            "planned_configuration"
        ]
    observed_ships = []
    seen_ships = set()
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(JournalEvent)
                .where(JournalEvent.event_type == "Loadout")
                .order_by(JournalEvent.timestamp.desc(), JournalEvent.id.desc())
                .limit(256)
            )
        ).scalars()
        for row in rows:
            try:
                event = json.loads(row.raw_json)
            except (ValueError, TypeError):
                continue
            if not isinstance(event, dict):
                continue
            ship_key = (str(event.get("Ship") or "").casefold(), event.get("ShipID"))
            if not ship_key[0] or ship_key in seen_ships:
                continue
            seen_ships.add(ship_key)
            observed_ships.append(
                {
                    "observation_id": row.id,
                    "observed_at": event.get("timestamp"),
                    "ship_type": event.get("Ship"),
                    "ship_id": event.get("ShipID"),
                    "ship_name": event.get("ShipName"),
                    "ship_ident": event.get("ShipIdent"),
                }
            )
    trader_payload = material_trader.payload(
        trader_rules,
        results,
        observed_pool,
        inventory,
        await material_trader.observed_trades(session_factory, trader_rules),
    )
    return {
        "observed_ships": observed_ships,
        "saved_configurations": saved_configurations,
        "inventory": inventory,
        "observed_recipes": recipe_rows,
        "engineer_progress": await engineer_progress(session_factory),
        "engineer_contributions": await engineer_contributions(session_factory),
        "engineer_directory": engineer_directory.safe_snapshot(),
        "material_trader": trader_payload,
        # GKI-05: where and how to get each short material, from this portfolio's
        # own shortages and trader plan plus the shipped knowledge packs.
        "acquisition_intelligence": material_intelligence.scopes(
            galactic_knowledge.index()
            if galactic_knowledge.catalog()["state"] == "available"
            else None,
            results,
            inventory,
            trader_payload,
            system=live_state.get("local_system_context")
            if isinstance(live_state.get("local_system_context"), dict)
            else None,
        ),
        "acquisition": material_acquisition.build_acquisition(
            results,
            observed_pool,
            inventory,
            trade_rules,
            trade_rule_sets,
            documented_categories=_documented_categories(results),
        ),
        "observed_loadout_catalog": loadout_catalog,
        "reference_catalog": engineering_catalog.designer_catalog(reference_catalog),
        "catalog_scope": CATALOG_SCOPE,
        "catalog_version": CATALOG_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "workbench": workbench,
        "builds": results,
        "allocation_policy": (
            "Active builds reserve one shared inventory pool in high, normal, "
            "unsorted, then low priority order."
        ),
        "fixed_roll_policy": (
            "One observed ingredient bill is counted for each unfinished grade; "
            "missing observed grades remain unknown."
        ),
    }
