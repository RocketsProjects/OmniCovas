"""Shared local-first economic substrate for the Operations Trade and Mining
workflows (Phase 14 R6).

Trade and Mining ask different questions and keep separate workflows, but they
read the same four local facts: what is in the hold, what a market snapshot
observed, what the journal recorded being refined, and what the journal recorded
being bought and sold. Those readings live here once, so the two workflows
cannot drift into disagreeing about the same file.

What this module will and will not claim
----------------------------------------

**Known local cargo** comes from `Cargo.json` or the newest `Cargo` journal
event, whichever the existing local-context reader prefers. An inventory the
journal reported without a breakdown is Unknown, never an empty hold.

**Last observed market** is exactly that: one station's snapshot, refreshed only
when the Commander opens the commodities screen. Its scope is derived from the
identity and freshness rules `local_context_facts` already owns — this module
re-labels that verdict for workflow use, it does not re-decide it.

OmniCOVAS does **not** know the galactic best price, prices at stations the
Commander has never visited, or whether a better market exists nearby. Nothing
here produces such a claim. Where a comparison is offered it is explicitly
bounded to stations this Commander has actually visited, and it says so in the
same breath.

**Limpets are not cargo to sell.** They occupy the hold and are reported as
their own fact, so a hold carrying 250 limpets never reads as 250 tonnes of
sellable freight.

**Profit needs a cost basis.** Frontier supplies one on `MarketSell` as
`AvgPricePaid`, so realised profit is computed only for sales that carry it.
Nothing is inferred from cargo appearing or disappearing.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import JournalEvent
from omnicovas.features import local_context_facts

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

UNKNOWN = "Unknown"

TRUTH_LOCAL_SCREEN_SNAPSHOT = "local_screen_snapshot"
TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
TRUTH_LOCAL_TELEMETRY = "local_telemetry"
TRUTH_UNKNOWN = "unknown"

# Journal events this module reads. Every one was confirmed present in a real
# Commander recorder before being relied on; `CollectCargo` is deliberately
# absent because this machine's history contains none, and a source that has
# never been observed must not become a number.
MINING_REFINED_EVENTS = ("MiningRefined",)
MARKET_SELL_EVENTS = ("MarketSell",)
MARKET_BUY_EVENTS = ("MarketBuy",)
MARKET_SNAPSHOT_EVENTS = ("Market",)

# Frontier writes market commodity names as `$platinum_name;` and cargo names as
# `platinum`. One key, so the two can be joined without either side guessing.
_COMMODITY_STRIP = re.compile(r"^\$|_name;$|;$")

# Limpets are stored in the cargo hold as an ordinary commodity row. They are
# consumables for mining and hauling, not freight, and every count in this
# module keeps them apart from sellable tonnage.
LIMPET_KEYS: frozenset[str] = frozenset({"drones"})


def commodity_key(name: Any) -> str:
    """Normalise a market or cargo commodity name to one join key."""
    token = str(name or "").strip().lower()
    if not token:
        return ""
    return _COMMODITY_STRIP.sub("", token)


def display_name(item: dict[str, Any]) -> str:
    """Commander-facing commodity name, preferring Frontier's localised form."""
    localised = item.get("name_localised") or item.get("Name_Localised")
    if localised:
        return str(localised)
    name = item.get("name") or item.get("Name") or ""
    key = commodity_key(name)
    return key.replace("_", " ").title() if key else UNKNOWN


# ---------------------------------------------------------------------------
# Known local cargo
# ---------------------------------------------------------------------------


def known_cargo(
    state: StateManager | None, *, cargo_path: Path | None = None
) -> dict[str, Any]:
    """Classify the hold into the categories a workflow actually acts on.

    `sellable` excludes limpets, and excludes mission cargo, which cannot be
    sold on a commodity market. Stolen cargo is separated rather than dropped:
    it is real tonnage the Commander is carrying, and the ordinary market will
    not take it, so a sell workflow that silently counted it would be wrong in
    both directions.
    """
    payload = local_context_facts.cargo_hold_payload(state, cargo_path=cargo_path)
    inventory = payload.get("inventory")
    complete = payload.get("inventory_complete")

    if inventory is None or complete is not True:
        # A count without a breakdown, or no snapshot at all. Either way the
        # manifest is Unknown; it is never read as an empty hold.
        return {
            "observed": False,
            "reason": payload.get("fallback")
            or (
                "The most recent cargo reading reported a total without an item "
                "breakdown, so the manifest is Unknown."
            ),
            "capacity": payload.get("capacity"),
            "total_count": payload.get("total_count"),
            "sellable": [],
            "mission": [],
            "stolen": [],
            "limpets": None,
            "sellable_tonnes": None,
            "source": payload.get("source"),
            "truth_class": payload.get("truth_class"),
            "caveat": payload.get("caveat"),
        }

    sellable: list[dict[str, Any]] = []
    mission: list[dict[str, Any]] = []
    stolen: list[dict[str, Any]] = []
    limpets = 0

    for raw in inventory:
        if not isinstance(raw, dict):
            continue
        key = commodity_key(raw.get("name"))
        count = int(raw.get("count") or 0)
        entry = {
            "key": key,
            "name": display_name(raw),
            "count": count,
            "stolen": bool(raw.get("stolen")),
            "mission_id": raw.get("mission_id"),
        }
        if key in LIMPET_KEYS:
            limpets += count
            continue
        if entry["mission_id"] is not None:
            mission.append(entry)
        elif entry["stolen"]:
            stolen.append(entry)
        else:
            sellable.append(entry)

    # Largest holding first, then by name: a stable order a Commander can read
    # twice and see the same thing.
    sellable.sort(key=lambda e: (-e["count"], e["name"]))
    mission.sort(key=lambda e: (-e["count"], e["name"]))
    stolen.sort(key=lambda e: (-e["count"], e["name"]))

    return {
        "observed": True,
        "reason": None,
        "capacity": payload.get("capacity"),
        "total_count": payload.get("total_count"),
        "sellable": sellable,
        "mission": mission,
        "stolen": stolen,
        "limpets": limpets,
        "sellable_tonnes": sum(entry["count"] for entry in sellable),
        "source": payload.get("source"),
        "truth_class": payload.get("truth_class"),
        "caveat": payload.get("caveat"),
    }


# ---------------------------------------------------------------------------
# Last observed market
# ---------------------------------------------------------------------------

SCOPE_NONE = "not_loaded"
SCOPE_CURRENT_STATION = "current_station"
SCOPE_SAME_STATION_STALE = "same_station_historical"
SCOPE_FOREIGN_STATION = "foreign_station"
SCOPE_UNKNOWN_IDENTITY = "unknown_identity"

SCOPE_LABELS: dict[str, str] = {
    SCOPE_NONE: "No local market snapshot loaded",
    SCOPE_CURRENT_STATION: "Current local market snapshot",
    SCOPE_SAME_STATION_STALE: "Historical snapshot from this station",
    SCOPE_FOREIGN_STATION: "Historical snapshot from another station",
    SCOPE_UNKNOWN_IDENTITY: "Market snapshot of unknown station identity",
}


def observed_market(
    state: StateManager | None, *, market_path: Path | None = None
) -> dict[str, Any]:
    """The last observed market snapshot, with its scope named.

    Freshness is not re-decided here. `local_context_facts` already owns the
    rule that a snapshot goes stale when the Commander undocks or moves, and
    this reads that verdict. What it adds is the workflow-facing distinction
    between "this is the station I am standing in" and "this is somewhere I
    used to be", because those two support completely different actions.
    """
    payload = local_context_facts.market_snapshot_payload(
        state, market_path=market_path
    )
    items = payload.get("items")
    if items is None:
        return {
            "available": False,
            "scope": SCOPE_NONE,
            "scope_label": SCOPE_LABELS[SCOPE_NONE],
            "station_name": None,
            "star_system": None,
            "market_id": None,
            "freshness": payload.get("freshness"),
            "event_timestamp": payload.get("event_timestamp"),
            "item_count": 0,
            "items": {},
            "truth_class": TRUTH_UNKNOWN,
            "caveat": payload.get("caveat"),
        }

    station_name = payload.get("station_name")
    star_system = payload.get("star_system")
    fresh = payload.get("freshness") == local_context_facts.FRESH

    current_station = (
        getattr(state.snapshot, "current_station", None) if state else None
    )

    if not station_name:
        scope = SCOPE_UNKNOWN_IDENTITY
    elif fresh:
        # `fresh` already means the reader found no reason to doubt that this
        # snapshot describes where the Commander is standing.
        scope = SCOPE_CURRENT_STATION
    elif current_station and current_station == station_name:
        scope = SCOPE_SAME_STATION_STALE
    else:
        scope = SCOPE_FOREIGN_STATION

    indexed: dict[str, dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        key = commodity_key(raw.get("name"))
        if not key:
            continue
        indexed[key] = {
            "key": key,
            "name": display_name(raw),
            "sell_price": raw.get("sell_price"),
            "buy_price": raw.get("buy_price"),
            "demand": raw.get("demand"),
            "demand_bracket": raw.get("demand_bracket"),
            "stock": raw.get("stock"),
        }

    return {
        "available": True,
        "scope": scope,
        "scope_label": SCOPE_LABELS[scope],
        "station_name": station_name,
        "star_system": star_system,
        "market_id": payload.get("market_id"),
        "freshness": payload.get("freshness"),
        "event_timestamp": payload.get("event_timestamp"),
        "item_count": len(indexed),
        "items": indexed,
        "truth_class": TRUTH_LOCAL_SCREEN_SNAPSHOT,
        "caveat": payload.get("caveat"),
    }


# ---------------------------------------------------------------------------
# Cargo x market: the sell matcher (P14-G03)
# ---------------------------------------------------------------------------


def sell_matches(cargo: dict[str, Any], market: dict[str, Any]) -> list[dict[str, Any]]:
    """Join sellable cargo against the observed market snapshot.

    This answers "does the market I last looked at buy what I am carrying, and
    at what observed price" — and nothing beyond it. The value it computes is
    quantity times an observed unit price: a **potential** sale value at that
    snapshot, not profit, not earnings, and not a claim that a better price does
    not exist elsewhere.
    """
    if not cargo.get("observed") or not market.get("available"):
        return []

    matches: list[dict[str, Any]] = []
    for entry in cargo.get("sellable") or []:
        row = (market.get("items") or {}).get(entry["key"])
        if row is None:
            matches.append(
                {
                    "key": entry["key"],
                    "name": entry["name"],
                    "count": entry["count"],
                    "in_snapshot": False,
                    "sell_price": None,
                    "demand": None,
                    "potential_value": None,
                    "buys_here": None,
                }
            )
            continue
        price = row.get("sell_price")
        # SellPrice 0 means the station does not buy it, which is a fact the
        # snapshot states. It is not a missing price.
        buys = None if price is None else bool(price)
        matches.append(
            {
                "key": entry["key"],
                "name": entry["name"],
                "count": entry["count"],
                "in_snapshot": True,
                "sell_price": price,
                "demand": row.get("demand"),
                "potential_value": (
                    int(price) * entry["count"]
                    if isinstance(price, int) and price
                    else None
                ),
                "buys_here": buys,
            }
        )

    # Highest potential value first; unpriced rows keep a stable place at the
    # end rather than being dropped.
    matches.sort(
        key=lambda m: (-(m["potential_value"] or 0), m["name"]),
    )
    return matches


# ---------------------------------------------------------------------------
# Observed markets across visited stations (P14-G04, workflow half)
# ---------------------------------------------------------------------------


def _json(path: str) -> Any:
    return func.json_extract(JournalEvent.raw_json, path)


async def stations_observed(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> dict[str, Any]:
    """How many distinct station markets this Commander has actually opened.

    Bounded by construction: it counts `Market` journal events, which exist only
    for markets the Commander personally looked at. It is never a statement
    about the galaxy, and the caveat travels with the number.
    """
    if session_factory is None:
        return {"observed": False, "station_count": 0, "stations": [], "reason": None}
    try:
        async with session_factory() as db:
            rows = (
                await db.execute(
                    select(
                        _json("$.StationName").label("station_name"),
                        _json("$.StarSystem").label("star_system"),
                        func.max(JournalEvent.timestamp).label("last_seen"),
                    )
                    .where(
                        JournalEvent.event_type.in_(MARKET_SNAPSHOT_EVENTS),
                        _json("$.StationName").is_not(None),
                    )
                    .group_by(_json("$.MarketID"))
                    .order_by(func.max(JournalEvent.timestamp).desc())
                )
            ).all()
    except Exception:  # noqa: BLE001 - a read failure is Unknown, not "none"
        return {
            "observed": False,
            "station_count": 0,
            "stations": [],
            "reason": "The local recorder did not answer.",
        }

    stations = [
        {
            "station_name": row.station_name,
            "star_system": row.star_system,
            "last_seen": row.last_seen.isoformat() if row.last_seen else None,
        }
        for row in rows
    ]
    return {
        "observed": True,
        "station_count": len(stations),
        "stations": stations,
        "reason": None,
    }


# ---------------------------------------------------------------------------
# Journal-recorded economic events
# ---------------------------------------------------------------------------


async def session_mining_yield(
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    since: Any | None = None,
) -> dict[str, Any]:
    """Tonnes refined, per commodity, from `MiningRefined` events.

    Frontier emits one `MiningRefined` per tonne that completes refining, so
    counting events is counting tonnes — a recorded fact, not an inference from
    cargo appearing. Cargo that was already aboard is never counted here, which
    is the whole reason this is derived from events rather than from the hold.
    """
    if session_factory is None:
        return {
            "observed": False,
            "total_tonnes": None,
            "by_commodity": {},
            "reason": "The local recorder is not available in this session.",
        }
    try:
        async with session_factory() as db:
            conditions: list[Any] = [JournalEvent.event_type.in_(MINING_REFINED_EVENTS)]
            if since is not None:
                conditions.append(JournalEvent.timestamp >= since)
            rows = (
                await db.execute(
                    select(
                        _json("$.Type_Localised").label("localised"),
                        _json("$.Type").label("raw_type"),
                        func.count().label("tonnes"),
                    )
                    .where(*conditions)
                    .group_by(_json("$.Type"))
                )
            ).all()
    except Exception:  # noqa: BLE001
        return {
            "observed": False,
            "total_tonnes": None,
            "by_commodity": {},
            "reason": "The local recorder did not answer.",
        }

    by_commodity: dict[str, dict[str, Any]] = {}
    total = 0
    for row in rows:
        key = commodity_key(row.raw_type)
        if not key:
            continue
        tonnes = int(row.tonnes)
        total += tonnes
        by_commodity[key] = {
            "key": key,
            "name": str(row.localised or key.title()),
            "tonnes": tonnes,
        }
    return {
        "observed": True,
        "total_tonnes": total,
        "by_commodity": by_commodity,
        "reason": None,
    }


async def recorded_sales(
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    since: Any | None = None,
) -> dict[str, Any]:
    """Sales the journal actually recorded, with profit only where cost is known.

    `MarketSell` carries `AvgPricePaid`, which is Frontier's own statement of
    what the Commander paid for that cargo. Where it is present, realised profit
    is arithmetic over two recorded numbers. Where it is absent, profit is
    Unknown and stays Unknown — it is never reconstructed from a market
    snapshot, because a snapshot price is not what anyone paid.
    """
    if session_factory is None:
        return {
            "observed": False,
            "sales": 0,
            "tonnes_sold": None,
            "revenue": None,
            "profit": None,
            "profit_basis": "unavailable",
            "reason": "The local recorder is not available in this session.",
        }
    try:
        async with session_factory() as db:
            conditions: list[Any] = [JournalEvent.event_type.in_(MARKET_SELL_EVENTS)]
            if since is not None:
                conditions.append(JournalEvent.timestamp >= since)
            rows = (
                await db.execute(
                    select(
                        # Deliberately not labelled "count": `Row.count` is the
                        # tuple method, so that label reads back as a bound
                        # method instead of the value.
                        _json("$.Count").label("tonnes"),
                        _json("$.TotalSale").label("total_sale"),
                        _json("$.AvgPricePaid").label("avg_paid"),
                    ).where(*conditions)
                )
            ).all()
    except Exception:  # noqa: BLE001
        return {
            "observed": False,
            "sales": 0,
            "tonnes_sold": None,
            "revenue": None,
            "profit": None,
            "profit_basis": "unavailable",
            "reason": "The local recorder did not answer.",
        }

    tonnes = 0
    revenue = 0
    profit = 0
    priced_sales = 0
    unpriced_sales = 0
    for row in rows:
        sold = int(row.tonnes or 0)
        sale = int(row.total_sale or 0)
        tonnes += sold
        revenue += sale
        if row.avg_paid is None:
            unpriced_sales += 1
            continue
        priced_sales += 1
        profit += sale - int(row.avg_paid) * sold

    if not rows:
        basis = "no_sales_recorded"
    elif unpriced_sales:
        # Partial cost coverage cannot produce a whole-session profit figure.
        basis = "partial"
    else:
        basis = "complete"

    return {
        "observed": True,
        "sales": len(rows),
        "tonnes_sold": tonnes,
        "revenue": revenue if rows else None,
        "profit": profit if basis == "complete" else None,
        "profit_basis": basis,
        "sales_with_cost_basis": priced_sales,
        "sales_without_cost_basis": unpriced_sales,
        "reason": None,
    }


def read_market_file(path: Path) -> dict[str, Any] | None:
    """Read one Market.json. Test seam; production goes through the reader above."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None
