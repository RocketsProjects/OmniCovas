"""Commander-authored system notes API — LNA-004 notes slice.

Writing and clearing a single note are ordinary edits: the Commander is
changing their own sentence and can change it straight back. Destroying every
note is different — nothing in the app can reconstruct authored text — so the
bulk clear goes through the one shared Week 13 Confirmation Gate, exactly like
a Commander Memory destructive action.

Export is offered so the Commander can take their notes with them before
deciding to destroy them (Law 8).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from omnicovas.api import week13
from omnicovas.core.event_types import (
    SYSTEM_NOTE_PROPOSAL_BLOCKED,
    SYSTEM_NOTE_PROPOSAL_CANCELED,
    SYSTEM_NOTE_PROPOSAL_CONFIRMED,
    SYSTEM_NOTE_PROPOSAL_SHOWN,
)
from omnicovas.features.system_notes import (
    NOTE_MAX_LENGTH,
    SYSTEM_NAME_MAX_LENGTH,
    SystemNoteService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system-notes", tags=["system-notes"])

SYSTEM_NOTE_ACTION_TYPE = "system_note_protected_action"
week13.register_outcome_action_type(
    SYSTEM_NOTE_ACTION_TYPE,
    confirmed_event=SYSTEM_NOTE_PROPOSAL_CONFIRMED,
    canceled_event=SYSTEM_NOTE_PROPOSAL_CANCELED,
    blocked_event=SYSTEM_NOTE_PROPOSAL_BLOCKED,
)

_PROPOSAL_TTL_SECONDS = 300
_MAX_PENDING_ACTIONS = 8

_service: SystemNoteService | None = None
_pending: dict[str, dict[str, Any]] = {}


def set_system_note_service(service: SystemNoteService | None) -> None:
    """Inject the one service instance built by the bridge."""
    global _service  # noqa: PLW0603
    _service = service


def reset_pending_actions() -> None:
    """Clear pending proposals. Test seam; not an HTTP surface."""
    _pending.clear()


def _notes() -> SystemNoteService:
    if _service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Commander system notes are unavailable.",
        )
    return _service


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SystemNoteWrite(BaseModel):
    """Commander-authored note text for one system."""

    model_config = ConfigDict(extra="forbid")

    note: str = Field(default="", max_length=NOTE_MAX_LENGTH)


class AuthorizationRequest(BaseModel):
    """A Commander decision being spent."""

    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=1, max_length=128)


@router.get("")
async def list_system_notes() -> dict[str, Any]:
    """Every Commander-authored system note."""
    return await _notes().list_notes()


@router.put("/{star_system}")
async def write_system_note(star_system: str, body: SystemNoteWrite) -> dict[str, Any]:
    """Save the Commander's note for one system. Empty text removes it."""
    if len(star_system) > SYSTEM_NAME_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="star_system is too long.",
        )
    try:
        return await _notes().write(star_system, body.note)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.delete("/{star_system}")
async def delete_system_note(star_system: str) -> dict[str, Any]:
    """Remove one note. Reversible by writing it again; not gated."""
    try:
        return await _notes().delete(star_system)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("/export")
async def export_system_notes() -> dict[str, Any]:
    """Stage every note for local download (Law 8: take your data with you)."""
    return await _notes().export_payload()


@router.post("/actions/propose")
async def propose_clear_all() -> dict[str, Any]:
    """Propose destroying every note. Authorizes nothing by itself."""
    service = _notes()
    _sweep_expired()
    if (
        week13.count_pending_by_action_type(SYSTEM_NOTE_ACTION_TYPE)
        >= _MAX_PENDING_ACTIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many system-note actions are awaiting a decision.",
        )
    total = await service.count()
    expires_at = _now() + timedelta(seconds=_PROPOSAL_TTL_SECONDS)
    confirmation_id = week13.enqueue_confirmation(
        suggestion_text=(
            f"Delete every Commander system note? {total} note"
            f"{'' if total == 1 else 's'} would be destroyed."
        ),
        why_text=(
            "These notes were written by you. Nothing in OmniCOVAS can "
            "reconstruct them from the flight recorder, which never held "
            "them. Export them first if you want to keep a copy."
        ),
        timeout_at=expires_at.isoformat(),
        action_type=SYSTEM_NOTE_ACTION_TYPE,
        metadata={"note_count": total},
    )
    _pending[confirmation_id] = {"expires_at": expires_at}
    service._log(  # noqa: SLF001 - same-feature proof write
        SYSTEM_NOTE_PROPOSAL_SHOWN,
        "Commander system-note deletion proposed; nothing authorized",
        {"confirmation_id": confirmation_id, "note_count": total, "authorized": False},
    )
    return {
        "status": "pending_commander_confirmation",
        "confirmation_id": confirmation_id,
        "authorized": False,
        "note_count": total,
        "timeout_at": expires_at.isoformat(),
    }


@router.post("/actions/authorize")
async def authorize_clear_all(body: AuthorizationRequest) -> dict[str, Any]:
    """Spend a CONFIRMED decision and clear every note. Fail-closed."""
    service = _notes()
    _sweep_expired()
    confirmation_id = body.confirmation_id
    if confirmation_id not in _pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unknown, expired, or already-used confirmation.",
        )

    outcome = week13.peek_confirmation_outcome(
        confirmation_id, expected_action_type=SYSTEM_NOTE_ACTION_TYPE
    )
    if outcome is None:
        pending = week13.peek_pending_confirmation(
            confirmation_id, expected_action_type=SYSTEM_NOTE_ACTION_TYPE
        )
        if pending is not None:
            return {"status": "pending_commander_confirmation", "authorized": False}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No consumable Commander decision for this confirmation.",
        )

    if outcome != week13.CONFIRMATION_OUTCOME_CONFIRMED:
        week13.consume_confirmation_outcome(
            confirmation_id, expected_action_type=SYSTEM_NOTE_ACTION_TYPE
        )
        _pending.pop(confirmation_id, None)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The deletion was not confirmed.",
        )

    deleted = await service.clear_all()
    # Spend the decision only after the work succeeded, so a failure leaves it
    # retriable rather than silently consumed.
    week13.consume_confirmation_outcome(
        confirmation_id, expected_action_type=SYSTEM_NOTE_ACTION_TYPE
    )
    _pending.pop(confirmation_id, None)
    return {"authorized": True, "deleted_notes": deleted}


def _sweep_expired() -> None:
    now = _now()
    for confirmation_id, record in list(_pending.items()):
        if record["expires_at"] <= now:
            del _pending[confirmation_id]
