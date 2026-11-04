"""Phase 8 local-only Engineering planning API."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.event_types import (
    ENGINEERING_CATALOG_IMPORTED,
    ENGINEERING_SOURCE_ATTEMPT_BLOCKED,
    ENGINEERING_SOURCE_ATTEMPT_FAILED,
)
from omnicovas.core.state_manager import StateManager
from omnicovas.db.models import JournalEvent
from omnicovas.features import (
    engineering,
    engineering_catalog,
    engineering_progression,
    engineering_reference,
    engineering_workbench,
    ship_power,
)

router = APIRouter(prefix="/engineering", tags=["engineering"])

_JOURNAL_INVENTORY_POSTURE = {
    "verified_local": "verified_local_journal",
    "partial_inconsistent": "journal_quantities_inconsistent",
}

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


class ProgressionCommissionRequest(BaseModel):
    """One outcome-first module target using locally observed recipes."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    slot: str = Field(min_length=1, max_length=96)
    module_label: str | None = Field(default=None, max_length=128)
    blueprint_id: str = Field(min_length=1, max_length=128)
    target_grade: int = Field(ge=1, le=5)
    experimental_effect: str | None = Field(default=None, max_length=128)
    priority: str = Field(default="normal", max_length=16)
    acquisition_destination: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)


class WorkbenchModuleTargetRequest(BaseModel):
    """One current-loadout slot in a whole-build Engineering design."""

    model_config = ConfigDict(extra="forbid")

    slot: str = Field(min_length=1, max_length=96)
    module_id: str | None = Field(default=None, max_length=128)
    module_label: str | None = Field(default=None, max_length=128)
    target_state: str = Field(
        default="engineered", pattern="^(engineered|stock|empty)$"
    )
    blueprint_id: str | None = Field(default=None, max_length=128)
    target_grade: int | None = Field(default=None, ge=1, le=5)
    experimental_effect: str | None = Field(default=None, max_length=128)


class WorkbenchBuildCommissionRequest(BaseModel):
    """Persist a multi-module design rooted in the observed current ship."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=128)
    baseline_build_id: str | None = Field(default=None, max_length=128)
    baseline_observation_id: int | None = Field(default=None, gt=0)
    preserve_cargo_capacity: bool = True
    power_plan: dict[str, Any] | None = None
    operating_conditions: dict[str, Any] | None = None
    hull_id: str | None = Field(default=None, max_length=128)
    module_targets: list[WorkbenchModuleTargetRequest] = Field(
        default_factory=list, max_length=64
    )
    priority: str = Field(default="normal", max_length=16)
    acquisition_destination: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)


class WorkbenchPreviewRequest(BaseModel):
    """Validate and preview one canonical ship configuration."""

    model_config = ConfigDict(extra="forbid")
    hull_id: str | None = Field(default=None, max_length=128)
    baseline_build_id: str | None = Field(default=None, max_length=128)
    baseline_observation_id: int | None = Field(default=None, gt=0)
    preserve_cargo_capacity: bool = True
    priority: str = Field(default="normal", pattern="^(high|normal|unsorted|low)$")
    power_plan: dict[str, Any] | None = None
    operating_conditions: dict[str, Any] | None = None

    module_targets: list[WorkbenchModuleTargetRequest] = Field(
        default_factory=list, max_length=64
    )


class CatalogImportRequest(BaseModel):
    """A local reference pack plus explicit Commander rights attestation."""

    model_config = ConfigDict(extra="forbid")

    catalog: dict[str, Any]
    rights_attested: bool


class ReferenceDownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    private_use_confirmed: bool


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


def _reject_unvalidated_module_targets(summary: dict[str, Any]) -> None:
    """Keep canonical module configurations behind fit/compatibility validation."""
    if "module_targets" in summary:
        raise ValueError(
            "Module configurations must be created through the Engineering "
            "workbench so slot fit and blueprint compatibility are validated."
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
    progression = await engineering_progression.portfolio(
        factory,
        builds,
        goals,
        _state_manager.public_snapshot() if _state_manager is not None else {},
    )
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
    overview["progression"] = progression
    source_posture = overview.setdefault("source_posture", {})
    inventory_state = progression["inventory"]["state"]
    source_posture["materials"] = {
        "current_inventory_state": inventory_state,
        "missing_file_semantics": "Unknown, not zero",
    }
    overview["dashboard_pin"]["inventory"] = (
        "Verified local Journal"
        if inventory_state == "verified_local"
        else "No Verified Source"
    )
    # The feature-level posture cannot see the Journal-backed inventory; keep
    # it from contradicting the reconciled state read just above.
    journal_posture = _JOURNAL_INVENTORY_POSTURE.get(inventory_state)
    if journal_posture is not None:
        source_posture["local_material_inventory"] = journal_posture
    reference_state = progression["reference_catalog"]["state"]
    overview["dashboard_pin"]["imports"] = (
        "Local reference active"
        if reference_state == "commander_supplied_validated"
        else "No local reference pack"
    )
    source_posture["engineering_reference_catalog"] = {
        "state": reference_state,
        "network_access": "none",
        "universal_coverage": False,
    }
    counts = overview.setdefault("counts", {})
    counts["material_gaps"] = len(gaps)
    counts["pending_acquisition_plans"] = len(
        [plan for plan in acquisitions if plan.state not in {"complete", "archived"}]
    )
    return overview


@router.get("/progression")
async def get_progression() -> dict[str, Any]:
    """Return the canonical target-to-readiness portfolio."""
    factory = _ensure_session_factory()
    return await engineering_progression.portfolio(
        factory,
        await engineering.list_build_plans(factory),
        await engineering.list_goals(factory),
        _state_manager.public_snapshot() if _state_manager is not None else {},
    )


async def _create_linked_progression(
    *,
    title: str,
    module_targets: list[dict[str, Any]],
    priority: str,
    acquisition_destination: str | None,
    notes: str | None,
    target_ship: dict[str, Any] | None = None,
    catalog_scope: str = engineering_progression.CATALOG_SCOPE,
    catalog_version: str = engineering_progression.CATALOG_VERSION,
    calculation_version: str = engineering_progression.CALCULATION_VERSION,
    build_source: str = "commander_designed_from_observed_loadout",
    baseline: dict[str, Any] | None = None,
    preserve_cargo_capacity: bool = True,
    power_plan: dict[str, Any] | None = None,
    operating_conditions: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create one durable build, goal, assessment, and acquisition plan."""
    factory = _ensure_session_factory()
    live_state = _state_manager.public_snapshot() if _state_manager is not None else {}
    ship_state = baseline or live_state
    build = await engineering.create_build_plan(
        factory,
        engineering.BuildPlanCreate(
            title=title,
            target_ship=target_ship
            or {
                "ship_type": ship_state.get("current_ship_type"),
                "ship_id": ship_state.get("current_ship_id"),
                "truth_class": "commander_observed_reference",
            },
            target_loadout_summary={
                "module_targets": module_targets,
                "acquisition_destination": acquisition_destination,
                "configuration_version": engineering_workbench.CONFIGURATION_VERSION,
                "catalog_scope": catalog_scope,
                "catalog_version": catalog_version,
                "calculation_version": calculation_version,
                "observed_baseline": baseline,
                "constraints": {"preserve_cargo_capacity": preserve_cargo_capacity},
                "power_plan": power_plan,
                "operating_conditions": operating_conditions,
            },
            source=build_source,
            state="active",
            notes=notes,
        ),
        activity_log=_activity_log,
    )
    goal = await engineering.create_goal(
        factory,
        engineering.EngineeringGoalCreate(
            title=title,
            target_kind="ship_build_engineering",
            target_reference={
                "module_targets": module_targets,
                "catalog_scope": catalog_scope,
            },
            state="active",
            priority=priority,
            notes=notes,
            linked_build_plan_id=build.build_plan_id,
        ),
        activity_log=_activity_log,
    )
    updated_build = await engineering.update_build_plan(
        factory,
        build.build_plan_id,
        {"linked_goal_ids": [goal.goal_id]},
        activity_log=_activity_log,
    )
    progression = await engineering_progression.portfolio(
        factory,
        await engineering.list_build_plans(factory),
        await engineering.list_goals(factory),
        live_state,
    )
    assessment = next(
        row
        for row in progression["builds"]
        if row["build_plan_id"] == build.build_plan_id
    )
    target_materials = [
        {
            "material_id": material["material_id"],
            "display_name": material["display_name"],
            "quantity_needed": material["deficit"],
            "required": material["required"],
            "reserved": material["reserved"],
            "destination": acquisition_destination,
            "inventory_state": material["state"],
            "trade_alternatives": [
                trade
                for trade in assessment.get("trade_alternatives", [])
                if trade.get("to_material_id") == material["material_id"]
            ],
        }
        for material in assessment["materials"]
        if material["deficit"] is None or material["deficit"] > 0
    ]
    acquisition = await engineering.create_acquisition_plan(
        factory,
        engineering.AcquisitionPlanCreate(
            title=f"Acquire materials — {title}",
            linked_goal_ids=[goal.goal_id],
            linked_build_plan_ids=[build.build_plan_id],
            target_materials=target_materials,
            notes=(
                notes
                or "Generated from locally observed recipes; unknown inputs "
                "remain visible in Engineering."
            ),
        ),
        activity_log=_activity_log,
    )
    return {
        "goal": _goal_payload(goal),
        "build": _build_payload(updated_build or build),
        "acquisition_plan": _acquisition_payload(acquisition),
        "assessment": assessment,
        "nullprovider_safe": True,
    }


@router.post("/progression/commission", status_code=status.HTTP_201_CREATED)
async def create_progression_commission(
    body: ProgressionCommissionRequest,
) -> dict[str, Any]:
    """Persist the linked goal, target build, and acquisition plan."""
    live_state = _state_manager.public_snapshot() if _state_manager is not None else {}
    recipes = await engineering_progression.observed_recipes(_ensure_session_factory())
    reference_catalog = await engineering_catalog.active_catalog(
        _ensure_session_factory()
    )
    workbench = engineering_workbench.build_observed_workbench(
        live_state, recipes, reference_catalog
    )
    try:
        targets = engineering_workbench.validate_observed_targets(
            workbench,
            [
                {
                    "slot": body.slot,
                    "target_state": "engineered",
                    "blueprint_id": body.blueprint_id,
                    "target_grade": body.target_grade,
                    "experimental_effect": body.experimental_effect,
                }
            ],
        )
        performance = engineering_workbench.performance_comparison(
            live_state, targets, reference_catalog
        )
        _apply_cargo_constraint(performance, True)
        errors = performance.get("configuration_check", {}).get("errors", [])
        if errors:
            raise ValueError(" ".join(errors))
        return await _create_linked_progression(
            title=body.title,
            module_targets=targets,
            priority=body.priority,
            acquisition_destination=body.acquisition_destination,
            notes=body.notes,
            baseline=engineering_workbench.observed_baseline(live_state),
            catalog_version=(
                f"{reference_catalog['catalog_id']}@{reference_catalog['version']}"
                if reference_catalog
                else engineering_progression.CATALOG_VERSION
            ),
        )
    except ValueError as exc:
        raise _http_422(exc) from exc


@router.post("/workbench/builds", status_code=status.HTTP_201_CREATED)
async def create_workbench_build(
    body: WorkbenchBuildCommissionRequest,
) -> dict[str, Any]:
    """Commission a build from an observed ship or active local reference pack."""
    if (
        sum(
            bool(value)
            for value in (
                body.hull_id,
                body.baseline_build_id,
                body.baseline_observation_id,
            )
        )
        > 1
    ):
        raise HTTPException(
            status_code=422, detail="Choose one ship observation or saved variant."
        )

    if body.hull_id and not any(
        h.get("stock_modules")
        for h in (
            await engineering_catalog.active_catalog(_ensure_session_factory()) or {}
        ).get("hulls", [])
        if h["id"] == body.hull_id
    ):
        active = await engineering_catalog.active_catalog(_ensure_session_factory())
        if active is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="No validated local Engineering reference pack is active.",
            )
        try:
            targets = engineering_catalog.validate_design(
                active,
                body.hull_id,
                [target.model_dump() for target in body.module_targets],
            )
        except ValueError as exc:
            raise _http_422(exc) from exc
        hull = next(row for row in active["hulls"] if row["id"] == body.hull_id)
        try:
            return await _create_linked_progression(
                title=body.title,
                module_targets=targets,
                priority=body.priority,
                acquisition_destination=body.acquisition_destination,
                notes=body.notes,
                target_ship={
                    "ship_type": hull["id"],
                    "ship_label": hull["name"],
                    "truth_class": "commander_planned_reference",
                    "ownership_state": "not_required",
                },
                catalog_scope="commander_supplied_reference_pack",
                catalog_version=f"{active['catalog_id']}@{active['version']}",
                calculation_version=engineering_catalog.CALCULATION_VERSION,
                build_source="commander_designed_from_reference_pack",
            )
        except ValueError as exc:
            raise _http_422(exc) from exc

    live_state = _state_manager.public_snapshot() if _state_manager is not None else {}
    saved_catalog = None
    if body.hull_id:
        active = await engineering_catalog.active_catalog(_ensure_session_factory())
        if active is None:
            raise HTTPException(
                status_code=422, detail="A validated local catalogue is required."
            )
        try:
            live_state = engineering_workbench.catalogue_baseline(active, body.hull_id)
        except ValueError as exc:
            raise _http_422(exc) from exc
    if body.baseline_build_id:
        live_state, saved_catalog = await _saved_baseline(body.baseline_build_id)
    elif body.baseline_observation_id:
        live_state = await _observation_baseline(body.baseline_observation_id)
    catalog = engineering_progression.observed_loadout_catalog(live_state)
    if catalog["state"] != "verified_local":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A locally observed ship Loadout is required to design a build.",
        )
    recipes = await engineering_progression.observed_recipes(_ensure_session_factory())
    reference_catalog = await engineering_catalog.active_catalog(
        _ensure_session_factory()
    )
    if body.baseline_build_id:
        reference_catalog = saved_catalog
    workbench = engineering_workbench.build_observed_workbench(
        live_state, recipes, reference_catalog
    )
    try:
        targets = engineering_workbench.validate_observed_targets(
            workbench,
            [target.model_dump() for target in body.module_targets],
            allow_empty=body.power_plan is not None,
        )
        performance = engineering_workbench.performance_comparison(
            live_state,
            targets,
            reference_catalog,
            body.power_plan,
            body.operating_conditions,
        )
        _apply_cargo_constraint(performance, body.preserve_cargo_capacity)
        errors = performance.get("configuration_check", {}).get("errors", [])
        if errors:
            raise ValueError(" ".join(errors))
    except ValueError as exc:
        raise _http_422(exc) from exc
    try:
        return await _create_linked_progression(
            title=body.title,
            module_targets=targets,
            priority=body.priority,
            acquisition_destination=body.acquisition_destination,
            notes=body.notes,
            calculation_version=engineering_progression.CALCULATION_VERSION,
            baseline=engineering_workbench.observed_baseline(live_state),
            target_ship={
                "ship_type": live_state["current_ship_type"],
                "truth_class": "commander_planned_reference",
                "ownership_state": "not_required",
            }
            if live_state.get("planning_hull_id")
            else None,
            build_source="commander_designed_from_reference_pack"
            if live_state.get("planning_hull_id")
            else "commander_designed_from_observed_loadout",
            operating_conditions=performance.get("operating_conditions"),
            preserve_cargo_capacity=body.preserve_cargo_capacity,
            power_plan=performance["power_management"]["plan"]
            if body.power_plan is not None
            else None,
            catalog_version=(
                f"{reference_catalog['catalog_id']}@{reference_catalog['version']}"
                if reference_catalog
                else engineering_progression.CATALOG_VERSION
            ),
        )
    except ValueError as exc:
        raise _http_422(exc) from exc


@router.post("/workbench/preview")
async def preview_workbench_build(body: WorkbenchPreviewRequest) -> dict[str, Any]:
    """Validate and calculate a non-persistent observed-ship plan preview."""
    if (
        sum(
            bool(v)
            for v in (
                body.hull_id,
                body.baseline_build_id,
                body.baseline_observation_id,
            )
        )
        > 1
    ):
        raise HTTPException(
            status_code=422, detail="Choose one ship observation or saved variant."
        )
    live_state = _state_manager.public_snapshot() if _state_manager is not None else {}
    recipes = await engineering_progression.observed_recipes(_ensure_session_factory())
    reference_catalog = await engineering_catalog.active_catalog(
        _ensure_session_factory()
    )
    if body.hull_id:
        if reference_catalog is None:
            raise HTTPException(
                status_code=422, detail="A validated local catalogue is required."
            )
        try:
            live_state = engineering_workbench.catalogue_baseline(
                reference_catalog, body.hull_id
            )
        except ValueError as exc:
            raise _http_422(exc) from exc
    if body.baseline_build_id:
        live_state, reference_catalog = await _saved_baseline(body.baseline_build_id)
    elif body.baseline_observation_id:
        live_state = await _observation_baseline(body.baseline_observation_id)
    workbench = engineering_workbench.build_observed_workbench(
        live_state, recipes, reference_catalog
    )
    if workbench["state"] != "verified_local":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A locally observed ship Loadout is required to preview a build.",
        )
    try:
        targets = engineering_workbench.validate_observed_targets(
            workbench,
            [target.model_dump() for target in body.module_targets],
            allow_empty=body.power_plan is not None,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    try:
        performance = engineering_workbench.performance_comparison(
            live_state,
            targets,
            reference_catalog,
            body.power_plan,
            body.operating_conditions,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    _apply_cargo_constraint(performance, body.preserve_cargo_capacity)
    # Use the existing portfolio allocator without writing a build, goal, or
    # reservation. The hypothetical variant competes with the same active plans
    # and priority order it will use after Save.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    preview_id = "engineering-preview"
    candidate = engineering.BuildPlanRecord(
        build_plan_id=preview_id,
        title="Preview",
        description=None,
        target_ship=workbench["ship"],
        target_loadout_summary={
            "module_targets": targets,
            "power_plan": performance["power_management"]["plan"]
            if body.power_plan is not None
            else None,
            "operating_conditions": performance.get("operating_conditions"),
            "observed_baseline": engineering_workbench.observed_baseline(live_state),
            "catalog_scope": engineering_progression.CATALOG_SCOPE,
            "catalog_version": (
                f"{reference_catalog['catalog_id']}@{reference_catalog['version']}"
                if reference_catalog
                else engineering_progression.CATALOG_VERSION
            ),
        },
        source="commander_designed_from_observed_loadout",
        format_verification_state="not_applicable",
        state="active",
        linked_goal_ids=[],
        linked_material_gap_view_id=None,
        source_url=None,
        notes=None,
        created_at=now,
        updated_at=now,
    )
    candidate_goal = engineering.EngineeringGoalRecord(
        goal_id=preview_id,
        commander_id=None,
        title="Preview",
        description=None,
        target_kind="module_engineering",
        target_reference={},
        state="active",
        priority=body.priority,
        notes=None,
        linked_build_plan_id=preview_id,
        linked_material_gap_view_id=None,
        linked_acquisition_handoff_ids=[],
        linked_operations_task_id=None,
        created_at=now,
        updated_at=now,
    )
    assessment = await engineering_progression.portfolio(
        _ensure_session_factory(),
        [*await engineering.list_build_plans(_ensure_session_factory()), candidate],
        [*await engineering.list_goals(_ensure_session_factory()), candidate_goal],
        live_state,
        include_workbenches=False,
    )
    return {
        "configuration_version": engineering_workbench.CONFIGURATION_VERSION,
        "targets": targets,
        "performance": performance,
        "requirements": next(
            row for row in assessment["builds"] if row["build_plan_id"] == preview_id
        ),
        "persisted": False,
        "nullprovider_safe": True,
    }


def _apply_cargo_constraint(performance: dict[str, Any], preserve: bool) -> None:
    cargo = next(
        (m for m in performance.get("metrics", []) if m["id"] == "cargo_capacity"), None
    )
    if (
        preserve
        and cargo
        and cargo["installed"].get("value") is not None
        and cargo["planned"].get("value") is None
    ):
        check = performance["configuration_check"]
        check["errors"].append(
            "Cargo preservation cannot be verified: "
            "planned capacity inputs are missing."
        )
        check["state"] = "invalid"
    if preserve and cargo and cargo.get("delta") is not None and cargo["delta"] < 0:
        check = performance["configuration_check"]
        check["errors"].append(
            "Cargo preservation is enabled: this change reduces cargo capacity."
        )
        check["state"] = "invalid"


async def _observation_baseline(observation_id: int) -> dict[str, Any]:
    async with _ensure_session_factory()() as db:
        row = await db.get(JournalEvent, observation_id)
        if row is None or row.event_type != "Loadout":
            raise HTTPException(
                status_code=404, detail="Loadout observation not found."
            )
        try:
            event = json.loads(row.raw_json)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=422, detail="Loadout observation is unreadable."
            ) from exc
        if not isinstance(event, dict):
            raise HTTPException(
                status_code=422, detail="Loadout observation is unreadable."
            )
    return engineering_workbench.loadout_baseline(event)


@router.get("/workbench/hulls/{hull_id}")
async def get_catalogue_workbench(hull_id: str) -> dict[str, Any]:
    """Open an unowned hull without persisting or changing local telemetry."""
    factory = _ensure_session_factory()
    catalog = await engineering_catalog.active_catalog(factory)
    if catalog is None:
        raise HTTPException(
            status_code=422, detail="A validated local catalogue is required."
        )
    try:
        baseline = engineering_workbench.catalogue_baseline(catalog, hull_id)
    except ValueError as exc:
        raise _http_422(exc) from exc
    workbench = engineering_workbench.build_observed_workbench(baseline, [], catalog)
    workbench.pop("_catalog", None)
    return {
        "workbench": workbench,
        "truth_class": "commander_planned_reference",
        "live_ship_changed": False,
    }


@router.get("/workbench/observations/{observation_id}")
async def get_observed_workbench(observation_id: int) -> dict[str, Any]:
    baseline = await _observation_baseline(observation_id)
    factory = _ensure_session_factory()
    catalog = await engineering_catalog.active_catalog(factory)
    recipes = await engineering_progression.observed_recipes(factory)
    workbench = engineering_workbench.build_observed_workbench(
        baseline, recipes, catalog
    )
    workbench.pop("_catalog", None)
    return {
        "workbench": workbench,
        "observation_id": observation_id,
        "truth_class": "commander_observed",
        "live_ship_changed": False,
    }


async def _saved_baseline(
    build_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    factory = _ensure_session_factory()
    build = next(
        (
            b
            for b in await engineering.list_build_plans(factory)
            if b.build_plan_id == build_id
        ),
        None,
    )
    if build is None or not isinstance(
        build.target_loadout_summary.get("observed_baseline"), dict
    ):
        raise HTTPException(
            status_code=422,
            detail="Saved observation is unavailable; select the "
            "current observed ship.",
        )
    summary = build.target_loadout_summary
    catalogs = await engineering_catalog.catalogs_by_version(factory)
    return summary["observed_baseline"], catalogs.get(
        summary.get("catalog_version", "")
    )


@router.post("/workbench/power-proposal")
async def propose_power_plan(body: WorkbenchPreviewRequest) -> dict[str, Any]:
    preview = await preview_workbench_build(body)
    errors = preview["performance"].get("configuration_check", {}).get("errors", [])
    if errors:
        return {"state": "invalid_configuration", "reason": " ".join(errors)}
    return await asyncio.to_thread(
        ship_power.propose, preview["performance"]["power_management"]
    )


@router.get("/workbench/power-plant-variants")
async def get_power_plant_variants(
    baseline_build_id: str | None = None,
    baseline_observation_id: int | None = None,
) -> dict[str, Any]:
    if baseline_build_id and baseline_observation_id:
        raise HTTPException(
            status_code=422, detail="Choose one ship observation or saved variant."
        )
    factory = _ensure_session_factory()
    live_state = _state_manager.public_snapshot() if _state_manager is not None else {}
    catalog = await engineering_catalog.active_catalog(factory)
    if baseline_build_id:
        live_state, catalog = await _saved_baseline(baseline_build_id)
    elif baseline_observation_id:
        live_state = await _observation_baseline(baseline_observation_id)
    recipes = await engineering_progression.observed_recipes(factory)
    return await asyncio.to_thread(
        engineering_workbench.power_plant_variants, live_state, recipes, catalog
    )


@router.get("/catalog")
async def get_catalog() -> dict[str, Any]:
    """Return the active local reference pack for the offline build designer."""
    active = await engineering_catalog.active_catalog(_ensure_session_factory())
    return engineering_catalog.designer_catalog(active)


@router.post("/catalog/local-power-plants")
@router.post("/catalog/local-outfitting")
async def enable_local_outfitting_reference(
    body: ReferenceDownloadRequest,
) -> dict[str, Any]:
    """Explicit private reference download; never uploads local commander data."""
    if not body.private_use_confirmed:
        raise HTTPException(
            status_code=422,
            detail="Confirm private non-commercial reference use before downloading.",
        )
    factory = _ensure_session_factory()
    retained = await engineering_catalog.catalogs_by_version(factory)
    key = f"{engineering_reference.CATALOG_ID}@{engineering_reference.VERSION}"
    try:
        catalog = retained.get(key)
        if catalog is None:
            catalog = await engineering_reference.download_reference()
        # Reuse the existing canonical store and activation semantics.
        result = await engineering_catalog.import_catalog(factory, catalog)
    except (ValueError, OSError, TimeoutError) as exc:
        if _activity_log is not None:
            _activity_log.append(
                ActivityEntry(
                    event_type=ENGINEERING_SOURCE_ATTEMPT_FAILED,
                    source="engineering",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    summary="Private outfitting reference could not be enabled",
                    payload={
                        "source_url": engineering_reference.SOURCE_URL,
                        "commander_data_sent": False,
                    },
                )
            )
        raise HTTPException(
            status_code=422,
            detail=f"Reference could not be enabled; existing data preserved. {exc}",
        ) from exc
    if _activity_log is not None:
        _activity_log.append(
            ActivityEntry(
                event_type=ENGINEERING_CATALOG_IMPORTED,
                source="engineering",
                summary="Commander enabled private local outfitting reference",
                timestamp=datetime.now(timezone.utc).isoformat(),
                payload={
                    "catalog_id": result["catalog_id"],
                    "version": result["version"],
                    "source_url": engineering_reference.SOURCE_URL,
                    "commander_data_sent": False,
                    "outbound_call_executed": key not in retained,
                },
            )
        )
    return result


@router.post("/catalog/import", status_code=status.HTTP_201_CREATED)
async def import_catalog(body: CatalogImportRequest) -> dict[str, Any]:
    """Validate and persist a Commander-authorized local reference pack."""
    if not body.rights_attested:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Confirm that you may use this local reference pack and that "
                "its provenance and licence fields are accurate."
            ),
        )
    try:
        result = await engineering_catalog.import_catalog(
            _ensure_session_factory(), body.catalog
        )
    except (TypeError, ValueError) as exc:
        raise _http_422(ValueError(str(exc))) from exc
    event_id = str(uuid4())
    if _activity_log is not None:
        _activity_log.append(
            ActivityEntry(
                event_type=ENGINEERING_CATALOG_IMPORTED,
                timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                summary="Local Engineering reference pack imported",
                payload={
                    "catalog_id": result["catalog_id"],
                    "version": result["version"],
                    "sha256": result["sha256"],
                    "hull_count": result["hull_count"],
                    "module_count": result["module_count"],
                    "outbound_call_executed": False,
                },
                source_chain=[
                    {
                        "source": result["provenance"]["source_name"],
                        "truth_class": "commander_supplied_reference",
                    }
                ],
                redaction_state="metadata_only",
                is_fact=False,
                linked_entity_refs={"catalog_id": result["catalog_id"]},
                surface_origin="engineering",
                correlation_id=event_id,
                event_id=event_id,
                source="commander_local_import",
            )
        )
    return result


@router.post("/progression/{build_plan_id}/acknowledge-ready")
async def acknowledge_progression_ready(build_plan_id: str) -> dict[str, Any]:
    """Record an explicit Commander acknowledgement; never imply telemetry."""
    factory = _ensure_session_factory()
    build = next(
        (
            item
            for item in await engineering.list_build_plans(factory)
            if item.build_plan_id == build_plan_id
        ),
        None,
    )
    if build is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Build not found"
        )
    updated_build = await engineering.update_build_plan(
        factory,
        build_plan_id,
        {"state": "complete", "notes": "Commander acknowledged readiness."},
        activity_log=_activity_log,
    )
    updated_goals = []
    for goal in await engineering.list_goals(factory):
        if goal.linked_build_plan_id != build_plan_id or goal.state == "archived":
            continue
        updated = await engineering.update_goal(
            factory,
            goal.goal_id,
            {"state": "complete", "notes": "Commander acknowledged readiness."},
            activity_log=_activity_log,
        )
        if updated is not None:
            updated_goals.append(_goal_payload(updated))
    return {
        "status": "commander_acknowledged",
        "build": _build_payload(updated_build) if updated_build is not None else None,
        "goals": updated_goals,
        "observed_completion": False,
    }


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
        _reject_unvalidated_module_targets(body.target_loadout_summary)
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
    protected = {
        "target_ship",
        "target_loadout_summary",
        "source",
        "format_verification_state",
    }
    if protected & body.model_fields_set:
        existing = next(
            (
                build
                for build in await engineering.list_build_plans(
                    _ensure_session_factory()
                )
                if build.build_plan_id == build_plan_id
            ),
            None,
        )
        if existing is not None and "module_targets" in existing.target_loadout_summary:
            raise HTTPException(
                status_code=422,
                detail="Use the outfitting editor to create a revalidated variant; "
                "a canonical build's ship, targets and provenance cannot be replaced "
                "through manual build updates.",
            )
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
        try:
            _reject_unvalidated_module_targets(body.target_loadout_summary)
        except ValueError as exc:
            raise _http_422(exc) from exc
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
    factory = _ensure_session_factory()
    rows = await engineering.list_material_gaps(factory)
    # ``inventory_state`` below describes the manual planning rows only; the
    # reconciled Journal inventory is reported beside it, never merged in.
    journal = await engineering_progression.horizons_inventory(factory)
    if not rows:
        snapshot = engineering.material_gap_empty_snapshot()
        snapshot["journal_inventory_state"] = journal["state"]
        return snapshot
    return {
        "surface_state": "manual_planning",
        "inventory_state": "manual_or_not_loaded",
        "journal_inventory_state": journal["state"],
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
