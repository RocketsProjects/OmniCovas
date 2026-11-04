"""Developer diagnostics for the Notification Director (decisions, lanes, kill switch).

Commander-facing presentation, receipts and preferences live in
``omnicovas.api.notifications``.
"""

from typing import Any

from fastapi import APIRouter, HTTPException

from omnicovas.features.notification_shadow import NotificationShadow

router = APIRouter(prefix="/diagnostics/notification-shadow", tags=["diagnostics"])
_service: NotificationShadow | None = None


def set_service(service: NotificationShadow) -> None:
    global _service
    _service = service


def require() -> NotificationShadow:
    if _service is None:
        raise HTTPException(503, "Notification shadow unavailable")
    return _service


@router.get("")
async def inspect_shadow(limit: int = 100) -> dict[str, Any]:
    service = require()
    return {**service.diagnostics(), "decisions": await service.records(limit)}


@router.post("/enabled")
async def enable_shadow(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body.get("enabled"), bool):
        raise HTTPException(422, "enabled must be a boolean")
    await require().set_enabled(body["enabled"])
    return require().diagnostics()


@router.post("/clear")
async def clear_shadow(body: dict[str, Any]) -> dict[str, str]:
    if body.get("confirm") is not True:
        raise HTTPException(400, "Confirm clearing local shadow diagnostics")
    await require().clear()
    return {"status": "cleared", "scope": "shadow_diagnostics_only"}
