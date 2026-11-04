"""Built-in Material Trader: exchange rules, quotes, trade simulation and planning.

The rules are the community-documented game mechanics adopted by Commander
authorisation (see ``omnicovas/data/material_trader_rules_v1.json`` and
docs/material-trader-20261029.md), structured and implemented here as original
OmniCOVAS logic:

* three traders (raw, manufactured, encoded); a trade never crosses traders;
* within a trader, materials sit in groups and grades.  The cost of one received
  unit, in units of the material given, is ``6`` per grade up, ``1/3`` per grade
  down, and ``6`` once if the groups differ, multiplied together;
* a trade is a whole number of lots of the reduced ratio ``pay:receive``;
* per-material storage caps by grade.

Arithmetic is exact (``fractions.Fraction`` and integers).  Nothing here touches
the game or the Journal: a quote, a basket and a plan are hypothetical, and the
observed inventory is never changed.  Stock reserved for planned builds is never
offered as a trade source.
"""

from __future__ import annotations

import json
import math
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

JsonDict = dict[str, Any]

SEED_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "material_trader_rules_v1.json"
)
SCHEMA = "omnicovas-material-trader-v1"
TYPES = ("raw", "manufactured", "encoded")
PLANNER_VERSION = "material-trader-planner-v1"
MAX_PLAN_TRADES = 60
OBJECTIVE = (
    "Shortages are taken in build priority order, largest first. Each step picks the "
    "single exchange, or two-step chain when no direct exchange fits storage limits, "
    "that loses the least material value, valuing one unit of grade g at 6^(g-1) "
    "units of grade 1 of its own group (the cost of trading it up). That prefers "
    "trading abundant lower grades up within a group, then trading down, then "
    "crossing groups. Only stock no active build has reserved is spent, and no trade "
    "may overfill storage. The plan is greedy and bounded; it is not proven optimal."
)


# --- rules data ---------------------------------------------------------------------


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def validate(raw: Any) -> JsonDict:
    """Validate the bundled rules and return them with a material index."""
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise ValueError("Unsupported Material Trader rules schema")
    distribution = raw.get("distribution") or {}
    if distribution.get("status") != "development_only" or any(
        distribution.get(c) != "excluded"
        for c in ("public_repository", "preview_repository", "release_build")
    ):
        raise ValueError("Material Trader rules must declare development_only")
    exchange = raw.get("exchange") or {}
    factors = {
        key: exchange.get(key)
        for key in ("up_one_grade_cost", "down_one_grade_yield", "group_change_cost")
    }
    if any(
        isinstance(v, bool) or not isinstance(v, int) or v < 2 for v in factors.values()
    ):
        raise ValueError("Exchange factors must be integers of at least 2")
    if exchange.get("lot") != "reduced_ratio_whole_lots":
        raise ValueError("Unsupported lot rule")
    caps_raw = raw.get("storage_caps_by_grade") or {}
    caps = {int(grade): cap for grade, cap in caps_raw.items()}
    if sorted(caps) != [1, 2, 3, 4, 5] or any(
        not isinstance(cap, int) or cap < 1 for cap in caps.values()
    ):
        raise ValueError("Storage caps must cover grades 1 to 5")

    materials: dict[str, JsonDict] = {}
    groups: list[JsonDict] = []
    traders = raw.get("traders") or []
    if [t.get("type") for t in traders] != list(TYPES):
        raise ValueError(
            "Exactly the raw, manufactured and encoded traders are required"
        )
    for trader in traders:
        trader_type = trader["type"]
        for group in trader.get("groups") or []:
            group_id = _text(group.get("id"), "group id")
            members = group.get("materials") or []
            if not 1 <= len(members) <= 5:
                raise ValueError(f"group {group_id} must hold one to five grades")
            ids = []
            for grade, entry in enumerate(members, start=1):
                if not isinstance(entry, list) or len(entry) != 2:
                    raise ValueError(f"group {group_id} entries are [id, name]")
                material_id = _text(entry[0], "material id").casefold()
                if material_id in materials:
                    raise ValueError(f"Duplicate material {material_id}")
                materials[material_id] = {
                    "id": material_id,
                    "name": _text(entry[1], "material name"),
                    "type": trader_type,
                    "group": group_id,
                    "group_name": _text(group.get("name"), "group name"),
                    "grade": grade,
                    "cap": caps[grade],
                }
                ids.append(material_id)
            groups.append(
                {
                    "id": group_id,
                    "type": trader_type,
                    "name": group["name"],
                    "materials": ids,
                }
            )
    return {
        "state": "available",
        "schema": SCHEMA,
        "version": _text(raw.get("version"), "version"),
        "reference": raw.get("reference") or {},
        "distribution": {
            "status": "development_only",
            "decision_record": distribution.get("decision_record"),
        },
        "exchange": {**factors, "lot": "reduced_ratio_whole_lots"},
        "storage_caps_by_grade": {str(k): v for k, v in sorted(caps.items())},
        "groups": groups,
        "materials": materials,
    }


@lru_cache(maxsize=1)
def _bundled() -> str:
    return json.dumps(validate(json.loads(SEED_PATH.read_text(encoding="utf-8"))))


def rules() -> JsonDict:
    loaded: JsonDict = json.loads(_bundled())
    return loaded


def safe_rules() -> JsonDict:
    """``rules`` that reports a missing or invalid file instead of failing."""
    try:
        return rules()
    except FileNotFoundError:
        return {"state": "unavailable", "reason": "not_included", "materials": {}}
    except (OSError, ValueError):
        return {"state": "unavailable", "reason": "invalid", "materials": {}}


# --- exchange arithmetic -----------------------------------------------------------


def cost_per_unit(data: JsonDict, give: str, take: str) -> Fraction | None:
    """Units of ``give`` per unit of ``take``, or None when no trade exists."""
    materials = data["materials"]
    source, target = materials.get(give), materials.get(take)
    if source is None or target is None or give == take:
        return None
    if source["type"] != target["type"]:
        return None
    factors = data["exchange"]
    steps = int(target["grade"]) - int(source["grade"])
    up = int(factors["up_one_grade_cost"])
    down = int(factors["down_one_grade_yield"])
    cost = Fraction(up**steps, 1) if steps >= 0 else Fraction(1, down ** (-steps))
    if source["group"] != target["group"]:
        cost *= int(factors["group_change_cost"])
    return cost


def lot(data: JsonDict, give: str, take: str) -> tuple[int, int] | None:
    """The smallest whole exchange: ``(pay, receive)``."""
    cost = cost_per_unit(data, give, take)
    if cost is None:
        return None
    return cost.numerator, cost.denominator


def _why_not(data: JsonDict, give: str, take: str) -> str:
    materials = data["materials"]
    if give not in materials or take not in materials:
        return "not_tradeable"
    if give == take:
        return "same_material"
    return "different_trader"


def quote(
    data: JsonDict,
    give: str,
    take: str,
    *,
    receive: int | None = None,
    spend: int | None = None,
    owned: dict[str, int] | None,
    protected: dict[str, int],
) -> JsonDict:
    """Exact cost and feasibility of one exchange against an inventory.

    ``owned`` is None when the stock is unknown: the arithmetic is still shown, but
    nothing is called affordable.  ``protected`` is stock reserved for builds and is
    never spent.  ``receive`` asks for at least that many (rounded up to whole lots);
    ``spend`` offers at most that many (rounded down).
    """
    pair = lot(data, give, take)
    if pair is None:
        return {"possible": False, "reason": _why_not(data, give, take)}
    pay, get = pair
    source, target = data["materials"][give], data["materials"][take]
    if receive is not None:
        lots = math.ceil(max(receive, 0) / get)
    elif spend is not None:
        lots = max(spend, 0) // pay
    else:
        lots = 1
    result: JsonDict = {
        "give": give,
        "take": take,
        "pay": pay,
        "receive": get,
        "rate": f"{pay}:{get}",
        "lots": lots,
        "pay_total": lots * pay,
        "receive_total": lots * get,
    }
    reasons = []
    if pay > source["cap"]:
        reasons.append("lot_exceeds_source_storage")
    if lots < 1:
        reasons.append("below_one_lot")
    if owned is None:
        result.update(
            possible=None,
            reason="inventory_unknown",
            reasons=reasons or ["inventory_unknown"],
            max_lots=None,
        )
        return result
    have_source = owned.get(give, 0)
    have_target = owned.get(take, 0)
    spendable = max(have_source - protected.get(give, 0), 0)
    room = max(target["cap"] - have_target, 0)
    max_lots = min(spendable // pay, room // get)
    if lots * pay > spendable:
        reasons.append(
            "reserved_for_builds" if lots * pay <= have_source else "insufficient_stock"
        )
    if lots * get > room:
        reasons.append("destination_full")
    result.update(
        possible=not reasons,
        reason=reasons[0] if reasons else None,
        reasons=reasons,
        max_lots=max_lots,
        spendable=spendable,
        source_before=have_source,
        source_after=have_source - lots * pay,
        target_before=have_target,
        target_after=have_target + lots * get,
        target_cap=target["cap"],
    )
    return result


def simulate(
    data: JsonDict,
    trades: list[JsonDict],
    owned: dict[str, int],
    protected: dict[str, int],
) -> JsonDict:
    """Apply proposed trades in order to a copy of the inventory.

    Each trade is ``{"give", "take", "lots"}``.  Every step is checked against the
    state left by the previous ones, so a later trade may spend what an earlier one
    received.  Nothing is applied after the first invalid step.
    """
    state = dict(owned)
    steps = []
    valid = True
    for index, trade in enumerate(trades):
        pair = lot(data, str(trade["give"]), str(trade["take"]))
        lots = int(trade.get("lots", 0))
        if pair is None:
            steps.append(
                {
                    "index": index,
                    "valid": False,
                    "reason": _why_not(data, str(trade["give"]), str(trade["take"])),
                }
            )
            valid = False
            break
        check = quote(
            data,
            str(trade["give"]),
            str(trade["take"]),
            spend=lots * pair[0],
            owned=state,
            protected=protected,
        )
        steps.append({"index": index, **check, "valid": bool(check["possible"])})
        if not check["possible"]:
            valid = False
            break
        state[check["give"]] = check["source_after"]
        state[check["take"]] = check["target_after"]
    changes = {
        key: state.get(key, 0) - owned.get(key, 0)
        for key in set(state) | set(owned)
        if state.get(key, 0) != owned.get(key, 0)
    }
    return {"valid": valid, "steps": steps, "after": state, "changes": changes}


# --- planning ----------------------------------------------------------------------


def _value(material: JsonDict) -> int:
    return int(6 ** (material["grade"] - 1))


def _allocate(
    order: list[tuple[str, dict[str, int]]], held: dict[str, int]
) -> dict[str, dict[str, tuple[int, int]]]:
    # The portfolio's own allocation semantics (shared replay in material_acquisition).
    from omnicovas.features.material_acquisition import allocate

    return allocate(order, held)


def _reserved_totals(alloc: dict[str, dict[str, tuple[int, int]]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for rows in alloc.values():
        for material, (reserved, _) in rows.items():
            totals[material] = totals.get(material, 0) + reserved
    return totals


def _direct_routes(
    data: JsonDict,
    target: str,
    need: int,
    state: dict[str, int],
    reserved: dict[str, int],
) -> list[JsonDict]:
    materials = data["materials"]
    take = materials[target]
    routes = []
    room = take["cap"] - state.get(target, 0)
    for source_id, source in materials.items():
        if source_id == target or source["type"] != take["type"]:
            continue
        surplus = state.get(source_id, 0) - reserved.get(source_id, 0)
        pair = lot(data, source_id, target)
        if surplus <= 0 or pair is None:
            continue
        pay, get = pair
        if pay > source["cap"]:
            continue  # a lot this size can never be held; see two-step chains
        lots = min(math.ceil(need / get), surplus // pay, room // get)
        if lots < 1:
            continue
        loss = Fraction(_value(source) * pay, get) - _value(take)
        routes.append(
            {
                "kind": "direct",
                "legs": [(source_id, target, lots, pay, get)],
                "loss_per_unit": loss,
                "same_group": source["group"] == take["group"],
                "surplus": surplus,
                "received": lots * get,
            }
        )
    return routes


def _chain_routes(
    data: JsonDict,
    target: str,
    need: int,
    state: dict[str, int],
    reserved: dict[str, int],
) -> list[JsonDict]:
    """Two-step routes through an intermediate material, for lots too large to hold."""
    materials = data["materials"]
    take = materials[target]
    room_target = take["cap"] - state.get(target, 0)
    routes = []
    for source_id, source in materials.items():
        if source["type"] != take["type"] or source_id == target:
            continue
        surplus = state.get(source_id, 0) - reserved.get(source_id, 0)
        if surplus <= 0:
            continue
        for middle_id, middle in materials.items():
            if middle["type"] != take["type"] or middle_id in (source_id, target):
                continue
            first, second = (
                lot(data, source_id, middle_id),
                lot(data, middle_id, target),
            )
            if first is None or second is None:
                continue
            (p1, r1), (p2, r2) = first, second
            if p1 > source["cap"] or p2 > middle["cap"]:
                continue
            middle_surplus = max(
                state.get(middle_id, 0) - reserved.get(middle_id, 0), 0
            )
            middle_room = middle["cap"] - state.get(middle_id, 0)
            best = None
            for lots2 in range(min(math.ceil(need / r2), room_target // r2), 0, -1):
                missing = max(lots2 * p2 - middle_surplus, 0)
                lots1 = math.ceil(missing / r1) if missing else 0
                if lots1 * p1 <= surplus and lots1 * r1 <= middle_room:
                    best = (lots1, lots2)
                    break
            if best is None or best[0] == 0:
                continue
            lots1, lots2 = best
            loss = Fraction(_value(source) * p1 * p2, r1 * r2) - _value(take)
            routes.append(
                {
                    "kind": "chain",
                    "legs": [
                        (source_id, middle_id, lots1, p1, r1),
                        (middle_id, target, lots2, p2, r2),
                    ],
                    "loss_per_unit": loss,
                    "same_group": source["group"] == take["group"],
                    "surplus": surplus,
                    "received": lots2 * r2,
                }
            )
    return routes


def _route_key(route: JsonDict) -> tuple[Any, ...]:
    return (
        route["loss_per_unit"],
        not route["same_group"],
        -route["received"],
        -route["surplus"],
        route["legs"][0][0],
    )


def _reason(data: JsonDict, give: str, take: str) -> str:
    source, target = data["materials"][give], data["materials"][take]
    steps = target["grade"] - source["grade"]
    move = (
        "same grade"
        if steps == 0
        else f"up {steps} grade{'s' if steps > 1 else ''}"
        if steps > 0
        else f"down {-steps} grade{'s' if steps < -1 else ''}"
    )
    where = "same group" if source["group"] == target["group"] else "another group"
    return f"{where}, {move}"


def plan(
    data: JsonDict,
    results: list[JsonDict],
    pool: dict[str, int],
    scope: list[str],
    *,
    max_trades: int = MAX_PLAN_TRADES,
) -> JsonDict:
    """Plan trades that reduce the shortages of the builds in ``scope``.

    ``results`` are the portfolio's active builds in priority order and ``pool`` the
    observed stock.  Reservations are recomputed with the portfolio's allocation
    after every simulated trade, so stock reserved for any build, in scope or not,
    is never spent, and received units reach builds in priority order.
    """
    materials = data["materials"]
    order = [
        (
            str(build["build_plan_id"]),
            {
                str(row["material_id"]): int(row["required"])
                for row in build.get("materials", [])
                if isinstance(row.get("required"), int)
            },
        )
        for build in results
    ]
    titles = {str(b["build_plan_id"]): b["title"] for b in results}
    names = {
        str(row["material_id"]): str(row.get("display_name") or row["material_id"])
        for build in results
        for row in build.get("materials", [])
    }
    members = [build_id for build_id, _ in order if build_id in scope]
    state = dict(pool)
    before = _allocate(order, state)
    trades: list[JsonDict] = []
    blocked: dict[str, str] = {}
    truncated = False
    while True:
        if len(trades) >= max_trades:
            truncated = True
            break
        alloc = _allocate(order, state)
        reserved = _reserved_totals(alloc)
        candidates = []
        for position, (build_id, _) in enumerate(order):
            if build_id not in members:
                continue
            for material_id, (_, deficit) in alloc[build_id].items():
                if deficit <= 0 or material_id in blocked:
                    continue
                if material_id not in materials:
                    blocked[material_id] = "not_tradeable"
                    continue
                # Received units go to builds in priority order, so a build is only
                # served once every earlier build's shortage of this material is.
                need = sum(
                    alloc[order[j][0]].get(material_id, (0, 0))[1]
                    for j in range(position + 1)
                )
                candidates.append((position, -deficit, material_id, need, build_id))
        candidates.sort()
        applied = False
        for _, _, material_id, need, build_id in candidates:
            if material_id in blocked:
                continue
            routes = _direct_routes(data, material_id, need, state, reserved)
            if not routes:
                routes = _chain_routes(data, material_id, need, state, reserved)
            if not routes:
                take = materials[material_id]
                blocked[material_id] = (
                    "destination_full"
                    if state.get(material_id, 0) >= take["cap"]
                    else "no_unreserved_source"
                )
                continue
            routes.sort(key=_route_key)
            chosen, others = routes[0], routes[1:4]
            for give, take_id, lots, pay, get in chosen["legs"]:
                trades.append(
                    {
                        "step": len(trades) + 1,
                        "give": give,
                        "give_name": materials[give]["name"],
                        "take": take_id,
                        "take_name": materials[take_id]["name"],
                        "type": materials[give]["type"],
                        "pay": pay,
                        "receive": get,
                        "lots": lots,
                        "pay_total": lots * pay,
                        "receive_total": lots * get,
                        "source_before": state.get(give, 0),
                        "source_after": state.get(give, 0) - lots * pay,
                        "target_before": state.get(take_id, 0),
                        "target_after": state.get(take_id, 0) + lots * get,
                        "for_build": build_id,
                        "for_build_title": titles[build_id],
                        "for_material": material_id,
                        "for_material_name": materials[material_id]["name"],
                        "chain": chosen["kind"] == "chain",
                        "why": _reason(data, give, take_id),
                        "alternatives": [
                            {
                                "give": route["legs"][0][0],
                                "give_name": materials[route["legs"][0][0]]["name"],
                                "via": route["legs"][0][1]
                                if route["kind"] == "chain"
                                else None,
                                "rate": f"{route['legs'][-1][3]}:{route['legs'][-1][4]}"
                                if route["kind"] == "direct"
                                else None,
                                "received": route["received"],
                                "why": _reason(data, route["legs"][0][0], material_id),
                            }
                            for route in others
                        ],
                    }
                )
                state[give] = state.get(give, 0) - lots * pay
                state[take_id] = state.get(take_id, 0) + lots * get
            applied = True
            break
        if not applied:
            break

    after = _allocate(order, state)
    remaining: dict[str, JsonDict] = {}
    for build_id in members:
        for material_id, (_, deficit) in after[build_id].items():
            if deficit <= 0:
                continue
            row = remaining.setdefault(
                material_id,
                {
                    "material_id": material_id,
                    "name": materials.get(material_id, {}).get(
                        "name", names.get(material_id, material_id)
                    ),
                    "collect": 0,
                    "before": 0,
                    "reason": blocked.get(material_id, "no_unreserved_source"),
                },
            )
            row["collect"] += deficit
    for build_id in members:
        for material_id, (_, deficit) in before[build_id].items():
            if material_id in remaining:
                remaining[material_id]["before"] += deficit
    shortage_before = sum(d for b in members for _, (_, d) in before[b].items())
    shortage_after = sum(r["collect"] for r in remaining.values())
    verified = verify(data, trades, pool, order)
    return {
        "scope": scope,
        "planner": PLANNER_VERSION,
        "objective": OBJECTIVE,
        "trades": trades,
        "shortage_before": shortage_before,
        "shortage_after": shortage_after,
        "resolved_by_trades": shortage_before - shortage_after,
        "builds": [
            {
                "build_plan_id": build_id,
                "title": titles[build_id],
                "before": {m: d for m, (_, d) in before[build_id].items() if d},
                "after": {m: d for m, (_, d) in after[build_id].items() if d},
            }
            for build_id in members
        ],
        "remaining": sorted(
            remaining.values(), key=lambda r: (-r["collect"], r["name"].casefold())
        ),
        "net_changes": {
            key: state.get(key, 0) - pool.get(key, 0)
            for key in sorted(set(state) | set(pool))
            if state.get(key, 0) != pool.get(key, 0)
        },
        "truncated": truncated,
        "verified": verified,
    }


def verify(
    data: JsonDict,
    trades: list[JsonDict],
    pool: dict[str, int],
    order: list[tuple[str, dict[str, int]]],
) -> bool:
    """Independently replay a plan: exact rates, stock, storage and reservations."""
    state = dict(pool)
    protected = _reserved_totals(_allocate(order, pool))
    for trade in trades:
        pair = lot(data, trade["give"], trade["take"])
        if pair is None or (trade["pay"], trade["receive"]) != pair:
            return False
        spend = trade["lots"] * pair[0]
        got = trade["lots"] * pair[1]
        give = data["materials"][trade["give"]]
        take = data["materials"][trade["take"]]
        if trade["lots"] < 1 or pair[0] > give["cap"]:
            return False
        if state.get(trade["give"], 0) - spend < protected.get(trade["give"], 0):
            return False
        if state.get(trade["take"], 0) + got > take["cap"]:
            return False
        state[trade["give"]] = state.get(trade["give"], 0) - spend
        state[trade["take"]] = state.get(trade["take"], 0) + got
    return True


# --- Journal ----------------------------------------------------------------------


async def observed_trades(
    session_factory: async_sessionmaker[AsyncSession], data: JsonDict, limit: int = 20
) -> list[JsonDict]:
    """Recent ``MaterialTrade`` events, compared with the built-in rate.

    These are trades that happened.  They are shown and checked against the
    reference; they are never used to derive a rule.
    """
    from omnicovas.features.engineering_progression import (
        _journal_rows,
        _material_key,
        _payload,
    )

    rows = await _journal_rows(session_factory, {"MaterialTrade"})
    names = {mid: m["name"] for mid, m in data.get("materials", {}).items()}
    out = []
    for row in reversed(rows[-limit:]):
        event = _payload(row)
        paid, received = event.get("Paid"), event.get("Received")
        if not isinstance(paid, dict) or not isinstance(received, dict):
            continue
        give = _material_key(paid.get("Material")) or ""
        take = _material_key(received.get("Material")) or ""
        paid_qty, got_qty = paid.get("Quantity"), received.get("Quantity")
        pair = lot(data, give, take) if data.get("state") == "available" else None
        if (
            pair is None
            or not isinstance(paid_qty, int)
            or not isinstance(got_qty, int)
        ):
            check = "not_covered"
        else:
            check = "matches" if paid_qty * pair[1] == got_qty * pair[0] else "differs"
        out.append(
            {
                "observed_at": row.timestamp.isoformat(),
                "trader_type": event.get("TraderType"),
                "give": give,
                "give_name": paid.get("Material_Localised")
                or names.get(give)
                or paid.get("Material"),
                "paid": paid_qty,
                "take": take,
                "take_name": received.get("Material_Localised")
                or names.get(take)
                or received.get("Material"),
                "received": got_qty,
                "reference_rate": f"{pair[0]}:{pair[1]}" if pair else None,
                "check": check,
            }
        )
    return out


def payload(
    data: JsonDict,
    results: list[JsonDict],
    pool: dict[str, int],
    inventory: JsonDict,
    trades_seen: list[JsonDict],
) -> JsonDict:
    """Everything the Material Trader view needs, from the portfolio's own output."""
    if data.get("state") != "available":
        return {
            "state": "unavailable",
            "reason": data.get("reason", "invalid"),
            "materials": [],
            "plans": {},
            "observed_trades": trades_seen,
        }
    known = inventory.get("state") == "verified_local"
    order = [
        (
            str(build["build_plan_id"]),
            {
                str(row["material_id"]): int(row["required"])
                for row in build.get("materials", [])
                if isinstance(row.get("required"), int)
            },
        )
        for build in results
    ]
    reserved = _reserved_totals(_allocate(order, pool)) if known else {}
    material_rows = [
        {
            **material,
            "owned": pool.get(material_id, 0) if known else None,
            "reserved": reserved.get(material_id, 0) if known else None,
            "available": max(pool.get(material_id, 0) - reserved.get(material_id, 0), 0)
            if known
            else None,
        }
        for material_id, material in data["materials"].items()
    ]
    plans: dict[str, JsonDict] = {}
    if known and results:
        ids = [str(build["build_plan_id"]) for build in results]
        plans["all"] = plan(data, results, pool, ids)
        for build_id in ids:
            plans[build_id] = plan(data, results, pool, [build_id])
    return {
        "state": "available",
        "inventory_state": inventory.get("state", "unknown"),
        "version": data["version"],
        "reference": data["reference"],
        "exchange": data["exchange"],
        "storage_caps_by_grade": data["storage_caps_by_grade"],
        "groups": data["groups"],
        "materials": material_rows,
        "plans": plans,
        "objective": OBJECTIVE,
        "observed_trades": trades_seen,
        "caveats": [
            "Quotes, baskets and plans are hypothetical; OmniCOVAS never trades.",
            "Stock reserved for planned builds is never offered as a trade source.",
        ],
    }
