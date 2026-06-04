"""Read-only Phase 6 extension — local context backplane snapshot endpoint.

Exposes the field-rich LocalStationContext / LocalSystemContext /
StationServicesSnapshot / LocalMarketSnapshot / LocalOutfittingSnapshot /
LocalShipyardSnapshot / CargoHoldSnapshot / ModuleLoadoutSnapshot composed by
omnicovas.features.local_context_facts.

Local-only. No external lookups. Per-field provenance preserved.

See: Local Elite Data Surface Reference v1.0 §6.1, §6.3, §7, §9
See: Source Capability Routing Reference v1 §1, §3
See: Engineering Standards v1.0 §12 API module standards
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from omnicovas.features import local_context_facts

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

router = APIRouter(prefix="/intel/local-context", tags=["intel"])

_state: "StateManager | None" = None
_market_path: Path | None = None
_outfitting_path: Path | None = None
_shipyard_path: Path | None = None
_cargo_path: Path | None = None
_modules_info_path: Path | None = None
_journal_dir_path: Path | None = None
_status_path: Path | None = None


def set_state_manager(state: "StateManager | None") -> None:
    """Inject the live StateManager into this router."""
    global _state  # noqa: PLW0603
    _state = state


def set_snapshot_paths(
    *,
    market_path: Path | None = None,
    outfitting_path: Path | None = None,
    shipyard_path: Path | None = None,
    cargo_path: Path | None = None,
    modules_info_path: Path | None = None,
    journal_dir_path: Path | None = None,
    status_path: Path | None = None,
) -> None:
    """Inject companion JSON paths for focused tests only."""
    global _market_path, _outfitting_path, _shipyard_path  # noqa: PLW0603
    global _cargo_path, _modules_info_path  # noqa: PLW0603
    global _journal_dir_path, _status_path  # noqa: PLW0603
    _market_path = market_path
    _outfitting_path = outfitting_path
    _shipyard_path = shipyard_path
    _cargo_path = cargo_path
    _modules_info_path = modules_info_path
    _journal_dir_path = journal_dir_path
    _status_path = status_path


def reset_snapshot_paths() -> None:
    """Clear focused-test companion snapshot path overrides."""
    set_snapshot_paths()


# --- Response models -------------------------------------------------------


class _ProvenanceBase(BaseModel):
    """Shared provenance trio used by every snapshot response model."""

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


class LocalStationContextResponse(_ProvenanceBase):
    """Field-rich local station context payload."""

    context_kind: str
    missing_fields: list[str]
    station_name: str | None
    station_type: str | None
    market_id: int | None
    star_system: str | None
    system_address: int | None
    is_docked: bool | None
    station_faction: dict[str, Any] | None
    station_government: str | None
    station_allegiance: str | None
    station_economy: str | None
    station_economies: list[dict[str, Any]] | None
    station_services: list[str] | None
    landing_pads: dict[str, Any] | None
    dist_from_star_ls: float | None


class LocalSystemContextResponse(_ProvenanceBase):
    """Field-rich local system context payload."""

    star_system: str | None
    system_address: int | None
    star_pos: list[float] | None
    body: str | None
    body_id: int | None
    body_type: str | None
    system_faction: dict[str, Any] | None
    system_allegiance: str | None
    system_economy: str | None
    system_second_economy: str | None
    system_government: str | None
    system_security: str | None
    population: int | None
    powers: list[str] | None
    powerplay_state: str | None
    factions: list[dict[str, Any]] | None
    conflicts: list[dict[str, Any]] | None


class StationServicesSnapshotResponse(_ProvenanceBase):
    """Station services derived from the most recent Docked event."""

    station_name: str | None
    star_system: str | None
    market_id: int | None
    services: list[str] | None


class LocalMarketItemResponse(BaseModel):
    """Field-rich Market.json Items[] entry preserved verbatim."""

    model_config = ConfigDict(extra="forbid")

    id: int | None
    name: str | None
    name_localised: str | None
    category: str | None
    category_localised: str | None
    buy_price: int | None
    sell_price: int | None
    mean_price: int | None
    stock: int | None
    stock_bracket: Any
    demand: int | None
    demand_bracket: Any
    consumer: bool | None
    producer: bool | None
    rare: bool | None
    prohibited: bool | None
    status_flags: list[str]


class LocalMarketSnapshotResponse(_ProvenanceBase):
    """Local Market.json snapshot with every Frontier-native item field."""

    market_id: Any
    station_name: str | None
    star_system: str | None
    items: list[LocalMarketItemResponse] | None


class LocalOutfittingItemResponse(BaseModel):
    """Single Outfitting.json Items[] entry."""

    model_config = ConfigDict(extra="forbid")

    id: Any
    name: str | None
    buy_price: Any


class LocalOutfittingSnapshotResponse(_ProvenanceBase):
    """Local Outfitting.json snapshot for one selected/visited station."""

    observed_at: str | None
    status: str
    market_id: Any
    station_name: str | None
    star_system: str | None
    horizons: bool | None
    item_count: int | None
    items: list[LocalOutfittingItemResponse] | None
    stale_reasons: list[str]


class LocalShipyardShipResponse(BaseModel):
    """Single Shipyard.json PriceList[] entry."""

    model_config = ConfigDict(extra="forbid")

    id: Any
    ship_type: str | None
    ship_price: Any


class LocalShipyardSnapshotResponse(_ProvenanceBase):
    """Local Shipyard.json snapshot for one selected/visited station."""

    observed_at: str | None
    status: str
    market_id: Any
    station_name: str | None
    star_system: str | None
    horizons: bool | None
    allow_cobra_mk_iv: bool | None
    ship_count: int | None
    ships: list[LocalShipyardShipResponse] | None
    stale_reasons: list[str]


class CargoItemResponse(BaseModel):
    """Single cargo entry with Frontier-native flags preserved."""

    model_config = ConfigDict(extra="forbid")

    name: str
    name_localised: str | None
    count: int
    stolen: int | None
    mission_id: int | None


class CargoHoldSnapshotResponse(_ProvenanceBase):
    """Local cargo hold snapshot (Cargo.json or Cargo journal event)."""

    vessel: str | None
    capacity: int | None
    inventory: list[CargoItemResponse] | None
    total_count: int | None


class ModuleSlotSnapshotResponse(BaseModel):
    """Module loadout entry preserving Loadout / ModulesInfo fields."""

    model_config = ConfigDict(extra="forbid")

    slot: str
    item: str
    item_localised: str | None
    on: bool
    priority: int | None
    power: float | None
    health: float
    ammo_in_clip: int | None
    ammo_in_hopper: int | None
    value: int | None
    engineering_raw: dict[str, Any] | None


class ModuleLoadoutSnapshotResponse(_ProvenanceBase):
    """Local module loadout snapshot from Loadout (+ optional ModulesInfo)."""

    vessel: str | None
    loadout_hash: str | None
    hull_value: int | None
    modules_value: int | None
    modules: list[ModuleSlotSnapshotResponse] | None
    shield_generator: dict[str, Any]


class SessionActivityResponse(_ProvenanceBase):
    """Local Elite session activity derived from file activity, not generated_at."""

    elite_session_state: str
    last_journal_event_at: str | None
    last_journal_event_type: str | None
    last_journal_file: str | None
    last_game_activity_at: str | None
    journal_files_scanned: list[str]


class WalletFieldResponse(_ProvenanceBase):
    """Single source-backed wallet value."""

    value: int | None


class WalletSnapshotResponse(BaseModel):
    """Source-backed local wallet snapshot."""

    model_config = ConfigDict(extra="forbid")

    credits: WalletFieldResponse
    rebuy: WalletFieldResponse
    loan: WalletFieldResponse
    carrier_balance: WalletFieldResponse
    missing_sources: list[str]
    unavailable_fields: list[str]
    nullprovider_safe: bool


class LocalContextSnapshotResponse(BaseModel):
    """Top-level Local Context backplane snapshot."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    session_activity: SessionActivityResponse
    station_context: LocalStationContextResponse
    system_context: LocalSystemContextResponse
    station_services: StationServicesSnapshotResponse
    market_snapshot: LocalMarketSnapshotResponse
    outfitting_snapshot: LocalOutfittingSnapshotResponse
    shipyard_snapshot: LocalShipyardSnapshotResponse
    cargo_hold: CargoHoldSnapshotResponse
    module_loadout: ModuleLoadoutSnapshotResponse
    wallet_snapshot: WalletSnapshotResponse
    missing_sources: list[str]
    nullprovider_safe: bool


@router.get("/snapshot", response_model=LocalContextSnapshotResponse)
async def get_local_context_snapshot() -> dict[str, Any]:
    """Return the field-rich local context backplane snapshot.

    Local-only. Pure projection of journal-derived state plus on-demand
    companion JSON reads. No external lookups. Missing sources surface as
    freshness="not_loaded" with explicit fallback wording.
    """
    return local_context_facts.local_context_snapshot_payload(
        _state,
        market_path=_market_path,
        outfitting_path=_outfitting_path,
        shipyard_path=_shipyard_path,
        cargo_path=_cargo_path,
        modules_info_path=_modules_info_path,
        journal_dir_path=_journal_dir_path,
        status_path=_status_path,
    )
