"""Phase 4 combat-state update helpers for the canonical StateManager."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, cast

from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.event_types import COMBAT_STATE_CHANGED
from omnicovas.core.state_manager import (
    CombatField,
    CombatFreshnessState,
    CombatSourceLabel,
    CombatState,
    StateManager,
    TelemetrySource,
)

JOURNAL_SOURCE: CombatSourceLabel = "journal"
INFERRED_SOURCE: CombatSourceLabel = "inferred"
STATUS_SOURCE: CombatSourceLabel = "status"
FRESH: CombatFreshnessState = "fresh"

TARGETED_MODE_HINT = "targeted"
HOSTILE_MODE_HINT = "under_attack"
HOSTILE_CONTEXT_LABEL = "Hostile telemetry detected"

_COMBAT_FIELD_PATHS: tuple[tuple[str, str], ...] = (
    ("target", "ship_type"),
    ("target", "faction"),
    ("target", "legal_status"),
    ("threat", "recent_hostile_events_count"),
    ("threat", "last_hostile_timestamp"),
    ("threat", "under_attack"),
    ("threat", "context_label"),
    ("session", "active"),
    ("session", "mode_hint"),
    ("workflow", "interdiction_active"),
    ("workflow", "interdiction_started_at"),
    ("workflow", "interdiction_ended_at"),
    ("workflow", "escape_outcome"),
)


@dataclass(frozen=True)
class CombatStateUpdate:
    """A committed combat-state change ready for optional broadcast."""

    reason: str
    changed_fields: tuple[str, ...]
    combat: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        return {
            "combat": self.combat,
            "changed_fields": list(self.changed_fields),
            "reason": self.reason,
        }


def snapshot_payload(state: StateManager) -> dict[str, Any]:
    """Return the explicit Phase 4 combat snapshot payload."""
    return {"combat": _combat_payload(state.snapshot.combat)}


def empty_snapshot_payload() -> dict[str, Any]:
    """Return the explicit Phase 4 combat snapshot when state is unavailable."""
    return {"combat": _combat_payload(CombatState())}


def record_ship_targeted(
    event: dict[str, Any],
    state: StateManager,
) -> CombatStateUpdate | None:
    """Record target ship context from an already-recognized ShipTargeted event."""
    ship = event.get("Ship")
    if ship is None:
        return None

    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    combat = deepcopy(before)
    combat.target.ship_type = _field(str(ship), JOURNAL_SOURCE, timestamp)
    combat.session.active = _field(True, INFERRED_SOURCE, timestamp)
    combat.session.mode_hint = _field(
        TARGETED_MODE_HINT,
        INFERRED_SOURCE,
        timestamp,
    )
    return _commit_change(state, before, combat, "ShipTargeted", timestamp)


def record_hull_damage(
    event: dict[str, Any],
    state: StateManager,
) -> CombatStateUpdate | None:
    """Record hostile telemetry from an already-recognized HullDamage event."""
    if event.get("Health") is None:
        return None

    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    combat = deepcopy(before)
    combat.threat.recent_hostile_events_count = _field(
        _recent_hostile_count(combat) + 1,
        INFERRED_SOURCE,
        timestamp,
    )
    combat.threat.last_hostile_timestamp = _field(
        timestamp,
        JOURNAL_SOURCE,
        timestamp,
    )
    combat.threat.under_attack = _field(True, INFERRED_SOURCE, timestamp)
    combat.threat.context_label = _field(
        HOSTILE_CONTEXT_LABEL,
        INFERRED_SOURCE,
        timestamp,
    )
    combat.session.active = _field(True, INFERRED_SOURCE, timestamp)
    combat.session.mode_hint = _field(HOSTILE_MODE_HINT, INFERRED_SOURCE, timestamp)
    return _commit_change(state, before, combat, "HullDamage", timestamp)


def record_session_boundary(
    event: dict[str, Any],
    state: StateManager,
) -> CombatStateUpdate | None:
    """Mark combat session focus inactive at a recognized session boundary."""
    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    combat = deepcopy(before)
    combat.threat.under_attack = _field(False, INFERRED_SOURCE, timestamp)
    combat.threat.context_label = _field(None, INFERRED_SOURCE, timestamp)
    combat.session.active = _field(False, INFERRED_SOURCE, timestamp)
    combat.session.mode_hint = _field(None, INFERRED_SOURCE, timestamp)
    reason = str(event.get("event") or "SessionBoundary")
    return _commit_change(state, before, combat, reason, timestamp)


def record_interdiction_boundary_clear(
    event: dict[str, Any],
    state: StateManager,
) -> CombatStateUpdate | None:
    """Clear active interdiction state at a session boundary (FSDJump, Docked).

    Returns None immediately if no interdiction is active so callers can
    skip broadcaster/log work cheaply.
    """
    if state.snapshot.combat.workflow.interdiction_active.value is not True:
        return None
    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    combat = deepcopy(before)
    combat.workflow.interdiction_active = _field(False, INFERRED_SOURCE, timestamp)
    combat.workflow.interdiction_ended_at = _field(
        timestamp, INFERRED_SOURCE, timestamp
    )
    combat.workflow.escape_outcome = _field("unknown", INFERRED_SOURCE, timestamp)
    reason = str(event.get("event") or "SessionBoundary")
    return _commit_change(
        state, before, combat, f"InterdictionBoundary:{reason}", timestamp
    )


def record_interdiction_started(
    event: dict[str, Any],
    state: StateManager,
) -> CombatStateUpdate | None:
    """Record interdiction start from a Status.json BeingInterdicted event."""
    if state.snapshot.combat.workflow.interdiction_active.value is True:
        return None
    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    combat = deepcopy(before)
    combat.workflow.interdiction_active = _field(True, STATUS_SOURCE, timestamp)
    combat.workflow.interdiction_started_at = _field(
        timestamp, STATUS_SOURCE, timestamp
    )
    combat.workflow.escape_outcome = _field(None, STATUS_SOURCE, timestamp)
    return _commit_change(state, before, combat, "BeingInterdicted", timestamp)


def record_interdiction_ended(
    event: dict[str, Any],
    state: StateManager,
    escape_outcome: str,
) -> CombatStateUpdate | None:
    """Record interdiction end from a journal EscapeInterdiction or Interdicted."""
    timestamp = _event_timestamp(event)
    before = _combat_copy(state)
    combat = deepcopy(before)
    combat.workflow.interdiction_active = _field(False, JOURNAL_SOURCE, timestamp)
    combat.workflow.interdiction_ended_at = _field(timestamp, JOURNAL_SOURCE, timestamp)
    combat.workflow.escape_outcome = _field(escape_outcome, JOURNAL_SOURCE, timestamp)
    reason = str(event.get("event") or "InterdictionEnded")
    return _commit_change(state, before, combat, reason, timestamp)


async def publish_update(
    update: CombatStateUpdate | None,
    broadcaster: ShipStateBroadcaster | None,
) -> bool:
    """Publish COMBAT_STATE_CHANGED through the existing broadcaster."""
    if update is None or broadcaster is None:
        return False

    await broadcaster.publish(
        COMBAT_STATE_CHANGED,
        ShipStateEvent.now(
            COMBAT_STATE_CHANGED,
            update.payload(),
            source="journal",
        ),
    )
    return True


def _combat_copy(state: StateManager) -> CombatState:
    return deepcopy(state.snapshot.combat)


def _commit_change(
    state: StateManager,
    before: CombatState,
    combat: CombatState,
    reason: str,
    timestamp: str | None,
) -> CombatStateUpdate | None:
    changed_fields = _changed_fields(before, combat)
    if not changed_fields:
        return None
    if not state.update_field("combat", combat, TelemetrySource.INFERRED, timestamp):
        return None
    return CombatStateUpdate(
        reason=reason,
        changed_fields=changed_fields,
        combat=_combat_payload(combat),
    )


def _event_timestamp(event: dict[str, Any]) -> str | None:
    timestamp = event.get("timestamp")
    if isinstance(timestamp, str):
        return timestamp
    return None


def _field(
    value: str | int | bool | None,
    source: CombatSourceLabel,
    timestamp: str | None,
    freshness: CombatFreshnessState = FRESH,
) -> CombatField:
    return CombatField(
        value=value,
        source=source,
        timestamp=timestamp,
        freshness=freshness,
    )


def _recent_hostile_count(combat: CombatState) -> int:
    value = combat.threat.recent_hostile_events_count.value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def _combat_payload(combat: CombatState) -> dict[str, Any]:
    payload: Any = asdict(combat)
    return cast(dict[str, Any], payload)


def _changed_fields(before: CombatState, after: CombatState) -> tuple[str, ...]:
    before_payload = _combat_payload(before)
    after_payload = _combat_payload(after)
    changed: list[str] = []
    for group, field_name in _COMBAT_FIELD_PATHS:
        if before_payload[group][field_name] != after_payload[group][field_name]:
            changed.append(f"{group}.{field_name}")
    return tuple(changed)
