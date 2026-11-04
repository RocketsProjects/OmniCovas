"""Transform the pinned data file into the one Engineering catalogue schema."""

from __future__ import annotations

import math
import re
from typing import Any

from omnicovas.features.reference_literals import read_object

JsonDict = dict[str, Any]
CORE = (
    "Armour",
    "PowerPlant",
    "MainEngines",
    "FrameShiftDrive",
    "LifeSupport",
    "PowerDistributor",
    "Radar",
    "FuelTank",
)
CATEGORIES = {
    "cbh": "armour",
    "cpp": "power_plant",
    "ct": "thrusters",
    "cfsd": "frame_shift_drive",
    "cfsdo": "frame_shift_drive",
    "cls": "life_support",
    "cpd": "power_distributor",
    "cs": "sensors",
    "cft": "fuel_tank",
    "isg": "shield_generator",
}
STATS = {
    "mass": "mass",
    "pwrdraw": "power_draw",
    "pwrcap": "power_capacity",
    "heateff": "heat_efficiency",
    "integ": "integrity",
    "fsdoptmass": "fsd_optimal_mass",
    "maxfuel": "fsd_max_fuel",
    "fuelmul": "fsd_fuel_multiplier",
    "fuelpower": "fsd_fuel_power",
    "jumpbst": "jump_boost",
    "cargocap": "cargo_capacity",
    "fuelcap": "fuel_capacity",
    "engmaxmass": "thruster_max_mass",
    "genmaxmass": "shield_max_hull_mass",
    "engcap": "distributor_eng_capacity",
}


def number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
    )


def convert(source: str) -> JsonDict:
    data = read_object(source)
    definitions = {
        row["attr"]: {
            key: row[key]
            for key in (
                "name",
                "unit",
                "fdattr",
                "default",
                "min",
                "max",
                "step",
                "modset",
                "modadd",
                "modmod",
                "bad",
            )
            if key in row and row[key] is not None
        }
        for row in data["attributes"]
        if row.get("attr")
    }
    hull_ids = {key: row["fdname"].casefold() for key, row in data["ship"].items()}

    def slot_name(ship: JsonDict, group: str, index: int, size: int) -> str:
        explicit = ship.get("slotnames", {}).get(group, [])
        if index < len(explicit) and explicit[index]:
            return str(explicit[index])
        if group == "component":
            return CORE[index]
        if group == "utility":
            return f"TinyHardpoint{index + 1}"
        if group == "hardpoint":
            ordinal = ship["slots"][group][: index + 1].count(size)
            prefix = ("Tiny", "Small", "Medium", "Large", "Huge")[size]
            return f"{prefix}Hardpoint{ordinal}"
        return (
            f"Military{index + 1:02}"
            if group == "military"
            else f"Slot{index + 1:02}_Size{size}"
        )

    hulls = []
    for key, ship in data["ship"].items():
        slots = []
        for group, sizes in ship["slots"].items():
            for index, size in enumerate(sizes):
                group_rule = (
                    data["group"][group][index]
                    if group == "component"
                    else data["group"][group]
                )
                allowed = set(group_rule["mtypes"])
                restricted = ship.get("reserved", {}).get(group, [])
                if index < len(restricted) and restricted[index]:
                    allowed &= set(restricted[index])
                name = slot_name(ship, group, index, size)
                slots.append(
                    {
                        "id": name,
                        "label": name
                        if group != "component"
                        else (
                            "Armour",
                            "Power plant",
                            "Thrusters",
                            "Frame shift drive",
                            "Life support",
                            "Power distributor",
                            "Sensors",
                            "Fuel tank",
                        )[index],
                        "slot_type": "core" if group == "component" else group,
                        "size": size,
                        "allowed_categories": sorted(
                            {CATEGORIES.get(m, m) for m in allowed}
                        ),
                        "exact_size": group == "component" and index in (4, 6),
                        "required": group == "component",
                        "group": group,
                    }
                )
        stock_modules = {}
        for group, entries in ship.get("stock", {}).items():
            for index, module_key in enumerate(entries):
                if not module_key:
                    continue
                module_key = str(module_key)
                record = {
                    **data["module"].get(module_key, {}),
                    **ship.get("module", {}).get(module_key, {}),
                }
                if record.get("fdname"):
                    stock_modules[
                        slot_name(ship, group, index, ship["slots"][group][index])
                    ] = record["fdname"].casefold()
        hulls.append(
            {
                "id": hull_ids[key],
                "name": ship["name"],
                "slots": slots,
                "stock_modules": stock_modules,
                "stats": {
                    "hull_mass": ship["mass"],
                    "boost_energy": ship.get("boostcost"),
                },
            }
        )

    def material_bill(bill: JsonDict) -> list[JsonDict]:
        return [
            {
                "material_id": data["material"][key]["fdname"].casefold(),
                "display_name": data["material"][key]["name"].strip(),
                "count": count,
            }
            for key, count in bill.items()
        ]

    blueprint_ids = {
        key: str(row.get("fdname") or f"reference_blueprint_{key}")
        for key, row in data["blueprint"].items()
    }
    # Preserve source keys for collisions rather than merging distinct mechanics.
    for key, identifier in list(blueprint_ids.items()):
        if list(blueprint_ids.values()).count(identifier) > 1:
            blueprint_ids[key] = f"{identifier}:{key}"
    effect_ids = {
        key: str(row.get("fdname") or f"reference_experimental_{key}")
        for key, row in data["expeffect"].items()
    }
    blueprints = []
    for key, row in data["blueprint"].items():
        categories = {
            CATEGORIES.get(mt, mt)
            for mt, record in data["mtype"].items()
            if key in record.get("blueprints", [])
        }
        if not categories:
            continue
        grade_count = min(int(row.get("maxgrade", 0)), len(row.get("mats", [])))
        if not grade_count:
            continue
        effect_keys = {
            e
            for mt, record in data["mtype"].items()
            if key in record.get("blueprints", [])
            for e in record.get("expeffects", [])
        }
        experiments = []
        for e in sorted(effect_keys):
            exp = data["expeffect"][e]
            experiments.append(
                {
                    "id": effect_ids[e],
                    "name": exp["name"],
                    "materials": material_bill(exp["mats"]) if "mats" in exp else None,
                    "effects": {
                        f"{target}_percent": exp[field]
                        for field, target in STATS.items()
                        if field in exp
                        and field
                        in {
                            "mass",
                            "integ",
                            "pwrdraw",
                            "pwrcap",
                            "heateff",
                            "fsdoptmass",
                            "maxfuel",
                        }
                    },
                    "attribute_effects": {
                        field: value
                        for field, value in exp.items()
                        if field in definitions and number(value)
                    },
                    "special": exp.get("special"),
                }
            )
        effects = {}
        generic = {}
        for grade in range(grade_count):
            fields = {
                field: values[grade]
                for field, values in row.items()
                if field in definitions
                and isinstance(values, list)
                and grade < len(values)
                and number(values[grade])
            }
            generic[str(grade + 1)] = fields
            effects[str(grade + 1)] = {
                f"{target}_percent": fields[field]
                for field, target in STATS.items()
                if field in fields
                and field
                in {
                    "mass",
                    "integ",
                    "pwrdraw",
                    "pwrcap",
                    "heateff",
                    "fsdoptmass",
                    "maxfuel",
                }
            }
        source_line = next(
            (
                line
                for line in source.splitlines()
                if re.match(r"\s*" + re.escape(key) + r"\s*:", line)
            ),
            "",
        )
        cost_caveats = (
            ["This reference omits Merc-Coin costs; its material bill is incomplete."]
            if "merccoin" in source_line.casefold()
            else []
        )
        if "TODO:" in source_line:
            cost_caveats.append(
                "Pinned reference marks this blueprint incomplete/unverified: "
                + source_line.split("TODO:", 1)[1].strip()
            )
        blueprints.append(
            {
                "id": blueprint_ids[key],
                "name": row["name"],
                "module_categories": sorted(categories),
                "grades": {
                    str(g + 1): material_bill(row["mats"][g])
                    for g in range(grade_count)
                },
                "grade_effects": effects,
                "attribute_effects": generic,
                "effect_rule": "multiplicative_blueprint_experimental",
                "experimentals": experiments,
                "special": row.get("special"),
                "cost_caveats": cost_caveats,
                "numerical_data_complete": "TODO:" not in source_line,
            }
        )

    def module_record(
        key: str, row: JsonDict, hull_id: str | None = None
    ) -> JsonDict | None:
        if row.get("hidden") or not row.get("mtype"):
            return None
        mt = row["mtype"]
        mtype = data["mtype"][mt]
        attributes = {
            field: value
            for field, value in row.items()
            if field in definitions and number(value)
        }
        for field in mtype.get("modifiable", []):
            if (
                field in definitions
                and field not in attributes
                and number(definitions[field].get("default"))
            ):
                attributes[field] = definitions[field]["default"]
        stats = {
            target: row[field]
            for field, target in STATS.items()
            if number(row.get(field))
        }
        # Omitted draw is zero only because this pinned source explicitly
        # defines that default. An absent definition must remain unavailable.
        if "power_draw" not in stats and number(
            definitions.get("pwrdraw", {}).get("default")
        ):
            stats["power_draw"] = definitions["pwrdraw"]["default"]
        # Mass defaults to zero only where the source attribute definition says so.
        if "mass" not in stats and number(definitions["mass"].get("default")):
            stats["mass"] = definitions["mass"]["default"]
        slot_types = (
            ["core"]
            if any(mt in g["mtypes"] for g in data["group"]["component"])
            else []
        )
        slot_types += [
            g
            for g in ("hardpoint", "utility", "military", "internal")
            if mt in data["group"][g]["mtypes"]
        ]
        restricted = (
            [hull_id]
            if hull_id
            else [hull_ids[k] for k in row.get("reserved", {}) if k in hull_ids]
        )
        mount = {"F": "Fixed", "G": "Gimballed", "T": "Turreted"}.get(
            str(row.get("mount") or ""), ""
        )
        identifier = str(row.get("fdname") or f"edsy_module_{key}").casefold()
        rules = {
            "power_lock": row.get("powerlock", 0),
            "no_undersize": bool(row.get("noundersize")),
            "limit_group": row.get("limit"),
            "raises_limit_group": row.get("unlimit"),
            "limit_increase": row.get("unlimitcount", 0),
            "retracted_power": (
                "deployed_only"
                if "hardpoint" in slot_types
                or ("utility" in slot_types and not row.get("passive"))
                else "same"
            ),
        }
        if row.get("reserved") and mt in {"icr", "imlc"}:
            rules["required_slot_prefixes"] = [
                "Cargo" if mt == "icr" else "LimpetController"
            ]
        if mt == "ipvh" and "largebuggybay" not in identifier:
            rules["forbidden_slot_prefixes"] = ["FighterBay"]
        if key == "80339":
            ship = data["ship"]["18"]
            rules["hull_slot_restrictions"] = {
                hull_ids["18"]: [
                    slot_name(ship, "hardpoint", i, ship["slots"]["hardpoint"][i])
                    for i in (3, 4)
                ]
            }
        return {
            "id": identifier,
            "name": (
                f"{row.get('class', 0)}{row.get('rating', '')} {row['name']}"
                + (" · " + mount if mount else "")
            ),
            "category": CATEGORIES.get(mt, mt),
            "class": row.get("class", 0),
            "rating": row.get("rating"),
            "slot_types": slot_types or ["reference_only"],
            "hull_restrictions": restricted,
            "stats": stats,
            "attributes": attributes,
            "rules": rules,
            "blueprint_ids": [
                blueprint_ids[b]
                for b in mtype.get("blueprints", [])
                if b in blueprint_ids
                and b not in row.get("noblueprints", {})
                and "*" not in row.get("noblueprints", {})
            ],
            "experimental_ids": [
                effect_ids[e]
                for e in mtype.get("expeffects", [])
                if e in effect_ids
                and e not in row.get("noexpeffects", {})
                and "*" not in row.get("noexpeffects", {})
            ],
            "modifiable_attributes": [
                a for a in mtype.get("modifiable", []) if a in definitions
            ],
        }

    modules = []
    for key, row in data["module"].items():
        if row.get("mtype") == "cbh":
            continue
        candidate = module_record(key, row)
        if candidate:
            modules.append(candidate)
    for key, ship in data["ship"].items():
        for module_key, override in ship.get("module", {}).items():
            base = data["module"].get(module_key, {})
            if base.get("mtype") != "cbh":
                continue
            candidate = module_record(module_key, {**base, **override}, hull_ids[key])
            if candidate:
                modules.append(candidate)
    supported_blueprints = {b["id"] for b in blueprints}
    for module in modules:
        module["blueprint_ids"] = [
            b for b in module["blueprint_ids"] if b in supported_blueprints
        ]
    return {
        "hulls": hulls,
        "modules": modules,
        "blueprints": blueprints,
        "attribute_definitions": definitions,
        "module_limits": data["limit"],
        "coverage": {
            "module_families": len(data["mtype"]),
            "source_module_rows": len(data["module"]),
            "source_blueprints": len(data["blueprint"]),
            "source_experimentals": len(data["expeffect"]),
            "boundary": (
                "All non-hidden catalogue entries; missing source identities/grades "
                "and special-effect simulations remain explicit, not invented."
            ),
        },
    }
