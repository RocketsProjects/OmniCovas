"""Acquisition queue and single-step Material Trader feasibility (Materials 03A).

Pure derivation over the portfolio's own allocation output; nothing here is
stored and nothing changes observed inventory.  Two rules govern it:

* Shortages are the portfolio's.  The queue re-presents each build's ``required``,
  ``reserved`` and ``deficit`` and sums them across builds without re-allocating,
  so the same reserved unit is never counted twice.  Observed stock is one shared
  pool, reported once.
* Trade proposals exist only for exchange rules a Commander-supplied reference
  pack explicitly declares and pins to the build.  OmniCOVAS ships no exchange
  table, derives none from Journal ``MaterialTrade`` observations and assumes
  none.  Without a declared rule there is an explicit "unavailable" state.
  Only stock left unreserved by *every* active build may be offered as a trade
  source, one rule at a time; a proposal is advice, never an executed trade.
"""

from __future__ import annotations

from typing import Any

from omnicovas.features import material_trader_rules

JsonDict = dict[str, Any]

VERSION = "acquisition-queue-v1"
OBSERVED_CATEGORIES = {"raw", "manufactured", "encoded"}

# What a verified, reusable exchange table still needs before Materials 03B can
# calculate trades without a Commander-supplied pack.  Listed in the payload so
# the UI can state it, and recorded in Source Verification Register FU-022.
MISSING_FOR_BUNDLED_RULES = (
    "A complete, version-pinned Material Trader exchange table for every "
    "category and grade, from a source with a recorded redistribution basis "
    "(Source Verification Register FU-022 / ER-01).",
    "Verified conversion restrictions: which categories and grades may be "
    "exchanged for which, and the rounding rule for partial lots.",
    "Independently acquired evidence for that table. Journal MaterialTrade "
    "events show individual trades, not the rules, and are not used to infer "
    "them.",
)


def allocate(
    order: list[tuple[str, dict[str, int]]],
    held: dict[str, int],
) -> dict[str, dict[str, tuple[int, int]]]:
    """Replay the portfolio's allocation: one pool, builds in priority order.

    Each build takes ``min(held, required)`` of every material in turn, exactly
    as ``engineering_progression.portfolio`` does for a known inventory.
    Returns ``{build_id: {material: (reserved, deficit)}}``.
    """
    pool = dict(held)
    result: dict[str, dict[str, tuple[int, int]]] = {}
    for build_id, required in order:
        rows: dict[str, tuple[int, int]] = {}
        for material, needed in required.items():
            have = pool.get(material, 0)
            reserved = min(have, needed)
            pool[material] = have - reserved
            rows[material] = (reserved, max(needed - have, 0))
        result[build_id] = rows
    return result


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _categories(inventory: JsonDict) -> dict[str, str]:
    return {
        str(row.get("material_id")): str(row.get("category") or "unknown")
        for row in inventory.get("materials", [])
        if isinstance(row, dict)
    }


def _queue(
    results: list[JsonDict],
    pool: dict[str, int],
    inventory_known: bool,
    categories: dict[str, str],
) -> list[JsonDict]:
    rows: dict[str, JsonDict] = {}
    for build in results:
        for allocation in build.get("materials", []):
            material = str(allocation["material_id"])
            row = rows.setdefault(
                material,
                {
                    "material_id": material,
                    "display_name": allocation.get("display_name") or material,
                    "category": categories.get(material, "unknown"),
                    "builds": [],
                },
            )
            row["builds"].append(
                {
                    "build_plan_id": build["build_plan_id"],
                    "title": build["title"],
                    "priority": build.get("priority", "unsorted"),
                    "required": _int(allocation.get("required")),
                    "reserved": _int(allocation.get("reserved")),
                    "deficit": _int(allocation.get("deficit")),
                }
            )
    queue: list[JsonDict] = []
    for material, row in rows.items():
        entries = row["builds"]
        known = inventory_known and all(
            entry["reserved"] is not None and entry["deficit"] is not None
            for entry in entries
        )
        required = sum(entry["required"] or 0 for entry in entries)
        reserved = sum(entry["reserved"] or 0 for entry in entries) if known else None
        deficit = sum(entry["deficit"] or 0 for entry in entries) if known else None
        observed = pool.get(material, 0) if inventory_known else None
        queue.append(
            {
                **row,
                "required": required,
                "observed": observed,
                "reserved": reserved,
                "deficit": deficit,
                "remaining": (
                    observed - reserved
                    if observed is not None and reserved is not None
                    else None
                ),
                "state": (
                    "unknown"
                    if not known
                    else ("missing" if (deficit or 0) > 0 else "covered")
                ),
            }
        )
    queue.sort(
        key=lambda item: (
            {"missing": 0, "unknown": 1, "covered": 2}[item["state"]],
            -(item["deficit"] or 0),
            str(item["display_name"]).casefold(),
        )
    )
    return queue


def _rule_set_detail(
    label: str, meta: JsonDict | None, verifications: list[str]
) -> JsonDict:
    """What the pack says about its own rules (nothing, for a legacy pack)."""
    if not meta:
        return {
            "label": label,
            "id": None,
            "version": None,
            "game_version": None,
            "verification": material_trader_rules.weakest(
                verifications or ["declared_unverified"]
            ),
            "completeness": None,
            "evidence": [],
            "limitations": [],
            "states_provenance": False,
        }
    return {
        "label": label,
        "id": meta["id"],
        "version": meta["version"],
        "game_version": meta.get("game_version"),
        "verification": material_trader_rules.weakest(
            [meta["verification"], *verifications]
        ),
        "completeness": meta["completeness"],
        "evidence": [
            {"id": e["id"], "kind": e["kind"], "name": e["name"]}
            for e in meta["evidence"]
        ],
        "limitations": list(meta["limitations"]),
        "states_provenance": True,
    }


def _surplus(queue: list[JsonDict], pool: dict[str, int]) -> dict[str, int]:
    """Unreserved stock per material: observed minus every build's reservation."""
    reserved = {row["material_id"]: row["reserved"] or 0 for row in queue}
    return {
        material: count - reserved.get(material, 0)
        for material, count in pool.items()
        if count - reserved.get(material, 0) > 0
    }


def _proposals(
    results: list[JsonDict],
    pool: dict[str, int],
    surplus: dict[str, int],
    categories: dict[str, str],
    rules_by_build: dict[str, tuple[str, list[JsonDict]]],
) -> list[JsonDict]:
    order = [
        (
            build["build_plan_id"],
            {
                str(row["material_id"]): int(row["required"])
                for row in build.get("materials", [])
                if _int(row.get("required")) is not None
            },
        )
        for build in results
    ]
    titles = {build["build_plan_id"]: build["title"] for build in results}
    before = allocate(order, pool)
    proposals: list[JsonDict] = []

    scopes: list[tuple[str, list[str]]] = []
    ids = [build["build_plan_id"] for build in results]
    if len(ids) > 1:
        scopes.append(("all", ids))
    scopes.extend((build_id, [build_id]) for build_id in ids)

    for scope, members in scopes:
        scope_deficit: dict[str, int] = {}
        for build_id in members:
            for material, (_, deficit) in before[build_id].items():
                if deficit:
                    scope_deficit[material] = scope_deficit.get(material, 0) + deficit
        # Declared rules from the pack versions these builds are pinned to.
        declared: dict[tuple[str, str, int, int], JsonDict] = {}
        for build_id in members:
            label, rules = rules_by_build.get(build_id, ("", []))
            for rule in rules:
                key = (
                    str(rule["from_key"]),
                    str(rule["to_key"]),
                    int(rule["pay"]),
                    int(rule["receive"]),
                )
                entry = declared.setdefault(key, {**rule, "rule_sets": []})
                if label not in entry["rule_sets"]:
                    entry["rule_sets"].append(label)
                # Several rule sets stating the same exchange: only as strong as
                # the weakest of them.
                entry["verification"] = material_trader_rules.weakest(
                    [
                        str(entry.get("verification") or "declared_unverified"),
                        str(rule.get("verification") or "declared_unverified"),
                    ]
                )
        for (source, target, pay, receive), rule in sorted(declared.items()):
            wanted = scope_deficit.get(target, 0)
            if not wanted or source == target:
                continue
            result = material_trader_rules.evaluate_exchange(
                rule,
                wanted,
                surplus.get(source, 0),
                (categories.get(source, "unknown"), categories.get(target, "unknown")),
            )
            feasible = bool(result["feasible"])
            reason = result["reason"]
            lots_wanted = int(result["lots_wanted"])
            lots = int(result["lots"])
            pay_total = int(result["pay_total"])
            receive_total = int(result["receive_total"])
            after_pool = dict(pool)
            after_pool[source] = after_pool.get(source, 0) - pay_total
            after_pool[target] = after_pool.get(target, 0) + receive_total
            after = allocate(order, after_pool)
            deficit_after = sum(after[b].get(target, (0, 0))[1] for b in members)
            outcome = (
                "no_change"
                if not feasible or deficit_after >= wanted
                else ("resolves_shortage" if deficit_after == 0 else "reduces_shortage")
            )
            proposals.append(
                {
                    "proposal_id": f"{scope}:{rule['rule_id']}",
                    "scope": scope,
                    "rule_id": rule["rule_id"],
                    "rule_sets": rule["rule_sets"],
                    "category": rule.get("category"),
                    "notes": rule.get("notes"),
                    "from_material_id": source,
                    "from_display_name": rule["from_display_name"],
                    "from_category": categories.get(source, "unknown"),
                    "to_material_id": target,
                    "to_display_name": rule["to_display_name"],
                    "to_category": categories.get(target, "unknown"),
                    "pay": pay,
                    "receive": receive,
                    "lots": lots if feasible else 0,
                    "pay_total": pay_total,
                    "receive_total": receive_total,
                    "pay_needed": lots_wanted * pay,
                    "feasible": feasible,
                    "reason": reason,
                    "outcome": outcome,
                    "shortage_before": wanted,
                    "shortage_after": deficit_after if feasible else wanted,
                    "source_observed": pool.get(source, 0),
                    "source_unreserved_before": surplus.get(source, 0),
                    "source_unreserved_after": surplus.get(source, 0) - pay_total,
                    "builds": [
                        {
                            "build_plan_id": build_id,
                            "title": titles[build_id],
                            "deficit_before": before[build_id].get(target, (0, 0))[1],
                            "deficit_after": after[build_id].get(target, (0, 0))[1],
                        }
                        for build_id in members
                    ],
                    "executed": False,
                    "truth_class": "suggested_unexecuted",
                    # The exchange rate is whatever the installed pack states; it
                    # is never "verified" here. No rule in OmniCOVAS carries any
                    # status other than this one.
                    "rule_status": material_trader_rules.rule_status(
                        rule.get("verification")
                    ),
                    "basis": _basis(rule["rule_sets"], rule.get("verification")),
                }
            )
    proposals.sort(
        key=lambda item: (
            item["scope"] != "all",
            not item["feasible"],
            {"resolves_shortage": 0, "reduces_shortage": 1, "no_change": 2}[
                item["outcome"]
            ],
            str(item["to_display_name"]).casefold(),
            item["rule_id"],
        )
    )
    return proposals


def _basis(rule_sets: list[str], verification: str | None) -> str:
    """Provenance sentence for one proposal; never stronger than the pack's record."""
    source = "According to installed reference pack " + ", ".join(rule_sets) + "."
    if verification == "independently_verified":
        return (
            source + " The pack records independent verification of its rules; "
            "OmniCOVAS has not re-checked them against the game."
        )
    if verification == "community_reported":
        return (
            source + " The pack cites community references for its rules. "
            "OmniCOVAS has not independently verified this exchange against the game."
        )
    return (
        source + " OmniCOVAS has not independently verified this exchange "
        "against the game."
    )


def build_acquisition(
    results: list[JsonDict],
    pool: dict[str, int],
    inventory: JsonDict,
    rules_by_build: dict[str, tuple[str, list[JsonDict]]],
    rule_sets: dict[str, JsonDict | None] | None = None,
    documented_categories: dict[str, str] | None = None,
) -> JsonDict:
    """Derive the acquisition queue and trade state from the portfolio's results.

    ``documented_categories`` (GKI-05) groups queue rows for materials the
    inventory has never recorded; trade feasibility keeps the inventory's own.
    """
    inventory_known = inventory.get("state") == "verified_local"
    categories = _categories(inventory)
    observed = {k: v for k, v in categories.items() if v != "unknown"}
    queue = _queue(
        results,
        pool,
        inventory_known,
        {**(documented_categories or {}), **observed},
    )
    surplus = _surplus(queue, pool)
    rule_total = sum(len(rules) for _, rules in rules_by_build.values())
    labels = sorted({label for label, rules in rules_by_build.values() if rules})
    declared_sets = rule_sets or {}
    rule_verifications = {
        label: [
            str(rule.get("verification") or "declared_unverified") for rule in rules
        ]
        for label, rules in rules_by_build.values()
        if rules
    }
    details = [
        _rule_set_detail(label, declared_sets.get(label), rule_verifications[label])
        for label in labels
    ]
    # Only as strong as the weakest rule actually in play, whatever a set claims.
    all_verifications = [v for values in rule_verifications.values() for v in values]
    overall = (
        material_trader_rules.rule_status(
            material_trader_rules.weakest(all_verifications)
        )
        if all_verifications
        else None
    )
    proposals: list[JsonDict] = []
    if not inventory_known:
        trading_state = "inventory_unknown"
    elif not rule_total:
        trading_state = "no_rules"
    else:
        trading_state = "rules_declared"
        proposals = _proposals(results, pool, surplus, categories, rules_by_build)

    declared_by_target: dict[str, int] = {}
    for _, rules in rules_by_build.values():
        for rule in rules:
            target = str(rule["to_key"])
            declared_by_target[target] = declared_by_target.get(target, 0) + 1
    single_scope = results[0]["build_plan_id"] if len(results) == 1 else "all"
    for row in queue:
        feasible = [
            p
            for p in proposals
            if p["scope"] == single_scope
            and p["to_material_id"] == row["material_id"]
            and p["feasible"]
        ]
        row["trade"] = {
            "state": (
                "unavailable"
                if trading_state in {"no_rules", "inventory_unknown"}
                else (
                    "declared"
                    if declared_by_target.get(row["material_id"])
                    else "none_declared"
                )
            ),
            "declared_rules": declared_by_target.get(row["material_id"], 0),
            "feasible_proposals": len(feasible),
        }
    names = {
        str(row["material_id"]): row["display_name"]
        for build in results
        for row in build.get("materials", [])
    }
    names.update(
        {
            str(row.get("material_id")): row.get("display_name")
            for row in inventory.get("materials", [])
            if isinstance(row, dict)
        }
    )
    return {
        "version": VERSION,
        "inventory_state": inventory.get("state", "unknown"),
        "materials": queue,
        "unreserved_stock": [
            {
                "material_id": material,
                "display_name": names.get(material, material),
                "category": categories.get(material, "unknown"),
                "observed": pool.get(material, 0),
                "unreserved": amount,
            }
            for material, amount in sorted(
                surplus.items(),
                key=lambda item: (-item[1], names.get(item[0], item[0]).casefold()),
            )
        ],
        "trading": {
            "state": trading_state,
            "rule_sets": labels,
            "rule_set_details": details,
            "declared_rule_count": rule_total,
            "rule_status": overall if rule_total else None,
            "proposals": proposals,
            "missing_for_bundled_rules": list(MISSING_FOR_BUNDLED_RULES),
            "caveats": [
                "Proposals are advice computed from rules a reference pack "
                "declares. They are not Journal transactions and change no "
                "observed stock.",
                "Only stock left unreserved by every active build is offered as "
                "a trade source, and each proposal is a single exchange.",
            ],
        },
    }
