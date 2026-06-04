"""Phase 8 local-only Engineering planning persistence helpers.

Engineering owns commander-entered goals, planned builds, material gap planning,
readiness notes, and handoff intent records. It does not enable providers, call
external services, infer Elite Dangerous mechanics, or mutate game state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Final, Literal, TypedDict, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.event_types import (
    ENGINEERING_ACQUISITION_HANDOFF_TO_NAVIGATION,
    ENGINEERING_ACQUISITION_PLAN_ARCHIVED,
    ENGINEERING_ACQUISITION_PLAN_CREATED,
    ENGINEERING_ACQUISITION_PLAN_STATE_CHANGED,
    ENGINEERING_ACQUISITION_PLAN_UPDATED,
    ENGINEERING_BLUEPRINT_PROGRESS_CREATED,
    ENGINEERING_BUILDPLAN_ARCHIVED,
    ENGINEERING_BUILDPLAN_CREATED,
    ENGINEERING_BUILDPLAN_UPDATED,
    ENGINEERING_ENGINEER_UNLOCK_STATE_CREATED,
    ENGINEERING_GOAL_ARCHIVED,
    ENGINEERING_GOAL_CREATED,
    ENGINEERING_GOAL_STATE_CHANGED,
    ENGINEERING_GOAL_UPDATED,
    ENGINEERING_GUARDIAN_TECH_PROGRESS_CREATED,
    ENGINEERING_IMPORT_SOURCE_STATE_CREATED,
    ENGINEERING_MATERIAL_GAP_OVERRIDE_CLEARED,
    ENGINEERING_MATERIAL_GAP_OVERRIDE_SET,
    ENGINEERING_SOURCE_ATTEMPT_DISABLED,
    ENGINEERING_SUIT_ENGINEERING_STATE_CREATED,
    ENGINEERING_TASK_HANDOFF_TO_OPERATIONS,
)
from omnicovas.db.models import (
    EngineeringAcquisitionPlanRef,
    EngineeringBlueprintProgressRef,
    EngineeringBuildPlanRef,
    EngineeringEngineerUnlockStateRef,
    EngineeringGoalRef,
    EngineeringGuardianTechProgressRef,
    EngineeringImportSourceStateRef,
    EngineeringMaterialGapOverrideRef,
    EngineeringSuitEngineeringStateRef,
)

JsonDict = dict[str, Any]
JsonList = list[Any]

DEFAULT_LIMIT: Final[int] = 100
MAX_LIMIT: Final[int] = 500
MAX_TITLE_LENGTH: Final[int] = 128
MAX_LABEL_LENGTH: Final[int] = 128
MAX_NOTE_LENGTH: Final[int] = 4000
MAX_URL_LENGTH: Final[int] = 2048

GOAL_TARGET_KINDS: Final[frozenset[str]] = frozenset(
    {
        "module_engineering",
        "ship_unlock",
        "engineer_unlock",
        "guardian_tech",
        "tech_broker_unlock",
        "suit_engineering",
        "general_progression",
        "commander_defined_other",
    }
)
GOAL_STATES: Final[frozenset[str]] = frozenset(
    {"draft", "active", "blocked", "paused", "complete", "archived"}
)
PRIORITIES: Final[frozenset[str]] = frozenset({"low", "normal", "high", "unsorted"})
BUILD_SOURCES: Final[frozenset[str]] = frozenset(
    {
        "commander_defined",
        "intel_current_loadout_reference",
        "imported_edsy",
        "imported_coriolis",
        "imported_other_format_verified",
    }
)
FORMAT_STATES: Final[frozenset[str]] = frozenset(
    {"format_unverified", "format_verified", "format_rejected", "not_applicable"}
)
BUILD_STATES: Final[frozenset[str]] = frozenset(
    {"draft", "active", "blocked", "paused", "complete", "archived"}
)
ACQUISITION_STATES: Final[frozenset[str]] = frozenset(
    {
        "draft",
        "handoff_sent_to_navigation",
        "route_candidates_returned",
        "commander_chose_candidate",
        "handoff_sent_to_operations",
        "operations_active",
        "complete",
        "archived",
    }
)
READINESS_KINDS: Final[frozenset[str]] = frozenset(
    {
        "blueprint_progress",
        "engineer_unlock_state",
        "guardian_tech_progress",
        "suit_engineering_state",
    }
)
READINESS_STATES: Final[frozenset[str]] = frozenset(
    {"manual", "unsupported", "no_verified_source", "not_loaded", "blocked"}
)
REQUIREMENTS_STATES: Final[frozenset[str]] = frozenset(
    {"manual", "unsupported", "no_verified_source", "not_loaded"}
)
IMPORT_PROVIDERS: Final[frozenset[str]] = frozenset({"edsy", "coriolis"})
SOURCE_CAVEATS: Final[tuple[str, ...]] = (
    "CAPI material inventory is disabled and source-gated.",
    "EDSY and Coriolis format verification evidence is not present.",
    "Missing local material files are not treated as zero inventory.",
)


class EngineeringGoalUpdate(TypedDict, total=False):
    """Allowed partial update fields for a local Engineering goal."""

    title: str
    description: str | None
    target_kind: str
    target_reference: JsonDict
    state: str
    priority: str
    notes: str | None
    linked_build_plan_id: str | None


class BuildPlanUpdate(TypedDict, total=False):
    """Allowed partial update fields for a local planned build."""

    title: str
    description: str | None
    target_ship: JsonDict
    target_loadout_summary: JsonDict
    source: str
    format_verification_state: str
    state: str
    linked_goal_ids: list[str]
    source_url: str | None
    notes: str | None


class AcquisitionPlanUpdate(TypedDict, total=False):
    """Allowed partial update fields for a local acquisition plan."""

    title: str
    linked_goal_ids: list[str]
    linked_build_plan_ids: list[str]
    target_materials: list[JsonDict]
    state: str
    notes: str | None


class ReadinessUpdate(TypedDict, total=False):
    """Allowed partial update fields for local readiness states."""

    label: str
    state: str
    requirements_known: str
    requirements_text: str | None
    notes: str | None
    target_grade: str
    target_engineer_label: str | None
    target_module_label: str | None


@dataclass(frozen=True)
class EngineeringGoalCreate:
    """Input for a commander-entered Engineering goal."""

    title: str
    commander_id: str | None = None
    description: str | None = None
    target_kind: str = "commander_defined_other"
    target_reference: JsonDict = field(default_factory=dict)
    state: str = "draft"
    priority: str = "normal"
    notes: str | None = None
    linked_build_plan_id: str | None = None


@dataclass(frozen=True)
class EngineeringGoalRecord:
    """Read model for a local Engineering goal."""

    goal_id: str
    commander_id: str | None
    title: str
    description: str | None
    target_kind: str
    target_reference: JsonDict
    state: str
    priority: str
    notes: str | None
    linked_build_plan_id: str | None
    linked_material_gap_view_id: str | None
    linked_acquisition_handoff_ids: list[str]
    linked_operations_task_id: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class BuildPlanCreate:
    """Input for a local planned build."""

    title: str
    description: str | None = None
    target_ship: JsonDict = field(default_factory=dict)
    target_loadout_summary: JsonDict = field(default_factory=dict)
    source: str = "commander_defined"
    format_verification_state: str = "not_applicable"
    state: str = "draft"
    linked_goal_ids: list[str] = field(default_factory=list)
    source_url: str | None = None
    notes: str | None = None


@dataclass(frozen=True)
class BuildPlanRecord:
    """Read model for a planned build separated from current loadout."""

    build_plan_id: str
    title: str
    description: str | None
    target_ship: JsonDict
    target_loadout_summary: JsonDict
    source: str
    format_verification_state: str
    state: str
    linked_goal_ids: list[str]
    linked_material_gap_view_id: str | None
    source_url: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MaterialGapOverrideUpsert:
    """Commander-entered material counts used only for planning."""

    material_id: str
    material_display_name: str
    goal_id: str | None = None
    build_plan_id: str | None = None
    commander_override_required: int | None = None
    commander_override_current: int | None = None
    required_note: str | None = None
    current_note: str | None = None


@dataclass(frozen=True)
class MaterialGapRecord:
    """Computed material gap view row."""

    gap_view_id: str
    material_id: str
    material_display_name: str
    goal_id: str | None
    build_plan_id: str | None
    required_count: int | None
    current_count: int | None
    missing_count: int | None
    gap_state: str
    requirement_state: str
    inventory_state: str
    source_chain: list[JsonDict]
    caveats: list[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AcquisitionPlanCreate:
    """Input for a local acquisition plan."""

    title: str
    linked_goal_ids: list[str] = field(default_factory=list)
    linked_build_plan_ids: list[str] = field(default_factory=list)
    target_materials: list[JsonDict] = field(default_factory=list)
    state: str = "draft"
    notes: str | None = None


@dataclass(frozen=True)
class AcquisitionPlanRecord:
    """Read model for a local acquisition plan."""

    acquisition_plan_id: str
    title: str
    linked_goal_ids: list[str]
    linked_build_plan_ids: list[str]
    target_materials: list[JsonDict]
    state: str
    navigation_handoff_ids: list[str]
    operations_task_id: str | None
    selected_navigation_candidate_summary: JsonDict
    notes: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class HandoffResult:
    """Route-transfer handoff plus updated acquisition plan."""

    plan: AcquisitionPlanRecord
    route_transfer_intent: JsonDict


@dataclass(frozen=True)
class ReadinessCreate:
    """Input for conservative local/manual readiness tracking."""

    kind: str
    label: str
    state: str = "manual"
    requirements_known: str = "manual"
    requirements_text: str | None = None
    notes: str | None = None
    target_grade: str = "manual"
    target_engineer_label: str | None = None
    target_module_label: str | None = None


@dataclass(frozen=True)
class ReadinessRecord:
    """Read model for conservative readiness surfaces."""

    readiness_id: str
    kind: str
    label: str
    state: str
    requirements_known: str
    requirements_text: str | None
    notes: str | None
    target_grade: str | None
    target_engineer_label: str | None
    target_module_label: str | None
    created_at: datetime
    updated_at: datetime
    caveats: list[str]
    source_chain: list[JsonDict]


@dataclass(frozen=True)
class ImportSourceStateRecord:
    """Read model for disabled/source-gated build interop posture."""

    import_source_state_id: str
    provider_label: str
    format_version_label: str | None
    format_verification_state: str
    format_verification_evidence_summary: str | None
    consent_state: str
    notes: str | None
    caveats: list[str]
    import_available: bool
    export_available: bool
    outbound_available: bool
    created_at: datetime | None
    updated_at: datetime | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_id() -> str:
    return str(uuid4())


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_object(text: str | None) -> JsonDict:
    if not text:
        return {}
    loaded = json.loads(text)
    return loaded if isinstance(loaded, dict) else {}


def _json_list(text: str | None) -> JsonList:
    if not text:
        return []
    loaded = json.loads(text)
    return loaded if isinstance(loaded, list) else []


def _json_string_list(text: str | None) -> list[str]:
    return [str(item) for item in _json_list(text)]


def _clean_text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    text = value.strip()
    if not text:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    if len(text) > max_length:
        raise ValueError(f"{field_name} is too long")
    return text


def _required_text(value: str, *, field_name: str, max_length: int) -> str:
    result = _clean_text(
        value,
        field_name=field_name,
        max_length=max_length,
        required=True,
    )
    if result is None:
        raise ValueError(f"{field_name} is required")
    return result


def _validate_choice(value: str, choices: frozenset[str], field_name: str) -> str:
    clean = _required_text(value, field_name=field_name, max_length=96)
    if clean not in choices:
        raise ValueError(f"{field_name} is unsupported")
    return clean


def _validate_non_negative(value: int | None, field_name: str) -> int | None:
    if value is None:
        return None
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return value


def _clean_url(value: str | None) -> str | None:
    text = _clean_text(value, field_name="source_url", max_length=MAX_URL_LENGTH)
    if text is None:
        return None
    lowered = text.lower()
    if not (lowered.startswith("https://") or lowered.startswith("http://")):
        raise ValueError("source_url must use http or https")
    return text


def _validate_limit(limit: int) -> int:
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError("limit is out of range")
    return limit


def _source_chain_manual(kind: str) -> list[JsonDict]:
    return [
        {
            "source": "commander_entered",
            "truth_class": "commander_entered",
            "freshness": "manual",
            "kind": kind,
        }
    ]


def _source_chain_disabled(provider: str) -> list[JsonDict]:
    return [
        {
            "source": provider,
            "truth_class": "external_disabled",
            "freshness": "not_loaded",
            "kind": "format_unverified",
        }
    ]


def _append_activity(
    activity_log: ActivityLog | None,
    *,
    event_type: str,
    summary: str,
    payload: JsonDict | None = None,
    source_chain: list[JsonDict] | None = None,
    linked_entity_refs: JsonDict | None = None,
    source: str = "commander_entered",
    is_fact: bool = False,
) -> str | None:
    if activity_log is None:
        return None
    event_id = _new_id()
    activity_log.append(
        ActivityEntry(
            event_type=event_type,
            timestamp=_timestamp(),
            summary=summary,
            payload=payload or {},
            source_chain=source_chain or _source_chain_manual("engineering"),
            redaction_state="redacted_summary_only",
            is_fact=is_fact,
            linked_entity_refs=linked_entity_refs or {},
            surface_origin="engineering",
            correlation_id=event_id,
            event_id=event_id,
            source=source,
        )
    )
    return event_id


def _goal_record(row: EngineeringGoalRef) -> EngineeringGoalRecord:
    return EngineeringGoalRecord(
        goal_id=row.goal_id,
        commander_id=row.commander_id,
        title=row.title,
        description=row.description,
        target_kind=row.target_kind,
        target_reference=_json_object(row.target_reference_json),
        state=row.state,
        priority=row.priority,
        notes=row.notes,
        linked_build_plan_id=row.linked_build_plan_id,
        linked_material_gap_view_id=row.linked_material_gap_view_id,
        linked_acquisition_handoff_ids=_json_string_list(
            row.linked_acquisition_handoff_ids_json
        ),
        linked_operations_task_id=row.linked_operations_task_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _build_plan_record(row: EngineeringBuildPlanRef) -> BuildPlanRecord:
    return BuildPlanRecord(
        build_plan_id=row.build_plan_id,
        title=row.title,
        description=row.description,
        target_ship=_json_object(row.target_ship_json),
        target_loadout_summary=_json_object(row.target_loadout_summary_json),
        source=row.source,
        format_verification_state=row.format_verification_state,
        state=row.state,
        linked_goal_ids=_json_string_list(row.linked_goal_ids_json),
        linked_material_gap_view_id=row.linked_material_gap_view_id,
        source_url=row.source_url,
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _acquisition_plan_record(
    row: EngineeringAcquisitionPlanRef,
) -> AcquisitionPlanRecord:
    target_materials = [
        cast(JsonDict, item)
        for item in _json_list(row.target_materials_json)
        if isinstance(item, dict)
    ]
    return AcquisitionPlanRecord(
        acquisition_plan_id=row.acquisition_plan_id,
        title=row.title,
        linked_goal_ids=_json_string_list(row.linked_goal_ids_json),
        linked_build_plan_ids=_json_string_list(row.linked_build_plan_ids_json),
        target_materials=target_materials,
        state=row.state,
        navigation_handoff_ids=_json_string_list(row.navigation_handoff_ids_json),
        operations_task_id=row.operations_task_id,
        selected_navigation_candidate_summary=_json_object(
            row.selected_navigation_candidate_summary_json
        ),
        notes=row.notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _material_gap_record(row: EngineeringMaterialGapOverrideRef) -> MaterialGapRecord:
    required = row.commander_override_required
    current = row.commander_override_current
    missing: int | None = None
    if required is not None and current is not None:
        missing = max(required - current, 0)
        gap_state = "gap_known" if missing > 0 else "complete"
    elif required is None:
        gap_state = "gap_unknown_requirement"
    else:
        gap_state = "gap_unknown_inventory"
    return MaterialGapRecord(
        gap_view_id=row.gap_view_id,
        material_id=row.material_id,
        material_display_name=row.material_display_name,
        goal_id=row.goal_id,
        build_plan_id=row.build_plan_id,
        required_count=required,
        current_count=current,
        missing_count=missing,
        gap_state=gap_state,
        requirement_state="manual" if required is not None else "unknown",
        inventory_state="manual" if current is not None else "not_loaded",
        source_chain=_source_chain_manual("material_gap"),
        caveats=[
            "Commander-entered counts are planning inputs, not source-backed "
            "inventory.",
            "Missing inventory is not treated as zero.",
        ],
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _readiness_caveats(requirements_known: str) -> list[str]:
    if requirements_known == "manual":
        return [
            "Commander-entered readiness note.",
            "Manual entries are not source-backed mechanics.",
        ]
    return [
        "Unsupported mechanics are not shown as verified.",
        "No verified source is loaded for requirements.",
    ]


async def create_goal(
    session_factory: async_sessionmaker[AsyncSession],
    payload: EngineeringGoalCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> EngineeringGoalRecord:
    now = _utc_now()
    row = EngineeringGoalRef(
        goal_id=_new_id(),
        commander_id=_clean_text(
            payload.commander_id,
            field_name="commander_id",
            max_length=64,
        ),
        title=_required_text(
            payload.title, field_name="title", max_length=MAX_TITLE_LENGTH
        ),
        description=_clean_text(
            payload.description,
            field_name="description",
            max_length=MAX_NOTE_LENGTH,
        ),
        target_kind=_validate_choice(
            payload.target_kind, GOAL_TARGET_KINDS, "target_kind"
        ),
        target_reference_json=_json_dump(payload.target_reference),
        state=_validate_choice(payload.state, GOAL_STATES, "state"),
        priority=_validate_choice(payload.priority, PRIORITIES, "priority"),
        notes=_clean_text(
            payload.notes,
            field_name="notes",
            max_length=MAX_NOTE_LENGTH,
        ),
        linked_build_plan_id=_clean_text(
            payload.linked_build_plan_id,
            field_name="linked_build_plan_id",
            max_length=36,
        ),
        linked_material_gap_view_id=None,
        linked_acquisition_handoff_ids_json="[]",
        linked_operations_task_id=None,
        last_activity_log_event_id=None,
        created_at=now,
        updated_at=now,
    )
    event_id = _append_activity(
        activity_log,
        event_type=ENGINEERING_GOAL_CREATED,
        summary="Engineering goal created",
        payload={
            "goal_id": row.goal_id,
            "title_length": len(row.title),
            "target_kind": row.target_kind,
            "state": row.state,
        },
        linked_entity_refs={"goal_id": row.goal_id},
    )
    row.last_activity_log_event_id = event_id
    async with session_factory() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _goal_record(row)


async def list_goals(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[EngineeringGoalRecord]:
    async with session_factory() as db:
        result = await db.execute(
            select(EngineeringGoalRef)
            .order_by(EngineeringGoalRef.updated_at.desc())
            .limit(_validate_limit(limit))
        )
        rows = cast(list[EngineeringGoalRef], result.scalars().all())
    return [_goal_record(row) for row in rows]


async def get_goal(
    session_factory: async_sessionmaker[AsyncSession],
    goal_id: str,
) -> EngineeringGoalRecord | None:
    async with session_factory() as db:
        row = await db.get(EngineeringGoalRef, goal_id)
    return _goal_record(row) if row is not None else None


async def update_goal(
    session_factory: async_sessionmaker[AsyncSession],
    goal_id: str,
    changes: EngineeringGoalUpdate,
    *,
    activity_log: ActivityLog | None = None,
) -> EngineeringGoalRecord | None:
    async with session_factory() as db:
        row = await db.get(EngineeringGoalRef, goal_id)
        if row is None:
            return None
        previous_state = row.state
        if "title" in changes:
            row.title = _required_text(
                changes["title"], field_name="title", max_length=MAX_TITLE_LENGTH
            )
        if "description" in changes:
            row.description = _clean_text(
                changes["description"],
                field_name="description",
                max_length=MAX_NOTE_LENGTH,
            )
        if "target_kind" in changes:
            row.target_kind = _validate_choice(
                changes["target_kind"], GOAL_TARGET_KINDS, "target_kind"
            )
        if "target_reference" in changes:
            row.target_reference_json = _json_dump(changes["target_reference"])
        if "state" in changes:
            row.state = _validate_choice(changes["state"], GOAL_STATES, "state")
        if "priority" in changes:
            row.priority = _validate_choice(changes["priority"], PRIORITIES, "priority")
        if "notes" in changes:
            row.notes = _clean_text(
                changes["notes"], field_name="notes", max_length=MAX_NOTE_LENGTH
            )
        if "linked_build_plan_id" in changes:
            row.linked_build_plan_id = _clean_text(
                changes["linked_build_plan_id"],
                field_name="linked_build_plan_id",
                max_length=36,
            )
        row.updated_at = _utc_now()
        event_type = (
            ENGINEERING_GOAL_STATE_CHANGED
            if row.state != previous_state
            else ENGINEERING_GOAL_UPDATED
        )
        event_id = _append_activity(
            activity_log,
            event_type=event_type,
            summary="Engineering goal updated",
            payload={
                "goal_id": row.goal_id,
                "changed_fields": sorted(changes.keys()),
                "state": row.state,
            },
            linked_entity_refs={"goal_id": row.goal_id},
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()
        await db.refresh(row)
    return _goal_record(row)


async def delete_goal(
    session_factory: async_sessionmaker[AsyncSession],
    goal_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> bool:
    async with session_factory() as db:
        row = await db.get(EngineeringGoalRef, goal_id)
        if row is None:
            return False
        await db.delete(row)
        await db.commit()
    _append_activity(
        activity_log,
        event_type=ENGINEERING_GOAL_ARCHIVED,
        summary="Engineering goal deleted",
        payload={"goal_id": goal_id, "redacted": True},
        linked_entity_refs={"goal_id": goal_id},
    )
    return True


async def create_build_plan(
    session_factory: async_sessionmaker[AsyncSession],
    payload: BuildPlanCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> BuildPlanRecord:
    now = _utc_now()
    row = EngineeringBuildPlanRef(
        build_plan_id=_new_id(),
        title=_required_text(
            payload.title, field_name="title", max_length=MAX_TITLE_LENGTH
        ),
        description=_clean_text(
            payload.description,
            field_name="description",
            max_length=MAX_NOTE_LENGTH,
        ),
        target_ship_json=_json_dump(payload.target_ship),
        target_loadout_summary_json=_json_dump(payload.target_loadout_summary),
        source=_validate_choice(payload.source, BUILD_SOURCES, "source"),
        format_verification_state=_validate_choice(
            payload.format_verification_state,
            FORMAT_STATES,
            "format_verification_state",
        ),
        state=_validate_choice(payload.state, BUILD_STATES, "state"),
        linked_goal_ids_json=_json_dump(payload.linked_goal_ids),
        linked_material_gap_view_id=None,
        source_url=_clean_url(payload.source_url),
        notes=_clean_text(
            payload.notes,
            field_name="notes",
            max_length=MAX_NOTE_LENGTH,
        ),
        last_activity_log_event_id=None,
        created_at=now,
        updated_at=now,
    )
    event_id = _append_activity(
        activity_log,
        event_type=ENGINEERING_BUILDPLAN_CREATED,
        summary="Engineering build plan created",
        payload={
            "build_plan_id": row.build_plan_id,
            "title_length": len(row.title),
            "source": row.source,
            "format_verification_state": row.format_verification_state,
        },
        linked_entity_refs={"build_plan_id": row.build_plan_id},
    )
    row.last_activity_log_event_id = event_id
    async with session_factory() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _build_plan_record(row)


async def list_build_plans(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[BuildPlanRecord]:
    async with session_factory() as db:
        result = await db.execute(
            select(EngineeringBuildPlanRef)
            .order_by(EngineeringBuildPlanRef.updated_at.desc())
            .limit(_validate_limit(limit))
        )
        rows = cast(list[EngineeringBuildPlanRef], result.scalars().all())
    return [_build_plan_record(row) for row in rows]


async def update_build_plan(
    session_factory: async_sessionmaker[AsyncSession],
    build_plan_id: str,
    changes: BuildPlanUpdate,
    *,
    activity_log: ActivityLog | None = None,
) -> BuildPlanRecord | None:
    async with session_factory() as db:
        row = await db.get(EngineeringBuildPlanRef, build_plan_id)
        if row is None:
            return None
        if "title" in changes:
            row.title = _required_text(
                changes["title"], field_name="title", max_length=MAX_TITLE_LENGTH
            )
        if "description" in changes:
            row.description = _clean_text(
                changes["description"],
                field_name="description",
                max_length=MAX_NOTE_LENGTH,
            )
        if "target_ship" in changes:
            row.target_ship_json = _json_dump(changes["target_ship"])
        if "target_loadout_summary" in changes:
            row.target_loadout_summary_json = _json_dump(
                changes["target_loadout_summary"]
            )
        if "source" in changes:
            row.source = _validate_choice(changes["source"], BUILD_SOURCES, "source")
        if "format_verification_state" in changes:
            row.format_verification_state = _validate_choice(
                changes["format_verification_state"],
                FORMAT_STATES,
                "format_verification_state",
            )
        if "state" in changes:
            row.state = _validate_choice(changes["state"], BUILD_STATES, "state")
        if "linked_goal_ids" in changes:
            row.linked_goal_ids_json = _json_dump(changes["linked_goal_ids"])
        if "source_url" in changes:
            row.source_url = _clean_url(changes["source_url"])
        if "notes" in changes:
            row.notes = _clean_text(
                changes["notes"], field_name="notes", max_length=MAX_NOTE_LENGTH
            )
        row.updated_at = _utc_now()
        event_id = _append_activity(
            activity_log,
            event_type=ENGINEERING_BUILDPLAN_UPDATED,
            summary="Engineering build plan updated",
            payload={
                "build_plan_id": row.build_plan_id,
                "changed_fields": sorted(changes.keys()),
                "source": row.source,
            },
            linked_entity_refs={"build_plan_id": row.build_plan_id},
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()
        await db.refresh(row)
    return _build_plan_record(row)


async def delete_build_plan(
    session_factory: async_sessionmaker[AsyncSession],
    build_plan_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> bool:
    async with session_factory() as db:
        row = await db.get(EngineeringBuildPlanRef, build_plan_id)
        if row is None:
            return False
        await db.delete(row)
        await db.commit()
    _append_activity(
        activity_log,
        event_type=ENGINEERING_BUILDPLAN_ARCHIVED,
        summary="Engineering build plan deleted",
        payload={"build_plan_id": build_plan_id, "redacted": True},
        linked_entity_refs={"build_plan_id": build_plan_id},
    )
    return True


async def upsert_material_override(
    session_factory: async_sessionmaker[AsyncSession],
    payload: MaterialGapOverrideUpsert,
    *,
    gap_view_id: str | None = None,
    activity_log: ActivityLog | None = None,
) -> MaterialGapRecord:
    now = _utc_now()
    material_id = _required_text(
        payload.material_id, field_name="material_id", max_length=96
    )
    async with session_factory() as db:
        row = await db.get(EngineeringMaterialGapOverrideRef, gap_view_id or "")
        if row is None:
            row = EngineeringMaterialGapOverrideRef(
                gap_view_id=gap_view_id or _new_id(),
                goal_id=_clean_text(
                    payload.goal_id,
                    field_name="goal_id",
                    max_length=36,
                ),
                build_plan_id=_clean_text(
                    payload.build_plan_id,
                    field_name="build_plan_id",
                    max_length=36,
                ),
                material_id=material_id,
                material_display_name=_required_text(
                    payload.material_display_name,
                    field_name="material_display_name",
                    max_length=MAX_LABEL_LENGTH,
                ),
                commander_override_required=_validate_non_negative(
                    payload.commander_override_required,
                    "commander_override_required",
                ),
                commander_override_current=_validate_non_negative(
                    payload.commander_override_current,
                    "commander_override_current",
                ),
                required_note=_clean_text(
                    payload.required_note,
                    field_name="required_note",
                    max_length=MAX_NOTE_LENGTH,
                ),
                current_note=_clean_text(
                    payload.current_note,
                    field_name="current_note",
                    max_length=MAX_NOTE_LENGTH,
                ),
                created_at=now,
                updated_at=now,
            )
            db.add(row)
        else:
            row.goal_id = _clean_text(
                payload.goal_id,
                field_name="goal_id",
                max_length=36,
            )
            row.build_plan_id = _clean_text(
                payload.build_plan_id,
                field_name="build_plan_id",
                max_length=36,
            )
            row.material_id = material_id
            row.material_display_name = _required_text(
                payload.material_display_name,
                field_name="material_display_name",
                max_length=MAX_LABEL_LENGTH,
            )
            row.commander_override_required = _validate_non_negative(
                payload.commander_override_required,
                "commander_override_required",
            )
            row.commander_override_current = _validate_non_negative(
                payload.commander_override_current,
                "commander_override_current",
            )
            row.required_note = _clean_text(
                payload.required_note,
                field_name="required_note",
                max_length=MAX_NOTE_LENGTH,
            )
            row.current_note = _clean_text(
                payload.current_note,
                field_name="current_note",
                max_length=MAX_NOTE_LENGTH,
            )
            row.updated_at = now
        await db.commit()
        await db.refresh(row)
    _append_activity(
        activity_log,
        event_type=ENGINEERING_MATERIAL_GAP_OVERRIDE_SET,
        summary="Engineering material planning entry saved",
        payload={
            "gap_view_id": row.gap_view_id,
            "material_id": row.material_id,
            "has_required_count": row.commander_override_required is not None,
            "has_current_count": row.commander_override_current is not None,
            "missing_count": (
                max(
                    row.commander_override_required - row.commander_override_current,
                    0,
                )
                if row.commander_override_required is not None
                and row.commander_override_current is not None
                else None
            ),
        },
        linked_entity_refs={"gap_view_id": row.gap_view_id},
    )
    return _material_gap_record(row)


async def list_material_gaps(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[MaterialGapRecord]:
    async with session_factory() as db:
        result = await db.execute(
            select(EngineeringMaterialGapOverrideRef)
            .order_by(EngineeringMaterialGapOverrideRef.updated_at.desc())
            .limit(_validate_limit(limit))
        )
        rows = cast(list[EngineeringMaterialGapOverrideRef], result.scalars().all())
    return [_material_gap_record(row) for row in rows]


async def delete_material_override(
    session_factory: async_sessionmaker[AsyncSession],
    gap_view_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> bool:
    async with session_factory() as db:
        row = await db.get(EngineeringMaterialGapOverrideRef, gap_view_id)
        if row is None:
            return False
        await db.delete(row)
        await db.commit()
    _append_activity(
        activity_log,
        event_type=ENGINEERING_MATERIAL_GAP_OVERRIDE_CLEARED,
        summary="Engineering material planning entry removed",
        payload={"gap_view_id": gap_view_id, "redacted": True},
        linked_entity_refs={"gap_view_id": gap_view_id},
    )
    return True


async def create_acquisition_plan(
    session_factory: async_sessionmaker[AsyncSession],
    payload: AcquisitionPlanCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> AcquisitionPlanRecord:
    now = _utc_now()
    row = EngineeringAcquisitionPlanRef(
        acquisition_plan_id=_new_id(),
        title=_required_text(
            payload.title, field_name="title", max_length=MAX_TITLE_LENGTH
        ),
        linked_goal_ids_json=_json_dump(payload.linked_goal_ids),
        linked_build_plan_ids_json=_json_dump(payload.linked_build_plan_ids),
        target_materials_json=_json_dump(payload.target_materials),
        state=_validate_choice(payload.state, ACQUISITION_STATES, "state"),
        navigation_handoff_ids_json="[]",
        operations_task_id=None,
        selected_navigation_candidate_summary_json="{}",
        notes=_clean_text(
            payload.notes,
            field_name="notes",
            max_length=MAX_NOTE_LENGTH,
        ),
        last_activity_log_event_id=None,
        created_at=now,
        updated_at=now,
    )
    event_id = _append_activity(
        activity_log,
        event_type=ENGINEERING_ACQUISITION_PLAN_CREATED,
        summary="Engineering acquisition plan created",
        payload={
            "acquisition_plan_id": row.acquisition_plan_id,
            "target_material_count": len(payload.target_materials),
        },
        linked_entity_refs={"acquisition_plan_id": row.acquisition_plan_id},
    )
    row.last_activity_log_event_id = event_id
    async with session_factory() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _acquisition_plan_record(row)


async def list_acquisition_plans(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    limit: int = DEFAULT_LIMIT,
) -> list[AcquisitionPlanRecord]:
    async with session_factory() as db:
        result = await db.execute(
            select(EngineeringAcquisitionPlanRef)
            .order_by(EngineeringAcquisitionPlanRef.updated_at.desc())
            .limit(_validate_limit(limit))
        )
        rows = cast(list[EngineeringAcquisitionPlanRef], result.scalars().all())
    return [_acquisition_plan_record(row) for row in rows]


async def update_acquisition_plan(
    session_factory: async_sessionmaker[AsyncSession],
    acquisition_plan_id: str,
    changes: AcquisitionPlanUpdate,
    *,
    activity_log: ActivityLog | None = None,
) -> AcquisitionPlanRecord | None:
    async with session_factory() as db:
        row = await db.get(EngineeringAcquisitionPlanRef, acquisition_plan_id)
        if row is None:
            return None
        previous_state = row.state
        if "title" in changes:
            row.title = _required_text(
                changes["title"], field_name="title", max_length=MAX_TITLE_LENGTH
            )
        if "linked_goal_ids" in changes:
            row.linked_goal_ids_json = _json_dump(changes["linked_goal_ids"])
        if "linked_build_plan_ids" in changes:
            row.linked_build_plan_ids_json = _json_dump(
                changes["linked_build_plan_ids"]
            )
        if "target_materials" in changes:
            row.target_materials_json = _json_dump(changes["target_materials"])
        if "state" in changes:
            row.state = _validate_choice(changes["state"], ACQUISITION_STATES, "state")
        if "notes" in changes:
            row.notes = _clean_text(
                changes["notes"], field_name="notes", max_length=MAX_NOTE_LENGTH
            )
        row.updated_at = _utc_now()
        event_type = (
            ENGINEERING_ACQUISITION_PLAN_STATE_CHANGED
            if row.state != previous_state
            else ENGINEERING_ACQUISITION_PLAN_UPDATED
        )
        event_id = _append_activity(
            activity_log,
            event_type=event_type,
            summary="Engineering acquisition plan updated",
            payload={
                "acquisition_plan_id": row.acquisition_plan_id,
                "changed_fields": sorted(changes.keys()),
                "state": row.state,
            },
            linked_entity_refs={"acquisition_plan_id": row.acquisition_plan_id},
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()
        await db.refresh(row)
    return _acquisition_plan_record(row)


async def delete_acquisition_plan(
    session_factory: async_sessionmaker[AsyncSession],
    acquisition_plan_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> bool:
    async with session_factory() as db:
        row = await db.get(EngineeringAcquisitionPlanRef, acquisition_plan_id)
        if row is None:
            return False
        await db.delete(row)
        await db.commit()
    _append_activity(
        activity_log,
        event_type=ENGINEERING_ACQUISITION_PLAN_ARCHIVED,
        summary="Engineering acquisition plan deleted",
        payload={"acquisition_plan_id": acquisition_plan_id, "redacted": True},
        linked_entity_refs={"acquisition_plan_id": acquisition_plan_id},
    )
    return True


def _route_intent(
    *,
    plan: EngineeringAcquisitionPlanRef,
    target_route: Literal["/navigation", "/operations"],
    target_section: str,
) -> JsonDict:
    return {
        "originRoute": "/engineering",
        "originPackage": "Phase 8 Engineering",
        "originSectionId": "engineering-acquisition",
        "targetRoute": target_route,
        "targetSectionId": target_section,
        "targetEntityId": plan.acquisition_plan_id,
        "targetLabel": plan.title,
        "reason": "Engineering acquisition handoff intent.",
        "returnLabel": "Return to Engineering",
        "returnTarget": {
            "route": "/engineering",
            "package": "Phase 8 Engineering",
            "sectionId": "engineering-acquisition",
            "entityId": plan.acquisition_plan_id,
        },
        "timestamp": _timestamp(),
    }


async def handoff_to_navigation(
    session_factory: async_sessionmaker[AsyncSession],
    acquisition_plan_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> HandoffResult | None:
    async with session_factory() as db:
        row = await db.get(EngineeringAcquisitionPlanRef, acquisition_plan_id)
        if row is None:
            return None
        handoff_id = _new_id()
        handoffs = _json_string_list(row.navigation_handoff_ids_json)
        handoffs.append(handoff_id)
        row.navigation_handoff_ids_json = _json_dump(handoffs)
        row.state = "handoff_sent_to_navigation"
        row.updated_at = _utc_now()
        intent = _route_intent(
            plan=row,
            target_route="/navigation",
            target_section="acquisition",
        )
        event_id = _append_activity(
            activity_log,
            event_type=ENGINEERING_ACQUISITION_HANDOFF_TO_NAVIGATION,
            summary="Engineering acquisition handoff sent to Navigation",
            payload={
                "acquisition_plan_id": row.acquisition_plan_id,
                "handoff_id": handoff_id,
                "target_route": "/navigation",
                "target_section_id": "acquisition",
                "route_intent": "/navigation",
            },
            linked_entity_refs={"acquisition_plan_id": row.acquisition_plan_id},
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()
        await db.refresh(row)
    return HandoffResult(
        plan=_acquisition_plan_record(row),
        route_transfer_intent=intent,
    )


async def handoff_to_operations(
    session_factory: async_sessionmaker[AsyncSession],
    acquisition_plan_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> HandoffResult | None:
    async with session_factory() as db:
        row = await db.get(EngineeringAcquisitionPlanRef, acquisition_plan_id)
        if row is None:
            return None
        task_id = row.operations_task_id or _new_id()
        row.operations_task_id = task_id
        row.state = "handoff_sent_to_operations"
        row.updated_at = _utc_now()
        intent = _route_intent(
            plan=row,
            target_route="/operations",
            target_section="active_engineering_task",
        )
        event_id = _append_activity(
            activity_log,
            event_type=ENGINEERING_TASK_HANDOFF_TO_OPERATIONS,
            summary="Engineering task handoff sent to Operations",
            payload={
                "acquisition_plan_id": row.acquisition_plan_id,
                "operations_task_id": task_id,
                "target_route": "/operations",
                "target_section_id": "active_engineering_task",
                "route_intent": "/operations",
            },
            linked_entity_refs={"acquisition_plan_id": row.acquisition_plan_id},
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()
        await db.refresh(row)
    return HandoffResult(
        plan=_acquisition_plan_record(row),
        route_transfer_intent=intent,
    )


def _readiness_record_from_blueprint(
    row: EngineeringBlueprintProgressRef,
) -> ReadinessRecord:
    return ReadinessRecord(
        readiness_id=row.blueprint_progress_id,
        kind="blueprint_progress",
        label=row.blueprint_label,
        state=row.state,
        requirements_known="unsupported",
        requirements_text=None,
        notes=row.notes,
        target_grade=row.target_grade,
        target_engineer_label=row.target_engineer_label,
        target_module_label=row.target_module_label,
        created_at=row.created_at,
        updated_at=row.updated_at,
        caveats=_readiness_caveats("unsupported"),
        source_chain=_source_chain_manual("blueprint_progress"),
    )


def _readiness_record_from_engineer(
    row: EngineeringEngineerUnlockStateRef,
) -> ReadinessRecord:
    return ReadinessRecord(
        readiness_id=row.engineer_unlock_state_id,
        kind="engineer_unlock_state",
        label=row.engineer_label,
        state=row.state,
        requirements_known=row.requirements_known,
        requirements_text=row.requirements_text,
        notes=row.commander_notes,
        target_grade=None,
        target_engineer_label=row.engineer_label,
        target_module_label=None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        caveats=_readiness_caveats(row.requirements_known),
        source_chain=_source_chain_manual("engineer_unlock_state"),
    )


def _readiness_record_from_guardian(
    row: EngineeringGuardianTechProgressRef,
) -> ReadinessRecord:
    return ReadinessRecord(
        readiness_id=row.guardian_tech_progress_id,
        kind="guardian_tech_progress",
        label=row.guardian_tech_label,
        state=row.state,
        requirements_known=row.requirements_known,
        requirements_text=row.requirements_text,
        notes=row.notes,
        target_grade=None,
        target_engineer_label=None,
        target_module_label=None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        caveats=_readiness_caveats(row.requirements_known),
        source_chain=_source_chain_manual("guardian_tech_progress"),
    )


def _readiness_record_from_suit(
    row: EngineeringSuitEngineeringStateRef,
) -> ReadinessRecord:
    return ReadinessRecord(
        readiness_id=row.suit_engineering_state_id,
        kind="suit_engineering_state",
        label=row.suit_engineering_label,
        state=row.state,
        requirements_known=row.requirements_known,
        requirements_text=row.requirements_text,
        notes=row.notes,
        target_grade=None,
        target_engineer_label=None,
        target_module_label=row.suit_engineering_label,
        created_at=row.created_at,
        updated_at=row.updated_at,
        caveats=_readiness_caveats(row.requirements_known),
        source_chain=_source_chain_manual("suit_engineering_state"),
    )


async def create_readiness_state(
    session_factory: async_sessionmaker[AsyncSession],
    payload: ReadinessCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> ReadinessRecord:
    kind = _validate_choice(payload.kind, READINESS_KINDS, "kind")
    state = _validate_choice(payload.state, READINESS_STATES, "state")
    requirements_known = _validate_choice(
        payload.requirements_known,
        REQUIREMENTS_STATES,
        "requirements_known",
    )
    label = _required_text(
        payload.label, field_name="label", max_length=MAX_LABEL_LENGTH
    )
    notes = _clean_text(payload.notes, field_name="notes", max_length=MAX_NOTE_LENGTH)
    now = _utc_now()
    event_type = ENGINEERING_BLUEPRINT_PROGRESS_CREATED
    async with session_factory() as db:
        if kind == "blueprint_progress":
            blueprint_row = EngineeringBlueprintProgressRef(
                blueprint_progress_id=_new_id(),
                blueprint_label=label,
                target_engineer_label=_clean_text(
                    payload.target_engineer_label,
                    field_name="target_engineer_label",
                    max_length=MAX_LABEL_LENGTH,
                ),
                target_module_label=_clean_text(
                    payload.target_module_label,
                    field_name="target_module_label",
                    max_length=MAX_LABEL_LENGTH,
                ),
                target_grade=_required_text(
                    payload.target_grade,
                    field_name="target_grade",
                    max_length=16,
                ),
                state=state,
                linked_material_gap_view_ids_json="[]",
                linked_engineer_unlock_state_id=None,
                linked_engineercraft_event_ids_json="[]",
                notes=notes,
                created_at=now,
                updated_at=now,
            )
            db.add(blueprint_row)
            await db.commit()
            await db.refresh(blueprint_row)
            record = _readiness_record_from_blueprint(blueprint_row)
        elif kind == "engineer_unlock_state":
            engineer_row = EngineeringEngineerUnlockStateRef(
                engineer_unlock_state_id=_new_id(),
                engineer_label=label,
                state=state,
                last_engineerprogress_event_at=None,
                commander_notes=notes,
                requirements_known=requirements_known,
                requirements_text=_clean_text(
                    payload.requirements_text,
                    field_name="requirements_text",
                    max_length=MAX_NOTE_LENGTH,
                ),
                created_at=now,
                updated_at=now,
            )
            event_type = ENGINEERING_ENGINEER_UNLOCK_STATE_CREATED
            db.add(engineer_row)
            await db.commit()
            await db.refresh(engineer_row)
            record = _readiness_record_from_engineer(engineer_row)
        elif kind == "guardian_tech_progress":
            guardian_row = EngineeringGuardianTechProgressRef(
                guardian_tech_progress_id=_new_id(),
                guardian_tech_label=label,
                state=state,
                linked_techbroker_event_ids_json="[]",
                requirements_known=requirements_known,
                requirements_text=_clean_text(
                    payload.requirements_text,
                    field_name="requirements_text",
                    max_length=MAX_NOTE_LENGTH,
                ),
                notes=notes,
                created_at=now,
                updated_at=now,
            )
            event_type = ENGINEERING_GUARDIAN_TECH_PROGRESS_CREATED
            db.add(guardian_row)
            await db.commit()
            await db.refresh(guardian_row)
            record = _readiness_record_from_guardian(guardian_row)
        else:
            suit_row = EngineeringSuitEngineeringStateRef(
                suit_engineering_state_id=_new_id(),
                suit_engineering_label=label,
                state=state,
                requirements_known=requirements_known,
                requirements_text=_clean_text(
                    payload.requirements_text,
                    field_name="requirements_text",
                    max_length=MAX_NOTE_LENGTH,
                ),
                notes=notes,
                created_at=now,
                updated_at=now,
            )
            event_type = ENGINEERING_SUIT_ENGINEERING_STATE_CREATED
            db.add(suit_row)
            await db.commit()
            await db.refresh(suit_row)
            record = _readiness_record_from_suit(suit_row)
    _append_activity(
        activity_log,
        event_type=event_type,
        summary="Engineering readiness state created",
        payload={
            "readiness_id": record.readiness_id,
            "kind": record.kind,
            "state": record.state,
            "requirements_known": record.requirements_known,
        },
        linked_entity_refs={"readiness_id": record.readiness_id},
    )
    return record


async def list_readiness_states(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    kind: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[ReadinessRecord]:
    if kind is not None:
        _validate_choice(kind, READINESS_KINDS, "kind")
    limit = _validate_limit(limit)
    records: list[ReadinessRecord] = []
    async with session_factory() as db:
        if kind in (None, "blueprint_progress"):
            result = await db.execute(
                select(EngineeringBlueprintProgressRef)
                .order_by(EngineeringBlueprintProgressRef.updated_at.desc())
                .limit(limit)
            )
            blueprint_rows = cast(
                list[EngineeringBlueprintProgressRef],
                result.scalars().all(),
            )
            records.extend(
                _readiness_record_from_blueprint(row) for row in blueprint_rows
            )
        if kind in (None, "engineer_unlock_state"):
            result = await db.execute(
                select(EngineeringEngineerUnlockStateRef)
                .order_by(EngineeringEngineerUnlockStateRef.updated_at.desc())
                .limit(limit)
            )
            engineer_rows = cast(
                list[EngineeringEngineerUnlockStateRef],
                result.scalars().all(),
            )
            records.extend(
                _readiness_record_from_engineer(row) for row in engineer_rows
            )
        if kind in (None, "guardian_tech_progress"):
            result = await db.execute(
                select(EngineeringGuardianTechProgressRef)
                .order_by(EngineeringGuardianTechProgressRef.updated_at.desc())
                .limit(limit)
            )
            guardian_rows = cast(
                list[EngineeringGuardianTechProgressRef],
                result.scalars().all(),
            )
            records.extend(
                _readiness_record_from_guardian(row) for row in guardian_rows
            )
        if kind in (None, "suit_engineering_state"):
            result = await db.execute(
                select(EngineeringSuitEngineeringStateRef)
                .order_by(EngineeringSuitEngineeringStateRef.updated_at.desc())
                .limit(limit)
            )
            suit_rows = cast(
                list[EngineeringSuitEngineeringStateRef],
                result.scalars().all(),
            )
            records.extend(_readiness_record_from_suit(row) for row in suit_rows)
    return sorted(records, key=lambda item: item.updated_at, reverse=True)[:limit]


async def list_import_source_states(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[ImportSourceStateRecord]:
    async with session_factory() as db:
        result = await db.execute(select(EngineeringImportSourceStateRef))
        rows = cast(list[EngineeringImportSourceStateRef], result.scalars().all())
    by_provider = {row.provider_label: row for row in rows}
    return [
        _import_source_record(by_provider.get(provider), provider)
        for provider in sorted(IMPORT_PROVIDERS)
    ]


def _import_source_record(
    row: EngineeringImportSourceStateRef | None,
    provider_label: str,
) -> ImportSourceStateRecord:
    caveat = (
        f"{provider_label} format verification is required before import or export."
    )
    if row is None:
        return ImportSourceStateRecord(
            import_source_state_id=provider_label,
            provider_label=provider_label,
            format_version_label=None,
            format_verification_state="format_unverified",
            format_verification_evidence_summary="No accepted format evidence in repo.",
            consent_state="disabled",
            notes=None,
            caveats=[caveat, "No outbound behavior is available."],
            import_available=False,
            export_available=False,
            outbound_available=False,
            created_at=None,
            updated_at=None,
        )
    return ImportSourceStateRecord(
        import_source_state_id=row.import_source_state_id,
        provider_label=row.provider_label,
        format_version_label=row.format_version_label,
        format_verification_state=row.format_verification_state,
        format_verification_evidence_summary=(row.format_verification_evidence_summary),
        consent_state=row.consent_state,
        notes=row.notes,
        caveats=[caveat, "No outbound behavior is available."],
        import_available=False,
        export_available=False,
        outbound_available=False,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def ensure_import_source_state(
    session_factory: async_sessionmaker[AsyncSession],
    provider_label: str,
    *,
    activity_log: ActivityLog | None = None,
) -> ImportSourceStateRecord:
    provider = _validate_choice(provider_label, IMPORT_PROVIDERS, "provider_label")
    now = _utc_now()
    async with session_factory() as db:
        result = await db.execute(
            select(EngineeringImportSourceStateRef).where(
                EngineeringImportSourceStateRef.provider_label == provider
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = EngineeringImportSourceStateRef(
                import_source_state_id=_new_id(),
                provider_label=provider,
                format_version_label=None,
                format_verification_state="format_unverified",
                format_verification_evidence_summary=(
                    "No accepted format verification evidence in repo."
                ),
                consent_state="disabled",
                last_consent_event_id=None,
                last_import_event_id=None,
                last_export_event_id=None,
                notes="Import/export execution disabled pending verification.",
                created_at=now,
                updated_at=now,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            _append_activity(
                activity_log,
                event_type=ENGINEERING_IMPORT_SOURCE_STATE_CREATED,
                summary="Engineering import source disabled state recorded",
                payload={
                    "provider_label": provider,
                    "format_verification_state": row.format_verification_state,
                    "consent_state": row.consent_state,
                },
                source_chain=_source_chain_disabled(provider),
                linked_entity_refs={
                    "import_source_state_id": row.import_source_state_id
                },
                source="external_disabled",
            )
    return _import_source_record(row, provider)


async def record_disabled_import_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    provider_label: str,
    *,
    activity_log: ActivityLog | None = None,
) -> ImportSourceStateRecord:
    record = await ensure_import_source_state(
        session_factory,
        provider_label,
        activity_log=activity_log,
    )
    _append_activity(
        activity_log,
        event_type=ENGINEERING_SOURCE_ATTEMPT_DISABLED,
        summary="Engineering import attempt disabled",
        payload={
            "provider_label": record.provider_label,
            "format_verification_state": record.format_verification_state,
            "blocked": True,
            "outbound_attempted": False,
            "outbound_call_executed": False,
            "scrape_executed": False,
            "oauth_started": False,
        },
        source_chain=_source_chain_disabled(record.provider_label),
        linked_entity_refs={
            "import_source_state_id": record.import_source_state_id,
        },
        source="external_disabled",
    )
    return record


async def record_disabled_export_attempt(
    session_factory: async_sessionmaker[AsyncSession],
    provider_label: str,
    *,
    activity_log: ActivityLog | None = None,
) -> ImportSourceStateRecord:
    record = await ensure_import_source_state(
        session_factory,
        provider_label,
        activity_log=activity_log,
    )
    _append_activity(
        activity_log,
        event_type=ENGINEERING_SOURCE_ATTEMPT_DISABLED,
        summary="Engineering export attempt disabled",
        payload={
            "provider_label": record.provider_label,
            "format_verification_state": record.format_verification_state,
            "blocked": True,
            "outbound_attempted": False,
            "outbound_call_executed": False,
            "scrape_executed": False,
            "oauth_started": False,
        },
        source_chain=_source_chain_disabled(record.provider_label),
        linked_entity_refs={
            "import_source_state_id": record.import_source_state_id,
        },
        source="external_disabled",
    )
    return record


async def overview(
    session_factory: async_sessionmaker[AsyncSession],
) -> JsonDict:
    goals = await list_goals(session_factory)
    builds = await list_build_plans(session_factory)
    gaps = await list_material_gaps(session_factory)
    acquisition = await list_acquisition_plans(session_factory)
    readiness = await list_readiness_states(session_factory)
    imports = await list_import_source_states(session_factory)
    active_goals = [
        goal for goal in goals if goal.state not in {"complete", "archived"}
    ]
    known_gap_count = sum(
        1 for gap in gaps if gap.gap_state in {"gap_known", "complete"}
    )
    return {
        "route": "engineering",
        "implementation_posture": "local_only_candidate",
        "nullprovider_safe": True,
        "counts": {
            "goals": len(goals),
            "active_goals": len(active_goals),
            "build_plans": len(builds),
            "material_gap_rows": len(gaps),
            "known_material_gap_rows": known_gap_count,
            "acquisition_plans": len(acquisition),
            "readiness_states": len(readiness),
            "disabled_import_sources": len(imports),
        },
        "source_posture": {
            "capi_material_inventory": "source_gated_disabled",
            "edsy": "format_unverified_disabled",
            "coriolis": "format_unverified_disabled",
            "ardent": "disabled_not_used_for_phase8_material_inventory",
            "commander_entered": "manual_local_only",
            "local_material_inventory": (
                "not_loaded_no_zero_inference" if not gaps else "manual_planning_rows"
            ),
        },
        "caveats": list(SOURCE_CAVEATS),
        "handoff_targets": {
            "navigation": "acquisition",
            "operations": "active_engineering_task",
        },
    }


def material_gap_empty_snapshot() -> JsonDict:
    return {
        "surface_state": "not_loaded",
        "inventory_state": "not_loaded",
        "requirement_state": "unknown",
        "rows": [],
        "caveats": [
            "No commander-entered requirements are stored yet.",
            "Missing local material files are not treated as zero inventory.",
            "No CAPI material inventory is enabled.",
        ],
        "nullprovider_safe": True,
    }
