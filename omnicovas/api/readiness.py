"""Operation readiness endpoints — LNA-028 contract, LNA-022 ship profile.

Read-only projection over StateManager. One computation, three consumers
(Operations, Dashboard, Engineering), so the answer cannot drift between
surfaces the way ship vitals did.

No persistence, no providers, no game action.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from omnicovas.core.state_manager import StateManager
from omnicovas.features import readiness

router = APIRouter(prefix="/readiness", tags=["readiness"])

_state: StateManager | None = None


def set_state_manager(state: StateManager | None) -> None:
    """Inject the one StateManager owned by the bridge."""
    global _state  # noqa: PLW0603
    _state = state


def _ensure_state() -> StateManager:
    if _state is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Local telemetry state is unavailable.",
        )
    return _state


class ReadinessCheckRow(BaseModel):
    """One readiness answer, naming the state field it read."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    value: str | None
    status: str
    note: str | None
    read_from: str
    source: str
    truth_class: str


class ReadinessResponse(BaseModel):
    """Readiness for one operation."""

    model_config = ConfigDict(extra="forbid")

    operation: str
    operations: list[str]
    summary: str
    attention_count: int
    unknown_count: int
    ready_count: int
    checks: list[ReadinessCheckRow]
    source: str
    truth_class: str
    caveat: str
    nullprovider_safe: bool


class RoleFitRow(BaseModel):
    """Evidence that the observed loadout suits one role."""

    model_config = ConfigDict(extra="forbid")

    role: str
    fitted: list[str]
    # Not "missing": the capability was not seen, which is not proof of absence.
    not_observed: list[str]
    status: str


class RoleFitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    loadout_observed: bool
    modules_observed: int
    roles: list[RoleFitRow]
    missing_facts: list[str]
    caveat: str


class ShipProfileResponse(BaseModel):
    """Current ship facts, what is unobserved, and role fit."""

    model_config = ConfigDict(extra="forbid")

    source: str
    truth_class: str
    facts: dict[str, Any]
    missing_facts: list[str]
    role_fit: RoleFitBody
    caveat: str
    nullprovider_safe: bool
    watch: dict[str, Any]


@router.get("", response_model=ReadinessResponse)
async def get_readiness(
    operation: str | None = Query(default=None, max_length=32),
) -> dict[str, Any]:
    """Readiness checks for one operation (local telemetry only)."""
    state = _ensure_state()
    try:
        return readiness.evaluate(state, operation=operation)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("/ship-profile", response_model=ShipProfileResponse)
async def get_ship_profile() -> dict[str, Any]:
    """Current ship profile with role fit and unobserved facts (LNA-022)."""
    return readiness.ship_profile(_ensure_state())
