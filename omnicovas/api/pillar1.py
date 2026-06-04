"""
omnicovas.api.pillar1

Phase 3 Pillar 1 HTTP endpoints.

Each endpoint returns exactly the data needed by a specific Dashboard card or
overlay surface — no more, no less.  Keeping them narrow means the UI contract
is explicit and testable.

Mounted under the prefix /pillar1 by ApiBridge._build_app().

Law 8 (Sovereignty & Transparency): every endpoint is read-only and local-only.
Law 5 (Zero Hallucination): None fields are returned as null, never filled in.

See: Phase 3 Development Guide Week 11, Part B
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter

if TYPE_CHECKING:
    from omnicovas.config.vault import ConfigVault
    from omnicovas.core.state_manager import StateManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pillar1", tags=["pillar1"])

# The router cannot hold a reference to StateManager at import time because
# the router is created before the StateManager.  ApiBridge injects it via
# pillar1.set_state_manager() immediately after creating the router.
_state: StateManager | None = None
_vault: ConfigVault | None = None


def set_state_manager(state: StateManager) -> None:
    """Inject the live StateManager into this router.

    Args:
        state: The application-wide StateManager instance.
    """
    global _state  # noqa: PLW0603
    _state = state


def set_config_vault(vault: ConfigVault) -> None:
    """Inject the ConfigVault instance for overlay settings persistence.

    Args:
        vault: The application-wide ConfigVault instance.
    """
    global _vault  # noqa: PLW0603
    _vault = vault


def _snap() -> Any:
    """Return the current state snapshot, or None if not yet injected."""
    return _state.snapshot if _state is not None else None


# After a HeatWarning/HeatDamage journal event, heat_state is held in
# StateManager with no natural expiry. A TTL prevents stale warning/damage
# state from persisting indefinitely when Status.json stops reporting Heat.
_HEAT_EVENT_STATE_TTL_SECONDS: float = 60.0


def _heat_event_is_fresh(last_event_at: str | None) -> bool:
    """Return True if the last heat event timestamp is within TTL.

    If last_event_at is None or unparseable, the event state is treated as
    stale and the stored heat_state is not applied to the API response.
    """
    if last_event_at is None:
        return False
    try:
        event_time = datetime.fromisoformat(last_event_at.replace("Z", "+00:00"))
        age_s = (datetime.now(timezone.utc) - event_time).total_seconds()
        return age_s <= _HEAT_EVENT_STATE_TTL_SECONDS
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# /pillar1/ship-state
# ---------------------------------------------------------------------------


@router.get("/ship-state")
async def get_ship_state() -> dict[str, Any]:
    """Consolidated ship snapshot for the Dashboard LiveShipState card.

    Returns the full set of fields the dashboard needs in one call so the
    UI does not need to assemble state from multiple endpoints.

    Returns:
        ship_type: internal ship type string, or null
        ship_name: commander-assigned name, or null
        ship_ident: commander-assigned ident tag, or null
        hull_health: 0.0–100.0 percent, or null
        shield_up: True/False/null
        shield_strength_pct: 0.0–100.0 percent, or null
        fuel_main: current main-tank fuel in tonnes, or null
        fuel_capacity: main-tank capacity in tonnes, or null
        fuel_pct: fuel_main / fuel_capacity * 100, or null
        jump_range_ly: max jump range in light-years, or null
        cargo_count: number of cargo units carried, or null
        cargo_capacity: cargo hold capacity, or null
        heat_level: 0.0–1.0+ (raw fraction), or null
        sys_pips: SYS pips 0–8, or null
        eng_pips: ENG pips 0–8, or null
        wep_pips: WEP pips 0–8, or null
        is_docked: True/False
        current_system: current star system name, or null
        current_station: current station name, or null
        is_wanted_in_system: True if bounty active in current system
    """
    s = _snap()
    if s is None:
        return _empty_ship_state()

    fuel_pct: float | None = None
    cap = s.fuel_capacity_main
    if s.fuel_main is not None and cap is not None and cap > 0:
        fuel_pct = round(s.fuel_main / cap * 100, 1)

    hull_pct: float | None = None
    if s.hull_health is not None:
        hull_pct = round(s.hull_health * 100, 1)

    return {
        "ship_type": s.current_ship_type,
        "ship_name": s.current_ship_name,
        "ship_ident": s.current_ship_ident,
        "hull_health": hull_pct,
        "shield_up": s.shield_up,
        "shield_strength_pct": s.shield_strength_pct,
        "fuel_main": s.fuel_main,
        "fuel_capacity": s.fuel_capacity_main,
        "fuel_pct": fuel_pct,
        "jump_range_ly": s.jump_range_ly,
        "cargo_count": s.cargo_count,
        "cargo_capacity": s.cargo_capacity,
        "heat_level": s.heat_level,
        "sys_pips": s.sys_pips,
        "eng_pips": s.eng_pips,
        "wep_pips": s.wep_pips,
        "is_docked": s.is_docked,
        "current_system": s.current_system,
        "current_station": s.current_station,
        "is_wanted_in_system": s.is_wanted_in_system,
    }


def _empty_ship_state() -> dict[str, Any]:
    return {
        "ship_type": None,
        "ship_name": None,
        "ship_ident": None,
        "hull_health": None,
        "shield_up": None,
        "shield_strength_pct": None,
        "fuel_main": None,
        "fuel_capacity": None,
        "fuel_pct": None,
        "jump_range_ly": None,
        "cargo_count": None,
        "cargo_capacity": None,
        "heat_level": None,
        "sys_pips": None,
        "eng_pips": None,
        "wep_pips": None,
        "is_docked": None,
        "current_system": None,
        "current_station": None,
        "is_wanted_in_system": False,
    }


# ---------------------------------------------------------------------------
# /pillar1/loadout
# ---------------------------------------------------------------------------


@router.get("/loadout")
async def get_loadout() -> dict[str, Any]:
    """Full module list for the Loadout view.

    Engineering blocks are returned raw — Phase 8 (Engineering Pillar) owns
    effect computation.  We preserve the raw block so it is available without
    a second read.

    Returns:
        ship_type: current ship type string, or null
        loadout_hash: SHA-256 of the current loadout, or null
        modules: list of module objects (slot, item, item_localised, health_pct,
                 power, priority, on, engineering, value)
    """
    s = _snap()
    if s is None:
        return {"ship_type": None, "loadout_hash": None, "modules": []}

    modules = []
    for slot, mod in (s.modules or {}).items():
        modules.append(
            {
                "slot": slot,
                "item": mod.item,
                "item_localised": mod.item_localised,
                "health_pct": (
                    round(mod.health * 100, 1) if mod.health is not None else None
                ),
                "power": mod.power,
                "priority": mod.priority,
                "on": mod.on,
                "engineering": mod.engineering,
                "value": mod.value,
            }
        )

    return {
        "ship_type": s.current_ship_type,
        "loadout_hash": s.loadout_hash,
        "modules": modules,
    }


# ---------------------------------------------------------------------------
# /pillar1/cargo
# ---------------------------------------------------------------------------


@router.get("/cargo")
async def get_cargo() -> dict[str, Any]:
    """Cargo inventory for the Cargo card and detail view.

    Returns:
        cargo_count: total units carried, or null
        cargo_capacity: hold capacity, or null
        inventory: list of {name, count} dicts, sorted by count descending
    """
    s = _snap()
    if s is None:
        return {"cargo_count": None, "cargo_capacity": None, "inventory": []}

    inventory = [
        {"name": name, "count": count}
        for name, count in sorted(
            (s.cargo_inventory or {}).items(), key=lambda kv: kv[1], reverse=True
        )
    ]

    return {
        "cargo_count": s.cargo_count,
        "cargo_capacity": s.cargo_capacity,
        "inventory": inventory,
    }


# ---------------------------------------------------------------------------
# /pillar1/heat
# ---------------------------------------------------------------------------


@router.get("/heat")
async def get_heat() -> dict[str, Any]:
    """Heat level for the Heat card and overlay banner.

    Returns:
        level: current heat fraction 0.0–1.0+, or null
        level_pct: level * 100 rounded to 1 dp, or null
        trend: 'rising' | 'falling' | 'steady' | null
        samples: last up-to-10 heat readings (for sparkline), list[float]
        state: 'normal' | 'warning' | 'critical' | 'damage' | null
        last_event_at: timestamp of last warning/damage, or null
        suggestion: grounded suggestion text, or null
    """
    s = _snap()
    if s is None:
        return {
            "level": None,
            "level_pct": None,
            "trend": None,
            "samples": [],
            "state": None,
            "last_event_at": None,
            "suggestion": None,
        }

    level = s.heat_level
    level_pct = round(level * 100, 1) if level is not None else None

    # Determine state: priority is damage > warning.
    # We use both grounded event state AND numeric heat levels if available.
    heat_state: str | None = None

    # Check grounded journal events first, but only when the event is fresh.
    # A stale warning/damage (beyond TTL) must not persist — it would show
    # a permanent alert for an event that happened many minutes ago.
    if _heat_event_is_fresh(s.heat_last_event_at):
        if s.heat_state == "damage":
            heat_state = "damage"
        elif s.heat_state == "warning":
            heat_state = "warning"

    # Numeric override if high heat
    if level is not None:
        if level >= 1.20:
            heat_state = "damage"
        elif level >= 0.95:
            heat_state = "critical"
        elif level >= 0.80 and heat_state != "damage":
            heat_state = "warning"
        elif heat_state is None:
            heat_state = "normal"
    elif heat_state is None:
        # If no grounded state and no level, state remains None
        pass

    # Trend and samples come from the HeatManagement feature's rolling window.
    trend: str | None = None
    samples: list[float] = []
    try:
        from omnicovas.features.heat_management import get_heat_trend_and_samples

        trend, samples = get_heat_trend_and_samples()
    except (ImportError, Exception):
        pass

    return {
        "level": level,
        "level_pct": level_pct,
        "trend": trend,
        "samples": samples,
        "state": heat_state,
        "last_event_at": s.heat_last_event_at,
        "suggestion": s.heat_suggestion,
    }


# ---------------------------------------------------------------------------
# /pillar1/pips
# ---------------------------------------------------------------------------


@router.get("/pips")
async def get_pips() -> dict[str, Any]:
    """Power distribution pips for the PIPS card.

    Returns:
        sys: SYS pips 0–8, or null
        eng: ENG pips 0–8, or null
        wep: WEP pips 0–8, or null
    """
    s = _snap()
    if s is None:
        return {"sys": None, "eng": None, "wep": None}

    return {
        "sys": s.sys_pips,
        "eng": s.eng_pips,
        "wep": s.wep_pips,
    }


# ---------------------------------------------------------------------------
# /pillar1/modules/summary
# ---------------------------------------------------------------------------


@router.get("/modules/summary")
async def get_modules_summary() -> dict[str, Any]:
    """Module health summary for the Dashboard card.

    Returns counts of modules in each health band — enough for the dashboard
    card without sending the full module list.

    Returns:
        total: number of modules tracked
        ok: modules at >= 80% health
        warning: modules at >= 20% and < 80% health
        critical: modules at < 20% health
    """
    s = _snap()
    if s is None:
        return {"total": 0, "ok": 0, "warning": 0, "critical": 0}

    ok = warning = critical = 0
    for mod in (s.modules or {}).values():
        h = mod.health
        if h is None:
            continue
        if h < 0.20:
            critical += 1
        elif h < 0.80:
            warning += 1
        else:
            ok += 1

    return {
        "total": ok + warning + critical,
        "ok": ok,
        "warning": warning,
        "critical": critical,
    }


# ---------------------------------------------------------------------------
# Overlay Settings (Week 12 Part D)
# ---------------------------------------------------------------------------


_OVERLAY_EVENT_DEFAULTS: dict[str, bool] = {
    "HULL_CRITICAL_10": True,
    "SHIELDS_DOWN": True,
    "HULL_CRITICAL_25": True,
    "FUEL_CRITICAL": True,
    "MODULE_CRITICAL": True,
    "FUEL_LOW": True,
    "HEAT_WARNING": True,
    "HEAT_DAMAGE": True,
}

_VALID_ANCHORS = {"tl", "tr", "bl", "br", "center"}


@router.get("/overlay/settings")
async def get_overlay_settings() -> dict[str, Any]:
    """Get current overlay settings, reading persisted values from vault when available.

    Returns:
        opacity: float from 0.5 to 1.0 (default 0.95)
        anchor: one of "tl", "tr", "bl", "br", "center" (default "center")
        events: dict[str, bool] for each critical event type
        click_through: bool (default True)
    """
    opacity: float = 0.95
    anchor: str = "center"
    events: dict[str, bool] = dict(_OVERLAY_EVENT_DEFAULTS)
    click_through: bool = True

    if _vault is not None:
        try:
            raw_opacity = _vault.get("settings_overlay_opacity")
            if raw_opacity is not None:
                parsed = float(raw_opacity)
                if 0.5 <= parsed <= 1.0:
                    opacity = parsed
        except (ValueError, TypeError):
            logger.warning("Ignoring invalid persisted overlay opacity")

        try:
            raw_anchor = _vault.get("settings_overlay_anchor")
            if raw_anchor is not None and raw_anchor in _VALID_ANCHORS:
                anchor = raw_anchor
        except Exception:
            logger.warning("Ignoring invalid persisted overlay anchor")

        try:
            raw_events = _vault.get("overlay_events")
            if raw_events is not None:
                stored: Any = json.loads(raw_events)
                if isinstance(stored, dict):
                    for k, v in stored.items():
                        if k in events and isinstance(v, bool):
                            events[k] = v
        except (ValueError, TypeError, json.JSONDecodeError):
            logger.warning("Ignoring invalid persisted overlay events; using defaults")

        try:
            raw_ct = _vault.get("overlay_click_through")
            if raw_ct is not None:
                click_through = raw_ct.lower() != "false"
        except Exception:
            logger.warning("Ignoring invalid persisted click_through; using default")

    return {
        "opacity": opacity,
        "anchor": anchor,
        "events": events,
        "click_through": click_through,
    }


@router.post("/overlay/settings")
async def update_overlay_settings(body: dict[str, Any]) -> dict[str, str]:
    """Update and persist overlay settings via DPAPI vault.

    Accepts partial updates — only present keys are changed.

    Returns:
        status: "ok"
    """
    if _vault is None:
        logger.warning("update_overlay_settings: vault not injected; skipping persist")
        return {"status": "ok"}

    try:
        if "opacity" in body:
            val = float(body["opacity"])
            if 0.5 <= val <= 1.0:
                _vault.set("settings_overlay_opacity", str(val))

        if "anchor" in body and body["anchor"] in _VALID_ANCHORS:
            _vault.set("settings_overlay_anchor", str(body["anchor"]))

        if "events" in body and isinstance(body["events"], dict):
            # Merge with current stored events to avoid clobbering unmentioned keys
            current_raw = _vault.get("overlay_events")
            current: dict[str, bool] = dict(_OVERLAY_EVENT_DEFAULTS)
            if current_raw is not None:
                try:
                    stored: Any = json.loads(current_raw)
                    if isinstance(stored, dict):
                        for k, v in stored.items():
                            if k in current and isinstance(v, bool):
                                current[k] = v
                except (ValueError, json.JSONDecodeError):
                    pass
            for k, v in body["events"].items():
                if k in current and isinstance(v, bool):
                    current[k] = v
            _vault.set("overlay_events", json.dumps(current))

        if "click_through" in body and isinstance(body["click_through"], bool):
            ct_val = "true" if body["click_through"] else "false"
            _vault.set("overlay_click_through", ct_val)

    except Exception as e:
        logger.error("Failed to persist overlay settings: %s", e)

    return {"status": "ok"}
