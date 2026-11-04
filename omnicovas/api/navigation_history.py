"""Read-only Navigation route-history endpoint over the local flight recorder.

Phase 15 Navigation slice (PB15-02; LNA-024): the recent commander-observed
jump timeline. Local-only bounded query over existing tables — no new
persistence, no migrations, no NavRoute writes, no route plotting, no
providers, no Activity Log producers.

See: omnicovas/api/navigation_bookmarks.py (session-factory pattern)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.features import navigation_history

router = APIRouter(prefix="/navigation", tags=["navigation"])

_session_factory: async_sessionmaker[AsyncSession] | None = None


def set_session_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    """Inject the live async session factory into this router."""
    global _session_factory  # noqa: PLW0603
    _session_factory = session_factory


def _ensure_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Flight recorder persistence not initialized",
        )
    return _session_factory


class RouteHistoryJumpRow(BaseModel):
    """One recorded jump observation."""

    model_config = ConfigDict(extra="forbid")

    id: int
    session_id: int
    timestamp: str | None
    event_type: str
    star_system: str
    # None means the event did not record the field, never zero.
    jump_distance_ly: float | None
    fuel_used: float | None
    fuel_level: float | None


class RouteHistorySummary(BaseModel):
    """Totals across the returned window, with their observed coverage."""

    model_config = ConfigDict(extra="forbid")

    jumps_returned: int
    distance_ly_total: float | None
    distance_observed_in: int
    longest_jump_ly: float | None
    fuel_used_total: float | None
    fuel_observed_in: int
    distinct_systems: int


class RouteHistoryResponse(BaseModel):
    """Commander-observed jump timeline (newest first, bounded)."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    source_events: list[str]
    returned: int
    limit: int
    summary: RouteHistorySummary
    jumps: list[RouteHistoryJumpRow]
    nullprovider_safe: bool


@router.get("/route-history", response_model=RouteHistoryResponse)
async def get_route_history(
    limit: int | None = Query(
        default=None, ge=1, le=navigation_history.ROUTE_HISTORY_MAX_LIMIT
    ),
) -> dict[str, Any]:
    """Recent commander-observed jump timeline (local flight recorder)."""
    factory = _ensure_session_factory()
    return await navigation_history.route_history(factory, limit=limit)
