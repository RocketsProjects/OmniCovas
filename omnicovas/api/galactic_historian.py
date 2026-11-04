"""Living Galactic Historian and Commander Chronicle API (GKI-07).

``/knowledge/historian`` answers the Historian's questions for where the Commander
is now and for any Atlas subject; ``/knowledge/chronicle`` is the current
commander's Chronicle.  The only writes are the Commander's own: confirming a
visit (always labelled commander-reported) and saving a story.  A forgotten
commander can read nothing and write nothing.  No endpoint calls the network.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, status

from omnicovas.features.commander_chronicle import (
    ChronicleConflict,
    ChronicleError,
    ChronicleNotFound,
    ChronicleService,
    ChronicleUnavailable,
)
from omnicovas.features.galactic_intelligence import GalacticIntelligence

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_service: ChronicleService | None = None
_intelligence: GalacticIntelligence | None = None


def set_service(service: ChronicleService | None) -> None:
    """Inject the Chronicle service (one per bridge)."""
    global _service  # noqa: PLW0603
    _service = service


def set_intelligence(service: GalacticIntelligence | None) -> None:
    """Inject Galactic Intelligence, which keeps the Historian's moments."""
    global _intelligence  # noqa: PLW0603
    _intelligence = service


def _require() -> ChronicleService:
    if _service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The Commander Chronicle is not initialized",
        )
    return _service


async def _guard(call: Any) -> Any:
    try:
        return await call
    except ChronicleNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Not found: {exc.args[0] if exc.args else 'entry'}",
        ) from exc
    except ChronicleConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ChronicleUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ChronicleError as exc:  # pragma: no cover - every refusal is typed
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


def _object(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The request body must be an object",
        )
    return body


@router.get("/historian/context")
async def get_historian_context(reveal: bool = False) -> dict[str, Any]:
    """Where the Commander is, what is documented here and what to explore next.

    Spoilers follow the Commander's spoiler protection unless ``reveal`` asks.
    """
    result: dict[str, Any] = await _guard(_require().context(reveal=reveal))
    return result


@router.get("/historian/subjects/{entity_id}")
async def get_historian_subject(entity_id: str, reveal: bool = False) -> dict[str, Any]:
    """One Atlas subject as the Historian reads it, with the Commander's record."""
    result: dict[str, Any] = await _guard(_require().subject(entity_id, reveal=reveal))
    return result


@router.get("/historian/opportunities")
async def get_historian_opportunities() -> dict[str, Any]:
    """Historian moments for the future Notification Director (nothing presented)."""
    if _intelligence is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Galactic Intelligence is not initialized",
        )
    return {"opportunities": _intelligence.recent_opportunities()}


@router.get("/chronicle")
async def get_chronicle() -> dict[str, Any]:
    """The current commander's Chronicle, by evidence class."""
    result: dict[str, Any] = await _guard(_require().chronicle())
    return result


@router.get("/chronicle/decisions")
async def get_chronicle_decisions() -> dict[str, Any]:
    """Why recent Journal events did or did not reach the Chronicle (diagnostics)."""
    return {"decisions": _require().recent_decisions()}


@router.post("/chronicle/confirmations")
async def post_confirmation(
    body: Any = Body(...),  # noqa: B008
) -> dict[str, Any]:
    """Confirm a visit yourself; it is always shown as commander-reported."""
    payload = _object(body)
    place_id = payload.get("place_id")
    if not isinstance(place_id, str) or not place_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="place_id must be text",
        )
    result: dict[str, Any] = await _guard(
        _require().confirm(place_id, payload.get("note"))
    )
    return result


@router.delete("/chronicle/confirmations/{place_id}")
async def delete_confirmation(place_id: str) -> dict[str, Any]:
    """Withdraw your own confirmation; Journal evidence is unaffected."""
    result: dict[str, Any] = await _guard(_require().unconfirm(place_id))
    return result


@router.post("/chronicle/saved")
async def post_saved(body: Any = Body(...)) -> dict[str, Any]:  # noqa: B008
    """Save an Atlas entry, a story or a chapter to your Chronicle."""
    result: dict[str, Any] = await _guard(_require().save(_object(body)))
    return result


@router.delete("/chronicle/saved/{entry_id}")
async def delete_saved(entry_id: str) -> dict[str, Any]:
    await _guard(_require().unsave(entry_id))
    return {"removed": entry_id}
