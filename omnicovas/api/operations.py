"""Operations API: exploration/exobiology snapshot and Phase 9 campaign endpoints.

PB05-08: exploration/exobiology read-only snapshot.
PB09-03: local-only campaign workflow (BGS / Powerplay)
    under /operations/phase9/campaigns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityLog
from omnicovas.core.confirmation_gate import ConfirmationGate
from omnicovas.features import campaign as campaign_feature
from omnicovas.features import operations_exploration

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

router = APIRouter(prefix="/operations", tags=["operations"])

_state: StateManager | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_activity_log: ActivityLog | None = None
_gate: ConfirmationGate = ConfirmationGate()
_ai_provider: Any = None


def set_state_manager(state: StateManager) -> None:
    """Inject the live StateManager into this router."""
    global _state  # noqa: PLW0603
    _state = state


def set_session_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    """Inject the live async session factory into this router."""
    global _session_factory  # noqa: PLW0603
    _session_factory = session_factory


def set_activity_log(activity_log: ActivityLog | None) -> None:
    """Inject the shared ActivityLog used for campaign write audit entries."""
    global _activity_log  # noqa: PLW0603
    _activity_log = activity_log


def set_confirmation_gate(gate: ConfirmationGate | None) -> None:
    """Inject the canonical ConfirmationGate (runtime: from ApiBridge; tests: override).

    ApiBridge calls this during startup to wire the application-level gate.
    Tests may call it to inject auto_approve=False for gate-cancellation coverage.
    A module-level default (auto_approve=True) remains as a safe fallback only.
    """
    global _gate  # noqa: PLW0603
    if gate is not None:
        _gate = gate


def set_ai_provider(ai_provider: Any) -> None:
    """Inject an AI provider (tests only; production default is None/NullProvider)."""
    global _ai_provider  # noqa: PLW0603
    _ai_provider = ai_provider


def _ensure_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Operations campaign persistence not initialized",
        )
    return _session_factory


class ActiveRouteRefResponse(BaseModel):
    """Public minimal active route reference for Operations exploration."""

    model_config = ConfigDict(extra="forbid")

    destination: str | None
    total_hops: int | None
    freshness_label: str
    fallback: str | None


class ExplorationObjectiveResponse(BaseModel):
    """Public exploration objective payload."""

    model_config = ConfigDict(extra="forbid")

    objective_id: str
    kind: str
    label: str
    state: str
    fallback: str | None
    source_id: str


class ExobiologyChecklistItemResponse(BaseModel):
    """Public exobiology checklist item payload."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    label: str
    state: str
    caveat: str | None


class OperationsExplorationBlockerResponse(BaseModel):
    """Public exploration blocker payload."""

    model_config = ConfigDict(extra="forbid")

    blocker_id: str
    label: str
    kind: str
    source_id: str | None


class OperationsExplorationSnapshotResponse(BaseModel):
    """Public Operations exploration/exobiology snapshot payload."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    session_status: str
    active_route_ref: ActiveRouteRefResponse | None
    objectives: list[ExplorationObjectiveResponse]
    checklist: list[ExobiologyChecklistItemResponse]
    blockers: list[OperationsExplorationBlockerResponse]
    handoffs: dict[str, str]
    unsupported_notes: list[str]
    nullprovider_safe: bool
    fallback: str | None


# ---------------------------------------------------------------------------
# Phase 9 campaign request models (PB09-03)
# ---------------------------------------------------------------------------


class CampaignCreateRequest(BaseModel):
    """Commander-entered campaign objective creation request."""

    model_config = ConfigDict(extra="forbid")

    workflow_type: str = Field(min_length=1, max_length=16)
    title: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    target_subject: str | None = Field(default=None, max_length=128)
    target_system: str | None = Field(default=None, max_length=128)
    state: str = Field(default="proposed", max_length=16)


class CampaignPatchRequest(BaseModel):
    """Allowed campaign objective patch fields."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    target_subject: str | None = Field(default=None, max_length=128)
    target_system: str | None = Field(default=None, max_length=128)
    blockers: list[str] | None = None
    next_actions: list[str] | None = None


class CampaignStateRequest(BaseModel):
    """Campaign state transition request."""

    model_config = ConfigDict(extra="forbid")

    state: str = Field(min_length=1, max_length=16)


class LinkIntelFactRequest(BaseModel):
    """Link or unlink an Intel fact id from a campaign."""

    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(min_length=1, max_length=128)
    link: bool = Field(default=True)


class LinkNavigationCircuitRequest(BaseModel):
    """Link or unlink a Navigation circuit id from a campaign."""

    model_config = ConfigDict(extra="forbid")

    circuit_id: str = Field(min_length=1, max_length=128)
    link: bool = Field(default=True)


class CampaignArchiveResponse(BaseModel):
    """Archive (soft-delete) response for campaign objectives."""

    model_config = ConfigDict(extra="forbid")

    status: str
    campaign_id: str


# ---------------------------------------------------------------------------
# Phase 9 campaign payload helpers
# ---------------------------------------------------------------------------


def _dt(value: Any) -> str | None:
    """Serialize datetime to ISO 8601 string or None."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def _campaign_payload(record: campaign_feature.CampaignRecord) -> dict[str, Any]:
    """Serialise a CampaignRecord to a public API payload dict."""
    return {
        "campaign_id": record.campaign_id,
        "workflow_type": record.workflow_type,
        "title": record.title,
        "description": record.description,
        "target_subject": record.target_subject,
        "target_system": record.target_system,
        "state": record.state,
        "blockers": record.blockers,
        "next_actions": record.next_actions,
        "linked_intel_facts": record.linked_intel_facts,
        "linked_navigation_circuits": record.linked_navigation_circuits,
        "ai_draft_history": record.ai_draft_history,
        "source_chain": [
            {
                "source": "commander_entered",
                "truth_class": "commander_entered",
                "freshness": "manual",
            }
        ],
        "nullprovider_safe": True,
        "is_fact": False,
        "created_at": _dt(record.created_at),
        "updated_at": _dt(record.updated_at),
        "archived_at": _dt(record.archived_at),
    }


def _http_422(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


# ---------------------------------------------------------------------------
# Existing exploration endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/exploration/snapshot", response_model=OperationsExplorationSnapshotResponse
)
async def get_exploration_snapshot() -> dict[str, Any]:
    """Return the current Operations exploration/exobiology active objectives snapshot.

    Local-only. No outbound provider call. Exobiology value/species/body/
    first-footfall facts remain No Verified Source or Unsupported.
    Operations owns active objectives; Intel owns facts; Navigation owns routes.
    """
    return operations_exploration.snapshot_payload()


# ---------------------------------------------------------------------------
# Phase 9 campaign endpoints  (PB09-03)
# ---------------------------------------------------------------------------
# All endpoints are local-only. No outbound provider calls. No AI facts.
# DELETE = soft archive only. is_fact=False in all AI draft responses.
# ---------------------------------------------------------------------------


@router.post(
    "/phase9/campaigns",
    status_code=status.HTTP_201_CREATED,
)
async def create_phase9_campaign(body: CampaignCreateRequest) -> dict[str, Any]:
    """Create a local campaign objective (BGS or Powerplay workflow).

    Local-only. No outbound behavior. Initial state defaults to 'proposed'.
    """
    try:
        record = await campaign_feature.create_campaign(
            _ensure_session_factory(),
            campaign_feature.CampaignCreate(
                workflow_type=body.workflow_type,
                title=body.title,
                description=body.description,
                target_subject=body.target_subject,
                target_system=body.target_system,
                state=body.state,
            ),
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    return _campaign_payload(record)


@router.get("/phase9/campaigns")
async def list_phase9_campaigns(
    workflow_type: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """List local campaign objectives with optional workflow_type / state filters."""
    try:
        records = await campaign_feature.list_campaigns(
            _ensure_session_factory(),
            workflow_type=workflow_type,
            state=state,
            limit=limit,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    return {
        "campaigns": [_campaign_payload(r) for r in records],
        "nullprovider_safe": True,
        "is_fact": False,
    }


@router.get("/phase9/campaigns/{campaign_id}")
async def get_phase9_campaign(campaign_id: str) -> dict[str, Any]:
    """Fetch a single local campaign objective by ID."""
    record = await campaign_feature.get_campaign(
        _ensure_session_factory(),
        campaign_id,
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _campaign_payload(record)


@router.patch("/phase9/campaigns/{campaign_id}")
async def update_phase9_campaign(
    campaign_id: str,
    body: CampaignPatchRequest,
) -> dict[str, Any]:
    """Update allowed fields on a local campaign objective."""
    changes: campaign_feature.CampaignUpdate = {}
    if "title" in body.model_fields_set and body.title is not None:
        changes["title"] = body.title
    if "description" in body.model_fields_set:
        changes["description"] = body.description
    if "target_subject" in body.model_fields_set:
        changes["target_subject"] = body.target_subject
    if "target_system" in body.model_fields_set:
        changes["target_system"] = body.target_system
    if "blockers" in body.model_fields_set and body.blockers is not None:
        changes["blockers"] = body.blockers
    if "next_actions" in body.model_fields_set and body.next_actions is not None:
        changes["next_actions"] = body.next_actions
    try:
        record = await campaign_feature.update_campaign(
            _ensure_session_factory(),
            campaign_id,
            changes,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _campaign_payload(record)


@router.post("/phase9/campaigns/{campaign_id}/state")
async def set_phase9_campaign_state(
    campaign_id: str,
    body: CampaignStateRequest,
) -> dict[str, Any]:
    """Transition a campaign objective to a new allowed state.

    State machine: proposed→active, active→blocked/completed/archived,
    blocked→active/archived, completed→archived. 'archived' is terminal.
    Returns HTTP 422 for disallowed transitions.
    """
    try:
        record = await campaign_feature.transition_state(
            _ensure_session_factory(),
            campaign_id,
            body.state,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _campaign_payload(record)


@router.post("/phase9/campaigns/{campaign_id}/links/intel")
async def link_phase9_campaign_intel(
    campaign_id: str,
    body: LinkIntelFactRequest,
) -> dict[str, Any]:
    """Link or unlink a local Intel fact id to a campaign objective.

    Weak link (no FK constraint). fact_id is a string reference only.
    link=true attaches; link=false removes.
    """
    try:
        record = await campaign_feature.link_intel_fact(
            _ensure_session_factory(),
            campaign_id,
            body.fact_id,
            link=body.link,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _campaign_payload(record)


@router.post("/phase9/campaigns/{campaign_id}/links/navigation")
async def link_phase9_campaign_navigation(
    campaign_id: str,
    body: LinkNavigationCircuitRequest,
) -> dict[str, Any]:
    """Link or unlink a local Navigation circuit id to a campaign objective.

    Weak link (no FK constraint). Navigation circuit model deferred to PB09-04.
    circuit_id is a string reference only.
    link=true attaches; link=false removes.
    """
    try:
        record = await campaign_feature.link_navigation_circuit(
            _ensure_session_factory(),
            campaign_id,
            body.circuit_id,
            link=body.link,
            activity_log=_activity_log,
        )
    except ValueError as exc:
        raise _http_422(exc) from exc
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _campaign_payload(record)


@router.post("/phase9/campaigns/{campaign_id}/ai-draft")
async def request_phase9_campaign_ai_draft(campaign_id: str) -> dict[str, Any]:
    """Request an AI campaign planning draft (Phase 9 NullProvider baseline).

    Confirmation Gate required. is_fact=False always.
    Phase 9 default: NullProvider path (status=nullprovider, draft_text=None).
    No outbound provider calls. No AI facts. No merit values. No tick times.
    source_chain returned even in nullprovider path.
    """
    result = await campaign_feature.request_ai_draft(
        _ensure_session_factory(),
        campaign_id,
        ai_provider=_ai_provider,
        gate=_gate,
        activity_log=_activity_log,
    )
    if result.status == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return {
        "campaign_id": result.campaign_id,
        "status": result.status,
        "draft_text": result.draft_text,
        "is_fact": result.is_fact,
        "source_chain": result.source_chain,
        "kb_references": result.kb_references,
        "confidence_label": result.confidence_label,
        "nullprovider_safe": True,
        "nullprovider_message": result.nullprovider_message,
        "validation_status": "failed" if result.status == "validation_failed" else None,
        "validation_error": result.validation_error,
    }


@router.delete(
    "/phase9/campaigns/{campaign_id}",
    response_model=CampaignArchiveResponse,
)
async def archive_phase9_campaign(campaign_id: str) -> CampaignArchiveResponse:
    """Soft-archive a campaign objective. No hard delete path.

    Sets state='archived', archived_at=now. Row is retained in DB.
    Returns HTTP 404 if not found. Returns HTTP 200 if already archived
    (idempotent archive is acceptable — caller should check state via GET).
    """
    archived = await campaign_feature.archive_campaign(
        _ensure_session_factory(),
        campaign_id,
        activity_log=_activity_log,
    )
    if not archived:
        # Either not found or already archived. Check which case.
        record = await campaign_feature.get_campaign(
            _ensure_session_factory(),
            campaign_id,
        )
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        # Already archived — return 200 with current state
        return CampaignArchiveResponse(
            status="already_archived", campaign_id=campaign_id
        )
    return CampaignArchiveResponse(status="archived", campaign_id=campaign_id)
