"""Local-only Commander Memory API for Phase 11 reconciliation.

Protected Memory actions use the same server-held Confirmation Gate contract as
Activity Log export. A browser-authored boolean can never authorize a mutation:
the backend proposes an exact action, the Commander answers through the shared
Week 13 gate, and this owner consumes the correlated decision exactly once.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from omnicovas.api import local_context as local_context_api
from omnicovas.api import week13
from omnicovas.core.event_types import (
    COMMANDER_MEMORY_ACTION_FAILED,
)
from omnicovas.core.event_types import (
    COMMANDER_MEMORY_EXPORT_ABANDONED as MEMORY_EXPORT_ABANDONED,
)
from omnicovas.core.event_types import (
    COMMANDER_MEMORY_EXPORT_DOWNLOAD_INITIATED as MEMORY_EXPORT_DOWNLOAD_INITIATED,
)
from omnicovas.core.event_types import (
    COMMANDER_MEMORY_EXPORT_FAILED as MEMORY_EXPORT_FAILED,
)
from omnicovas.core.event_types import (
    COMMANDER_MEMORY_PROPOSAL_BLOCKED as MEMORY_PROPOSAL_BLOCKED,
)
from omnicovas.core.event_types import (
    COMMANDER_MEMORY_PROPOSAL_CANCELED as MEMORY_PROPOSAL_CANCELED,
)
from omnicovas.core.event_types import (
    COMMANDER_MEMORY_PROPOSAL_CONFIRMED as MEMORY_PROPOSAL_CONFIRMED,
)
from omnicovas.core.event_types import (
    COMMANDER_MEMORY_PROPOSAL_SHOWN as MEMORY_PROPOSAL_SHOWN,
)
from omnicovas.features.commander_memory import (
    MEMORY_CATEGORIES,
    CommanderMemoryService,
)

router = APIRouter(prefix="/memory", tags=["commander-memory"])

_service: CommanderMemoryService | None = None

MemoryAction = Literal[
    "clear", "rebuild", "export", "delete_category", "forget_profile"
]

MEMORY_PROTECTED_ACTION_TYPE = "commander_memory_protected_action"
week13.register_outcome_action_type(
    MEMORY_PROTECTED_ACTION_TYPE,
    confirmed_event=MEMORY_PROPOSAL_CONFIRMED,
    canceled_event=MEMORY_PROPOSAL_CANCELED,
    blocked_event=MEMORY_PROPOSAL_BLOCKED,
)

_PROPOSAL_TTL_SECONDS = 300
_PROPOSAL_RESULT_TTL_SECONDS = 900
_EXPORT_TICKET_TTL_SECONDS = 900
_MAX_PENDING_ACTIONS = 32
_MAX_PENDING_EXPORTS = 32
_pending_actions: OrderedDict[str, dict[str, Any]] = OrderedDict()
_pending_exports: OrderedDict[str, dict[str, Any]] = OrderedDict()
_authorization_lock = asyncio.Lock()


def set_commander_memory_service(service: CommanderMemoryService | None) -> None:
    """Inject the single process-wide Commander Memory service."""
    global _service  # noqa: PLW0603
    _service = service


def reset_protected_action_state() -> None:
    """Clear process-lifetime proposal/export registries for focused tests."""
    _pending_actions.clear()
    _pending_exports.clear()


def _memory() -> CommanderMemoryService:
    if _service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Commander Memory is not initialized",
        )
    return _service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class PauseRequest(BaseModel):
    """Non-destructive pause/resume request."""

    model_config = ConfigDict(extra="forbid")
    paused: bool


class ProtectedActionProposal(BaseModel):
    """Exact protected operation to retain server-side before confirmation."""

    model_config = ConfigDict(extra="forbid")
    action: MemoryAction
    category: str | None = Field(default=None, max_length=32)
    profile_key: str | None = Field(default=None, max_length=64)


class AuthorizationRequest(BaseModel):
    """Server-issued proposal id; contains no client-authored approval flag."""

    model_config = ConfigDict(extra="forbid")
    confirmation_id: str = Field(min_length=1, max_length=64)


class ExportResultRequest(BaseModel):
    """Truthful browser report for an authorized Memory export ticket."""

    model_config = ConfigDict(extra="forbid")
    export_id: str = Field(min_length=1, max_length=64)
    outcome: Literal["download_initiated", "failed"]


def _validate_proposal(body: ProtectedActionProposal) -> dict[str, Any]:
    category = body.category
    profile_key = body.profile_key
    if body.action == "delete_category":
        if category not in MEMORY_CATEGORIES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A supported category is required for category deletion.",
            )
    elif category is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="category is only valid for category deletion.",
        )
    if body.action == "forget_profile":
        if not profile_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="profile_key is required to forget a profile.",
            )
    elif profile_key is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="profile_key is only valid when forgetting a profile.",
        )
    return {
        "action": body.action,
        "category": category,
        "profile_key": profile_key,
    }


def _proposal_copy(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "action": record["action"],
        "category": record.get("category"),
        "profile_key": record.get("profile_key"),
    }


def _action_text(record: dict[str, Any]) -> tuple[str, str]:
    action = record["action"]
    if action == "clear":
        return (
            "Clear all Commander Memory records?",
            "This removes derived Memory but preserves the flight recorder. "
            "Retained Journal history can repopulate it only after a later rebuild.",
        )
    if action == "rebuild":
        return (
            "Rebuild Commander Memory from retained local history?",
            "This replaces derived Memory from the local flight recorder and "
            "currently readable companion snapshots. Nothing is sent anywhere.",
        )
    if action == "export":
        return (
            "Export private Commander Memory to a local JSON file?",
            "The backend will stage a local-only payload. The browser must still "
            "initiate the download, and completion cannot be observed.",
        )
    if action == "delete_category":
        category = record["category"]
        return (
            f"Delete the {category} Commander Memory category?",
            "This removes that derived category only. Retained history or a new "
            "observation may repopulate it later.",
        )
    return (
        "Forget this Commander Memory profile?",
        "This removes the profile's derived records and keeps a display-name-free "
        "paused tombstone so retained history cannot silently repopulate it.",
    )


def _sweep_expired_state() -> None:
    """Bound proposal and export state independently of browser polling."""
    now = _now()
    # This call performs the Week 13 canonical expiry sweep.
    week13.count_pending_by_action_type(MEMORY_PROTECTED_ACTION_TYPE)
    for confirmation_id, record in list(_pending_actions.items()):
        if record["cleanup_at"] > now:
            continue
        outcome = week13.peek_confirmation_outcome(
            confirmation_id, expected_action_type=MEMORY_PROTECTED_ACTION_TYPE
        )
        # Preserve retained terminal outcomes long enough for the owner to
        # report a precise declined/expired result. Once the Week 13 outcome
        # itself has aged out, this correlation record can be reclaimed.
        if outcome is None:
            del _pending_actions[confirmation_id]
    for export_id, ticket in list(_pending_exports.items()):
        if ticket["expires_at"] > now:
            continue
        del _pending_exports[export_id]
        if _service is not None and _service.proof_available:
            _service.record_proof(
                MEMORY_EXPORT_ABANDONED,
                (
                    "Commander Memory export was authorized but no browser "
                    "result was reported"
                ),
                {
                    "export_id": export_id,
                    "completion_observed": False,
                    "outbound": False,
                },
            )


@router.get("/status")
async def get_memory_status() -> dict[str, Any]:
    """Return local Memory state, category counts, and profile boundaries."""
    return await _memory().status()


@router.get("/observed")
async def get_observed_memory(
    category: str | None = Query(default=None),
    profile_key: str | None = Query(default=None, max_length=64),
    q: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Search bounded remembered facts for Intel's Observed Galaxy."""
    try:
        return await _memory().list_records(
            category=category,
            profile_key=profile_key,
            query=q,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.post("/pause")
async def set_memory_paused(body: PauseRequest) -> dict[str, Any]:
    """Pause or resume local Memory acquisition without deleting records."""
    return await _memory().set_paused(body.paused)


@router.post("/profiles/{profile_key}/pause")
async def set_profile_paused(profile_key: str, body: PauseRequest) -> dict[str, Any]:
    """Pause or resume one non-forgotten profile."""
    changed = await _memory().set_profile_paused(profile_key, body.paused)
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )
    return {
        "status": "paused" if body.paused else "resumed",
        "profile_key": profile_key,
    }


@router.post("/actions/propose")
async def propose_protected_action(body: ProtectedActionProposal) -> dict[str, Any]:
    """Queue one exact Memory action in the shared Commander gate."""
    service = _memory()
    if not service.proof_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The shared Activity Log proof sink is unavailable.",
        )
    _sweep_expired_state()
    if (
        week13.count_pending_by_action_type(MEMORY_PROTECTED_ACTION_TYPE)
        >= _MAX_PENDING_ACTIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many Commander Memory actions are awaiting a decision.",
        )
    record = _validate_proposal(body)
    suggestion, why = _action_text(record)
    expires_at = _now() + timedelta(seconds=_PROPOSAL_TTL_SECONDS)
    confirmation_id = week13.enqueue_confirmation(
        suggestion_text=suggestion,
        why_text=why,
        timeout_at=_iso(expires_at),
        action_type=MEMORY_PROTECTED_ACTION_TYPE,
        metadata={"memory_action": record["action"]},
    )
    _pending_actions[confirmation_id] = {
        **record,
        "created_at": _now(),
        "expires_at": expires_at,
        "cleanup_at": expires_at + timedelta(seconds=_PROPOSAL_RESULT_TTL_SECONDS),
    }
    service.record_proof(
        MEMORY_PROPOSAL_SHOWN,
        "Commander Memory protected action proposed; nothing authorized",
        {
            "confirmation_id": confirmation_id,
            **_proposal_copy(record),
            "authorized": False,
        },
    )
    return {
        "status": "pending_commander_confirmation",
        "confirmation_id": confirmation_id,
        "authorized": False,
        "timeout_at": _iso(expires_at),
    }


async def _execute_action(record: dict[str, Any]) -> dict[str, Any]:
    service = _memory()
    action = record["action"]
    if action == "clear":
        deleted = await service.clear()
        return {"status": "cleared", "deleted_records": deleted}
    if action == "delete_category":
        category = str(record["category"])
        deleted = await service.delete_category(category)
        return {
            "status": "category_deleted",
            "category": category,
            "deleted_records": deleted,
        }
    if action == "forget_profile":
        profile_key = str(record["profile_key"])
        forgotten_count = await service.forget_profile(profile_key)
        if forgotten_count is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The retained profile no longer exists.",
            )
        return {"status": "profile_forgotten", "deleted_records": forgotten_count}
    if action == "rebuild":
        try:
            result = await service.rebuild()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=str(exc)
            ) from exc
        companion_count = await service.observe_local_context(
            local_context_api.build_local_context_snapshot()
        )
        return {
            "status": "rebuilt",
            **result,
            "companion_records_observed": companion_count,
        }

    payload = await service.export_payload()
    export_id = uuid4().hex
    _pending_exports[export_id] = {
        "created_at": _now(),
        "expires_at": _now() + timedelta(seconds=_EXPORT_TICKET_TTL_SECONDS),
        "record_count": len(payload["records"]),
    }
    return {
        "status": "export_staged",
        "export_id": export_id,
        "payload": payload,
        "completion_observed": False,
    }


@router.post("/actions/authorize")
async def authorize_protected_action(body: AuthorizationRequest) -> dict[str, Any]:
    """Consume one genuine Commander decision and execute its exact action."""
    _sweep_expired_state()
    confirmation_id = body.confirmation_id
    record = _pending_actions.get(confirmation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unknown, expired, or already-consumed Memory proposal.",
        )
    outcome = week13.peek_confirmation_outcome(
        confirmation_id, expected_action_type=MEMORY_PROTECTED_ACTION_TYPE
    )
    if outcome is None:
        pending = week13.peek_pending_confirmation(
            confirmation_id, expected_action_type=MEMORY_PROTECTED_ACTION_TYPE
        )
        if pending is not None:
            return {"status": "pending_commander_confirmation", "authorized": False}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No consumable Commander decision for this Memory proposal.",
        )
    if outcome == week13.CONFIRMATION_OUTCOME_CANCELED:
        week13.consume_confirmation_outcome(
            confirmation_id, expected_action_type=MEMORY_PROTECTED_ACTION_TYPE
        )
        del _pending_actions[confirmation_id]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Commander declined the Memory action.",
        )
    if outcome == week13.CONFIRMATION_OUTCOME_BLOCKED:
        week13.consume_confirmation_outcome(
            confirmation_id, expected_action_type=MEMORY_PROTECTED_ACTION_TYPE
        )
        del _pending_actions[confirmation_id]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Memory proposal expired without a Commander decision.",
        )
    if outcome != week13.CONFIRMATION_OUTCOME_CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Memory action was not confirmed.",
        )

    # Retriable capacity and in-progress refusals are checked before the
    # decision is spent.
    if record["action"] == "export" and len(_pending_exports) >= _MAX_PENDING_EXPORTS:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Commander Memory export capacity is full. The confirmation "
                "remains valid; retry after earlier export results are reported."
            ),
        )
    if record["action"] == "rebuild" and (await _memory().status())["rebuilding"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Commander Memory rebuild is already in progress. The confirmation "
                "remains valid; retry after it finishes."
            ),
        )

    # Serialize decision consumption so concurrent authorize calls cannot run
    # one operation twice. Once consumed, the exact action owns one attempt.
    async with _authorization_lock:
        if confirmation_id not in _pending_actions:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The Memory proposal was already consumed.",
            )
        if (
            record["action"] == "export"
            and len(_pending_exports) >= _MAX_PENDING_EXPORTS
        ):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Commander Memory export capacity is full. The confirmation "
                    "remains valid; retry after earlier export results are reported."
                ),
            )
        if record["action"] == "rebuild" and (await _memory().status())["rebuilding"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Commander Memory rebuild is already in progress. The confirmation "
                    "remains valid; retry after it finishes."
                ),
            )
        consumed = week13.consume_confirmation_outcome(
            confirmation_id, expected_action_type=MEMORY_PROTECTED_ACTION_TYPE
        )
        if consumed != week13.CONFIRMATION_OUTCOME_CONFIRMED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The Commander confirmation is no longer consumable.",
            )
        del _pending_actions[confirmation_id]
        try:
            result = await _execute_action(record)
        except Exception:
            _memory().record_proof(
                COMMANDER_MEMORY_ACTION_FAILED,
                "Confirmed Commander Memory action failed",
                {**_proposal_copy(record), "completion_observed": False},
            )
            raise
    return {
        "authorized": True,
        "confirmation_id": confirmation_id,
        "action": record["action"],
        **result,
    }


@router.post("/export/result")
async def report_export_result(body: ExportResultRequest) -> dict[str, Any]:
    """Record whether the browser initiated a staged local download."""
    service = _memory()
    _sweep_expired_state()
    ticket = _pending_exports.get(body.export_id)
    if ticket is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unknown, expired, or already-reported Memory export.",
        )
    initiated = body.outcome == "download_initiated"
    service.record_proof(
        MEMORY_EXPORT_DOWNLOAD_INITIATED if initiated else MEMORY_EXPORT_FAILED,
        (
            "Commander Memory export download initiated by the browser"
            if initiated
            else "Commander Memory export failed before browser download initiation"
        ),
        {
            "export_id": body.export_id,
            "record_count": ticket["record_count"],
            "outcome": body.outcome,
            "completion_observed": False,
            "outbound": False,
        },
    )
    del _pending_exports[body.export_id]
    return {
        "recorded": True,
        "outcome": body.outcome,
        "completion_observed": False,
    }
