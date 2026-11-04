"""Truthful observed-ship workbench classification and performance preview.

This module deliberately works from the Commander's current Loadout projection.
It is not a universal Elite catalogue.  Physical slot classification is based
on Journal slot/item families; engineering choices are exposed only when a
blueprint family is independently compatible with that module family and the
choice is grounded by an observed craft recipe or the module's own installed
engineering block.

Projected deltas reuse the canonical performance engine: observed modifiers,
compatible catalogue replacements, and explicit grade/experimental endpoints.
Arbitrary interpolation and unavailable jump constants are never invented.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

from omnicovas.features import engineering_catalog, outfitting_rules, ship_performance

JsonDict = dict[str, Any]

CONFIGURATION_VERSION = "canonical-planned-loadout-v4"
PERFORMANCE_VERSION = ship_performance.PERFORMANCE_VERSION

_RATING = {5: "A", 4: "B", 3: "C", 2: "D", 1: "E"}

_CORE_SLOTS = {
    "Armour": ("core", "Armour"),
    "PowerPlant": ("core", "Power Plant"),
    "MainEngines": ("core", "Thrusters"),
    "FrameShiftDrive": ("core", "Frame Shift Drive"),
    "LifeSupport": ("core", "Life Support"),
    "PowerDistributor": ("core", "Power Distributor"),
    "Radar": ("core", "Sensors"),
    "FuelTank": ("core", "Fuel Tank"),
}

_SPECIAL_SLOTS = {
    "CargoHatch",
    "PlanetaryApproachSuite",
    "ShipCockpit",
    "VesselVoice",
}

# Compatibility is intentionally narrower than a global game catalogue.  Each
# prefix is a stable Journal blueprint family and maps to one observed module
# family. Unknown blueprint families remain unavailable.
_BLUEPRINT_PREFIXES: dict[str, tuple[str, ...]] = {
    "thrusters": ("engine_",),
    "fsd": ("fsd_",),
    "power_plant": ("powerplant_",),
    "power_distributor": ("powerdistributor_",),
    "sensors": ("sensor_",),
    "life_support": ("lifesupport_",),
    "shield_generator": ("shieldgenerator_",),
    "armour": ("armour_", "bulkheads_"),
    "weapon": (
        "weapon_",
        "beamlaser_",
        "pulselaser_",
        "burstlaser_",
        "multicannon_",
        "cannon_",
        "railgun_",
        "plasmaaccelerator_",
        "missilerack_",
        "fragcannon_",
    ),
    "utility": (
        "chafflauncher_",
        "heatsinklauncher_",
        "shieldbooster_",
        "killwarrantscanner_",
        "wake_scanner_",
    ),
}

_BLUEPRINT_NAMES = {
    "engine_dirty": "Dirty Drive Tuning",
    "engine_clean": "Clean Drive Tuning",
    "engine_strengthened": "Strengthened Thrusters",
    "fsd_longrange": "Increased Range",
    "fsd_fastboot": "Faster Boot Sequence",
    "powerplant_boosted": "Overcharged Power Plant",
    "powerplant_armoured": "Armoured Power Plant",
    "powerplant_lowemissions": "Low Emissions Power Plant",
    "powerplant_stealth": "Low Emissions Power Plant",
    "powerdistributor_prioritysystems": "Charge Enhanced Power Distributor",
    "sensor_lightweight": "Lightweight Sensors",
    "sensor_longrange": "Long Range Sensors",
    "lifesupport_lightweight": "Lightweight Life Support",
}

_EXPERIMENTAL_NAMES = {
    "special_engine_overloaded": "Drag Drives",
    "special_powerplant_highcharge": "Monstered",
    "special_powerplant_cooled": "Thermal Spread",
    "special_powerplant_lightweight": "Stripped Down",
    "special_powerplant_toughened": "Double Braced",
    "mass_manager": "Mass Manager",
    "stripped_down": "Stripped Down",
    "thermal_spread": "Thermal Spread",
}

_FAMILY_CATEGORIES = {
    "thrusters": "thrusters",
    "fsd": "frame_shift_drive",
    "power_plant": "power_plant",
    "power_distributor": "power_distributor",
    "sensors": "sensors",
    "life_support": "life_support",
    "shield_generator": "shield_generator",
    "armour": "armour",
    "weapon": "weapon",
    "utility": "utility",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _module_family(item: str) -> str | None:
    value = item.casefold()
    if value.startswith("int_engine_"):
        return "thrusters"
    if value.startswith("int_hyperdrive_"):
        return "fsd"
    if value.startswith("int_powerplant_"):
        return "power_plant"
    if value.startswith("int_powerdistributor_"):
        return "power_distributor"
    if value.startswith("int_sensors_"):
        return "sensors"
    if value.startswith("int_lifesupport_"):
        return "life_support"
    if value.startswith("int_shieldgenerator_"):
        return "shield_generator"
    if "_armour_" in value or value.endswith("_armour_grade1"):
        return "armour"
    if value.startswith(("hpt_", "wpn_")) and "_tiny" not in value:
        return "weapon"
    if value.startswith("hpt_") and "_tiny" in value:
        return "utility"
    return None


def blueprint_compatible(family: str | None, blueprint_id: str) -> bool:
    if not family or not blueprint_id:
        return False
    value = blueprint_id.casefold()
    return any(
        value.startswith(prefix) for prefix in _BLUEPRINT_PREFIXES.get(family, ())
    )


def _blueprint_name(blueprint_id: str, localised: Any = None) -> str:
    label = str(localised or "").strip()
    return (
        label
        or _BLUEPRINT_NAMES.get(blueprint_id.casefold())
        or blueprint_id.replace("_", " ")
    )


def _experimental_name(effect_id: str | None, localised: Any = None) -> str | None:
    if not effect_id:
        return None
    label = str(localised or "").strip()
    return (
        label
        or _EXPERIMENTAL_NAMES.get(effect_id.casefold())
        or effect_id.replace("_", " ")
    )


def _slot_group(slot: str, item: str) -> tuple[str, str, bool]:
    if slot in _CORE_SLOTS:
        group, label = _CORE_SLOTS[slot]
        return group, label, True
    if slot in _SPECIAL_SLOTS or slot.casefold().startswith(("decal", "shipkit")):
        return "special", "Ship equipment", False
    if re.match(r"^(tiny)hardpoint\d+$", slot, re.IGNORECASE):
        return "utility", "Utility mount", True
    if re.match(r"^(small|medium|large|huge)hardpoint\d+$", slot, re.IGNORECASE):
        return "hardpoints", "Hardpoint", True
    if re.match(
        r"^(slot\d+_size\d+|optionalinternal\d+|cargo\d+)$", slot, re.IGNORECASE
    ):
        return "optional", "Optional internal", True
    # Unrecognised Loadout objects stay visible in a non-editable group. This
    # prevents raw cosmetics/support objects becoming engineerable controls.
    return "special", "Other fitted item", False


def _size_rating(item: str, family: str | None) -> tuple[int | None, str | None]:
    match = re.search(r"_size(\d+)_class(\d+)", item, re.IGNORECASE)
    if not match:
        return None, None
    size, raw_rating = int(match.group(1)), int(match.group(2))
    rating = _RATING.get(raw_rating)
    return size, rating


def _friendly_name(
    raw: JsonDict, family: str | None, size: int | None, rating: str | None
) -> str:
    localised = str(raw.get("item_localised") or "").strip()
    family_names = {
        "thrusters": "Thrusters",
        "fsd": "Frame Shift Drive",
        "power_plant": "Power Plant",
        "power_distributor": "Power Distributor",
        "sensors": "Sensors",
        "life_support": "Life Support",
        "shield_generator": "Shield Generator",
        "armour": "Armour",
    }
    item = str(raw.get("item") or "").casefold()
    observed_names = (
        ("int_corrosionproofcargorack_", "Corrosion Resistant Cargo Rack"),
        ("int_largecargorack_", "Cargo Rack"),
        ("int_cargorack_", "Cargo Rack"),
        ("int_fueltank_", "Fuel Tank"),
        ("int_dockingcomputer_advanced", "Advanced Docking Computer"),
        ("int_dockingcomputer_", "Docking Computer"),
        ("int_supercruiseassist", "Supercruise Assist"),
        ("modularcargobaydoor", "Cargo Hatch"),
        ("int_planetapproachsuite_advanced", "Advanced Planetary Approach Suite"),
        ("int_planetapproachsuite", "Planetary Approach Suite"),
        ("voicepack_", "Ship Voice"),
        ("decal_", "Ship Decal"),
    )
    observed_name = next(
        (label for prefix, label in observed_names if item.startswith(prefix)), None
    )
    if item.endswith("_cockpit"):
        observed_name = "Ship Cockpit"
    base = (
        localised or family_names.get(family or "") or observed_name or "Fitted module"
    )
    prefix = (
        f"{size}{rating}"
        if size is not None and rating
        else (f"Class {size}" if size is not None else "")
    )
    if prefix and prefix.casefold() not in base.casefold():
        return f"{prefix} {base}"
    return base


def _engineering(raw: JsonDict) -> JsonDict:
    value = raw.get("engineering")
    return value if isinstance(value, dict) else {}


def _modifier_rows(engineering: JsonDict) -> list[JsonDict]:
    return ship_performance.modifier_rows(engineering)


def _recipe_options(
    family: str | None,
    engineering: JsonDict,
    recipes: Iterable[JsonDict],
) -> list[JsonDict]:
    options: dict[str, JsonDict] = {}
    current_id = str(engineering.get("BlueprintName") or "").strip()
    current_grade = engineering.get("Level")
    current_effect = str(engineering.get("ExperimentalEffect") or "").strip() or None
    if blueprint_compatible(family, current_id) and isinstance(current_grade, int):
        options[current_id.casefold()] = {
            "id": current_id,
            "label": _blueprint_name(
                current_id, engineering.get("BlueprintName_Localised")
            ),
            "grades": [current_grade],
            "experimentals": [
                {
                    "id": current_effect,
                    "label": _experimental_name(
                        current_effect, engineering.get("ExperimentalEffect_Localised")
                    ),
                }
            ]
            if current_effect
            else [],
            "evidence": "installed on this module",
        }
    for recipe in recipes:
        blueprint = str(recipe.get("blueprint_id") or "").strip()
        grade = recipe.get("grade")
        if not blueprint_compatible(family, blueprint) or not isinstance(grade, int):
            continue
        key = blueprint.casefold()
        option = options.setdefault(
            key,
            {
                "id": blueprint,
                "label": _blueprint_name(blueprint, recipe.get("blueprint_label")),
                "grades": [],
                "experimentals": [],
                "evidence": "locally observed craft recipe",
            },
        )
        if grade not in option["grades"]:
            option["grades"].append(grade)
        effect = str(recipe.get("experimental_effect") or "").strip()
        if effect and not any(row["id"] == effect for row in option["experimentals"]):
            option["experimentals"].append(
                {"id": effect, "label": _experimental_name(effect)}
            )
    for option in options.values():
        option["grades"].sort()
    return sorted(options.values(), key=lambda row: str(row["label"]).casefold())


def _catalog_hull(catalog: JsonDict | None, ship_type: Any) -> JsonDict | None:
    if not isinstance(catalog, dict) or not ship_type:
        return None
    wanted = str(ship_type).casefold()
    return next(
        (
            row
            for row in catalog.get("hulls", [])
            if isinstance(row, dict) and str(row.get("id") or "").casefold() == wanted
        ),
        None,
    )


def _catalog_slot(hull: JsonDict | None, slot: str) -> JsonDict | None:
    if hull is None:
        return None
    wanted = slot.casefold()
    return next(
        (
            row
            for row in hull.get("slots", [])
            if isinstance(row, dict) and str(row.get("id") or "").casefold() == wanted
        ),
        None,
    )


def _module_options(
    catalog: JsonDict | None, hull: JsonDict | None, slot: JsonDict | None
) -> list[JsonDict]:
    if not isinstance(catalog, dict) or hull is None or slot is None:
        return []
    result: list[JsonDict] = []
    for module in catalog.get("modules", []):
        if not isinstance(module, dict):
            continue
        legal = outfitting_rules.compatible(module, hull, slot)
        if legal:
            result.append(
                {
                    "id": module["id"],
                    "name": module["name"],
                    "category": module["category"],
                    "class": module["class"],
                    "rating": module.get("rating"),
                    "stats": dict(module.get("stats", {})),
                    "blueprint_ids": outfitting_rules.supported_blueprint_ids(
                        module, catalog
                    ),
                    "engineering_gaps": outfitting_rules.engineering_gaps(
                        module, catalog
                    ),
                    "experimental_ids": module.get("experimental_ids"),
                    "compatibility_evidence": "active_reference_pack",
                }
            )
    return sorted(
        result,
        key=lambda row: (-int(row["class"]), str(row.get("rating") or ""), row["name"]),
    )


def _catalog_blueprint_options(
    catalog: JsonDict | None, category: str | None, module: JsonDict | None = None
) -> list[JsonDict]:
    if not isinstance(catalog, dict) or not category:
        return []
    result = []
    for blueprint in catalog.get("blueprints", []):
        if not isinstance(blueprint, dict):
            continue
        if category not in blueprint.get("module_categories", []):
            continue
        if module is not None and outfitting_rules.engineering_gap(module, blueprint):
            continue
        if (
            module is not None
            and module.get("blueprint_ids") is not None
            and blueprint["id"] not in module["blueprint_ids"]
        ):
            continue
        result.append(
            {
                "id": blueprint["id"],
                "label": blueprint["name"],
                "grades": sorted(int(value) for value in blueprint["grades"]),
                "grade_effects": dict(blueprint.get("grade_effects", {})),
                "attribute_effects": dict(blueprint.get("attribute_effects", {})),
                "materials_by_grade": dict(blueprint["grades"]),
                "cost_caveats": blueprint.get("cost_caveats", []),
                "numerical_data_complete": blueprint.get(
                    "numerical_data_complete", True
                ),
                "experimentals": [
                    {
                        "id": effect["id"],
                        "label": effect["name"],
                        "effects": dict(effect.get("effects", {})),
                        "materials": effect.get("materials"),
                        "attribute_effects": effect.get("attribute_effects", {}),
                        "special": effect.get("special"),
                    }
                    for effect in blueprint.get("experimentals", [])
                    if module is None
                    or module.get("experimental_ids") is None
                    or effect["id"] in module["experimental_ids"]
                ],
                "effect_rule": blueprint.get(
                    "effect_rule", "additive_percent_of_unmodified_base"
                ),
                "evidence": "active reference pack",
            }
        )
    return sorted(result, key=lambda row: str(row["label"]).casefold())


def build_observed_workbench(
    live_state: JsonDict,
    recipes: Iterable[JsonDict],
    reference_catalog: JsonDict | None = None,
) -> JsonDict:
    modules = live_state.get("modules")
    groups: dict[str, list[JsonDict]] = {
        key: [] for key in ("core", "optional", "hardpoints", "utility", "special")
    }
    hull = _catalog_hull(reference_catalog, live_state.get("current_ship_type"))
    if isinstance(modules, dict):
        modules = dict(modules)
        if hull:
            for slot in hull["slots"]:
                modules.setdefault(slot["id"], {"item": "", "on": True})
        for slot, raw in modules.items():
            if not isinstance(raw, dict):
                continue
            item = str(raw.get("item") or "")
            family = _module_family(item)
            group, slot_label, physical = _slot_group(str(slot), item)
            size, rating = _size_rating(item, family)
            engineering = _engineering(raw)
            reference_slot = _catalog_slot(hull, str(slot))
            if reference_slot:
                physical = True
                group = {
                    "component": "core",
                    "hardpoint": "hardpoints",
                    "internal": "optional",
                    "military": "optional",
                    "utility": "utility",
                }.get(str(reference_slot.get("group") or ""), group)
                slot_label = reference_slot["label"]
            module_options = _module_options(reference_catalog, hull, reference_slot)
            category = _FAMILY_CATEGORIES.get(family or "")
            installed_reference = next(
                (
                    choice
                    for choice in module_options
                    if choice["id"].casefold() == item.casefold()
                ),
                None,
            )
            if installed_reference is not None:
                category = installed_reference["category"]
            options = (
                _catalog_blueprint_options(
                    reference_catalog,
                    category,
                    next(
                        (
                            m
                            for m in reference_catalog.get("modules", [])
                            if m["id"].casefold() == item.casefold()
                        ),
                        None,
                    )
                    if reference_catalog
                    else None,
                )
                or _recipe_options(family, engineering, recipes)
                if physical
                else []
            )
            engineerable = bool((family or category) and options and physical)
            canonical: JsonDict = next(
                (
                    m
                    for m in (reference_catalog or {}).get("modules", [])
                    if m["id"].casefold() == item.casefold()
                ),
                {},
            )
            definitions = (reference_catalog or {}).get("attribute_definitions", {})
            observed = outfitting_rules.observed_attributes(raw, canonical, definitions)
            variant_note = None
            installed_blueprint = next(
                (
                    b
                    for b in (reference_catalog or {}).get("blueprints", [])
                    if b["id"] == engineering.get("BlueprintName")
                ),
                None,
            )
            if (
                canonical.get("attributes")
                and installed_blueprint
                and engineering.get("Quality") == 1
            ):
                experimental = next(
                    (
                        e
                        for e in installed_blueprint.get("experimentals", [])
                        if e["id"] == engineering.get("ExperimentalEffect")
                    ),
                    None,
                )
                standard = outfitting_rules.attribute_values(
                    {
                        **outfitting_rules.target_metadata(
                            canonical,
                            installed_blueprint,
                            engineering.get("Level"),
                            experimental,
                            definitions,
                        ),
                        "target_state": "engineered",
                        "numerical_effects_verified": True,
                    }
                )
                if any(
                    not math.isclose(value, standard[k], rel_tol=0.0001, abs_tol=0.0001)
                    for k, value in observed.items()
                    if k in standard
                ):
                    variant_note = (
                        "Nonstandard observed modifiers. Unchanged engineering retains "
                        "them; "
                        "new engineering uses the standard catalogue recipe."
                    )
            groups[group].append(
                {
                    "slot": str(slot),
                    "slot_label": slot_label,
                    "module_id": item,
                    "name": (
                        installed_reference["name"]
                        if installed_reference
                        else _friendly_name(raw, family, size, rating)
                    )
                    if item
                    else f"Empty {slot_label}",
                    "size": size,
                    "rating": rating,
                    "family": family,
                    "engineerable": engineerable,
                    "eligibility": (
                        "verified_options"
                        if engineerable
                        else "not_engineerable"
                        if not family or not physical
                        else "unchecked_no_compatible_local_evidence"
                    ),
                    "installed_engineering": {
                        "blueprint_id": engineering.get("BlueprintName"),
                        "blueprint_label": _blueprint_name(
                            str(engineering.get("BlueprintName") or ""),
                            engineering.get("BlueprintName_Localised"),
                        )
                        if engineering.get("BlueprintName")
                        else None,
                        "grade": engineering.get("Level"),
                        "experimental_effect_id": engineering.get("ExperimentalEffect"),
                        "experimental_effect": _experimental_name(
                            str(engineering.get("ExperimentalEffect") or "") or None,
                            engineering.get("ExperimentalEffect_Localised"),
                        ),
                    },
                    "blueprint_options": options,
                    "module_options": module_options,
                    "reference_slot": reference_slot,
                    "attribute_changes": _modifier_rows(engineering),
                    "power_draw": _number(raw.get("power")),
                    "installed_attributes": observed,
                    "reference_variant_note": variant_note,
                    "attribute_definitions": {
                        k: v for k, v in definitions.items() if k in observed
                    },
                    "on": raw.get("on"),
                    "technical": {"slot": str(slot), "item": item},
                }
            )
    for rows in groups.values():
        rows.sort(key=lambda row: (str(row["slot_label"]), str(row["slot"])))
    ship_name = live_state.get("current_ship_name")
    ship_type = live_state.get("current_ship_type")
    return {
        "state": "verified_local" if ship_type and any(groups.values()) else "unknown",
        "planning_hull_id": live_state.get("planning_hull_id"),
        "configuration_version": CONFIGURATION_VERSION,
        "performance_version": PERFORMANCE_VERSION,
        "ship": {
            "ship_type": ship_type,
            "ship_id": live_state.get("current_ship_id"),
            "ship_name": ship_name,
            "ship_ident": live_state.get("current_ship_ident"),
        },
        "groups": [
            {"id": key, "label": label, "modules": groups[key]}
            for key, label in (
                ("core", "Core internals"),
                ("optional", "Optional internals"),
                ("hardpoints", "Hardpoints"),
                ("utility", "Utility mounts"),
                ("special", "Ship equipment"),
            )
            if groups[key]
        ],
        "comparison": performance_comparison(live_state, [], reference_catalog),
        "_catalog": reference_catalog,
        "blueprint_definitions": (reference_catalog or {}).get("blueprints", []),
        "catalog": (
            {
                "catalog_id": reference_catalog.get("catalog_id"),
                "version": reference_catalog.get("version"),
                "hull_matched": hull is not None,
            }
            if isinstance(reference_catalog, dict)
            else None
        ),
        "limitations": [
            "Catalogue choices are restricted to verified slot/category/class rules. "
            "Other engineering options require observed evidence.",
            "Module swaps need a validated local reference pack; the Journal "
            "does not publish a universal outfitting catalogue.",
        ],
    }


def performance_comparison(
    live_state: JsonDict,
    targets: Iterable[JsonDict],
    reference_catalog: JsonDict | None = None,
    power_plan: JsonDict | None = None,
    operating_conditions: JsonDict | None = None,
) -> JsonDict:
    return ship_performance.performance_comparison(
        live_state, targets, reference_catalog, power_plan, operating_conditions
    )


def catalogue_baseline(catalog: JsonDict, hull_id: str) -> JsonDict:
    """A reproducible stock planning baseline, never a Journal observation."""
    hull = _catalog_hull(catalog, hull_id)
    if hull is None:
        raise ValueError("Hull is not present in the validated local catalogue.")
    records = {m["id"]: m for m in catalog["modules"]}
    modules = {}
    for slot in hull["slots"]:
        identifier = hull.get("stock_modules", {}).get(slot["id"], "")
        if identifier and identifier not in records:
            raise ValueError("The stock fit references an unavailable module.")
        if identifier and not outfitting_rules.compatible(
            records[identifier], hull, slot
        ):
            raise ValueError("The stock fit violates the verified fitting rules.")
        if slot.get("required") and not identifier:
            raise ValueError("The catalogue has no stock fit for a required core slot.")
        # This baseline uses the same zero-based priority input as Journal data.
        modules[slot["id"]] = {"item": identifier, "on": True, "priority": 0}
    # The pinned reference explicitly includes the hatch electrical load.
    if "modularcargobaydoor" in records:
        modules["CargoHatch"] = {
            "item": "modularcargobaydoor",
            "on": True,
            "priority": 0,
        }
    fitted = [records[m["item"]] for m in modules.values() if m["item"]]
    mass_values = [m.get("stats", {}).get("mass") for m in fitted]
    mass = hull.get("stats", {}).get("hull_mass")
    return {
        "planning_hull_id": hull_id,
        "current_ship_type": hull_id,
        "current_ship_name": hull["name"],
        "modules": modules,
        "unladen_mass": mass + math.fsum(mass_values)
        if mass is not None and all(v is not None for v in mass_values)
        else None,
        "cargo_capacity": math.fsum(
            m.get("stats", {}).get("cargo_capacity", 0) for m in fitted
        ),
        "fuel_capacity_main": math.fsum(
            m.get("stats", {}).get("fuel_capacity", 0) for m in fitted
        ),
        "jump_range_ly": None,
    }


def observed_baseline(live_state: JsonDict) -> JsonDict:
    """Retain only local inputs needed to reproduce a saved ship comparison."""
    import copy

    keys = (
        "planning_hull_id",
        "current_ship_type",
        "current_ship_id",
        "current_ship_name",
        "current_ship_ident",
        "unladen_mass",
        "cargo_capacity",
        "jump_range_ly",
        "fuel_capacity_main",
        "modules",
    )
    return copy.deepcopy({key: live_state.get(key) for key in keys})


def loadout_baseline(event: JsonDict) -> JsonDict:
    """Build a planning snapshot from a real Journal Loadout, without live writes."""
    from dataclasses import asdict

    from omnicovas.features.loadout import modules_from_loadout_event

    return {
        "current_ship_type": event.get("Ship"),
        "current_ship_id": event.get("ShipID"),
        "current_ship_name": event.get("ShipName"),
        "current_ship_ident": event.get("ShipIdent"),
        "unladen_mass": event.get("UnladenMass"),
        "cargo_capacity": event.get("CargoCapacity"),
        "jump_range_ly": event.get("MaxJumpRange"),
        "fuel_capacity_main": (event.get("FuelCapacity") or {}).get("Main"),
        "modules": {k: asdict(v) for k, v in modules_from_loadout_event(event).items()},
    }


def validate_observed_targets(
    workbench: JsonDict,
    targets: Iterable[JsonDict],
    *,
    allow_empty: bool = False,
) -> list[JsonDict]:
    modules = {
        m["slot"]: m
        for group in workbench.get("groups", [])
        for m in group.get("modules", [])
    }
    normalized: list[JsonDict] = []
    seen: set[str] = set()
    for raw in targets:
        slot = str(raw.get("slot") or "")
        if not slot or slot in seen:
            raise ValueError("Each genuine fitted slot may appear only once.")
        seen.add(slot)
        module = modules.get(slot)
        if module is None:
            raise ValueError(f"Module slot is not in the observed Loadout: {slot}")
        state = str(raw.get("target_state") or "engineered")
        if state not in {"stock", "engineered", "empty"}:
            raise ValueError("Unsupported target state")
        if state == "empty":
            if not module.get("reference_slot") or module["reference_slot"].get(
                "required"
            ):
                raise ValueError("A required core module cannot be removed.")
            normalized.append(
                {
                    "slot": slot,
                    "module_id": None,
                    "target_state": "empty",
                    "module_label": "Empty slot",
                }
            )
            continue
        requested = str(raw.get("module_id") or module["module_id"])
        replacement = requested.casefold() != str(module["module_id"]).casefold()
        choice = next(
            (
                row
                for row in module.get("module_options", [])
                if row["id"].casefold() == requested.casefold()
            ),
            None,
        )
        if replacement and choice is None:
            raise ValueError(
                f"{requested} is not a verified legal fit for {module['slot_label']}."
            )
        choice = choice or {
            "id": module["module_id"],
            "name": module["name"],
            "category": _FAMILY_CATEGORIES.get(module.get("family") or ""),
            "class": module.get("size"),
            "rating": module.get("rating"),
            "stats": {},
            "compatibility_evidence": "observed installed module",
        }
        target = {
            "slot": slot,
            "installed_module_id": module["module_id"],
            "module_id": choice["id"],
            "module_label": choice["name"],
            "module_class": choice.get("class"),
            "module_rating": choice.get("rating"),
            "module_category": choice.get("category"),
            "module_stats": dict(choice.get("stats", {})),
            "target_state": state,
            "blueprint_id": None,
            "target_grade": None,
            "experimental_effect": None,
            "engineering_effects": {},
            "compatibility_evidence": choice.get("compatibility_evidence"),
        }
        catalog = workbench.get("_catalog") or {}
        canonical = next(
            (
                m
                for m in catalog.get("modules", [])
                if m["id"].casefold() == str(choice["id"]).casefold()
            ),
            None,
        )
        if state == "stock":
            if (
                raw.get("blueprint_id")
                or raw.get("target_grade") is not None
                or raw.get("experimental_effect")
            ):
                raise ValueError("Stock targets cannot contain engineering selections.")
            if (
                not replacement
                and not module.get("attribute_changes")
                and canonical is None
            ):
                raise ValueError(
                    f"{module['name']} has no observed stock comparison data."
                )
            target["compatibility_evidence"] = (
                "active_reference_pack"
                if replacement
                else "observed_module_stock_values"
            )
        else:
            options = (
                _catalog_blueprint_options(catalog, choice.get("category"), canonical)
                if canonical
                else module.get("blueprint_options", [])
            )
            if not options:
                raise ValueError(
                    f"{module['name']} has no verified engineering choices."
                )
            blueprint = str(raw.get("blueprint_id") or "")
            option = next(
                (
                    row
                    for row in options
                    if row["id"].casefold() == blueprint.casefold()
                ),
                None,
            )
            if option is None:
                raise ValueError(
                    f"Blueprint {blueprint} is incompatible or "
                    f"unchecked for {module['name']}."
                )
            grade = raw.get("target_grade")
            if (
                isinstance(grade, bool)
                or not isinstance(grade, int)
                or grade not in option["grades"]
            ):
                raise ValueError(
                    f"Grade {grade} is not grounded for {option['label']}."
                )
            effect = str(raw.get("experimental_effect") or "").strip() or None
            experimental = (
                next(
                    (row for row in option["experimentals"] if row["id"] == effect),
                    None,
                )
                if effect
                else None
            )
            if effect and experimental is None:
                raise ValueError(
                    f"Experimental effect {effect} is not grounded for "
                    f"{option['label']}."
                )
            target.update(
                {
                    "blueprint_id": option["id"],
                    "blueprint_label": option["label"],
                    "target_grade": grade,
                    "experimental_effect": effect,
                    "engineering_effects": engineering_catalog.combined_effects(
                        option, grade, experimental
                    ),
                    "numerical_effects_verified": str(grade)
                    in option.get("grade_effects", {})
                    and (experimental is None or bool(experimental.get("effects"))),
                    "effect_rule": option.get(
                        "effect_rule", "additive_percent_of_unmodified_base"
                    ),
                    "compatibility_evidence": option["evidence"],
                }
            )
        if canonical:
            canonical_blueprint = next(
                (
                    b
                    for b in catalog.get("blueprints", [])
                    if b["id"] == target.get("blueprint_id")
                ),
                None,
            )
            experimental = next(
                (
                    e
                    for e in (canonical_blueprint or {}).get("experimentals", [])
                    if e["id"] == target.get("experimental_effect")
                ),
                None,
            )
            target.update(
                outfitting_rules.target_metadata(
                    canonical,
                    canonical_blueprint,
                    target.get("target_grade"),
                    experimental,
                    catalog.get("attribute_definitions", {}),
                )
            )
            if target["target_state"] == "engineered":
                target["numerical_effects_verified"] = (
                    str(target.get("target_grade"))
                    in (canonical_blueprint or {}).get("grade_effects", {})
                    and (canonical_blueprint or {}).get("numerical_data_complete", True)
                    and (
                        experimental is None
                        or bool(experimental.get("effects"))
                        or bool(experimental.get("attribute_effects"))
                        or bool(experimental.get("special"))
                    )
                )
        normalized.append(target)
    if not normalized and not allow_empty:
        raise ValueError("Choose at least one genuine engineerable module.")
    return normalized


def power_plant_variants(
    live_state: JsonDict, recipes: list[JsonDict], catalog: JsonDict | None
) -> JsonDict:
    """Rank A-rated alternatives with cargo fixed, then laden range, then heat."""
    workbench = build_observed_workbench(live_state, recipes, catalog)
    plant = next(
        (
            m
            for g in workbench["groups"]
            for m in g["modules"]
            if m["slot"] == "PowerPlant"
        ),
        None,
    )
    if not plant or not plant["module_options"]:
        return {
            "state": "unavailable",
            "variants": [],
            "reason": "Enable the local outfitting catalogue for "
            "compatible alternatives.",
        }
    variants = []
    for module in plant["module_options"]:
        if module["rating"] != "A":
            continue
        canonical = next(
            (m for m in (catalog or {}).get("modules", []) if m["id"] == module["id"]),
            None,
        )
        for blueprint in _catalog_blueprint_options(
            catalog, module["category"], canonical
        ):
            for grade in blueprint["grades"]:
                for effect in [None, *[e["id"] for e in blueprint["experimentals"]]]:
                    target = {
                        "slot": "PowerPlant",
                        "module_id": module["id"],
                        "target_state": "engineered",
                        "blueprint_id": blueprint["id"],
                        "target_grade": grade,
                        "experimental_effect": effect,
                    }
                    validated = validate_observed_targets(workbench, [target])
                    effect_label = next(
                        (
                            row["label"]
                            for row in blueprint["experimentals"]
                            if row["id"] == effect
                        ),
                        "No experimental",
                    )
                    performance = performance_comparison(live_state, validated, catalog)
                    metrics = {
                        m["id"]: m["planned"]["value"] for m in performance["metrics"]
                    }
                    variants.append(
                        {
                            "target": target,
                            "label": (
                                f"{module['name']} - "
                                f"{blueprint['label']} G{grade} - "
                                f"{effect_label}"
                            ),
                            "metrics": metrics,
                            "power_sufficient": performance["power_viability"][
                                "planned"
                            ],
                        }
                    )
    # Unknown power/range is never treated as a feasible ranking result.
    feasible = [
        v
        for v in variants
        if v["power_sufficient"]
        and v["metrics"].get("fully_laden_jump_range") is not None
    ]
    feasible.sort(
        key=lambda v: (
            -v["metrics"]["fully_laden_jump_range"],
            v["metrics"].get("heat_efficiency") or float("inf"),
        )
    )
    explicit = [
        v
        for v in variants
        if (
            v["target"]["blueprint_id"],
            v["target"]["target_grade"],
            v["target"]["experimental_effect"],
        )
        in {
            ("PowerPlant_Stealth", 2, "special_powerplant_highcharge"),
            ("PowerPlant_Armoured", 5, "special_powerplant_cooled"),
        }
    ]
    return {
        "state": "ranked" if feasible else "incomplete",
        "variants": feasible[:10],
        "explicit_candidates": explicit,
        "evaluated": len(variants),
        "feasible": len(feasible),
        "policy": "Unchanged observed cargo capacity; sufficient "
        "enabled deployed power; fully laden range "
        "descending; heat coefficient ascending only for "
        "equal range. Full observed main tank. Unknown "
        "inputs exclude a candidate from the ranking.",
    }
