"""Knowledge graph traversal endpoint — LNA-006 foundation slice.

One read-only surface: resolve an entity, return its derived edges and the
recorded events that prove them. Every edge carries the `type` and `key`
needed to resolve the next entity, so the Commander can actually walk from a
sitting to a system to a station to what was observed there.

No new persistence: this projects over the flight recorder and Commander
Memory. See omnicovas/features/knowledge_graph.py for the scope boundary
against the Phase 13 Intel terminal.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.features import knowledge_graph

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_session_factory: async_sessionmaker[AsyncSession] | None = None
_notes_service: Any = None


def set_session_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    """Inject the live async session factory into this router."""
    global _session_factory  # noqa: PLW0603
    _session_factory = session_factory


def set_system_note_service(service: Any) -> None:
    """Inject the Commander system-note service.

    Optional: the graph is derived and stays correct without it, so an absent
    service means "no notes", never an error.
    """
    global _notes_service  # noqa: PLW0603
    _notes_service = service


def _ensure_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Flight recorder persistence not initialized",
        )
    return _session_factory


class EntityEdgeRow(BaseModel):
    """One traversable link. `type` + `key` resolve the entity at the far end."""

    model_config = ConfigDict(extra="allow")

    relation: str
    type: str
    key: str
    display_name: str


class SourceChainRow(BaseModel):
    """One recorded event standing behind this entity."""

    model_config = ConfigDict(extra="forbid")

    id: int
    session_id: int
    timestamp: str | None
    event_type: str


class EntityNoteRow(BaseModel):
    """Commander-authored text attached to this entity."""

    model_config = ConfigDict(extra="allow")

    note: str
    updated_at: str | None


class EntityBody(BaseModel):
    """The resolved entity itself."""

    model_config = ConfigDict(extra="forbid")

    type: str
    key: str
    display_name: str
    attributes: dict[str, Any]


class EntityResponse(BaseModel):
    """An entity with its derived edges and recorded proof."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    # False means nothing was ever recorded for this key — not an error, and
    # never proof the place does not exist.
    found: bool
    entity: EntityBody
    edges: list[EntityEdgeRow]
    source_chain: list[SourceChainRow]
    notes: list[EntityNoteRow]
    nullprovider_safe: bool


@router.get("/entity", response_model=EntityResponse)
async def get_entity(
    type: str = Query(max_length=32),
    key: str = Query(max_length=256),
    source_chain_limit: int | None = Query(
        default=None, ge=1, le=knowledge_graph.SOURCE_CHAIN_MAX
    ),
) -> dict[str, Any]:
    """Resolve one entity and the connections recorded around it."""
    factory = _ensure_session_factory()
    try:
        return await knowledge_graph.resolve_entity(
            factory,
            entity_type=type,
            key=key,
            source_chain_limit=source_chain_limit,
            notes_service=_notes_service,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get("/entity-types")
async def get_entity_types() -> dict[str, Any]:
    """Entity types this graph models, so callers never guess a type."""
    return {
        "entity_types": list(knowledge_graph.ENTITY_TYPES),
        "source": knowledge_graph.SOURCE_FLIGHT_RECORDER,
        "truth_class": knowledge_graph.TRUTH_LOCAL_EVENT_HISTORY,
        "nullprovider_safe": True,
    }
