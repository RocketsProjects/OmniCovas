"""Inert Ardent imported-dataset contract.

This module defines the PB-ARD-02 fixture/design contract only. It does not
download, import, query, route, or open Ardent databases.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

ARDENT_PROVIDER_ID = "ardent"
ARDENT_SOURCE_CLASS = "LOCAL_EXTERNAL_DATASET"
ARDENT_DATASET_KIND = "imported_dataset"


class ArdentDatasetStatus(str, Enum):
    """Dataset lifecycle vocabulary for a future local Ardent import."""

    DISABLED = "disabled"
    DATASET_MISSING = "dataset_missing"
    DATASET_PRESENT_UNVERIFIED = "dataset_present_unverified"
    DATASET_VERIFIED = "dataset_verified"
    DATASET_STALE = "dataset_stale"
    IMPORT_FAILED = "import_failed"


class ArdentImplementationStatus(str, Enum):
    """Implementation maturity vocabulary for the Ardent dataset path."""

    NOT_IMPLEMENTED = "not_implemented"
    CONTRACT_ONLY = "contract_only"
    FIXTURE_ONLY = "fixture_only"
    IMPORTER_AVAILABLE = "importer_available"
    QUERY_AVAILABLE = "query_available"


class ArdentDomain(str, Enum):
    """Known Ardent downloadable data domains."""

    SYSTEMS = "systems"
    STATIONS = "stations"
    TRADE = "trade"
    LOCATIONS = "locations"


FORBIDDEN_REAL_DB_FILE_NAMES: frozenset[str] = frozenset(
    {
        "systems.db",
        "systems.db.gz",
        "stations.db",
        "stations.db.gz",
        "trade.db",
        "trade.db.gz",
        "locations.db",
        "locations.db.gz",
    }
)
FORBIDDEN_FIXTURE_SUFFIXES: tuple[str, ...] = (".sqlite", ".sqlite3")


@dataclass(frozen=True)
class ArdentManifestFile:
    """Expected metadata for one future downloaded Ardent database artifact."""

    file_name: str
    expected_sha256: str
    size_bytes: int
    dataset_created_at: str
    source_url: str
    compression: str
    format: str
    table_names: tuple[str, ...]
    imported_at: str | None = None
    verified_at: str | None = None
    manifest_hash: str | None = None


@dataclass(frozen=True)
class ArdentDatasetManifest:
    """Expected manifest shape for a future local Ardent import."""

    files: tuple[ArdentManifestFile, ...]


@dataclass(frozen=True)
class ArdentDomainContract:
    """Per-domain source file, allowed future roles, and forbidden claims."""

    domain: ArdentDomain
    source_db_file: str
    expected_role: str
    table_names: tuple[str, ...]
    allowed_future_query_types: tuple[str, ...]
    forbidden_claims: tuple[str, ...]


@dataclass(frozen=True)
class SourcePrecedenceRule:
    """Local fact source that must outrank imported Ardent context."""

    local_source: str
    beats_provider_id: str
    fact_scope: str


@dataclass(frozen=True)
class ArdentPrivacyContract:
    """Privacy promises for the future imported Ardent dataset path."""

    local_queries_after_import_send_outbound_data: bool
    download_import_commander_triggered: bool
    automatic_update_enabled: bool
    https_api_query_enabled: bool
    activity_log_required_for_import_update: bool
    diagnostics_fields: tuple[str, ...]


@dataclass(frozen=True)
class ArdentDatasetContract:
    """Top-level inert contract for Ardent dataset metadata."""

    source_class: str
    provider_id: str
    dataset_kind: str
    dataset_status: ArdentDatasetStatus
    implementation_status: ArdentImplementationStatus
    domains: tuple[ArdentDomainContract, ...]
    source_precedence: tuple[SourcePrecedenceRule, ...]
    privacy: ArdentPrivacyContract
    required_fact_labels: tuple[str, ...]
    forbidden_fact_labels: tuple[str, ...]
    manifest: ArdentDatasetManifest | None = None


ARDENT_DOMAIN_CONTRACTS: tuple[ArdentDomainContract, ...] = (
    ArdentDomainContract(
        domain=ArdentDomain.SYSTEMS,
        source_db_file="systems.db.gz",
        expected_role="Community-observed system directory and coordinate context.",
        table_names=("systems",),
        allowed_future_query_types=("system_lookup", "nearby_systems_context"),
        forbidden_claims=(
            "live_commander_location_truth",
            "official_frontier_truth",
            "route_planning_truth",
        ),
    ),
    ArdentDomainContract(
        domain=ArdentDomain.STATIONS,
        source_db_file="stations.db.gz",
        expected_role="Community-observed station and service context.",
        table_names=("stations",),
        allowed_future_query_types=(
            "station_lookup_context",
            "station_service_context",
            "nearest_station_by_service_candidate",
        ),
        forbidden_claims=(
            "exact_local_selected_station_outfitting",
            "exact_local_selected_station_shipyard",
            "guaranteed_station_services",
        ),
    ),
    ArdentDomainContract(
        domain=ArdentDomain.TRADE,
        source_db_file="trade.db.gz",
        expected_role="Community-observed commodity and market candidate context.",
        table_names=("commodities",),
        allowed_future_query_types=(
            "community_observed_market_candidate_context",
            "nearby_buy_sell_candidates",
            "market_commodity_candidates",
        ),
        forbidden_claims=(
            "current_cargo",
            "guaranteed_best_price",
            "current_station_local_market_truth",
            "complete_market_coverage",
        ),
    ),
    ArdentDomainContract(
        domain=ArdentDomain.LOCATIONS,
        source_db_file="locations.db.gz",
        expected_role="Community-observed spatial helper and location context.",
        table_names=("locations",),
        allowed_future_query_types=(
            "spatial_helper_context",
            "poi_context_candidates",
        ),
        forbidden_claims=(
            "route_planning_truth",
            "live_navigation_truth",
            "current_commander_position",
        ),
    ),
)


ARDENT_SOURCE_PRECEDENCE: tuple[SourcePrecedenceRule, ...] = (
    SourcePrecedenceRule(
        local_source="Journal",
        beats_provider_id=ARDENT_PROVIDER_ID,
        fact_scope="session events, commander-observed location, cargo events",
    ),
    SourcePrecedenceRule(
        local_source="Status.json",
        beats_provider_id=ARDENT_PROVIDER_ID,
        fact_scope="live ship, wallet, selected target, and status telemetry",
    ),
    SourcePrecedenceRule(
        local_source="StateManager",
        beats_provider_id=ARDENT_PROVIDER_ID,
        fact_scope="assembled current session state from local telemetry",
    ),
    SourcePrecedenceRule(
        local_source="Cargo.json",
        beats_provider_id=ARDENT_PROVIDER_ID,
        fact_scope="current local cargo manifest",
    ),
    SourcePrecedenceRule(
        local_source="Market.json",
        beats_provider_id=ARDENT_PROVIDER_ID,
        fact_scope="last observed selected-station market snapshot",
    ),
    SourcePrecedenceRule(
        local_source="Outfitting.json",
        beats_provider_id=ARDENT_PROVIDER_ID,
        fact_scope="known selected-station module availability snapshot",
    ),
    SourcePrecedenceRule(
        local_source="Shipyard.json",
        beats_provider_id=ARDENT_PROVIDER_ID,
        fact_scope="known selected-station shipyard availability snapshot",
    ),
    SourcePrecedenceRule(
        local_source="ModulesInfo.json",
        beats_provider_id=ARDENT_PROVIDER_ID,
        fact_scope="current loadout and module state snapshot",
    ),
    SourcePrecedenceRule(
        local_source="NavRoute.json",
        beats_provider_id=ARDENT_PROVIDER_ID,
        fact_scope="current plotted in-game route snapshot",
    ),
)


ARDENT_PRIVACY_CONTRACT = ArdentPrivacyContract(
    local_queries_after_import_send_outbound_data=False,
    download_import_commander_triggered=True,
    automatic_update_enabled=False,
    https_api_query_enabled=False,
    activity_log_required_for_import_update=True,
    diagnostics_fields=(
        "dataset_path",
        "size_bytes",
        "expected_sha256",
        "imported_at",
        "dataset_created_at",
        "verified_at",
        "stale_state",
    ),
)

REQUIRED_FACT_LABELS: tuple[str, ...] = (
    "Imported Ardent dataset",
    "Community-observed data",
    "Dataset snapshot",
    "Last imported",
    "Not live",
    "Not guaranteed complete",
)
FORBIDDEN_FACT_LABELS: tuple[str, ...] = (
    "Local truth",
    "Frontier source",
    "Live data",
    "Guaranteed",
    "Complete",
)


def default_ardent_dataset_contract() -> ArdentDatasetContract:
    """Return the disabled/missing contract-only Ardent posture."""

    return ArdentDatasetContract(
        source_class=ARDENT_SOURCE_CLASS,
        provider_id=ARDENT_PROVIDER_ID,
        dataset_kind=ARDENT_DATASET_KIND,
        dataset_status=ArdentDatasetStatus.DATASET_MISSING,
        implementation_status=ArdentImplementationStatus.CONTRACT_ONLY,
        domains=ARDENT_DOMAIN_CONTRACTS,
        source_precedence=ARDENT_SOURCE_PRECEDENCE,
        privacy=ARDENT_PRIVACY_CONTRACT,
        required_fact_labels=REQUIRED_FACT_LABELS,
        forbidden_fact_labels=FORBIDDEN_FACT_LABELS,
    )


def contract_from_explicit_manifest(
    manifest: ArdentDatasetManifest,
) -> ArdentDatasetContract:
    """Describe an explicit fixture manifest without verifying or opening DBs."""

    base = default_ardent_dataset_contract()
    return ArdentDatasetContract(
        source_class=base.source_class,
        provider_id=base.provider_id,
        dataset_kind=base.dataset_kind,
        dataset_status=ArdentDatasetStatus.DATASET_PRESENT_UNVERIFIED,
        implementation_status=ArdentImplementationStatus.FIXTURE_ONLY,
        domains=base.domains,
        source_precedence=base.source_precedence,
        privacy=base.privacy,
        required_fact_labels=base.required_fact_labels,
        forbidden_fact_labels=base.forbidden_fact_labels,
        manifest=manifest,
    )


def manifest_from_mapping(payload: Mapping[str, object]) -> ArdentDatasetManifest:
    """Build a manifest model from already-loaded fixture metadata."""

    files_value = payload.get("files")
    if not isinstance(files_value, Sequence) or isinstance(files_value, str):
        raise ValueError("Ardent manifest requires a files array")

    files: list[ArdentManifestFile] = []
    for raw_file in files_value:
        if not isinstance(raw_file, Mapping):
            raise ValueError("Ardent manifest file entries must be objects")
        files.append(_manifest_file_from_mapping(raw_file))

    return ArdentDatasetManifest(files=tuple(files))


def validate_fixture_tree(root: Path) -> tuple[Path, ...]:
    """Return forbidden fixture paths under root.

    The helper scans only the explicit path supplied by tests or future tooling.
    It never reads app data directories and never opens database files.
    """

    if not root.exists():
        return ()

    rejected: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        lower_name = path.name.lower()
        lower_suffix = path.suffix.lower()
        if lower_name in FORBIDDEN_REAL_DB_FILE_NAMES:
            rejected.append(path)
        elif lower_suffix in FORBIDDEN_FIXTURE_SUFFIXES:
            rejected.append(path)
    return tuple(rejected)


def _manifest_file_from_mapping(
    payload: Mapping[str, object],
) -> ArdentManifestFile:
    dataset_created_at = _optional_str(payload, "dataset_created_at")
    if dataset_created_at is None:
        dataset_created_at = _required_str(payload, "created_at")

    table_names_value = payload.get("table_names")
    table_names = _required_str_sequence(table_names_value, "table_names")

    return ArdentManifestFile(
        file_name=_required_str(payload, "file_name"),
        expected_sha256=_required_str(payload, "expected_sha256"),
        size_bytes=_required_int(payload, "size_bytes"),
        dataset_created_at=dataset_created_at,
        source_url=_required_str(payload, "source_url"),
        compression=_required_str(payload, "compression"),
        format=_required_str(payload, "format"),
        table_names=table_names,
        imported_at=_optional_str(payload, "imported_at"),
        verified_at=_optional_str(payload, "verified_at"),
        manifest_hash=_optional_str(payload, "manifest_hash"),
    )


def _required_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Ardent manifest requires non-empty string field {key!r}")
    return value


def _optional_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"Ardent manifest optional field {key!r} must be a string")
    return value


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"Ardent manifest requires non-negative int field {key!r}")
    return value


def _required_str_sequence(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ValueError(f"Ardent manifest requires string array field {key!r}")
    values: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise ValueError(f"Ardent manifest field {key!r} must contain strings")
        values.append(item)
    return tuple(values)
