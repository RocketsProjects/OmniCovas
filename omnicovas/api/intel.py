"""Read-only PB05-03 Intel snapshot endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from omnicovas.features import intel, local_context_facts

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

router = APIRouter(prefix="/intel", tags=["intel"])

_state: StateManager | None = None


def set_state_manager(state: StateManager) -> None:
    """Inject the live StateManager into this router."""
    global _state  # noqa: PLW0603
    _state = state


class EntityRefResponse(BaseModel):
    """Public entity reference shape for Intel fact payloads."""

    model_config = ConfigDict(extra="forbid")

    entity_type: str
    entity_id: str
    display_name: str | None


class KnownFactResponse(BaseModel):
    """Public Intel KnownFact payload."""

    model_config = ConfigDict(extra="forbid")

    field_key: str
    label: str
    value: str | int | float | bool | None
    fallback: str | None
    source_id: str
    freshness_label: str
    truth_class: str
    caveat: str | None
    observed_at: str | None
    entity_ref: EntityRefResponse | None
    activity_log_ref: str | None


class IntelSectionResponse(BaseModel):
    """Public Intel section payload."""

    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    facts: list[KnownFactResponse]


class IntelSnapshotResponse(BaseModel):
    """Public Intel snapshot payload."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    sections: list[IntelSectionResponse]
    nullprovider_safe: bool


class Phase9ProofBase(BaseModel):
    """Shared PB09-02 local fact proof fields."""

    model_config = ConfigDict(extra="forbid")

    source: str
    source_event: str | None
    source_file: str | None
    event_timestamp: str | None
    freshness: str
    truth_class: str
    caveat: str
    fallback: str | None
    nullprovider_safe: bool


class Phase9SystemBgsResponse(Phase9ProofBase):
    """Current-system BGS facts from local Journal context."""

    scope: str
    system_name: str | None
    controlling_faction: str | None
    controlling_faction_fallback: str | None
    factions: list[dict[str, Any]]
    faction_count: int
    factions_fallback: str | None


class Phase9StationBgsResponse(Phase9ProofBase):
    """Current-station BGS facts from local Journal context."""

    scope: str
    station_name: str | None
    system_name: str | None
    controlling_faction: str | None
    controlling_faction_fallback: str | None


class Phase9BgsMissionEffectResponse(Phase9ProofBase):
    """MissionCompleted.FactionEffects local evidence."""

    mission_id: int | None
    faction: str | None
    effect_kinds: list[str]
    raw_effect: dict[str, Any]


class Phase9BgsRewardResponse(Phase9ProofBase):
    """Bounty/bond local evidence."""

    event_type: str
    reward_type: str | None
    amount: int | None
    faction: str | None
    faction_entries: list[dict[str, Any]]


class Phase9KnowledgeReferenceResponse(Phase9ProofBase):
    """KB reference material surfaced separately from telemetry facts."""

    id: str
    topic: str
    content: str
    patch_verified: str
    reference_source: str
    confidence: str


class Phase9UnsupportedClaimResponse(Phase9ProofBase):
    """Explicit unsupported Phase 9 claim."""

    field_key: str
    label: str
    value: None


class Phase9BgsFactsResponse(BaseModel):
    """PB09-02 local-first BGS fact surface payload."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    system_bgs: Phase9SystemBgsResponse
    station_bgs: Phase9StationBgsResponse
    recent_mission_effects: list[Phase9BgsMissionEffectResponse]
    recent_reward_events: list[Phase9BgsRewardResponse]
    knowledge_references: list[Phase9KnowledgeReferenceResponse]
    unsupported_claims: list[Phase9UnsupportedClaimResponse]
    missing_sources: list[str]
    nullprovider_safe: bool


class Phase9PowerplayPledgeResponse(Phase9ProofBase):
    """Local Powerplay pledge state."""

    value: str | None
    power: str | None
    status: str | None


class Phase9PowerplayRankResponse(Phase9ProofBase):
    """Local Powerplay rank state."""

    value: int | None


class Phase9SystemPowerplayResponse(Phase9ProofBase):
    """Current-system Powerplay context from local Journal context."""

    system_name: str | None
    powers: list[str]
    powerplay_state: str | None


class Phase9PowerplayEventResponse(Phase9ProofBase):
    """Local Powerplay event history with merit values withheld."""

    event_type: str
    power: str | None
    observed_fields: dict[str, Any]
    withheld_fields: list[str]


class Phase9PowerplayFactsResponse(BaseModel):
    """PB09-02 local-first Powerplay fact surface payload."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    pledge: Phase9PowerplayPledgeResponse
    rank: Phase9PowerplayRankResponse
    system_powerplay: Phase9SystemPowerplayResponse
    recent_events: list[Phase9PowerplayEventResponse]
    unsupported_claims: list[Phase9UnsupportedClaimResponse]
    missing_sources: list[str]
    nullprovider_safe: bool


@router.get("/snapshot", response_model=IntelSnapshotResponse)
async def get_intel_snapshot() -> dict[str, Any]:
    """Return the current first-wave Intel snapshot."""
    if _state is None:
        return intel.empty_snapshot_payload()
    return intel.snapshot_payload(_state)


@router.get("/phase9/bgs-facts", response_model=Phase9BgsFactsResponse)
async def get_phase9_bgs_facts() -> dict[str, Any]:
    """Return PB09-02 local-first BGS facts for the Intel route."""
    return local_context_facts.phase9_bgs_facts_payload(_state)


@router.get("/phase9/powerplay-facts", response_model=Phase9PowerplayFactsResponse)
async def get_phase9_powerplay_facts() -> dict[str, Any]:
    """Return PB09-02 local-first Powerplay facts for the Intel route."""
    return local_context_facts.phase9_powerplay_facts_payload(_state)
