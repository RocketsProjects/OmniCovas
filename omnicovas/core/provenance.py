"""Field-level provenance contracts.

Provenance tracks where each sourced field value came from — which source,
which call type, when it was fetched, how fresh it is, and the entity it
describes. No outbound calls are made here.

FreshnessLabel is defined here because freshness is a provenance concept;
source_cache.py imports it from this module.

Authority:
    Backend Blueprint v1.0 — provenance contract (Section K)
    Source Capability Routing Reference v1 — Section 1, Rule 5
    Master Blueprint v5.0 — Law 5 (Zero Hallucination), Principle 6 (KB Stewardship)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class FreshnessLabel(str, Enum):
    """Freshness classification for a cached or sourced value."""

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"
    LOCAL_ONLY = "local_only"
    UNKNOWN_FRESHNESS = "unknown_freshness"


class TruthClass(str, Enum):
    """Confidence classification of a sourced value."""

    LOCAL_TELEMETRY = "local_telemetry"
    VERIFIED_EXTERNAL = "verified_external"
    UNVERIFIED_EXTERNAL = "unverified_external"
    COMMANDER_ENTERED = "commander_entered"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EntityRef:
    """Reference to a game entity used to scope a provenance or cache entry."""

    entity_type: str
    entity_id: str
    display_name: str | None


@dataclass(frozen=True)
class FieldProvenance:
    """Provenance metadata for a single sourced field value."""

    source_id: str
    call_type: str
    fetched_at: datetime | None
    freshness_label: FreshnessLabel
    truth_class: TruthClass
    entity_ref: EntityRef | None


class ProvenanceRegistry:
    """In-memory field-key → FieldProvenance map.

    field_key is caller-defined — typically a dotted path such as
    ``"system.faction"`` or ``"body.atmosphere_type"``.
    """

    def __init__(self) -> None:
        self._records: dict[str, FieldProvenance] = {}

    def set(self, field_key: str, provenance: FieldProvenance) -> None:
        """Record or replace provenance for field_key."""
        self._records[field_key] = provenance

    def get(self, field_key: str) -> FieldProvenance | None:
        """Return provenance for field_key, or None if not set."""
        return self._records.get(field_key)

    def list_all(self) -> dict[str, FieldProvenance]:
        """Return a shallow copy of all provenance records."""
        return dict(self._records)

    def clear(self, field_key: str) -> None:
        """Remove provenance for field_key if present; no-op otherwise."""
        self._records.pop(field_key, None)
