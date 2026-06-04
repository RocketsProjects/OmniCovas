"""Inert Ardent manual-import validation shell for PB-ARD-05.

CRR-011 compliance gate: PB-ARD-05 is allowed only as a manual-import
validation shell + inert contract. Real import, download, execution, SQLite
parsing, HTTPS API use, and source-router dispatch remain blocked.

This module is pure and validation-only. It does not and must not:
    - execute import or download
    - read, hash, open, or unpack files from disk
    - create directories or write files
    - connect to databases
    - make network requests
    - dispatch source-router calls
    - enable any runtime provider or query behavior
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from omnicovas.features.ardent_dataset_contract import (
    ARDENT_PROVIDER_ID,
    ARDENT_SOURCE_CLASS,
    FORBIDDEN_FIXTURE_SUFFIXES,
    FORBIDDEN_REAL_DB_FILE_NAMES,
    ArdentDatasetStatus,
    ArdentImplementationStatus,
)
from omnicovas.features.ardent_dataset_storage_plan import (
    ARDENT_APP_DATA_ROOT_CONTRACT,
    ARDENT_REQUIRED_DOWNLOAD_FILES,
    ArdentFreshnessState,
    evaluate_dataset_staleness,
)

# ---------------------------------------------------------------------------
# Status vocabulary
# ---------------------------------------------------------------------------


class ArdentImportShellStatus(str, Enum):
    """Status vocabulary for the manual import validation shell."""

    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    DESIGN_SHELL_ONLY = "design_shell_only"
    REQUIRES_COMMANDER_CONFIRMATION = "requires_commander_confirmation"
    BLOCKED_BY_COMPLIANCE_FOR_EXECUTION = "blocked_by_compliance_for_execution"
    BLOCKED_BY_MISSING_MANIFEST = "blocked_by_missing_manifest"
    BLOCKED_BY_MISSING_FILES = "blocked_by_missing_files"
    BLOCKED_BY_UNVERIFIED_HASHES = "blocked_by_unverified_hashes"
    BLOCKED_BY_REPO_STORAGE = "blocked_by_repo_storage"
    VALIDATION_PLAN_READY = "validation_plan_ready"


# ---------------------------------------------------------------------------
# Capability flags — all execution paths disabled
# ---------------------------------------------------------------------------

MANUAL_IMPORT_DESIGN_AVAILABLE: bool = True
MANUAL_IMPORT_EXECUTION_AVAILABLE: bool = False
REQUIRES_COMMANDER_CONFIRMATION: bool = True
REQUIRES_ACTIVITY_LOG: bool = True
REQUIRES_SOURCES_DIAGNOSTICS: bool = True
REQUIRES_NO_REPO_STORAGE: bool = True
COMPLIANCE_REVIEW_SCOPE: str = "design_shell_only"

MANUAL_IMPORT_ENABLED: bool = False
MANUAL_IMPORT_AVAILABLE: bool = False
PRODUCTION_IMPORT_AVAILABLE: bool = False
DOWNLOADER_ENABLED: bool = False
LOCAL_QUERIES_AVAILABLE: bool = False
QUERY_ENGINE_ENABLED: bool = False
HTTPS_API_ENABLED: bool = False
OUTBOUND_DEFAULT: bool = False

CURRENT_SHELL_STATUS: ArdentImportShellStatus = (
    ArdentImportShellStatus.DESIGN_SHELL_ONLY
)

# ---------------------------------------------------------------------------
# Activity Log event contract
# ---------------------------------------------------------------------------


class ArdentImportActivityLogEvent(str, Enum):
    """Future Activity Log event name constants for the manual import path."""

    ARDENT_IMPORT_VALIDATION_REQUESTED = "ARDENT_IMPORT_VALIDATION_REQUESTED"
    ARDENT_IMPORT_VALIDATION_BLOCKED = "ARDENT_IMPORT_VALIDATION_BLOCKED"
    ARDENT_IMPORT_CONFIRMATION_REQUIRED = "ARDENT_IMPORT_CONFIRMATION_REQUIRED"
    ARDENT_IMPORT_STARTED = "ARDENT_IMPORT_STARTED"
    ARDENT_IMPORT_FAILED = "ARDENT_IMPORT_FAILED"
    ARDENT_IMPORT_COMPLETED = "ARDENT_IMPORT_COMPLETED"
    ARDENT_IMPORT_REJECTED_REPO_STORAGE = "ARDENT_IMPORT_REJECTED_REPO_STORAGE"
    ARDENT_IMPORT_REJECTED_HASH_MISMATCH = "ARDENT_IMPORT_REJECTED_HASH_MISMATCH"
    ARDENT_IMPORT_REJECTED_LICENSE_GATE = "ARDENT_IMPORT_REJECTED_LICENSE_GATE"
    ARDENT_IMPORT_REJECTED_MISSING_MANIFEST = "ARDENT_IMPORT_REJECTED_MISSING_MANIFEST"


ARDENT_IMPORT_ACTIVITY_LOG_EVENT_NAMES: tuple[str, ...] = tuple(
    e.value for e in ArdentImportActivityLogEvent
)

# ---------------------------------------------------------------------------
# Caller-supplied candidate file metadata (no disk access)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArdentCandidateFileMetadata:
    """Caller-supplied metadata for one candidate import file; no disk reads."""

    file_name: str
    size_bytes: int
    candidate_path: str
    sha256: str | None = None
    table_names: tuple[str, ...] = ()
    dataset_created_at: str | None = None


# ---------------------------------------------------------------------------
# Validation plan result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArdentImportValidationPlan:
    """Pure validation plan built from explicit metadata; no filesystem access."""

    shell_status: ArdentImportShellStatus
    required_files: tuple[str, ...]
    candidate_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    unverified_files: tuple[str, ...]
    rejected_files: tuple[str, ...]
    planned_app_data_targets: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    confirmation_required: bool
    activity_log_event_names: tuple[str, ...]
    total_size_bytes: int
    dataset_created_at: str | None
    stale: bool | None
    caveats: tuple[str, ...]
    execution_available: bool
    can_build_validation_plan: bool


# ---------------------------------------------------------------------------
# Confirmation / consent contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArdentConfirmationContract:
    """Pure data contract for future Ardent import Commander confirmation."""

    source: str
    source_class: str
    action_type: str
    status: str
    warning: str
    storage_root: str
    no_repo_storage_required: bool
    sha256_verification_required: bool
    attribution_required: bool
    frontier_non_endorsement_required: bool
    activity_log_required: bool
    commander_initiated_required: bool


# ---------------------------------------------------------------------------
# Sources & Diagnostics contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArdentSourcesDiagnosticsContract:
    """Pure metadata structure for future Sources & Diagnostics surface."""

    source_id: str
    source_class: str
    provider_status: str
    dataset_status: str
    implementation_status: str
    manual_import_design_status: str
    storage_root: str
    required_files: tuple[str, ...]
    candidate_files: tuple[str, ...]
    missing_files: tuple[str, ...]
    unverified_files: tuple[str, ...]
    rejected_files: tuple[str, ...]
    total_size_bytes: int | None
    dataset_created_at: str | None
    imported_at: str | None
    verified_at: str | None
    stale: bool | None
    caveats: tuple[str, ...]
    blocked_reasons: tuple[str, ...]


# ---------------------------------------------------------------------------
# Attribution / non-endorsement contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArdentAttributionNotice:
    """Structured attribution and non-endorsement requirements for Ardent data."""

    ardent_attribution_required: bool
    eddn_attribution_required: bool
    edsm_spansh_eddb_attribution_required: bool
    frontier_non_endorsement_required: bool
    community_observed_wording_required: bool
    not_live: bool
    not_guaranteed_complete: bool
    not_official_frontier_data: bool
    attribution_notes: tuple[str, ...]


# ---------------------------------------------------------------------------
# Capability report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArdentManualImportCapabilityReport:
    """Full inert capability report for the manual import shell."""

    shell_status: ArdentImportShellStatus
    manual_import_design_available: bool
    manual_import_execution_available: bool
    manual_import_enabled: bool
    production_import_available: bool
    downloader_enabled: bool
    local_queries_available: bool
    query_engine_enabled: bool
    https_api_enabled: bool
    outbound_default: bool
    requires_commander_confirmation: bool
    requires_activity_log: bool
    requires_sources_diagnostics: bool
    requires_no_repo_storage: bool
    compliance_review_scope: str
    provider_status: str
    dataset_status: ArdentDatasetStatus
    implementation_status: ArdentImplementationStatus


# ---------------------------------------------------------------------------
# Caveats and disabled reasons
# ---------------------------------------------------------------------------

ARDENT_MANUAL_IMPORT_CAVEATS: tuple[str, ...] = (
    "Ardent data is community-observed; not live Frontier truth.",
    "Not guaranteed complete.",
    "Local Journal, Status.json, and companion JSON take precedence.",
    "Manual import execution remains blocked pending future Commander approval.",
    "This is a design-shell only; no import has been performed.",
)

ARDENT_MANUAL_IMPORT_BLOCKED_REASONS: tuple[str, ...] = (
    "Manual import execution requires future Commander approval.",
    "Real import execution is blocked by CRR-011 compliance gate (design_shell_only).",
    "No downloader or importer is implemented.",
    "SHA-256 verification must be planned and recorded before any import.",
    "Storage root under app-data must be confirmed.",
    "Manifest must be manually supplied.",
    "Confirmation Gate or user confirmation required before import.",
    "Activity Log event must be recorded for any future import.",
)

# ---------------------------------------------------------------------------
# Pure planning and inspection functions
# ---------------------------------------------------------------------------


def build_validation_plan(
    *,
    manifest_metadata: dict[str, object] | None = None,
    candidate_files: Sequence[ArdentCandidateFileMetadata] = (),
) -> ArdentImportValidationPlan:
    """Build a pure validation plan from explicit metadata only.

    Never reads files, checks path existence, hashes files, creates directories,
    opens databases, makes network calls, or performs any side effect.
    """
    required = ARDENT_REQUIRED_DOWNLOAD_FILES
    targets = _planned_target_strings()

    if manifest_metadata is None:
        return ArdentImportValidationPlan(
            shell_status=ArdentImportShellStatus.BLOCKED_BY_MISSING_MANIFEST,
            required_files=required,
            candidate_files=(),
            missing_files=required,
            unverified_files=(),
            rejected_files=(),
            planned_app_data_targets=targets,
            blocked_reasons=(
                "No manifest metadata supplied.",
                "Manual import execution requires future Commander approval.",
            ),
            confirmation_required=True,
            activity_log_event_names=ARDENT_IMPORT_ACTIVITY_LOG_EVENT_NAMES,
            total_size_bytes=0,
            dataset_created_at=None,
            stale=None,
            caveats=ARDENT_MANUAL_IMPORT_CAVEATS,
            execution_available=False,
            can_build_validation_plan=True,
        )

    candidate_names_set = {f.file_name for f in candidate_files}
    missing_files = tuple(f for f in required if f not in candidate_names_set)
    unverified: list[str] = []
    rejected: list[str] = []
    path_blocked: list[str] = []

    for cfile in candidate_files:
        rejection = _check_candidate_path(cfile.candidate_path)
        if rejection is not None:
            rejected.append(cfile.file_name)
            path_blocked.append(rejection)
        elif cfile.sha256 is None:
            unverified.append(cfile.file_name)

    blocked_reasons: list[str] = list(path_blocked)
    if missing_files:
        blocked_reasons.append("Missing required files: " + ", ".join(missing_files))
    if unverified:
        blocked_reasons.append(
            "Unverified files (no SHA-256): " + ", ".join(unverified)
        )
    blocked_reasons.append(
        "Manual import execution requires future Commander approval."
    )

    total_size = sum(f.size_bytes for f in candidate_files)
    dataset_created_at = next(
        (f.dataset_created_at for f in candidate_files if f.dataset_created_at),
        None,
    )
    stale = _compute_staleness(dataset_created_at)

    if rejected:
        shell_status: ArdentImportShellStatus = (
            ArdentImportShellStatus.BLOCKED_BY_REPO_STORAGE
        )
    elif missing_files:
        shell_status = ArdentImportShellStatus.BLOCKED_BY_MISSING_FILES
    elif unverified:
        shell_status = ArdentImportShellStatus.BLOCKED_BY_UNVERIFIED_HASHES
    else:
        shell_status = ArdentImportShellStatus.VALIDATION_PLAN_READY

    return ArdentImportValidationPlan(
        shell_status=shell_status,
        required_files=required,
        candidate_files=tuple(f.file_name for f in candidate_files),
        missing_files=missing_files,
        unverified_files=tuple(unverified),
        rejected_files=tuple(rejected),
        planned_app_data_targets=targets,
        blocked_reasons=tuple(blocked_reasons),
        confirmation_required=True,
        activity_log_event_names=ARDENT_IMPORT_ACTIVITY_LOG_EVENT_NAMES,
        total_size_bytes=total_size,
        dataset_created_at=dataset_created_at,
        stale=stale,
        caveats=ARDENT_MANUAL_IMPORT_CAVEATS,
        execution_available=False,
        can_build_validation_plan=True,
    )


def validate_candidate_path(
    candidate_path: str,
    *,
    repo_root: str | None = None,
) -> tuple[bool, str | None]:
    """Validate a candidate import path by string analysis only.

    Returns (is_valid, rejection_reason). Never performs filesystem access
    or checks whether paths exist on disk.
    """
    rejection = _check_candidate_path(candidate_path, repo_root=repo_root)
    if rejection is not None:
        return False, rejection
    return True, None


def default_confirmation_contract() -> ArdentConfirmationContract:
    """Return the pure confirmation/consent contract for a future import."""
    return ArdentConfirmationContract(
        source="Ardent imported dataset",
        source_class=ARDENT_SOURCE_CLASS,
        action_type="future_manual_import",
        status="confirmation_required",
        warning=(
            "Community-observed data, not live, not guaranteed complete. "
            "Not official Frontier data."
        ),
        storage_root=ARDENT_APP_DATA_ROOT_CONTRACT,
        no_repo_storage_required=True,
        sha256_verification_required=True,
        attribution_required=True,
        frontier_non_endorsement_required=True,
        activity_log_required=True,
        commander_initiated_required=True,
    )


def activity_log_event_names() -> tuple[str, ...]:
    """Return the future Activity Log event names for the manual import path."""
    return ARDENT_IMPORT_ACTIVITY_LOG_EVENT_NAMES


def sources_diagnostics_contract(
    *,
    candidate_files: Sequence[ArdentCandidateFileMetadata] = (),
    dataset_created_at: str | None = None,
    imported_at: str | None = None,
    verified_at: str | None = None,
) -> ArdentSourcesDiagnosticsContract:
    """Return a pure diagnostics metadata structure for a future UI surface."""
    required = ARDENT_REQUIRED_DOWNLOAD_FILES
    candidate_names = tuple(f.file_name for f in candidate_files)
    candidate_set = set(candidate_names)
    missing = tuple(f for f in required if f not in candidate_set)
    unverified = tuple(f.file_name for f in candidate_files if f.sha256 is None)
    rejected = tuple(
        f.file_name
        for f in candidate_files
        if _check_candidate_path(f.candidate_path) is not None
    )
    total_size: int | None = (
        sum(f.size_bytes for f in candidate_files) if candidate_files else None
    )

    return ArdentSourcesDiagnosticsContract(
        source_id=ARDENT_PROVIDER_ID,
        source_class=ARDENT_SOURCE_CLASS,
        provider_status="disabled",
        dataset_status=ArdentDatasetStatus.DATASET_MISSING.value,
        implementation_status=ArdentImplementationStatus.FIXTURE_ONLY.value,
        manual_import_design_status=ArdentImportShellStatus.DESIGN_SHELL_ONLY.value,
        storage_root=ARDENT_APP_DATA_ROOT_CONTRACT,
        required_files=required,
        candidate_files=candidate_names,
        missing_files=missing,
        unverified_files=unverified,
        rejected_files=rejected,
        total_size_bytes=total_size,
        dataset_created_at=dataset_created_at,
        imported_at=imported_at,
        verified_at=verified_at,
        stale=None,
        caveats=ARDENT_MANUAL_IMPORT_CAVEATS,
        blocked_reasons=ARDENT_MANUAL_IMPORT_BLOCKED_REASONS,
    )


def attribution_notice() -> ArdentAttributionNotice:
    """Return the structured attribution and non-endorsement contract."""
    return ArdentAttributionNotice(
        ardent_attribution_required=True,
        eddn_attribution_required=True,
        edsm_spansh_eddb_attribution_required=True,
        frontier_non_endorsement_required=True,
        community_observed_wording_required=True,
        not_live=True,
        not_guaranteed_complete=True,
        not_official_frontier_data=True,
        attribution_notes=(
            "Ardent attribution required in display and About route.",
            "EDDN attribution required for EDDN-backed data.",
            (
                "EDSM/Spansh/EDDB.io seed-source attribution required "
                "if Ardent wording requires."
            ),
            "Frontier non-endorsement: not official Frontier data.",
            "Community-observed data. Not live. Not guaranteed complete.",
        ),
    )


def manual_import_capability_report() -> ArdentManualImportCapabilityReport:
    """Return the full inert capability report for the manual import shell."""
    return ArdentManualImportCapabilityReport(
        shell_status=CURRENT_SHELL_STATUS,
        manual_import_design_available=MANUAL_IMPORT_DESIGN_AVAILABLE,
        manual_import_execution_available=MANUAL_IMPORT_EXECUTION_AVAILABLE,
        manual_import_enabled=MANUAL_IMPORT_ENABLED,
        production_import_available=PRODUCTION_IMPORT_AVAILABLE,
        downloader_enabled=DOWNLOADER_ENABLED,
        local_queries_available=LOCAL_QUERIES_AVAILABLE,
        query_engine_enabled=QUERY_ENGINE_ENABLED,
        https_api_enabled=HTTPS_API_ENABLED,
        outbound_default=OUTBOUND_DEFAULT,
        requires_commander_confirmation=REQUIRES_COMMANDER_CONFIRMATION,
        requires_activity_log=REQUIRES_ACTIVITY_LOG,
        requires_sources_diagnostics=REQUIRES_SOURCES_DIAGNOSTICS,
        requires_no_repo_storage=REQUIRES_NO_REPO_STORAGE,
        compliance_review_scope=COMPLIANCE_REVIEW_SCOPE,
        provider_status="disabled",
        dataset_status=ArdentDatasetStatus.DATASET_MISSING,
        implementation_status=ArdentImplementationStatus.FIXTURE_ONLY,
    )


# ---------------------------------------------------------------------------
# Private helpers — pure string analysis, no filesystem access
# ---------------------------------------------------------------------------


def _planned_target_strings() -> tuple[str, ...]:
    """Return planned staging target paths as strings; no filesystem calls."""
    staging = ARDENT_APP_DATA_ROOT_CONTRACT + r"\staging"
    return tuple(staging + "\\" + fn for fn in ARDENT_REQUIRED_DOWNLOAD_FILES)


def _check_candidate_path(
    candidate_path: str,
    *,
    repo_root: str | None = None,
) -> str | None:
    """Return a rejection reason string if the path is unsafe; None if acceptable.

    Never reads from disk. Pure string analysis only.
    """
    file_name = _path_basename(candidate_path).lower()
    is_real_db = file_name in FORBIDDEN_REAL_DB_FILE_NAMES or any(
        file_name.endswith(s) for s in FORBIDDEN_FIXTURE_SUFFIXES
    )
    if not is_real_db:
        return None

    normalized = candidate_path.lower().replace("\\", "/")

    if "tests/fixtures" in normalized:
        return (
            f"Candidate path {candidate_path!r} would store a real Ardent DB "
            "file under test fixtures."
        )

    if repo_root is not None:
        repo_normalized = repo_root.lower().replace("\\", "/").rstrip("/")
        prefix = repo_normalized + "/"
        if normalized.startswith(prefix) or normalized == repo_normalized:
            return (
                f"Candidate path {candidate_path!r} would place a real Ardent "
                "DB file inside the repository root."
            )

    return None


def _path_basename(path: str) -> str:
    """Return the final component of a path string; no filesystem calls."""
    normalized = path.replace("\\", "/")
    return normalized.rstrip("/").rsplit("/", 1)[-1]


def _compute_staleness(dataset_created_at: str | None) -> bool | None:
    """Compute staleness from metadata string; no filesystem side effects."""
    if dataset_created_at is None:
        return None
    result = evaluate_dataset_staleness(
        dataset_created_at=dataset_created_at,
        imported_at=None,
    )
    if result.freshness == ArdentFreshnessState.UNKNOWN:
        return None
    return result.stale
