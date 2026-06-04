"""Inert Ardent app-data storage and import-state contract.

PB-ARD-04A defines only path planning, manifest metadata checks, verification
task planning, future diagnostics fields, and staleness policy. It does not
create directories, download files, import databases, open SQLite files, or
query production Ardent data.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from omnicovas.features.ardent_dataset_contract import (
    ARDENT_DOMAIN_CONTRACTS,
    ARDENT_PROVIDER_ID,
    ARDENT_SOURCE_CLASS,
    FORBIDDEN_FIXTURE_SUFFIXES,
    FORBIDDEN_REAL_DB_FILE_NAMES,
    ArdentDatasetManifest,
    ArdentDatasetStatus,
    manifest_from_mapping,
)

ARDENT_APP_DATA_ROOT_CONTRACT = r"%APPDATA%\OmniCOVAS\ardent"
ARDENT_STORAGE_DIRECTORIES: tuple[str, ...] = (
    "downloads",
    "imported",
    "manifests",
    "staging",
    "quarantine",
    "metadata",
)
ARDENT_REQUIRED_DOWNLOAD_FILES: tuple[str, ...] = tuple(
    domain.source_db_file for domain in ARDENT_DOMAIN_CONTRACTS
)
ARDENT_MANIFEST_FILE_NAME = "active_manifest.json"
ARDENT_IMPORT_STATE_FILE_NAME = "import_state.json"
ARDENT_PUBLISHED_REFRESH_CADENCE_DAYS = 7
ARDENT_DEFAULT_STALENESS_THRESHOLD_DAYS = 10
ARDENT_DEFAULT_STALENESS_THRESHOLD = timedelta(
    days=ARDENT_DEFAULT_STALENESS_THRESHOLD_DAYS
)

ARDENT_STORAGE_SAFETY_RULES: tuple[str, ...] = (
    "Store future Ardent artifacts under app data only, never the repository.",
    "Use staging before any verification result is recorded.",
    "Verify SHA-256 and size before any dataset_verified state is recorded.",
    "Move verified staged artifacts into imported atomically.",
    "Move failed imports to quarantine or remove them.",
    "Record file size, source URL, dataset_created_at, imported_at, and verified_at.",
    "Record manifest hash when the upstream manifest supplies one.",
    "Local Frontier data always outranks imported Ardent context.",
)

ARDENT_ACTIVITY_LOG_EVENT_TYPES: tuple[str, ...] = (
    "ardent.import_requested",
    "ardent.download_started",
    "ardent.download_completed",
    "ardent.download_failed",
    "ardent.verify_started",
    "ardent.verify_failed",
    "ardent.import_completed",
    "ardent.dataset_stale",
    "ardent.dataset_disabled",
)

ARDENT_DIAGNOSTICS_FIELDS: tuple[str, ...] = (
    "source_id",
    "source_class",
    "provider_status",
    "dataset_status",
    "implementation_status",
    "dataset_root",
    "active_manifest",
    "required_files",
    "present_files",
    "missing_files",
    "verified_files",
    "total_size_bytes",
    "dataset_created_at",
    "imported_at",
    "verified_at",
    "stale",
    "caveats",
)

_HEX_CHARS = frozenset("0123456789abcdefABCDEF")


class ArdentImportState(str, Enum):
    """Future local import-state vocabulary; no runtime importer exists here."""

    DISABLED = "disabled"
    DOWNLOAD_PENDING = "download_pending"
    DOWNLOAD_IN_PROGRESS = "download_in_progress"
    DOWNLOAD_FAILED = "download_failed"
    VERIFICATION_FAILED = "verification_failed"
    IMPORT_IN_PROGRESS = "import_in_progress"
    IMPORT_COMPLETE = "import_complete"


class ArdentFreshnessState(str, Enum):
    """Freshness labels for UI/diagnostics once a dataset is otherwise verified."""

    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ArdentStorageLayout:
    """Pure path plan for future Ardent app-data storage."""

    root: Path
    downloads: Path
    imported: Path
    manifests: Path
    staging: Path
    quarantine: Path
    metadata: Path
    active_manifest: Path
    import_state: Path

    def all_paths(self) -> tuple[Path, ...]:
        """Return every planned directory or metadata file path."""

        return (
            self.root,
            self.downloads,
            self.imported,
            self.manifests,
            self.staging,
            self.quarantine,
            self.metadata,
            self.active_manifest,
            self.import_state,
        )


@dataclass(frozen=True)
class ArdentRequiredFilePlan:
    """Planned locations for one required downloadable Ardent artifact."""

    domain: str
    file_name: str
    download_path: Path
    staging_path: Path
    imported_path: Path


@dataclass(frozen=True)
class ArdentVerificationTask:
    """Expected future verification work; no file content is read here."""

    file_name: str
    expected_sha256: str
    expected_size_bytes: int
    dataset_created_at: str
    source_url: str
    staging_path: Path
    imported_path: Path
    manifest_hash: str | None = None


@dataclass(frozen=True)
class ArdentManifestMetadataCheck:
    """Result of checking manifest metadata shape without verifying files."""

    required_files: tuple[str, ...]
    present_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    unexpected_files: tuple[str, ...]
    metadata_errors: tuple[str, ...]
    manifest_parse_error: str | None = None

    @property
    def can_plan_verification_tasks(self) -> bool:
        """Return True when metadata is sufficient to plan hash checks."""

        return (
            self.manifest_parse_error is None
            and not self.metadata_errors
            and not self.missing_files
            and not self.unexpected_files
        )


@dataclass(frozen=True)
class ArdentManifestVerificationPlan:
    """Contract result for future manifest verification planning."""

    dataset_status: ArdentDatasetStatus
    import_state: ArdentImportState
    manifest: ArdentDatasetManifest | None
    metadata_check: ArdentManifestMetadataCheck
    verification_tasks: tuple[ArdentVerificationTask, ...]
    total_size_bytes: int
    caveats: tuple[str, ...]


@dataclass(frozen=True)
class ArdentStalenessResult:
    """Freshness assessment for a dataset that has otherwise been verified."""

    freshness: ArdentFreshnessState
    stale: bool
    dataset_status_if_hashes_verified: ArdentDatasetStatus
    dataset_created_at: datetime | None
    imported_at: datetime | None
    threshold_days: int
    caveats: tuple[str, ...]


def plan_ardent_storage_layout(
    omnicovas_app_data_root: Path | None = None,
) -> ArdentStorageLayout:
    """Return the future Ardent app-data path plan without creating paths."""

    app_data_root = omnicovas_app_data_root or Path(
        os.path.expandvars(r"%APPDATA%\OmniCOVAS")
    )
    root = app_data_root / "ardent"
    metadata = root / "metadata"
    manifests = root / "manifests"
    return ArdentStorageLayout(
        root=root,
        downloads=root / "downloads",
        imported=root / "imported",
        manifests=manifests,
        staging=root / "staging",
        quarantine=root / "quarantine",
        metadata=metadata,
        active_manifest=manifests / ARDENT_MANIFEST_FILE_NAME,
        import_state=metadata / ARDENT_IMPORT_STATE_FILE_NAME,
    )


def validate_storage_layout(
    layout: ArdentStorageLayout,
    *,
    repo_root: Path | None = None,
) -> tuple[str, ...]:
    """Return safety errors for a planned storage layout."""

    errors: list[str] = []
    for path in layout.all_paths():
        if not _is_relative_to(path, layout.root):
            errors.append(f"planned path escapes Ardent root: {path}")

    if repo_root is not None and _is_relative_to(layout.root, repo_root):
        errors.append("Ardent app-data root must not be inside the repository")

    return tuple(errors)


def plan_required_files(
    layout: ArdentStorageLayout,
) -> tuple[ArdentRequiredFilePlan, ...]:
    """Return required file path plans for the four known Ardent artifacts."""

    return tuple(
        ArdentRequiredFilePlan(
            domain=domain.domain.value,
            file_name=domain.source_db_file,
            download_path=layout.downloads / domain.source_db_file,
            staging_path=layout.staging / domain.source_db_file,
            imported_path=layout.imported / domain.source_db_file,
        )
        for domain in ARDENT_DOMAIN_CONTRACTS
    )


def is_forbidden_ardent_repo_filename(file_name: str) -> bool:
    """Return True for real Ardent DB/dump names forbidden in the repo."""

    lower_name = file_name.lower()
    return lower_name in FORBIDDEN_REAL_DB_FILE_NAMES or lower_name.endswith(
        FORBIDDEN_FIXTURE_SUFFIXES
    )


def detect_forbidden_repo_artifact_paths(
    paths: Sequence[Path],
    *,
    repo_root: Path,
) -> tuple[Path, ...]:
    """Check explicit paths for repo-local real DB artifacts without scanning."""

    return tuple(
        path
        for path in paths
        if _is_relative_to(path, repo_root)
        and is_forbidden_ardent_repo_filename(path.name)
    )


def check_manifest_metadata(
    payload: Mapping[str, object],
) -> ArdentManifestMetadataCheck:
    """Check future manifest metadata requirements without reading artifacts."""

    files_value = payload.get("files")
    if not isinstance(files_value, Sequence) or isinstance(files_value, str):
        return ArdentManifestMetadataCheck(
            required_files=ARDENT_REQUIRED_DOWNLOAD_FILES,
            present_files=(),
            missing_files=ARDENT_REQUIRED_DOWNLOAD_FILES,
            unexpected_files=(),
            metadata_errors=("manifest.files must be an array",),
            manifest_parse_error="Ardent manifest requires a files array",
        )

    present_files: list[str] = []
    metadata_errors: list[str] = []
    for index, raw_file in enumerate(files_value):
        if not isinstance(raw_file, Mapping):
            metadata_errors.append(f"files[{index}] must be an object")
            continue
        file_name = raw_file.get("file_name")
        if isinstance(file_name, str) and file_name:
            present_files.append(file_name)
        else:
            metadata_errors.append(f"files[{index}].file_name is required")
        metadata_errors.extend(_manifest_file_metadata_errors(index, raw_file))

    present_ordered = _ordered_files(present_files)
    present_set = set(present_files)
    required_set = set(ARDENT_REQUIRED_DOWNLOAD_FILES)
    missing_files = tuple(
        file_name
        for file_name in ARDENT_REQUIRED_DOWNLOAD_FILES
        if file_name not in present_set
    )
    unexpected_files = tuple(
        file_name for file_name in present_ordered if file_name not in required_set
    )

    parse_error: str | None = None
    try:
        manifest_from_mapping(payload)
    except ValueError as exc:
        parse_error = str(exc)

    return ArdentManifestMetadataCheck(
        required_files=ARDENT_REQUIRED_DOWNLOAD_FILES,
        present_files=present_ordered,
        missing_files=missing_files,
        unexpected_files=unexpected_files,
        metadata_errors=tuple(metadata_errors),
        manifest_parse_error=parse_error,
    )


def plan_manifest_verification(
    payload: Mapping[str, object],
    *,
    layout: ArdentStorageLayout | None = None,
) -> ArdentManifestVerificationPlan:
    """Plan future SHA-256 verification tasks from already-loaded metadata."""

    storage_layout = layout or plan_ardent_storage_layout()
    metadata_check = check_manifest_metadata(payload)
    manifest: ArdentDatasetManifest | None = None
    tasks: tuple[ArdentVerificationTask, ...] = ()

    if metadata_check.can_plan_verification_tasks:
        manifest = manifest_from_mapping(payload)
        task_by_file = {
            task.file_name: task
            for task in _verification_tasks_from_manifest(manifest, storage_layout)
        }
        tasks = tuple(
            task_by_file[file_name] for file_name in ARDENT_REQUIRED_DOWNLOAD_FILES
        )

    if metadata_check.manifest_parse_error == "Ardent manifest requires a files array":
        dataset_status = ArdentDatasetStatus.IMPORT_FAILED
        import_state = ArdentImportState.VERIFICATION_FAILED
    elif metadata_check.can_plan_verification_tasks:
        dataset_status = ArdentDatasetStatus.DATASET_PRESENT_UNVERIFIED
        import_state = ArdentImportState.DOWNLOAD_PENDING
    else:
        dataset_status = ArdentDatasetStatus.DATASET_PRESENT_UNVERIFIED
        import_state = ArdentImportState.VERIFICATION_FAILED

    caveats = (
        "Contract-only plan; no Ardent files were downloaded or opened.",
        "Verification tasks describe expected future SHA-256 and size checks only.",
        "A dataset cannot become dataset_verified until verification is recorded.",
    )

    return ArdentManifestVerificationPlan(
        dataset_status=dataset_status,
        import_state=import_state,
        manifest=manifest,
        metadata_check=metadata_check,
        verification_tasks=tasks,
        total_size_bytes=sum(task.expected_size_bytes for task in tasks),
        caveats=caveats,
    )


def evaluate_dataset_staleness(
    *,
    dataset_created_at: str | None,
    imported_at: str | None,
    now: datetime | None = None,
    threshold: timedelta = ARDENT_DEFAULT_STALENESS_THRESHOLD,
) -> ArdentStalenessResult:
    """Evaluate freshness from manifest timestamps without changing usability."""

    checked_at = _normalize_datetime(now or datetime.now(timezone.utc))
    parsed_created_at = _parse_iso_datetime(dataset_created_at)
    parsed_imported_at = _parse_iso_datetime(imported_at)
    threshold_days = max(0, threshold.days)

    if parsed_created_at is None:
        return ArdentStalenessResult(
            freshness=ArdentFreshnessState.UNKNOWN,
            stale=False,
            dataset_status_if_hashes_verified=(
                ArdentDatasetStatus.DATASET_PRESENT_UNVERIFIED
            ),
            dataset_created_at=None,
            imported_at=parsed_imported_at,
            threshold_days=threshold_days,
            caveats=(
                "Missing dataset_created_at means freshness is unknown.",
                "Unknown freshness must be labeled before use.",
            ),
        )

    stale = checked_at - parsed_created_at > threshold
    freshness = ArdentFreshnessState.STALE if stale else ArdentFreshnessState.FRESH
    dataset_status = (
        ArdentDatasetStatus.DATASET_STALE
        if stale
        else ArdentDatasetStatus.DATASET_VERIFIED
    )
    caveats = (
        "Stale imported Ardent data is not automatically unusable.",
        "UI must label stale or unknown freshness clearly.",
        "Weekly cadence is audited planning input, not an availability guarantee.",
    )

    return ArdentStalenessResult(
        freshness=freshness,
        stale=stale,
        dataset_status_if_hashes_verified=dataset_status,
        dataset_created_at=parsed_created_at,
        imported_at=parsed_imported_at,
        threshold_days=threshold_days,
        caveats=caveats,
    )


def source_diagnostics_contract() -> dict[str, str | bool | tuple[str, ...]]:
    """Return future diagnostics metadata without inspecting runtime storage."""

    return {
        "source_id": ARDENT_PROVIDER_ID,
        "source_class": ARDENT_SOURCE_CLASS,
        "provider_status": "disabled",
        "dataset_status": ArdentDatasetStatus.DATASET_MISSING.value,
        "implementation_status": "fixture_only/storage_contract_only",
        "dataset_root": ARDENT_APP_DATA_ROOT_CONTRACT,
        "required_files": ARDENT_REQUIRED_DOWNLOAD_FILES,
        "diagnostics_fields": ARDENT_DIAGNOSTICS_FIELDS,
        "activity_log_future_events": ARDENT_ACTIVITY_LOG_EVENT_TYPES,
        "storage_contract_only": True,
    }


def _manifest_file_metadata_errors(
    index: int,
    payload: Mapping[str, object],
) -> tuple[str, ...]:
    errors: list[str] = []
    _require_string(payload, "expected_sha256", index, errors)
    _require_positive_int(payload, "size_bytes", index, errors)
    _require_created_timestamp(payload, index, errors)
    _require_string(payload, "source_url", index, errors)
    _require_string(payload, "compression", index, errors)
    _require_string(payload, "format", index, errors)
    _require_table_names(payload, index, errors)
    _validate_optional_manifest_hash(payload, index, errors)
    return tuple(errors)


def _require_string(
    payload: Mapping[str, object],
    field_name: str,
    index: int,
    errors: list[str],
) -> None:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        errors.append(f"files[{index}].{field_name} is required")
        return
    if field_name == "expected_sha256" and not _is_sha256(value):
        errors.append(f"files[{index}].expected_sha256 must be 64 hex characters")


def _require_positive_int(
    payload: Mapping[str, object],
    field_name: str,
    index: int,
    errors: list[str],
) -> None:
    value = payload.get(field_name)
    if not isinstance(value, int) or value <= 0:
        errors.append(f"files[{index}].{field_name} must be a positive integer")


def _require_created_timestamp(
    payload: Mapping[str, object],
    index: int,
    errors: list[str],
) -> None:
    created_at = payload.get("dataset_created_at") or payload.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        errors.append(
            f"files[{index}].dataset_created_at or files[{index}].created_at "
            "is required"
        )


def _require_table_names(
    payload: Mapping[str, object],
    index: int,
    errors: list[str],
) -> None:
    value = payload.get("table_names")
    if not isinstance(value, Sequence) or isinstance(value, str):
        errors.append(f"files[{index}].table_names must be a string array")
        return
    if not value:
        errors.append(f"files[{index}].table_names must not be empty")
        return
    for item in value:
        if not isinstance(item, str) or not item:
            errors.append(f"files[{index}].table_names must contain strings")
            return


def _validate_optional_manifest_hash(
    payload: Mapping[str, object],
    index: int,
    errors: list[str],
) -> None:
    value = payload.get("manifest_hash")
    if value is None:
        return
    if not isinstance(value, str) or not _is_sha256(value):
        errors.append(f"files[{index}].manifest_hash must be 64 hex characters")


def _verification_tasks_from_manifest(
    manifest: ArdentDatasetManifest,
    layout: ArdentStorageLayout,
) -> tuple[ArdentVerificationTask, ...]:
    return tuple(
        ArdentVerificationTask(
            file_name=file_contract.file_name,
            expected_sha256=file_contract.expected_sha256,
            expected_size_bytes=file_contract.size_bytes,
            dataset_created_at=file_contract.dataset_created_at,
            source_url=file_contract.source_url,
            staging_path=layout.staging / file_contract.file_name,
            imported_path=layout.imported / file_contract.file_name,
            manifest_hash=file_contract.manifest_hash,
        )
        for file_contract in manifest.files
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in _HEX_CHARS for char in value)


def _ordered_files(file_names: Sequence[str]) -> tuple[str, ...]:
    known = tuple(
        file_name
        for file_name in ARDENT_REQUIRED_DOWNLOAD_FILES
        if file_name in file_names
    )
    unknown = tuple(
        sorted(
            {
                file_name
                for file_name in file_names
                if file_name not in ARDENT_REQUIRED_DOWNLOAD_FILES
            }
        )
    )
    return known + unknown


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _normalize_datetime(parsed)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
