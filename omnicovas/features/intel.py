"""Read-only Intel snapshot helpers for PB05-03.

Intel owns known facts only. This first-wave seam reads the existing
StateManager snapshot and field-source metadata without introducing new local
readers, outbound calls, or a parallel provenance registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from omnicovas.core.provenance import (
    EntityRef,
    FieldProvenance,
    FreshnessLabel,
    TruthClass,
)
from omnicovas.core.state_manager import TelemetrySource

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

IntelSectionId = Literal["galaxy", "system", "local", "ship", "personal"]
IntelValue = str | int | float | bool | None

UNKNOWN = "Unknown"
NOT_LOADED = "Not Loaded"
NO_VERIFIED_SOURCE = "No Verified Source"


@dataclass(frozen=True)
class KnownFact:
    """A single fact row suitable for the Intel UI."""

    field_key: str
    label: str
    value: IntelValue
    fallback: str | None
    provenance: FieldProvenance
    caveat: str | None = None
    activity_log_ref: str | None = None

    def payload(self) -> dict[str, Any]:
        """Serialize the public Intel fact shape."""
        return {
            "field_key": self.field_key,
            "label": self.label,
            "value": self.value,
            "fallback": self.fallback,
            "source_id": self.provenance.source_id,
            "freshness_label": self.provenance.freshness_label.value,
            "truth_class": self.provenance.truth_class.value,
            "caveat": self.caveat,
            "observed_at": (
                self.provenance.fetched_at.isoformat()
                if self.provenance.fetched_at is not None
                else None
            ),
            "entity_ref": _entity_ref_payload(self.provenance.entity_ref),
            "activity_log_ref": self.activity_log_ref,
        }


@dataclass(frozen=True)
class IntelSection:
    """A UI-facing Intel fact bucket."""

    section_id: IntelSectionId
    label: str
    facts: tuple[KnownFact, ...]

    def payload(self) -> dict[str, Any]:
        """Serialize the public Intel section shape."""
        return {
            "id": self.section_id,
            "label": self.label,
            "facts": [fact.payload() for fact in self.facts],
        }


@dataclass(frozen=True)
class IntelSnapshot:
    """Read-only first-wave Intel snapshot."""

    generated_at: datetime
    sections: tuple[IntelSection, ...]
    nullprovider_safe: bool = True

    def payload(self) -> dict[str, Any]:
        """Serialize the public Intel snapshot shape."""
        return {
            "generated_at": self.generated_at.isoformat(),
            "sections": [section.payload() for section in self.sections],
            "nullprovider_safe": self.nullprovider_safe,
        }


def snapshot_payload(state: StateManager) -> dict[str, Any]:
    """Return the current Intel snapshot from existing StateManager fields."""
    return build_snapshot(state).payload()


def empty_snapshot_payload() -> dict[str, Any]:
    """Return an honest Intel snapshot when StateManager is unavailable."""
    generated_at = datetime.now().astimezone()
    return IntelSnapshot(
        generated_at=generated_at,
        sections=_build_sections(None),
    ).payload()


def build_snapshot(state: StateManager | None) -> IntelSnapshot:
    """Build the typed Intel snapshot used by the read-only API."""
    generated_at = datetime.now().astimezone()
    return IntelSnapshot(
        generated_at=generated_at,
        sections=_build_sections(state),
    )


def _build_sections(state: StateManager | None) -> tuple[IntelSection, ...]:
    return (
        IntelSection(
            section_id="galaxy",
            label="Galaxy",
            facts=(
                _fallback_fact(
                    field_key="galaxy.context",
                    label="Galaxy context",
                    fallback=NO_VERIFIED_SOURCE,
                    caveat=(
                        "No first-wave verified local galaxy fact is exposed here yet."
                    ),
                ),
            ),
        ),
        IntelSection(
            section_id="system",
            label="System",
            facts=(
                _state_fact(
                    state=state,
                    state_field="current_system",
                    field_key="system.current_system",
                    label="Current system",
                    fallback=NOT_LOADED,
                    entity_kind="system",
                ),
            ),
        ),
        IntelSection(
            section_id="local",
            label="Local",
            facts=(
                _state_fact(
                    state=state,
                    state_field="current_station",
                    field_key="local.current_station",
                    label="Current station",
                    fallback=NOT_LOADED,
                    entity_kind="station",
                ),
                _state_fact(
                    state=state,
                    state_field="is_docked",
                    field_key="local.docked_state",
                    label="Docked",
                    fallback=UNKNOWN,
                    entity_kind="station",
                ),
            ),
        ),
        IntelSection(
            section_id="ship",
            label="Ship",
            facts=(
                _state_fact(
                    state=state,
                    state_field="current_ship_type",
                    field_key="ship.type",
                    label="Ship type",
                    fallback=NOT_LOADED,
                    entity_kind="ship",
                ),
                _state_fact(
                    state=state,
                    state_field="current_ship_name",
                    field_key="ship.name",
                    label="Ship name",
                    fallback=NOT_LOADED,
                    entity_kind="ship",
                ),
                _state_fact(
                    state=state,
                    state_field="current_ship_ident",
                    field_key="ship.ident",
                    label="Ship ident",
                    fallback=NOT_LOADED,
                    entity_kind="ship",
                ),
                _state_fact(
                    state=state,
                    state_field="jump_range_ly",
                    field_key="ship.jump_range_ly",
                    label="Jump range",
                    fallback=NOT_LOADED,
                    entity_kind="ship",
                ),
            ),
        ),
        IntelSection(
            section_id="personal",
            label="Personal",
            facts=(
                _state_fact(
                    state=state,
                    state_field="commander_name",
                    field_key="personal.commander_name",
                    label="Commander",
                    fallback=NOT_LOADED,
                    entity_kind="commander",
                ),
            ),
        ),
    )


def _state_fact(
    *,
    state: StateManager | None,
    state_field: str,
    field_key: str,
    label: str,
    fallback: str,
    entity_kind: str,
) -> KnownFact:
    value: IntelValue = None
    provenance = _unknown_provenance()

    if state is not None:
        snapshot = state.snapshot
        value = getattr(snapshot, state_field, None)
        field_source = state.get_field_source(state_field)
        if value is not None and field_source is not None:
            provenance = _provenance_for_field(
                source=field_source.source,
                timestamp=field_source.timestamp,
                entity_kind=entity_kind,
                value=value,
            )
        elif value is not None:
            provenance = FieldProvenance(
                source_id="state_manager",
                call_type="state_manager",
                fetched_at=None,
                freshness_label=FreshnessLabel.UNKNOWN_FRESHNESS,
                truth_class=TruthClass.UNKNOWN,
                entity_ref=_entity_ref(entity_kind, value),
            )

    return KnownFact(
        field_key=field_key,
        label=label,
        value=value,
        fallback=None if value is not None else fallback,
        provenance=provenance,
    )


def _fallback_fact(
    *,
    field_key: str,
    label: str,
    fallback: str,
    caveat: str | None = None,
) -> KnownFact:
    return KnownFact(
        field_key=field_key,
        label=label,
        value=None,
        fallback=fallback,
        caveat=caveat,
        provenance=_unknown_provenance(),
    )


def _unknown_provenance() -> FieldProvenance:
    return FieldProvenance(
        source_id="unknown",
        call_type="unknown",
        fetched_at=None,
        freshness_label=FreshnessLabel.UNKNOWN_FRESHNESS,
        truth_class=TruthClass.UNKNOWN,
        entity_ref=None,
    )


def _provenance_for_field(
    *,
    source: TelemetrySource,
    timestamp: str | None,
    entity_kind: str,
    value: IntelValue,
) -> FieldProvenance:
    source_id, call_type = _source_labels(source)
    return FieldProvenance(
        source_id=source_id,
        call_type=call_type,
        fetched_at=_parse_timestamp(timestamp),
        freshness_label=FreshnessLabel.LOCAL_ONLY,
        truth_class=_truth_class_for_source(source),
        entity_ref=_entity_ref(entity_kind, value),
    )


def _source_labels(source: TelemetrySource) -> tuple[str, str]:
    if source == TelemetrySource.JOURNAL:
        return ("local_journal", "local_journal")
    if source == TelemetrySource.STATUS_JSON:
        return ("status_json", "status_json")
    if source == TelemetrySource.CAPI:
        return ("capi", "capi")
    if source == TelemetrySource.EDDN:
        return ("eddn", "eddn")
    return ("inferred", "inferred")


def _truth_class_for_source(source: TelemetrySource) -> TruthClass:
    if source in (TelemetrySource.JOURNAL, TelemetrySource.STATUS_JSON):
        return TruthClass.LOCAL_TELEMETRY
    if source == TelemetrySource.CAPI:
        return TruthClass.VERIFIED_EXTERNAL
    if source == TelemetrySource.EDDN:
        return TruthClass.UNVERIFIED_EXTERNAL
    return TruthClass.UNKNOWN


def _entity_ref(entity_kind: str, value: IntelValue) -> EntityRef | None:
    if isinstance(value, bool):
        return None
    if value is None:
        return None
    entity_id = str(value).strip()
    if not entity_id:
        return None
    return EntityRef(
        entity_type=entity_kind,
        entity_id=entity_id,
        display_name=entity_id,
    )


def _entity_ref_payload(entity_ref: EntityRef | None) -> dict[str, str | None] | None:
    if entity_ref is None:
        return None
    return {
        "entity_type": entity_ref.entity_type,
        "entity_id": entity_ref.entity_id,
        "display_name": entity_ref.display_name,
    }


def _parse_timestamp(timestamp: str | None) -> datetime | None:
    if not isinstance(timestamp, str) or not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
