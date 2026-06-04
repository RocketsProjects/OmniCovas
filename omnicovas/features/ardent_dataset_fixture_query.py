"""Fixture-only Ardent dataset query helpers for PB-ARD-03.

This module proves future imported-dataset query semantics over tiny,
hand-authored JSON fixtures only. It is not a provider, importer, downloader,
runtime router, or production database reader.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from omnicovas.features.ardent_dataset_contract import (
    ARDENT_PROVIDER_ID,
    ARDENT_SOURCE_CLASS,
    validate_fixture_tree,
)

ARDENT_FIXTURE_DATASET_STATUS = "fixture_only"
ARDENT_FIXTURE_SOURCE_LABEL = "Imported Ardent dataset fixture"
MAX_FIXTURE_QUERY_LIMIT = 25

FORBIDDEN_FIXTURE_QUERY_TYPES: tuple[str, ...] = (
    "route_planning",
    "live_market_truth",
    "current_cargo",
    "current_station_local_market_override",
    "exact_module_availability",
    "exact_ship_availability",
    "commander_profile",
    "mission_board",
    "community_goals",
    "fleet_carrier_owner_private_context",
)

_FIXTURE_FILES = {
    "systems": "fixture_systems.json",
    "stations": "fixture_stations.json",
    "trade": "fixture_trade.json",
    "locations": "fixture_locations.json",
}


@dataclass(frozen=True)
class ArdentFixtureProvenance:
    """Source/provenance label carried by every fixture query result."""

    provider_id: str = ARDENT_PROVIDER_ID
    source_class: str = ARDENT_SOURCE_CLASS
    dataset_status: str = ARDENT_FIXTURE_DATASET_STATUS
    source_label: str = ARDENT_FIXTURE_SOURCE_LABEL
    community_observed: bool = True
    not_live: bool = True
    not_guaranteed_complete: bool = True
    fixture_created_at: str | None = None
    caveats: tuple[str, ...] = (
        "Fixture-only PB-ARD-03 result; not downloaded Ardent data.",
        "Community-observed candidate context only.",
        "Local Journal, Status.json, StateManager, and companion JSON take precedence.",
    )

    def payload(self) -> dict[str, Any]:
        """Return a JSON-safe provenance payload."""

        return {
            "provider_id": self.provider_id,
            "source_class": self.source_class,
            "dataset_status": self.dataset_status,
            "source_label": self.source_label,
            "community_observed": self.community_observed,
            "not_live": self.not_live,
            "not_guaranteed_complete": self.not_guaranteed_complete,
            "fixture_created_at": self.fixture_created_at,
            "caveats": list(self.caveats),
        }


@dataclass(frozen=True)
class ArdentFixtureSystem:
    """Tiny fake system record used by PB-ARD-03 fixture queries."""

    name: str
    system_address: int
    coordinates: tuple[float, float, float]
    updated_at: str | None = None


@dataclass(frozen=True)
class ArdentFixtureStation:
    """Tiny fake station/service record used by PB-ARD-03 fixture queries."""

    name: str
    market_id: int
    system_name: str
    system_address: int
    services: tuple[str, ...]
    updated_at: str | None = None


@dataclass(frozen=True)
class ArdentFixtureTrade:
    """Tiny fake market commodity record used by PB-ARD-03 fixture queries."""

    commodity_name: str
    market_id: int
    station_name: str
    system_name: str
    buy_price: int
    sell_price: int
    stock: int
    demand: int
    updated_at: str | None = None


@dataclass(frozen=True)
class ArdentFixtureLocation:
    """Tiny fake spatial helper record used by PB-ARD-03 fixture loading."""

    name: str
    system_address: int
    body_name: str | None
    coordinates: tuple[float, float, float]
    updated_at: str | None = None


@dataclass(frozen=True)
class ArdentSystemResult:
    """Provider-labeled fixture system context result."""

    name: str
    system_address: int
    coordinates: tuple[float, float, float]
    distance_ly: float | None
    updated_at: str | None
    provenance: ArdentFixtureProvenance

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "system_address": self.system_address,
            "coordinates": list(self.coordinates),
            "distance_ly": self.distance_ly,
            "updated_at": self.updated_at,
            "provenance": self.provenance.payload(),
        }


@dataclass(frozen=True)
class ArdentStationResult:
    """Provider-labeled fixture station/service context result."""

    name: str
    market_id: int
    system_name: str
    system_address: int
    services: tuple[str, ...]
    updated_at: str | None
    provenance: ArdentFixtureProvenance

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "market_id": self.market_id,
            "system_name": self.system_name,
            "system_address": self.system_address,
            "services": list(self.services),
            "updated_at": self.updated_at,
            "provenance": self.provenance.payload(),
        }


@dataclass(frozen=True)
class ArdentTradeResult:
    """Provider-labeled fixture commodity candidate result."""

    commodity_name: str
    market_id: int
    station_name: str
    system_name: str
    buy_price: int
    sell_price: int
    stock: int
    demand: int
    candidate_role: str
    updated_at: str | None
    provenance: ArdentFixtureProvenance

    def payload(self) -> dict[str, Any]:
        return {
            "commodity_name": self.commodity_name,
            "market_id": self.market_id,
            "station_name": self.station_name,
            "system_name": self.system_name,
            "buy_price": self.buy_price,
            "sell_price": self.sell_price,
            "stock": self.stock,
            "demand": self.demand,
            "candidate_role": self.candidate_role,
            "updated_at": self.updated_at,
            "provenance": self.provenance.payload(),
        }


@dataclass(frozen=True)
class ArdentFixtureDataset:
    """Explicit, fixture-only Ardent dataset query surface."""

    systems: tuple[ArdentFixtureSystem, ...]
    stations: tuple[ArdentFixtureStation, ...]
    trade: tuple[ArdentFixtureTrade, ...]
    locations: tuple[ArdentFixtureLocation, ...]
    fixture_created_at: str | None = None

    @classmethod
    def from_records(
        cls,
        *,
        systems: Sequence[ArdentFixtureSystem],
        stations: Sequence[ArdentFixtureStation],
        trade: Sequence[ArdentFixtureTrade],
        locations: Sequence[ArdentFixtureLocation] = (),
        fixture_created_at: str | None = None,
    ) -> ArdentFixtureDataset:
        """Build a fixture dataset from explicit typed records."""

        return cls(
            systems=tuple(systems),
            stations=tuple(stations),
            trade=tuple(trade),
            locations=tuple(locations),
            fixture_created_at=fixture_created_at,
        )

    @classmethod
    def from_fixture_directory(cls, fixture_dir: Path) -> ArdentFixtureDataset:
        """Load the four PB-ARD-03 JSON fixture files from an explicit directory."""

        rejected = validate_fixture_tree(fixture_dir)
        if rejected:
            names = ", ".join(sorted(path.name for path in rejected))
            raise ValueError(f"Forbidden Ardent fixture files present: {names}")

        systems_payload = _load_fixture_payload(fixture_dir, _FIXTURE_FILES["systems"])
        stations_payload = _load_fixture_payload(
            fixture_dir, _FIXTURE_FILES["stations"]
        )
        trade_payload = _load_fixture_payload(fixture_dir, _FIXTURE_FILES["trade"])
        locations_payload = _load_fixture_payload(
            fixture_dir, _FIXTURE_FILES["locations"]
        )

        fixture_created_at = (
            systems_payload.fixture_created_at
            or stations_payload.fixture_created_at
            or trade_payload.fixture_created_at
            or locations_payload.fixture_created_at
        )

        return cls(
            systems=tuple(
                _system_from_mapping(record) for record in systems_payload.records
            ),
            stations=tuple(
                _station_from_mapping(record) for record in stations_payload.records
            ),
            trade=tuple(
                _trade_from_mapping(record) for record in trade_payload.records
            ),
            locations=tuple(
                _location_from_mapping(record) for record in locations_payload.records
            ),
            fixture_created_at=fixture_created_at,
        )

    def lookup_system(
        self,
        *,
        name: str | None = None,
        system_address: int | None = None,
    ) -> ArdentSystemResult | None:
        """Look up a fixture system by exact name or exact system address."""

        if name is None and system_address is None:
            raise ValueError("System lookup requires name or system_address")

        normalized_name = _normalize(name) if name is not None else None
        for record in self.systems:
            if (
                normalized_name is not None
                and _normalize(record.name) == normalized_name
            ):
                return self._system_result(record, distance_ly=None)
            if system_address is not None and record.system_address == system_address:
                return self._system_result(record, distance_ly=None)
        return None

    def nearby_systems(
        self,
        origin: tuple[float, float, float],
        *,
        limit: int,
    ) -> tuple[ArdentSystemResult, ...]:
        """Return nearest fixture systems from explicit coordinates."""

        bounded_limit = _bounded_limit(limit)
        ranked = sorted(
            (
                (record, _distance(origin, record.coordinates))
                for record in self.systems
            ),
            key=lambda item: (item[1], item[0].name),
        )
        return tuple(
            self._system_result(record, distance_ly=round(distance, 3))
            for record, distance in ranked[:bounded_limit]
        )

    def stations_with_service(
        self,
        service: str,
        *,
        system_name: str | None = None,
        limit: int = MAX_FIXTURE_QUERY_LIMIT,
    ) -> tuple[ArdentStationResult, ...]:
        """Return fixture stations that advertise a service flag."""

        normalized_service = _normalize(service)
        normalized_system = _normalize(system_name) if system_name else None
        bounded_limit = _bounded_limit(limit)
        matches: list[ArdentStationResult] = []
        for record in self.stations:
            services = {_normalize(item) for item in record.services}
            if normalized_service not in services:
                continue
            if normalized_system is not None and (
                _normalize(record.system_name) != normalized_system
            ):
                continue
            matches.append(self._station_result(record))
        return tuple(matches[:bounded_limit])

    def commodity_candidates(
        self,
        commodity_name: str,
        *,
        role: str,
        limit: int = MAX_FIXTURE_QUERY_LIMIT,
    ) -> tuple[ArdentTradeResult, ...]:
        """Return fixture importer/exporter commodity candidates."""

        normalized_commodity = _normalize(commodity_name)
        normalized_role = _normalize(role)
        if normalized_role not in {"import", "export"}:
            raise ValueError("Commodity candidate role must be 'import' or 'export'")

        bounded_limit = _bounded_limit(limit)
        records = [
            record
            for record in self.trade
            if _normalize(record.commodity_name) == normalized_commodity
            and _trade_matches_role(record, normalized_role)
        ]
        records.sort(
            key=lambda record: _trade_sort_key(record, normalized_role),
            reverse=normalized_role == "import",
        )
        return tuple(
            self._trade_result(record, candidate_role=normalized_role)
            for record in records[:bounded_limit]
        )

    def market_commodity(
        self,
        *,
        market_id: int,
        commodity_name: str,
    ) -> ArdentTradeResult | None:
        """Return a fixture commodity row for a marketId and exact commodity."""

        normalized_commodity = _normalize(commodity_name)
        for record in self.trade:
            if record.market_id == market_id and (
                _normalize(record.commodity_name) == normalized_commodity
            ):
                return self._trade_result(record, candidate_role="market_context")
        return None

    def _provenance(self) -> ArdentFixtureProvenance:
        return ArdentFixtureProvenance(fixture_created_at=self.fixture_created_at)

    def _system_result(
        self,
        record: ArdentFixtureSystem,
        *,
        distance_ly: float | None,
    ) -> ArdentSystemResult:
        return ArdentSystemResult(
            name=record.name,
            system_address=record.system_address,
            coordinates=record.coordinates,
            distance_ly=distance_ly,
            updated_at=record.updated_at,
            provenance=self._provenance(),
        )

    def _station_result(self, record: ArdentFixtureStation) -> ArdentStationResult:
        return ArdentStationResult(
            name=record.name,
            market_id=record.market_id,
            system_name=record.system_name,
            system_address=record.system_address,
            services=record.services,
            updated_at=record.updated_at,
            provenance=self._provenance(),
        )

    def _trade_result(
        self,
        record: ArdentFixtureTrade,
        *,
        candidate_role: str,
    ) -> ArdentTradeResult:
        return ArdentTradeResult(
            commodity_name=record.commodity_name,
            market_id=record.market_id,
            station_name=record.station_name,
            system_name=record.system_name,
            buy_price=record.buy_price,
            sell_price=record.sell_price,
            stock=record.stock,
            demand=record.demand,
            candidate_role=candidate_role,
            updated_at=record.updated_at,
            provenance=self._provenance(),
        )


@dataclass(frozen=True)
class _FixturePayload:
    fixture_created_at: str | None
    records: tuple[Mapping[str, object], ...]


def _load_fixture_payload(fixture_dir: Path, filename: str) -> _FixturePayload:
    path = fixture_dir / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError(f"Ardent fixture {filename} must contain a JSON object")

    fixture_created_at = _optional_str(data.get("fixture_created_at"))
    records_value = data.get("records")
    if not isinstance(records_value, Sequence) or isinstance(records_value, str):
        raise ValueError(f"Ardent fixture {filename} requires a records array")

    records: list[Mapping[str, object]] = []
    for raw_record in records_value:
        if not isinstance(raw_record, Mapping):
            raise ValueError(f"Ardent fixture {filename} records must be objects")
        records.append(cast(Mapping[str, object], raw_record))

    return _FixturePayload(
        fixture_created_at=fixture_created_at,
        records=tuple(records),
    )


def _system_from_mapping(payload: Mapping[str, object]) -> ArdentFixtureSystem:
    return ArdentFixtureSystem(
        name=_required_str(payload.get("name"), "name"),
        system_address=_required_int(payload.get("system_address"), "system_address"),
        coordinates=_coordinates(payload.get("coordinates")),
        updated_at=_optional_str(payload.get("updated_at")),
    )


def _station_from_mapping(payload: Mapping[str, object]) -> ArdentFixtureStation:
    return ArdentFixtureStation(
        name=_required_str(payload.get("name"), "name"),
        market_id=_required_int(payload.get("market_id"), "market_id"),
        system_name=_required_str(payload.get("system_name"), "system_name"),
        system_address=_required_int(payload.get("system_address"), "system_address"),
        services=_str_tuple(payload.get("services"), "services"),
        updated_at=_optional_str(payload.get("updated_at")),
    )


def _trade_from_mapping(payload: Mapping[str, object]) -> ArdentFixtureTrade:
    return ArdentFixtureTrade(
        commodity_name=_required_str(payload.get("commodity_name"), "commodity_name"),
        market_id=_required_int(payload.get("market_id"), "market_id"),
        station_name=_required_str(payload.get("station_name"), "station_name"),
        system_name=_required_str(payload.get("system_name"), "system_name"),
        buy_price=_required_int(payload.get("buy_price"), "buy_price"),
        sell_price=_required_int(payload.get("sell_price"), "sell_price"),
        stock=_required_int(payload.get("stock"), "stock"),
        demand=_required_int(payload.get("demand"), "demand"),
        updated_at=_optional_str(payload.get("updated_at")),
    )


def _location_from_mapping(payload: Mapping[str, object]) -> ArdentFixtureLocation:
    return ArdentFixtureLocation(
        name=_required_str(payload.get("name"), "name"),
        system_address=_required_int(payload.get("system_address"), "system_address"),
        body_name=_optional_str(payload.get("body_name")),
        coordinates=_coordinates(payload.get("coordinates")),
        updated_at=_optional_str(payload.get("updated_at")),
    )


def _required_str(value: object, key: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Ardent fixture requires non-empty string {key!r}")
    return value


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("Ardent fixture optional string fields must be strings")
    return value


def _required_int(value: object, key: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"Ardent fixture requires integer {key!r}")
    return value


def _required_float(value: object, key: str) -> float:
    if not isinstance(value, int | float):
        raise ValueError(f"Ardent fixture requires numeric coordinate {key!r}")
    return float(value)


def _coordinates(value: object) -> tuple[float, float, float]:
    if not isinstance(value, Mapping):
        raise ValueError("Ardent fixture requires coordinates object")
    coordinates = cast(Mapping[str, object], value)
    return (
        _required_float(coordinates.get("x"), "x"),
        _required_float(coordinates.get("y"), "y"),
        _required_float(coordinates.get("z"), "z"),
    )


def _str_tuple(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ValueError(f"Ardent fixture requires string array {key!r}")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"Ardent fixture {key!r} must contain strings")
        result.append(item)
    return tuple(result)


def _normalize(value: str | None) -> str:
    return "" if value is None else value.casefold()


def _bounded_limit(limit: int) -> int:
    if limit < 1:
        raise ValueError("Fixture query limit must be positive")
    return min(limit, MAX_FIXTURE_QUERY_LIMIT)


def _distance(
    origin: tuple[float, float, float],
    coordinates: tuple[float, float, float],
) -> float:
    return math.sqrt(
        (coordinates[0] - origin[0]) ** 2
        + (coordinates[1] - origin[1]) ** 2
        + (coordinates[2] - origin[2]) ** 2
    )


def _trade_matches_role(record: ArdentFixtureTrade, role: str) -> bool:
    if role == "import":
        return record.demand > 0 and record.buy_price > 0
    return record.stock > 0 and record.sell_price > 0


def _trade_sort_key(record: ArdentFixtureTrade, role: str) -> tuple[int, str]:
    if role == "import":
        return (record.buy_price, record.station_name)
    return (record.sell_price, record.station_name)
