"""Operation readiness engine — LNA-028 contract, LNA-022 role fit.

One owner for "is the ship ready for this?". The first slice computed this
inside a single Operations view model, which put the answer out of reach of
the Dashboard and Engineering — the two other surfaces the row names — and
invited each of them to grow a rival derivation. That already happened once
with ship vitals (LNA-027), where the same defect had to be fixed twice in
two renderers. The computation lives here so every surface reads one answer.

Three rules carried forward from the first slice, because they were right:

    * Unknown is never failure. A check with no local reading reports
      `unknown` and says which fact is missing. It is never rendered as a
      problem with the ship.
    * Thresholds are imported from the features that own them, not restated.
      Fuel low is fuel's number; hull critical is hull's number.
    * Nothing is invented. Every check names the state field it read.

Role fit (LNA-022) is evidence, not a verdict. A ship is reported as fitted
for mining because a refinery was observed in the loadout — never because the
engine guessed. Absent evidence is reported as an unobserved fact, so a
Commander is never told their ship is unsuitable on the strength of a journal
line that has not arrived yet.

No providers, no thresholds beyond those already ratified, no game action.
"""

from __future__ import annotations

import logging
from typing import Any

from omnicovas.core.state_manager import StateManager
from omnicovas.features.fuel import _FUEL_LOW_FRACTION
from omnicovas.features.hull_triggers import _HULL_25_FRACTION

logger = logging.getLogger(__name__)

TRUTH_LOCAL_TELEMETRY = "local_telemetry"
SOURCE_LOCAL_STATE = "Local telemetry (StateManager)"

STATUS_READY = "ready"
STATUS_ATTENTION = "attention"
STATUS_UNKNOWN = "unknown"

FUEL_LOW_PCT = _FUEL_LOW_FRACTION * 100
HULL_CRITICAL_PCT = _HULL_25_FRACTION * 100

READINESS_CAVEAT = (
    "State-backed checks from local telemetry only. Unknown means the local "
    "source has not reported that fact yet — never a failure, and never a "
    "judgement about the ship."
)

# Operation profiles. `engineering` was named in the row's checklist and was
# missing from the first slice; a Commander heading to an engineer needs the
# same travel safety answers as any other trip.
OPERATION_PROFILES: dict[str, tuple[str, ...]] = {
    "idle": ("fuel", "hull", "shields", "rebuy"),
    "mining": ("cargo_space", "fuel", "hull", "rebuy", "modules"),
    "trading": ("cargo_space", "fuel", "rebuy", "modules"),
    "combat": ("hull", "shields", "fuel", "rebuy", "modules"),
    "exploration": ("fuel", "hull", "rebuy", "modules"),
    "engineering": ("fuel", "hull", "rebuy", "cargo_space"),
    "travel": ("fuel", "hull", "rebuy"),
    "station": ("rebuy", "cargo_space"),
    "squadron": ("fuel", "hull", "rebuy"),
    "bgs": ("fuel", "hull", "rebuy"),
    "powerplay": ("fuel", "hull", "rebuy"),
}
DEFAULT_OPERATION = "idle"

# Role evidence, matched against observed loadout module item names. Every
# token is a Frontier-native module identifier substring already present in
# Loadout output; no capability is inferred from anything else.
ROLE_EVIDENCE: dict[str, dict[str, tuple[str, ...]]] = {
    "mining": {
        "refinery": ("refinery",),
        "mining_laser": ("mining_laser", "miningkaser", "mininglaser"),
        # Frontier names the limpet controllers `int_dronecontrol_prospector`
        # and `int_dronecontrol_collection`. The prospector token already
        # matched; the collection controller had no entry at all, so a ship
        # fitted for mining reported no way to retrieve what it cracked. Both
        # tokens were read off real Loadout events, not guessed (Phase 14 R6).
        "prospector": ("prospector",),
        "collector": ("dronecontrol_collection", "collectionlimpet"),
        "cargo_rack": ("cargorack",),
    },
    "trading": {
        "cargo_rack": ("cargorack",),
    },
    "combat": {
        "weapon": (
            "hpt_pulselaser",
            "hpt_beamlaser",
            "hpt_multicannon",
            "hpt_cannon",
            "hpt_railgun",
            "hpt_plasmaaccelerator",
            "hpt_slugshot",
            "hpt_dumbfiremissile",
            "hpt_basicmissile",
        ),
        "shield_generator": ("shieldgenerator",),
    },
    "exploration": {
        "fuel_scoop": ("fuelscoop",),
        "discovery_scanner": ("discoveryscanner", "dsc_"),
        "detailed_surface_scanner": ("detailedsurfacescanner", "dss_"),
    },
}


def _pct(value: float | None) -> float | None:
    return None if value is None else round(float(value), 1)


def _check(
    check_id: str,
    label: str,
    value: str | None,
    status: str,
    note: str | None,
    read_from: str,
) -> dict[str, Any]:
    """One readiness answer, always naming the state field it read."""
    return {
        "id": check_id,
        "label": label,
        "value": value,
        "status": status,
        "note": note,
        "read_from": read_from,
        "source": SOURCE_LOCAL_STATE,
        "truth_class": TRUTH_LOCAL_TELEMETRY,
    }


def _unknown(check_id: str, label: str, missing: str, read_from: str) -> dict[str, Any]:
    return _check(
        check_id,
        label,
        None,
        STATUS_UNKNOWN,
        f"No local reading for {missing} yet.",
        read_from,
    )


def _fuel_check(snap: Any) -> dict[str, Any]:
    main = snap.fuel_main
    capacity = snap.fuel_capacity_main
    if main is None:
        return _unknown("fuel", "Fuel", "fuel level", "fuel_main")
    if not capacity:
        # Tonnage is known and capacity is not. Report the fact held rather
        # than withholding it behind a ratio that cannot be computed.
        return _check(
            "fuel",
            "Fuel",
            f"{_pct(main)} t",
            STATUS_UNKNOWN,
            "Tank size not observed yet, so remaining range cannot be judged.",
            "fuel_main",
        )
    pct = main / capacity * 100
    if pct < FUEL_LOW_PCT:
        return _check(
            "fuel",
            "Fuel",
            f"{round(pct)}%",
            STATUS_ATTENTION,
            f"Below the {round(FUEL_LOW_PCT)}% low-fuel threshold.",
            "fuel_main",
        )
    return _check("fuel", "Fuel", f"{round(pct)}%", STATUS_READY, None, "fuel_main")


def _hull_check(snap: Any) -> dict[str, Any]:
    hull = snap.hull_health
    if hull is None:
        return _unknown("hull", "Hull", "hull integrity", "hull_health")
    # Journal hull health is a 0.0-1.0 fraction; older paths may carry percent.
    pct = hull * 100 if hull <= 1.0 else hull
    if pct < HULL_CRITICAL_PCT:
        return _check(
            "hull",
            "Hull",
            f"{round(pct)}%",
            STATUS_ATTENTION,
            f"Below the {round(HULL_CRITICAL_PCT)}% hull-critical threshold.",
            "hull_health",
        )
    return _check("hull", "Hull", f"{round(pct)}%", STATUS_READY, None, "hull_health")


def shield_generator_fitted(snap: Any) -> bool | None:
    """Whether a shield generator was observed in the local loadout.

    Returns None when no loadout has been observed at all: absence of evidence
    is not evidence the ship lacks the module. Uses the same
    `shieldgenerator` token the combat role evidence already matches on, so
    there is one definition of "has shields" rather than two.
    """
    modules = getattr(snap, "modules", None) or {}
    if not modules:
        return None
    tokens = ROLE_EVIDENCE["combat"]["shield_generator"]
    for module in modules.values():
        item = str(getattr(module, "item", "") or "").lower()
        if any(token in item for token in tokens):
            return True
    return False


def _shields_check(snap: Any) -> dict[str, Any]:
    """Shield readiness, aware of whether a generator is actually fitted.

    `shield_up` is False both for a ship whose shields are down and for a ship
    that has no shield generator at all. Reporting the second case as "Shields
    are down" is a false attention state — and, because attentions become
    blockers, a false blocker. The ship-state watch strip already distinguishes
    these two cases; this check now agrees with it.
    """
    up = snap.shield_up
    # Shields reported up is direct positive evidence and outranks any
    # inference from the module list: a ship cannot raise shields it does not
    # have, and an observed loadout may still be partial.
    if up is True:
        return _check("shields", "Shields", "Up", STATUS_READY, None, "shield_up")

    if up is False:
        fitted = shield_generator_fitted(snap)
        if fitted is False:
            # Not a failure and not a blocker: the ship is flying as
            # configured. This is the case that used to read "Shields are
            # down." and become the only blocker on the route.
            return _check(
                "shields",
                "Shields",
                "None fitted",
                STATUS_UNKNOWN,
                "No shield generator observed in the local loadout.",
                "modules",
            )
        if fitted is None:
            # No loadout observed, so "down" cannot be distinguished from
            # "no generator". Unknown rather than a possibly-false attention.
            return _unknown("shields", "Shields", "shield generator loadout", "modules")
        return _check(
            "shields",
            "Shields",
            "Down",
            STATUS_ATTENTION,
            "Shields are down.",
            "shield_up",
        )

    return _unknown("shields", "Shields", "shield state", "shield_up")


def _rebuy_check(snap: Any) -> dict[str, Any]:
    credits = snap.credit_balance
    rebuy = snap.rebuy_cost
    if credits is None or rebuy is None:
        return _unknown(
            "rebuy", "Rebuy cover", "credits or rebuy cost", "credit_balance"
        )
    note = f"{credits:,.0f} cr held against {rebuy:,.0f} cr rebuy."
    if credits >= rebuy:
        return _check(
            "rebuy", "Rebuy cover", "Covered", STATUS_READY, note, "credit_balance"
        )
    return _check(
        "rebuy", "Rebuy cover", "Short", STATUS_ATTENTION, note, "credit_balance"
    )


def _cargo_space_check(snap: Any) -> dict[str, Any]:
    used = snap.cargo_count
    capacity = snap.cargo_capacity
    if used is None:
        return _unknown("cargo_space", "Cargo space", "cargo", "cargo_count")
    if capacity is None:
        return _check(
            "cargo_space",
            "Cargo space",
            f"{used} t",
            STATUS_UNKNOWN,
            "Hold size not observed yet, so free space cannot be judged.",
            "cargo_count",
        )
    free = max(int(capacity) - int(used), 0)
    note = f"{free} t free of {int(capacity)} t."
    if free == 0 and capacity:
        return _check(
            "cargo_space", "Cargo space", "Full", STATUS_ATTENTION, note, "cargo_count"
        )
    return _check(
        "cargo_space",
        "Cargo space",
        f"{free} t free",
        STATUS_READY,
        note,
        "cargo_count",
    )


def _modules_check(snap: Any) -> dict[str, Any]:
    modules = getattr(snap, "modules", None) or {}
    if not modules:
        return _unknown("modules", "Modules", "loadout", "modules")
    destroyed = [
        slot
        for slot, module in modules.items()
        if getattr(module, "health", 1.0) == 0.0
    ]
    if destroyed:
        listed = ", ".join(sorted(destroyed)[:3])
        more = "" if len(destroyed) <= 3 else f" (+{len(destroyed) - 3} more)"
        return _check(
            "modules",
            "Modules",
            f"{len(destroyed)} destroyed",
            STATUS_ATTENTION,
            f"Destroyed: {listed}{more}.",
            "modules",
        )
    return _check(
        "modules", "Modules", f"{len(modules)} fitted", STATUS_READY, None, "modules"
    )


_CHECK_BUILDERS = {
    "fuel": _fuel_check,
    "hull": _hull_check,
    "shields": _shields_check,
    "rebuy": _rebuy_check,
    "cargo_space": _cargo_space_check,
    "modules": _modules_check,
}


def role_fit(state: StateManager) -> dict[str, Any]:
    """Evidence that the observed loadout suits each role (LNA-022).

    Reports what was seen fitted and what was not seen. Absent evidence is an
    unobserved fact, never a verdict that the ship is unsuitable: a Loadout
    event may simply not have arrived.
    """
    snap = state.snapshot
    modules = getattr(snap, "modules", None) or {}
    observed = [
        str(getattr(module, "item", "") or "").lower() for module in modules.values()
    ]
    loadout_observed = bool(modules)

    roles: list[dict[str, Any]] = []
    for role, evidence in ROLE_EVIDENCE.items():
        fitted: list[str] = []
        missing: list[str] = []
        for capability, tokens in evidence.items():
            if any(token in item for item in observed for token in tokens):
                fitted.append(capability)
            else:
                missing.append(capability)
        roles.append(
            {
                "role": role,
                "fitted": sorted(fitted),
                "not_observed": sorted(missing),
                # Without a loadout there is nothing to judge, so the role is
                # unknown rather than unfitted.
                "status": (
                    STATUS_UNKNOWN
                    if not loadout_observed
                    else (STATUS_READY if fitted else STATUS_UNKNOWN)
                ),
            }
        )

    return {
        "loadout_observed": loadout_observed,
        "modules_observed": len(modules),
        "roles": sorted(roles, key=lambda entry: entry["role"]),
        "missing_facts": [] if loadout_observed else ["loadout"],
        "caveat": (
            "Role fit is evidence from the observed loadout. A capability not "
            "listed as fitted was not seen in local data — which is not proof "
            "the ship lacks it."
        ),
    }


def ship_profile(state: StateManager) -> dict[str, Any]:
    """Current ship identity, live facts, role fit, and missing facts."""
    snap = state.snapshot
    facts = {
        "ship_type": snap.current_ship_type,
        "ship_name": snap.current_ship_name,
        "ship_ident": snap.current_ship_ident,
        "hull_health": snap.hull_health,
        "shield_up": snap.shield_up,
        "fuel_main": snap.fuel_main,
        "fuel_capacity_main": snap.fuel_capacity_main,
        "cargo_count": snap.cargo_count,
        "cargo_capacity": snap.cargo_capacity,
        "jump_range_ly": snap.jump_range_ly,
        "rebuy_cost": snap.rebuy_cost,
    }
    # Naming what has not been observed is the point of the row: a Commander
    # can see why an answer is unavailable instead of meeting a blank.
    missing = sorted(key for key, value in facts.items() if value is None)
    fit = role_fit(state)
    return {
        "source": SOURCE_LOCAL_STATE,
        "truth_class": TRUTH_LOCAL_TELEMETRY,
        "facts": facts,
        "missing_facts": missing,
        "role_fit": fit,
        "caveat": READINESS_CAVEAT,
        "nullprovider_safe": True,
    }


def evaluate(state: StateManager, *, operation: str | None = None) -> dict[str, Any]:
    """Readiness for one operation.

    Raises ValueError for an unknown operation so the caller refuses rather
    than silently answering for a different one.
    """
    requested = (operation or DEFAULT_OPERATION).strip().lower() or DEFAULT_OPERATION
    if requested not in OPERATION_PROFILES:
        raise ValueError(f"Unknown operation: {operation}")

    snap = state.snapshot
    checks = [
        _CHECK_BUILDERS[check_id](snap) for check_id in OPERATION_PROFILES[requested]
    ]
    attention = [check for check in checks if check["status"] == STATUS_ATTENTION]
    unknown = [check for check in checks if check["status"] == STATUS_UNKNOWN]

    if attention:
        summary = f"{len(attention)} need attention"
    elif unknown:
        # Silence about what is unknown would read as a clean bill of health.
        summary = f"{len(unknown)} unknown"
    else:
        summary = "Ready"

    return {
        "operation": requested,
        "operations": sorted(OPERATION_PROFILES),
        "summary": summary,
        "attention_count": len(attention),
        "unknown_count": len(unknown),
        "ready_count": len(checks) - len(attention) - len(unknown),
        "checks": checks,
        "source": SOURCE_LOCAL_STATE,
        "truth_class": TRUTH_LOCAL_TELEMETRY,
        "caveat": READINESS_CAVEAT,
        "nullprovider_safe": True,
    }
