"""Galactic Expeditions API (GKI-06): ``/navigation/expeditions``.

Expeditions live in Navigation's Plan mode.  Every endpoint reads or writes the
current commander's own expeditions (Commander Memory's active profile); a
forgotten commander can read nothing and write nothing.  No endpoint calls the
network: distances are straight lines between documented positions, stories come
from the bundled knowledge packs, and the next-leg Spansh link is only a URL.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, status

from omnicovas.features import expeditions
from omnicovas.features.expedition_service import (
    ExpeditionConflict,
    ExpeditionError,
    ExpeditionNotFound,
    ExpeditionService,
)

router = APIRouter(prefix="/navigation/expeditions", tags=["navigation"])

_service: ExpeditionService | None = None


def set_service(service: ExpeditionService | None) -> None:
    """Inject the expedition service (one per bridge)."""
    global _service  # noqa: PLW0603
    _service = service


def _require() -> ExpeditionService:
    if _service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Expeditions are not initialized",
        )
    return _service


async def _guard(call: Any) -> Any:
    try:
        return await call
    except ExpeditionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Not found: {exc.args[0] if exc.args else 'expedition'}",
        ) from exc
    except ExpeditionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ExpeditionError as exc:  # pragma: no cover - every refusal is typed
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


# Static paths first: ``/{expedition_id}`` would otherwise capture them.


@router.get("")
async def list_expeditions() -> dict[str, Any]:
    """The current commander's expeditions, newest activity first."""
    result: dict[str, Any] = await _guard(_require().list_all())
    return result


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_expedition(body: Any = Body(...)) -> dict[str, Any]:  # noqa: B008
    """Start an expedition from a destination, a theme, a story, a goal or nothing.

    ``narrative_id`` adds the story's chapter places in story order; ``place_id`` or
    ``system`` adds a destination; ``stops`` adds chosen stops (goal-first).
    """
    result: dict[str, Any] = await _guard(_require().create(_object(body)))
    return result


@router.get("/catalog")
async def get_catalog() -> dict[str, Any]:
    """Stories and themes to start from, and the current storytelling mode."""
    result: dict[str, Any] = await _guard(_require().catalog())
    return result


@router.get("/themes/{theme_id}")
async def get_theme(theme_id: str, expedition_id: str | None = None) -> dict[str, Any]:
    """Places a theme selects, with why and how far (theme-first)."""
    result: dict[str, Any] = await _guard(
        _require().theme_candidates(theme_id, expedition_id)
    )
    return result


@router.get("/materials")
async def get_materials(
    scope: str = "all", expedition_id: str | None = None
) -> dict[str, Any]:
    """GKI-05 acquisition destinations for one build or all, by system (goal-first)."""
    result: dict[str, Any] = await _guard(_require().materials(scope, expedition_id))
    return result


@router.get("/search")
async def search_places(q: str = "") -> dict[str, Any]:
    """Documented places by name or system, and the named system itself."""
    return _require().search(q)


@router.get("/narratives/{narrative_id}")
async def get_narrative(narrative_id: str, reveal: bool = False) -> dict[str, Any]:
    """One story with each passage's evidence, sources and spoiler marking.

    Spoiler passages are withheld while spoiler protection is on, unless the
    Commander asks to reveal them in the reader (``reveal`` is the reader's own
    choice and changes no preference).
    """
    service = _require()
    knowledge = service.knowledge()
    if knowledge is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Galactic knowledge is not included in this build.",
        )
    try:
        narrative = knowledge.narrative(narrative_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown story"
        ) from exc
    mode = await _guard(service.storytelling())
    return {
        "narrative": expeditions.reader_view(
            narrative, spoilers=reveal or not mode["spoiler_protection"]
        ),
        "storytelling": mode,
        "contract": expeditions.CONTRACT,
    }


@router.get("/opportunities")
async def get_opportunities() -> dict[str, Any]:
    """Narrative opportunities the Journal earned this session (never presented).

    The ``narrative-opportunity-v1`` contract for a future presenter; GKI-06 shows
    them only inside the expedition workspace.
    """
    service = _require()
    return {
        "contract": expeditions.CONTRACT,
        "opportunities": service.opportunities(),
        "storytelling": await _guard(service.storytelling()),
    }


@router.post("/opportunities/{opportunity_id}/dismiss")
async def dismiss_opportunity(opportunity_id: str) -> dict[str, Any]:
    if not _require().dismiss(opportunity_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown opportunity"
        )
    return {"dismissed": opportunity_id}


@router.get("/unassigned")
async def get_unassigned() -> dict[str, Any]:
    """Expeditions planned before any commander was identified, to claim."""
    return {"expeditions": await _guard(_require().unassigned())}


@router.get("/decisions")
async def get_decisions() -> dict[str, Any]:
    """Recent Journal progress decisions for the current commander (diagnostics)."""
    return {"decisions": _require().recent_decisions()}


@router.get("/{expedition_id}")
async def get_expedition(expedition_id: str) -> dict[str, Any]:
    """Stops, straight-line legs, orders, preflight, story and opportunities."""
    result: dict[str, Any] = await _guard(_require().detail(expedition_id))
    return result


@router.patch("/{expedition_id}")
async def update_expedition(
    expedition_id: str,
    body: Any = Body(...),  # noqa: B008
) -> dict[str, Any]:
    """Rename, attach a story or theme, or start, pause, complete or archive."""
    result: dict[str, Any] = await _guard(
        _require().update(expedition_id, _object(body))
    )
    return result


@router.delete("/{expedition_id}")
async def delete_expedition(expedition_id: str) -> dict[str, Any]:
    """Delete an expedition and its history (the Commander's explicit request)."""
    await _guard(_require().delete(expedition_id))
    return {"deleted": expedition_id}


@router.post("/{expedition_id}/claim")
async def claim_expedition(expedition_id: str) -> dict[str, Any]:
    result: dict[str, Any] = await _guard(_require().claim(expedition_id))
    return result


@router.post("/{expedition_id}/stops", status_code=status.HTTP_201_CREATED)
async def add_stop(
    expedition_id: str,
    body: Any = Body(...),  # noqa: B008
) -> dict[str, Any]:
    """Add a place or system; a place already on the expedition gains the purpose."""
    result: dict[str, Any] = await _guard(
        _require().add_stop(expedition_id, _object(body))
    )
    return result


@router.patch("/{expedition_id}/stops/{stop_id}")
async def update_stop(
    expedition_id: str,
    stop_id: str,
    body: Any = Body(...),  # noqa: B008
) -> dict[str, Any]:
    """Mark a stop complete, skipped or planned again, or change its note."""
    result: dict[str, Any] = await _guard(
        _require().update_stop(expedition_id, stop_id, _object(body))
    )
    return result


@router.delete("/{expedition_id}/stops/{stop_id}")
async def remove_stop(expedition_id: str, stop_id: str) -> dict[str, Any]:
    result: dict[str, Any] = await _guard(
        _require().remove_stop(expedition_id, stop_id)
    )
    return result


@router.put("/{expedition_id}/order")
async def reorder(
    expedition_id: str,
    body: Any = Body(...),  # noqa: B008
) -> dict[str, Any]:
    """``stop_ids`` in the Commander's order, or ``apply`` a suggested order."""
    result: dict[str, Any] = await _guard(
        _require().reorder(expedition_id, _object(body))
    )
    return result


@router.put("/{expedition_id}/chapters/{narrative_id}/{chapter_id}")
async def mark_chapter(
    expedition_id: str,
    narrative_id: str,
    chapter_id: str,
    body: Any = Body(...),  # noqa: B008
) -> dict[str, Any]:
    """Mark a chapter read or unread; chapters can be read in any order."""
    read = _object(body).get("read")
    if not isinstance(read, bool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="read must be true or false",
        )
    result: dict[str, Any] = await _guard(
        _require().mark_chapter(expedition_id, narrative_id, chapter_id, read=read)
    )
    return result


@router.get("/{expedition_id}/suggestions")
async def get_suggestions(expedition_id: str) -> dict[str, Any]:
    """Stories along the way, story places not yet added, and related places."""
    result: dict[str, Any] = await _guard(_require().suggestions(expedition_id))
    return result


@router.get("/{expedition_id}/recap")
async def get_recap(expedition_id: str) -> dict[str, Any]:
    """The journey so far from its structured history (Chronicle-ready)."""
    result: dict[str, Any] = await _guard(_require().recap(expedition_id))
    return result
