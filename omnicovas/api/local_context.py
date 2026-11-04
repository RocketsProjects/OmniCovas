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

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from omnicovas.features import local_context_facts

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager
    from omnicovas.features.commander_memory import CommanderMemoryService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intel/local-context", tags=["intel"])

_state: "StateManager | None" = None
_market_path: Path | None = None
_outfitting_path: Path | None = None
_shipyard_path: Path | None = None
_cargo_path: Path | None = None
_modules_info_path: Path | None = None
_journal_dir_path: Path | None = None
_status_path: Path | None = None
_backpack_path: Path | None = None
_ship_locker_path: Path | None = None
_fc_materials_path: Path | None = None
_commander_memory: "CommanderMemoryService | None" = None


def set_state_manager(state: "StateManager | None") -> None:
    """Inject the live StateManager into this router."""
    global _state  # noqa: PLW0603
    _state = state


def set_commander_memory_service(service: "CommanderMemoryService | None") -> None:
    """Inject the single Commander Memory owner for snapshot observation."""
    global _commander_memory  # noqa: PLW0603
    _commander_memory = service


def set_snapshot_paths(
    *,
    market_path: Path | None = None,
    outfitting_path: Path | None = None,
    shipyard_path: Path | None = None,
    cargo_path: Path | None = None,
    modules_info_path: Path | None = None,
    journal_dir_path: Path | None = None,
    status_path: Path | None = None,
    backpack_path: Path | None = None,
    ship_locker_path: Path | None = None,
    fc_materials_path: Path | None = None,
) -> None:
    """Inject companion JSON paths for focused tests only."""
    global _market_path, _outfitting_path, _shipyard_path  # noqa: PLW0603
    global _cargo_path, _modules_info_path  # noqa: PLW0603
    global _journal_dir_path, _status_path  # noqa: PLW0603
    global _backpack_path, _ship_locker_path, _fc_materials_path  # noqa: PLW0603
    _market_path = market_path
    _outfitting_path = outfitting_path
    _shipyard_path = shipyard_path
    _cargo_path = cargo_path
    _modules_info_path = modules_info_path
    _journal_dir_path = journal_dir_path
    _status_path = status_path
    _backpack_path = backpack_path
    _ship_locker_path = ship_locker_path
    _fc_materials_path = fc_materials_path


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
    inventory_complete: bool | None
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


class OdysseyInventorySnapshotResponse(_ProvenanceBase):
    """Local Backpack.json / ShipLocker.json Odyssey inventory snapshot.

    Per-entry fields are preserved verbatim from the local file; OmniCOVAS
    asserts only the four registry-documented list containers.  ``*_count``
    fields count entries, never quantities; quantities live on the normalized
    ``materials`` records and the per-category ``categories`` summaries.
    Backpack and ShipLocker are separate sources and are never summed here.
    """

    storage_location: str
    observed_at: str | None
    observation_time_state: str
    freshness_policy: str
    source_state: str
    status: str
    materials: list[dict[str, Any]] | None
    categories: dict[str, dict[str, Any]]
    malformed_entry_count: int | None
    quantities_complete: bool | None
    items: list[dict[str, Any]] | None
    components: list[dict[str, Any]] | None
    consumables: list[dict[str, Any]] | None
    data: list[dict[str, Any]] | None
    items_count: int | None
    components_count: int | None
    consumables_count: int | None
    data_count: int | None
    total_entry_count: int | None


class FcMaterialsSnapshotResponse(_ProvenanceBase):
    """Local FCMaterials.json fleet-carrier materials trader snapshot."""

    observed_at: str | None
    status: str
    market_id: Any
    carrier_name: str | None
    item_count: int | None
    items: list[dict[str, Any]] | None


class SessionActivityResponse(_ProvenanceBase):
    """Local Elite session activity derived from file activity, not generated_at."""

    elite_session_state: str
    last_journal_event_at: str | None
    last_journal_event_type: str | None
    last_journal_file: str | None
    last_game_activity_at: str | None
    journal_files_scanned: list[str]
    # Startup exit criterion 3 (Phase 11 Dev Guide §C): local source path
    # posture, as a class rather than a path. "missing" means the Elite
    # directory is absent, which is materially different from an empty one:
    # nothing will ever be written to a path that does not exist.
    local_path_posture: str


class WalletFieldResponse(_ProvenanceBase):
    """Single source-backed wallet value."""

    value: int | None


class BalanceObservationResponse(BaseModel):
    """One source-backed credit-balance observation (FU-014)."""

    model_config = ConfigDict(extra="forbid")

    value: int
    source: str
    timestamp: str | None


class ObservedSessionChangeResponse(BaseModel):
    """Observed balance change over this session's observations (FU-014).

    Arithmetic over source-backed observations only — never a transaction
    record.
    """

    model_config = ConfigDict(extra="forbid")

    value: int | None
    from_value: int | None
    to_value: int | None
    first_observed_at: str | None
    last_observed_at: str | None
    caveat: str
    fallback: str | None
    nullprovider_safe: bool


class WalletSnapshotResponse(BaseModel):
    """Source-backed local wallet snapshot."""

    model_config = ConfigDict(extra="forbid")

    credits: WalletFieldResponse
    rebuy: WalletFieldResponse
    loan: WalletFieldResponse
    carrier_balance: WalletFieldResponse
    balance_history: list[BalanceObservationResponse]
    observed_session_change: ObservedSessionChangeResponse
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
    backpack_snapshot: OdysseyInventorySnapshotResponse
    ship_locker_snapshot: OdysseyInventorySnapshotResponse
    fc_materials_snapshot: FcMaterialsSnapshotResponse
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
    payload = build_local_context_snapshot()
    if _commander_memory is not None:
        try:
            await _commander_memory.observe_local_context(payload)
        except Exception:
            # Memory is an observed-history subscriber. A persistence fault must
            # never make the current local-context owner unavailable.
            logger.exception("Commander Memory could not observe local context")
    return payload


def build_local_context_snapshot() -> dict[str, Any]:
    """Build the current local-context payload without duplicating source reads."""
    return local_context_facts.local_context_snapshot_payload(
        _state,
        market_path=_market_path,
        outfitting_path=_outfitting_path,
        shipyard_path=_shipyard_path,
        cargo_path=_cargo_path,
        modules_info_path=_modules_info_path,
        journal_dir_path=_journal_dir_path,
        status_path=_status_path,
        backpack_path=_backpack_path,
        ship_locker_path=_ship_locker_path,
        fc_materials_path=_fc_materials_path,
    )
