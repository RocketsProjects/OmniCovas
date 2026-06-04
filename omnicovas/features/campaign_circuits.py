"""Local Navigation campaign circuit persistence helpers.

This module owns CampaignCircuit and CampaignCircuitStop CRUD for PB09-04.
Circuits are local-only BGS/Powerplay route planning artifacts.
They are not the active in-game route — NavRoute.json remains the in-game route truth.

No outbound calls. No AI. No provider activation. No second state manager.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Final, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import (
    ActivityEntry,
    ActivityLog,
    normalize_phase9_payload,
)
from omnicovas.core.event_types import (
    PHASE_9_NAVIGATION_CIRCUIT_ARCHIVED,
    PHASE_9_NAVIGATION_CIRCUIT_CREATED,
    PHASE_9_NAVIGATION_CIRCUIT_LINKED_TO_CAMPAIGN,
    PHASE_9_NAVIGATION_CIRCUIT_UNLINKED_FROM_CAMPAIGN,
    PHASE_9_NAVIGATION_CIRCUIT_UPDATED,
    PHASE_9_NAVIGATION_STOP_ADDED,
    PHASE_9_NAVIGATION_STOP_REMOVED,
    PHASE_9_NAVIGATION_STOP_UPDATED,
)
from omnicovas.db.models import CampaignCircuitRef, CampaignCircuitStopRef

MAX_TITLE_LENGTH: Final[int] = 128
MAX_SYSTEM_NAME_LENGTH: Final[int] = 128
MAX_NOTE_LENGTH: Final[int] = 4000
MAX_STOPS: Final[int] = 100
DEFAULT_LIMIT: Final[int] = 100
MAX_LIMIT: Final[int] = 500

VALID_WORKFLOW_TYPES: Final[frozenset[str]] = frozenset({"bgs", "powerplay"})
VALID_SOURCE_LABELS: Final[frozenset[str]] = frozenset(
    {"commander_entered", "derived_from_navroute", "spansh_link_out_only"}
)


@dataclass(frozen=True)
class CircuitCreate:
    """Input for creating a local campaign circuit."""

    workflow_type: str
    title: str
    source_label: str = "commander_entered"
    description: str | None = None
    linked_campaign_id: str | None = None


class CircuitUpdate(TypedDict, total=False):
    """Allowed partial update fields for a local campaign circuit."""

    title: str
    description: str | None
    source_label: str


@dataclass(frozen=True)
class StopCreate:
    """Input for adding a stop to a campaign circuit."""

    system_name: str
    order_index: int
    note: str | None = None
    linked_intel_fact_id: str | None = None


class StopUpdate(TypedDict, total=False):
    """Allowed partial update fields for a circuit stop."""

    system_name: str
    order_index: int
    note: str | None
    linked_intel_fact_id: str | None


@dataclass(frozen=True)
class StopRecord:
    """Typed read model for a campaign circuit stop."""

    stop_id: str
    circuit_id: str
    order_index: int
    system_name: str
    note: str | None
    linked_intel_fact_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class CircuitRecord:
    """Typed read model for a local campaign circuit."""

    circuit_id: str
    workflow_type: str
    title: str
    description: str | None
    linked_campaign_id: str | None
    source_label: str
    last_activity_log_event_id: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    stops: list[StopRecord] = field(default_factory=list)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _activity_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat() + "Z"


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _clean_required_text(value: str, *, field_name: str, max_length: int) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    if len(text) > max_length:
        raise ValueError(f"{field_name} is too long")
    return text


def _clean_optional_text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > max_length:
        raise ValueError(f"{field_name} is too long")
    return text


def _validate_workflow_type(value: str) -> str:
    if value not in VALID_WORKFLOW_TYPES:
        raise ValueError(
            f"workflow_type must be one of {sorted(VALID_WORKFLOW_TYPES)},"
            f" got {value!r}"
        )
    return value


def _validate_source_label(value: str) -> str:
    if value not in VALID_SOURCE_LABELS:
        raise ValueError(
            f"source_label must be one of {sorted(VALID_SOURCE_LABELS)}, got {value!r}"
        )
    return value


def _append_activity(
    activity_log: ActivityLog | None,
    *,
    event_type: str,
    summary: str,
    payload: dict[str, object] | None = None,
    source_chain: list[dict[str, object]] | None = None,
) -> None:
    if activity_log is None:
        return
    activity_log.append(
        ActivityEntry(
            event_type=event_type,
            timestamp=_activity_timestamp(),
            summary=summary,
            payload=normalize_phase9_payload(payload or {}),
            source_chain=source_chain,
            redaction_state="redacted_summary_only",
            is_fact=False,
            surface_origin="navigation",
            source="commander_entered",
        )
    )


def _source_chain_for_circuit(
    *,
    workflow_type: str,
    source_label: str,
) -> list[dict[str, object]]:
    truth_class = (
        "local_event_history"
        if source_label == "derived_from_navroute"
        else "external_link_out_only"
        if source_label == "spansh_link_out_only"
        else "commander_entered"
    )
    return [
        {
            "source": source_label,
            "source_type": "local_navigation_planning",
            "truth_class": truth_class,
            "freshness": "last_known",
            "workflow_type": workflow_type,
        }
    ]


def _to_stop_record(row: CampaignCircuitStopRef) -> StopRecord:
    return StopRecord(
        stop_id=str(row.stop_id),
        circuit_id=str(row.circuit_id),
        order_index=int(row.order_index),
        system_name=row.system_name,
        note=row.note,
        linked_intel_fact_id=row.linked_intel_fact_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_circuit_record(
    row: CampaignCircuitRef, stops: list[StopRecord] | None = None
) -> CircuitRecord:
    return CircuitRecord(
        circuit_id=str(row.circuit_id),
        workflow_type=row.workflow_type,
        title=row.title,
        description=row.description,
        linked_campaign_id=row.linked_campaign_id,
        source_label=row.source_label,
        last_activity_log_event_id=row.last_activity_log_event_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
        stops=stops or [],
    )


# --- Circuit CRUD -----------------------------------------------------------


async def create_circuit(
    session_factory: async_sessionmaker[AsyncSession],
    payload: CircuitCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> CircuitRecord:
    """Create a local campaign circuit and audit the write."""
    now = _utc_now()
    circuit_id = _new_uuid()
    row = CampaignCircuitRef(
        circuit_id=circuit_id,
        workflow_type=_validate_workflow_type(payload.workflow_type),
        title=_clean_required_text(
            payload.title, field_name="title", max_length=MAX_TITLE_LENGTH
        ),
        description=_clean_optional_text(
            payload.description, field_name="description", max_length=MAX_NOTE_LENGTH
        ),
        linked_campaign_id=payload.linked_campaign_id or None,
        source_label=_validate_source_label(payload.source_label),
        last_activity_log_event_id=None,
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    async with session_factory() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)

    _append_activity(
        activity_log,
        event_type=PHASE_9_NAVIGATION_CIRCUIT_CREATED,
        summary=(
            f"circuit_created: circuit_id={circuit_id} "
            f"workflow_type={payload.workflow_type} "
            f"source_label={payload.source_label} "
            f"redacted=True"
        ),
        payload={
            "circuit_id": circuit_id,
            "workflow_type": row.workflow_type,
            "stop_count": 0,
            "source_label": row.source_label,
            "linked_campaign_id": row.linked_campaign_id,
        },
        source_chain=_source_chain_for_circuit(
            workflow_type=row.workflow_type,
            source_label=row.source_label,
        ),
    )
    return _to_circuit_record(row)


async def list_circuits(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_type: str | None = None,
    linked_campaign_id: str | None = None,
    include_archived: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> list[CircuitRecord]:
    """Return local campaign circuits, newest first. Excludes archived by default."""
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError("limit is out of range")

    async with session_factory() as db:
        stmt = select(CampaignCircuitRef)
        if not include_archived:
            stmt = stmt.where(CampaignCircuitRef.archived_at.is_(None))
        if workflow_type is not None:
            stmt = stmt.where(CampaignCircuitRef.workflow_type == workflow_type)
        if linked_campaign_id is not None:
            stmt = stmt.where(
                CampaignCircuitRef.linked_campaign_id == linked_campaign_id
            )
        stmt = stmt.order_by(CampaignCircuitRef.updated_at.desc()).limit(limit)
        result = await db.execute(stmt)
        rows = list(result.scalars().all())

        circuit_ids = [row.circuit_id for row in rows]
        stops_by_circuit: dict[str, list[StopRecord]] = {cid: [] for cid in circuit_ids}
        if circuit_ids:
            stop_result = await db.execute(
                select(CampaignCircuitStopRef)
                .where(CampaignCircuitStopRef.circuit_id.in_(circuit_ids))
                .order_by(
                    CampaignCircuitStopRef.circuit_id,
                    CampaignCircuitStopRef.order_index,
                )
            )
            for stop_row in stop_result.scalars().all():
                stops_by_circuit[stop_row.circuit_id].append(_to_stop_record(stop_row))

    return [_to_circuit_record(row, stops_by_circuit[row.circuit_id]) for row in rows]


async def get_circuit(
    session_factory: async_sessionmaker[AsyncSession],
    circuit_id: str,
) -> CircuitRecord | None:
    """Return a local campaign circuit by id, including its stops."""
    async with session_factory() as db:
        row = await db.get(CampaignCircuitRef, circuit_id)
        if row is None:
            return None
        stop_result = await db.execute(
            select(CampaignCircuitStopRef)
            .where(CampaignCircuitStopRef.circuit_id == circuit_id)
            .order_by(CampaignCircuitStopRef.order_index)
        )
        stops = [_to_stop_record(s) for s in stop_result.scalars().all()]

    return _to_circuit_record(row, stops)


async def update_circuit(
    session_factory: async_sessionmaker[AsyncSession],
    circuit_id: str,
    changes: CircuitUpdate,
    *,
    activity_log: ActivityLog | None = None,
) -> CircuitRecord | None:
    """Update title/description/source_label on a local campaign circuit."""
    async with session_factory() as db:
        row = await db.get(CampaignCircuitRef, circuit_id)
        if row is None:
            return None

        if "title" in changes:
            row.title = _clean_required_text(
                changes["title"], field_name="title", max_length=MAX_TITLE_LENGTH
            )
        if "description" in changes:
            row.description = _clean_optional_text(
                changes["description"],
                field_name="description",
                max_length=MAX_NOTE_LENGTH,
            )
        if "source_label" in changes:
            row.source_label = _validate_source_label(changes["source_label"])

        row.updated_at = _utc_now()
        await db.commit()
        await db.refresh(row)

        stop_result = await db.execute(
            select(CampaignCircuitStopRef)
            .where(CampaignCircuitStopRef.circuit_id == circuit_id)
            .order_by(CampaignCircuitStopRef.order_index)
        )
        stops = [_to_stop_record(s) for s in stop_result.scalars().all()]

    _append_activity(
        activity_log,
        event_type=PHASE_9_NAVIGATION_CIRCUIT_UPDATED,
        summary=(
            f"circuit_updated: circuit_id={circuit_id} "
            f"workflow_type={row.workflow_type} "
            f"redacted=True"
        ),
        payload={
            "circuit_id": circuit_id,
            "workflow_type": row.workflow_type,
            "stop_count": len(stops),
            "source_label": row.source_label,
        },
        source_chain=_source_chain_for_circuit(
            workflow_type=row.workflow_type,
            source_label=row.source_label,
        ),
    )
    return _to_circuit_record(row, stops)


async def archive_circuit(
    session_factory: async_sessionmaker[AsyncSession],
    circuit_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> bool:
    """Soft-archive a local campaign circuit. Row is retained; archived_at is set."""
    async with session_factory() as db:
        row = await db.get(CampaignCircuitRef, circuit_id)
        if row is None:
            return False
        row.archived_at = _utc_now()
        row.updated_at = _utc_now()
        await db.commit()

    _append_activity(
        activity_log,
        event_type=PHASE_9_NAVIGATION_CIRCUIT_ARCHIVED,
        summary=(
            f"circuit_archived: circuit_id={circuit_id} "
            f"workflow_type={row.workflow_type} "
            f"redacted=True"
        ),
        payload={
            "circuit_id": circuit_id,
            "workflow_type": row.workflow_type,
            "source_label": row.source_label,
        },
        source_chain=_source_chain_for_circuit(
            workflow_type=row.workflow_type,
            source_label=row.source_label,
        ),
    )
    return True


# --- Stop CRUD --------------------------------------------------------------


async def add_stop(
    session_factory: async_sessionmaker[AsyncSession],
    circuit_id: str,
    payload: StopCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> StopRecord:
    """Add a stop to an existing campaign circuit."""
    async with session_factory() as db:
        circuit_row = await db.get(CampaignCircuitRef, circuit_id)
        if circuit_row is None:
            raise ValueError(f"circuit_id {circuit_id!r} not found")

        # Validate stop count before inserting.
        count_result = await db.execute(
            select(CampaignCircuitStopRef).where(
                CampaignCircuitStopRef.circuit_id == circuit_id
            )
        )
        existing_stops = list(count_result.scalars().all())
        if len(existing_stops) >= MAX_STOPS:
            raise ValueError(f"Circuit already has {MAX_STOPS} stops; cannot add more")

        now = _utc_now()
        stop_id = _new_uuid()
        stop_row = CampaignCircuitStopRef(
            stop_id=stop_id,
            circuit_id=circuit_id,
            order_index=payload.order_index,
            system_name=_clean_required_text(
                payload.system_name,
                field_name="system_name",
                max_length=MAX_SYSTEM_NAME_LENGTH,
            ),
            note=_clean_optional_text(
                payload.note, field_name="note", max_length=MAX_NOTE_LENGTH
            ),
            linked_intel_fact_id=payload.linked_intel_fact_id or None,
            created_at=now,
            updated_at=now,
        )
        db.add(stop_row)
        circuit_row.updated_at = now
        workflow_type = circuit_row.workflow_type
        source_label = circuit_row.source_label
        await db.commit()
        await db.refresh(stop_row)

    _append_activity(
        activity_log,
        event_type=PHASE_9_NAVIGATION_STOP_ADDED,
        summary=(
            f"stop_added: stop_id={stop_id} circuit_id={circuit_id} "
            f"order_index={payload.order_index} redacted=True"
        ),
        payload={
            "circuit_id": circuit_id,
            "stop_id": stop_id,
            "workflow_type": workflow_type,
            "stop_count": len(existing_stops) + 1,
            "order_index": payload.order_index,
            "source_label": source_label,
            "linked_intel_fact_id": payload.linked_intel_fact_id,
        },
        source_chain=_source_chain_for_circuit(
            workflow_type=workflow_type,
            source_label=source_label,
        ),
    )
    return _to_stop_record(stop_row)


async def update_stop(
    session_factory: async_sessionmaker[AsyncSession],
    stop_id: str,
    changes: StopUpdate,
    *,
    activity_log: ActivityLog | None = None,
) -> StopRecord | None:
    """Update system_name/note/order_index/linked_intel_fact_id on a circuit stop."""
    async with session_factory() as db:
        stop_row = await db.get(CampaignCircuitStopRef, stop_id)
        if stop_row is None:
            return None

        if "system_name" in changes:
            stop_row.system_name = _clean_required_text(
                changes["system_name"],
                field_name="system_name",
                max_length=MAX_SYSTEM_NAME_LENGTH,
            )
        if "order_index" in changes:
            stop_row.order_index = changes["order_index"]
        if "note" in changes:
            stop_row.note = _clean_optional_text(
                changes["note"], field_name="note", max_length=MAX_NOTE_LENGTH
            )
        if "linked_intel_fact_id" in changes:
            stop_row.linked_intel_fact_id = changes["linked_intel_fact_id"] or None

        circuit_row = await db.get(CampaignCircuitRef, stop_row.circuit_id)
        workflow_type = circuit_row.workflow_type if circuit_row else "bgs"
        source_label = circuit_row.source_label if circuit_row else "commander_entered"
        stop_row.updated_at = _utc_now()
        await db.commit()
        await db.refresh(stop_row)

    _append_activity(
        activity_log,
        event_type=PHASE_9_NAVIGATION_STOP_UPDATED,
        summary=(
            f"stop_updated: stop_id={stop_id} circuit_id={stop_row.circuit_id} "
            f"redacted=True"
        ),
        payload={
            "circuit_id": stop_row.circuit_id,
            "stop_id": stop_id,
            "workflow_type": workflow_type,
            "changed_fields": sorted(changes.keys()),
            "source_label": source_label,
            "linked_intel_fact_id": stop_row.linked_intel_fact_id,
        },
        source_chain=_source_chain_for_circuit(
            workflow_type=workflow_type,
            source_label=source_label,
        ),
    )
    return _to_stop_record(stop_row)


async def remove_stop(
    session_factory: async_sessionmaker[AsyncSession],
    stop_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> bool:
    """Remove a stop from a campaign circuit."""
    async with session_factory() as db:
        stop_row = await db.get(CampaignCircuitStopRef, stop_id)
        if stop_row is None:
            return False
        circuit_id = stop_row.circuit_id
        await db.delete(stop_row)
        circuit_row = await db.get(CampaignCircuitRef, circuit_id)
        if circuit_row is not None:
            circuit_row.updated_at = _utc_now()
        workflow_type = circuit_row.workflow_type if circuit_row else "bgs"
        source_label = circuit_row.source_label if circuit_row else "commander_entered"
        await db.commit()

    _append_activity(
        activity_log,
        event_type=PHASE_9_NAVIGATION_STOP_REMOVED,
        summary=(
            f"stop_removed: stop_id={stop_id} circuit_id={circuit_id} redacted=True"
        ),
        payload={
            "circuit_id": circuit_id,
            "stop_id": stop_id,
            "workflow_type": workflow_type,
            "source_label": source_label,
        },
        source_chain=_source_chain_for_circuit(
            workflow_type=workflow_type,
            source_label=source_label,
        ),
    )
    return True


# --- Campaign weak link -----------------------------------------------------


async def link_campaign(
    session_factory: async_sessionmaker[AsyncSession],
    circuit_id: str,
    campaign_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> CircuitRecord | None:
    """Set a weak campaign link on a circuit (no FK — string reference only)."""
    async with session_factory() as db:
        row = await db.get(CampaignCircuitRef, circuit_id)
        if row is None:
            return None
        row.linked_campaign_id = campaign_id
        row.updated_at = _utc_now()
        await db.commit()
        await db.refresh(row)

        stop_result = await db.execute(
            select(CampaignCircuitStopRef)
            .where(CampaignCircuitStopRef.circuit_id == circuit_id)
            .order_by(CampaignCircuitStopRef.order_index)
        )
        stops = [_to_stop_record(s) for s in stop_result.scalars().all()]

    _append_activity(
        activity_log,
        event_type=PHASE_9_NAVIGATION_CIRCUIT_LINKED_TO_CAMPAIGN,
        summary=(
            f"circuit_linked_to_campaign: circuit_id={circuit_id} "
            f"linked_campaign_id={campaign_id} redacted=True"
        ),
        payload={
            "circuit_id": circuit_id,
            "workflow_type": row.workflow_type,
            "linked_campaign_id": campaign_id,
            "source_label": row.source_label,
            "stop_count": len(stops),
        },
        source_chain=_source_chain_for_circuit(
            workflow_type=row.workflow_type,
            source_label=row.source_label,
        ),
    )
    return _to_circuit_record(row, stops)


async def unlink_campaign(
    session_factory: async_sessionmaker[AsyncSession],
    circuit_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> CircuitRecord | None:
    """Clear the weak campaign link on a circuit."""
    async with session_factory() as db:
        row = await db.get(CampaignCircuitRef, circuit_id)
        if row is None:
            return None
        previous_campaign_id = row.linked_campaign_id
        row.linked_campaign_id = None
        row.updated_at = _utc_now()
        await db.commit()
        await db.refresh(row)

        stop_result = await db.execute(
            select(CampaignCircuitStopRef)
            .where(CampaignCircuitStopRef.circuit_id == circuit_id)
            .order_by(CampaignCircuitStopRef.order_index)
        )
        stops = [_to_stop_record(s) for s in stop_result.scalars().all()]

    _append_activity(
        activity_log,
        event_type=PHASE_9_NAVIGATION_CIRCUIT_UNLINKED_FROM_CAMPAIGN,
        summary=(
            f"circuit_unlinked_from_campaign: circuit_id={circuit_id} "
            f"previous_campaign_id={previous_campaign_id} redacted=True"
        ),
        payload={
            "circuit_id": circuit_id,
            "workflow_type": row.workflow_type,
            "linked_campaign_id": previous_campaign_id,
            "source_label": row.source_label,
            "stop_count": len(stops),
        },
        source_chain=_source_chain_for_circuit(
            workflow_type=row.workflow_type,
            source_label=row.source_label,
        ),
    )
    return _to_circuit_record(row, stops)


# JSON helper for serialising stop list into an activity log count summary.
def _stop_count_for_log(stops: list[StopRecord]) -> int:
    return len(stops)
