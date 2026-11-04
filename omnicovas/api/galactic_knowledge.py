"""Galactic Knowledge API (GKI-01, GKI-03 Atlas, GKI-04 Galactic Intelligence).

Deterministic lookups over the bundled knowledge packs plus the technology unlock
planner and the Galactic Atlas.  No endpoint calls the network or uses an AI provider;
tracking an unlock and its checklist reuses the existing Engineering goal endpoints.
Location matching is read-only.

GKI-04 adds ``/knowledge/intelligence``: the Commander Context, what is documented
where the Commander is, and the only writes on this router, which are the
Commander's own Galactic Intelligence preferences and briefing dismissals.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.state_manager import StateManager
from omnicovas.features import (
    commander_context,
    engineering,
    galactic_atlas,
    galactic_intelligence,
    galactic_knowledge,
    material_intelligence,
    navigation,
    technology_unlock_planner,
)
from omnicovas.features.galactic_intelligence import GalacticIntelligence
from omnicovas.features.galactic_knowledge import KnowledgeIndex

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_session_factory: async_sessionmaker[AsyncSession] | None = None
_state_manager: StateManager | None = None
_intelligence: GalacticIntelligence | None = None


def set_session_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    """Inject the live async session factory into this router."""
    global _session_factory  # noqa: PLW0603
    _session_factory = session_factory


def set_state_manager(state_manager: StateManager | None) -> None:
    """Inject canonical state so the planner can read the current cargo snapshot."""
    global _state_manager  # noqa: PLW0603
    _state_manager = state_manager


def set_intelligence(service: GalacticIntelligence | None) -> None:
    """Inject the Galactic Intelligence service (GKI-04)."""
    global _intelligence  # noqa: PLW0603
    _intelligence = service


def _require_intelligence() -> GalacticIntelligence:
    if _intelligence is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Galactic Intelligence is not initialized",
        )
    return _intelligence


def _knowledge() -> KnowledgeIndex:
    catalog = galactic_knowledge.catalog()
    if catalog["state"] != "available":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "state": "unavailable",
                "reason": catalog["reason"],
                "message": "Galactic knowledge is not included in this build."
                if catalog["reason"] == "not_included"
                else "The bundled galactic knowledge failed validation.",
            },
        )
    return galactic_knowledge.index()


def _missing(entity_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"No knowledge record for {entity_id}",
    )


@router.get("/catalog")
async def get_catalog() -> dict[str, Any]:
    """Pack summary, coverage and the technology unlocks available to plan."""
    return galactic_knowledge.catalog()


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str) -> dict[str, Any]:
    entity = _knowledge().entity(entity_id)
    if entity is None:
        raise _missing(entity_id)
    return entity


@router.get("/entities/{entity_id}/acquisition")
async def get_acquisition(entity_id: str) -> dict[str, Any]:
    """Known ways to obtain an item, with procedures and documented places."""
    try:
        return _knowledge().acquisition(entity_id)
    except KeyError as exc:
        raise _missing(entity_id) from exc


@router.get("/entities/{entity_id}/related")
async def get_related(entity_id: str) -> dict[str, Any]:
    try:
        return {"entity_id": entity_id, "related": _knowledge().related(entity_id)}
    except KeyError as exc:
        raise _missing(entity_id) from exc


@router.get("/entities/{entity_id}/locations")
async def get_locations(entity_id: str) -> dict[str, Any]:
    try:
        return {"entity_id": entity_id, "locations": _knowledge().locations(entity_id)}
    except KeyError as exc:
        raise _missing(entity_id) from exc


@router.get("/entities/{entity_id}/sources")
async def get_sources(entity_id: str) -> dict[str, Any]:
    """The declared sources that support everything said about an entity."""
    try:
        return {"entity_id": entity_id, "sources": _knowledge().sources_for(entity_id)}
    except KeyError as exc:
        raise _missing(entity_id) from exc


@router.get("/atlas")
async def get_atlas() -> dict[str, Any]:
    """Every Galactic Atlas subject, with what the Atlas browser lists."""
    return {"network_access": "none", "subjects": _knowledge().atlas()}


@router.get("/atlas/{entity_id}")
async def get_atlas_entry(entity_id: str) -> dict[str, Any]:
    """One Atlas subject: history, connections, opportunities, location and sources."""
    knowledge = _knowledge()
    try:
        entry = knowledge.atlas_entry(entity_id)
        entry["related_destinations"] = knowledge.related_destinations(entity_id)
    except KeyError as exc:
        raise _missing(entity_id) from exc
    return entry


@router.get("/atlas/{entity_id}/relevance")
async def get_atlas_relevance(entity_id: str) -> dict[str, Any]:
    """Why this place may matter to active Engineering builds (deterministic)."""
    knowledge = _knowledge()
    if _session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Knowledge persistence not initialized",
        )
    try:
        return await galactic_atlas.relevance(
            _session_factory,
            knowledge,
            entity_id,
            builds=await engineering.list_build_plans(_session_factory),
            goals=await engineering.list_goals(_session_factory),
            live_state=_state_manager.public_snapshot()
            if _state_manager is not None
            else {},
        )
    except KeyError as exc:
        raise _missing(entity_id) from exc


@router.get("/materials/{symbol}/places")
async def get_material_places(symbol: str) -> dict[str, Any]:
    """Atlas places documented as sources of a Journal material symbol."""
    knowledge = _knowledge()
    material = knowledge.find_by_symbol("materials", symbol)
    places: list[dict[str, Any]] = []
    if material is not None:
        atlas_ids = {row["id"] for row in knowledge.atlas()}
        places = [
            {
                **{key: place[key] for key in ("id", "kind", "name")},
                "activity": {"id": method["id"], "name": method["name"]},
            }
            for method in knowledge.acquisition(material["id"])["methods"]
            for place in method["locations"]
            if place["id"] in atlas_ids
        ]
    return {
        "symbol": symbol.casefold(),
        "material": {"id": material["id"], "name": material["name"]}
        if material
        else None,
        "places": places,
    }


@router.get("/materials/{symbol}/acquisition")
async def get_material_acquisition(symbol: str) -> dict[str, Any]:
    """Every documented way to obtain one material (GKI-05), offline.

    High Grade Emissions are checked against the factions recorded in the
    Commander's current or last system; nothing else about them is assumed.
    """
    catalog = galactic_knowledge.catalog()
    knowledge = galactic_knowledge.index() if catalog["state"] == "available" else None
    system = None
    if _state_manager is not None:
        candidate = _state_manager.public_snapshot().get("local_system_context")
        system = candidate if isinstance(candidate, dict) else None
    return material_intelligence.guide(knowledge, symbol.casefold(), system=system)


@router.get("/locations/match")
async def get_location_match(
    system_address: int | None = None,
    system: str | None = None,
    market_id: int | None = None,
    station: str | None = None,
    body_id: int | None = None,
    body: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    """Documented places an observed position matches, and how deeply and surely."""
    if system_address is None and not system:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A system name or SystemAddress is required",
        )
    knowledge = _knowledge()
    result = knowledge.match_location(
        {
            "system_address": system_address,
            "system": system,
            "market_id": market_id,
            "station": station,
            "body_id": body_id,
            "body": body,
            "latitude": latitude,
            "longitude": longitude,
        }
    )
    result["associated"] = knowledge.knowledge_for_system(
        system_address=system_address, system=system
    )["associated"]
    return result


# -- Galactic Intelligence (GKI-04) ------------------------------------------


def _navigation() -> dict[str, Any] | None:
    """The existing NavRoute projection, or None when it cannot be read."""
    try:
        return navigation.build_active_route(navigation.read_navroute()).payload()
    except Exception:  # noqa: BLE001 - a route is optional context
        return None


@router.get("/intelligence/context")
async def get_intelligence_context(include_engineering: bool = False) -> dict[str, Any]:
    """The Commander Context and what is documented there (manual reading)."""
    service = _require_intelligence()
    context = service.context(navigation=_navigation())
    keys = galactic_intelligence.presence_keys(context)
    result: dict[str, Any] = {
        "context": context,
        "documented": service.documented(context),
        # GKI-08 closeout: the places a briefing can be compared with.  Not
        # known proves neither presence nor departure.
        "presence": {"known": keys is not None, "keys": sorted(keys or [])},
    }
    if include_engineering and _session_factory is not None and _state_manager:
        result["engineering"] = await commander_context.engineering_context(
            _session_factory, _state_manager
        )
    return result


async def _preferences_payload(service: GalacticIntelligence) -> dict[str, Any]:
    profile = service.profile_key()
    forgotten = await service.is_forgotten(profile)
    return {
        "profile_key": profile,
        "commander_known": profile != galactic_intelligence.DEFAULT_PROFILE_KEY,
        "forgotten": forgotten,
        "own_record": service.preferences.has_own(profile) and not forgotten,
        "preferences": await service.preferences_for(profile),
        "defaults": galactic_intelligence.default_preferences(),
        "categories": [
            {"id": key, "label": label}
            for key, label in galactic_intelligence.CATEGORY_LABELS.items()
        ],
        "frequencies": list(galactic_intelligence.FREQUENCIES),
    }


@router.get("/intelligence/preferences")
async def get_intelligence_preferences() -> dict[str, Any]:
    """The current commander's Galactic Intelligence preferences."""
    return await _preferences_payload(_require_intelligence())


@router.put("/intelligence/preferences")
async def put_intelligence_preferences(
    body: dict[str, Any] = Body(...),  # noqa: B008
) -> dict[str, Any]:
    """Save the current commander's preferences (validated, complete record)."""
    service = _require_intelligence()
    if await service.is_forgotten(service.profile_key()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This commander was forgotten; nothing is kept for them",
        )
    try:
        service.preferences.set(service.profile_key(), body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Preferences could not be saved",
        ) from exc
    return await _preferences_payload(service)


@router.post("/intelligence/preferences/reset")
async def reset_intelligence_preferences() -> dict[str, Any]:
    """Return the current commander to the defaults (automatic intelligence off)."""
    service = _require_intelligence()
    service.preferences.reset(service.profile_key())
    return await _preferences_payload(service)


@router.get("/intelligence/briefings")
async def get_intelligence_briefings() -> dict[str, Any]:
    """Undismissed automatic briefings for the current commander."""
    return {"briefings": await _require_intelligence().active_briefings()}


@router.post("/intelligence/briefings/{briefing_id}/dismiss")
async def dismiss_intelligence_briefing(briefing_id: str) -> dict[str, Any]:
    """Dismiss one briefing; preferences are not changed."""
    if not await _require_intelligence().dismiss(briefing_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such briefing for this commander",
        )
    return {"dismissed": briefing_id}


@router.get("/intelligence/decisions")
async def get_intelligence_decisions() -> dict[str, Any]:
    """Why recent Journal observations did or did not brief (diagnostics)."""
    return {"decisions": _require_intelligence().recent_decisions()}


@router.get("/unlocks/{unlock_id}/requirements")
async def get_requirements(unlock_id: str) -> dict[str, Any]:
    """An unlock's requirements and the inventory record each one maps to."""
    try:
        return {
            "unlock_id": unlock_id,
            "requirements": _knowledge().requirements(unlock_id),
        }
    except KeyError as exc:
        raise _missing(unlock_id) from exc


@router.get("/unlocks/{unlock_id}/plan")
async def get_unlock_plan(
    unlock_id: str, recipe: str | None = None, quantity: int = 1
) -> dict[str, Any]:
    """Requirements compared with observed inventory, unlock evidence and guidance.

    ``recipe`` picks between source-conflicting recipes; ``quantity`` is the number
    of items for a per-item purchase (a permanent unlock is always 1).
    """
    knowledge = _knowledge()
    if _session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Knowledge persistence not initialized",
        )
    cargo = (
        _state_manager.snapshot.cargo_hold_snapshot
        if _state_manager is not None
        else None
    )
    try:
        return await technology_unlock_planner.plan(
            _session_factory,
            knowledge,
            unlock_id,
            cargo=cargo,
            goals=await engineering.list_goals(_session_factory),
            recipe=recipe,
            quantity=quantity,
        )
    except KeyError as exc:
        raise _missing(
            recipe if recipe and str(exc).strip("'") == recipe else unlock_id
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
