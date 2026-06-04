"""Local Navigation bookmarks, saved routes, and campaign circuit API endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityLog
from omnicovas.features import campaign_circuits as circuits
from omnicovas.features import navigation_bookmarks as bookmarks
from omnicovas.features.campaign_circuits import CircuitRecord, StopRecord
from omnicovas.features.navigation_bookmarks import (
    BookmarkRecord,
    SavedRouteRecord,
)

router = APIRouter(prefix="/navigation", tags=["navigation"])

_session_factory: async_sessionmaker[AsyncSession] | None = None
_activity_log: ActivityLog | None = None


def set_session_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    """Inject the live async session factory into this router."""
    global _session_factory  # noqa: PLW0603
    _session_factory = session_factory


def set_activity_log(activity_log: ActivityLog | None) -> None:
    """Inject the shared ActivityLog used for write audit entries."""
    global _activity_log  # noqa: PLW0603
    _activity_log = activity_log


def _ensure_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Navigation persistence not initialized",
        )
    return _session_factory


# --- Models -----------------------------------------------------------------


class BookmarkResponse(BaseModel):
    """Public API shape for a local Navigation bookmark."""

    model_config = ConfigDict(extra="forbid")

    id: int
    label: str
    entity_type: str
    target_name: str
    target_system_address: int | None
    x: float | None
    y: float | None
    z: float | None
    commander_note: str | None
    tags: list[str]
    created_at: str
    updated_at: str


class SavedRouteResponse(BaseModel):
    """Public API shape for a local saved route record."""

    model_config = ConfigDict(extra="forbid")

    id: int
    label: str
    origin: str
    destination: str
    hop_count: int
    source_id: str
    commander_note: str | None
    created_at: str
    updated_at: str


class RouteLibrarySnapshotResponse(BaseModel):
    """Public Navigation route library snapshot."""

    model_config = ConfigDict(extra="forbid")

    bookmarks: list[BookmarkResponse]
    saved_routes: list[SavedRouteResponse]
    nullprovider_safe: bool = True


class BookmarkCreateRequest(BaseModel):
    """Commander-entered bookmark creation request."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=64)
    entity_type: str = Field(min_length=1, max_length=32)
    target_name: str = Field(min_length=1, max_length=128)
    target_system_address: int | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    commander_note: str | None = Field(default=None, max_length=4000)
    tags: list[str] = Field(default_factory=list)


class BookmarkPatchRequest(BaseModel):
    """Commander-entered bookmark update request."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=64)
    commander_note: str | None = Field(default=None, max_length=4000)
    tags: list[str] | None = None


class SavedRouteCreateRequest(BaseModel):
    """Commander-entered saved route creation request."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=64)
    origin: str = Field(min_length=1, max_length=128)
    destination: str = Field(min_length=1, max_length=128)
    hop_count: int = Field(ge=0)
    source_id: str = Field(min_length=1, max_length=32)
    commander_note: str | None = Field(default=None, max_length=4000)


class SavedRoutePatchRequest(BaseModel):
    """Commander-entered saved route update request."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=64)
    commander_note: str | None = Field(default=None, max_length=4000)


class DeleteResponse(BaseModel):
    """Delete response shape."""

    model_config = ConfigDict(extra="forbid")

    status: str


# --- Helpers ----------------------------------------------------------------


def _to_bookmark_response(record: BookmarkRecord) -> BookmarkResponse:
    return BookmarkResponse(
        id=record.id,
        label=record.label,
        entity_type=record.entity_type,
        target_name=record.target_name,
        target_system_address=record.target_system_address,
        x=record.x,
        y=record.y,
        z=record.z,
        commander_note=record.commander_note,
        tags=record.tags,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


def _to_route_response(record: SavedRouteRecord) -> SavedRouteResponse:
    return SavedRouteResponse(
        id=record.id,
        label=record.label,
        origin=record.origin,
        destination=record.destination,
        hop_count=record.hop_count,
        source_id=record.source_id,
        commander_note=record.commander_note,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


# --- Endpoints --------------------------------------------------------------


@router.get("/library/snapshot", response_model=RouteLibrarySnapshotResponse)
async def get_library_snapshot() -> RouteLibrarySnapshotResponse:
    """Return a snapshot of local bookmarks and saved routes."""
    factory = _ensure_session_factory()
    bookmark_records = await bookmarks.list_bookmarks(factory)
    route_records = await bookmarks.list_saved_routes(factory)

    return RouteLibrarySnapshotResponse(
        bookmarks=[_to_bookmark_response(b) for b in bookmark_records],
        saved_routes=[_to_route_response(r) for r in route_records],
    )


@router.post(
    "/bookmarks",
    response_model=BookmarkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_bookmark(body: BookmarkCreateRequest) -> BookmarkResponse:
    """Create a local Navigation bookmark."""
    factory = _ensure_session_factory()
    try:
        record = await bookmarks.create_bookmark(
            factory,
            bookmarks.BookmarkCreate(
                label=body.label,
                entity_type=body.entity_type,
                target_name=body.target_name,
                target_system_address=body.target_system_address,
                x=body.x,
                y=body.y,
                z=body.z,
                commander_note=body.commander_note,
                tags=list(body.tags),
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    return _to_bookmark_response(record)


@router.patch("/bookmarks/{bookmark_id}", response_model=BookmarkResponse)
async def update_bookmark(
    bookmark_id: int,
    body: BookmarkPatchRequest,
) -> BookmarkResponse:
    """Update a local Navigation bookmark (label/note only)."""
    factory = _ensure_session_factory()
    changes: bookmarks.BookmarkUpdate = {}
    if body.label is not None:
        changes["label"] = body.label
    if "commander_note" in body.model_fields_set:
        changes["commander_note"] = body.commander_note
    if body.tags is not None:
        changes["tags"] = body.tags

    try:
        record = await bookmarks.update_bookmark(
            factory,
            bookmark_id,
            changes,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bookmark not found",
        )
    return _to_bookmark_response(record)


@router.delete("/bookmarks/{bookmark_id}", response_model=DeleteResponse)
async def delete_bookmark(bookmark_id: int) -> DeleteResponse:
    """Delete a local Navigation bookmark."""
    factory = _ensure_session_factory()
    deleted = await bookmarks.delete_bookmark(
        factory, bookmark_id, activity_log=_activity_log
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bookmark not found",
        )
    return DeleteResponse(status="ok")


@router.post(
    "/saved-routes",
    response_model=SavedRouteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_saved_route(body: SavedRouteCreateRequest) -> SavedRouteResponse:
    """Create a local saved route record."""
    factory = _ensure_session_factory()
    try:
        record = await bookmarks.create_saved_route(
            factory,
            bookmarks.SavedRouteCreate(
                label=body.label,
                origin=body.origin,
                destination=body.destination,
                hop_count=body.hop_count,
                source_id=body.source_id,
                commander_note=body.commander_note,
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    return _to_route_response(record)


@router.patch("/saved-routes/{route_id}", response_model=SavedRouteResponse)
async def update_saved_route(
    route_id: int,
    body: SavedRoutePatchRequest,
) -> SavedRouteResponse:
    """Update a local saved route record (label/note only)."""
    factory = _ensure_session_factory()
    changes: bookmarks.SavedRouteUpdate = {}
    if body.label is not None:
        changes["label"] = body.label
    if "commander_note" in body.model_fields_set:
        changes["commander_note"] = body.commander_note

    try:
        record = await bookmarks.update_saved_route(
            factory,
            route_id,
            changes,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved route not found",
        )
    return _to_route_response(record)


@router.delete("/saved-routes/{route_id}", response_model=DeleteResponse)
async def delete_saved_route(route_id: int) -> DeleteResponse:
    """Delete a local saved route record."""
    factory = _ensure_session_factory()
    deleted = await bookmarks.delete_saved_route(
        factory, route_id, activity_log=_activity_log
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved route not found",
        )
    return DeleteResponse(status="ok")


# --- Bookmark tag-filter endpoint (Phase 9 PB09-04) -------------------------


class BookmarkListResponse(BaseModel):
    """Public API shape for a filtered list of local Navigation bookmarks."""

    model_config = ConfigDict(extra="forbid")

    bookmarks: list[BookmarkResponse]
    nullprovider_safe: bool = True


@router.get("/bookmarks", response_model=BookmarkListResponse)
async def list_bookmarks(
    tag: Optional[str] = Query(default=None),
) -> BookmarkListResponse:
    """Return local Navigation bookmarks, optionally filtered by tag.

    Supported Phase 9 tags: bgs_target, powerplay_target.
    When tag is omitted, returns all bookmarks.
    """
    factory = _ensure_session_factory()
    try:
        if tag is not None:
            records = await bookmarks.list_bookmarks_by_tag(factory, tag)
        else:
            records = await bookmarks.list_bookmarks(factory)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return BookmarkListResponse(bookmarks=[_to_bookmark_response(r) for r in records])


# --- Campaign circuit models and endpoints (Phase 9 PB09-04) ----------------


class StopResponse(BaseModel):
    """Public API shape for a campaign circuit stop."""

    model_config = ConfigDict(extra="forbid")

    stop_id: str
    circuit_id: str
    order_index: int
    system_name: str
    note: str | None
    linked_intel_fact_id: str | None
    created_at: str
    updated_at: str


class CircuitResponse(BaseModel):
    """Public API shape for a local campaign circuit."""

    model_config = ConfigDict(extra="forbid")

    circuit_id: str
    workflow_type: str
    title: str
    description: str | None
    linked_campaign_id: str | None
    source_label: str
    last_activity_log_event_id: str | None
    created_at: str
    updated_at: str
    archived_at: str | None
    stops: list[StopResponse]
    nullprovider_safe: bool = True


class CircuitListResponse(BaseModel):
    """Public API shape for a list of local campaign circuits."""

    model_config = ConfigDict(extra="forbid")

    circuits: list[CircuitResponse]
    nullprovider_safe: bool = True


class CircuitCreateRequest(BaseModel):
    """Commander-entered circuit creation request."""

    model_config = ConfigDict(extra="forbid")

    workflow_type: str = Field(min_length=1, max_length=16)
    title: str = Field(min_length=1, max_length=128)
    source_label: str = Field(default="commander_entered", max_length=32)
    description: str | None = Field(default=None, max_length=4000)
    linked_campaign_id: str | None = None


class CircuitPatchRequest(BaseModel):
    """Commander-entered circuit update request."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    source_label: str | None = Field(default=None, max_length=32)


class StopCreateRequest(BaseModel):
    """Commander-entered stop creation request."""

    model_config = ConfigDict(extra="forbid")

    system_name: str = Field(min_length=1, max_length=128)
    order_index: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=4000)
    linked_intel_fact_id: str | None = None


class StopPatchRequest(BaseModel):
    """Commander-entered stop update request."""

    model_config = ConfigDict(extra="forbid")

    system_name: str | None = Field(default=None, min_length=1, max_length=128)
    order_index: int | None = Field(default=None, ge=1)
    note: str | None = None
    linked_intel_fact_id: str | None = None


class LinkCampaignRequest(BaseModel):
    """Body for linking a campaign circuit to a campaign objective."""

    model_config = ConfigDict(extra="forbid")

    linked_campaign_id: str = Field(min_length=1, max_length=36)


def _to_stop_response(record: StopRecord) -> StopResponse:
    return StopResponse(
        stop_id=record.stop_id,
        circuit_id=record.circuit_id,
        order_index=record.order_index,
        system_name=record.system_name,
        note=record.note,
        linked_intel_fact_id=record.linked_intel_fact_id,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


def _to_circuit_response(record: CircuitRecord) -> CircuitResponse:
    return CircuitResponse(
        circuit_id=record.circuit_id,
        workflow_type=record.workflow_type,
        title=record.title,
        description=record.description,
        linked_campaign_id=record.linked_campaign_id,
        source_label=record.source_label,
        last_activity_log_event_id=record.last_activity_log_event_id,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        archived_at=record.archived_at.isoformat() if record.archived_at else None,
        stops=[_to_stop_response(s) for s in record.stops],
    )


@router.post(
    "/phase9/circuits",
    response_model=CircuitResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_circuit(body: CircuitCreateRequest) -> CircuitResponse:
    """Create a local campaign circuit."""
    factory = _ensure_session_factory()
    try:
        record = await circuits.create_circuit(
            factory,
            circuits.CircuitCreate(
                workflow_type=body.workflow_type,
                title=body.title,
                source_label=body.source_label,
                description=body.description,
                linked_campaign_id=body.linked_campaign_id,
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return _to_circuit_response(record)


@router.get("/phase9/circuits", response_model=CircuitListResponse)
async def list_circuits(
    workflow_type: Optional[str] = Query(default=None),
    linked_campaign_id: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
) -> CircuitListResponse:
    """Return local campaign circuits."""
    factory = _ensure_session_factory()
    try:
        records = await circuits.list_circuits(
            factory,
            workflow_type=workflow_type,
            linked_campaign_id=linked_campaign_id,
            include_archived=include_archived,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return CircuitListResponse(circuits=[_to_circuit_response(r) for r in records])


@router.get("/phase9/circuits/{circuit_id}", response_model=CircuitResponse)
async def get_circuit(circuit_id: str) -> CircuitResponse:
    """Return a local campaign circuit by id."""
    factory = _ensure_session_factory()
    record = await circuits.get_circuit(factory, circuit_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Circuit not found",
        )
    return _to_circuit_response(record)


@router.patch("/phase9/circuits/{circuit_id}", response_model=CircuitResponse)
async def update_circuit(
    circuit_id: str,
    body: CircuitPatchRequest,
) -> CircuitResponse:
    """Update title/description/source_label on a local campaign circuit."""
    factory = _ensure_session_factory()
    changes: circuits.CircuitUpdate = {}
    if body.title is not None:
        changes["title"] = body.title
    if "description" in body.model_fields_set:
        changes["description"] = body.description
    if body.source_label is not None:
        changes["source_label"] = body.source_label

    try:
        record = await circuits.update_circuit(
            factory, circuit_id, changes, activity_log=_activity_log
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Circuit not found",
        )
    return _to_circuit_response(record)


@router.delete("/phase9/circuits/{circuit_id}", response_model=DeleteResponse)
async def archive_circuit(circuit_id: str) -> DeleteResponse:
    """Soft-archive a local campaign circuit (row retained; archived_at set)."""
    factory = _ensure_session_factory()
    archived = await circuits.archive_circuit(
        factory, circuit_id, activity_log=_activity_log
    )
    if not archived:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Circuit not found",
        )
    return DeleteResponse(status="ok")


@router.post(
    "/phase9/circuits/{circuit_id}/stops",
    response_model=StopResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_stop(circuit_id: str, body: StopCreateRequest) -> StopResponse:
    """Add a stop to a campaign circuit."""
    factory = _ensure_session_factory()
    try:
        record = await circuits.add_stop(
            factory,
            circuit_id,
            circuits.StopCreate(
                system_name=body.system_name,
                order_index=body.order_index,
                note=body.note,
                linked_intel_fact_id=body.linked_intel_fact_id,
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return _to_stop_response(record)


@router.patch(
    "/phase9/circuits/{circuit_id}/stops/{stop_id}",
    response_model=StopResponse,
)
async def update_stop(
    circuit_id: str,
    stop_id: str,
    body: StopPatchRequest,
) -> StopResponse:
    """Update a campaign circuit stop."""
    factory = _ensure_session_factory()
    changes: circuits.StopUpdate = {}
    if body.system_name is not None:
        changes["system_name"] = body.system_name
    if body.order_index is not None:
        changes["order_index"] = body.order_index
    if "note" in body.model_fields_set:
        changes["note"] = body.note
    if "linked_intel_fact_id" in body.model_fields_set:
        changes["linked_intel_fact_id"] = body.linked_intel_fact_id

    try:
        record = await circuits.update_stop(
            factory, stop_id, changes, activity_log=_activity_log
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stop not found",
        )
    return _to_stop_response(record)


@router.delete(
    "/phase9/circuits/{circuit_id}/stops/{stop_id}",
    response_model=DeleteResponse,
)
async def remove_stop(circuit_id: str, stop_id: str) -> DeleteResponse:
    """Remove a stop from a campaign circuit."""
    factory = _ensure_session_factory()
    removed = await circuits.remove_stop(factory, stop_id, activity_log=_activity_log)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stop not found",
        )
    return DeleteResponse(status="ok")


@router.post(
    "/phase9/circuits/{circuit_id}/link-campaign",
    response_model=CircuitResponse,
)
async def link_campaign(
    circuit_id: str,
    body: LinkCampaignRequest,
) -> CircuitResponse:
    """Set a weak campaign link on a circuit."""
    factory = _ensure_session_factory()
    record = await circuits.link_campaign(
        factory, circuit_id, body.linked_campaign_id, activity_log=_activity_log
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Circuit not found",
        )
    return _to_circuit_response(record)


@router.delete(
    "/phase9/circuits/{circuit_id}/link-campaign",
    response_model=CircuitResponse,
)
async def unlink_campaign(circuit_id: str) -> CircuitResponse:
    """Clear the weak campaign link on a circuit."""
    factory = _ensure_session_factory()
    record = await circuits.unlink_campaign(
        factory, circuit_id, activity_log=_activity_log
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Circuit not found",
        )
    return _to_circuit_response(record)
