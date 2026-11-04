"""Commander-observed route history — Phase 15 Navigation slice (LNA-024).

Read-only bounded query over the local flight recorder: the recent
sequence of recorded FSDJump / CarrierJump events as a jump timeline.
Truth class local_event_history — recorded sessions on this machine only;
never a complete travel history, and absence is not proof of non-travel.

Navigation owns movement (NRL-20): this module serves the Navigation
route surface. It reads only fields already verified for these events in
the local data registry (StarSystem, JumpDist, FuelUsed, FuelLevel per the
Elite Event Home Matrix FSDJump row); no route plotting, no NavRoute
writes, no game action, no providers. After-action route summaries remain
deferred per the branch coverage matrix.

LNA-003 (Commander flight history) asks for a flight log, not a list of
destinations. Distance and fuel are recorded on the event and were being
discarded here, so a Commander could see where they went but never how far
they travelled or what it cost. Both are surfaced per jump and totalled,
with the totals reporting how many jumps actually carried the field —
CarrierJump does not report a jump distance, and a total that quietly
treats a missing value as zero would understate the truth.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import JournalEvent

TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
SOURCE_FLIGHT_RECORDER = "Local session database (flight recorder)"

ROUTE_HISTORY_DEFAULT_LIMIT = 25
ROUTE_HISTORY_MAX_LIMIT = 200

_ROUTE_HISTORY_CAVEAT = (
    "Commander-observed jump timeline from recorded FSDJump and "
    "CarrierJump events on this machine. Recorded sessions only — not a "
    "complete travel history, and absence is not proof of non-travel."
)

# Frontier-native event names already recorded and handled elsewhere;
# matched verbatim against recorded rows. No new event names introduced.
_JUMP_EVENTS = ("FSDJump", "CarrierJump")


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return ROUTE_HISTORY_DEFAULT_LIMIT
    return max(1, min(ROUTE_HISTORY_MAX_LIMIT, limit))


def _iso_or_none(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _observed_number(value: Any) -> float | None:
    """Return a recorded numeric field, or None when it was not recorded.

    None means "the event did not carry this", never zero: a jump with no
    recorded distance is unknown, not a jump of no distance.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return round(float(value), 2)


async def route_history(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    """Recent recorded jump timeline, newest first (bounded)."""
    bounded_limit = _clamp_limit(limit)
    star_system = func.json_extract(JournalEvent.raw_json, "$.StarSystem")
    jump_distance = func.json_extract(JournalEvent.raw_json, "$.JumpDist")
    fuel_used = func.json_extract(JournalEvent.raw_json, "$.FuelUsed")
    fuel_level = func.json_extract(JournalEvent.raw_json, "$.FuelLevel")

    async with session_factory() as db:
        rows = (
            await db.execute(
                select(
                    JournalEvent.id,
                    JournalEvent.session_id,
                    JournalEvent.timestamp,
                    JournalEvent.event_type,
                    star_system.label("star_system"),
                    jump_distance.label("jump_distance_ly"),
                    fuel_used.label("fuel_used"),
                    fuel_level.label("fuel_level"),
                )
                .where(
                    JournalEvent.event_type.in_(_JUMP_EVENTS),
                    star_system.is_not(None),
                )
                .order_by(JournalEvent.timestamp.desc(), JournalEvent.id.desc())
                .limit(bounded_limit)
            )
        ).all()

    jumps = [
        {
            "id": row.id,
            "session_id": row.session_id,
            "timestamp": _iso_or_none(row.timestamp),
            "event_type": row.event_type,
            "star_system": row.star_system,
            "jump_distance_ly": _observed_number(row.jump_distance_ly),
            "fuel_used": _observed_number(row.fuel_used),
            "fuel_level": _observed_number(row.fuel_level),
        }
        for row in rows
    ]

    # Totals describe the jumps in this bounded window that actually carried
    # the field. `*_observed_in` is reported alongside so a partial total is
    # never mistaken for a complete travel figure.
    distances = [
        jump["jump_distance_ly"]
        for jump in jumps
        if jump["jump_distance_ly"] is not None
    ]
    fuel_costs = [jump["fuel_used"] for jump in jumps if jump["fuel_used"] is not None]
    summary = {
        "jumps_returned": len(jumps),
        "distance_ly_total": round(sum(distances), 2) if distances else None,
        "distance_observed_in": len(distances),
        "longest_jump_ly": max(distances) if distances else None,
        "fuel_used_total": round(sum(fuel_costs), 2) if fuel_costs else None,
        "fuel_observed_in": len(fuel_costs),
        "distinct_systems": len(
            {jump["star_system"] for jump in jumps if jump["star_system"]}
        ),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": _ROUTE_HISTORY_CAVEAT,
        "source_events": list(_JUMP_EVENTS),
        "returned": len(jumps),
        "limit": bounded_limit,
        "summary": summary,
        "jumps": jumps,
        "nullprovider_safe": True,
    }
