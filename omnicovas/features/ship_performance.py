"""Deterministic ship-performance calculations over one canonical configuration.

The jump equation is the community-standard model documented independently by
EDSY and Elite Dangerous Almanac Core.  This is an independent Python
implementation of the mathematical relationship, not copied source code or a
bundled third-party catalogue.  Formula references:

* https://github.com/taleden/EDSY (edsy.js, GAME FORMULAS)
* https://github.com/Elite-Dangerous-Almanac/Almanac-Core/tree/main/typescript/src/ships

Reference numbers come from Commander-supplied or explicitly enabled local
packs, with their declared rights and provenance retained. A projected jump is emitted
only when the pack has every intrinsic drive constant and the calculated
installed baseline reproduces Frontier's Loadout.MaxJumpRange within the
declared tolerance.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from omnicovas.features import outfitting_rules, ship_power
from omnicovas.features.outfitting_reference import STATS

JsonDict = dict[str, Any]


def _power_control_lock(
    rules: JsonDict, record: JsonDict, catalog: JsonDict | None
) -> int | None:
    """Resolve electrical controls, including the pinned v3 converter omission.

    That converter dropped powerlock for *every* module. Interpret only this
    known source/version; arbitrary packs and unrecognised modules stay unknown.
    These exceptions are from the same digest-verified EDSY revision as v3/v4,
    not an upgrade of its fitting rules or a mutation of the retained catalogue.
    """
    if "power_lock" in rules:
        lock = rules["power_lock"]
        return lock if type(lock) is int and 0 <= lock <= 5 else None
    from omnicovas.features import engineering_reference

    provenance = (catalog or {}).get("provenance", {})
    if not (
        record
        and (catalog or {}).get("catalog_id") == engineering_reference.CATALOG_ID
        and (catalog or {}).get("version") == "2026-10-20-ea787cf8-v3"
        and provenance.get("source_url") == engineering_reference.SOURCE_URL
        and engineering_reference.SOURCE_SHA256
        in provenance.get("verification_notes", "")
    ):
        return None
    identifier = record.get("id", "").casefold()
    if not identifier:
        return None
    # Pinned source: Guardian reinforcement packages and weapon stabilisers
    # have fixed P1. All other modules in this legacy source are adjustable.
    fixed = {
        f"int_guardian{kind}reinforcement_size{size}_class{rating}"
        for kind in ("hull", "shield", "module")
        for size in range(1, 6)
        for rating in (1, 2)
    } | {f"int_expmodulestabiliser_size{size}_class3" for size in (3, 5)}
    return 1 if identifier in fixed else 0


PERFORMANCE_VERSION = "ship-performance-v4"
JUMP_FORMULA_ID = "community-fsd-power-law-v1"
JUMP_ABSOLUTE_TOLERANCE_LY = 0.0001
JUMP_RELATIVE_TOLERANCE = 0.000002
JUMP_RESEARCH_SOURCES = (
    {
        "name": "Frontier Player Journal Loadout semantics",
        "url": "https://hosting.zaonce.net/community/journal/v26/Journal-Manual-v26.pdf",
    },
    {
        "name": "EDSY game formulas reference e85bb52c",
        "url": "https://github.com/taleden/EDSY",
    },
    {
        "name": "Elite Dangerous Almanac Core jump model 5da3bfca",
        "url": (
            "https://github.com/Elite-Dangerous-Almanac/Almanac-Core/"
            "blob/5da3bfca20aba4bb39332628e220ea2acb5dbcd9/typescript/"
            "src/ships/jump-range.ts"
        ),
    },
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def single_jump_range(
    *,
    mass_excluding_fuel: float,
    fuel_on_board: float,
    optimal_mass: float,
    max_fuel_per_jump: float,
    fuel_multiplier: float,
    fuel_power: float,
    jump_boost: float = 0.0,
) -> float:
    """Return one hyperspace jump in light-years.

    ``mass_excluding_fuel`` includes hull, modules, and cargo.  The full
    ``fuel_on_board`` contributes to moved mass while the burn is capped at the
    drive's per-jump limit.  A Guardian booster is a flat range addition.
    """
    values = {
        "mass_excluding_fuel": mass_excluding_fuel,
        "fuel_on_board": fuel_on_board,
        "optimal_mass": optimal_mass,
        "max_fuel_per_jump": max_fuel_per_jump,
        "fuel_multiplier": fuel_multiplier,
        "fuel_power": fuel_power,
        "jump_boost": jump_boost,
    }
    if any(not math.isfinite(value) or value < 0 for value in values.values()):
        raise ValueError("Jump-range inputs must be finite and non-negative.")
    if optimal_mass <= 0 or fuel_multiplier <= 0 or fuel_power <= 0:
        raise ValueError(
            "FSD optimal mass, fuel multiplier, and fuel power must be positive."
        )
    burn = min(fuel_on_board, max_fuel_per_jump)
    loaded_mass = mass_excluding_fuel + fuel_on_board
    if burn <= 0 or loaded_mass <= 0:
        return 0.0
    result = float(
        (burn / fuel_multiplier) ** (1.0 / fuel_power) * optimal_mass / loaded_mass
        + jump_boost
    )
    if not math.isfinite(result):
        raise ValueError("Jump-range inputs produced a non-finite result.")
    return result


def modifier_rows(engineering: JsonDict) -> list[JsonDict]:
    raw_rows = engineering.get("Modifiers", engineering.get("Modifications"))
    if not isinstance(raw_rows, list):
        return []
    labels = {
        "mass": ("Mass", "t"),
        "powerdraw": ("Power draw", "MW"),
        "integrity": ("Integrity", None),
        "optmass": ("Optimal mass", "t"),
        "fsdoptimalmass": ("FSD optimal mass", "t"),
        "maxfuelperjump": ("Maximum fuel per jump", "t"),
        "engineminimummass": ("Minimum mass", "t"),
        "engineoptimalmass": ("Optimal mass", "t"),
        "enginemaximummass": ("Maximum mass", "t"),
        "engineoptperformance": ("Optimal multiplier", "%"),
        "powercapacity": ("Power capacity", "MW"),
        "boottime": ("Boot time", "s"),
    }
    rows: list[JsonDict] = []
    for raw in raw_rows:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("Label") or "").strip()
        original = _number(raw.get("OriginalValue"))
        modified = _number(raw.get("Value"))
        if not label or original is None or modified is None:
            continue
        friendly, unit = labels.get(label.casefold(), (label, None))
        rows.append(
            {
                "id": label,
                "label": friendly,
                "original": original,
                "modified": modified,
                "delta": modified - original,
                "unit": unit,
                "less_is_good": raw.get("LessIsGood") is True,
                "source": "Journal Loadout Engineering.Modifiers",
            }
        )
    return rows


def _engineering(raw: JsonDict) -> JsonDict:
    value = raw.get("engineering")
    return value if isinstance(value, dict) else {}


def _modifier_value(raw: JsonDict, label: str, *, stock: bool) -> float | None:
    engineering = _engineering(raw)
    for row in engineering.get("Modifiers", engineering.get("Modifications", [])) or []:
        if (
            isinstance(row, dict)
            and str(row.get("Label") or "").casefold() == label.casefold()
        ):
            return _number(row.get("OriginalValue" if stock else "Value"))
    return None


def _modifier_delta(raw: JsonDict, label: str, *, stock: bool) -> float:
    if not stock:
        return 0.0
    for row in modifier_rows(_engineering(raw)):
        if str(row["id"]).casefold() == label.casefold():
            return float(row["original"]) - float(row["modified"])
    return 0.0


def _target_matches_installed(raw: JsonDict, target: JsonDict) -> bool:
    "Return whether an engineered target describes the observed state exactly."
    engineering = _engineering(raw)
    installed_blueprint = str(engineering.get("BlueprintName") or "").casefold()
    target_blueprint = str(target.get("blueprint_id") or "").casefold()
    installed_grade = engineering.get("Level")
    target_grade = target.get("target_grade")
    installed_effect = str(engineering.get("ExperimentalEffect") or "").casefold()
    target_effect = str(target.get("experimental_effect") or "").casefold()
    return (
        str(raw.get("item") or "").casefold()
        == str(target.get("module_id") or raw.get("item") or "").casefold()
        and target.get("target_state") != "stock"
        and (
            not target.get("numerical_effects_verified")
            or _number(engineering.get("Quality")) == 1.0
        )
        and bool(installed_blueprint)
        and installed_blueprint == target_blueprint
        and installed_grade == target_grade
        and installed_effect == target_effect
    )


def _target_stat(target: JsonDict, stat: str) -> float | None:
    if target.get("target_state") == "empty":
        return 0.0
    if target.get("module_attributes"):
        attributes = outfitting_rules.attribute_values(target)
        source_field = next(
            (key for key, value in STATS.items() if value == stat), None
        )
        if source_field:
            value = _number(attributes.get(source_field))
            if value is not None:
                return value
            if stat == "power_draw" and target.get("numerical_effects_verified", True):
                return _number(target.get("module_stats", {}).get(stat))
    stats = target.get("module_stats")
    if not isinstance(stats, dict):
        return None
    base = _number(stats.get(stat))
    if base is None:
        return None
    effects = target.get("engineering_effects")
    if target.get("target_state") == "engineered":
        if target.get("numerical_effects_verified") is not True:
            return None
        if target.get("effect_rule") not in {
            "additive_percent_of_unmodified_base",
            "multiplicative_blueprint_experimental",
        }:
            return None
        if isinstance(effects, dict):
            percent = _number(effects.get(f"{stat}_percent")) or 0.0
            return base * (1.0 + percent / 100.0)
    return base


def _installed_stat(
    raw: JsonDict, record: JsonDict, stat: str, modifier_label: str | None = None
) -> float | None:
    if modifier_label:
        modified = _modifier_value(raw, modifier_label, stock=False)
        if modified is not None:
            return modified
        engineering = _engineering(raw)
        if engineering and not isinstance(
            engineering.get("Modifiers", engineering.get("Modifications")), list
        ):
            return None
    stats = record.get("stats")
    return _number(stats.get(stat)) if isinstance(stats, dict) else None


def _is_deployable_hardpoint(slot: str) -> bool:
    value = slot.casefold()
    return value.startswith(
        ("smallhardpoint", "mediumhardpoint", "largehardpoint", "hugehardpoint")
    )


def _deployment_policy(slot: str, record: JsonDict) -> str | None:
    if _is_deployable_hardpoint(slot):
        return "deployed_only"
    if slot.casefold().startswith("tinyhardpoint"):
        policy = record.get("rules", {}).get("retracted_power")
        return str(policy) if policy in {"same", "deployed_only"} else None
    return "same"


def _power_boost(
    modules: dict[str, JsonDict],
    reference: dict[str, JsonDict],
    targets: dict[str, JsonDict],
) -> float | None:
    target = targets.get("PowerDistributor")
    raw = modules.get("PowerDistributor", {})
    identifier = str(
        (target or {}).get("module_id") or raw.get("item") or ""
    ).casefold()
    if target and target.get("module_attributes"):
        if target.get("target_state") == "engineered" and not target.get(
            "numerical_effects_verified"
        ):
            return None
        return float(outfitting_rules.attribute_values(target).get("pwrbst", 0))
    attrs = reference.get(identifier, {}).get("attributes", {})
    if "pwrbst" in attrs:
        return float(attrs["pwrbst"])
    if identifier.startswith("int_guardianpowerdistributor_"):
        return None
    return 0.0


def _power_rows(
    modules: JsonDict,
    reference: JsonDict,
    targets: JsonDict,
    catalog: JsonDict | None,
    hull: JsonDict | None = None,
) -> list[JsonDict]:
    "One source-resolved view of canonical slots, not a second configuration."
    rows = []
    hull_slots = {s["id"]: s for s in (hull or {}).get("slots", [])}
    cosmetic = (
        "paintjob",
        "decal",
        "shipname",
        "shipkit",
        "bobble",
        "stringlights",
        "vesselvoice",
        "shipcockpit",
        "weaponcolour",
        "enginecolour",
        "enginecustomisation",
        "planetaryapproachsuite",
    )
    for slot, raw in modules.items():
        if slot.casefold().startswith(cosmetic):
            continue
        target: JsonDict = targets.get(slot) or {}
        identifier = str((target or {}).get("module_id") or raw.get("item") or "")
        empty = (target or {}).get("target_state") == "empty" or not identifier
        if not identifier and not target:
            continue
        record = reference.get(identifier.casefold(), {})
        if slot.casefold() == "cargohatch" and identifier.casefold().startswith(
            "modularcargobaydoor"
        ):
            record = reference.get("modularcargobaydoor", record)
        unchanged = not target or _target_matches_installed(raw, target)
        draw: float | None
        if empty:
            draw, basis = 0.0, "empty slot"
        elif unchanged:
            observed = _number(raw.get("power"))
            modifier = _modifier_value(raw, "PowerDraw", stock=False)
            draw = (
                observed
                if observed is not None
                else _installed_stat(raw, record, "power_draw", "PowerDraw")
            )
            basis = (
                "observed module Power"
                if observed is not None
                else "observed PowerDraw modifier"
                if modifier is not None
                else "pinned reference (unmodified attribute)"
                if draw is not None
                else "unavailable"
            )
        else:
            draw = _target_stat(target, "power_draw")
            basis = (
                "calculated verified engineering"
                if target.get("target_state") == "engineered"
                else "pinned replacement/stock reference"
            )
        if draw is not None and draw < 0:
            draw, basis = None, "unavailable: negative power observation"
        rules = (
            target.get("module_rules", {})
            if target and not unchanged
            else record.get("rules", {})
        )
        verified_lock = _power_control_lock(rules, record, catalog)
        lock = verified_lock or 0
        priority = raw.get("priority")
        priority = (
            priority + 1
            if isinstance(priority, int)
            and not isinstance(priority, bool)
            and 0 <= priority <= 4
            else None
        )
        enabled = raw.get("on") if isinstance(raw.get("on"), bool) else None
        new_fit = bool(target and not raw.get("item") and not empty)
        if new_fit:
            priority, enabled = 1, True
        if lock:
            priority, enabled = lock, True
        rows.append(
            {
                "slot": slot,
                "module_id": None if empty else identifier,
                "name": (target or {}).get("module_label")
                or record.get("name")
                or raw.get("item_localised")
                or identifier,
                "reference_version": (
                    f"{(catalog or {}).get('catalog_id', 'unavailable')}@"
                    f"{(catalog or {}).get('version', 'unavailable')}"
                ),
                "draw_mw": draw,
                "draw_basis": basis,
                "deployment_policy": _deployment_policy(slot, {"rules": rules}),
                "deployment_basis": "pinned family rule"
                if record
                else "Journal hardpoint slot"
                if _is_deployable_hardpoint(slot)
                else "unavailable"
                if slot.startswith("TinyHardpoint")
                else "internal slot",
                "enabled": enabled,
                "priority": priority,
                "priority_basis": "reference default for new fit"
                if new_fit
                else "reference power lock"
                if lock
                else "Journal 0–4 translated to 1–5",
                "power_lock": lock,
                "controls_verified": verified_lock is not None,
                "new_fit": new_fit,
                "empty": empty,
                "engineering": {
                    "blueprint": target.get("blueprint_id")
                    if target
                    else _engineering(raw).get("BlueprintName"),
                    "grade": target.get("target_grade")
                    if target
                    else _engineering(raw).get("Level"),
                    "experimental": target.get("experimental_effect")
                    if target
                    else _engineering(raw).get("ExperimentalEffect"),
                },
                "slot_type": hull_slots.get(slot, {}).get("slot_type"),
            }
        )
    return sorted(rows, key=lambda row: row["slot"])


def _reference_modules(catalog: JsonDict | None) -> dict[str, JsonDict]:
    if not isinstance(catalog, dict):
        return {}
    return {
        str(row.get("id") or "").casefold(): row
        for row in catalog.get("modules", [])
        if isinstance(row, dict) and row.get("id")
    }


def _metric(
    value: float | None,
    unit: str,
    basis: str,
    unavailable: str | None = None,
    calculation: JsonDict | None = None,
) -> JsonDict:
    return {
        "value": value,
        "unit": unit,
        "basis": basis,
        "unavailable_reason": unavailable,
        "calculation": calculation,
    }


def _drive_inputs(
    modules: dict[str, JsonDict],
    reference: dict[str, JsonDict],
    targets: dict[str, JsonDict],
) -> tuple[JsonDict | None, list[str]]:
    fsd_slot = "FrameShiftDrive"
    raw = modules.get(fsd_slot)
    if not isinstance(raw, dict):
        return None, ["fitted Frame Shift Drive"]
    target = targets.get(fsd_slot, {})
    target_module_id = str(target.get("module_id") or "")
    replacement = (
        bool(target_module_id)
        and target_module_id.casefold() != str(raw.get("item") or "").casefold()
    )
    record = (
        {"stats": target.get("module_stats", {})}
        if replacement
        else reference.get(str(raw.get("item") or "").casefold(), {})
    )
    stats_value = record.get("stats")
    stats: JsonDict = stats_value if isinstance(stats_value, dict) else {}
    stock = target.get("target_state") == "stock"
    optimal_mass = _target_stat(target, "fsd_optimal_mass") if target else None
    if optimal_mass is None and not replacement:
        optimal_mass = _modifier_value(raw, "FSDOptimalMass", stock=stock)
    if optimal_mass is None:
        optimal_mass = _number(stats.get("fsd_optimal_mass"))
    max_fuel = _target_stat(target, "fsd_max_fuel") if target else None
    if max_fuel is None and not replacement:
        max_fuel = _modifier_value(raw, "MaxFuelPerJump", stock=stock)
    if max_fuel is None:
        max_fuel = _number(stats.get("fsd_max_fuel"))
    values = {
        "optimal_mass": optimal_mass,
        "max_fuel_per_jump": max_fuel,
        "fuel_multiplier": _number(stats.get("fsd_fuel_multiplier")),
        "fuel_power": _number(stats.get("fsd_fuel_power")),
    }
    missing = [
        name.replace("_", " ") for name, value in values.items() if value is None
    ]
    if missing:
        return None, missing
    jump_boost = 0.0
    for slot, module in modules.items():
        if not isinstance(module, dict):
            continue
        boost_target = targets.get(slot)
        if boost_target and boost_target.get("target_state") == "empty":
            continue
        if boost_target:
            jump_boost += _target_stat(boost_target, "jump_boost") or 0.0
        else:
            module_record = reference.get(str(module.get("item") or "").casefold(), {})
            jump_boost += (
                _number(module_record.get("stats", {}).get("jump_boost")) or 0.0
            )
    return {**values, "jump_boost": jump_boost}, []


def performance_comparison(
    live_state: JsonDict,
    targets: Iterable[JsonDict],
    reference_catalog: JsonDict | None = None,
    power_plan: JsonDict | None = None,
    operating_conditions: JsonDict | None = None,
) -> JsonDict:
    "Compare installed and planned configurations without inventing inputs."
    modules_value = live_state.get("modules")
    modules: dict[str, JsonDict] = (
        {str(slot): raw for slot, raw in modules_value.items() if isinstance(raw, dict)}
        if isinstance(modules_value, dict)
        else {}
    )
    targets_by_slot = {
        str(row.get("slot") or ""): row
        for row in targets
        if isinstance(row, dict) and row.get("slot")
    }
    mass = _number(live_state.get("unladen_mass"))
    cargo_raw = live_state.get("cargo_capacity")
    cargo = _number(cargo_raw)
    jump = _number(live_state.get("jump_range_ly"))
    reference = _reference_modules(reference_catalog)
    hull = next(
        (
            h
            for h in (reference_catalog or {}).get("hulls", [])
            if h["id"].casefold()
            == str(live_state.get("current_ship_type") or "").casefold()
        ),
        None,
    )
    if hull:
        for slot in hull["slots"]:
            modules.setdefault(slot["id"], {"item": "", "on": True, "power": 0.0})
    mass_delta = 0.0
    module_changes: list[JsonDict] = []
    unmodelled_engineering_slots: list[str] = []
    cargo_delta = 0.0
    fuel_delta = 0.0
    cargo_known = True
    fuel_known = True
    for slot, target in targets_by_slot.items():
        raw = modules.get(slot)
        if not isinstance(raw, dict):
            continue
        replacement = (
            bool(target.get("module_id"))
            and str(target.get("module_id") or "").casefold()
            != str(raw.get("item") or "").casefold()
        )
        exact_installed = _target_matches_installed(raw, target) and not replacement
        if target.get("target_state") == "engineered" and not exact_installed:
            if target.get("numerical_effects_verified") is not True:
                if (
                    "cargo_capacity" in target.get("module_stats", {})
                    or "cargorack" in str(raw.get("item", "")).casefold()
                ):
                    cargo_known = False
                if "fuel_capacity" in target.get("module_stats", {}):
                    fuel_known = False
                unmodelled_engineering_slots.append(slot)
                module_changes.append(
                    {
                        "slot": slot,
                        "target_state": "engineered",
                        "basis": (
                            "validated planned engineering effect values unavailable"
                        ),
                    }
                )
                continue
        if exact_installed:
            module_changes.append(
                {
                    "slot": slot,
                    "target_state": "engineered",
                    "mass_delta": 0.0,
                    "power_draw_delta": 0.0,
                    "basis": "same observed engineering",
                }
            )
            continue
        installed_record = reference.get(str(raw.get("item") or "").casefold(), {})
        installed_mass = _installed_stat(raw, installed_record, "mass", "Mass")
        if not raw.get("item"):
            installed_mass = 0.0
        installed_draw = _number(raw.get("power"))
        if installed_draw is None:
            installed_draw = _installed_stat(
                raw, installed_record, "power_draw", "PowerDraw"
            )
        target_mass = _target_stat(target, "mass")
        target_draw = _target_stat(target, "power_draw")
        for stat, label in [
            ("cargo_capacity", "CargoCapacity"),
            ("fuel_capacity", "FuelCapacity"),
        ]:
            old = _modifier_value(raw, label, stock=False)
            if old is None:
                old = _number(installed_record.get("stats", {}).get(stat))
            new = _target_stat(target, stat)
            role = "cargorack" if stat == "cargo_capacity" else "fueltank"
            old_capacity_missing = (
                old is None and role in str(raw.get("item") or "").casefold()
            )
            new_capacity_missing = (
                new is None
                and target.get("target_state") != "empty"
                and role in str(target.get("module_id") or "").casefold()
            )
            if old_capacity_missing or new_capacity_missing:
                if stat == "cargo_capacity":
                    cargo_known = False
                else:
                    fuel_known = False
            affected = old is not None or new is not None
            if affected:
                if new is None and stat in target.get("module_stats", {}):
                    if stat == "cargo_capacity":
                        cargo_known = False
                    else:
                        fuel_known = False
                    continue
                # A module outside the capacity-bearing families contributes zero.
                old = old or 0.0
                new = new or 0.0
                if stat == "cargo_capacity":
                    cargo_delta += new - old
                else:
                    fuel_delta += new - old
        if target.get("target_state") == "stock" and not replacement:
            mass_change = _modifier_delta(raw, "Mass", stock=True)
            power_change = _modifier_delta(raw, "PowerDraw", stock=True)
        else:
            mass_change = (
                target_mass - installed_mass
                if target_mass is not None and installed_mass is not None
                else 0.0
            )
            power_change = (
                target_draw - installed_draw
                if target_draw is not None and installed_draw is not None
                else 0.0
            )
            if target_mass is None or installed_mass is None:
                unmodelled_engineering_slots.append(slot)
        mass_delta += mass_change
        module_changes.append(
            {
                "slot": slot,
                "target_state": target.get("target_state"),
                "installed_module_id": raw.get("item"),
                "planned_module_id": target.get("module_id"),
                "mass_delta": mass_change,
                "power_draw_delta": power_change,
                "basis": (
                    "validated base module stats and additive engineering effects"
                    if replacement or target.get("target_state") == "engineered"
                    else "Journal Loadout Engineering.Modifiers "
                    "OriginalValue versus Value"
                ),
            }
        )
    planned_mass = (
        mass + mass_delta
        if mass is not None and not unmodelled_engineering_slots
        else None
    )
    power_plant = modules.get("PowerPlant")
    plant_record = (
        reference.get(str(power_plant.get("item") or "").casefold(), {})
        if isinstance(power_plant, dict)
        else {}
    )
    installed_capacity = (
        _installed_stat(power_plant, plant_record, "power_capacity", "PowerCapacity")
        if isinstance(power_plant, dict)
        else None
    )
    installed_heat = (
        _installed_stat(power_plant, plant_record, "heat_efficiency", "HeatEfficiency")
        if isinstance(power_plant, dict)
        else None
    )
    installed_integrity = (
        _installed_stat(power_plant, plant_record, "integrity", "Integrity")
        if isinstance(power_plant, dict)
        else None
    )
    plant_target = targets_by_slot.get("PowerPlant")
    if (
        plant_target
        and isinstance(power_plant, dict)
        and not _target_matches_installed(power_plant, plant_target)
    ):
        planned_capacity = _target_stat(plant_target, "power_capacity")
        planned_heat = _target_stat(plant_target, "heat_efficiency")
        planned_integrity = _target_stat(plant_target, "integrity")
    else:
        planned_capacity = installed_capacity
        planned_heat = installed_heat
        planned_integrity = installed_integrity
    installed_boost = _power_boost(modules, reference, {})
    planned_boost = _power_boost(modules, reference, targets_by_slot)
    installed_supply = (
        installed_capacity * (1 + installed_boost / 100)
        if installed_capacity is not None and installed_boost is not None
        else None
    )
    planned_supply = (
        planned_capacity * (1 + planned_boost / 100)
        if planned_capacity is not None and planned_boost is not None
        else None
    )
    power = ship_power.compare(
        _power_rows(modules, reference, {}, reference_catalog, hull),
        _power_rows(modules, reference, targets_by_slot, reference_catalog, hull),
        installed_supply,
        planned_supply,
        power_plan,
    )
    normal = {c["id"]: c for c in power["cases"]}
    missing_power_slots = normal["normal:deployed"]["planned"]["missing"]
    unmodelled_retracted_slots = normal["normal:retracted"]["planned"]["missing"]
    deployed_power = normal["normal:deployed"]["installed"]["requested_mw"]
    planned_deployed_power = normal["normal:deployed"]["planned"]["requested_mw"]
    retracted_power = normal["normal:retracted"]["installed"]["requested_mw"]
    planned_retracted_power = normal["normal:retracted"]["planned"]["requested_mw"]
    configuration_changed = bool(targets_by_slot)
    planned_cargo = cargo + cargo_delta if cargo is not None and cargo_known else None
    installed_fuel_capacity = _number(live_state.get("fuel_capacity_main"))
    planned_fuel_capacity = (
        installed_fuel_capacity + fuel_delta
        if installed_fuel_capacity is not None and fuel_known
        else None
    )

    planned_jump = jump
    jump_basis = "same observed configuration"
    jump_unavailable = None
    jump_calculation = None
    validation = None
    if configuration_changed or jump is not None:
        drive, missing = _drive_inputs(modules, reference, targets_by_slot)
        installed_drive, installed_missing = _drive_inputs(modules, reference, {})
        missing.extend(installed_missing)
        if unmodelled_engineering_slots:
            missing.append("validated planned engineering effect values")
        fuel_capacity = _number(live_state.get("fuel_capacity_main"))
        if fuel_capacity is None:
            missing.append("main fuel capacity")
        if planned_fuel_capacity is None:
            missing.append("planned fuel capacity")
        if planned_mass is None:
            missing.append("unladen mass")
        if jump is None:
            missing.append("observed MaxJumpRange baseline")
        if missing:
            planned_jump = None
            jump_basis = "unavailable"
            jump_unavailable = "Missing " + ", ".join(dict.fromkeys(missing)) + "."
        else:
            assert drive is not None
            assert fuel_capacity is not None
            assert mass is not None
            assert planned_mass is not None
            assert jump is not None
            baseline_fuel = min(
                planned_fuel_capacity
                if planned_fuel_capacity is not None
                else fuel_capacity,
                float(drive["max_fuel_per_jump"]),
            )
            baseline_targets: dict[str, JsonDict] = {}
            installed_drive, _ = _drive_inputs(modules, reference, baseline_targets)
            assert installed_drive is not None
            installed_fuel = min(
                fuel_capacity, float(installed_drive["max_fuel_per_jump"])
            )
            calculated_installed = single_jump_range(
                mass_excluding_fuel=mass,
                fuel_on_board=installed_fuel,
                optimal_mass=float(installed_drive["optimal_mass"]),
                max_fuel_per_jump=float(installed_drive["max_fuel_per_jump"]),
                fuel_multiplier=float(installed_drive["fuel_multiplier"]),
                fuel_power=float(installed_drive["fuel_power"]),
                jump_boost=float(installed_drive["jump_boost"]),
            )
            tolerance = max(
                JUMP_ABSOLUTE_TOLERANCE_LY,
                abs(jump) * JUMP_RELATIVE_TOLERANCE,
            )
            discrepancy = abs(calculated_installed - jump)
            validation = {
                "state": "validated" if discrepancy <= tolerance else "mismatch",
                "observed": jump,
                "calculated": calculated_installed,
                "absolute_error": discrepancy,
                "tolerance": tolerance,
                "reference": "Frontier Loadout.MaxJumpRange",
            }
            if discrepancy > tolerance:
                planned_jump = None
                jump_basis = "unavailable"
                jump_unavailable = (
                    "The supplied FSD reference inputs do not reproduce the "
                    "observed MaxJumpRange within tolerance."
                )
            else:
                planned_jump = single_jump_range(
                    mass_excluding_fuel=planned_mass,
                    fuel_on_board=baseline_fuel,
                    optimal_mass=float(drive["optimal_mass"]),
                    max_fuel_per_jump=float(drive["max_fuel_per_jump"]),
                    fuel_multiplier=float(drive["fuel_multiplier"]),
                    fuel_power=float(drive["fuel_power"]),
                    jump_boost=float(drive["jump_boost"]),
                )
                jump_basis = "validated calculated projection"
                jump_calculation = {
                    "formula_id": JUMP_FORMULA_ID,
                    "inputs": {
                        "mass_excluding_fuel": planned_mass,
                        "fuel_on_board": baseline_fuel,
                        **drive,
                    },
                    "reference_pack": (
                        f"{reference_catalog.get('catalog_id')}@"
                        f"{reference_catalog.get('version')}"
                        if reference_catalog is not None
                        else None
                    ),
                }

    fully_laden_installed = None
    fully_laden_planned = None
    fully_laden_unavailable = None
    fully_laden_calculation = None
    fuel_capacity = _number(live_state.get("fuel_capacity_main"))
    drive, laden_missing = _drive_inputs(modules, reference, targets_by_slot)
    installed_drive, installed_missing = _drive_inputs(modules, reference, {})
    if cargo is None:
        laden_missing.append("cargo capacity")
    if fuel_capacity is None:
        laden_missing.append("main fuel capacity")
    if planned_cargo is None:
        laden_missing.append("planned cargo capacity")
    if planned_fuel_capacity is None:
        laden_missing.append("planned fuel capacity")
    if mass is None or planned_mass is None:
        laden_missing.append("unladen mass")
    if installed_missing:
        laden_missing.extend(installed_missing)
    if validation is None or validation.get("state") != "validated":
        laden_missing.append("validated observed MaxJumpRange proof gate")
    if laden_missing:
        fully_laden_unavailable = (
            "Missing " + ", ".join(dict.fromkeys(laden_missing)) + "."
        )
    else:
        assert cargo is not None and fuel_capacity is not None
        assert mass is not None and planned_mass is not None
        assert drive is not None and installed_drive is not None
        fully_laden_installed = single_jump_range(
            mass_excluding_fuel=mass + cargo,
            fuel_on_board=fuel_capacity,
            optimal_mass=float(installed_drive["optimal_mass"]),
            max_fuel_per_jump=float(installed_drive["max_fuel_per_jump"]),
            fuel_multiplier=float(installed_drive["fuel_multiplier"]),
            fuel_power=float(installed_drive["fuel_power"]),
            jump_boost=float(installed_drive["jump_boost"]),
        )
        fully_laden_planned = single_jump_range(
            mass_excluding_fuel=planned_mass
            + (planned_cargo if planned_cargo is not None else cargo),
            fuel_on_board=planned_fuel_capacity
            if planned_fuel_capacity is not None
            else fuel_capacity,
            optimal_mass=float(drive["optimal_mass"]),
            max_fuel_per_jump=float(drive["max_fuel_per_jump"]),
            fuel_multiplier=float(drive["fuel_multiplier"]),
            fuel_power=float(drive["fuel_power"]),
            jump_boost=float(drive["jump_boost"]),
        )
        fully_laden_calculation = {
            "formula_id": JUMP_FORMULA_ID,
            "fuel_policy": "full installed/planned main tanks respectively",
            "reserve_fuel_policy": "0 t comparison assumption; reservoir excluded",
            "cargo_mass": cargo,
            "fuel_on_board": fuel_capacity,
            "planned_cargo_mass": planned_cargo,
            "planned_fuel_on_board": planned_fuel_capacity,
            "planned_mass_excluding_fuel": planned_mass + (planned_cargo or 0),
        }

    metrics: list[JsonDict] = [
        {
            "id": "module_mass",
            "label": "Power plant mass",
            "installed": _metric(
                _installed_stat(power_plant, plant_record, "mass", "Mass")
                if isinstance(power_plant, dict)
                else None,
                "t",
                "Journal modifier or reference base mass",
            ),
            "planned": _metric(
                _target_stat(plant_target, "mass")
                if plant_target
                and not _target_matches_installed(power_plant or {}, plant_target)
                else _installed_stat(power_plant, plant_record, "mass", "Mass")
                if isinstance(power_plant, dict)
                else None,
                "t",
                "reference base and verified engineering endpoint",
            ),
        },
        {
            "id": "unladen_mass",
            "label": "Unladen mass",
            "installed": _metric(
                mass,
                "t",
                "direct Journal Loadout.UnladenMass",
                "Loadout.UnladenMass was not observed" if mass is None else None,
            ),
            "planned": _metric(
                planned_mass,
                "t",
                "calculated from observed Engineering.Modifiers"
                if module_changes
                else "same observed configuration",
                (
                    "Validated planned engineering mass effects are unavailable"
                    if unmodelled_engineering_slots
                    else "Installed mass is unavailable"
                    if planned_mass is None
                    else None
                ),
            ),
        },
        {
            "id": "cargo_capacity",
            "label": "Cargo capacity",
            "installed": _metric(
                cargo,
                "t",
                "direct Journal Loadout.CargoCapacity",
                "Loadout.CargoCapacity was not observed" if cargo is None else None,
            ),
            "planned": _metric(
                planned_cargo,
                "t",
                "observed capacity plus validated planned module capacity deltas",
                "Installed cargo capacity is unavailable"
                if cargo is None
                else "Planned module capacity inputs are unavailable"
                if not cargo_known
                else None,
            ),
        },
        {
            "id": "power_draw",
            "label": "Active module power draw",
            "installed": _metric(
                deployed_power,
                "MW",
                "complete enabled-module sum: Journal "
                "Power/PowerDraw, else pinned module reference",
                "At least one enabled physical module lacks a "
                "power observation or reference"
                if deployed_power is None
                else None,
            ),
            "planned": _metric(
                planned_deployed_power,
                "MW",
                "calculated from observed Engineering.Modifiers"
                if module_changes
                else "same observed configuration",
                (
                    "Validated planned engineering power effects are unavailable"
                    if unmodelled_engineering_slots
                    else "Module power draw is unavailable"
                    if planned_deployed_power is None
                    else None
                ),
            ),
        },
        {
            "id": "retracted_power_draw",
            "label": "Retracted power load",
            "installed": _metric(
                retracted_power, "MW", "active modules excluding deployable hardpoints"
            ),
            "planned": _metric(
                planned_retracted_power,
                "MW",
                "planned active modules excluding deployable hardpoints",
            ),
        },
        {
            "id": "power_capacity",
            "label": "Power plant output",
            "installed": _metric(
                installed_capacity,
                "MW",
                "Journal modifier or validated module reference",
            ),
            "planned": _metric(
                planned_capacity,
                "MW",
                "validated base stat plus declared engineering effects",
            ),
        },
        {
            "id": "operating_power_capacity",
            "label": "Available power including distributor boost",
            "installed": _metric(
                installed_supply, "MW", "plant output × sourced distributor boost"
            ),
            "planned": _metric(
                planned_supply, "MW", "planned plant output × sourced distributor boost"
            ),
        },
        {
            "id": "deployed_power_headroom",
            "label": "Deployed power headroom",
            "installed": _metric(
                installed_supply - deployed_power
                if installed_supply is not None and deployed_power is not None
                else None,
                "MW",
                "power capacity minus deployed load",
            ),
            "planned": _metric(
                planned_supply - planned_deployed_power
                if planned_supply is not None and planned_deployed_power is not None
                else None,
                "MW",
                "power capacity minus planned deployed load",
            ),
        },
        {
            "id": "retracted_power_headroom",
            "label": "Retracted power headroom",
            "installed": _metric(
                installed_supply - retracted_power
                if installed_supply is not None and retracted_power is not None
                else None,
                "MW",
                "power capacity minus retracted load",
            ),
            "planned": _metric(
                planned_supply - planned_retracted_power
                if planned_supply is not None and planned_retracted_power is not None
                else None,
                "MW",
                "power capacity minus planned retracted load",
            ),
        },
        {
            "id": "heat_efficiency",
            "label": "Heat efficiency coefficient",
            "installed": _metric(
                installed_heat,
                "coefficient",
                "Journal modifier or validated module reference",
            ),
            "planned": _metric(
                planned_heat,
                "coefficient",
                "validated base stat plus declared engineering effects",
            ),
        },
        {
            "id": "power_plant_integrity",
            "label": "Power plant integrity",
            "installed": _metric(
                installed_integrity,
                "integrity",
                "Journal modifier or validated module reference",
            ),
            "planned": _metric(
                planned_integrity,
                "integrity",
                "validated base stat plus declared engineering effects",
            ),
        },
        {
            "id": "max_jump_range",
            "label": "Maximum jump range  -  zero cargo",
            "installed": _metric(
                jump,
                "ly",
                "direct Journal Loadout.MaxJumpRange",
                "Loadout.MaxJumpRange was not observed" if jump is None else None,
            ),
            "planned": _metric(
                planned_jump,
                "ly",
                jump_basis,
                jump_unavailable,
                jump_calculation,
            ),
        },
        {
            "id": "fully_laden_jump_range",
            "label": "Fully laden jump range",
            "installed": _metric(
                fully_laden_installed,
                "ly",
                "validated calculation with full cargo and full observed main tank",
                fully_laden_unavailable,
                fully_laden_calculation,
            ),
            "planned": _metric(
                fully_laden_planned,
                "ly",
                "validated calculation with full planned cargo capacity "
                "and full planned main tank",
                fully_laden_unavailable,
                fully_laden_calculation,
            ),
        },
    ]
    for metric in metrics:
        installed_value = metric["installed"]["value"]
        planned_value = metric["planned"]["value"]
        metric["delta"] = (
            planned_value - installed_value
            if installed_value is not None and planned_value is not None
            else None
        )
    attribute_comparisons = []
    for slot, target in targets_by_slot.items():
        if not target.get("module_attributes"):
            continue
        planned = outfitting_rules.attribute_values(target)
        raw = modules.get(slot, {})
        record = reference.get(str(raw.get("item") or "").casefold(), {})
        definitions = target.get("attribute_definitions", {})
        baseline = outfitting_rules.observed_attributes(raw, record, definitions)
        if _target_matches_installed(raw, target):
            planned = dict(baseline)
        rows = [
            {
                "id": key,
                "label": definitions.get(key, {}).get("name", key),
                "unit": definitions.get(key, {}).get("unit", ""),
                "installed": baseline.get(key),
                "planned": value,
                "delta": value - baseline[key]
                if isinstance(baseline.get(key), (int, float))
                else None,
            }
            for key, value in planned.items()
            if isinstance(value, (int, float))
        ]
        attribute_comparisons.append(
            {
                "slot": slot,
                "module_label": target.get("module_label"),
                "attributes": rows,
                "notes": target.get("special_effect_notes", []),
            }
        )
    fit = outfitting_rules.configuration_check(
        reference_catalog,
        live_state.get("current_ship_type"),
        live_state.get("modules") or {},
        list(targets_by_slot.values()),
    )
    if (
        planned_supply is not None
        and planned_deployed_power is not None
        and planned_supply < planned_deployed_power
    ):
        if not power_plan or not any(
            r.get("required_in") for r in power_plan.get("modules", [])
        ):
            # Legacy callers require all enabled equipment. Explicit power plans
            # may intentionally shed equipment, but required losses are reported.
            fit["errors"].append(
                "Enabled module demand exceeds the planned power plant output."
            )
            fit["state"] = "invalid"
        else:
            fit["warnings"].append(
                (
                    "Requested demand exceeds generation; inspect priority "
                    "shutdowns and required modules."
                )
            )
    elif planned_supply is None or planned_deployed_power is None:
        fit["unknown"].append(
            "Complete enabled power demand or plant output is unavailable; "
            "operating power is unverified."
        )
        if not fit["errors"]:
            fit["state"] = "unknown"
    if missing_power_slots:
        fit["unknown"].append(
            "Missing enabled-module power draw: " + "; ".join(missing_power_slots) + "."
        )
        if not fit["errors"]:
            fit["state"] = "unknown"
    if unmodelled_retracted_slots:
        fit["unknown"].append(
            "Missing planned retracted deployment policy: "
            + ", ".join(unmodelled_retracted_slots)
            + "."
        )
        if not fit["errors"]:
            fit["state"] = "unknown"
    conditions = operating_conditions or {}
    if set(conditions) - {"cargo_mass", "fuel_mass"}:
        raise ValueError("Unsupported operating assumption.")
    loaded = {}
    for field, capacity in (
        ("cargo_mass", planned_cargo),
        ("fuel_mass", planned_fuel_capacity),
    ):
        value = conditions.get(field)
        if value is not None:
            number = _number(value)
            if (
                number is None
                or number < 0
                or (capacity is not None and number > capacity)
            ):
                raise ValueError(
                    f"{field.replace('_', ' ')} must be within the planned capacity."
                )
            loaded[field] = number
    condition_reason = fully_laden_unavailable
    selected_ranges: dict[str, float | None] = {"installed": None, "planned": None}
    for side, ship_mass, cargo_limit, tank, engine in (
        ("installed", mass, cargo, fuel_capacity, installed_drive),
        ("planned", planned_mass, planned_cargo, planned_fuel_capacity, drive),
    ):
        carried = loaded.get("cargo_mass", cargo_limit)
        fuel = loaded.get("fuel_mass", tank)
        if (
            not condition_reason
            and engine
            and ship_mass is not None
            and carried is not None
            and fuel is not None
            and cargo_limit is not None
            and tank is not None
            and carried <= cargo_limit
            and fuel <= tank
        ):
            selected_ranges[side] = single_jump_range(
                mass_excluding_fuel=ship_mass + carried,
                fuel_on_board=fuel,
                optimal_mass=float(engine["optimal_mass"]),
                max_fuel_per_jump=float(engine["max_fuel_per_jump"]),
                fuel_multiplier=float(engine["fuel_multiplier"]),
                fuel_power=float(engine["fuel_power"]),
                jump_boost=float(engine["jump_boost"]),
            )
    metrics.append(
        {
            "id": "configured_jump_range",
            "label": "Configured loading jump range",
            **{
                side: _metric(
                    value,
                    "ly",
                    "Verified jump equation; selected cargo/main fuel; 0 t reservoir",
                    condition_reason if value is None else None,
                )
                for side, value in selected_ranges.items()
            },
        }
    )
    if live_state.get("planning_hull_id"):
        for metric in metrics:
            for side in ("installed", "planned"):
                if metric[side]["value"] is not None:
                    metric[side]["basis"] = (
                        "Pinned catalogue stock planning baseline "
                        "and verified target effects"
                    )
    return {
        "operating_conditions": loaded,
        "loading_capacity": {
            "cargo_mass": planned_cargo,
            "fuel_mass": planned_fuel_capacity,
        },
        "configuration_check": fit,
        "power_management": power,
        "module_attribute_comparisons": attribute_comparisons,
        "version": PERFORMANCE_VERSION,
        "model_provenance": {
            "jump_formula_id": JUMP_FORMULA_ID,
            "implementation": "independent local implementation",
            "sources": list(JUMP_RESEARCH_SOURCES),
            "validation_tolerance": {
                "absolute_ly": JUMP_ABSOLUTE_TOLERANCE_LY,
                "relative": JUMP_RELATIVE_TOLERANCE,
            },
        },
        "assumptions": (
            "The Frontier MaxJumpRange proof gate retains zero cargo and one-jump "
            "fuel semantics. Fully laden range loads each configuration's "
            "complete cargo capacity and full main fuel tank, with a fixed "
            "0 t reservoir-fuel comparison assumption. This is not current range."
        ),
        "cargo_constraint": (
            "Cargo capacity is unknown and is never inferred."
            if cargo is None
            else "Planned cargo capacity is unknown."
            if planned_cargo is None
            else f"Cargo locked at {cargo:g} t across comparisons."
            if planned_cargo == cargo
            else f"Cargo changes from {cargo:g} t to {planned_cargo:g} t; "
            "cargo-preserving priority is not met."
        ),
        "power_viability": {
            "missing_power_slots": missing_power_slots,
            "installed": (
                installed_supply >= deployed_power
                if installed_supply is not None and deployed_power is not None
                else None
            ),
            "planned": (
                planned_supply >= planned_deployed_power
                if planned_supply is not None and planned_deployed_power is not None
                else None
            ),
            "basis": "all currently enabled modules at deployed load",
        },
        "metrics": metrics,
        "module_changes": module_changes,
        "jump_model_validation": validation,
    }
