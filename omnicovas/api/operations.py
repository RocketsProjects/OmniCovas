"""Operations API: exploration snapshot, campaigns, and Commander objectives.

PB05-08: exploration/exobiology read-only snapshot.
PB09-03: local-only campaign workflow (BGS / Powerplay)
    under /operations/phase9/campaigns.
PB14-R1: the Commander objective lifecycle under /operations/objectives.
    Operations owns this domain: an objective is workflow intent, not an Intel
    fact and not a Dashboard concern, so it is neither routed through nor
    stored by either. Setting a first objective is an ordinary write; changing,
    completing, clearing and destroying one are protected actions and go
    through the shared Week 13 Confirmation Gate.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.api import week13
from omnicovas.core.activity_log import ActivityLog
from omnicovas.core.confirmation_gate import ConfirmationGate
from omnicovas.core.event_types import (
    OPERATIONS_OBJECTIVE_PROPOSAL_BLOCKED,
    OPERATIONS_OBJECTIVE_PROPOSAL_CANCELED,
    OPERATIONS_OBJECTIVE_PROPOSAL_CONFIRMED,
    OPERATIONS_OBJECTIVE_PROPOSAL_SHOWN,
    PHASE_9_CAMPAIGN_ACTION_BLOCKED_GATE,
    PHASE_9_CAMPAIGN_ACTION_CANCELED_GATE,
    PHASE_9_CAMPAIGN_ACTION_CONFIRMED_GATE,
    PHASE_9_CAMPAIGN_ACTION_GATE_SHOWN,
)
from omnicovas.features import campaign as campaign_feature
from omnicovas.features import operations_combat_workflow as combat_workflow
from omnicovas.features import operations_exploration
from omnicovas.features import operations_handoff as handoff_feature
from omnicovas.features import operations_mining_workflow as mining_workflow
from omnicovas.features import operations_objectives as objectives_feature
from omnicovas.features import operations_trade_workflow as trade_workflow
from omnicovas.features.operations_objectives import (
    OBJECTIVE_MAX_LENGTH,
    ObjectiveConflict,
    ObjectiveError,
    OperationsObjectiveService,
)

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

router = APIRouter(prefix="/operations", tags=["operations"])

_state: StateManager | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_activity_log: ActivityLog | None = None
# PB10-R6: the module-level fallback denies. Only an explicitly injected
# gate (ApiBridge at startup, or a test) can resolve anything, and even an
# advisory gate authorises drafting only — never an action.
_gate: ConfirmationGate = ConfirmationGate.denying()
_ai_provider: Any = None
_objectives: OperationsObjectiveService | None = None
_mining_prospector: Any = None


def set_mining_prospector(service: Any) -> None:
    global _mining_prospector  # noqa: PLW0603
    _mining_prospector = service


# PB14-R1: change / complete / clear / purge are protected. They reuse the one
# shared Week 13 confirmation queue rather than introducing a second gate:
# `ConfirmationGate` itself documents that commander-facing confirmation is
# owned by that queue and its two-step propose/authorize flow.
OBJECTIVE_ACTION_TYPE = "operations_objective_protected_action"
week13.register_outcome_action_type(
    OBJECTIVE_ACTION_TYPE,
    confirmed_event=OPERATIONS_OBJECTIVE_PROPOSAL_CONFIRMED,
    canceled_event=OPERATIONS_OBJECTIVE_PROPOSAL_CANCELED,
    blocked_event=OPERATIONS_OBJECTIVE_PROPOSAL_BLOCKED,
)

_OBJECTIVE_PROPOSAL_TTL_SECONDS = 300
_MAX_PENDING_OBJECTIVE_ACTIONS = 8
_pending_objective_actions: dict[str, dict[str, Any]] = {}

# Phase 14 R8 (`P14-O02` / `P14-K05`): campaign protected transitions reuse the
# SAME Week 13 queue as objectives. `P14-O02`'s finding was not that campaigns
# were unsafe — every mutation was already soft, reversible and logged — but
# that Operations held two different gate policies for one class of action.
# One queue, one policy.
CAMPAIGN_ACTION_TYPE = "operations_campaign_protected_action"
week13.register_outcome_action_type(
    CAMPAIGN_ACTION_TYPE,
    confirmed_event=PHASE_9_CAMPAIGN_ACTION_CONFIRMED_GATE,
    canceled_event=PHASE_9_CAMPAIGN_ACTION_CANCELED_GATE,
    blocked_event=PHASE_9_CAMPAIGN_ACTION_BLOCKED_GATE,
)

GATE_REQUIRED_DETAIL = (
    "This is a protected campaign transition. Propose it at "
    "/operations/phase9/campaigns/actions/propose and authorize the "
    "Commander's decision."
)

_CAMPAIGN_PROPOSAL_TTL_SECONDS = 300
_MAX_PENDING_CAMPAIGN_ACTIONS = 8
_pending_campaign_actions: dict[str, dict[str, Any]] = {}

#: States a campaign cannot be moved into without a Commander decision.
#: `completed` is COMPLETE and `archived` is CLEAR_ARCHIVE_DELETE in the R8
#: matrix. `active` and `blocked` are ordinary reversible workflow progression
#: and stay ungated — gating them would be a modal on every button, which the
#: R8 ruling explicitly forbids.
PROTECTED_CAMPAIGN_STATES: frozenset[str] = frozenset({"completed", "archived"})

#: Patch fields whose replacement is a material overwrite of Commander-authored
#: state. `blockers` and `next_actions` are workflow annotations, additive in
#: practice and trivially re-entered, so they stay ungated.
MATERIAL_CAMPAIGN_FIELDS: tuple[str, ...] = (
    "title",
    "description",
    "target_subject",
    "target_system",
)


def set_objective_service(service: OperationsObjectiveService | None) -> None:
    """Inject the one Commander objective service built by the bridge."""
    global _objectives  # noqa: PLW0603
    _objectives = service


def reset_objective_pending_actions() -> None:
    """Clear pending objective proposals. Test seam; not an HTTP surface."""
    _pending_objective_actions.clear()


def reset_campaign_pending_actions() -> None:
    """Clear pending campaign proposals. Test seam; not an HTTP surface."""
    _pending_campaign_actions.clear()


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
    Tests may inject a denying gate for gate-cancellation coverage.

    PB10-R6: the module-level fallback is `GatePolicy.DENY`, so a router that
    was never wired refuses rather than approving.
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
    owner: str = "derived"
    target: str | None = None
    target_kind: str | None = None


class ExobiologyChecklistItemResponse(BaseModel):
    """Public exobiology checklist item payload."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    label: str
    state: str
    caveat: str | None
    evidence: str | None = None
    source_event: str | None = None


class OperationsExplorationBlockerResponse(BaseModel):
    """Public exploration blocker payload."""

    model_config = ConfigDict(extra="forbid")

    blocker_id: str
    label: str
    kind: str
    source_id: str | None
    detail: str | None = None
    condition_id: str | None = None


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
    # Phase 14 R5. Deliberately an open mapping rather than a mirrored model:
    # every value inside is already source-labelled by the workflow builder, and
    # restating that structure here would create a second place for the truth
    # classes to drift out of step.
    workflow: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Phase 9 campaign request models (PB09-03)
# ---------------------------------------------------------------------------


class HandoffProofRequest(BaseModel):
    """One purposeful Operations workflow handoff, described in slugs only.

    `extra="forbid"` is the first privacy control: a caller cannot smuggle an
    objective sentence, a campaign title or a prompt into the log by adding a
    field. The second is in `operations_handoff.build_payload`, which drops
    anything that is not a conservative slug.

    Deliberately absent: `target_label`, `reason` and `target_query`. All three
    are free text in the RouteTransferIntent grammar, and one of them (a
    campaign title) can be Commander-authored. The handoff is proved by its
    structured identity, not by its human wording.
    """

    model_config = ConfigDict(extra="forbid")

    origin_package: str = Field(min_length=1, max_length=32)
    target_route: str = Field(min_length=1, max_length=64)
    origin_section_id: str | None = Field(default=None, max_length=128)
    target_section_id: str | None = Field(default=None, max_length=128)
    target_entity_kind: str | None = Field(default=None, max_length=64)
    target_entity_id: str | None = Field(default=None, max_length=128)
    handoff_kind: str | None = Field(default=None, max_length=64)
    workflow_id: str | None = Field(default=None, max_length=128)


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


class CampaignActionProposal(BaseModel):
    """Exact protected campaign transition to retain server-side.

    The replacement values are held by the SERVER between propose and
    authorize, exactly as R3 holds objective text, so the campaign the
    Commander confirmed is the campaign that lands.
    """

    model_config = ConfigDict(extra="forbid")

    action: Literal["update", "complete", "archive"]
    campaign_id: str = Field(min_length=1, max_length=64)
    #: `update` only.
    title: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=4000)
    target_subject: str | None = Field(default=None, max_length=128)
    target_system: str | None = Field(default=None, max_length=128)


class CampaignAuthorizationRequest(BaseModel):
    """Server-issued proposal id; carries no client-authored approval flag."""

    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=1, max_length=128)


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
    """Return the current Operations exploration/exobiology workflow snapshot.

    Local-only. No outbound provider call. Exobiology value and first-footfall
    remain No Verified Source or Unknown; observed biology is fact and candidate
    biology stays a prediction. Operations owns the workflow; Intel owns facts;
    Navigation owns routes.

    Phase 14 R5: the snapshot now carries a workflow stage, evidence-advanced
    checklist, work remaining and completion readiness, all derived from this
    machine's journal history for the system the Commander is actually in. A
    router that was never wired reports the workflow unavailable rather than
    reporting an empty exploration.
    """
    star_system = None
    if _state is not None:
        star_system = getattr(_state.snapshot, "current_system", None)
    return await operations_exploration.workflow_snapshot_payload(
        _session_factory,
        star_system=star_system,
    )


# ---------------------------------------------------------------------------
# Trade and Mining workflows (Phase 14 R6)
# ---------------------------------------------------------------------------
#
# Two endpoints rather than one "economy" endpoint. Trade and Mining read the
# same cargo and the same market snapshot, but they answer different questions
# and a Commander switching modes is switching workflows, not filters. Merging
# them would produce a payload where half the fields are inert in either mode.


def _active_route_destination() -> str | None:
    """Navigation's own reading of the plotted route. No second reader."""
    from omnicovas.features.navigation import build_active_route, read_navroute

    try:
        route = build_active_route(read_navroute(None))
    except Exception:  # noqa: BLE001 - an unreadable route is Unknown, not "none"
        return None
    return route.destination if route.route_state == "active" else None


@router.get("/trade/workflow")
async def get_trade_workflow() -> dict[str, Any]:
    """Return the Operations Trade workflow derived from local facts only.

    Known local cargo joined against the last observed market snapshot. No
    provider is called, no galaxy-wide price is claimed, and a snapshot from
    another station is reported as exactly that.
    """
    return await trade_workflow.build_workflow(
        _state,
        _session_factory,
        route_active=_active_route_destination() is not None,
    )


@router.get("/mining/workflow")
async def get_mining_workflow() -> dict[str, Any]:
    """Return the Operations Mining workflow derived from local facts only.

    Equipment comes from the observed loadout through the one readiness engine,
    limpets from the observed manifest, refined tonnage from recorded
    MiningRefined events. Hotspot and ring quality are not claimed at all.
    """
    objective: dict[str, Any] | None = None
    if _objectives is not None:
        try:
            objective = await _objectives.get_current("mining")
        except Exception:  # noqa: BLE001 - an unreadable store is Unknown
            objective = None
    result = await mining_workflow.build_workflow(
        _state,
        _session_factory,
        objective=objective,
        route_active=_active_route_destination() is not None,
    )
    result["prospector"] = (
        await _mining_prospector.snapshot()
        if _mining_prospector
        else {"state": "unavailable", "latest": None, "reports": []}
    )
    return result


@router.get("/combat/workflow")
async def get_combat_workflow() -> dict[str, Any]:
    """Return the Operations Combat workflow derived from local facts only.

    Reads the Phase 4 combat state, the one readiness engine and the durable
    local PvP store. Combat zone presence and intensity, and ammunition counts,
    have no verified local source and are reported as unsupported rather than
    inferred from adjacent telemetry.
    """
    objective: dict[str, Any] | None = None
    if _objectives is not None:
        try:
            objective = await _objectives.get_current("combat")
        except Exception:  # noqa: BLE001 - an unreadable store is Unknown
            objective = None
    return await combat_workflow.build_workflow(
        _state,
        _session_factory,
        objective=objective,
        route_active=_active_route_destination() is not None,
    )


@router.post("/handoff", status_code=status.HTTP_201_CREATED)
async def record_workflow_handoff(body: HandoffProofRequest) -> dict[str, Any]:
    """Prove one purposeful Operations workflow handoff. R8-9.

    Called by the cockpit when a `RouteTransferIntent` is successfully
    committed to the shell — once per handoff, never on arrival, render or
    refresh. Ordinary tab navigation does not call it at all.

    **No Confirmation Gate.** A handoff mutates nothing, sends nothing outward
    and is trivially reversible by navigating back. Logging proof does not make
    navigation destructive, and gating it would train the Commander to dismiss
    confirmations that protect nothing.
    """
    try:
        return handoff_feature.record_handoff(
            _activity_log,
            origin_package=body.origin_package,
            target_route=body.target_route,
            origin_section_id=body.origin_section_id,
            target_section_id=body.target_section_id,
            target_entity_kind=body.target_entity_kind,
            target_entity_id=body.target_entity_id,
            handoff_kind=body.handoff_kind,
            workflow_id=body.workflow_id,
        )
    except handoff_feature.HandoffError as exc:
        raise _http_422(exc) from exc


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
    # R8 gate matrix: replacing Commander-authored campaign identity is a
    # PERSISTENT_UPDATE that materially overwrites existing state. Adjusting
    # blockers or next actions is workflow annotation and stays ungated.
    material = [
        field
        for field in MATERIAL_CAMPAIGN_FIELDS
        if getattr(body, field, None) is not None
    ]
    if material:
        # Existence is checked FIRST so a missing campaign still answers 404.
        # Telling a caller to go and get a decision for a campaign that does
        # not exist would send them round a loop that cannot succeed.
        existing = await campaign_feature.get_campaign(
            _ensure_session_factory(), campaign_id
        )
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GATE_REQUIRED_DETAIL,
        )
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
    # R8 gate matrix: COMPLETE and CLEAR_ARCHIVE_DELETE need a Commander
    # decision. Moving between proposed/active/blocked does not: those are
    # reversible workflow progression, and gating them would be the modal-on-
    # every-button the ruling forbids.
    if body.state in PROTECTED_CAMPAIGN_STATES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=GATE_REQUIRED_DETAIL,
        )
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


def _log_campaign_proof(event_type: str, summary: str, payload: dict[str, Any]) -> None:
    campaign_feature.log_gate_proof(
        _activity_log, event_type=event_type, summary=summary, payload=payload
    )


def _campaign_now() -> datetime:
    return datetime.now(timezone.utc)


def _sweep_expired_campaign_actions() -> None:
    now = _campaign_now()
    for confirmation_id, record in list(_pending_campaign_actions.items()):
        if record["expires_at"] <= now:
            del _pending_campaign_actions[confirmation_id]


def _campaign_action_text(record: dict[str, Any]) -> tuple[str, str]:
    """Gate copy: what is being confirmed, and what it costs.

    The campaign TITLE is shown back to the Commander because they cannot judge
    the change without knowing which campaign it applies to. It is never written
    to the Activity Log and never leaves the machine — the same split R3 makes
    for objective text.
    """
    action = record["action"]
    title = record.get("current_title") or "this campaign"
    if action == "complete":
        return (
            f"Mark the campaign {title!r} complete?",
            "Completing records the campaign as finished. It does not complete "
            "your Commander Objective, which stays yours to decide.",
        )
    if action == "archive":
        return (
            f"Archive the campaign {title!r}?",
            "Archiving retires the campaign and is terminal — it cannot be "
            "moved back to active. The record is kept, never deleted.",
        )
    return (
        f"Replace the details of the campaign {title!r}?",
        "This overwrites campaign details you authored. The previous values are "
        "not kept.",
    )


@router.post("/phase9/campaigns/actions/propose")
async def propose_campaign_action(body: CampaignActionProposal) -> dict[str, Any]:
    """Propose a protected campaign transition. Authorizes nothing by itself."""
    _sweep_expired_campaign_actions()
    if (
        week13.count_pending_by_action_type(CAMPAIGN_ACTION_TYPE)
        >= _MAX_PENDING_CAMPAIGN_ACTIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many campaign actions are awaiting a decision.",
        )

    current = await campaign_feature.get_campaign(
        _ensure_session_factory(), body.campaign_id
    )
    if current is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    record: dict[str, Any] = {
        "action": body.action,
        "campaign_id": body.campaign_id,
        "workflow_type": current.workflow_type,
        "current_title": current.title,
    }
    if body.action == "update":
        changes = {
            field: getattr(body, field)
            for field in MATERIAL_CAMPAIGN_FIELDS
            if getattr(body, field) is not None
        }
        if not changes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="An update proposal must change at least one detail.",
            )
        record["changes"] = changes
    elif any(getattr(body, field) is not None for field in MATERIAL_CAMPAIGN_FIELDS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Campaign details are only valid when updating.",
        )

    target_state = {"complete": "completed", "archive": "archived"}.get(body.action)
    if target_state is not None:
        allowed = campaign_feature.ALLOWED_TRANSITIONS.get(current.state, frozenset())
        if target_state not in allowed:
            # Refused BEFORE a decision is requested: asking the Commander to
            # confirm something the state machine will reject is a false choice.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"A {current.state} campaign cannot move to {target_state}."),
            )

    suggestion, why = _campaign_action_text(record)
    expires_at = _campaign_now() + timedelta(seconds=_CAMPAIGN_PROPOSAL_TTL_SECONDS)
    confirmation_id = week13.enqueue_confirmation(
        suggestion_text=suggestion,
        why_text=why,
        timeout_at=expires_at.isoformat(),
        action_type=CAMPAIGN_ACTION_TYPE,
        # Display state, not proof, and deliberately carries no authored text.
        metadata={"action": body.action, "campaign_id": body.campaign_id},
    )
    record["expires_at"] = expires_at
    _pending_campaign_actions[confirmation_id] = record

    _log_campaign_proof(
        PHASE_9_CAMPAIGN_ACTION_GATE_SHOWN,
        "Protected campaign transition proposed; nothing authorized",
        {
            "campaign_id": body.campaign_id,
            "workflow_type": current.workflow_type,
            "action": body.action,
            "confirmation_id": confirmation_id,
            "authorized": False,
            "redacted": True,
        },
    )
    return {
        "status": "pending_commander_confirmation",
        "confirmation_id": confirmation_id,
        "authorized": False,
        "action": body.action,
        "campaign_id": body.campaign_id,
        "timeout_at": expires_at.isoformat(),
    }


@router.post("/phase9/campaigns/actions/authorize")
async def authorize_campaign_action(
    body: CampaignAuthorizationRequest,
) -> dict[str, Any]:
    """Spend a CONFIRMED decision and run the transition. Fail-closed."""
    _sweep_expired_campaign_actions()
    confirmation_id = body.confirmation_id
    record = _pending_campaign_actions.get(confirmation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unknown, expired, or already-used confirmation.",
        )

    outcome = week13.peek_confirmation_outcome(
        confirmation_id, expected_action_type=CAMPAIGN_ACTION_TYPE
    )
    if outcome is None:
        pending = week13.peek_pending_confirmation(
            confirmation_id, expected_action_type=CAMPAIGN_ACTION_TYPE
        )
        if pending is not None:
            return {"status": "pending_commander_confirmation", "authorized": False}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No consumable Commander decision for this confirmation.",
        )

    if outcome != week13.CONFIRMATION_OUTCOME_CONFIRMED:
        week13.consume_confirmation_outcome(
            confirmation_id, expected_action_type=CAMPAIGN_ACTION_TYPE
        )
        _pending_campaign_actions.pop(confirmation_id, None)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The campaign change was not confirmed.",
        )

    action = record["action"]
    campaign_id = record["campaign_id"]
    try:
        if action == "archive":
            archived = await _archive_campaign_authorized(campaign_id)
            result: dict[str, Any] = {
                "authorized": True,
                "action": action,
                "campaign_id": archived.campaign_id,
                "status": archived.status,
            }
        elif action == "complete":
            updated = await campaign_feature.transition_state(
                _ensure_session_factory(),
                campaign_id,
                "completed",
                activity_log=_activity_log,
            )
            if updated is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            result = {
                "authorized": True,
                "action": action,
                **_campaign_payload(updated),
            }
        else:
            updated = await campaign_feature.update_campaign(
                _ensure_session_factory(),
                campaign_id,
                record["changes"],
                activity_log=_activity_log,
            )
            if updated is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            result = {
                "authorized": True,
                "action": action,
                **_campaign_payload(updated),
            }
    except ValueError as exc:
        # The decision is deliberately NOT spent: the transition did not run,
        # so the Commander's answer is still theirs to use.
        raise _http_422(exc) from exc

    # Spend the decision only after the work succeeded, so a persistence
    # failure leaves it retriable rather than silently consumed.
    week13.consume_confirmation_outcome(
        confirmation_id, expected_action_type=CAMPAIGN_ACTION_TYPE
    )
    _pending_campaign_actions.pop(confirmation_id, None)
    return result


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
    """Refuse an ungated archive. R8 gate matrix: CLEAR_ARCHIVE_DELETE.

    Archiving is terminal — `ALLOWED_TRANSITIONS` gives `archived` no way back
    — so it is the one campaign transition a Commander cannot undo. It now
    requires a decision, spent exactly once, through the same queue that
    protects objective transitions.

    The route is kept rather than removed so a caller that has not been updated
    is told where the decision lives instead of silently doing nothing.
    """
    existing = await campaign_feature.get_campaign(
        _ensure_session_factory(), campaign_id
    )
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=GATE_REQUIRED_DETAIL,
    )


async def _archive_campaign_authorized(campaign_id: str) -> CampaignArchiveResponse:
    """Archive after a Commander decision was confirmed. Not an HTTP route."""
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


# ---------------------------------------------------------------------------
# Commander objective lifecycle  (PB14-R1)
# ---------------------------------------------------------------------------
# Operations owns this domain end to end. Local-only, no provider, no network.
# Setting a first objective is an ordinary write. Changing, completing,
# clearing and destroying one are protected: the mutation is held server-side
# and cannot execute without a Commander decision spent exactly once.
# ---------------------------------------------------------------------------

OBJECTIVE_ACTIONS = ("change", "complete", "clear", "purge_all")


class ObjectiveSetRequest(BaseModel):
    """Commander-authored objective text for one operation.

    Phase 14 R6 adds an optional structured selection alongside the sentence.
    It is never derived from the sentence: `P14-H02` asks the Commander to
    *select* a target commodity, and a selection that was parsed out of prose
    would be a guess wearing a choice's clothes.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=OBJECTIVE_MAX_LENGTH)
    target_commodity: str | None = Field(default=None, max_length=64)
    target_quantity: int | None = Field(default=None, ge=1, le=100_000)


class ObjectiveActionProposal(BaseModel):
    """Exact protected objective transition to retain server-side."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["change", "complete", "clear", "purge_all"]
    operation: str | None = Field(default=None, max_length=32)
    #: Required for `change` only. Held by the server so the text the
    #: Commander confirmed is the text that lands.
    text: str | None = Field(default=None, max_length=OBJECTIVE_MAX_LENGTH)
    #: R6: the structured selection travels with the change and through the
    #: same gate. Replacing a stated target is as much the Commander's
    #: decision as replacing the sentence, so it is not a quiet side effect.
    target_commodity: str | None = Field(default=None, max_length=64)
    target_quantity: int | None = Field(default=None, ge=1, le=100_000)


class ObjectiveAuthorizationRequest(BaseModel):
    """Server-issued proposal id; carries no client-authored approval flag."""

    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(min_length=1, max_length=128)


def _objective_service() -> OperationsObjectiveService:
    if _objectives is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Commander objectives are unavailable.",
        )
    return _objectives


def _objective_now() -> datetime:
    return datetime.now(timezone.utc)


def _sweep_expired_objective_actions() -> None:
    now = _objective_now()
    for confirmation_id, record in list(_pending_objective_actions.items()):
        if record["expires_at"] <= now:
            del _pending_objective_actions[confirmation_id]


def _objective_action_text(record: dict[str, Any]) -> tuple[str, str]:
    """Gate copy: what is being confirmed, and what it costs.

    The Commander's own objective text is shown back to them here — they are
    deciding about their own sentence and cannot judge the change without
    seeing it. It is never written to the Activity Log, and never leaves the
    machine.
    """
    action = record["action"]
    operation = record.get("operation") or "this operation"
    current = record.get("current_text")
    if action == "change":
        return (
            f"Change the {operation} objective?",
            "Current objective: "
            f"{current or 'none'}. "
            f"Proposed objective: {record.get('text') or ''}. "
            "The objective keeps its identity and its history; only the "
            "wording changes.",
        )
    if action == "complete":
        return (
            f"Mark the {operation} objective complete?",
            f"Objective: {current or 'none'}. Completion is your declaration, "
            "not something OmniCOVAS observed. The objective stays visible as "
            "completed until you clear it.",
        )
    if action == "clear":
        return (
            f"Clear the {operation} objective?",
            f"Objective: {current or 'none'}. It leaves the current slot and "
            "is kept as history, so the Activity Log proof still points at "
            "something real.",
        )
    return (
        "Destroy every Commander objective?",
        f"{record.get('objective_count', 0)} objective(s), including cleared "
        "history, would be destroyed. You wrote these; nothing in OmniCOVAS "
        "can reconstruct them. Export them first if you want a copy.",
    )


@router.get("/objectives")
async def list_operation_objectives() -> dict[str, Any]:
    """Every mode's current Commander objective. Read-only."""
    return await _objective_service().list_current()


@router.get("/objectives/export")
async def export_operation_objectives() -> dict[str, Any]:
    """Stage every objective for local download (Law 8: take your data with you)."""
    return await _objective_service().export_payload()


@router.get("/objectives/{operation}")
async def get_operation_objective(operation: str) -> dict[str, Any]:
    """The Commander objective for one mode, or an honest absence."""
    try:
        return await _objective_service().get_current(operation)
    except ObjectiveError as exc:
        raise _http_422(exc) from exc


@router.post("/objectives/{operation}", status_code=status.HTTP_201_CREATED)
async def set_operation_objective(
    operation: str, body: ObjectiveSetRequest
) -> dict[str, Any]:
    """Set the first objective for a mode. Not gated (PB14-R1 section 4).

    Stating an intention where none existed destroys nothing. Replacing one
    that already exists is refused here and must go through the gate.
    """
    service = _objective_service()
    try:
        return await service.set_first(
            operation,
            body.text,
            target_commodity=body.target_commodity,
            target_quantity=body.target_quantity,
        )
    except ObjectiveConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except ObjectiveError as exc:
        raise _http_422(exc) from exc


@router.post("/objectives/actions/propose")
async def propose_objective_action(body: ObjectiveActionProposal) -> dict[str, Any]:
    """Propose a protected objective transition. Authorizes nothing by itself."""
    service = _objective_service()
    _sweep_expired_objective_actions()
    if (
        week13.count_pending_by_action_type(OBJECTIVE_ACTION_TYPE)
        >= _MAX_PENDING_OBJECTIVE_ACTIONS
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Too many objective actions are awaiting a decision.",
        )

    record: dict[str, Any] = {"action": body.action}
    if body.action == "purge_all":
        if body.operation is not None or body.text is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="operation and text are not valid for purge_all.",
            )
        record["objective_count"] = await service.count()
    else:
        try:
            operation = objectives_feature.normalize_operation(body.operation)
        except ObjectiveError as exc:
            raise _http_422(exc) from exc
        current = await service.get_current(operation)
        if not current.get("available"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The local objective store did not answer.",
            )
        objective = current.get("objective")
        if objective is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This operation holds no objective.",
            )
        record["operation"] = operation
        record["objective_id"] = objective["objective_id"]
        record["current_text"] = objective["text"]
        if body.action == "change":
            try:
                record["text"] = objectives_feature.normalize_text(body.text)
                record["target_commodity"] = (
                    objectives_feature.normalize_target_commodity(body.target_commodity)
                )
                record["target_quantity"] = (
                    objectives_feature.normalize_target_quantity(body.target_quantity)
                )
            except ObjectiveError as exc:
                raise _http_422(exc) from exc
            unchanged = (
                record["text"] == objective["text"]
                and record["target_commodity"] == objective.get("target_commodity")
                and record["target_quantity"] == objective.get("target_quantity")
            )
            if unchanged:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The objective already reads exactly that.",
                )
        elif body.text is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="text is only valid when changing an objective.",
            )

    suggestion, why = _objective_action_text(record)
    expires_at = _objective_now() + timedelta(seconds=_OBJECTIVE_PROPOSAL_TTL_SECONDS)
    confirmation_id = week13.enqueue_confirmation(
        suggestion_text=suggestion,
        why_text=why,
        timeout_at=expires_at.isoformat(),
        action_type=OBJECTIVE_ACTION_TYPE,
        # Queue metadata is display state, not proof, and deliberately carries
        # no authored text.
        metadata={"action": body.action, "operation": record.get("operation")},
    )
    record["expires_at"] = expires_at
    _pending_objective_actions[confirmation_id] = record

    service.log_proof(
        OPERATIONS_OBJECTIVE_PROPOSAL_SHOWN,
        "Commander objective change proposed; nothing authorized",
        {
            "objective_id": record.get("objective_id"),
            "operation": record.get("operation"),
            "action": body.action,
            "confirmation_id": confirmation_id,
            "authorized": False,
        },
    )
    return {
        "status": "pending_commander_confirmation",
        "confirmation_id": confirmation_id,
        "authorized": False,
        "action": body.action,
        "operation": record.get("operation"),
        "timeout_at": expires_at.isoformat(),
    }


@router.post("/objectives/actions/authorize")
async def authorize_objective_action(
    body: ObjectiveAuthorizationRequest,
) -> dict[str, Any]:
    """Spend a CONFIRMED decision and run the transition. Fail-closed."""
    service = _objective_service()
    _sweep_expired_objective_actions()
    confirmation_id = body.confirmation_id
    record = _pending_objective_actions.get(confirmation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unknown, expired, or already-used confirmation.",
        )

    outcome = week13.peek_confirmation_outcome(
        confirmation_id, expected_action_type=OBJECTIVE_ACTION_TYPE
    )
    if outcome is None:
        pending = week13.peek_pending_confirmation(
            confirmation_id, expected_action_type=OBJECTIVE_ACTION_TYPE
        )
        if pending is not None:
            return {"status": "pending_commander_confirmation", "authorized": False}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No consumable Commander decision for this confirmation.",
        )

    if outcome != week13.CONFIRMATION_OUTCOME_CONFIRMED:
        week13.consume_confirmation_outcome(
            confirmation_id, expected_action_type=OBJECTIVE_ACTION_TYPE
        )
        _pending_objective_actions.pop(confirmation_id, None)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The objective change was not confirmed.",
        )

    action = record["action"]
    try:
        if action == "purge_all":
            destroyed = await service.purge_all()
            result: dict[str, Any] = {
                "authorized": True,
                "action": action,
                "deleted_objectives": destroyed,
            }
        else:
            operation = record["operation"]
            if action == "change":
                payload = await service.change(
                    operation,
                    record["text"],
                    target_commodity=record.get("target_commodity"),
                    target_quantity=record.get("target_quantity"),
                )
            elif action == "complete":
                payload = await service.complete(operation)
            else:
                payload = await service.clear(operation)
            result = {"authorized": True, "action": action, **payload}
    except ObjectiveError as exc:
        # The decision is deliberately not spent: the transition did not run,
        # so the Commander's answer is still theirs to use.
        raise _http_422(exc) from exc

    # Spend the decision only after the work succeeded, so a failure leaves it
    # retriable rather than silently consumed.
    week13.consume_confirmation_outcome(
        confirmation_id, expected_action_type=OBJECTIVE_ACTION_TYPE
    )
    _pending_objective_actions.pop(confirmation_id, None)
    return result
