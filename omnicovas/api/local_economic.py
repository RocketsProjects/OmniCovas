"""Read-only PB06-03 local economic fact snapshot endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from omnicovas.features import local_economic_facts

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

router = APIRouter(prefix="/intel/economic", tags=["intel"])

_state: StateManager | None = None
_market_path: Path | None = None
_outfitting_path: Path | None = None
_shipyard_path: Path | None = None


def set_state_manager(state: StateManager | None) -> None:
    """Inject the live StateManager into this router."""
    global _state  # noqa: PLW0603
    _state = state


def set_snapshot_paths(
    *,
    market_path: Path | None = None,
    outfitting_path: Path | None = None,
    shipyard_path: Path | None = None,
) -> None:
    """Inject local companion snapshot paths for focused tests only."""
    global _market_path, _outfitting_path, _shipyard_path  # noqa: PLW0603
    _market_path = market_path
    _outfitting_path = outfitting_path
    _shipyard_path = shipyard_path


def reset_snapshot_paths() -> None:
    """Clear focused-test companion snapshot path overrides."""
    set_snapshot_paths()


class CargoItemResponse(BaseModel):
    """Single local cargo item count."""

    model_config = ConfigDict(extra="forbid")

    name: str
    count: int


class CargoSummaryResponse(BaseModel):
    """Journal-derived local cargo summary."""

    model_config = ConfigDict(extra="forbid")

    source: str
    timestamp: str | None
    freshness: str
    truth_class: str
    caveat: str
    fallback: str | None
    items: list[CargoItemResponse] | None
    total_count: int | None
    commodity_types: int | None
    nullprovider_safe: bool


class LocalStationSnapshotBaseResponse(BaseModel):
    """Common local station companion snapshot fields."""

    model_config = ConfigDict(extra="forbid")

    source: str
    timestamp: str | None
    freshness: str
    truth_class: str
    caveat: str
    fallback: str | None
    market_id: Any
    station_name: str | None
    star_system: str | None
    nullprovider_safe: bool


class MarketSnapshotResponse(LocalStationSnapshotBaseResponse):
    """Local Market.json snapshot payload."""

    items: list[dict[str, Any]] | None


class OutfittingSnapshotResponse(LocalStationSnapshotBaseResponse):
    """Local Outfitting.json snapshot payload."""

    items: list[dict[str, Any]] | None


class ShipyardSnapshotResponse(LocalStationSnapshotBaseResponse):
    """Local Shipyard.json snapshot payload."""

    price_list: list[dict[str, Any]] | None


class DisabledExternalSourceResponse(BaseModel):
    """PB06-02 provider lock row."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    display_name: str
    state: str
    fallback: str
    requires_auth: bool
    requires_consent: bool
    capabilities: list[str]


class DisabledExternalContextResponse(BaseModel):
    """Disabled external context metadata for UI consumers."""

    model_config = ConfigDict(extra="forbid")

    phase6_local_only: bool
    fallback: str
    sources: list[DisabledExternalSourceResponse]


class LocalEconomicSnapshotResponse(BaseModel):
    """Public local economic snapshot payload."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    cargo: CargoSummaryResponse
    market: MarketSnapshotResponse
    outfitting: OutfittingSnapshotResponse
    shipyard: ShipyardSnapshotResponse
    disabled_external_context: DisabledExternalContextResponse
    nullprovider_safe: bool


@router.get("/snapshot", response_model=LocalEconomicSnapshotResponse)
async def get_local_economic_snapshot() -> dict[str, Any]:
    """Return local-only economic facts for PB06-04 consumers."""
    return local_economic_facts.snapshot_payload(
        _state,
        market_path=_market_path,
        outfitting_path=_outfitting_path,
        shipyard_path=_shipyard_path,
    )
