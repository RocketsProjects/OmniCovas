"""Notification presentation, delivery receipts, ownership and preferences.

Surfaces report what they actually rendered; acknowledgement dismisses a
presentation and never resolves its condition. Preferences are commander-scoped
in the existing configuration vault; critical event switches, overlay opacity
and anchor stay with the existing overlay settings.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from omnicovas.features.notification_preferences import (
    normalize_device,
    normalize_profile,
)
from omnicovas.features.notification_shadow import NotificationShadow

router = APIRouter(prefix="/notifications", tags=["notifications"])
_service: NotificationShadow | None = None
_profile_provider: Any = None


def set_service(service: NotificationShadow, profile_provider: Any = None) -> None:
    global _service, _profile_provider
    _service, _profile_provider = service, profile_provider


def require() -> NotificationShadow:
    if _service is None:
        raise HTTPException(503, "Notifications unavailable")
    return _service


def _commander() -> str | None:
    try:
        value = _profile_provider() if callable(_profile_provider) else None
    except Exception:
        value = None
    return value if isinstance(value, str) and value else None


def _text(body: dict[str, Any], key: str, limit: int = 64) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > limit:
        raise HTTPException(422, f"{key} must be a short string")
    return value


@router.get("/presentation")
async def presentation() -> dict[str, Any]:
    return require().presentation_snapshot()


@router.post("/receipts")
async def receipt(body: dict[str, Any]) -> dict[str, Any]:
    service = require()
    client = _text(body, "client", 16)
    status = _text(body, "status", 16)
    pid = _text(body, "presentation_id")
    raw_detail = body.get("detail")
    detail = raw_detail if isinstance(raw_detail, str) else ""
    if client is None or status is None:
        raise HTTPException(422, "client and status are required")
    accepted = await service.receipt(pid, client, status, detail[:80])
    return {"accepted": accepted}


@router.get("/receipts")
async def receipts(limit: int = 50) -> dict[str, Any]:
    service = require()
    return {
        "receipts": service.presenter.receipts(limit, service.scope.commander),
        "counters": dict(service.presenter.counters),
    }


@router.post("/acknowledge")
async def acknowledge(body: dict[str, Any]) -> dict[str, Any]:
    pid = _text(body, "presentation_id")
    client = _text(body, "client", 16) or "desktop"
    if pid is None:
        raise HTTPException(422, "presentation_id is required")
    done = await require().acknowledge(pid, client)
    return {"acknowledged": done, "condition_resolved": False}


@router.get("/owner")
async def owner() -> dict[str, Any]:
    snap = require().presentation_snapshot()
    service = require()
    return {
        "owner": snap["owner"],
        "configured_owner": service.presenter.configured_owner,
        "reason": snap["owner_reason"],
    }


@router.post("/owner")
async def set_owner(body: dict[str, Any]) -> dict[str, Any]:
    value = body.get("owner")
    if value not in {"director", "legacy"}:
        raise HTTPException(422, "owner must be director or legacy")
    try:
        snap = await require().set_owner(value)
    except OSError as error:
        raise HTTPException(500, str(error)) from error
    return {
        "owner": snap["owner"],
        "configured_owner": value,
        "reason": snap["owner_reason"],
    }


async def _preferences_payload() -> dict[str, Any]:
    service = require()
    commander = _commander()
    forgotten = bool(commander) and await service.intelligence.is_forgotten(
        commander or ""
    )
    return {
        "commander_known": commander is not None,
        "forgotten": forgotten,
        "has_own": bool(commander) and service.store.has_own(commander or ""),
        "preferences": service.store.get(commander),
        "device": service.store.device(),
        "sound": "unsupported",
    }


@router.get("/preferences")
async def get_preferences() -> dict[str, Any]:
    return await _preferences_payload()


@router.put("/preferences")
async def put_preferences(body: dict[str, Any]) -> dict[str, Any]:
    service = require()
    commander = _commander()
    if commander and await service.intelligence.is_forgotten(commander):
        raise HTTPException(409, "This commander was forgotten; nothing is saved")
    try:
        if "preferences" in body:
            normalize_profile(body["preferences"], strict=True)
        if "device" in body:
            normalize_device(body["device"], strict=True)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    try:
        if "preferences" in body:
            service.store.set(commander, body["preferences"])
        if "device" in body:
            service.store.set_device(body["device"])
    except OSError as error:
        raise HTTPException(500, str(error)) from error
    service.invalidate_preferences()
    service.wake.set()
    return await _preferences_payload()


@router.post("/preferences/reset")
async def reset_preferences(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("confirm") is not True:
        raise HTTPException(400, "Confirm resetting this commander's notifications")
    service = require()
    service.store.reset(_commander())
    service.invalidate_preferences()
    service.wake.set()
    return await _preferences_payload()
