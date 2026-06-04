"""Source registry — typed catalog of data sources and their capabilities.

In-memory only. No outbound calls are made here.

External sources default to DISABLED, REQUIRES_AUTH, REQUIRES_CONSENT, BLOCKED,
or UNKNOWN. Only local sources may be ENABLED, and only where the local-data
authority supports them.

Presence of a SourceCapability enum member indicates the capability is *known*
to the registry routing vocabulary; it does NOT imply any implemented provider
call exists. capability_known_to_registry != implemented_provider_call.

Authority:
    Backend Blueprint v1.0 — source routing contract
    Source Capability Routing Reference v1 — Section 1 (priority rules)
    Master Blueprint v5.0 — Law 5 (Zero Hallucination), Law 7 (Telemetry Rigidity)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class SourceCapability(str, Enum):
    """Routing vocabulary for call-type resolution.

    Each member names a *capability class* that a source may advertise.
    Presence here is routing vocabulary only — it does NOT imply any
    implemented provider call or verified external source exists.
    """

    SYSTEM_FACTION = "system_faction"
    STAR_DATA = "star_data"
    BODY_DATA = "body_data"
    MARKET_DATA = "market_data"
    SHIPYARD = "shipyard"
    OUTFITTING = "outfitting"
    ROUTE_PLANNING = "route_planning"
    TRAFFIC = "traffic"
    COMBAT_LOG = "combat_log"
    EXOBIOLOGY = "exobiology"
    FLEET_CARRIER = "fleet_carrier"
    LOCAL_JOURNAL = "local_journal"
    LOCAL_STATUS = "local_status"
    LOCAL_COMPANION = "local_companion"


class SourceState(str, Enum):
    """Operational state of a registered source."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    REQUIRES_AUTH = "requires_auth"
    REQUIRES_CONSENT = "requires_consent"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


SourceMetadataValue = str | bool | tuple[str, ...]
SourceMetadata = dict[str, SourceMetadataValue]


@dataclass(frozen=True)
class SourceHealth:
    """Point-in-time health snapshot for a registered source."""

    source_id: str
    state: SourceState
    last_checked: datetime | None
    last_success: datetime | None
    error_count: int
    is_available: bool


@dataclass(frozen=True)
class SourceDefinition:
    """Immutable definition of a data source registered with the routing system.

    The capabilities set declares what call-types this source can satisfy.
    state drives router fallback decisions. is_local distinguishes local-file
    sources (always usable offline) from external network sources.
    """

    source_id: str
    display_name: str
    description: str
    capabilities: frozenset[SourceCapability]
    state: SourceState
    is_local: bool
    requires_auth: bool
    requires_consent: bool
    metadata: SourceMetadata = field(default_factory=dict)


class SourceRegistry:
    """In-memory catalog of SourceDefinition and SourceHealth records.

    One instance per process. Definitions are registered at startup;
    health snapshots are updated at runtime without mutating definitions.
    """

    def __init__(self) -> None:
        self._sources: dict[str, SourceDefinition] = {}
        self._health: dict[str, SourceHealth] = {}

    def register(self, definition: SourceDefinition) -> None:
        """Register or replace a source definition."""
        self._sources[definition.source_id] = definition

    def get(self, source_id: str) -> SourceDefinition | None:
        """Return the definition for source_id, or None if not registered."""
        return self._sources.get(source_id)

    def list_all(self) -> list[SourceDefinition]:
        """Return all registered definitions in registration order."""
        return list(self._sources.values())

    def list_by_capability(self, cap: SourceCapability) -> list[SourceDefinition]:
        """Return all definitions that advertise the given capability."""
        return [d for d in self._sources.values() if cap in d.capabilities]

    def update_health(self, health: SourceHealth) -> None:
        """Record a health snapshot for a registered source."""
        self._health[health.source_id] = health

    def get_health(self, source_id: str) -> SourceHealth | None:
        """Return the latest health snapshot for source_id, or None."""
        return self._health.get(source_id)
