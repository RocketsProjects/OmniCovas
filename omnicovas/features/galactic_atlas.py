"""Galactic Atlas relevance: why a documented place matters to the Commander's goals.

The Atlas itself is reference knowledge (``galactic_knowledge``).  This module answers
one deterministic question for an Atlas entry: which of its documented acquisition
opportunities touch a material that an active Engineering build is short of, using
the same portfolio allocation the Engineering workspace shows.

Nothing here predicts yields or claims a shortfall will be filled at a place: a site
being a documented source of a material says nothing about how many will drop.  An
unknown inventory stays unknown, never zero.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.features import engineering_progression
from omnicovas.features.engineering import BuildPlanRecord, EngineeringGoalRecord
from omnicovas.features.galactic_knowledge import KnowledgeIndex

JsonDict = dict[str, Any]

VERSION = "galactic-atlas-relevance-v1"


def documented_materials(knowledge: KnowledgeIndex, entity_id: str) -> list[JsonDict]:
    """Materials an Atlas entry's documented activities can yield, in pack order."""
    rows: dict[str, JsonDict] = {}
    for activity in knowledge.atlas_entry(entity_id)["practical"]:
        for material in activity["materials"]:
            inventory = material.get("inventory") or {}
            if inventory.get("store") != "materials" or material["id"] in rows:
                continue
            rows[material["id"]] = {
                "id": material["id"],
                "name": material["name"],
                "symbol": inventory["symbol"],
                "grade": inventory.get("grade"),
                "activity": {"id": activity["id"], "name": activity["name"]},
            }
    return list(rows.values())


async def relevance(
    session_factory: async_sessionmaker[AsyncSession],
    knowledge: KnowledgeIndex,
    entity_id: str,
    *,
    builds: list[BuildPlanRecord],
    goals: list[EngineeringGoalRecord],
    live_state: JsonDict,
) -> JsonDict:
    """Why an Atlas entry may matter to active Engineering builds, with evidence.

    Raises ``KeyError`` for an unknown entry.
    """
    materials = documented_materials(knowledge, entity_id)
    base: JsonDict = {
        "version": VERSION,
        "entity_id": entity_id,
        "materials": [],
        "reasons": [],
    }
    if not materials:
        return {
            **base,
            "state": "no_documented_opportunity",
            "explanation": "No acquisition opportunity is documented here, so it is "
            "not tied to your Engineering plans.",
        }
    progression = await engineering_progression.portfolio(
        session_factory, builds, goals, live_state, include_workbenches=False
    )
    inventory = progression.get("inventory") or {}
    inventory_known = inventory.get("state") == "verified_local"
    held = {
        str(row["material_id"]): row.get("count")
        for row in inventory.get("materials", [])
    }
    by_symbol = {row["symbol"]: row for row in materials}
    reasons: list[JsonDict] = []
    unknown_builds: list[str] = []
    for build in progression.get("builds", []):
        for row in build.get("materials", []):
            material = by_symbol.get(str(row.get("material_id")))
            if material is None:
                continue
            deficit = row.get("deficit")
            if deficit is None:
                unknown_builds.append(build["title"])
            elif deficit > 0:
                reasons.append(
                    {
                        "build_plan_id": build["build_plan_id"],
                        "build": build["title"],
                        "priority": build.get("priority"),
                        "material": {"id": material["id"], "name": material["name"]},
                        "deficit": deficit,
                        "activity": material["activity"],
                    }
                )
    rows = [
        {
            **material,
            # A complete Materials record lists everything held, so an absent
            # material is an observed zero, exactly as the Materials workspace says.
            "owned": int(held.get(material["symbol"]) or 0)
            if inventory_known
            else None,
            "quantity_state": "observed" if inventory_known else "unknown",
            "needed_by": [
                reason["build"]
                for reason in reasons
                if reason["material"]["id"] == material["id"]
            ],
        }
        for material in materials
    ]
    if reasons:
        state = "relevant"
        count = len({reason["build_plan_id"] for reason in reasons})
        explanation = (
            f"{count} active build{' is' if count == 1 else 's are'} short of a "
            "material documented here. Drops are not guaranteed amounts, so the "
            "shortfall is shown, not a promise to fill it."
        )
    elif unknown_builds:
        state = "unknown"
        explanation = (
            "Your builds use materials documented here, but your Materials record "
            "is not complete, so OmniCOVAS cannot tell whether you are short."
        )
    elif not progression.get("builds"):
        state = "no_active_builds"
        explanation = "No active Engineering build to compare against."
    else:
        state = "not_needed"
        explanation = (
            "None of your active builds is short of a material documented here."
        )
    return {
        **base,
        "state": state,
        "explanation": explanation,
        "inventory_state": inventory.get("state") or "unavailable",
        "materials": rows,
        "reasons": reasons,
    }
