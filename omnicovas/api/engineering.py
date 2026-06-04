"""Phase 8 local-only Engineering planning API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.event_types import ENGINEERING_SOURCE_ATTEMPT_BLOCKED
from omnicovas.core.state_manager import StateManager
from omnicovas.features import engineering

router = APIRouter(prefix="/engineering", tags=["engineering"])

_session_factory: async_sessionmaker[AsyncSession] | None = None
_activity_log: ActivityLog | None = None
_state_manager: StateManager | None = None


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


def set_state_manager(state_manager: StateManager | None) -> None:
    """Inject canonical state for future local facts without creating a store."""
    global _state_manager  # noqa: PLW0603
    _state_manager = state_manager


def _ensure_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Engineering persistence not initialized",
        )
    return _session_factory


class GoalCreateRequest(BaseModel):
    """Commander-entered Engineering goal creation request."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    commander_id: str | None = Field(default=None, max_length=64)
    description: str | None = Field(default=None, max_length=4000)
    target_kind: str = Field(default="commander_defined_other", max_length=48)
    target_reference: dict[str, Any] = Field(default_factory=dict)
    state: str = Field(default="draft", max_length=24)
    priority: str = Field(default="normal", max_length=16)
    notes: str | None = Field(default=None, max_length=4000)
    linked_build_plan_id: str | None = Field(default=None, max_length=36)


class GoalPatchRequest(BaseModel):
    """Allowed Engineering goal patch fields."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    target_kind: str | None = Field(default=None, max_length=48)
    target_reference: dict[str, Any] | None = None
    state: str | None = Field(default=None, max_length=24)
    priority: str | None = Field(default=None, max_length=16)
    notes: str | None = Field(default=None, max_length=4000)
    linked_build_plan_id: str | None = Field(default=None, max_length=36)


class BuildPlanCreateRequest(BaseModel):
    """Commander-entered planned build creation request."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    target_ship: dict[str, Any] = Field(default_factory=dict)
    target_loadout_summary: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="commander_defined", max_length=48)
    format_verification_state: str = Field(default="not_applicable", max_length=32)
    state: str = Field(default="draft", max_length=24)
    linked_goal_ids: list[str] = Field(default_factory=list)
    source_url: str | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, max_length=4000)


class BuildPlanPatchRequest(BaseModel):
    """Allowed planned build patch fields."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    target_ship: dict[str, Any] | None = None
    target_loadout_summary: dict[str, Any] | None = None
    source: str | None = Field(default=None, max_length=48)
    format_verification_state: str | None = Field(default=None, max_length=32)
    state: str | None = Field(default=None, max_length=24)
    linked_goal_ids: list[str] | None = None
    source_url: str | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, max_length=4000)


class MaterialOverrideRequest(BaseModel):
    """Commander-entered material planning counts."""

    model_config = ConfigDict(extra="forbid")

    material_id: str = Field(min_length=1, max_length=96)
    material_display_name: str = Field(min_length=1, max_length=128)
    goal_id: str | None = Field(default=None, max_length=36)
    build_plan_id: str | None = Field(default=None, max_length=36)
    commander_override_required: int | None = Field(default=None, ge=0)
    commander_override_current: int | None = Field(default=None, ge=0)
    required_note: str | None = Field(default=None, max_length=4000)
    current_note: str | None = Field(default=None, max_length=4000)


class AcquisitionPlanCreateRequest(BaseModel):
    """Commander-entered acquisition plan creation request."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    linked_goal_ids: list[str] = Field(default_factory=list)
    linked_build_plan_ids: list[str] = Field(default_factory=list)
    target_materials: list[dict[str, Any]] = Field(default_factory=list)
    state: str = Field(default="draft", max_length=48)
    notes: str | None = Field(default=None, max_length=4000)


class AcquisitionPlanPatchRequest(BaseModel):
    """Allowed acquisition plan patch fields."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=128)
    linked_goal_ids: list[str] | None = None
    linked_build_plan_ids: list[str] | None = None
    target_materials: list[dict[str, Any]] | None = None
    state: str | None = Field(default=None, max_length=48)
    notes: str | None = Field(default=None, max_length=4000)


class ReadinessCreateRequest(BaseModel):
    """Commander-entered conservative readiness state."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=48)
    label: str = Field(min_length=1, max_length=128)
    state: str = Field(default="manual", max_length=48)
    requirements_known: str = Field(default="manual", max_length=32)
    requirements_text: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=4000)
    target_grade: str = Field(default="manual", max_length=16)
    target_engineer_label: str | None = Field(default=None, max_length=128)
    target_module_label: str | None = Field(default=None, max_length=128)


class DeleteResponse(BaseModel):
    """Delete response shape."""

    model_config = ConfigDict(extra="forbid")

    status: str


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _goal_payload(record: engineering.EngineeringGoalRecord) -> dict[str, Any]:
    return {
        "goal_id": record.goal_id,
        "commander_id": record.commander_id,
        "title": record.title,
        "description": record.description,
        "target_kind": record.target_kind,
        "target_reference": record.target_reference,
        "state": record.state,
        "priority": record.priority,
        "notes": record.notes,
        "linked_build_plan_id": record.linked_build_plan_id,
        "linked_material_gap_view_id": record.linked_material_gap_view_id,
        "linked_acquisition_handoff_ids": record.linked_acquisition_handoff_ids,
        "linked_operations_task_id": record.linked_operations_task_id,
        "source_chain": [
            {
                "source": "commander_entered",
                "truth_class": "commander_entered",
                "freshness": "manual",
            }
        ],
        "manual": True,
        "created_at": _dt(record.created_at),
        "updated_at": _dt(record.updated_at),
    }


def _build_payload(record: engineering.BuildPlanRecord) -> dict[str, Any]:
    return {
        "build_plan_id": record.build_plan_id,
        "title": record.title,
        "description": record.description,
        "target_ship": record.target_ship,
        "target_loadout_summary": record.target_loadout_summary,
        "source": record.source,
        "format_verification_state": record.format_verification_state,
        "state": record.state,
        "linked_goal_ids": record.linked_goal_ids,
        "linked_material_gap_view_id": record.linked_material_gap_view_id,
        "source_url": record.source_url,
        "notes": record.notes,
        "planned_build_not_current_loadout": True,
        "current_loadout_truth_owner": "intel_local_loadout_modulesinfo",
        "separation_from_current_loadout": (
            "BuildPlan is target planning only; Intel owns current loadout truth."
        ),
        "created_at": _dt(record.created_at),
        "updated_at": _dt(record.updated_at),
    }


def _gap_payload(record: engineering.MaterialGapRecord) -> dict[str, Any]:
    return {
        "gap_view_id": record.gap_view_id,
        "material_id": record.material_id,
        "material_display_name": record.material_display_name,
        "goal_id": record.goal_id,
        "build_plan_id": record.build_plan_id,
        "required_count": record.required_count,
        "current_count": record.current_count,
        "missing_count": record.missing_count,
        "gap_state": record.gap_state,
        "requirement_state": record.requirement_state,
        "inventory_state": record.inventory_state,
        "source_chain": record.source_chain,
        "caveats": record.caveats,
        "created_at": _dt(record.created_at),
        "updated_at": _dt(record.updated_at),
    }


def _gap_compat_payload(record: engineering.MaterialGapRecord) -> dict[str, Any]:
    payload = _gap_payload(record)
    payload["gap"] = record.missing_count
    payload["state"] = record.gap_state
    payload["fallback"] = (
        "Manual planning row"
        if record.missing_count is not None
        else "Unknown - missing inventory is not zero"
    )
    return payload


def _acquisition_payload(record: engineering.AcquisitionPlanRecord) -> dict[str, Any]:
    return {
        "acquisition_plan_id": record.acquisition_plan_id,
        "title": record.title,
        "linked_goal_ids": record.linked_goal_ids,
        "linked_build_plan_ids": record.linked_build_plan_ids,
        "target_materials": record.target_materials,
        "state": record.state,
        "navigation_handoff_ids": record.navigation_handoff_ids,
        "operations_task_id": record.operations_task_id,
        "selected_navigation_candidate_summary": (
            record.selected_navigation_candidate_summary
        ),
        "notes": record.notes,
        "ownership": {
            "plan": "engineering",
            "route_candidates": "navigation",
            "active_task": "operations",
        },
        "created_at": _dt(record.created_at),
        "updated_at": _dt(record.updated_at),
    }


def _readiness_payload(record: engineering.ReadinessRecord) -> dict[str, Any]:
    payload = {
        "readiness_id": record.readiness_id,
        "kind": record.kind,
        "label": record.label,
        "state": record.state,
        "requirements_known": record.requirements_known,
        "requirements_text": record.requirements_text,
        "notes": record.notes,
        "target_grade": record.target_grade,
        "target_engineer_label": record.target_engineer_label,
        "target_module_label": record.target_module_label,
        "caveats": record.caveats,
        "source_chain": record.source_chain,
        "manual_only": True,
        "created_at": _dt(record.created_at),
        "updated_at": _dt(record.updated_at),
    }
    if record.kind == "blueprint_progress":
        payload["blueprint_label"] = record.label
    elif record.kind == "engineer_unlock_state":
        payload["engineer_label"] = record.label
    elif record.kind == "guardian_tech_progress":
        payload["guardian_tech_label"] = record.label
    elif record.kind == "suit_engineering_state":
        payload["suit_engineering_label"] = record.label
    return payload


def _readiness_groups(
    records: list[engineering.ReadinessRecord],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {
        "blueprints": [],
        "engineers": [],
        "guardian_tech": [],
        "suit_engineering": [],
    }
    for record in records:
        payload = _readiness_payload(record)
        if record.kind == "blueprint_progress":
            groups["blueprints"].append(payload)
        elif record.kind == "engineer_unlock_state":
            groups["engineers"].append(payload)
        elif record.kind == "guardian_tech_progress":
            groups["guardian_tech"].append(payload)
        elif record.kind == "suit_engineering_state":
            groups["suit_engineering"].append(payload)
    return groups


def _import_payload(record: engineering.ImportSourceStateRecord) -> dict[str, Any]:
    return {
        "import_source_state_id": record.import_source_state_id,
        "provider_label": record.provider_label,
        "format_version_label": record.format_version_label,
        "format_verification_state": record.format_verification_state,
        "format_verification_evidence_summary": (
            record.format_verification_evidence_summary
        ),
        "consent_state": record.consent_state,
        "notes": record.notes,
        "caveats": record.caveats,
        "import_available": record.import_available,
        "export_available": record.export_available,
        "outbound_available": record.outbound_available,
        "created_at": _dt(record.created_at),
        "updated_at": _dt(record.updated_at),
    }


def _handoff_payload(result: engineering.HandoffResult) -> dict[str, Any]:
    return {
        "plan": _acquisition_payload(result.plan),
        "route_transfer_intent": result.route_transfer_intent,
        "route_intent": result.route_transfer_intent,
    }


def _http_422(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


def _record_disabled_source_attempt(source_label: str) -> str:
    event_id = str(uuid4())
    if _activity_log is not None:
        _activity_log.append(
            ActivityEntry(
                event_type=ENGINEERING_SOURCE_ATTEMPT_BLOCKED,
                timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                summary="Engineering source attempt blocked",
                payload={
                    "source_label": source_label,
                    "provider_label": source_label,
                    "attempted_capability": "source_attempt",
                    "blocked": True,
                    "outbound_attempted": False,
                    "outbound_call_executed": False,
                    "scrape_executed": False,
                    "oauth_started": False,
                },
                source_chain=[
                    {
                        "source": source_label,
                        "truth_class": "external_disabled",
                        "freshness": "not_loaded",
                    }
                ],
                redaction_state="redacted_summary_only",
                is_fact=False,
                linked_entity_refs={"source_label": source_label},
                surface_origin="engineering",
                correlation_id=event_id,
                event_id=event_id,
                source="external_disabled",
            )
        )
    return event_id


@router.get("/overview")
async def get_overview() -> dict[str, Any]:
    """Return the local-only Engineering overview."""
    factory = _ensure_session_factory()
    overview = await engineering.overview(factory)
    goals = await engineering.list_goals(factory)
    builds = await engineering.list_build_plans(factory)
    gaps = await engineering.list_material_gaps(factory)
    acquisitions = await engineering.list_acquisition_plans(factory)
    readiness = await engineering.list_readiness_states(factory)
    imports = await engineering.list_import_source_states(factory)
    overview["goals"] = [_goal_payload(record) for record in goals]
    overview["build_plans"] = [_build_payload(record) for record in builds]
    overview["material_gaps"] = [_gap_compat_payload(record) for record in gaps]
    overview["acquisition_plans"] = [
        _acquisition_payload(record) for record in acquisitions
    ]
    overview["import_sources"] = [_import_payload(record) for record in imports]
    overview["dashboard_pin"] = {
        "inventory": "Manual rows" if gaps else "No Verified Source",
        "active_goals": len([goal for goal in goals if goal.state != "archived"]),
        "pending_acquisitions": len(
            [
                plan
                for plan in acquisitions
                if plan.state not in {"complete", "archived"}
            ]
        ),
        "imports": "Disabled in Settings",
    }
    overview["readiness"] = _readiness_groups(readiness)
    source_posture = overview.setdefault("source_posture", {})
    source_posture["materials"] = {
        "current_inventory_state": "manual" if gaps else "No Verified Source",
        "missing_file_semantics": "Unknown, not zero",
    }
    counts = overview.setdefault("counts", {})
    counts["material_gaps"] = len(gaps)
    counts["pending_acquisition_plans"] = len(
        [plan for plan in acquisitions if plan.state not in {"complete", "archived"}]
    )
    return overview


@router.get("/goals")
async def get_goals() -> dict[str, Any]:
    """Return local Engineering goals."""
    records = await engineering.list_goals(_ensure_session_factory())
    return {"goals": [_goal_payload(record) for record in records], "manual": True}


@router.post("/goal", status_code=status.HTTP_201_CREATED)
async def create_goal(body: GoalCreateRequest) -> dict[str, Any]:
    """Create a local commander-entered Engineering goal."""
    try:
        record = await engineering.create_goal(
            _ensure_session_factory(),
            engineering.EngineeringGoalCreate(
                title=body.title,
                commander_id=body.commander_id,
                description=body.description,
                target_kind=body.target_kind,
                target_reference=body.target_reference,
                state=body.state,
                priority=body.priority,
                notes=body.notes,
                linked_build_plan_id=body.linked_build_plan_id,
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    return _goal_payload(record)


@router.patch("/goals/{goal_id}")
async def update_goal(goal_id: str, body: GoalPatchRequest) -> dict[str, Any]:
    """Update a local Engineering goal."""
    changes: engineering.EngineeringGoalUpdate = {}
    if "title" in body.model_fields_set and body.title is not None:
        changes["title"] = body.title
    if "description" in body.model_fields_set:
        changes["description"] = body.description
    if "target_kind" in body.model_fields_set and body.target_kind is not None:
        changes["target_kind"] = body.target_kind
    if (
        "target_reference" in body.model_fields_set
        and body.target_reference is not None
    ):
        changes["target_reference"] = body.target_reference
    if "state" in body.model_fields_set and body.state is not None:
        changes["state"] = body.state
    if "priority" in body.model_fields_set and body.priority is not None:
        changes["priority"] = body.priority
    if "notes" in body.model_fields_set:
        changes["notes"] = body.notes
    if "linked_build_plan_id" in body.model_fields_set:
        changes["linked_build_plan_id"] = body.linked_build_plan_id
    try:
        record = await engineering.update_goal(
            _ensure_session_factory(),
            goal_id,
            changes,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _goal_payload(record)


@router.delete("/goals/{goal_id}", response_model=DeleteResponse)
async def delete_goal(goal_id: str) -> DeleteResponse:
    """Delete a local Engineering goal."""
    deleted = await engineering.delete_goal(
        _ensure_session_factory(),
        goal_id,
        activity_log=_activity_log,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return DeleteResponse(status="ok")


@router.get("/builds")
async def get_builds() -> dict[str, Any]:
    """Return local planned builds."""
    records = await engineering.list_build_plans(_ensure_session_factory())
    return {
        "build_plans": [_build_payload(record) for record in records],
        "current_loadout_truth_owner": "intel",
    }


@router.post("/builds", status_code=status.HTTP_201_CREATED)
async def create_build(body: BuildPlanCreateRequest) -> dict[str, Any]:
    """Create a local planned build."""
    try:
        record = await engineering.create_build_plan(
            _ensure_session_factory(),
            engineering.BuildPlanCreate(
                title=body.title,
                description=body.description,
                target_ship=body.target_ship,
                target_loadout_summary=body.target_loadout_summary,
                source=body.source,
                format_verification_state=body.format_verification_state,
                state=body.state,
                linked_goal_ids=body.linked_goal_ids,
                source_url=body.source_url,
                notes=body.notes,
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    return _build_payload(record)


@router.patch("/builds/{build_plan_id}")
async def update_build(
    build_plan_id: str,
    body: BuildPlanPatchRequest,
) -> dict[str, Any]:
    """Update a local planned build."""
    changes: engineering.BuildPlanUpdate = {}
    if "title" in body.model_fields_set and body.title is not None:
        changes["title"] = body.title
    if "description" in body.model_fields_set:
        changes["description"] = body.description
    if "target_ship" in body.model_fields_set and body.target_ship is not None:
        changes["target_ship"] = body.target_ship
    if (
        "target_loadout_summary" in body.model_fields_set
        and body.target_loadout_summary is not None
    ):
        changes["target_loadout_summary"] = body.target_loadout_summary
    if "source" in body.model_fields_set and body.source is not None:
        changes["source"] = body.source
    if (
        "format_verification_state" in body.model_fields_set
        and body.format_verification_state is not None
    ):
        changes["format_verification_state"] = body.format_verification_state
    if "state" in body.model_fields_set and body.state is not None:
        changes["state"] = body.state
    if "linked_goal_ids" in body.model_fields_set and body.linked_goal_ids is not None:
        changes["linked_goal_ids"] = body.linked_goal_ids
    if "source_url" in body.model_fields_set:
        changes["source_url"] = body.source_url
    if "notes" in body.model_fields_set:
        changes["notes"] = body.notes
    try:
        record = await engineering.update_build_plan(
            _ensure_session_factory(),
            build_plan_id,
            changes,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _build_payload(record)


@router.delete("/builds/{build_plan_id}", response_model=DeleteResponse)
async def delete_build(build_plan_id: str) -> DeleteResponse:
    """Delete a local planned build."""
    deleted = await engineering.delete_build_plan(
        _ensure_session_factory(),
        build_plan_id,
        activity_log=_activity_log,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return DeleteResponse(status="ok")


@router.get("/materials")
async def get_materials() -> dict[str, Any]:
    """Return material gap view rows without inferred-zero inventory."""
    rows = await engineering.list_material_gaps(_ensure_session_factory())
    if not rows:
        return engineering.material_gap_empty_snapshot()
    return {
        "surface_state": "manual_planning",
        "inventory_state": "manual_or_not_loaded",
        "requirement_state": "manual_or_unknown",
        "rows": [_gap_payload(row) for row in rows],
        "caveats": [
            "Commander-entered counts are planning inputs.",
            "Missing local material files are not treated as zero inventory.",
        ],
        "nullprovider_safe": True,
    }


@router.post("/material-overrides", status_code=status.HTTP_201_CREATED)
async def upsert_material_override(body: MaterialOverrideRequest) -> dict[str, Any]:
    """Create a commander-entered material gap planning row."""
    try:
        record = await engineering.upsert_material_override(
            _ensure_session_factory(),
            engineering.MaterialGapOverrideUpsert(
                material_id=body.material_id,
                material_display_name=body.material_display_name,
                goal_id=body.goal_id,
                build_plan_id=body.build_plan_id,
                commander_override_required=body.commander_override_required,
                commander_override_current=body.commander_override_current,
                required_note=body.required_note,
                current_note=body.current_note,
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    return _gap_payload(record)


@router.post("/material-gaps", status_code=status.HTTP_201_CREATED)
async def create_material_gap_alias(body: MaterialOverrideRequest) -> dict[str, Any]:
    """Compatibility alias for material gap planning rows."""
    return await upsert_material_override(body)


@router.delete("/material-overrides/{gap_view_id}", response_model=DeleteResponse)
async def delete_material_override(gap_view_id: str) -> DeleteResponse:
    """Delete a commander-entered material gap planning row."""
    deleted = await engineering.delete_material_override(
        _ensure_session_factory(),
        gap_view_id,
        activity_log=_activity_log,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return DeleteResponse(status="ok")


@router.get("/acquisition-plans")
async def get_acquisition_plans() -> dict[str, Any]:
    """Return local acquisition plans."""
    records = await engineering.list_acquisition_plans(_ensure_session_factory())
    return {"acquisition_plans": [_acquisition_payload(record) for record in records]}


@router.post("/acquisition-plan", status_code=status.HTTP_201_CREATED)
async def create_acquisition_plan(
    body: AcquisitionPlanCreateRequest,
) -> dict[str, Any]:
    """Create a local acquisition plan."""
    try:
        record = await engineering.create_acquisition_plan(
            _ensure_session_factory(),
            engineering.AcquisitionPlanCreate(
                title=body.title,
                linked_goal_ids=body.linked_goal_ids,
                linked_build_plan_ids=body.linked_build_plan_ids,
                target_materials=body.target_materials,
                state=body.state,
                notes=body.notes,
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    return _acquisition_payload(record)


@router.patch("/acquisition-plans/{acquisition_plan_id}")
async def update_acquisition_plan(
    acquisition_plan_id: str,
    body: AcquisitionPlanPatchRequest,
) -> dict[str, Any]:
    """Update a local acquisition plan."""
    changes: engineering.AcquisitionPlanUpdate = {}
    if "title" in body.model_fields_set and body.title is not None:
        changes["title"] = body.title
    if "linked_goal_ids" in body.model_fields_set and body.linked_goal_ids is not None:
        changes["linked_goal_ids"] = body.linked_goal_ids
    if (
        "linked_build_plan_ids" in body.model_fields_set
        and body.linked_build_plan_ids is not None
    ):
        changes["linked_build_plan_ids"] = body.linked_build_plan_ids
    if (
        "target_materials" in body.model_fields_set
        and body.target_materials is not None
    ):
        changes["target_materials"] = body.target_materials
    if "state" in body.model_fields_set and body.state is not None:
        changes["state"] = body.state
    if "notes" in body.model_fields_set:
        changes["notes"] = body.notes
    try:
        record = await engineering.update_acquisition_plan(
            _ensure_session_factory(),
            acquisition_plan_id,
            changes,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _acquisition_payload(record)


@router.delete(
    "/acquisition-plans/{acquisition_plan_id}",
    response_model=DeleteResponse,
)
async def delete_acquisition_plan(acquisition_plan_id: str) -> DeleteResponse:
    """Delete a local acquisition plan."""
    deleted = await engineering.delete_acquisition_plan(
        _ensure_session_factory(),
        acquisition_plan_id,
        activity_log=_activity_log,
    )
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return DeleteResponse(status="ok")


@router.post("/acquisition-plans/{acquisition_plan_id}/handoff/navigation")
async def handoff_to_navigation(acquisition_plan_id: str) -> dict[str, Any]:
    """Create a Navigation handoff intent for an Engineering plan."""
    result = await engineering.handoff_to_navigation(
        _ensure_session_factory(),
        acquisition_plan_id,
        activity_log=_activity_log,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _handoff_payload(result)


@router.post("/acquisition-plans/{acquisition_plan_id}/handoff/operations")
async def handoff_to_operations(acquisition_plan_id: str) -> dict[str, Any]:
    """Create an Operations handoff intent for an Engineering plan."""
    result = await engineering.handoff_to_operations(
        _ensure_session_factory(),
        acquisition_plan_id,
        activity_log=_activity_log,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _handoff_payload(result)


@router.get("/readiness-states")
async def get_readiness_states() -> dict[str, Any]:
    """Return all conservative local/manual readiness states."""
    records = await engineering.list_readiness_states(_ensure_session_factory())
    return {"readiness_states": [_readiness_payload(record) for record in records]}


@router.post("/readiness-states", status_code=status.HTTP_201_CREATED)
async def create_readiness_state(body: ReadinessCreateRequest) -> dict[str, Any]:
    """Create a local/manual readiness state."""
    try:
        record = await engineering.create_readiness_state(
            _ensure_session_factory(),
            engineering.ReadinessCreate(
                kind=body.kind,
                label=body.label,
                state=body.state,
                requirements_known=body.requirements_known,
                requirements_text=body.requirements_text,
                notes=body.notes,
                target_grade=body.target_grade,
                target_engineer_label=body.target_engineer_label,
                target_module_label=body.target_module_label,
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    return _readiness_payload(record)


@router.get("/blueprints")
async def get_blueprints() -> dict[str, Any]:
    """Return conservative blueprint readiness rows."""
    records = await engineering.list_readiness_states(
        _ensure_session_factory(),
        kind="blueprint_progress",
    )
    return {
        "blueprints": [_readiness_payload(record) for record in records],
        "unsupported_facts": ["blueprint material costs", "global blueprint lists"],
    }


@router.get("/engineers")
async def get_engineers() -> dict[str, Any]:
    """Return conservative engineer unlock readiness rows."""
    records = await engineering.list_readiness_states(
        _ensure_session_factory(),
        kind="engineer_unlock_state",
    )
    return {
        "engineers": [_readiness_payload(record) for record in records],
        "unsupported_facts": ["unlock requirements", "referral mechanics"],
    }


@router.get("/guardian-tech")
async def get_guardian_tech() -> dict[str, Any]:
    """Return conservative Guardian tech readiness rows."""
    records = await engineering.list_readiness_states(
        _ensure_session_factory(),
        kind="guardian_tech_progress",
    )
    return {
        "guardian_tech": [_readiness_payload(record) for record in records],
        "unsupported_facts": ["Guardian site mechanics", "unlock requirements"],
    }


@router.get("/suit-engineering")
async def get_suit_engineering() -> dict[str, Any]:
    """Return conservative suit engineering readiness rows."""
    records = await engineering.list_readiness_states(
        _ensure_session_factory(),
        kind="suit_engineering_state",
    )
    return {
        "suit_engineering": [_readiness_payload(record) for record in records],
        "unsupported_facts": ["suit material costs", "effect requirements"],
    }


@router.get("/import-sources")
async def get_import_sources() -> dict[str, Any]:
    """Return disabled EDSY/Coriolis import/export posture."""
    factory = _ensure_session_factory()
    records = [
        await engineering.ensure_import_source_state(
            factory,
            provider,
            activity_log=_activity_log,
        )
        for provider in sorted(engineering.IMPORT_PROVIDERS)
    ]
    return {
        "import_sources": [_import_payload(record) for record in records],
        "outbound_behavior": "disabled",
    }


@router.post("/import-sources/{provider_label}/attempt-import")
async def attempt_import(provider_label: str) -> dict[str, Any]:
    """Record a disabled import attempt without any outbound behavior."""
    try:
        record = await engineering.record_disabled_import_attempt(
            _ensure_session_factory(),
            provider_label,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    return {
        "status": "disabled",
        "import_source": _import_payload(record),
        "outbound_attempted": False,
        "reason": "Format verification evidence is required before import.",
    }


@router.post("/import-sources/{provider_label}/attempt-export")
async def attempt_export(provider_label: str) -> dict[str, Any]:
    """Record a disabled export attempt without any outbound behavior."""
    try:
        record = await engineering.record_disabled_export_attempt(
            _ensure_session_factory(),
            provider_label,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    return {
        "status": "disabled",
        "import_source": _import_payload(record),
        "outbound_attempted": False,
        "reason": "Format verification evidence is required before export.",
    }


@router.post("/source-attempts/{source_label}")
async def record_disabled_source_attempt(source_label: str) -> dict[str, Any]:
    """Record a disabled/source-gated attempt without outbound behavior."""
    normalized = source_label.strip().lower()
    if normalized not in {"capi", "ardent"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    event_id = _record_disabled_source_attempt(normalized)
    return {
        "status": "blocked",
        "source_label": normalized,
        "outbound_attempted": False,
        "event_id": event_id,
        "reason": "Source is gated or disabled for Phase 8 local-only baseline.",
    }


@router.post("/materials/capi-attempt")
async def record_capi_material_attempt() -> dict[str, Any]:
    """Compatibility endpoint for disabled CAPI material inventory attempts."""
    return await record_disabled_source_attempt("capi")


@router.post("/materials/ardent-attempt")
async def record_ardent_material_attempt() -> dict[str, Any]:
    """Compatibility endpoint for disabled Ardent material truth attempts."""
    return await record_disabled_source_attempt("ardent")


@router.post("/builds/edsy-import-attempt")
async def record_edsy_import_attempt() -> dict[str, Any]:
    """Compatibility endpoint for disabled EDSY import attempts."""
    return await attempt_import("edsy")


@router.post("/builds/edsy-export-attempt")
async def record_edsy_export_attempt() -> dict[str, Any]:
    """Compatibility endpoint for disabled EDSY export attempts."""
    return await attempt_export("edsy")


@router.post("/builds/coriolis-import-attempt")
async def record_coriolis_import_attempt() -> dict[str, Any]:
    """Compatibility endpoint for disabled Coriolis import attempts."""
    return await attempt_import("coriolis")


@router.post("/builds/coriolis-export-attempt")
async def record_coriolis_export_attempt() -> dict[str, Any]:
    """Compatibility endpoint for disabled Coriolis export attempts."""
    return await attempt_export("coriolis")
