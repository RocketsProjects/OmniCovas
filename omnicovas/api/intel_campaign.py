"""Read-only Intel campaign fact endpoint (PB13-03 slice, LNA-039).

Intel presents campaign facts and source age. Operations owns execution,
Navigation owns circuits, Activity Log owns proof — so this router exposes
GET only. No writes, no state transitions, no AI drafting, no providers.

See: omnicovas/features/intel_campaign.py (match basis and honesty posture)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.features import intel_campaign

router = APIRouter(prefix="/intel", tags=["intel"])

_session_factory: async_sessionmaker[AsyncSession] | None = None


def set_session_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    """Inject the live async session factory into this router."""
    global _session_factory  # noqa: PLW0603
    _session_factory = session_factory


def _ensure_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Campaign persistence not initialized",
        )
    return _session_factory


class CampaignEventTypeRow(BaseModel):
    """Recorded count for one event type under a single match basis."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    recorded: int
    last_seen: str | None


class CampaignSystemActivity(BaseModel):
    """Recorded activity matching a campaign's target system."""

    model_config = ConfigDict(extra="forbid")

    target: str
    matched_field: str
    events_recorded: int
    events_before_window: int
    last_seen: str | None
    by_event_type: list[CampaignEventTypeRow]


class CampaignSubjectActivity(BaseModel):
    """Recorded activity naming a campaign's target faction or power."""

    model_config = ConfigDict(extra="forbid")

    target: str
    matched_fields: list[str]
    events_recorded: int
    events_before_window: int
    last_seen: str | None
    by_event_type: list[CampaignEventTypeRow]


class CampaignEvidence(BaseModel):
    """Local evidence bundle for one campaign objective (LNA-039).

    ``available`` is false when the objective declares no target at all —
    distinct from a target that matched nothing, which reports zero.
    """

    model_config = ConfigDict(extra="forbid")

    window_start: str | None
    events_considered: list[str]
    system_activity: CampaignSystemActivity | None
    subject_activity: CampaignSubjectActivity | None
    available: bool
    unavailable_reason: str | None
    truth_class: str


class CampaignFactRow(BaseModel):
    """One Commander-entered campaign objective as an Intel fact."""

    model_config = ConfigDict(extra="forbid")

    campaign_id: str
    workflow_type: str
    title: str
    state: str
    target_subject: str | None
    target_system: str | None
    created_at: str | None
    updated_at: str | None
    archived_at: str | None
    record_age_seconds: int | None
    freshness: str
    truth_class: str
    proof_event_id: str | None
    evidence: CampaignEvidence


class CampaignFactsResponse(BaseModel):
    """Campaign objectives with source age and matching recorded activity."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    returned: int
    limit: int
    include_archived: bool
    campaigns: list[CampaignFactRow]
    execution_owner: str
    proof_owner: str
    nullprovider_safe: bool


@router.get("/campaign/facts", response_model=CampaignFactsResponse)
async def get_campaign_facts(
    workflow_type: str | None = Query(default=None, pattern="^(bgs|powerplay)$"),
    include_archived: bool = Query(default=False),
    limit: int | None = Query(default=None, ge=1, le=intel_campaign.CAMPAIGN_MAX_LIMIT),
) -> dict[str, Any]:
    """Campaign facts with source age and target-matching recorded activity."""
    factory = _ensure_session_factory()
    return await intel_campaign.campaign_facts(
        factory,
        workflow_type=workflow_type,
        include_archived=include_archived,
        limit=limit,
    )
