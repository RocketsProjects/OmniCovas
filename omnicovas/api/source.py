"""Source infrastructure API — read-only inspection endpoints.

Provides:
  GET /source/health         — registry health snapshot for all sources
  GET /source/plan/{wf_id}   — last WorkflowSourcePlan for a workflow_id

All endpoints are read-only. No mutation, no outbound calls, no provider
activation. The plan index is populated by callers via register_plan(); it
is in-memory and inspection-only.

Authority:
    Backend Blueprint v1.0 — API/bridge contracts
    PB05-02 Stage E — read-only inspection surfaces only
    ADR 0003 — no unsafe rendering (N/A: backend API only)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict

from omnicovas.core.source_plan import WorkflowSourcePlan
from omnicovas.core.source_registry import (
    SourceMetadata,
    SourceRegistry,
    SourceState,
)

router = APIRouter(prefix="/source", tags=["source"])

# ---------------------------------------------------------------------------
# Injected state — set at application startup; never mutated by endpoints
# ---------------------------------------------------------------------------

_registry: SourceRegistry | None = None
_plan_index: dict[str, WorkflowSourcePlan] = {}


def set_source_registry(registry: SourceRegistry | None) -> None:
    """Inject the shared SourceRegistry into this router."""
    global _registry  # noqa: PLW0603
    _registry = registry


def register_plan(plan: WorkflowSourcePlan) -> None:
    """Record a WorkflowSourcePlan in the in-memory plan index.

    Called by SourceRouter users after resolving a plan. The plan index
    is not an endpoint — it is populated internally and read via the API.
    Most recent plan for a given workflow_id replaces any prior entry.
    """
    _plan_index[plan.workflow_id] = plan


def _ensure_registry() -> SourceRegistry:
    if _registry is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Source registry not initialized",
        )
    return _registry


# ---------------------------------------------------------------------------
# Response models — read-only; extra="forbid" per repo convention
# ---------------------------------------------------------------------------


class SourceHealthEntryResponse(BaseModel):
    """Health snapshot for a single registered source."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    display_name: str
    description: str
    state: str
    is_local: bool
    requires_auth: bool
    requires_consent: bool
    capabilities: list[str]
    metadata: dict[str, str | bool | list[str]]
    health_available: bool
    last_checked: str | None
    last_success: str | None
    error_count: int
    is_available: bool


class SourceHealthSnapshotResponse(BaseModel):
    """Full registry health snapshot."""

    model_config = ConfigDict(extra="forbid")

    sources: list[SourceHealthEntryResponse]
    total_count: int
    enabled_count: int


class WorkflowSourcePlanResponse(BaseModel):
    """Read-only view of a WorkflowSourcePlan."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str
    call_type: str
    primary_source_id: str | None
    fallback_decision: str
    requires_auth: bool
    requires_consent: bool
    nullprovider_safe: bool
    notes: str
    created_at: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health", response_model=SourceHealthSnapshotResponse)
async def get_source_health() -> SourceHealthSnapshotResponse:
    """Return a read-only health snapshot for all registered sources.

    capability_known_to_registry != implemented_provider_call.
    """
    registry = _ensure_registry()
    definitions = registry.list_all()
    entries: list[SourceHealthEntryResponse] = []
    enabled_count = 0

    for defn in definitions:
        health = registry.get_health(defn.source_id)
        if defn.state == SourceState.ENABLED:
            enabled_count += 1
        entries.append(
            SourceHealthEntryResponse(
                source_id=defn.source_id,
                display_name=defn.display_name,
                description=defn.description,
                state=defn.state.value,
                is_local=defn.is_local,
                requires_auth=defn.requires_auth,
                requires_consent=defn.requires_consent,
                capabilities=[
                    cap.value
                    for cap in sorted(defn.capabilities, key=lambda c: c.value)
                ],
                metadata=_metadata_response(defn.metadata),
                health_available=health is not None,
                last_checked=health.last_checked.isoformat()
                if health and health.last_checked
                else None,
                last_success=health.last_success.isoformat()
                if health and health.last_success
                else None,
                error_count=health.error_count if health else 0,
                is_available=health.is_available if health else False,
            )
        )

    return SourceHealthSnapshotResponse(
        sources=entries,
        total_count=len(entries),
        enabled_count=enabled_count,
    )


def _metadata_response(metadata: SourceMetadata) -> dict[str, str | bool | list[str]]:
    """Return JSON-safe source metadata for read-only API consumers."""
    response: dict[str, str | bool | list[str]] = {}
    for key, value in metadata.items():
        response[key] = list(value) if isinstance(value, tuple) else value
    return response


@router.get("/plan/{workflow_id}", response_model=WorkflowSourcePlanResponse)
async def get_workflow_plan(workflow_id: str) -> WorkflowSourcePlanResponse:
    """Return the last WorkflowSourcePlan recorded for workflow_id.

    Plans are recorded via register_plan(). Returns 404 if no plan is held.
    This endpoint is read-only inspection; it does not trigger any source call.
    """
    plan = _plan_index.get(workflow_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No plan found for workflow_id: {workflow_id!r}",
        )
    return WorkflowSourcePlanResponse(
        workflow_id=plan.workflow_id,
        call_type=plan.call_type,
        primary_source_id=plan.primary_source_id,
        fallback_decision=plan.fallback_decision.value,
        requires_auth=plan.requires_auth,
        requires_consent=plan.requires_consent,
        nullprovider_safe=plan.nullprovider_safe,
        notes=plan.notes,
        created_at=plan.created_at.isoformat(),
    )
