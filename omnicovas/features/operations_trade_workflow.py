"""Operations Trade workflow depth (Phase 14 R6).

`P14-G03`, `P14-G04`, `P14-G08`.

The audit's finding was blunt: Trade's named capability "exists only as button
labels". Three differently-worded buttons — "Search sell prices", "Open Market
Search", "Compare current station" — were bound to one handler that set
`window.location.hash = '#/intel'`. "Compare current station" compared nothing.

This module is the join those labels promised. It reads known local cargo and
the last observed market snapshot, and answers the questions a Commander with a
full hold actually has: what am I carrying, does the market I last looked at buy
it, is that market the one I am standing in, what is it worth at that observed
price, and what should I do next.

The line it will not cross
--------------------------

OmniCOVAS has no galaxy-wide market. It knows one snapshot per station the
Commander personally opened, and nothing at all about stations they have not
visited. So there is no best price, no best station, no optimal loop, and no
"you could get more elsewhere" — because the honest form of that sentence is
"there may be a better price somewhere; this machine cannot see it", and that
sentence is a caveat, not a recommendation.

Potential sale value is quantity times an observed unit price. It is not profit
and it is not earnings. Realised profit comes only from `MarketSell` events that
carry Frontier's own `AvgPricePaid`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.features import operations_economy as economy

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

# ---------------------------------------------------------------------------
# Stage vocabulary
# ---------------------------------------------------------------------------
#
# An ordered ladder, like the exploration stages R5 established: the stage is
# the first gate whose condition holds. Deterministic over the facts, with no
# stored state to drift, and every stage names the fact that selected it.

STAGE_UNKNOWN = "unknown"
STAGE_NO_CARGO = "no_cargo"
STAGE_CARGO_ABOARD = "cargo_aboard"
STAGE_MARKET_REVIEW = "market_review"
STAGE_NO_LOCAL_DEMAND = "no_local_demand"
STAGE_SELL_OPPORTUNITY = "sell_opportunity"

STAGE_ORDER: tuple[str, ...] = (
    STAGE_UNKNOWN,
    STAGE_NO_CARGO,
    STAGE_CARGO_ABOARD,
    STAGE_MARKET_REVIEW,
    STAGE_NO_LOCAL_DEMAND,
    STAGE_SELL_OPPORTUNITY,
)

STAGE_LABELS: dict[str, str] = {
    STAGE_UNKNOWN: "Unknown",
    STAGE_NO_CARGO: "No sale workflow active",
    STAGE_CARGO_ABOARD: "Cargo aboard",
    STAGE_MARKET_REVIEW: "Market review required",
    STAGE_NO_LOCAL_DEMAND: "No local demand",
    STAGE_SELL_OPPORTUNITY: "Local sell opportunity known",
}

COMPLETION_UNKNOWN = "unknown_coverage"
COMPLETION_WORK_REMAINING = "work_remaining"
COMPLETION_NO_KNOWN_WORK = "no_known_work_remaining"

COMPLETION_LABELS: dict[str, str] = {
    COMPLETION_UNKNOWN: "Trade state Unknown",
    COMPLETION_WORK_REMAINING: "Work remaining",
    COMPLETION_NO_KNOWN_WORK: "No additional locally-known trade step",
}

WORK_KIND_WORK = "work"
WORK_KIND_OPPORTUNITY = "opportunity"
WORK_KIND_UNKNOWN = "unknown"

CONDITION_CARGO = "trade_cargo"
CONDITION_MARKET = "trade_market"
CONDITION_ROUTE = "trade_route"

WORKFLOW_CAVEAT = (
    "Trade workflow derived from known local cargo and the last observed market "
    "snapshot. OmniCOVAS observes one station's market at a time and knows "
    "nothing about stations the Commander has not visited, so no price here is "
    "a claim about the galaxy."
)


def _identity(kind: str, target: str | None = None) -> str:
    from omnicovas.features.operations_exploration import objective_identity

    ident = objective_identity(kind, target)
    return ident.replace("exploration.objective", "trade.objective", 1)


# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------


def derive_stage(
    *,
    cargo: dict[str, Any],
    market: dict[str, Any],
    matches: list[dict[str, Any]],
) -> tuple[str, str]:
    """Return `(stage, detail)`. Pure over the facts handed in."""
    if not cargo.get("observed"):
        return (
            STAGE_UNKNOWN,
            cargo.get("reason")
            or "Local cargo has not been observed, so the trade state is Unknown.",
        )

    sellable = cargo.get("sellable") or []
    if not sellable:
        held = []
        if cargo.get("limpets"):
            held.append(f"{cargo['limpets']} limpets")
        if cargo.get("mission"):
            held.append(f"{len(cargo['mission'])} mission item(s)")
        if cargo.get("stolen"):
            held.append(f"{len(cargo['stolen'])} stolen item(s)")
        suffix = f" Hold carries {', '.join(held)}." if held else ""
        return (
            STAGE_NO_CARGO,
            f"No sellable cargo aboard.{suffix}",
        )

    tonnes = cargo.get("sellable_tonnes") or 0
    lead = sellable[0]

    if not market.get("available"):
        return (
            STAGE_CARGO_ABOARD,
            f"{tonnes} t of sellable cargo aboard ({lead['count']} t "
            f"{lead['name']}). No local market snapshot loaded.",
        )

    scope = market.get("scope")
    if scope != economy.SCOPE_CURRENT_STATION:
        station = market.get("station_name") or "an unknown station"
        return (
            STAGE_MARKET_REVIEW,
            f"{tonnes} t of sellable cargo aboard. The only market snapshot is "
            f"a historical observation from {station}.",
        )

    buying = [m for m in matches if m.get("buys_here")]
    station = market.get("station_name") or "this station"
    if not buying:
        return (
            STAGE_NO_LOCAL_DEMAND,
            f"{station} does not buy any of the {tonnes} t aboard, according to "
            "the current snapshot.",
        )

    # Named for what it is — the highest potential value in THIS snapshot —
    # rather than "best", which would invite the next reader to put that word in
    # the Commander-facing sentence. There is no basis for it: one station's
    # snapshot cannot rank against markets this machine has never seen.
    top_by_snapshot_value = buying[0]
    return (
        STAGE_SELL_OPPORTUNITY,
        f"{station} buys {top_by_snapshot_value['name']} at "
        f"{int(top_by_snapshot_value['sell_price']):,} Cr/t in the current "
        "snapshot.",
    )


# ---------------------------------------------------------------------------
# Derived step
# ---------------------------------------------------------------------------


def derive_step(
    *,
    stage: str,
    cargo: dict[str, Any],
    market: dict[str, Any],
    matches: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """The one concrete trade step, labelled as derived rather than Commander intent."""
    if stage == STAGE_UNKNOWN:
        return None

    base = {"owner": "derived", "state": "active"}

    if stage == STAGE_NO_CARGO:
        return {
            **base,
            "objective_id": _identity("acquire_cargo"),
            "kind": "acquire_cargo",
            "label": "Acquire cargo to start a sale workflow",
            "target": None,
            "target_kind": None,
            "source_id": economy.TRUTH_LOCAL_SCREEN_SNAPSHOT,
        }

    if stage == STAGE_CARGO_ABOARD:
        return {
            **base,
            "objective_id": _identity("load_market"),
            "kind": "load_market",
            "label": "Open a station commodities market to load a snapshot",
            "target": None,
            "target_kind": None,
            "source_id": economy.TRUTH_LOCAL_SCREEN_SNAPSHOT,
        }

    if stage == STAGE_MARKET_REVIEW:
        station = market.get("station_name")
        return {
            **base,
            "objective_id": _identity("market_review", station),
            "kind": "market_review",
            "label": f"Review the {station or 'historical'} snapshot in Intel",
            "target": station,
            "target_kind": "station",
            "source_id": economy.TRUTH_LOCAL_SCREEN_SNAPSHOT,
        }

    if stage == STAGE_NO_LOCAL_DEMAND:
        return {
            **base,
            "objective_id": _identity("find_buyer"),
            "kind": "find_buyer",
            "label": "Review commodity demand in Intel",
            "target": (cargo.get("sellable") or [{}])[0].get("name"),
            "target_kind": "commodity",
            "source_id": economy.TRUTH_LOCAL_SCREEN_SNAPSHOT,
        }

    lead = next(m for m in matches if m.get("buys_here"))
    return {
        **base,
        "objective_id": _identity("sell_commodity", lead["key"]),
        "kind": "sell_commodity",
        "label": f"Sell {lead['count']} t {lead['name']} at "
        f"{market.get('station_name') or 'this station'}",
        "target": lead["name"],
        "target_kind": "commodity",
        "source_id": economy.TRUTH_LOCAL_SCREEN_SNAPSHOT,
    }


# ---------------------------------------------------------------------------
# Value
# ---------------------------------------------------------------------------


def derive_value(
    *, matches: list[dict[str, Any]], market: dict[str, Any], sales: dict[str, Any]
) -> dict[str, Any]:
    """Potential value, realised revenue and profit — three separate fields.

    The first is arithmetic over a snapshot and is labelled an estimate at that
    snapshot. The second is money the journal recorded arriving. The third
    exists only when Frontier told us what the cargo cost.
    """
    priced = [m for m in matches if m.get("potential_value")]
    unpriced = [m for m in matches if m.get("in_snapshot") and not m.get("sell_price")]
    absent = [m for m in matches if not m.get("in_snapshot")]

    return {
        "potential_sale_value": {
            "total": sum(m["potential_value"] for m in priced) if priced else None,
            "commodities_priced": len(priced),
            "commodities_not_bought_here": len(unpriced),
            "commodities_absent_from_snapshot": len(absent),
            "is_estimate": True,
            "at_station": market.get("station_name"),
            "scope": market.get("scope"),
            "truth_class": economy.TRUTH_LOCAL_SCREEN_SNAPSHOT,
            "label": "Potential value at this snapshot (not earned)",
        },
        "recorded_sales": {
            "revenue": sales.get("revenue"),
            "tonnes_sold": sales.get("tonnes_sold"),
            "sales": sales.get("sales"),
            "truth_class": economy.TRUTH_LOCAL_EVENT_HISTORY,
            "label": "Credits received",
        },
        "realised_profit": {
            "value": sales.get("profit"),
            "basis": sales.get("profit_basis"),
            "truth_class": economy.TRUTH_LOCAL_EVENT_HISTORY,
            "label": "Realised profit",
            "unavailable_reason": (
                None
                if sales.get("profit") is not None
                else (
                    "Profit needs what the cargo cost. Frontier reports it on a "
                    "sale as AvgPricePaid; without it, profit is Unknown rather "
                    "than assumed."
                )
            ),
        },
        "unknown": [
            "Prices at stations this Commander has not visited are not known.",
            "Whether a better price exists elsewhere is not known.",
        ],
    }


# ---------------------------------------------------------------------------
# Work remaining, blockers, completion
# ---------------------------------------------------------------------------


def derive_work_remaining(
    *,
    stage: str,
    cargo: dict[str, Any],
    market: dict[str, Any],
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if stage == STAGE_UNKNOWN:
        return [
            {
                "id": "trade.unknown.cargo",
                "label": "Trade state Unknown",
                "detail": cargo.get("reason") or "Local cargo has not been observed.",
                "kind": WORK_KIND_UNKNOWN,
            }
        ]

    items: list[dict[str, Any]] = []
    sellable = cargo.get("sellable") or []

    if sellable:
        tonnes = cargo.get("sellable_tonnes") or 0
        items.append(
            {
                "id": "trade.cargo.sellable",
                "label": f"{tonnes} t of sellable cargo aboard",
                "detail": ", ".join(
                    f"{entry['count']} t {entry['name']}" for entry in sellable[:3]
                )
                + ("…" if len(sellable) > 3 else ""),
                "kind": WORK_KIND_WORK,
            }
        )

    if cargo.get("mission"):
        items.append(
            {
                "id": "trade.cargo.mission",
                "label": f"{len(cargo['mission'])} mission item(s) aboard",
                "detail": "Mission cargo is not sold on the commodity market.",
                "kind": WORK_KIND_UNKNOWN,
            }
        )
    if cargo.get("stolen"):
        items.append(
            {
                "id": "trade.cargo.stolen",
                "label": f"{len(cargo['stolen'])} stolen item(s) aboard",
                "detail": "Stolen cargo is not bought by an ordinary market.",
                "kind": WORK_KIND_UNKNOWN,
            }
        )

    if not market.get("available"):
        items.append(
            {
                "id": "trade.market.absent",
                "label": "No market snapshot loaded",
                "detail": (
                    "Prices are Unknown until a station commodities screen is "
                    "opened. Nothing is assumed about what a market pays."
                ),
                "kind": WORK_KIND_UNKNOWN,
            }
        )
    elif market.get("scope") != economy.SCOPE_CURRENT_STATION:
        items.append(
            {
                "id": "trade.market.historical",
                "label": "Only a historical snapshot is available",
                "detail": (
                    "Observed at "
                    f"{market.get('station_name') or 'an unknown station'}. It is "
                    "not a statement about prices here or now."
                ),
                "kind": WORK_KIND_OPPORTUNITY,
            }
        )

    absent = [m for m in matches if not m.get("in_snapshot")]
    if absent:
        items.append(
            {
                "id": "trade.market.commodity_absent",
                "label": f"{len(absent)} commodity(s) not in the snapshot",
                "detail": (
                    f"{absent[0]['name']} does not appear in the observed market. "
                    "That is an absent row, not a price of zero."
                ),
                "kind": WORK_KIND_UNKNOWN,
            }
        )

    return items


def derive_blockers(
    *,
    stage: str,
    cargo: dict[str, Any],
    market: dict[str, Any],
    route_active: bool,
) -> list[dict[str, Any]]:
    """Only conditions that actually stop the trade workflow.

    A historical snapshot merely existing is not a blocker; nor is the absence
    of galaxy-wide coverage, nor the possibility that somewhere pays more. Those
    are limits on what is known, and R4 settled that Unknown is never a blocker.
    """
    blockers: list[dict[str, Any]] = []

    if not cargo.get("observed"):
        blockers.append(
            {
                "blocker_id": "trade.blocker.cargo-unavailable",
                "label": "Cargo manifest unavailable",
                "detail": cargo.get("reason")
                or "No local cargo snapshot has been observed.",
                "kind": "source_unavailable",
                "source_id": None,
                "condition_id": CONDITION_CARGO,
            }
        )
        return blockers

    # Sitting on sellable cargo with a current market that buys none of it, and
    # no route out, is the one trade state where the Commander is genuinely
    # stuck: the sale cannot happen here and nothing is plotted to anywhere else.
    if stage == STAGE_NO_LOCAL_DEMAND and not route_active:
        blockers.append(
            {
                "blocker_id": "trade.blocker.no-route",
                "label": "No route to a market that buys this cargo",
                "detail": (
                    f"{market.get('station_name') or 'This station'} buys none of "
                    "the cargo aboard, and no route is plotted. Navigation owns "
                    "route planning."
                ),
                "kind": "no_route",
                "source_id": "local_navroute",
                "condition_id": CONDITION_ROUTE,
            }
        )

    return blockers


def derive_completion(
    *, stage: str, cargo: dict[str, Any], work_remaining: list[dict[str, Any]]
) -> dict[str, Any]:
    if stage == STAGE_UNKNOWN:
        return {
            "state": COMPLETION_UNKNOWN,
            "label": COMPLETION_LABELS[COMPLETION_UNKNOWN],
            "reason": cargo.get("reason") or "Local cargo has not been observed.",
        }

    if stage == STAGE_NO_CARGO:
        return {
            "state": COMPLETION_NO_KNOWN_WORK,
            "label": COMPLETION_LABELS[COMPLETION_NO_KNOWN_WORK],
            "reason": "No sellable cargo aboard, so no sale workflow is open.",
        }

    proven = [item for item in work_remaining if item["kind"] == WORK_KIND_WORK]
    return {
        "state": COMPLETION_WORK_REMAINING,
        "label": COMPLETION_LABELS[COMPLETION_WORK_REMAINING],
        "reason": (proven[0]["label"] + ".") if proven else "Cargo aboard is unsold.",
    }


# ---------------------------------------------------------------------------
# Handoffs
# ---------------------------------------------------------------------------


def derive_handoffs(
    *, cargo: dict[str, Any], market: dict[str, Any], step: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Where the detail lives. Operations names the owner; it never rebuilds it."""
    lead = (cargo.get("sellable") or [{}])[0]
    commodity = lead.get("name")

    handoffs: list[dict[str, Any]] = []
    if commodity:
        handoffs.append(
            {
                "id": "intel_commodity",
                "label": f"Review {commodity} in Intel",
                "route": "/intel",
                "section_id": "intel-domain-search",
                "entity_id": "commodity",
                "query": commodity,
                "reason": f"Commodity lookup from Operations: {commodity}",
            }
        )
    handoffs.append(
        {
            "id": "intel_market",
            "label": "Review market facts in Intel",
            "route": "/intel",
            "section_id": "intel-domain-search",
            "entity_id": "commodity",
            "query": None,
            "reason": "Intel owns market facts and commodity search.",
        }
    )
    handoffs.append(
        {
            "id": "navigation_route",
            "label": "Plot a route",
            "route": "/navigation",
            "section_id": "navigation-current-route",
            "entity_id": None,
            "query": None,
            "reason": "Navigation owns route planning.",
        }
    )
    handoffs.append(
        {
            "id": "activity_log",
            "label": "Open Activity Log",
            "route": "/activity-log",
            "section_id": None,
            "entity_id": None,
            "query": None,
            "reason": "Activity Log owns the proof record.",
        }
    )
    return handoffs


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def unavailable_workflow(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "stage": STAGE_UNKNOWN,
        "stage_label": STAGE_LABELS[STAGE_UNKNOWN],
        "stage_detail": reason,
        "step": None,
        "cargo": None,
        "market": None,
        "matches": [],
        "value": None,
        "work_remaining": [
            {
                "id": "trade.unknown.unavailable",
                "label": "Trade state Unknown",
                "detail": reason,
                "kind": WORK_KIND_UNKNOWN,
            }
        ],
        "blockers": [
            {
                "blocker_id": "trade.blocker.cargo-unavailable",
                "label": "Cargo manifest unavailable",
                "detail": reason,
                "kind": "source_unavailable",
                "source_id": None,
                "condition_id": CONDITION_CARGO,
            }
        ],
        "completion": {
            "state": COMPLETION_UNKNOWN,
            "label": COMPLETION_LABELS[COMPLETION_UNKNOWN],
            "reason": reason,
        },
        "observed_stations": None,
        "handoffs": derive_handoffs(cargo={}, market={}, step=None),
        "caveat": WORKFLOW_CAVEAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def build_workflow(
    state: StateManager | None,
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    route_active: bool = False,
    cargo_path: Path | None = None,
    market_path: Path | None = None,
) -> dict[str, Any]:
    """Compose the Operations Trade workflow from local facts only."""
    cargo = economy.known_cargo(state, cargo_path=cargo_path)
    market = economy.observed_market(state, market_path=market_path)
    matches = economy.sell_matches(cargo, market)
    sales = await economy.recorded_sales(session_factory)
    stations = await economy.stations_observed(session_factory)

    stage, detail = derive_stage(cargo=cargo, market=market, matches=matches)
    step = derive_step(stage=stage, cargo=cargo, market=market, matches=matches)
    work_remaining = derive_work_remaining(
        stage=stage, cargo=cargo, market=market, matches=matches
    )
    completion = derive_completion(
        stage=stage, cargo=cargo, work_remaining=work_remaining
    )
    blockers = derive_blockers(
        stage=stage, cargo=cargo, market=market, route_active=route_active
    )

    return {
        "available": True,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "stage_detail": detail,
        "step": step,
        "cargo": {
            "observed": cargo["observed"],
            "reason": cargo["reason"],
            "capacity": cargo["capacity"],
            "total_count": cargo["total_count"],
            "sellable": cargo["sellable"],
            "sellable_tonnes": cargo["sellable_tonnes"],
            "mission_items": len(cargo["mission"]),
            "stolen_items": len(cargo["stolen"]),
            "limpets": cargo["limpets"],
            "truth_class": cargo["truth_class"],
        },
        "market": {
            key: market[key]
            for key in (
                "available",
                "scope",
                "scope_label",
                "station_name",
                "star_system",
                "market_id",
                "freshness",
                "event_timestamp",
                "item_count",
                "truth_class",
            )
        },
        "matches": matches,
        "value": derive_value(matches=matches, market=market, sales=sales),
        "work_remaining": work_remaining,
        "blockers": blockers,
        "completion": completion,
        # Bounded by construction: markets this Commander personally opened.
        # Never a statement about the galaxy, and the wording says so.
        "observed_stations": {
            "count": stations["station_count"] if stations["observed"] else None,
            "observed": stations["observed"],
            "caveat": (
                "Counts only station markets this Commander has opened. Stations "
                "never visited are not known and are not counted."
            ),
        },
        "handoffs": derive_handoffs(cargo=cargo, market=market, step=step),
        "caveat": WORKFLOW_CAVEAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
