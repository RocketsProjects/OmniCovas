"""Shared fit, attribute and whole-configuration rules for Engineering plans.

All functions consume the versioned canonical catalogue; no second state/store.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

JsonDict = dict[str, Any]
VERSION = "whole-loadout-fitting-v2"

# Display names only. The versioned catalogue owns membership and allowances.
LIMIT_LABELS = {
    "hex": "Experimental weapons",
    "uex": "Xeno scanner",
    "ukws": "Kill warrant scanner",
    "ucs": "Manifest scanner",
    "upwa": "Pulse wave analyser",
    "ufsws": "Wake scanner",
    "iex": "Experimental weapon stabiliser",
    "ifh": "Vessel hangar",
    "ifa_dc": "Docking computer",
    "ifa_sc": "Supercruise assist",
    "ifsdb": "Guardian FSD booster",
    "ifsdi": "FSD interdictor",
    "ifs": "Fuel scoop",
    "imlc": "Multi-limpet controller",
    "ir": "Refinery",
    "isg": "Shield generator",
    "isbs": "Discovery scanner",
    "iss": "Detailed surface scanner",
}


def slot_label(slot: JsonDict) -> str:
    text = slot.get("label") or slot["id"]
    text = re.sub(r"^Slot0*(\d+)_Size(\d+)$", r"Internal \1 (class \2)", text)
    text = re.sub(r"^Military0*(\d+)$", r"Military \1", text)
    text = re.sub(r"^TinyHardpoint(\d+)$", r"Utility \1", text)
    return text


def blocked_replacements(
    catalog: JsonDict,
    hull: JsonDict,
    fitted: JsonDict,
    counts: Counter[str],
    raises: Counter[str],
) -> JsonDict:
    """Evaluate quantity changes against the complete fit, including the slot replaced.

    Slot/hull compatibility stays in compatible(). Existing invalid observations
    may be repaired incrementally; an unchanged excess is not a new installation.
    Power switches never change a structural quantity allowance.
    """
    limits = catalog.get("module_limits", {})
    result: JsonDict = {}
    candidates = [
        m
        for m in catalog["modules"]
        if m.get("rules", {}).get("limit_group")
        or m.get("rules", {}).get("raises_limit_group")
    ]
    # Removing a stabiliser can invalidate weapons of a different family.
    for slot in hull["slots"]:
        old = fitted.get(slot["id"], ({}, {}))[0].get("rules", {})
        options = catalog["modules"] if old.get("raises_limit_group") else candidates
        blocked = {}
        for module in options:
            if not compatible(module, hull, slot):
                continue
            rules = module.get("rules", {})
            for group, base in limits.items():
                before = counts[group] - base - raises[group]
                after = (
                    counts[group]
                    - int(old.get("limit_group") == group)
                    + int(rules.get("limit_group") == group)
                    - base
                    - raises[group]
                    + (
                        old.get("limit_increase", 0)
                        if old.get("raises_limit_group") == group
                        else 0
                    )
                    - (
                        rules.get("limit_increase", 0)
                        if rules.get("raises_limit_group") == group
                        else 0
                    )
                )
                if after > max(0, before):
                    allowed = (
                        base
                        + raises[group]
                        - (
                            old.get("limit_increase", 0)
                            if old.get("raises_limit_group") == group
                            else 0
                        )
                        + (
                            rules.get("limit_increase", 0)
                            if rules.get("raises_limit_group") == group
                            else 0
                        )
                    )
                    blocked[module["id"]] = (
                        f"{LIMIT_LABELS.get(group, group)}: maximum "
                        f"{allowed} per ship. Remove or replace existing equipment "
                        "in its slot first; disabled modules still count."
                    )
                    break
        if blocked:
            result[slot["id"]] = blocked
    return result


def engineering_gap(module: JsonDict, blueprint: JsonDict) -> str | None:
    """Conservative support boundary, distinct from physical module fit.

    Ordinary engineering on stock mining lasers/abrasion blasters is contradicted
    by the direct menu audit documented at Almanac-Core 5c9479ad, data/ships/
    SOURCES.md (Engineering availability). Reward articles are separate identities.
    Source TODO recipes also lack sufficient proof of effects, costs/prerequisites.
    """
    if module.get("category") == "hmtl" and blueprint["id"] == "Weapon_LongRange":
        return "Stock mining tools have no ordinary Long Range engineering menu."
    if blueprint.get("numerical_data_complete") is False:
        caveats = "; ".join(blueprint.get("cost_caveats", []))
        return (
            f"{blueprint['name']}: verified effects/costs or special-article "
            f"prerequisites are incomplete. {caveats}"
        )
    return None


def supported_blueprint_ids(module: JsonDict, catalog: JsonDict) -> list[str] | None:
    identifiers = module.get("blueprint_ids")
    if identifiers is None:
        return None
    return [
        bp["id"]
        for bp in catalog.get("blueprints", [])
        if bp["id"] in identifiers and not engineering_gap(module, bp)
    ]


def engineering_gaps(module: JsonDict, catalog: JsonDict) -> list[str]:
    return [
        reason
        for bp in catalog.get("blueprints", [])
        if bp["id"] in (module.get("blueprint_ids") or [])
        and (reason := engineering_gap(module, bp))
    ]


def compatible(module: JsonDict, hull: JsonDict, slot: JsonDict) -> bool:
    rules = module.get("rules", {})
    size, maximum = module["class"], slot["size"]
    prefixes = rules.get("required_slot_prefixes", [])
    forbidden = rules.get("forbidden_slot_prefixes", [])
    restricted_slots = rules.get("hull_slot_restrictions", {}).get(hull["id"])
    return bool(
        slot["slot_type"] in module["slot_types"]
        and module["category"] in slot["allowed_categories"]
        and size <= maximum
        and (
            not (slot.get("exact_size") or rules.get("no_undersize")) or size == maximum
        )
        and (
            not module.get("hull_restrictions")
            or hull["id"] in module["hull_restrictions"]
        )
        and (
            not prefixes
            or any(slot["id"].casefold().startswith(p.casefold()) for p in prefixes)
        )
        and not any(slot["id"].casefold().startswith(p.casefold()) for p in forbidden)
        and (restricted_slots is None or slot["id"] in restricted_slots)
    )


def attribute_values(target: JsonDict) -> JsonDict:
    base = dict(target.get("module_attributes", {}))
    definitions = target.get("attribute_definitions", {})
    bp = (
        target.get("blueprint_attribute_effects", {})
        if target.get("target_state") == "engineered"
        else {}
    )
    exp = (
        target.get("experimental_attribute_effects", {})
        if target.get("target_state") == "engineered"
        else {}
    )
    if (
        target.get("target_state") == "engineered"
        and target.get("numerical_effects_verified") is not True
    ):
        return {}
    values = dict(base)
    for attr in set(base) | set(bp) | set(exp):
        definition = definitions.get(attr, {})
        original = base.get(attr, definition.get("default"))
        if not isinstance(original, (int, float)) or not math.isfinite(original):
            continue
        left, right = bp.get(attr, 0), exp.get(attr, 0)
        if not left and not right:
            continue
        if definition.get("modset"):
            value = left if attr in bp else right
        elif definition.get("modadd"):
            value = original + left + right
        elif definition.get("modmod"):
            scale = definition["modmod"]
            value = (original + scale) * (1 + left / scale) * (
                1 + right / scale
            ) - scale
        else:
            value = original * (1 + left / 100) * (1 + right / 100)
        if attr == "ammoclip" and left:
            burst = bp.get("bstsize", base.get("bstsize", 1))
            value = math.ceil(original * (1 + left / 100) / burst) * burst
            value *= 1 + right / 100
        if attr == "dmgfall" and left and "maximumrng" in base:
            value = min(
                original * (1 + left / 100),
                base["maximumrng"] * (1 + bp.get("maximumrng", 0) / 100),
            ) * (1 + right / 100)
        if definition.get("step"):
            step = definition["step"]
            value = math.floor(value / step + 0.5) * step
        if isinstance(definition.get("min"), (int, float)):
            value = max(value, definition["min"])
        if isinstance(definition.get("max"), (int, float)):
            value = min(value, definition["max"])
        values[attr] = value
    # Linked mass curves use their independently documented common multiplier.
    for child, parent, positive_only in [
        ("engminmass", "engoptmass", False),
        ("engmaxmass", "engoptmass", False),
        ("genminmass", "genoptmass", False),
        ("genmaxmass", "genoptmass", True),
        ("engminmul", "engoptmul", False),
        ("engmaxmul", "engoptmul", False),
        ("genminmul", "genoptmul", False),
        ("genmaxmul", "genoptmul", False),
        ("brcdmg", "damage", False),
        ("shotspd", "maximumrng", True),
        ("maxrng", "typemis", False),
    ]:
        if child in base and base.get(parent) and parent in values:
            ratio = values[parent] / base[parent]
            values[child] = values.get(child, base[child]) * (
                max(1, ratio) if positive_only else ratio
            )
    # Rates use the source burst/clip timing model, minimum weapon charge.
    if "damage" in values:
        burst = values.get("bstsize", definitions.get("bstsize", {}).get("default", 1))
        burst_rate = values.get("bstrof", definitions.get("bstrof", {}).get("default"))
        interval = values.get("bstint", definitions.get("bstint", {}).get("default"))
        duration = 0 if values.get("dmgmul") else values.get("duration", 0)
        if isinstance(interval, (int, float)) and (burst == 1 or burst_rate):
            cycle = (
                duration + (0 if burst == 1 else (burst - 1) / burst_rate) + interval
            )
            clip = values.get("ammoclip", 0) or burst
            if target.get("experimental_effect") == "special_auto_loader":
                clip += clip - 1
            cycles = math.ceil(clip / burst)
            if cycle > 0:
                values["rof"] = clip / (cycle * cycles)
                reload_duration = (
                    0
                    if target.get("module_id") == "hpt_railgun_fixed_medium_burst"
                    else duration
                )
                reload_cycle = (
                    reload_duration
                    + (0 if burst == 1 else (burst - 1) / burst_rate)
                    + interval
                )
                values["srof"] = clip / (
                    reload_cycle * cycles
                    + max(0, values.get("rldtime", 0) - reload_duration - interval)
                )
        rate = values.get("rof")
        if rate:
            values["dps"] = values["damage"] * values.get("rounds", 1) * rate
            values["sdps"] = (
                values["damage"] * values.get("rounds", 1) * values.get("srof", rate)
            )
        elif "dps" in base and base.get("damage"):
            values["dps"] = base["dps"] * values["damage"] / base["damage"]
    return values


def observed_attributes(
    raw: JsonDict, module: JsonDict, definitions: JsonDict
) -> JsonDict:
    """Read absolute Journal modifiers without reconstructing unknown weapon rates."""
    base = dict(module.get("attributes", {}))
    engineering = raw.get("engineering") or {}
    modifiers = engineering.get("Modifiers", engineering.get("Modifications"))
    if engineering and not isinstance(modifiers, list):
        return {}
    fields = {
        str(d.get("fdattr") or "").casefold(): key
        for key, d in definitions.items()
        if d.get("fdattr")
    }
    changed = set()
    for modifier in modifiers or []:
        key = fields.get(str(modifier.get("Label") or "").casefold())
        value = modifier.get("Value")
        if key and isinstance(value, (int, float)) and math.isfinite(value):
            base[key] = value
            changed.add(key)
    for child, parent, positive_only in [
        ("engminmass", "engoptmass", False),
        ("engmaxmass", "engoptmass", False),
        ("genminmass", "genoptmass", False),
        ("genmaxmass", "genoptmass", True),
    ]:
        stock = module.get("attributes", {})
        if (
            parent in changed
            and child not in changed
            and stock.get(parent)
            and child in stock
        ):
            ratio = base[parent] / stock[parent]
            base[child] = stock[child] * (max(1, ratio) if positive_only else ratio)
    if engineering:
        for field in ("dps", "sdps", "rof", "srof", "eps", "seps", "hps", "shps"):
            if field not in changed:
                base.pop(field, None)
    return base


def target_metadata(
    module: JsonDict,
    blueprint: JsonDict | None,
    grade: int | None,
    experimental: JsonDict | None,
    definitions: JsonDict,
) -> JsonDict:
    attrs = module.get("attributes", {})
    bp = (blueprint or {}).get("attribute_effects", {}).get(str(grade), {})
    if module.get("modifiable_attributes"):
        bp = {
            key: value
            for key, value in bp.items()
            if key in module["modifiable_attributes"]
        }
    exp = (experimental or {}).get("attribute_effects", {})
    fields = set(attrs) | set(bp) | set(exp)
    return {
        "module_attributes": dict(attrs),
        "attribute_definitions": {
            k: v
            for k, v in definitions.items()
            if k in fields or k in {"bstsize", "bstrof", "bstint"}
        },
        "blueprint_attribute_effects": dict(bp),
        "experimental_attribute_effects": dict(exp),
        "module_rules": dict(module.get("rules", {})),
        "cost_caveats": list((blueprint or {}).get("cost_caveats", [])),
        "special_effect_notes": [
            s
            for s in [
                (blueprint or {}).get("special"),
                (experimental or {}).get("special"),
            ]
            if s
        ],
    }


def configuration_check(
    catalog: JsonDict | None,
    hull_id: str | None,
    modules: JsonDict,
    targets: list[JsonDict],
) -> JsonDict:
    if not catalog:
        return {
            "state": "unknown",
            "errors": [],
            "unknown": [
                "A full validated catalogue is needed for complete fitting checks."
            ],
        }
    hull = next(
        (
            h
            for h in catalog.get("hulls", [])
            if h["id"].casefold() == str(hull_id).casefold()
        ),
        None,
    )
    if hull is None:
        return {
            "state": "unknown",
            "errors": [],
            "unknown": [
                "Hull slot/operating rules are absent from the active catalogue."
            ],
        }
    index = {m["id"].casefold(): m for m in catalog["modules"]}
    changed = {t["slot"]: t for t in targets}
    counts: Counter[str] = Counter()
    raises: Counter[str] = Counter()
    errors, unknown = [], []
    violations = []
    fitted = {}
    for slot in hull["slots"]:
        raw = modules.get(slot["id"], {})
        target = changed.get(slot["id"])
        identifier = target.get("module_id") if target else raw.get("item")
        if target and target.get("target_state") == "empty":
            identifier = None
        if not identifier:
            if slot.get("required"):
                errors.append(f"{slot_label(slot)} is a required core module.")
            continue
        module = index.get(str(identifier).casefold())
        if module is None:
            unknown.append(f"Module rules are unavailable for {slot['label']}.")
            continue
        if not compatible(module, hull, slot):
            errors.append(f"{module['name']} is not a legal fit in {slot_label(slot)}.")
            violations.append({"rule": "slot_hull", "slot": slot["id"], "excess": 1})
        rules = module.get("rules", {})
        if rules.get("limit_group"):
            counts[rules["limit_group"]] += 1
            if rules["limit_group"] not in catalog.get("module_limits", {}):
                unknown.append(f"Quantity allowance unavailable for {module['name']}.")
        if rules.get("raises_limit_group"):
            raises[rules["raises_limit_group"]] += rules.get("limit_increase", 0)
        attrs = (
            attribute_values(target) if target else dict(module.get("attributes", {}))
        )
        if (
            target
            and target.get("target_state") == "engineered"
            and not target.get("numerical_effects_verified")
        ):
            unknown.append(
                f"Exact planned engineering is unavailable for {slot['label']}."
            )
        if not target and isinstance(raw.get("engineering"), dict):
            eng = raw["engineering"]
            observed = eng.get("Modifiers", eng.get("Modifications"))
            if not isinstance(observed, list):
                unknown.append(
                    f"Observed engineering is incomplete for {slot['label']}."
                )
                observed = []
            for modifier in observed:
                field = next(
                    (
                        a
                        for a, d in catalog.get("attribute_definitions", {}).items()
                        if d.get("fdattr", "").casefold()
                        == str(modifier.get("Label", "")).casefold()
                    ),
                    None,
                )
                if field and isinstance(modifier.get("Value"), (int, float)):
                    attrs[field] = modifier["Value"]
            # Known linked engine maximum follows observed optimal-mass change.
            base = module.get("attributes", {})
            if (
                base.get("engoptmass")
                and attrs.get("engoptmass")
                and base.get("engmaxmass")
            ):
                attrs["engmaxmass"] = (
                    base["engmaxmass"] * attrs["engoptmass"] / base["engoptmass"]
                )
        fitted[slot["id"]] = (module, attrs)
        hull_mass = hull.get("stats", {}).get("hull_mass")
        if hull_mass is None and module["category"] in {
            "thrusters",
            "shield_generator",
        }:
            unknown.append(
                f"Hull mass is unavailable for {slot['label']} support checks."
            )
        if module["category"] == "thrusters" and "engmaxmass" not in attrs:
            unknown.append("Thruster maximum supported hull mass is unavailable.")
        if module["category"] == "shield_generator" and "genmaxmass" not in attrs:
            unknown.append("Shield generator maximum hull mass is unavailable.")
        for field, description in [
            ("engmaxmass", "thruster maximum supported hull mass"),
            ("genmaxmass", "shield generator maximum hull mass"),
        ]:
            if field in attrs and hull_mass is not None and attrs[field] < hull_mass:
                errors.append(
                    f"{module['name']}: {description} {attrs[field]:g} t "
                    f"is below hull mass {hull_mass:g} t."
                )
    for group, count in counts.items():
        maximum = catalog.get("module_limits", {}).get(group)
        if maximum is not None and count > maximum + raises[group]:
            slots = [
                slot_label(s)
                for s in hull["slots"]
                if fitted.get(s["id"], ({}, {}))[0].get("rules", {}).get("limit_group")
                == group
            ]
            errors.append(
                f"{LIMIT_LABELS.get(group, group)}: {count} fitted; maximum "
                f"{maximum + raises[group]} per ship. Fitted in {', '.join(slots)}."
            )
            violations.append(
                {
                    "rule": "quantity",
                    "group": group,
                    "excess": count - maximum - raises[group],
                }
            )
    distributor = fitted.get("PowerDistributor")
    boost = hull.get("stats", {}).get("boost_energy")
    warnings = []
    if distributor and boost and distributor[1].get("engcap", float("inf")) < boost:
        # Low-capacity distributors can be fitted, but boosting is unavailable.
        warnings.append(
            "Boost unavailable: distributor ENG capacity is below the hull's "
            f"{boost:g} MJ boost requirement."
        )
    return {
        "version": VERSION,
        "state": "invalid" if errors else "unknown" if unknown else "valid",
        "errors": errors,
        "unknown": unknown,
        "warnings": warnings,
        "violations": violations,
        "blocked_replacements": blocked_replacements(
            catalog, hull, fitted, counts, raises
        ),
    }
