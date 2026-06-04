"""Phase 4 (PB04-06) combat-session HTTP endpoints.

Read-only snapshot of mission session, local conflict context, rewards/rank,
and loadout/munitions readiness derived from existing baseline state.

No public debrief-summary endpoint -- PB04-07 owns Debrief endpoint and
public consumption (a draft-only schema lives in
`omnicovas/features/combat_session.DEBRIEF_PAYLOAD_DRAFT_SCHEMA` for
PB04-07's reference only).

Mounted under prefix /combat-session by ApiBridge._build_app().
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

from omnicovas.features import combat_session

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

router = APIRouter(prefix="/combat-session", tags=["combat-session"])

_state: StateManager | None = None


def set_state_manager(state: StateManager) -> None:
    """Inject the live StateManager into this router."""
    global _state  # noqa: PLW0603
    _state = state


@router.get("/snapshot")
async def get_combat_session_snapshot() -> dict[str, Any]:
    """Return the current combat-session snapshot.

    Includes mission session scalars, active mission list, local conflict
    context, and rewards/rank session totals. Active CZ detection and CZ
    kind (low/medium/high) are intentionally absent -- Unsupported.
    """
    if _state is None:
        return combat_session.empty_snapshot_payload()
    return combat_session.snapshot_payload(_state)


@router.get("/loadout-readiness")
async def get_loadout_readiness() -> dict[str, Any]:
    """Return the current loadout/munitions readiness summary.

    Consume-only view of existing baseline state (modules, cargo, hull/
    modules value). Munitions row is rendered as 'No Verified Source' --
    no journal mechanism exposes ammunition counts.
    """
    if _state is None:
        return combat_session.empty_loadout_readiness_payload()
    return combat_session.loadout_readiness_payload(_state)
