"""Read-only PB05-04 Navigation snapshot endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from omnicovas.features import navigation

if TYPE_CHECKING:
    from omnicovas.core.activity_log import ActivityLog
    from omnicovas.core.state_manager import StateManager

router = APIRouter(prefix="/navigation", tags=["navigation"])

_state: StateManager | None = None
_activity_log: ActivityLog | None = None


def set_state_manager(state: StateManager) -> None:
    """Inject the live StateManager into this router."""
    global _state  # noqa: PLW0603
    _state = state


def set_activity_log(log: ActivityLog) -> None:
    """Inject the shared ActivityLog into this router."""
    global _activity_log  # noqa: PLW0603
    _activity_log = log


class RouteHopResponse(BaseModel):
    """Public NavRoute hop payload."""

    model_config = ConfigDict(extra="forbid")

    star_system: str
    star_class: str | None
    star_pos: list[float] | None


class ActiveRouteStateResponse(BaseModel):
    """Public active route state payload."""

    model_config = ConfigDict(extra="forbid")

    origin: str | None
    destination: str | None
    next_hop: str | None
    total_hops: int | None
    route_state: str
    hops: list[RouteHopResponse]
    freshness_label: str
    truth_class: str
    source_id: str
    observed_at: str | None
    fallback: str | None
    caveat: str | None
    nullprovider_safe: bool


class NavigationSnapshotResponse(BaseModel):
    """Public Navigation snapshot payload."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    active_route: ActiveRouteStateResponse
    spansh_url: str | None
    current_system: str | None
    current_station: str | None
    nullprovider_safe: bool


@router.get("/snapshot", response_model=NavigationSnapshotResponse)
async def get_navigation_snapshot() -> dict[str, Any]:
    """Return the current first-wave Navigation snapshot from local NavRoute.json."""
    return navigation.snapshot_payload(state=_state)
