"""Validated, local-only Engineering reference packs.

Reference packs are supplied by the Commander.  OmniCOVAS validates their
shape and internal relationships, records declared provenance and a digest,
and never downloads or scrapes a catalogue.  Validation proves conformance to
this format; it does not convert a third party's claims into telemetry truth.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import EngineeringCatalogRef
from omnicovas.features import material_trader_rules, outfitting_rules

JsonDict = dict[str, Any]

SCHEMA_VERSION = "1"
CALCULATION_VERSION = "reference-pack-cost-performance-v2"
MAX_HULLS = 96
MAX_MODULES = 2048
MAX_BLUEPRINTS = 512
MAX_ENGINEERS = 256
MAX_SERIALIZED_CATALOG_BYTES = 4_000_000
MODULE_STAT_FIELDS = {
    "mass",
    "power_draw",
    "power_capacity",
    "cargo_capacity",
    "fuel_capacity",
    "fsd_optimal_mass",
    "fsd_max_fuel",
    "fsd_fuel_multiplier",
    "fsd_fuel_power",
    "jump_boost",
    "heat_efficiency",
    "integrity",
    "thruster_max_mass",
    "shield_max_hull_mass",
    "distributor_eng_capacity",
}
ENGINEERING_EFFECT_FIELDS = {
    "mass_percent",
    "power_draw_percent",
    "power_capacity_percent",
    "heat_efficiency_percent",
    "integrity_percent",
    "fsd_optimal_mass_percent",
    "fsd_max_fuel_percent",
}


def _text(value: Any, field: str, limit: int = 128) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    clean = value.strip()
    if len(clean) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return clean


def _optional_text(value: Any, field: str, limit: int = 2048) -> str | None:
    if value is None or value == "":
        return None
    return _text(value, field, limit)


def _list(value: Any, field: str, maximum: int) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds the supported limit of {maximum}")
    return value


def _unique_id(value: Any, field: str, seen: set[str]) -> str:
    item_id = _text(value, field, 128)
    key = item_id.casefold()
    if key in seen:
        raise ValueError(f"Duplicate {field}: {item_id}")
    seen.add(key)
    return item_id


def _material_rows(value: Any, field: str) -> list[JsonDict]:
    rows: list[JsonDict] = []
    seen: set[str] = set()
    for index, raw in enumerate(_list(value, field, 32)):
        if not isinstance(raw, dict):
            raise ValueError(f"{field}[{index}] must be an object")
        material_id = _unique_id(raw.get("material_id"), f"{field}.material_id", seen)
        count = raw.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError(f"{field}.{material_id}.count must be a positive integer")
        rows.append(
            {
                "material_id": material_id,
                "display_name": _text(
                    raw.get("display_name", material_id),
                    f"{field}.{material_id}.display_name",
                ),
                "count": count,
            }
        )
    return rows


def _module_stats(value: Any, module_id: str) -> JsonDict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"module {module_id}.stats must be an object")
    unknown = sorted(set(value) - MODULE_STAT_FIELDS)
    if unknown:
        raise ValueError(f"module {module_id}.stats has unsupported field {unknown[0]}")
    stats: JsonDict = {}
    for key, raw in value.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"module {module_id}.stats.{key} must be numeric")
        number = float(raw)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"module {module_id}.stats.{key} cannot be negative")
        stats[key] = number
    return stats


def _engineering_effects(value: Any, field: str) -> JsonDict:
    """Normalize percentages applied additively to an unmodified base stat.

    Keeping the combination rule explicit avoids silently treating recipe
    identity or a material cost as proof of a numerical effect.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    unknown = sorted(set(value) - ENGINEERING_EFFECT_FIELDS)
    if unknown:
        raise ValueError(f"{field} has unsupported field {unknown[0]}")
    effects: JsonDict = {}
    for key, raw in value.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"{field}.{key} must be numeric")
        number = float(raw)
        if not math.isfinite(number) or number < -100 or number >= 1000:
            raise ValueError(f"{field}.{key} must be finite and between -100 and 1000")
        effects[key] = number
    return effects


def _effect_rule(value: Any) -> str:
    rule = value or "additive_percent_of_unmodified_base"
    if rule not in {
        "additive_percent_of_unmodified_base",
        "multiplicative_blueprint_experimental",
    }:
        raise ValueError("Unsupported engineering effect combination rule")
    return str(rule)


def _reference_object(value: Any, field: str) -> JsonDict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    # Data only: bounded by the outer serialized-pack limit. No strings from
    # these objects are executed or interpolated into HTML.
    if len(value) > 256:
        raise ValueError(f"{field} has too many fields")
    json.dumps(value, allow_nan=False)
    return dict(value)


def _numeric_attributes(value: Any, field: str) -> JsonDict:
    result = _reference_object(value, field)
    for key, number in result.items():
        if (
            isinstance(number, bool)
            or not isinstance(number, (int, float))
            or not math.isfinite(number)
        ):
            raise ValueError(f"{field}.{key} must be a finite number")
    return result


def _grade_attributes(value: Any) -> JsonDict:
    result = _reference_object(value, "grade attribute effects")
    return {
        key: _numeric_attributes(row, f"grade {key} attributes")
        for key, row in result.items()
    }


def _reference_ids(value: Any, field: str) -> list[str] | None:
    if value is None:
        return None
    return [_text(item, field, 128) for item in _list(value, field, 128)]


def _module_rules(value: Any) -> JsonDict:
    result = _reference_object(value, "module rules")
    if "power_lock" in result and (
        isinstance(result["power_lock"], bool)
        or not isinstance(result["power_lock"], int)
        or not 0 <= result["power_lock"] <= 5
    ):
        raise ValueError("Power lock must be zero or a priority from 1 to 5")
    if result.get("retracted_power") not in {None, "same", "deployed_only"}:
        raise ValueError("Unsupported retracted power policy")
    for field in ("limit_group", "raises_limit_group"):
        if result.get(field) is not None:
            result[field] = _text(result[field], field, 64)
    for field in ("required_slot_prefixes", "forbidden_slot_prefixes"):
        if field in result:
            result[field] = _reference_ids(result[field], field) or []
    increase = result.get("limit_increase", 0)
    if isinstance(increase, bool) or not isinstance(increase, int) or increase < 0:
        raise ValueError("module limit_increase must be a nonnegative integer")
    if "hull_slot_restrictions" in result:
        result["hull_slot_restrictions"] = {
            hull: _reference_ids(slots, "hull slot restrictions") or []
            for hull, slots in _reference_object(
                result["hull_slot_restrictions"], "hull slot restrictions"
            ).items()
        }
    return result


def combined_effects(
    blueprint: JsonDict, grade: int, experimental: JsonDict | None
) -> JsonDict:
    base = blueprint.get("grade_effects", {}).get(str(grade), {})
    extra = (experimental or {}).get("effects", {})
    return {
        key: (
            (1 + float(base.get(key, 0)) / 100) * (1 + float(extra.get(key, 0)) / 100)
            - 1
        )
        * 100
        if blueprint.get("effect_rule") == "multiplicative_blueprint_experimental"
        else float(base.get(key, 0)) + float(extra.get(key, 0))
        for key in set(base) | set(extra)
    }


def normalize_catalog(raw: Any) -> JsonDict:
    """Validate and normalize a Commander-supplied reference pack."""
    if not isinstance(raw, dict):
        raise ValueError("catalog must be a JSON object")
    if (
        len(json.dumps(raw, separators=(",", ":")).encode())
        > MAX_SERIALIZED_CATALOG_BYTES
    ):
        raise ValueError("catalog exceeds the supported 4 MB local import limit")
    if str(raw.get("schema_version")) != SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {SCHEMA_VERSION}")

    provenance = raw.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("provenance is required")
    normalized: JsonDict = {
        "schema_version": SCHEMA_VERSION,
        "catalog_id": _text(raw.get("catalog_id"), "catalog_id", 96),
        "version": _text(raw.get("version"), "version", 64),
        "title": _text(raw.get("title"), "title"),
        "provenance": {
            "source_name": _text(provenance.get("source_name"), "source_name"),
            "source_url": _optional_text(provenance.get("source_url"), "source_url"),
            "license": _text(provenance.get("license"), "license"),
            "rights_basis": _text(provenance.get("rights_basis"), "rights_basis", 256),
            "acquired_at": _text(provenance.get("acquired_at"), "acquired_at", 64),
            "verification_notes": _optional_text(
                provenance.get("verification_notes"), "verification_notes", 1000
            ),
        },
    }

    hull_ids: set[str] = set()
    hulls: list[JsonDict] = []
    for index, raw_hull in enumerate(_list(raw.get("hulls"), "hulls", MAX_HULLS)):
        if not isinstance(raw_hull, dict):
            raise ValueError(f"hulls[{index}] must be an object")
        hull_id = _unique_id(raw_hull.get("id"), "hull id", hull_ids)
        slot_ids: set[str] = set()
        slots: list[JsonDict] = []
        for raw_slot in _list(raw_hull.get("slots"), f"hull {hull_id} slots", 128):
            if not isinstance(raw_slot, dict):
                raise ValueError(f"hull {hull_id} slot must be an object")
            slot_id = _unique_id(raw_slot.get("id"), f"{hull_id} slot id", slot_ids)
            size = raw_slot.get("size")
            if (
                isinstance(size, bool)
                or not isinstance(size, int)
                or not 0 <= size <= 8
            ):
                raise ValueError(f"{hull_id}.{slot_id}.size must be 0 through 8")
            categories = [
                _text(item, f"{hull_id}.{slot_id}.allowed_categories", 64)
                for item in _list(
                    raw_slot.get("allowed_categories"),
                    f"{hull_id}.{slot_id}.allowed_categories",
                    64,
                )
            ]
            if not categories:
                raise ValueError(f"{hull_id}.{slot_id} needs allowed_categories")
            slots.append(
                {
                    "id": slot_id,
                    "label": _text(raw_slot.get("label", slot_id), f"{slot_id}.label"),
                    "slot_type": _text(
                        raw_slot.get("slot_type"), f"{slot_id}.slot_type", 32
                    ),
                    "size": size,
                    "allowed_categories": categories,
                }
            )
        if not slots:
            raise ValueError(f"hull {hull_id} needs at least one slot")
        hulls.append(
            {
                "id": hull_id,
                "name": _text(raw_hull.get("name"), "hull name"),
                "slots": slots,
            }
        )
    if not hulls:
        raise ValueError("catalog needs at least one hull")
    normalized["hulls"] = hulls
    for hull, raw_hull in zip(hulls, raw["hulls"], strict=True):
        hull["stats"] = _reference_object(raw_hull.get("stats"), "hull stats")
        _numeric_attributes(
            {k: v for k, v in hull["stats"].items() if v is not None}, "hull stats"
        )
        hull["stock_modules"] = _reference_object(
            raw_hull.get("stock_modules"), "reference stock fit"
        )
        for identifier in hull["stock_modules"].values():
            _text(identifier, "stock module id", 128)
        for slot, source_slot in zip(hull["slots"], raw_hull["slots"], strict=True):
            slot["exact_size"] = source_slot.get("exact_size") is True
            slot["required"] = source_slot.get("required") is True
            slot["group"] = source_slot.get("group")
    normalized["attribute_definitions"] = _reference_object(
        raw.get("attribute_definitions"), "attribute definitions"
    )
    for attribute, definition in normalized["attribute_definitions"].items():
        definition = _reference_object(definition, f"attribute {attribute}")
        for key in ("name", "unit", "fdattr"):
            if key in definition:
                _optional_text(definition[key], f"attribute {attribute} {key}", 256)
        for key in ("default", "min", "max", "step", "modmod"):
            if key in definition:
                if key == "default" and isinstance(definition[key], str):
                    _optional_text(
                        definition[key], f"attribute {attribute} default", 128
                    )
                    continue
                _numeric_attributes({key: definition[key]}, f"attribute {attribute}")
        if "step" in definition and definition["step"] <= 0:
            raise ValueError("Attribute step must be positive")
        if "modmod" in definition and definition["modmod"] == 0:
            raise ValueError("Attribute modifier scale cannot be zero")
    normalized["module_limits"] = _reference_object(
        raw.get("module_limits"), "module limits"
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in normalized["module_limits"].values()
    ):
        raise ValueError("Module limits must be nonnegative integers")
    normalized["coverage"] = _reference_object(raw.get("coverage"), "coverage")

    module_ids: set[str] = set()
    modules: list[JsonDict] = []
    for index, raw_module in enumerate(
        _list(raw.get("modules"), "modules", MAX_MODULES)
    ):
        if not isinstance(raw_module, dict):
            raise ValueError(f"modules[{index}] must be an object")
        module_id = _unique_id(raw_module.get("id"), "module id", module_ids)
        size = raw_module.get("class")
        if isinstance(size, bool) or not isinstance(size, int) or not 0 <= size <= 8:
            raise ValueError(f"module {module_id} class must be 0 through 8")
        restricted = [
            _text(item, f"module {module_id} hull_restrictions", 128)
            for item in _list(
                raw_module.get("hull_restrictions", []),
                f"module {module_id} hull_restrictions",
                MAX_HULLS,
            )
        ]
        unknown_hulls = [item for item in restricted if item.casefold() not in hull_ids]
        if unknown_hulls:
            raise ValueError(
                f"module {module_id} restricts unknown hull {unknown_hulls[0]}"
            )
        modules.append(
            {
                "id": module_id,
                "name": _text(raw_module.get("name"), "module name"),
                "category": _text(raw_module.get("category"), "module category", 64),
                "class": size,
                "rating": _optional_text(raw_module.get("rating"), "module rating", 16),
                "slot_types": [
                    _text(item, f"module {module_id} slot_types", 32)
                    for item in _list(
                        raw_module.get("slot_types"),
                        f"module {module_id} slot_types",
                        16,
                    )
                ],
                "hull_restrictions": restricted,
                "stats": _module_stats(raw_module.get("stats"), module_id),
                "attributes": _numeric_attributes(
                    raw_module.get("attributes"), "module attributes"
                ),
                "rules": _module_rules(raw_module.get("rules")),
                "blueprint_ids": _reference_ids(
                    raw_module.get("blueprint_ids"), "blueprint ids"
                ),
                "experimental_ids": _reference_ids(
                    raw_module.get("experimental_ids"), "experimental ids"
                ),
                "modifiable_attributes": _reference_ids(
                    raw_module.get("modifiable_attributes", []), "modifiable attributes"
                )
                or [],
            }
        )
        if not modules[-1]["slot_types"]:
            raise ValueError(f"module {module_id} needs slot_types")
    if not modules:
        raise ValueError("catalog needs at least one module")
    normalized["modules"] = modules

    blueprint_ids: set[str] = set()
    blueprints: list[JsonDict] = []
    for index, raw_bp in enumerate(
        _list(raw.get("blueprints", []), "blueprints", MAX_BLUEPRINTS)
    ):
        if not isinstance(raw_bp, dict):
            raise ValueError(f"blueprints[{index}] must be an object")
        blueprint_id = _unique_id(raw_bp.get("id"), "blueprint id", blueprint_ids)
        grades_raw = raw_bp.get("grades")
        if not isinstance(grades_raw, dict):
            raise ValueError(f"blueprint {blueprint_id}.grades must be an object")
        grades: JsonDict = {}
        for grade_key, materials in grades_raw.items():
            try:
                grade = int(grade_key)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"blueprint {blueprint_id} has invalid grade") from exc
            if not 1 <= grade <= 5:
                raise ValueError(f"blueprint {blueprint_id} grade must be 1 through 5")
            grades[str(grade)] = _material_rows(
                materials, f"blueprint {blueprint_id} grade {grade}"
            )
        grade_effects_raw = raw_bp.get("grade_effects", {})
        if not isinstance(grade_effects_raw, dict):
            raise ValueError(
                f"blueprint {blueprint_id}.grade_effects must be an object"
            )
        grade_effects: JsonDict = {}
        for grade_key, effects in grade_effects_raw.items():
            try:
                grade = int(grade_key)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"blueprint {blueprint_id} has invalid effect grade"
                ) from exc
            if str(grade) not in grades:
                raise ValueError(
                    f"blueprint {blueprint_id} effects reference "
                    f"unavailable grade {grade}"
                )
            grade_effects[str(grade)] = _engineering_effects(
                effects, f"blueprint {blueprint_id} grade {grade} effects"
            )
        experimentals: list[JsonDict] = []
        exp_ids: set[str] = set()
        for raw_effect in _list(
            raw_bp.get("experimentals", []),
            f"blueprint {blueprint_id} experimentals",
            64,
        ):
            if not isinstance(raw_effect, dict):
                raise ValueError(
                    f"blueprint {blueprint_id} experimental must be an object"
                )
            effect_id = _unique_id(raw_effect.get("id"), "experimental id", exp_ids)
            cost = raw_effect.get("materials")
            experimentals.append(
                {
                    "id": effect_id,
                    "name": _text(raw_effect.get("name"), "experimental name"),
                    "materials": None
                    if cost is None
                    else _material_rows(cost, f"experimental {effect_id}"),
                    "effects": _engineering_effects(
                        raw_effect.get("effects"),
                        f"experimental {effect_id} effects",
                    ),
                    "attribute_effects": _numeric_attributes(
                        raw_effect.get("attribute_effects"), "experimental attributes"
                    ),
                    "special": _optional_text(
                        raw_effect.get("special"), "experimental special", 1000
                    ),
                }
            )
        blueprints.append(
            {
                "id": blueprint_id,
                "name": _text(raw_bp.get("name"), "blueprint name"),
                "module_categories": [
                    _text(item, f"blueprint {blueprint_id} categories", 64)
                    for item in _list(
                        raw_bp.get("module_categories"),
                        f"blueprint {blueprint_id} module_categories",
                        64,
                    )
                ],
                "grades": grades,
                "grade_effects": grade_effects,
                "experimentals": experimentals,
                "effect_rule": _effect_rule(raw_bp.get("effect_rule")),
                "attribute_effects": _grade_attributes(raw_bp.get("attribute_effects")),
                "special": _optional_text(
                    raw_bp.get("special"), "blueprint special", 1000
                ),
                "cost_caveats": [
                    _text(caveat, "cost caveat", 1000)
                    for caveat in _list(
                        raw_bp.get("cost_caveats", []), "cost caveats", 32
                    )
                ],
                "numerical_data_complete": raw_bp.get("numerical_data_complete")
                is not False,
            }
        )
    normalized["blueprints"] = blueprints

    engineers: list[JsonDict] = []
    engineer_ids: set[str] = set()
    for index, raw_engineer in enumerate(
        _list(raw.get("engineers", []), "engineers", MAX_ENGINEERS)
    ):
        if not isinstance(raw_engineer, dict):
            raise ValueError(f"engineers[{index}] must be an object")
        engineer_id = _unique_id(raw_engineer.get("id"), "engineer id", engineer_ids)
        access = raw_engineer.get("access")
        if not isinstance(access, dict):
            raise ValueError(f"engineer {engineer_id}.access must be an object")
        capabilities = []
        for capability in _list(
            raw_engineer.get("blueprints", []),
            f"engineer {engineer_id} blueprints",
            256,
        ):
            if not isinstance(capability, dict):
                raise ValueError(f"engineer {engineer_id} blueprint must be an object")
            bp_id = _text(capability.get("blueprint_id"), "engineer blueprint id")
            if bp_id.casefold() not in blueprint_ids:
                raise ValueError(
                    f"engineer {engineer_id} references unknown blueprint {bp_id}"
                )
            max_grade = capability.get("max_grade")
            if (
                isinstance(max_grade, bool)
                or not isinstance(max_grade, int)
                or not 1 <= max_grade <= 5
            ):
                raise ValueError(
                    f"engineer {engineer_id} max_grade must be 1 through 5"
                )
            capabilities.append({"blueprint_id": bp_id, "max_grade": max_grade})
        # Optional Frontier EngineerID, so a pack entry reconciles with the
        # Journal by identifier instead of by display name.
        frontier_id = raw_engineer.get("engineer_id")
        if frontier_id is not None and (
            isinstance(frontier_id, bool)
            or not isinstance(frontier_id, int)
            or frontier_id <= 0
        ):
            raise ValueError(f"engineer {engineer_id} engineer_id must be positive")
        engineers.append(
            {
                "id": engineer_id,
                "engineer_id": frontier_id,
                "name": _text(raw_engineer.get("name"), "engineer name"),
                "location": _optional_text(
                    raw_engineer.get("location"), "engineer location", 256
                ),
                "system": _optional_text(
                    raw_engineer.get("system"), "engineer system", 128
                ),
                "base": _optional_text(raw_engineer.get("base"), "engineer base", 128),
                "access": {
                    "state": _text(access.get("state"), "engineer access state", 32),
                    "requirements": _optional_text(
                        access.get("requirements"), "engineer requirements", 1000
                    ),
                    "referral": _optional_text(
                        access.get("referral"), "engineer referral", 256
                    ),
                },
                "blueprints": capabilities,
            }
        )
    normalized["engineers"] = engineers
    if raw.get("trader_rule_set") is not None:
        # Opt-in strict contract (Materials 03B): the rule set states its own
        # provenance and every rule is validated or rejected, never interpreted.
        rule_set = material_trader_rules.normalize_rule_set(raw["trader_rule_set"])
        normalized["trader_rules"] = material_trader_rules.normalize_rules(
            raw.get("trader_rules", []), rule_set
        )
        normalized["trader_rule_set"] = rule_set
        return normalized
    # Legacy (03A) shape: normalized output is unchanged so an already imported
    # pack version keeps its digest and can be re-imported.
    trader_rules: list[JsonDict] = []
    trader_ids: set[str] = set()
    for index, raw_rule in enumerate(
        _list(raw.get("trader_rules", []), "trader_rules", 128)
    ):
        if not isinstance(raw_rule, dict):
            raise ValueError(f"trader_rules[{index}] must be an object")
        rule_id = _unique_id(raw_rule.get("id"), "trader rule id", trader_ids)
        pay = raw_rule.get("pay")
        receive = raw_rule.get("receive")
        if (
            isinstance(pay, bool)
            or not isinstance(pay, int)
            or pay <= 0
            or isinstance(receive, bool)
            or not isinstance(receive, int)
            or receive <= 0
        ):
            raise ValueError(
                f"trader rule {rule_id} pay/receive must be positive integers"
            )
        trader_rules.append(
            {
                "id": rule_id,
                "category": _text(raw_rule.get("category"), "trader category", 64),
                "from_material_id": _text(
                    raw_rule.get("from_material_id"), "trader source material", 128
                ),
                "from_display_name": _text(
                    raw_rule.get("from_display_name", raw_rule.get("from_material_id")),
                    "trader source display name",
                ),
                "to_material_id": _text(
                    raw_rule.get("to_material_id"), "trader target material", 128
                ),
                "to_display_name": _text(
                    raw_rule.get("to_display_name", raw_rule.get("to_material_id")),
                    "trader target display name",
                ),
                "pay": pay,
                "receive": receive,
                "notes": _optional_text(raw_rule.get("notes"), "trader notes", 500),
            }
        )
    normalized["trader_rules"] = trader_rules
    return normalized


def digest(catalog: JsonDict) -> str:
    encoded = json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


async def import_catalog(
    session_factory: async_sessionmaker[AsyncSession], raw: Any
) -> JsonDict:
    catalog = normalize_catalog(raw)
    provenance = catalog["provenance"]
    now = datetime.now(timezone.utc)
    sha256 = digest(catalog)
    catalog_key = f"{catalog['catalog_id']}@{catalog['version']}"
    async with session_factory() as db:
        row = await db.get(EngineeringCatalogRef, catalog_key)
        if row is not None and row.sha256 != sha256:
            raise ValueError(
                "A catalogue version is immutable; import changed "
                "data under a new version."
            )
        await db.execute(update(EngineeringCatalogRef).values(active=False))
        if row is None:
            row = EngineeringCatalogRef(
                catalog_key=catalog_key,
                catalog_id=catalog["catalog_id"],
                imported_at=now,
            )
            db.add(row)
        row.version = catalog["version"]
        row.title = catalog["title"]
        row.source_name = provenance["source_name"]
        row.source_url = provenance["source_url"]
        row.license_label = provenance["license"]
        row.rights_basis = provenance["rights_basis"]
        row.sha256 = sha256
        row.catalog_json = json.dumps(catalog, sort_keys=True, separators=(",", ":"))
        row.active = True
        row.imported_at = now
        await db.commit()
    return catalog_summary(catalog, sha256=sha256, imported_at=now.isoformat())


async def active_catalog(
    session_factory: async_sessionmaker[AsyncSession],
) -> JsonDict | None:
    async with session_factory() as db:
        result = await db.execute(
            select(EngineeringCatalogRef)
            .where(EngineeringCatalogRef.active.is_(True))
            .order_by(EngineeringCatalogRef.imported_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
    if row is None:
        return None
    catalog_value = json.loads(row.catalog_json)
    if not isinstance(catalog_value, dict):
        return None
    catalog: JsonDict = catalog_value
    catalog["_stored"] = {
        "sha256": row.sha256,
        "imported_at": row.imported_at.isoformat(),
    }
    return catalog


async def catalogs_by_version(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, JsonDict]:
    """Return every retained catalogue version keyed as ``id@version``."""
    async with session_factory() as db:
        result = await db.execute(select(EngineeringCatalogRef))
        rows = list(result.scalars().all())
    catalogs: dict[str, JsonDict] = {}
    for row in rows:
        value = json.loads(row.catalog_json)
        if not isinstance(value, dict):
            continue
        value["_stored"] = {
            "sha256": row.sha256,
            "imported_at": row.imported_at.isoformat(),
        }
        catalogs[row.catalog_key] = value
    return catalogs


def catalog_summary(
    catalog: JsonDict, *, sha256: str | None = None, imported_at: str | None = None
) -> JsonDict:
    stored = catalog.get("_stored", {})
    return {
        "state": "commander_supplied_validated",
        "catalog_id": catalog["catalog_id"],
        "version": catalog["version"],
        "title": catalog["title"],
        "hull_count": len(catalog["hulls"]),
        "module_count": len(catalog["modules"]),
        "blueprint_count": len(catalog["blueprints"]),
        "engineer_count": len(catalog["engineers"]),
        "sha256": sha256 or stored.get("sha256") or digest(catalog),
        "imported_at": imported_at or stored.get("imported_at"),
        "provenance": catalog["provenance"],
        "truth_class": "commander_supplied_reference",
        "verification_boundary": (
            "OmniCOVAS validated structure and internal references only; source "
            "accuracy and redistribution rights remain as declared by the Commander."
        ),
    }


def designer_catalog(catalog: JsonDict | None) -> JsonDict:
    if catalog is None:
        return {
            "state": "unavailable",
            "hulls": [],
            "modules": [],
            "blueprints": [],
            "engineers": [],
            "limitations": [
                "No lawful local reference pack is active.",
                "Enable the private catalogue or add an authorised reference pack.",
            ],
        }
    payload = catalog_summary(catalog)
    from omnicovas.features import engineering_reference

    payload["private_reference_update_available"] = (
        catalog["catalog_id"] == engineering_reference.CATALOG_ID
        and catalog["version"] != engineering_reference.VERSION
    )
    payload.update(
        {
            "hulls": catalog["hulls"],
            "modules": [
                {
                    **module,
                    "blueprint_ids": outfitting_rules.supported_blueprint_ids(
                        module, catalog
                    ),
                    "engineering_gaps": outfitting_rules.engineering_gaps(
                        module, catalog
                    ),
                }
                for module in catalog["modules"]
            ],
            "blueprints": catalog["blueprints"],
            "attribute_definitions": catalog.get("attribute_definitions", {}),
            "coverage": catalog.get("coverage", {}),
            "engineers": catalog["engineers"],
            "trader_rules": catalog["trader_rules"],
            "trader_rule_set": catalog.get("trader_rule_set"),
            "calculation_version": CALCULATION_VERSION,
            "limitations": [
                "Coverage is limited to this Commander-supplied reference pack.",
                "Validated means schema-valid, not independently licensed or "
                "fact-verified by OmniCOVAS.",
                "Material Trader rules are shown only when explicitly present; "
                "OmniCOVAS does not infer exchanges.",
            ],
        }
    )
    return payload


def validate_design(
    catalog: JsonDict, hull_id: str, targets: list[JsonDict]
) -> list[JsonDict]:
    hull = next((row for row in catalog["hulls"] if row["id"] == hull_id), None)
    if hull is None:
        raise ValueError(f"Hull is not in the active reference pack: {hull_id}")
    slots = {row["id"]: row for row in hull["slots"]}
    modules = {row["id"]: row for row in catalog["modules"]}
    blueprints = {row["id"]: row for row in catalog["blueprints"]}
    seen_slots: set[str] = set()
    normalized: list[JsonDict] = []
    for target in targets:
        slot_id = str(target.get("slot") or "")
        module_id = str(target.get("module_id") or "")
        if slot_id in seen_slots:
            raise ValueError(f"Each physical slot may appear only once: {slot_id}")
        seen_slots.add(slot_id)
        slot = slots.get(slot_id)
        module = modules.get(module_id)
        if slot is None:
            raise ValueError(f"Slot is not present on {hull['name']}: {slot_id}")
        if module is None:
            raise ValueError(f"Module is not in the active reference pack: {module_id}")
        if slot["slot_type"] not in module["slot_types"]:
            raise ValueError(f"{module['name']} cannot occupy {slot['label']}")
        if module["class"] > slot["size"]:
            raise ValueError(
                f"Class {module['class']} {module['name']} is too large for "
                f"class {slot['size']} {slot['label']}"
            )
        if module["category"] not in slot["allowed_categories"]:
            raise ValueError(f"{module['name']} is not legal in {slot['label']}")
        restrictions = module["hull_restrictions"]
        if restrictions and hull_id not in restrictions:
            raise ValueError(f"{module['name']} is restricted from {hull['name']}")
        if not outfitting_rules.compatible(module, hull, slot):
            raise ValueError(
                f"{module['name']} violates slot/hull rules for {slot['label']}."
            )
        blueprint_id = target.get("blueprint_id")
        grade = target.get("target_grade")
        effect_id = target.get("experimental_effect")
        target_state = str(target.get("target_state") or "engineered")
        if target_state not in {"stock", "engineered"}:
            raise ValueError(
                f"Unsupported target state for {module['name']}: {target_state}"
            )
        if target_state == "stock" and (blueprint_id or grade is not None or effect_id):
            raise ValueError(
                f"Stock {module['name']} cannot include engineering selections"
            )
        if target_state == "engineered" and not blueprint_id:
            raise ValueError(
                f"Engineered {module['name']} needs a compatible blueprint"
            )
        blueprint = None
        experimental = None
        if blueprint_id:
            blueprint = blueprints.get(str(blueprint_id))
            if blueprint is None:
                raise ValueError(
                    f"Blueprint is not in the active reference pack: {blueprint_id}"
                )
            gap = outfitting_rules.engineering_gap(module, blueprint)
            if gap:
                raise ValueError(gap)
            if module["category"] not in blueprint["module_categories"] or (
                module.get("blueprint_ids") is not None
                and blueprint_id not in module["blueprint_ids"]
            ):
                raise ValueError(
                    f"{blueprint['name']} is incompatible with {module['name']}"
                )
            if not isinstance(grade, int) or str(grade) not in blueprint["grades"]:
                raise ValueError(
                    f"Grade {grade} is unavailable for {blueprint['name']}"
                )
            experimental = (
                next(
                    (
                        row
                        for row in blueprint["experimentals"]
                        if row["id"] == effect_id
                    ),
                    None,
                )
                if effect_id
                else None
            )
            if effect_id and (
                experimental is None
                or (
                    module.get("experimental_ids") is not None
                    and effect_id not in module["experimental_ids"]
                )
            ):
                raise ValueError(
                    "Experimental effect is unavailable for "
                    f"{blueprint['name']}: {effect_id}"
                )
        elif grade is not None or effect_id:
            raise ValueError(
                f"{module['name']} needs a blueprint before grade or experimental"
            )
        normalized.append(
            {
                "slot": slot_id,
                "slot_label": slot["label"],
                "module_id": module_id,
                "module_label": module["name"],
                "module_class": module["class"],
                "module_rating": module["rating"],
                "module_category": module["category"],
                "module_stats": dict(module["stats"]),
                "target_state": target_state,
                "blueprint_id": blueprint_id,
                "blueprint_label": blueprint["name"] if blueprint else None,
                "target_grade": grade,
                "experimental_effect": effect_id,
                "engineering_effects": combined_effects(
                    blueprint, int(grade or 0), experimental
                )
                if blueprint
                else {},
                "numerical_effects_verified": (
                    str(grade) in blueprint.get("grade_effects", {})
                    and blueprint.get("numerical_data_complete", True)
                    and (
                        experimental is None
                        or bool(experimental.get("attribute_effects"))
                        or bool(experimental.get("special"))
                        or bool(experimental.get("effects"))
                    )
                    if blueprint
                    else True
                ),
                "effect_rule": (blueprint.get("effect_rule") if blueprint else None),
                "compatibility_evidence": "active_reference_pack",
            }
        )
    for target in normalized:
        module = modules[target["module_id"]]
        blueprint = blueprints.get(str(target.get("blueprint_id")))
        experimental = next(
            (
                e
                for e in (blueprint or {}).get("experimentals", [])
                if e["id"] == target.get("experimental_effect")
            ),
            None,
        )
        target.update(
            outfitting_rules.target_metadata(
                module,
                blueprint,
                target.get("target_grade"),
                experimental,
                catalog.get("attribute_definitions", {}),
            )
        )
    check = outfitting_rules.configuration_check(catalog, hull_id, {}, normalized)
    capacities = [
        target
        for target in normalized
        if target.get("module_category") == "power_plant"
    ]
    if capacities:

        def stat(target: JsonDict, field: str, source_field: str) -> float | None:
            if target.get("target_state") == "engineered" and not target.get(
                "numerical_effects_verified"
            ):
                return None
            attrs = outfitting_rules.attribute_values(target)
            value = attrs.get(source_field, target.get("module_stats", {}).get(field))
            return float(value) if isinstance(value, (int, float)) else None

        capacity = stat(capacities[0], "power_capacity", "pwrcap")
        boost = sum(
            outfitting_rules.attribute_values(target).get("pwrbst", 0)
            for target in normalized
        )
        if capacity is not None:
            capacity *= 1 + boost / 100
        draws = [stat(target, "power_draw", "pwrdraw") for target in normalized]
        if (
            capacity is not None
            and all(value is not None for value in draws)
            and sum(value or 0 for value in draws) > capacity
        ):
            check["errors"].append(
                "The planned power plant cannot supply all fitted enabled modules."
            )
    if check["errors"]:
        raise ValueError(" ".join(check["errors"]))
    if not normalized:
        raise ValueError("Choose at least one module")
    return normalized


def recipe_index(catalog: JsonDict | None) -> dict[tuple[str, int], JsonDict]:
    rows: dict[tuple[str, int], JsonDict] = {}
    if catalog is None:
        return rows
    for blueprint in catalog["blueprints"]:
        for grade, materials in blueprint["grades"].items():
            rows[(blueprint["id"].casefold(), int(grade))] = {
                "blueprint_id": blueprint["id"],
                "blueprint_label": blueprint["name"],
                "grade": int(grade),
                "materials": materials,
                "source_chain": [
                    {
                        "source": catalog["provenance"]["source_name"],
                        "truth_class": "commander_supplied_reference",
                        "catalog_id": catalog["catalog_id"],
                        "catalog_version": catalog["version"],
                    }
                ],
            }
    return rows


def experimental_cost(
    catalog: JsonDict | None, blueprint_id: str, effect_id: str
) -> list[JsonDict] | None:
    if catalog is None:
        return None
    blueprint = next(
        (
            row
            for row in catalog["blueprints"]
            if row["id"].casefold() == blueprint_id.casefold()
        ),
        None,
    )
    if blueprint is None:
        return None
    effect = next(
        (row for row in blueprint["experimentals"] if row["id"] == effect_id), None
    )
    return effect.get("materials") if effect else None
