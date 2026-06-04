"""GET /combat/snapshot returns combat target/threat/session provenance fields."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from omnicovas.features import combat_state

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

router = APIRouter(prefix="/combat", tags=["combat"])

_state: StateManager | None = None


def set_state_manager(state: StateManager) -> None:
    """Inject the live StateManager into this router."""
    global _state  # noqa: PLW0603
    _state = state


@router.get("/snapshot")
async def get_combat_snapshot() -> dict[str, Any]:
    """Return the current Combat Target & Threat snapshot."""
    if _state is None:
        return combat_state.empty_snapshot_payload()
    return combat_state.snapshot_payload(_state)
