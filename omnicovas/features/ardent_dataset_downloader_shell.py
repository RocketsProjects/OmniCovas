"""Inert Ardent downloader/importer disabled shell for PB-ARD-04B.

This module exposes future downloader/importer posture as a disabled shell only.
It does not download, import, query, open databases, make network requests, or
mutate the filesystem. No production implementation exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from omnicovas.features.ardent_dataset_contract import (
    ArdentDatasetStatus,
    ArdentImplementationStatus,
)
from omnicovas.features.ardent_dataset_storage_plan import (
    ARDENT_ACTIVITY_LOG_EVENT_TYPES,
    ARDENT_REQUIRED_DOWNLOAD_FILES,
    ArdentStorageLayout,
)


class ArdentDownloaderState(str, Enum):
    """Downloader/importer state vocabulary for the future Ardent import path."""

    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    NOT_CONFIGURED = "not_configured"
    NOT_IMPLEMENTED = "not_implemented"
    READY_REQUIRES_COMMANDER_APPROVAL = "ready_requires_commander_approval"
    BLOCKED_BY_COMPLIANCE = "blocked_by_compliance"
    BLOCKED_BY_MISSING_MANIFEST = "blocked_by_missing_manifest"
    BLOCKED_BY_MISSING_STORAGE_ROOT = "blocked_by_missing_storage_root"


# ---------------------------------------------------------------------------
# Capability flags — all disabled/inert
# ---------------------------------------------------------------------------

DOWNLOADER_ENABLED: bool = False
IMPORTER_ENABLED: bool = False
DOWNLOADER_AVAILABLE: bool = False
IMPORTER_AVAILABLE: bool = False
MANUAL_IMPORT_AVAILABLE: bool = False
AUTO_UPDATE_AVAILABLE: bool = False
REQUIRES_COMMANDER_APPROVAL: bool = True

CURRENT_DOWNLOADER_STATE: ArdentDownloaderState = ArdentDownloaderState.NOT_IMPLEMENTED

# ---------------------------------------------------------------------------
# Disabled reasons
# ---------------------------------------------------------------------------

ARDENT_DOWNLOADER_DISABLED_REASON: str = (
    "No downloader or importer is implemented. "
    "Ardent dataset download and import require future Commander-approved "
    "implementation with compliance review accepted."
)

ARDENT_DOWNLOADER_DISABLED_REASONS: tuple[str, ...] = (
    "Downloader not implemented (PB-ARD-04B disabled shell only).",
    "Importer not implemented.",
    "Commander explicit enablement required before any download.",
    "Compliance review must be accepted before any download.",
    "Storage root under app-data must be confirmed.",
    "Manifest must be downloaded or manually supplied.",
    "SHA-256 verification must be planned and recorded.",
    "Disk-space check must pass before any download.",
    "Confirmation Gate or user confirmation required before download/import.",
)

# ---------------------------------------------------------------------------
# Future safety gates (planning constants only; no implementation here)
# ---------------------------------------------------------------------------

ARDENT_FUTURE_SAFETY_GATES: tuple[str, ...] = (
    "gate.commander_explicit_enablement_required",
    "gate.compliance_review_accepted",
    "gate.storage_root_confirmed_under_app_data",
    "gate.manifest_present_downloaded_or_manual",
    "gate.sha256_verification_passed",
    "gate.disk_space_check_passed",
    "gate.no_repo_storage",
    "gate.activity_log_import_event_recorded",
    "gate.sources_diagnostics_dataset_displayed",
    "gate.confirmation_gate_or_user_confirmation_before_download_import",
)

# ---------------------------------------------------------------------------
# Future Activity Log event names
# ---------------------------------------------------------------------------

ARDENT_DOWNLOADER_ACTIVITY_LOG_EVENTS: tuple[str, ...] = ARDENT_ACTIVITY_LOG_EVENT_TYPES

# ---------------------------------------------------------------------------
# Required manifest fields for a valid future download/import
# ---------------------------------------------------------------------------

ARDENT_REQUIRED_MANIFEST_FIELDS: tuple[str, ...] = (
    "file_name",
    "expected_sha256",
    "size_bytes",
    "dataset_created_at",
    "source_url",
    "compression",
    "format",
    "table_names",
)

# ---------------------------------------------------------------------------
# Inert capability report dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArdentDownloaderCapabilityReport:
    """Inert capability report for the downloader/importer disabled shell."""

    downloader_state: ArdentDownloaderState
    downloader_enabled: bool
    importer_enabled: bool
    downloader_available: bool
    importer_available: bool
    manual_import_available: bool
    auto_update_available: bool
    requires_commander_approval: bool
    dataset_status: ArdentDatasetStatus
    implementation_status: ArdentImplementationStatus
    provider_status: str
    disabled_reason: str
    future_gates: tuple[str, ...]
    future_activity_log_events: tuple[str, ...]


# ---------------------------------------------------------------------------
# Pure planning functions (no network, no filesystem mutation, no DB access)
# ---------------------------------------------------------------------------


def planned_download_filenames() -> tuple[str, ...]:
    """Return the planned download filenames without accessing the filesystem."""
    return ARDENT_REQUIRED_DOWNLOAD_FILES


def planned_app_data_target_paths(layout: ArdentStorageLayout) -> tuple[Path, ...]:
    """Return planned app-data download target paths without creating them."""
    return tuple(
        layout.downloads / file_name for file_name in ARDENT_REQUIRED_DOWNLOAD_FILES
    )


def downloader_disabled_reason() -> str:
    """Return the human-readable disabled reason for this shell."""
    return ARDENT_DOWNLOADER_DISABLED_REASON


def future_activity_log_event_names() -> tuple[str, ...]:
    """Return the planned Activity Log event names for a future download/import."""
    return ARDENT_DOWNLOADER_ACTIVITY_LOG_EVENTS


def future_confirmation_requirement() -> str:
    """Return the planned confirmation requirement description."""
    return (
        "Future download and import require explicit Commander confirmation "
        "via Confirmation Gate before any network request or filesystem write."
    )


def future_checksum_verification_plan() -> tuple[str, ...]:
    """Return the planned checksum verification steps (no implementation)."""
    return (
        "Download each gz artifact to the staging directory.",
        "Verify SHA-256 hash matches the manifest expected_sha256 field.",
        "Verify file size matches the manifest size_bytes field.",
        "Record verified_at and manifest_hash on success.",
        "Move verified staging artifacts to the imported directory atomically.",
        "Move failed or unverified artifacts to quarantine or remove them.",
        "Record ardent.verify_started and ardent.verify_failed "
        "or ardent.import_completed.",
    )


def required_manifest_fields() -> tuple[str, ...]:
    """Return the required manifest fields for a valid download/import."""
    return ARDENT_REQUIRED_MANIFEST_FIELDS


def future_safety_gates() -> tuple[str, ...]:
    """Return the gate identifiers that must pass before download/import."""
    return ARDENT_FUTURE_SAFETY_GATES


def downloader_capability_report() -> ArdentDownloaderCapabilityReport:
    """Return the full inert capability report for the downloader shell."""
    return ArdentDownloaderCapabilityReport(
        downloader_state=CURRENT_DOWNLOADER_STATE,
        downloader_enabled=DOWNLOADER_ENABLED,
        importer_enabled=IMPORTER_ENABLED,
        downloader_available=DOWNLOADER_AVAILABLE,
        importer_available=IMPORTER_AVAILABLE,
        manual_import_available=MANUAL_IMPORT_AVAILABLE,
        auto_update_available=AUTO_UPDATE_AVAILABLE,
        requires_commander_approval=REQUIRES_COMMANDER_APPROVAL,
        dataset_status=ArdentDatasetStatus.DATASET_MISSING,
        implementation_status=ArdentImplementationStatus.FIXTURE_ONLY,
        provider_status="disabled",
        disabled_reason=ARDENT_DOWNLOADER_DISABLED_REASON,
        future_gates=ARDENT_FUTURE_SAFETY_GATES,
        future_activity_log_events=ARDENT_DOWNLOADER_ACTIVITY_LOG_EVENTS,
    )
