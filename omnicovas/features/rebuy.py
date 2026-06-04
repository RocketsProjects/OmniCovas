"""
omnicovas.features.rebuy

Rebuy Calculator -- Feature 11 (Pillar 1, Tier 1 -- Pure Telemetry).

Computes the estimated rebuy cost for the commander's current ship from
data already present in StateManager. No AI calls, no external requests.

Calculation:
    rebuy = int((hull_value + modules_value) * INSURANCE_FRACTION)

Inputs (all from the most recent Loadout journal event):
    hull_value    -- Loadout.HullValue (credits)
    modules_value -- Loadout.ModulesValue (credits) or sum of
                     ModuleInfo.value when ModulesValue is absent

Insurance rate:
    5.0% standard (KB: combat_mechanics::insurance_percentage).
    Premium insurance is not tracked in the journal; 5% is used as default.

Law 5 (Zero Hallucination):
    Returns None if ship identity or value data is unavailable.
    Never fabricates a cost from a hard-coded ship table.

Law 7 (Telemetry Rigidity):
    All inputs derive from journal telemetry. KB provides the insurance
    rate constant only.

See: Phase 2 Development Guide Week 10, Part A
See: Master Blueprint v4.2 -- Pillar 1, Feature 11
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from omnicovas.core.state_manager import StateManager

logger = logging.getLogger(__name__)

# Standard Elite Dangerous insurance rate.
# KB entry: combat_mechanics::insurance_percentage
# 5% confirmed from in-game insurance screen and community documentation.
_INSURANCE_FRACTION: float = 0.05


def calculate_rebuy(state: StateManager) -> int | None:
    """Calculate estimated rebuy cost from current ship state.

    Uses hull_value and modules_value captured from the most recent Loadout
    event. Falls back to summing per-module values when ModulesValue was
    absent in the Loadout payload (some game versions omit it).

    Args:
        state: The shared StateManager instance.

    Returns:
        Estimated rebuy cost in credits (integer), or None when no ship is
        loaded or when value data is entirely absent.

    Note:
        Insurance fraction = 5% (KB: combat_mechanics::insurance_percentage).
        Premium insurance is not available from the journal and is not modelled.
    """
    snap = state.snapshot

    if snap.current_ship_type is None:
        logger.debug("calculate_rebuy: no ship loaded -- returning None")
        return None

    hull_val = snap.hull_value or 0

    # Prefer the Loadout.ModulesValue aggregate; fall back to summing
    # per-module values if ModulesValue was not present in the journal.
    if snap.modules_value is not None:
        modules_val = snap.modules_value
    else:
        modules_val = sum(m.value for m in snap.modules.values() if m.value is not None)

    total = hull_val + modules_val
    if total <= 0:
        logger.debug(
            "calculate_rebuy: total value=0 for %s -- returning None",
            snap.current_ship_type,
        )
        return None

    rebuy = int(total * _INSURANCE_FRACTION)
    logger.debug(
        "calculate_rebuy: ship=%s hull=%d modules=%d total=%d rebuy=%d",
        snap.current_ship_type,
        hull_val,
        modules_val,
        total,
        rebuy,
    )
    return rebuy


def rebuy_api_payload(state: StateManager) -> dict[str, Any]:
    """Build the /rebuy endpoint response payload.

    Args:
        state: The shared StateManager instance.

    Returns:
        Dict suitable for direct JSON serialisation by FastAPI.
    """
    snap = state.snapshot
    return {
        "rebuy_cost": calculate_rebuy(state),
        "ship_type": snap.current_ship_type,
        "hull_value": snap.hull_value,
        "modules_value": snap.modules_value,
        "insurance_percent": _INSURANCE_FRACTION * 100,
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }
