"""
omnicovas.api.week13

Phase 3 Week 13 endpoints: onboarding, privacy, settings, confirmations.

Onboarding:
  - GET /onboarding/status — check if first-run wizard should fire
  - POST /onboarding/complete — mark first-run as complete

Privacy:
  - GET /privacy/toggles — get all privacy toggle state
  - POST /privacy/toggles/{key} — set a privacy toggle
  - POST /privacy/export — export vault-backed configuration as JSON
  - POST /privacy/delete — clear vault-backed configuration

Settings:
  - GET /settings — get full settings config
  - POST /settings — save full settings config
  - POST /settings/reset — reset to defaults

Confirmations (Law 1 — Confirmation Gate):
  - GET /confirmations/pending — get queued advisories
  - POST /confirmations/{id} — respond to an advisory

Law 8 (Sovereignty & Transparency): every setting is auditable.
Privacy toggles default OFF; no exceptions.

See: Phase 3 Development Guide Week 13
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from omnicovas.config.vault import ConfigVault
from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.event_types import (
    CRITICAL_RESPONSE_PROPOSAL_BLOCKED,
    CRITICAL_RESPONSE_PROPOSAL_CANCELED,
    CRITICAL_RESPONSE_PROPOSAL_CONFIRMED,
    CRITICAL_RESPONSE_PROPOSAL_SHOWN,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/week13", tags=["week13"])

_vault: ConfigVault | None = None
_activity_log: ActivityLog | None = None

CRITICAL_RESPONSE_ACTION_TYPE = "critical_response_proposal"


def set_config_vault(vault: ConfigVault) -> None:
    """Inject the ConfigVault instance."""
    global _vault  # noqa: PLW0603
    _vault = vault


def set_activity_log(activity_log: ActivityLog | None) -> None:
    """Inject the shared ActivityLog used for confirmation audit entries."""
    global _activity_log  # noqa: PLW0603
    _activity_log = activity_log


def _ensure_vault() -> ConfigVault:
    """Raise if vault is not yet injected."""
    if _vault is None:
        raise HTTPException(
            status_code=500,
            detail="ConfigVault not yet initialized",
        )
    return _vault


@router.get("/onboarding/status")
async def get_onboarding_status() -> dict[str, Any]:
    """Check if first-run wizard should display."""
    vault = _ensure_vault()

    completed_str = vault.get("first_run_completed")
    should_show = completed_str != "true"

    timestamp = None
    if not should_show:
        try:
            ts_str = vault.get("first_run_completed_at")
            if ts_str:
                timestamp = ts_str
        except Exception:
            pass

    return {
        "should_show_wizard": should_show,
        "completed_at": timestamp,
    }


@router.post("/onboarding/complete")
async def complete_onboarding(
    body: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Mark first-run wizard as complete."""
    vault = _ensure_vault()
    vault.set("first_run_completed", "true")
    vault.set("first_run_completed_at", datetime.utcnow().isoformat() + "Z")
    logger.info("first_run_completed")
    return {"status": "ok"}


CURRENT_LICENSE_VERSION = "1.0"


@router.get("/license/status")
async def get_license_status() -> dict[str, Any]:
    """Check whether the commander has accepted the current license version."""
    vault = _ensure_vault()

    accepted_str = vault.get("license_accepted")
    accepted_version = vault.get("license_accepted_version")
    accepted_at = vault.get("license_accepted_at")

    accepted = accepted_str == "true"
    needs_acceptance = not accepted or accepted_version != CURRENT_LICENSE_VERSION

    return {
        "accepted": accepted,
        "accepted_version": accepted_version,
        "current_version": CURRENT_LICENSE_VERSION,
        "needs_acceptance": needs_acceptance,
        "accepted_at": accepted_at if accepted else None,
    }


@router.post("/license/accept")
async def accept_license() -> dict[str, str]:
    """Record commander license acceptance for the current license version."""
    vault = _ensure_vault()
    vault.set("license_accepted", "true")
    vault.set("license_accepted_version", CURRENT_LICENSE_VERSION)
    vault.set("license_accepted_at", datetime.utcnow().isoformat() + "Z")
    logger.info("license_accepted | version=%s", CURRENT_LICENSE_VERSION)
    return {"status": "ok", "version": CURRENT_LICENSE_VERSION}


@router.post("/license/reset")
async def reset_license_acceptance() -> dict[str, str]:
    """Clear license acceptance state (re-arms the first-run license gate)."""
    vault = _ensure_vault()
    for key in ("license_accepted", "license_accepted_version", "license_accepted_at"):
        try:
            vault.delete(key)
        except Exception:
            pass
    logger.info("license_acceptance_reset")
    return {"status": "ok"}


@router.post("/onboarding/reset")
async def reset_onboarding() -> dict[str, str]:
    """Clear onboarding completion state (re-arms the first-run wizard).

    Does NOT touch license acceptance keys — use /license/reset for that.
    """
    vault = _ensure_vault()
    for key in ("first_run_completed", "first_run_completed_at"):
        try:
            vault.delete(key)
        except Exception:
            pass
    logger.info("onboarding_reset")
    return {"status": "ok"}


PRIVACY_TOGGLES = frozenset(
    {
        "eddn_submission",
        "edsm_tracking",
        "squadron_telemetry",
        "ai_provider_calls",
        "crash_reports",
        "usage_analytics",
    }
)

PHASE6_LOCKED_PROVIDER_TOGGLES = frozenset(
    {
        "eddn_submission",
        "edsm_tracking",
    }
)

PHASE6_PROVIDER_LOCK_REASON = (
    "Locked disabled for Phase 6 local-only baseline. Future provider "
    "enablement requires a Commander-approved provider-specific playbook."
)

PRIVACY_DESCRIPTIONS = {
    "eddn_submission": (
        "EDDN market submission/read-cache consent placeholder. "
        f"{PHASE6_PROVIDER_LOCK_REASON}"
    ),
    "edsm_tracking": (
        f"EDSM visit tracking consent placeholder. {PHASE6_PROVIDER_LOCK_REASON}"
    ),
    "squadron_telemetry": (
        "Local-only stored preference. Squadron sync is not yet shipped and this "
        "toggle does not send data. Requires future security doctrine."
    ),
    "ai_provider_calls": (
        "Stored local preference only. External AI provider activation is not "
        "wired in this build; NullProvider remains the active runtime posture."
    ),
    "crash_reports": (
        "Stored local preference only. Automatic crash-report transmission to "
        "maintainers is not shipped in this build."
    ),
    "usage_analytics": (
        "Stored local preference only. Automatic usage analytics transmission "
        "is not shipped in this build."
    ),
}


@router.get("/privacy/toggles")
async def get_privacy_toggles() -> dict[str, Any]:
    """Get all privacy toggle state."""
    vault = _ensure_vault()

    result = {}
    for toggle_key in sorted(PRIVACY_TOGGLES):
        enabled_str = vault.get(f"privacy_{toggle_key}")
        locked = toggle_key in PHASE6_LOCKED_PROVIDER_TOGGLES
        enabled = False if locked else enabled_str == "true"
        result[toggle_key] = {
            "enabled": enabled,
            "description": PRIVACY_DESCRIPTIONS.get(toggle_key, ""),
            "locked": locked,
            "locked_reason": PHASE6_PROVIDER_LOCK_REASON if locked else "",
        }

    return result


@router.post("/privacy/toggles/{toggle_key}")
async def set_privacy_toggle(
    toggle_key: str,
    body: dict[str, Any],
) -> dict[str, str]:
    """Set a privacy toggle on or off."""
    if toggle_key not in PRIVACY_TOGGLES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown toggle: {toggle_key}",
        )

    enabled = body.get("enabled", False)
    vault = _ensure_vault()
    if toggle_key in PHASE6_LOCKED_PROVIDER_TOGGLES:
        vault.set(f"privacy_{toggle_key}", "false")
        logger.info(
            "privacy_toggle_locked | key=%s requested_enabled=%s",
            toggle_key,
            enabled,
        )
        return {"status": "locked", "enabled": "false"}

    vault.set(f"privacy_{toggle_key}", "true" if enabled else "false")

    logger.info(
        "privacy_toggle_changed | key=%s enabled=%s",
        toggle_key,
        enabled,
    )
    return {"status": "ok"}


@router.post("/privacy/export")
async def export_privacy_data() -> dict[str, Any]:
    """Export vault-backed settings and configuration values as JSON."""
    vault = _ensure_vault()

    config_export = {}
    for key in vault.list_keys():
        if not key.endswith("_api_key"):
            try:
                value = vault.get(key)
                config_export[key] = value
            except Exception:
                pass

    kb_count = 0
    activity_log_count = 0

    return {
        "config": config_export,
        "kb_entries": kb_count,
        "activity_log_entries": activity_log_count,
        "exported_at": datetime.utcnow().isoformat() + "Z",
    }


@router.post("/privacy/delete")
async def delete_all_data(body: dict[str, Any] | None = None) -> dict[str, str]:
    """Clear vault-backed settings and configuration values."""
    vault = _ensure_vault()
    vault.clear_all()

    logger.warning("privacy_configuration_vault_cleared")
    return {"status": "ok"}


PRESET_PROFILES = {
    "casual": {
        "name": "Casual Pilot",
        "pillar_1_enabled": True,
        "overlay_enabled": True,
        "overlay_opacity": 0.85,
        "overlay_anchor": "center",
        "ai_provider": "null",
    },
    "combat": {
        "name": "Combat Pilot",
        "pillar_1_enabled": True,
        "overlay_enabled": True,
        "overlay_opacity": 0.95,
        "overlay_anchor": "center",
        "ai_provider": "null",
    },
    "explorer": {
        "name": "Explorer",
        "pillar_1_enabled": True,
        "overlay_enabled": False,
        "overlay_opacity": 0.85,
        "overlay_anchor": "center",
        "ai_provider": "null",
    },
    "trader": {
        "name": "Trader",
        "pillar_1_enabled": True,
        "overlay_enabled": False,
        "overlay_opacity": 0.85,
        "overlay_anchor": "center",
        "ai_provider": "null",
    },
    "miner": {
        "name": "Miner",
        "pillar_1_enabled": True,
        "overlay_enabled": False,
        "overlay_opacity": 0.85,
        "overlay_anchor": "center",
        "ai_provider": "null",
    },
}


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    """Get full settings config."""
    vault = _ensure_vault()

    preset = vault.get("settings_preset") or "casual"
    ai_provider = vault.get("settings_ai_provider") or "null"
    overlay_opacity = float(vault.get("settings_overlay_opacity") or 0.95)
    overlay_anchor = vault.get("settings_overlay_anchor") or "center"

    return {
        "preset": preset,
        "pillar_categories": {
            "pillar_1": {"enabled": True, "phase_ready": True},
            "pillar_2": {"enabled": False, "phase_ready": False, "phase": 4},
            "pillar_3": {"enabled": False, "phase_ready": False, "phase": 5},
            "pillar_5": {"enabled": False, "phase_ready": False, "phase": 6},
            "pillar_7": {"enabled": False, "phase_ready": False, "phase": 7},
            "pillar_6": {"enabled": False, "phase_ready": False, "phase": 8},
            "pillar_4": {"enabled": False, "phase_ready": False, "phase": 9},
        },
        "output_modes": {
            "ship_telemetry": "overlay",
            "combat": "overlay",
            "exploration": "overlay",
        },
        "ai_provider": ai_provider,
        "overlay": {
            "opacity": overlay_opacity,
            "anchor": overlay_anchor,
            "event_toggles": {
                "HULL_CRITICAL_10": True,
                "SHIELDS_DOWN": True,
                "HULL_CRITICAL_25": True,
                "FUEL_CRITICAL": True,
                "MODULE_CRITICAL": True,
                "FUEL_LOW": True,
                "HEAT_WARNING": True,
            },
        },
    }


@router.post("/settings")
async def update_settings(body: dict[str, Any]) -> dict[str, str]:
    """Save settings config."""
    vault = _ensure_vault()

    if "preset" in body:
        preset = body["preset"]
        if preset in PRESET_PROFILES:
            vault.set("settings_preset", preset)

    if "ai_provider" in body:
        vault.set("settings_ai_provider", body["ai_provider"])

    if "overlay" in body:
        overlay = body["overlay"]
        if "opacity" in overlay:
            vault.set("settings_overlay_opacity", str(overlay["opacity"]))
        if "anchor" in overlay:
            vault.set("settings_overlay_anchor", overlay["anchor"])

    logger.info("settings_updated")
    return {"status": "ok"}


@router.post("/settings/reset")
async def reset_settings_to_default() -> dict[str, str]:
    """Reset all settings to defaults."""
    vault = _ensure_vault()

    for key in [
        "settings_preset",
        "settings_ai_provider",
        "settings_overlay_opacity",
        "settings_overlay_anchor",
    ]:
        try:
            vault.delete(key)
        except Exception:
            pass

    logger.info("settings_reset_to_default")
    return {"status": "ok"}


@router.post("/settings/export")
async def export_settings() -> dict[str, Any]:
    """Export settings as JSON."""
    vault = _ensure_vault()

    settings = {}
    for key in vault.list_keys():
        if "settings_" in key:
            try:
                settings[key] = vault.get(key)
            except Exception:
                pass

    return {"settings": settings}


@router.post("/settings/import")
async def import_settings(body: dict[str, Any]) -> dict[str, str]:
    """Import settings from an exported JSON file."""
    vault = _ensure_vault()

    if "settings" not in body:
        raise HTTPException(status_code=400, detail="Missing 'settings' key")

    for key, value in body["settings"].items():
        if key.startswith("settings_"):
            vault.set(key, str(value))

    logger.info("settings_imported")
    return {"status": "ok"}


_pending_confirmations: dict[str, dict[str, Any]] = {}


def enqueue_confirmation(
    *,
    confirmation_id: str | None = None,
    suggestion_text: str,
    why_text: str,
    timeout_at: str | None = None,
    action_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Queue a commander-facing confirmation without adding an HTTP endpoint."""
    conf_id = confirmation_id or uuid4().hex
    existing = _pending_confirmations.get(conf_id)
    if existing is not None:
        return conf_id

    _pending_confirmations[conf_id] = {
        "suggestion_text": suggestion_text,
        "why_text": why_text,
        "timeout_at": timeout_at,
        "action_type": action_type,
        "metadata": _safe_metadata(metadata),
    }

    if action_type == CRITICAL_RESPONSE_ACTION_TYPE:
        _record_activity(
            CRITICAL_RESPONSE_PROPOSAL_SHOWN,
            "Critical response proposal queued for commander review",
        )

    return conf_id


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Keep queue metadata bounded and inert; never retain executable objects."""
    if not metadata:
        return {}

    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            safe[str(key)] = value
    return safe


def _record_activity(event_type: str, summary: str) -> None:
    if _activity_log is None:
        return
    _activity_log.append(
        ActivityEntry(
            event_type=event_type,
            timestamp=datetime.utcnow().isoformat() + "Z",
            summary=summary,
        )
    )


def _is_critical_response(conf: dict[str, Any]) -> bool:
    return conf.get("action_type") == CRITICAL_RESPONSE_ACTION_TYPE


@router.get("/confirmations/pending")
async def get_pending_confirmations() -> dict[str, Any]:
    """Get all pending confirmation requests."""
    confirmations = []
    now = datetime.utcnow().isoformat() + "Z"

    for conf_id, conf in list(_pending_confirmations.items()):
        if conf.get("timeout_at") and conf["timeout_at"] < now:
            if _is_critical_response(conf):
                _record_activity(
                    CRITICAL_RESPONSE_PROPOSAL_BLOCKED,
                    "Critical response proposal expired without commander response",
                )
            del _pending_confirmations[conf_id]
            continue

        confirmations.append(
            {
                "id": conf_id,
                "suggestion_text": conf.get("suggestion_text", ""),
                "why_text": conf.get("why_text", ""),
                "timeout_at": conf.get("timeout_at"),
            }
        )

    return {"confirmations": confirmations}


@router.post("/confirmations/{confirmation_id}")
async def respond_to_confirmation(
    confirmation_id: str,
    body: dict[str, Any],
) -> dict[str, str]:
    """Respond to a confirmation request."""
    response = body.get("response", "").lower()

    if response not in ("confirm", "decline"):
        raise HTTPException(
            status_code=400,
            detail="response must be 'confirm' or 'decline'",
        )

    if confirmation_id in _pending_confirmations:
        conf = _pending_confirmations[confirmation_id]
        if _is_critical_response(conf):
            event_type = (
                CRITICAL_RESPONSE_PROPOSAL_CONFIRMED
                if response == "confirm"
                else CRITICAL_RESPONSE_PROPOSAL_CANCELED
            )
            summary = (
                "Critical response proposal confirmed by commander"
                if response == "confirm"
                else "Critical response proposal canceled by commander"
            )
            _record_activity(event_type, summary)
        logger.info(
            "confirmation_response | confirmation_id=%s response=%s suggestion=%s",
            confirmation_id,
            response,
            conf.get("suggestion_text", ""),
        )
        del _pending_confirmations[confirmation_id]

    return {"status": "ok"}
