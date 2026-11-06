"""Operations Mining workflow depth (Phase 14 R6).

`P14-H01` … `P14-H06`.

The audit found Mining ending where a real workflow begins. Its "preflight" was
the generic vitals card — and, before R1, the *idle* profile's vitals at that.
There was no target commodity, so "fill progress" had no denominator; no limpet
or refinery reading, though `role_fit()` was already tokenising module names one
call away; and the return/sell step was a button labelled "Search sell prices"
wired to `window.location.hash = '#/intel'`.

This module carries Mining through the whole arc — prepare, extract, return,
sell, done — using only facts this machine actually holds.

The lines it will not cross
---------------------------

**Hotspot and ring quality are not known.** No authorised source supplies them,
so there is no best hotspot, no pristine ring, no highest yield and no best
mining location. A Commander's own plotted route and selected target are used
instead, labelled as exactly that.

**Unknown equipment is not missing equipment.** `role_fit()` reports what was
seen fitted and what was not seen, and R0's shield doctrine settled which of
those is a verdict: a partial loadout is silence, not absence. Only a loadout
that *was* observed can support "confirmed absent".

**Current cargo is not session yield.** Tonnes refined come from `MiningRefined`
events, one per refined tonne. Cargo that was aboard before is never counted,
which is exactly why this reads events rather than the hold.

**Limpets are counted, not inferred.** They appear in the hold as the commodity
`drones`. Cargo capacity is not a limpet count, and a limpet in the hold is not
proof that a controller is fitted to launch it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.features import operations_economy as economy
from omnicovas.features import readiness as readiness_feature

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

STAGE_UNKNOWN = "unknown"
STAGE_PREPARE = "prepare"
STAGE_EXTRACT = "extract"
STAGE_RETURN = "return"
STAGE_SELL = "sell"
STAGE_COMPLETE_READY = "complete_ready"

STAGE_ORDER: tuple[str, ...] = (
    STAGE_UNKNOWN,
    STAGE_PREPARE,
    STAGE_EXTRACT,
    STAGE_RETURN,
    STAGE_SELL,
    STAGE_COMPLETE_READY,
)

STAGE_LABELS: dict[str, str] = {
    STAGE_UNKNOWN: "Unknown",
    STAGE_PREPARE: "Prepare",
    STAGE_EXTRACT: "Extract",
    STAGE_RETURN: "Return",
    STAGE_SELL: "Sell",
    STAGE_COMPLETE_READY: "Session complete",
}

COMPLETION_UNKNOWN = "unknown_coverage"
COMPLETION_WORK_REMAINING = "work_remaining"
COMPLETION_NO_KNOWN_WORK = "no_known_work_remaining"

COMPLETION_LABELS: dict[str, str] = {
    COMPLETION_UNKNOWN: "Mining state Unknown",
    COMPLETION_WORK_REMAINING: "Work remaining",
    COMPLETION_NO_KNOWN_WORK: "No additional locally-known mining step",
}

WORK_KIND_WORK = "work"
WORK_KIND_OPPORTUNITY = "opportunity"
WORK_KIND_UNKNOWN = "unknown"

FIT_FITTED = "fitted"
FIT_NOT_OBSERVED = "not_observed"
FIT_UNKNOWN = "unknown"

CONDITION_LOADOUT = "mining_loadout"
CONDITION_EQUIPMENT = "mining_equipment"
CONDITION_LIMPETS = "mining_limpets"
CONDITION_CARGO = "mining_cargo"
CONDITION_ROUTE = "mining_route"

# Capabilities a laser-mining workflow genuinely needs. Core mining (seismic
# charges, abrasion blasters) needs different tools; this module does not claim
# to know which style the Commander is flying, so a confirmed-absent refinery or
# collector is reported as blocking laser mining specifically.
REQUIRED_CAPABILITIES: tuple[str, ...] = ("refinery", "collector")
SUPPORTING_CAPABILITIES: tuple[str, ...] = ("mining_laser", "prospector", "cargo_rack")

CAPABILITY_LABELS: dict[str, str] = {
    "refinery": "Refinery",
    "collector": "Collector limpet controller",
    "prospector": "Prospector limpet controller",
    "mining_laser": "Mining laser",
    "cargo_rack": "Cargo rack",
}

WORKFLOW_CAVEAT = (
    "Mining workflow derived from the observed loadout, known local cargo and "
    "recorded MiningRefined events. Hotspot and ring quality have no verified "
    "local source, so no location is described as best, pristine or highest "
    "yield. Equipment not seen in the loadout is Unknown, never confirmed "
    "absent."
)

HOTSPOT_UNSUPPORTED = (
    "Hotspot and ring quality are not known. No verified local source reports "
    "them and no provider is enabled, so OmniCOVAS names only the destination "
    "the Commander selected or plotted."
)


def _identity(kind: str, target: str | None = None) -> str:
    from omnicovas.features.operations_exploration import objective_identity

    ident = objective_identity(kind, target)
    return ident.replace("exploration.objective", "mining.objective", 1)


# ---------------------------------------------------------------------------
# Readiness (P14-H01, P14-H04)
# ---------------------------------------------------------------------------


def derive_equipment(state: StateManager | None) -> dict[str, Any]:
    """Mining equipment, in three states that must never collapse into two.

    `role_fit()` is the one engine that reads the loadout; this maps its mining
    role rather than tokenising module names a second time. Its distinction
    between "fitted" and "not seen" is the whole point: with no loadout observed
    every capability is Unknown, and with one observed a capability still absent
    from it is reported as not observed in local data — which is a weaker claim
    than "you do not have it", and the correct one.
    """
    if state is None:
        return {
            "loadout_observed": False,
            "capabilities": {
                name: {
                    "label": CAPABILITY_LABELS[name],
                    "state": FIT_UNKNOWN,
                    "required": name in REQUIRED_CAPABILITIES,
                }
                for name in (*REQUIRED_CAPABILITIES, *SUPPORTING_CAPABILITIES)
            },
            "confirmed_missing_required": [],
            "unknown_capabilities": list(
                (*REQUIRED_CAPABILITIES, *SUPPORTING_CAPABILITIES)
            ),
            "caveat": "No local state, so the loadout is Unknown.",
        }

    fit = readiness_feature.role_fit(state)
    mining_role: dict[str, Any] = next(
        (role for role in fit["roles"] if role["role"] == "mining"),
        {"fitted": [], "not_observed": []},
    )
    observed = bool(fit.get("loadout_observed"))
    fitted = set(mining_role.get("fitted") or [])

    capabilities: dict[str, dict[str, Any]] = {}
    confirmed_missing_required: list[str] = []
    unknown: list[str] = []
    for name in (*REQUIRED_CAPABILITIES, *SUPPORTING_CAPABILITIES):
        if not observed:
            fit_state = FIT_UNKNOWN
        elif name in fitted:
            fit_state = FIT_FITTED
        else:
            # A loadout WAS observed and this capability was not in it. That is
            # the strongest negative claim the data supports, and it is still
            # phrased as "not observed" rather than "absent".
            fit_state = FIT_NOT_OBSERVED
        capabilities[name] = {
            "label": CAPABILITY_LABELS[name],
            "state": fit_state,
            "required": name in REQUIRED_CAPABILITIES,
        }
        if fit_state == FIT_UNKNOWN:
            unknown.append(name)
        elif fit_state == FIT_NOT_OBSERVED and name in REQUIRED_CAPABILITIES:
            confirmed_missing_required.append(name)

    return {
        "loadout_observed": observed,
        "modules_observed": fit.get("modules_observed"),
        "capabilities": capabilities,
        "confirmed_missing_required": confirmed_missing_required,
        "unknown_capabilities": unknown,
        "caveat": fit.get("caveat"),
    }


def derive_limpets(cargo: dict[str, Any]) -> dict[str, Any]:
    """Limpets aboard, as a count and never as an inference.

    Cargo capacity is not a limpet count, and a hold full of limpets says
    nothing about which controllers are fitted to launch them. Those are two
    separate facts and they are reported separately.
    """
    if not cargo.get("observed"):
        return {
            "count": None,
            "state": FIT_UNKNOWN,
            "detail": "Cargo manifest not observed, so limpets are Unknown.",
        }
    count = int(cargo.get("limpets") or 0)
    return {
        "count": count,
        "state": FIT_FITTED if count else FIT_NOT_OBSERVED,
        "detail": (
            f"{count} limpets aboard."
            if count
            else "No limpets in the observed manifest."
        ),
    }


# ---------------------------------------------------------------------------
# Target and fill progress (P14-H02, P14-H03)
# ---------------------------------------------------------------------------


def derive_target(
    objective: dict[str, Any] | None, cargo: dict[str, Any]
) -> dict[str, Any]:
    """The Commander's SELECTED mining target, and progress toward it.

    The commodity and quantity come from structured columns the Commander chose
    from — never from reading their objective sentence. Without a selection this
    reports no target and says so; it does not invent one from whatever happens
    to be the largest thing in the hold.
    """
    record = (objective or {}).get("objective") or {}
    commodity = record.get("target_commodity")
    quantity = record.get("target_quantity")

    if not commodity:
        return {
            "selected": False,
            "commodity": None,
            "quantity": None,
            "held": None,
            "percent": None,
            "reached": None,
            "reason": (
                "No target commodity selected. Fill progress needs a target the "
                "Commander chose; it is not guessed from the hold."
            ),
        }

    key = economy.commodity_key(commodity)
    held = None
    if cargo.get("observed"):
        held = sum(
            entry["count"]
            for entry in (cargo.get("sellable") or [])
            if entry["key"] == key
        )

    percent = None
    reached = None
    if quantity and held is not None:
        percent = min(100, int(round(held * 100 / quantity)))
        reached = held >= quantity

    return {
        "selected": True,
        "commodity": commodity,
        "commodity_key": key,
        "quantity": quantity,
        "held": held,
        "percent": percent,
        "reached": reached,
        "reason": (
            None
            if held is not None
            else (
                "Cargo manifest not observed, so progress toward the target is Unknown."
            )
        ),
    }


# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------


def derive_stage(
    *,
    cargo: dict[str, Any],
    equipment: dict[str, Any],
    limpets: dict[str, Any],
    target: dict[str, Any],
    yield_facts: dict[str, Any],
    docked: bool,
    hold_full: bool | None,
) -> tuple[str, str]:
    """Return `(stage, detail)` — the first gate that holds."""
    if not cargo.get("observed"):
        return (
            STAGE_UNKNOWN,
            cargo.get("reason")
            or "Local cargo has not been observed, so the mining state is Unknown.",
        )

    mined_tonnes = _mined_aboard(cargo, yield_facts)

    # Selling and returning outrank preparation, and the order matters. A
    # Commander docked with a hold of mined platinum has necessarily spent their
    # limpets getting it; telling them "Prepare: no limpets" at that moment
    # describes the *next* run while the current one is still waiting to be
    # sold. Preparation gates a run that has not started, never one whose cargo
    # is already aboard.
    if mined_tonnes and docked:
        return (
            STAGE_SELL,
            f"Docked with {mined_tonnes} t of mined cargo aboard.",
        )
    if mined_tonnes and (hold_full or target.get("reached")):
        reason = "hold full" if hold_full else "target reached"
        return (
            STAGE_RETURN,
            f"{mined_tonnes} t aboard and the {reason}. Return to a market to sell.",
        )

    missing = equipment.get("confirmed_missing_required") or []
    if missing:
        names = ", ".join(CAPABILITY_LABELS[name] for name in missing)
        return (
            STAGE_PREPARE,
            f"{names} not observed in the loadout, so laser mining cannot be "
            "completed as configured.",
        )
    if limpets.get("state") == FIT_NOT_OBSERVED:
        return (
            STAGE_PREPARE,
            "No limpets aboard. Collecting what is cracked needs them.",
        )

    if mined_tonnes or not docked:
        if target.get("selected") and target.get("percent") is not None:
            return (
                STAGE_EXTRACT,
                f"{target['held']} of {target['quantity']} t "
                f"{target['commodity']} aboard ({target['percent']}%).",
            )
        return (
            STAGE_EXTRACT,
            f"{mined_tonnes} t of mined cargo aboard."
            if mined_tonnes
            else "Equipped to mine. No mined cargo aboard yet.",
        )

    if yield_facts.get("total_tonnes"):
        return (
            STAGE_COMPLETE_READY,
            f"{yield_facts['total_tonnes']} t refined in the recorded history, "
            "and no mined cargo remains aboard.",
        )
    return (
        STAGE_EXTRACT,
        "Equipped to mine. No mined cargo aboard yet.",
    )


def _mined_aboard(cargo: dict[str, Any], yield_facts: dict[str, Any]) -> int:
    """Tonnes aboard of commodities the recorder actually saw being refined.

    Cargo that was bought, hauled or already aboard is not counted. Where the
    recorder has no refining history at all this is zero, which is a statement
    about the *recorded* history rather than about the hold — the hold's own
    contents are reported separately and in full.
    """
    if not cargo.get("observed") or not yield_facts.get("observed"):
        return 0
    refined_keys = set(yield_facts.get("by_commodity") or {})
    return sum(
        entry["count"]
        for entry in (cargo.get("sellable") or [])
        if entry["key"] in refined_keys
    )


# ---------------------------------------------------------------------------
# Derived step
# ---------------------------------------------------------------------------


def derive_step(
    *,
    stage: str,
    equipment: dict[str, Any],
    limpets: dict[str, Any],
    target: dict[str, Any],
    market: dict[str, Any],
) -> dict[str, Any] | None:
    if stage == STAGE_UNKNOWN:
        return None

    base = {"owner": "derived", "state": "active"}

    if stage == STAGE_PREPARE:
        missing = equipment.get("confirmed_missing_required") or []
        if missing:
            name = CAPABILITY_LABELS[missing[0]]
            return {
                **base,
                "objective_id": _identity("fit_equipment", missing[0]),
                "kind": "fit_equipment",
                "label": f"Outfit a {name.lower()}",
                "target": name,
                "target_kind": "module",
                "source_id": economy.TRUTH_LOCAL_TELEMETRY,
            }
        return {
            **base,
            "objective_id": _identity("restock_limpets"),
            "kind": "restock_limpets",
            "label": "Restock limpets before mining",
            "target": "Limpet",
            "target_kind": "commodity",
            "source_id": economy.TRUTH_LOCAL_SCREEN_SNAPSHOT,
        }

    if stage == STAGE_EXTRACT:
        if target.get("selected"):
            return {
                **base,
                "objective_id": _identity("extract", target.get("commodity_key")),
                "kind": "extract",
                "label": f"Extract {target['commodity']}"
                + (
                    f" — {target['held']} of {target['quantity']} t"
                    if target.get("quantity") and target.get("held") is not None
                    else ""
                ),
                "target": target["commodity"],
                "target_kind": "commodity",
                "source_id": economy.TRUTH_LOCAL_SCREEN_SNAPSHOT,
            }
        return {
            **base,
            "objective_id": _identity("select_target"),
            "kind": "select_target",
            "label": "Select a target commodity for this mining session",
            "target": None,
            "target_kind": None,
            "source_id": "commander_entered",
        }

    if stage == STAGE_RETURN:
        return {
            **base,
            "objective_id": _identity("return_to_market"),
            "kind": "return_to_market",
            "label": "Plot a route to a market",
            "target": None,
            "target_kind": None,
            "source_id": "local_navroute",
        }

    if stage == STAGE_SELL:
        station = market.get("station_name")
        return {
            **base,
            "objective_id": _identity("sell_mined", station),
            "kind": "sell_mined",
            "label": (
                f"Review the sale at {station}"
                if station and market.get("scope") == economy.SCOPE_CURRENT_STATION
                else "Open the commodities market to price this cargo"
            ),
            "target": station,
            "target_kind": "station",
            "source_id": economy.TRUTH_LOCAL_SCREEN_SNAPSHOT,
        }

    return {
        **base,
        "objective_id": _identity("session_complete"),
        "kind": "session_complete",
        "label": "Start a new mining run",
        "target": None,
        "target_kind": None,
        "source_id": economy.TRUTH_LOCAL_EVENT_HISTORY,
    }


# ---------------------------------------------------------------------------
# Work remaining, blockers, completion
# ---------------------------------------------------------------------------


def derive_work_remaining(
    *,
    stage: str,
    cargo: dict[str, Any],
    equipment: dict[str, Any],
    limpets: dict[str, Any],
    target: dict[str, Any],
    yield_facts: dict[str, Any],
) -> list[dict[str, Any]]:
    if stage == STAGE_UNKNOWN:
        return [
            {
                "id": "mining.unknown.cargo",
                "label": "Mining state Unknown",
                "detail": cargo.get("reason") or "Local cargo has not been observed.",
                "kind": WORK_KIND_UNKNOWN,
            }
        ]

    items: list[dict[str, Any]] = []

    if (
        target.get("selected")
        and target.get("quantity")
        and target.get("held") is not None
    ):
        remaining = max(0, int(target["quantity"]) - int(target["held"]))
        if remaining:
            items.append(
                {
                    "id": "mining.target.remaining",
                    "label": f"{remaining} t of {target['commodity']} remaining",
                    "detail": (
                        f"{target['held']} of {target['quantity']} t aboard "
                        f"({target['percent']}%)."
                    ),
                    "kind": WORK_KIND_WORK,
                }
            )
    elif not target.get("selected"):
        items.append(
            {
                "id": "mining.target.unselected",
                "label": "No target commodity selected",
                "detail": target.get("reason") or "",
                "kind": WORK_KIND_UNKNOWN,
            }
        )

    unknown_caps = equipment.get("unknown_capabilities") or []
    if unknown_caps:
        items.append(
            {
                "id": "mining.equipment.unknown",
                "label": f"{len(unknown_caps)} mining capability(s) Unknown",
                "detail": (
                    "No loadout has been observed, so fitted equipment cannot be "
                    "judged. That is not a claim the ship lacks it."
                    if not equipment.get("loadout_observed")
                    else "Not seen in the observed loadout."
                ),
                "kind": WORK_KIND_UNKNOWN,
            }
        )

    if limpets.get("state") == FIT_UNKNOWN:
        items.append(
            {
                "id": "mining.limpets.unknown",
                "label": "Limpets Unknown",
                "detail": limpets.get("detail") or "",
                "kind": WORK_KIND_UNKNOWN,
            }
        )

    if not yield_facts.get("observed"):
        items.append(
            {
                "id": "mining.yield.unknown",
                "label": "Refined tonnage Unknown",
                "detail": yield_facts.get("reason")
                or "The local recorder did not answer.",
                "kind": WORK_KIND_UNKNOWN,
            }
        )

    # Hotspot coverage is a limit on what is known, not outstanding work and not
    # a blocker. It is stated once, here, rather than shouted from the Blockers
    # slot (R6-13, R6-17).
    items.append(
        {
            "id": "mining.location.coverage",
            "label": "Ring and hotspot quality not known",
            "detail": HOTSPOT_UNSUPPORTED,
            "kind": WORK_KIND_UNKNOWN,
        }
    )
    return items


def derive_blockers(
    *,
    stage: str,
    cargo: dict[str, Any],
    equipment: dict[str, Any],
    limpets: dict[str, Any],
    route_active: bool,
) -> list[dict[str, Any]]:
    """Only what genuinely stops this workflow.

    A hold that is not yet full is work. Unknown module coverage is Unknown. The
    absence of a hotspot-quality source is a coverage limit that no Commander
    action can clear, so it is never a blocker. What does block: equipment the
    observed loadout shows is not there, no limpets to collect with, and — at
    the return step and only there — no route.
    """
    blockers: list[dict[str, Any]] = []

    if not cargo.get("observed"):
        blockers.append(
            {
                "blocker_id": "mining.blocker.cargo-unavailable",
                "label": "Cargo manifest unavailable",
                "detail": cargo.get("reason")
                or "No local cargo snapshot has been observed.",
                "kind": "source_unavailable",
                "source_id": None,
                "condition_id": CONDITION_CARGO,
            }
        )
        return blockers

    for name in equipment.get("confirmed_missing_required") or []:
        blockers.append(
            {
                "blocker_id": f"mining.blocker.equipment.{name}",
                "label": f"{CAPABILITY_LABELS[name]} not observed in the loadout",
                "detail": (
                    "A loadout was observed and this module was not in it. "
                    "Laser mining needs it to complete."
                ),
                "kind": "equipment_missing",
                "source_id": "local_telemetry",
                "condition_id": CONDITION_EQUIPMENT,
            }
        )

    if limpets.get("state") == FIT_NOT_OBSERVED:
        blockers.append(
            {
                "blocker_id": "mining.blocker.no-limpets",
                "label": "No limpets aboard",
                "detail": (
                    "The observed manifest carries no limpets, so nothing can be "
                    "collected from a cracked asteroid."
                ),
                "kind": "consumable_missing",
                "source_id": "local_screen_snapshot",
                "condition_id": CONDITION_LIMPETS,
            }
        )

    if stage == STAGE_RETURN and not route_active:
        blockers.append(
            {
                "blocker_id": "mining.blocker.no-route",
                "label": "No route to a market",
                "detail": (
                    "Returning is the remaining step and no route is plotted. "
                    "Navigation owns route planning."
                ),
                "kind": "no_route",
                "source_id": "local_navroute",
                "condition_id": CONDITION_ROUTE,
            }
        )

    return blockers


def derive_completion(
    *, stage: str, cargo: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any]:
    if stage == STAGE_UNKNOWN:
        return {
            "state": COMPLETION_UNKNOWN,
            "label": COMPLETION_LABELS[COMPLETION_UNKNOWN],
            "reason": cargo.get("reason") or "Local cargo has not been observed.",
        }
    if stage == STAGE_COMPLETE_READY:
        return {
            "state": COMPLETION_NO_KNOWN_WORK,
            "label": COMPLETION_LABELS[COMPLETION_NO_KNOWN_WORK],
            "reason": "No mined cargo remains aboard and no extraction step is open.",
        }
    if target.get("selected") and target.get("reached"):
        return {
            "state": COMPLETION_WORK_REMAINING,
            "label": COMPLETION_LABELS[COMPLETION_WORK_REMAINING],
            "reason": (
                f"Target of {target['quantity']} t {target['commodity']} reached; "
                "the sale is the remaining step."
            ),
        }
    return {
        "state": COMPLETION_WORK_REMAINING,
        "label": COMPLETION_LABELS[COMPLETION_WORK_REMAINING],
        "reason": "The mining workflow has steps outstanding.",
    }


# ---------------------------------------------------------------------------
# Session summary (P14-H06) and handoffs
# ---------------------------------------------------------------------------


def derive_session(
    *, yield_facts: dict[str, Any], sales: dict[str, Any], cargo: dict[str, Any]
) -> dict[str, Any]:
    """The factual summary a debrief will need. R9 owns the loop; this is input.

    Every figure names its own source, and the one figure that would be easiest
    to fake — tonnes mined — is the one derived strictly from recorded refining
    events rather than from the hold.
    """
    by_commodity = yield_facts.get("by_commodity") or {}
    top = sorted(by_commodity.values(), key=lambda e: -e["tonnes"])[:3]
    return {
        "refined_tonnes": yield_facts.get("total_tonnes"),
        "refined_observed": yield_facts.get("observed"),
        "refined_top": top,
        "refined_source": "MiningRefined journal events",
        "cargo_aboard": cargo.get("total_count") if cargo.get("observed") else None,
        "sales_recorded": sales.get("sales"),
        "sale_revenue": sales.get("revenue"),
        "realised_profit": sales.get("profit"),
        "profit_basis": sales.get("profit_basis"),
        "caveat": (
            "Refined tonnage counts recorded MiningRefined events, so cargo that "
            "was already aboard is never counted as mined. Revenue and profit "
            "come from recorded sales, not from a market snapshot."
        ),
    }


def derive_handoffs(
    *, target: dict[str, Any], market: dict[str, Any], cargo: dict[str, Any]
) -> list[dict[str, Any]]:
    handoffs: list[dict[str, Any]] = []
    commodity = target.get("commodity") or (
        (cargo.get("sellable") or [{}])[0].get("name")
        if cargo.get("observed")
        else None
    )
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
        "equipment": None,
        "limpets": None,
        "target": None,
        "cargo": None,
        "market": None,
        "yield_facts": None,
        "session": None,
        "work_remaining": [
            {
                "id": "mining.unknown.unavailable",
                "label": "Mining state Unknown",
                "detail": reason,
                "kind": WORK_KIND_UNKNOWN,
            }
        ],
        "blockers": [
            {
                "blocker_id": "mining.blocker.cargo-unavailable",
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
        "location_coverage": HOTSPOT_UNSUPPORTED,
        "handoffs": derive_handoffs(target={}, market={}, cargo={}),
        "caveat": WORKFLOW_CAVEAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def build_workflow(
    state: StateManager | None,
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    objective: dict[str, Any] | None = None,
    route_active: bool = False,
    cargo_path: Path | None = None,
    market_path: Path | None = None,
) -> dict[str, Any]:
    """Compose the Operations Mining workflow from local facts only."""
    cargo = economy.known_cargo(state, cargo_path=cargo_path)
    market = economy.observed_market(state, market_path=market_path)
    equipment = derive_equipment(state)
    limpets = derive_limpets(cargo)
    target = derive_target(objective, cargo)
    yield_facts = await economy.session_mining_yield(session_factory)
    sales = await economy.recorded_sales(session_factory)

    snap = getattr(state, "snapshot", None)
    docked = bool(getattr(snap, "is_docked", False)) if snap is not None else False
    capacity = cargo.get("capacity")
    total = cargo.get("total_count")
    hold_full = (
        None if capacity is None or total is None else int(total) >= int(capacity)
    )

    stage, detail = derive_stage(
        cargo=cargo,
        equipment=equipment,
        limpets=limpets,
        target=target,
        yield_facts=yield_facts,
        docked=docked,
        hold_full=hold_full,
    )
    step = derive_step(
        stage=stage,
        equipment=equipment,
        limpets=limpets,
        target=target,
        market=market,
    )
    work_remaining = derive_work_remaining(
        stage=stage,
        cargo=cargo,
        equipment=equipment,
        limpets=limpets,
        target=target,
        yield_facts=yield_facts,
    )
    blockers = derive_blockers(
        stage=stage,
        cargo=cargo,
        equipment=equipment,
        limpets=limpets,
        route_active=route_active,
    )
    completion = derive_completion(stage=stage, cargo=cargo, target=target)
    matches = economy.sell_matches(cargo, market)

    return {
        "available": True,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "stage_detail": detail,
        "step": step,
        "equipment": equipment,
        "limpets": limpets,
        "target": target,
        "cargo": {
            "observed": cargo["observed"],
            "event_timestamp": cargo.get("event_timestamp"),
            "vessel": cargo.get("vessel"),
            "reason": cargo["reason"],
            "capacity": capacity,
            "total_count": total,
            "hold_full": hold_full,
            "sellable_tonnes": cargo["sellable_tonnes"],
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
                "freshness",
                "event_timestamp",
                "truth_class",
            )
        },
        # The sell half of the return transition, using the same matcher Trade
        # uses. One join, two workflows, no second implementation to disagree.
        "sell_matches": [m for m in matches if m.get("in_snapshot")],
        "yield_facts": yield_facts,
        "session": derive_session(yield_facts=yield_facts, sales=sales, cargo=cargo),
        "work_remaining": work_remaining,
        "blockers": blockers,
        "completion": completion,
        "location_coverage": HOTSPOT_UNSUPPORTED,
        "handoffs": derive_handoffs(target=target, market=market, cargo=cargo),
        "caveat": WORKFLOW_CAVEAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
