"""Commander Context: one read-only answer to "where is the Commander, and how sure?"

GKI-04.  This module owns no state and reads no file of its own.  It gathers what the
existing projections already hold:

* ``StateManager`` — the Journal-owned ``local_system_context`` (FSDJump, CarrierJump,
  Location: StarSystem, SystemAddress, StarPos, Body, BodyID) and
  ``local_station_context`` (Docked, Location while docked: StationName, MarketID),
  the ship identity fields and their field sources;
* Commander Memory's active profile key (the pseudonymous commander boundary);
* the Navigation feature's NavRoute projection, when the caller supplies it;
* Engineering's portfolio, through :func:`engineering_context`.

Each location level reports a ``state``:

``current``
    The latest projection for that level, while the Commander's Journal is live
    (an event within :data:`LIVE_WINDOW_SECONDS`).
``last_known``
    The latest projection, but the Journal is not live, so it may no longer hold.
``historical``
    The latest projection is older than :data:`HISTORICAL_AFTER_SECONDS`.
``unknown``
    Nothing observed, or the projection was cleared (for example by Undocked).

Identity says how the level was identified: by a stable Journal identifier
(``system_address``, ``market_id``, ``body_id``) or by ``name`` only.  Nothing is
inferred: a surface position is reported ``unknown`` because no existing projection
keeps one, and an old Journal entry never becomes the present location.

Intended consumers: Galactic Intelligence (GKI-04), Farming Intelligence (GKI-05),
Navigation and Galactic Road Trips (GKI-06), the Commander Chronicle (GKI-07) and
Engineering acquisition planning.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.state_manager import StateManager

JsonDict = dict[str, Any]

VERSION = "commander-context-v1"
LIVE_WINDOW_SECONDS = 15 * 60
HISTORICAL_AFTER_SECONDS = 24 * 60 * 60
STATES = ("current", "last_known", "historical", "unknown")


def parse_timestamp(value: Any) -> datetime | None:
    """A Journal ``timestamp`` as an aware UTC datetime, or None."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def journal_is_live(last_event_at: datetime | None, now: datetime) -> bool:
    """True while the Commander's Journal has produced an event recently."""
    if last_event_at is None:
        return False
    return 0 <= (now - last_event_at).total_seconds() <= LIVE_WINDOW_SECONDS


def classify(observed_at: datetime | None, *, live: bool, now: datetime) -> str:
    """The freshness state of the latest projection for one level."""
    if observed_at is None:
        return "unknown"
    if live:
        return "current"
    if (now - observed_at).total_seconds() > HISTORICAL_AFTER_SECONDS:
        return "historical"
    return "last_known"


def _unknown(reason: str) -> JsonDict:
    return {"state": "unknown", "reason": reason}


def build(
    state: StateManager,
    *,
    profile_key: str | None,
    last_journal_event_at: datetime | None,
    navigation: JsonDict | None = None,
    now: datetime | None = None,
) -> JsonDict:
    """The Commander's context from existing projections; never writes anything."""
    now = now or datetime.now(timezone.utc)
    live = journal_is_live(last_journal_event_at, now)
    snapshot = state.snapshot
    system_ctx = snapshot.local_system_context
    station_ctx = snapshot.local_station_context

    if system_ctx is not None and system_ctx.star_system:
        observed = parse_timestamp(system_ctx.event_timestamp)
        system: JsonDict = {
            "state": classify(observed, live=live, now=now),
            "name": system_ctx.star_system,
            "system_address": system_ctx.system_address,
            "star_pos": list(system_ctx.star_pos) if system_ctx.star_pos else None,
            "identity": "system_address"
            if system_ctx.system_address is not None
            else "name",
            "observed_at": iso(observed),
            "source_event": system_ctx.source_event,
        }
        if system_ctx.body:
            body: JsonDict = {
                "state": system["state"],
                "name": system_ctx.body,
                "body_id": system_ctx.body_id,
                "body_type": system_ctx.body_type,
                # BodyID identifies a body only within its SystemAddress.
                "identity": "body_id"
                if system_ctx.body_id is not None
                and system_ctx.system_address is not None
                else "name",
                "observed_at": iso(observed),
                "source_event": system_ctx.source_event,
            }
        else:
            body = _unknown("No body in the latest system observation.")
    else:
        system = _unknown("No system observed in this Journal session.")
        body = _unknown("No system observed in this Journal session.")

    if station_ctx is not None and station_ctx.station_name:
        observed = parse_timestamp(station_ctx.event_timestamp)
        station: JsonDict = {
            "state": classify(observed, live=live, now=now),
            "name": station_ctx.station_name,
            "station_type": station_ctx.station_type,
            "market_id": station_ctx.market_id,
            "system": station_ctx.star_system,
            "system_address": station_ctx.system_address,
            "docked": station_ctx.is_docked is not False,
            "identity": "market_id" if station_ctx.market_id is not None else "name",
            "observed_at": iso(observed),
            "source_event": station_ctx.source_event,
        }
    else:
        station = _unknown("Not docked, or no docking observed.")
    # A later arrival in another system means the Commander has left that station,
    # even if no Undocked event was seen; never report two places at once.
    if (
        station["state"] != "unknown"
        and system["state"] != "unknown"
        and station.get("system_address") is not None
        and system.get("system_address") is not None
        and station["system_address"] != system["system_address"]
        and (system.get("observed_at") or "") >= (station.get("observed_at") or "")
    ):
        station = _unknown("A later jump left the station's system.")

    ship_source = state.get_field_source("current_ship_type")
    ship_observed = parse_timestamp(ship_source.timestamp) if ship_source else None
    if snapshot.current_ship_type:
        ship: JsonDict = {
            "state": classify(ship_observed, live=live, now=now),
            "type": snapshot.current_ship_type,
            "name": snapshot.current_ship_name,
            "ident": snapshot.current_ship_ident,
            "jump_range_ly": snapshot.jump_range_ly,
            "cargo_capacity": snapshot.cargo_capacity,
            "observed_at": iso(ship_observed),
        }
    else:
        ship = _unknown("No ship identity observed.")

    if (
        navigation
        and navigation.get("destination")
        and navigation.get("route_state") == "active"
    ):
        # NavRoute.json describes the route as last plotted; the Navigation
        # feature owns its freshness, so the route is never more than last known
        # unless the Journal is live.
        route_observed = parse_timestamp(navigation.get("observed_at"))
        route: JsonDict = {
            "state": classify(route_observed or now, live=live, now=now)
            if route_observed is not None
            else "last_known",
            "destination": navigation.get("destination"),
            "origin": navigation.get("origin"),
            "total_hops": navigation.get("total_hops"),
            "observed_at": iso(route_observed),
            "source": navigation.get("source_id") or "NavRoute.json",
        }
    else:
        route = _unknown("No plotted route observed.")

    return {
        "version": VERSION,
        "generated_at": iso(now),
        "commander": {"profile_key": profile_key, "known": profile_key is not None},
        "journal": {"last_event_at": iso(last_journal_event_at), "live": live},
        "system": system,
        "station": station,
        "body": body,
        "surface": _unknown(
            "No existing projection keeps a surface position, so arrival at a "
            "surface site cannot be confirmed."
        ),
        "ship": ship,
        "navigation": route,
    }


def observation(context: JsonDict) -> JsonDict:
    """The location fields a knowledge lookup may use, in Journal terms.

    Only levels that are not ``unknown`` contribute, and a station contributes only
    while the Commander is docked there.
    """
    seen: JsonDict = {}
    system = context["system"]
    if system["state"] != "unknown":
        seen["system"] = system["name"]
        seen["system_address"] = system.get("system_address")
    station = context["station"]
    if station["state"] != "unknown" and station.get("docked"):
        seen["station"] = station["name"]
        seen["market_id"] = station.get("market_id")
        seen.setdefault("system", station.get("system"))
        if seen.get("system_address") is None:
            seen["system_address"] = station.get("system_address")
    body = context["body"]
    if body["state"] != "unknown":
        seen["body"] = body["name"]
        seen["body_id"] = body.get("body_id")
    return {key: value for key, value in seen.items() if value is not None}


async def engineering_context(
    session_factory: async_sessionmaker[AsyncSession],
    state: StateManager,
) -> JsonDict:
    """Active Engineering builds and their material shortfalls, from the portfolio.

    Reuses the Materials workspace's own allocation; an unknown inventory stays
    unknown and never becomes zero.
    """
    from omnicovas.features import engineering, engineering_progression

    builds = await engineering.list_build_plans(session_factory)
    goals = await engineering.list_goals(session_factory)
    progression = await engineering_progression.portfolio(
        session_factory,
        builds,
        goals,
        state.public_snapshot(),
        include_workbenches=False,
    )
    shortages = [
        {
            "build_plan_id": build["build_plan_id"],
            "build": build["title"],
            "material_id": row.get("material_id"),
            "deficit": row.get("deficit"),
        }
        for build in progression.get("builds", [])
        for row in build.get("materials", [])
        if row.get("deficit") is None or row.get("deficit") > 0
    ]
    inventory = progression.get("inventory") or {}
    return {
        "active_builds": len(progression.get("builds", [])),
        "inventory_state": inventory.get("state") or "unavailable",
        "shortages": shortages,
    }
