"""Provider lookup logic (disabled skeleton only).

This module contains inert external provider definitions for source-routing
visibility. Provider rows are status/audit vocabulary only unless an existing
repo/source-authority capability was already registered before PB06-02.

No outbound calls are made here. No network clients are imported.
"""

from __future__ import annotations

from omnicovas.core.activity_log import ActivityLog, log_external_request_blocked
from omnicovas.core.source_registry import (
    SourceCapability,
    SourceDefinition,
    SourceMetadata,
    SourceRegistry,
    SourceState,
)
from omnicovas.core.source_router import SourceRouter
from omnicovas.features.ardent_dataset_contract import (
    ARDENT_DATASET_KIND,
    ARDENT_SOURCE_CLASS,
    ArdentDatasetStatus,
    ArdentImplementationStatus,
)
from omnicovas.features.ardent_dataset_downloader_shell import (
    AUTO_UPDATE_AVAILABLE,
    DOWNLOADER_AVAILABLE,
    DOWNLOADER_ENABLED,
    IMPORTER_AVAILABLE,
    REQUIRES_COMMANDER_APPROVAL,
)
from omnicovas.features.ardent_dataset_manual_import_shell import (
    MANUAL_IMPORT_DESIGN_AVAILABLE,
    MANUAL_IMPORT_EXECUTION_AVAILABLE,
)
from omnicovas.features.ardent_dataset_storage_plan import (
    ARDENT_ACTIVITY_LOG_EVENT_TYPES,
    ARDENT_APP_DATA_ROOT_CONTRACT,
    ARDENT_DIAGNOSTICS_FIELDS,
    ARDENT_STORAGE_DIRECTORIES,
    ARDENT_STORAGE_SAFETY_RULES,
)

EMPTY_CAPABILITIES: frozenset[SourceCapability] = frozenset()

ARDENT_DESCRIPTION_LINES = (
    "Future imported dataset of community-observed market/system/service data.",
    "Stored locally only after Commander-approved import.",
    "Not local Frontier telemetry.",
    "Not live.",
    "Not guaranteed complete.",
    "Local Journal, Status.json, and companion JSON always take precedence.",
)

ARDENT_DATASET_METADATA: SourceMetadata = {
    "id": "ardent",
    "source_class": ARDENT_SOURCE_CLASS,
    "dataset_kind": ARDENT_DATASET_KIND,
    "mode": "downloadable_db",
    "status": "disabled",
    "dataset_status": ArdentDatasetStatus.DATASET_MISSING.value,
    "implementation_status": ArdentImplementationStatus.FIXTURE_ONLY.value,
    "implementation_posture_composite": (
        "fixture_only / storage_contract"
        " / downloader_shell / manual_import_validation_shell_only"
    ),
    "outbound_default": False,
    "local_queries_available": False,
    "https_api_enabled": False,
    "downloader_enabled": DOWNLOADER_ENABLED,
    "downloader_available": DOWNLOADER_AVAILABLE,
    "importer_enabled": False,
    "importer_available": IMPORTER_AVAILABLE,
    "auto_update_available": AUTO_UPDATE_AVAILABLE,
    "requires_commander_approval": REQUIRES_COMMANDER_APPROVAL,
    "query_engine_enabled": False,
    "fixture_queries_available": True,
    "fixture_query_only": True,
    "storage_contract_only": True,
    "manual_import_design_available": MANUAL_IMPORT_DESIGN_AVAILABLE,
    "manual_import_execution_available": MANUAL_IMPORT_EXECUTION_AVAILABLE,
    "requires_compliance_review_before_execution": True,
    "dataset_root_contract": ARDENT_APP_DATA_ROOT_CONTRACT,
    "storage_directories": ARDENT_STORAGE_DIRECTORIES,
    "future_diagnostics_fields": ARDENT_DIAGNOSTICS_FIELDS,
    "future_activity_log_events": ARDENT_ACTIVITY_LOG_EVENT_TYPES,
    "storage_safety_rules": ARDENT_STORAGE_SAFETY_RULES,
    "description_lines": ARDENT_DESCRIPTION_LINES,
}

ARDENT_DATASET_DESCRIPTION = " ".join(ARDENT_DESCRIPTION_LINES)

PHASE6_EXTERNAL_PROVIDER_IDS = (
    "ardent",
    "edsm",
    "capi",
    "eddn",
    "inara",
    "spansh",
    "edastro",
    "elitebgs",
    "external_web_tools",
)


def _register_inert_provider(
    registry: SourceRegistry,
    *,
    source_id: str,
    display_name: str,
    description: str,
    state: SourceState,
    requires_auth: bool,
    requires_consent: bool,
    capabilities: frozenset[SourceCapability] = EMPTY_CAPABILITIES,
    metadata: SourceMetadata | None = None,
) -> None:
    """Register a non-callable external source row."""
    registry.register(
        SourceDefinition(
            source_id=source_id,
            display_name=display_name,
            description=description,
            capabilities=capabilities,
            state=state,
            is_local=False,
            requires_auth=requires_auth,
            requires_consent=requires_consent,
            metadata=dict(metadata or {}),
        )
    )


def register_providers(registry: SourceRegistry) -> None:
    """Register external providers as disabled/requires-auth in the source registry."""
    _register_inert_provider(
        registry,
        source_id="ardent",
        display_name="Ardent imported dataset",
        description=ARDENT_DATASET_DESCRIPTION,
        state=SourceState.DISABLED,
        requires_auth=False,
        requires_consent=False,
        metadata=ARDENT_DATASET_METADATA,
    )
    _register_inert_provider(
        registry,
        source_id="edsm",
        display_name="EDSM",
        description="Elite Dangerous Star Map (Disabled pending authorization)",
        capabilities=frozenset(
            {
                SourceCapability.SYSTEM_FACTION,
                SourceCapability.STAR_DATA,
                SourceCapability.BODY_DATA,
                SourceCapability.TRAFFIC,
            }
        ),
        state=SourceState.REQUIRES_AUTH,
        requires_auth=True,
        requires_consent=True,
    )
    _register_inert_provider(
        registry,
        source_id="capi",
        display_name="Frontier CAPI",
        description=(
            "Requires authorization; disabled for Phase 6 local-only baseline."
        ),
        state=SourceState.REQUIRES_AUTH,
        requires_auth=True,
        requires_consent=True,
    )
    _register_inert_provider(
        registry,
        source_id="eddn",
        display_name="EDDN",
        description=(
            "Disabled for Phase 6 local-only baseline; no read, cache, or "
            "submission path is active."
        ),
        state=SourceState.DISABLED,
        requires_auth=False,
        requires_consent=True,
    )
    _register_inert_provider(
        registry,
        source_id="inara",
        display_name="Inara",
        description=(
            "Requires authorization; disabled for Phase 6 local-only baseline."
        ),
        state=SourceState.REQUIRES_AUTH,
        requires_auth=True,
        requires_consent=True,
    )
    _register_inert_provider(
        registry,
        source_id="spansh",
        display_name="Spansh",
        description=(
            "Disabled for Phase 6 local-only baseline; no expanded source path "
            "is active."
        ),
        state=SourceState.DISABLED,
        requires_auth=False,
        requires_consent=False,
    )
    _register_inert_provider(
        registry,
        source_id="edastro",
        display_name="EDAstro",
        description="Elite Dangerous Astrometrics (Disabled pending authorization)",
        capabilities=frozenset(
            {
                SourceCapability.ROUTE_PLANNING,
            }
        ),
        state=SourceState.REQUIRES_AUTH,
        requires_auth=True,
        requires_consent=True,
    )
    _register_inert_provider(
        registry,
        source_id="elitebgs",
        display_name="EliteBGS",
        description=(
            "Disabled for Phase 6 local-only baseline; future provider-specific "
            "Commander playbook required."
        ),
        state=SourceState.DISABLED,
        requires_auth=False,
        requires_consent=False,
    )
    _register_inert_provider(
        registry,
        source_id="external_web_tools",
        display_name="External Web Tools",
        description=(
            "Disabled for Phase 6 local-only baseline; no scraping, import, "
            "export, or expanded link workflow is active."
        ),
        state=SourceState.DISABLED,
        requires_auth=False,
        requires_consent=False,
    )


def attempt_blocked_lookup(
    router: SourceRouter,
    activity_log: ActivityLog,
    call_type: str,
    workflow_id: str,
    source_id: str | None = None,
) -> dict[str, str]:
    """This function represents a blocked-only provider boundary.

    It consults SourceRouter for the disabled/requires-auth fallback, records
    blocked proof, and returns a safe blocked response. It never queues,
    dispatches, retries, or performs a provider call.
    """
    decision = router.resolve(call_type=call_type, workflow_id=workflow_id)

    if not decision.is_supported:
        log_external_request_blocked(
            activity_log=activity_log,
            source_id=source_id or decision.plan.primary_source_id or "unknown",
            call_type=call_type,
            workflow_id=workflow_id,
            blocked_reason=decision.reason,
        )

    return {
        "status": "blocked",
        "reason": decision.reason,
        "fallback_decision": decision.plan.fallback_decision.value,
    }
