"""Local PvP encounter API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityLog
from omnicovas.features import pvp_encounter
from omnicovas.features.pvp_encounter import (
    MAX_COMMANDER_NAME_LENGTH,
    MAX_NOTE_LENGTH,
    MAX_RISK_EXPLANATION_LENGTH,
    MAX_SYSTEM_LENGTH,
    PvpEncounterRecord,
    PvpEncounterType,
    PvpEncounterUpdate,
)

router = APIRouter(prefix="/pvp", tags=["pvp"])

_session_factory: async_sessionmaker[AsyncSession] | None = None
_activity_log: ActivityLog | None = None


def set_session_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    """Inject the live async session factory into this router."""
    global _session_factory  # noqa: PLW0603
    _session_factory = session_factory


def set_activity_log(activity_log: ActivityLog | None) -> None:
    """Inject the shared ActivityLog used for PvP write audit entries."""
    global _activity_log  # noqa: PLW0603
    _activity_log = activity_log


def _ensure_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="PvP encounter store not initialized",
        )
    return _session_factory


def _strip_optional(value: object) -> object:
    if value is None or not isinstance(value, str):
        return value
    text = value.strip()
    return text or None


class PvpEncounterResponse(BaseModel):
    """Public API shape for a local PvP encounter record."""

    model_config = ConfigDict(extra="forbid")

    id: int
    timestamp: datetime
    created_at: datetime
    updated_at: datetime
    commander_name: str | None
    system: str | None
    source_label: str
    encounter_type: PvpEncounterType
    note: str
    risk_explanation: str | None
    provenance_event_type: str | None


class PvpEncounterListResponse(BaseModel):
    """List response wrapper for local PvP encounters."""

    model_config = ConfigDict(extra="forbid")

    encounters: list[PvpEncounterResponse]


class PvpEncounterCreateRequest(BaseModel):
    """Commander-entered PvP encounter note creation request."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime | None = None
    commander_name: str | None = Field(
        default=None,
        max_length=MAX_COMMANDER_NAME_LENGTH,
    )
    system: str | None = Field(default=None, max_length=MAX_SYSTEM_LENGTH)
    encounter_type: PvpEncounterType = "commander_entered"
    note: str = Field(min_length=1, max_length=MAX_NOTE_LENGTH)
    risk_explanation: str | None = Field(
        default=None,
        max_length=MAX_RISK_EXPLANATION_LENGTH,
    )

    @field_validator("commander_name", "system", "risk_explanation", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        return _strip_optional(value)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("note is required")
        return text


class PvpEncounterPatchRequest(BaseModel):
    """Commander-entered PvP encounter note update request."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime | None = None
    commander_name: str | None = Field(
        default=None,
        max_length=MAX_COMMANDER_NAME_LENGTH,
    )
    system: str | None = Field(default=None, max_length=MAX_SYSTEM_LENGTH)
    encounter_type: PvpEncounterType | None = None
    note: str | None = Field(default=None, min_length=1, max_length=MAX_NOTE_LENGTH)
    risk_explanation: str | None = Field(
        default=None,
        max_length=MAX_RISK_EXPLANATION_LENGTH,
    )

    @field_validator("commander_name", "system", "risk_explanation", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        return _strip_optional(value)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("note is required")
        return text

    @model_validator(mode="after")
    def _require_supported_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("At least one field is required")
        if "timestamp" in self.model_fields_set and self.timestamp is None:
            raise ValueError("timestamp cannot be null")
        if "note" in self.model_fields_set and self.note is None:
            raise ValueError("note cannot be null")
        if "encounter_type" in self.model_fields_set and self.encounter_type is None:
            raise ValueError("encounter_type cannot be null")
        return self


class DeleteResponse(BaseModel):
    """Delete response shape."""

    model_config = ConfigDict(extra="forbid")

    status: str


def _to_response(record: PvpEncounterRecord) -> PvpEncounterResponse:
    return PvpEncounterResponse(
        id=record.id,
        timestamp=record.timestamp,
        created_at=record.created_at,
        updated_at=record.updated_at,
        commander_name=record.commander_name,
        system=record.system,
        source_label=record.source_label,
        encounter_type=record.encounter_type,
        note=record.note,
        risk_explanation=record.risk_explanation,
        provenance_event_type=record.provenance_event_type,
    )


def _patch_changes(body: PvpEncounterPatchRequest) -> PvpEncounterUpdate:
    changes: PvpEncounterUpdate = {}
    if "timestamp" in body.model_fields_set and body.timestamp is not None:
        changes["timestamp"] = body.timestamp
    if "commander_name" in body.model_fields_set:
        changes["commander_name"] = body.commander_name
    if "system" in body.model_fields_set:
        changes["system"] = body.system
    if "note" in body.model_fields_set and body.note is not None:
        changes["note"] = body.note
    if "encounter_type" in body.model_fields_set and body.encounter_type is not None:
        changes["encounter_type"] = body.encounter_type
    if "risk_explanation" in body.model_fields_set:
        changes["risk_explanation"] = body.risk_explanation
    return changes


@router.get("/encounters", response_model=PvpEncounterListResponse)
async def list_pvp_encounters(
    limit: int = pvp_encounter.DEFAULT_LIMIT,
) -> PvpEncounterListResponse:
    """List local PvP encounter notes without writing Activity Log entries."""
    session_factory = _ensure_session_factory()
    try:
        records = await pvp_encounter.list_encounters(session_factory, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    return PvpEncounterListResponse(encounters=[_to_response(row) for row in records])


@router.get("/encounters/{encounter_id}", response_model=PvpEncounterResponse)
async def get_pvp_encounter(encounter_id: int) -> PvpEncounterResponse:
    """Get one local PvP encounter note without writing Activity Log entries."""
    record = await pvp_encounter.get_encounter(
        _ensure_session_factory(),
        encounter_id,
    )
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter note not found",
        )
    return _to_response(record)


@router.post(
    "/encounters",
    response_model=PvpEncounterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_pvp_encounter(
    body: PvpEncounterCreateRequest,
) -> PvpEncounterResponse:
    """Create a commander-entered local PvP encounter note."""
    try:
        record = await pvp_encounter.create_encounter(
            _ensure_session_factory(),
            pvp_encounter.PvpEncounterCreate(
                timestamp=body.timestamp,
                commander_name=body.commander_name,
                system=body.system,
                encounter_type=body.encounter_type,
                note=body.note,
                risk_explanation=body.risk_explanation,
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc
    return _to_response(record)


@router.patch("/encounters/{encounter_id}", response_model=PvpEncounterResponse)
async def update_pvp_encounter(
    encounter_id: int,
    body: PvpEncounterPatchRequest,
) -> PvpEncounterResponse:
    """Update allowed fields on a commander-entered local PvP encounter note."""
    try:
        record = await pvp_encounter.update_encounter(
            _ensure_session_factory(),
            encounter_id,
            _patch_changes(body),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT) from exc

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter note not found",
        )
    return _to_response(record)


@router.delete("/encounters/{encounter_id}", response_model=DeleteResponse)
async def delete_pvp_encounter(encounter_id: int) -> DeleteResponse:
    """Delete a commander-entered local PvP encounter note."""
    deleted = await pvp_encounter.delete_encounter(
        _ensure_session_factory(),
        encounter_id,
        activity_log=_activity_log,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter note not found",
        )
    return DeleteResponse(status="ok")
