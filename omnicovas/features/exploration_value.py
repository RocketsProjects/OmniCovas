"""Exploration scan value estimation — Phase 13, reference-backed estimate.

Everything here is an **estimate**, and the module is built so a caller cannot
accidentally treat it as anything else.

Two deliberate refusals:

1. **No single credit figure.** Real payouts depend on body mass and other
   terms this reference does not model, so a precise number would be
   confidently wrong. Callers get a value *class* and a *range*.
2. **Never summed with observed earnings.** `exploration_history.
   exploration_earnings` reports money actually received. Adding an estimate
   to it would turn a guess into an account balance — the failure Law 5 exists
   to prevent, and the one users of comparable third-party tools complain
   about most.

Bands come from knowledge_base/exploration_mechanics.json entry
`scan_value_classes`, which carries needs_review: true.

See: PB13-02 planning scope (known-facts result shape and source labels)
"""

from __future__ import annotations

from typing import Any

TRUTH_KNOWLEDGE_REFERENCE = "knowledge_reference"
KB_ENTRY_VALUES = "exploration_mechanics/scan_value_classes"

VALUE_CLASS_ORDER = ("negligible", "low", "moderate", "high", "very_high")

# Approximate pre-bonus credit bands by body class. Ranges, never points.
_BODY_VALUE_BANDS: tuple[tuple[tuple[str, ...], str, int, int], ...] = (
    (("earth-like", "earthlike"), "very_high", 240_000, 300_000),
    (("ammonia world",), "high", 90_000, 145_000),
    (("water world",), "high", 90_000, 130_000),
    (("metal-rich", "metal rich"), "moderate", 20_000, 35_000),
    (("high metal content",), "moderate", 9_000, 16_000),
    (
        ("gas giant", "class i", "class ii", "class iii", "class iv", "class v"),
        "low",
        1_000,
        5_000,
    ),
    (("water giant",), "low", 1_000, 5_000),
    (("rocky ice",), "negligible", 300, 900),
    (("icy",), "negligible", 300, 900),
    (("rocky",), "negligible", 300, 900),
)

_STAR_VALUE_BANDS: tuple[tuple[tuple[str, ...], str, int, int], ...] = (
    # Neutron stars and black holes are the exception among stars.
    (("n", "h", "supermassiveblackhole"), "moderate", 16_000, 25_000),
    (("d", "da", "db", "dc", "dq", "dx"), "low", 12_000, 16_000),
)
_DEFAULT_STAR_BAND = ("low", 1_200, 3_000)

_TERRAFORMABLE_MULTIPLIER = (1.6, 2.4)
_FIRST_DISCOVERY_MULTIPLIER = (2.0, 2.9)
_MAPPED_MULTIPLIER = (2.6, 3.4)

VALUE_CAVEAT = (
    "Estimated from body class against community-derived reference bands (KB "
    "exploration_mechanics/scan_value_classes, needs_review: true). A range, "
    "not a figure: the real payout also depends on mass and other terms this "
    "reference does not model. Never added to credits already received — see "
    "the exploration earnings surface for money actually earned."
)


def _normalise(value: Any) -> str:
    return str(value or "").strip().lower()


def _band_for(body: dict[str, Any]) -> tuple[str, int, int] | None:
    planet_class = _normalise(body.get("planet_class"))
    if planet_class:
        for keys, value_class, low, high in _BODY_VALUE_BANDS:
            if any(key in planet_class for key in keys):
                return value_class, low, high
        return None

    star_type = _normalise(body.get("star_type"))
    if star_type:
        for keys, value_class, low, high in _STAR_VALUE_BANDS:
            if star_type in keys:
                return value_class, low, high
        return _DEFAULT_STAR_BAND
    return None


def estimate_body_value(body: dict[str, Any]) -> dict[str, Any] | None:
    """Estimate one body's scan value as a class plus a credit range.

    Returns None when the body's class was never recorded — an unclassified
    body is not worth "nothing", it is worth *unknown*, and a caller must be
    able to tell those apart.
    """
    band = _band_for(body)
    if band is None:
        return None

    value_class, low, high = band
    applied: list[str] = []

    terraform = _normalise(body.get("terraform_state"))
    if terraform and "terraformable" in terraform:
        low = int(low * _TERRAFORMABLE_MULTIPLIER[0])
        high = int(high * _TERRAFORMABLE_MULTIPLIER[1])
        applied.append("terraformable")

    # Only apply a bonus the journal actually confirmed. None stays unapplied
    # rather than being assumed either way.
    if body.get("first_discovered_by_commander") is True:
        low = int(low * _FIRST_DISCOVERY_MULTIPLIER[0])
        high = int(high * _FIRST_DISCOVERY_MULTIPLIER[1])
        applied.append("first discovered")

    if body.get("surface_mapped_by_commander") is True:
        low = int(low * _MAPPED_MULTIPLIER[0])
        high = int(high * _MAPPED_MULTIPLIER[1])
        applied.append("surface mapped")

    # A bonus can lift a body out of its base class.
    effective_class = value_class
    if high >= 200_000:
        effective_class = "very_high"
    elif high >= 60_000:
        effective_class = "high"
    elif high >= 15_000:
        effective_class = "moderate"
    elif high >= 2_000:
        effective_class = "low"

    return {
        "value_class": effective_class,
        "base_class": value_class,
        "estimated_low": low,
        "estimated_high": high,
        "bonuses_applied": applied,
        "is_estimate": True,
        "truth_class": TRUTH_KNOWLEDGE_REFERENCE,
        "kb_entry": KB_ENTRY_VALUES,
    }


def summarise_estimates(bodies: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-body estimates, keeping unvalued bodies visible.

    `bodies_unvalued` is reported rather than silently dropped: a total that
    hides how much it could not judge invites being read as complete.
    """
    low_total = 0
    high_total = 0
    valued = 0
    unvalued = 0
    best: dict[str, Any] | None = None

    for body in bodies:
        estimate = body.get("value_estimate")
        if not estimate:
            unvalued += 1
            continue
        valued += 1
        low_total += int(estimate["estimated_low"])
        high_total += int(estimate["estimated_high"])
        if best is None or estimate["estimated_high"] > best["estimated_high"]:
            best = {**estimate, "body_name": body.get("body_name")}

    return {
        "bodies_valued": valued,
        "bodies_unvalued": unvalued,
        "estimated_low_total": low_total if valued else None,
        "estimated_high_total": high_total if valued else None,
        "highest_value_body": best,
        "is_estimate": True,
        "truth_class": TRUTH_KNOWLEDGE_REFERENCE,
        "kb_entry": KB_ENTRY_VALUES,
        "caveat": VALUE_CAVEAT,
    }
