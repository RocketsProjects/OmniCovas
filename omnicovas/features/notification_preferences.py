"""Commander notification preferences in the existing configuration vault.

Follows the Galactic Intelligence pattern: one vault key holds
``{"version": 1, "profiles": {profile_key: prefs}, "device": {...}}``. Attention
choices belong to a Commander; display geometry and text/motion belong to this
device. Critical event switches, overlay opacity and anchor keep their existing
owners (``overlay_events``, ``settings_overlay_*``) and are only read here.

Defaults are migration-safe: a missing, corrupted or unknown record reads as
Minimal (critical alerts only, no noncritical overlay, no sound).
"""

import json
from typing import Any

from omnicovas.features.notification_contracts import Preferences

VAULT_KEY = "settings_notifications"
DEFAULT_PROFILE_KEY = "local-default"
PROFILES = ("Minimal", "Flightdeck", "Explorer", "Custom")
DURATIONS = (4, 8, 15, 30)
CATEGORIES = ("exploration", "engineering", "mining", "navigation")
ANCHORS = ("tr", "tl", "tc", "br", "bl", "center")
TEXT_SCALES = (100, 125, 150, 200)
MOTION = ("system", "reduce")

JsonDict = dict[str, Any]


def default_profile() -> JsonDict:
    return {
        "profile": "Minimal",
        "quiet": False,
        "mining_target_alerts": False,
        "overlay_glances": False,
        "duration": 4,
        "categories": {name: True for name in CATEGORIES},
    }


def default_device() -> JsonDict:
    return {"overlay": True, "text_scale": 100, "reduced_motion": "system"}


def _choice(
    raw: Any, key: str, allowed: tuple[Any, ...], fallback: Any, strict: bool
) -> Any:
    value = raw.get(key, fallback) if isinstance(raw, dict) else fallback
    if value in allowed and not isinstance(value, bool):
        return value
    if strict and isinstance(raw, dict) and key in raw:
        raise ValueError(f"{key} must be one of {', '.join(map(str, allowed))}")
    return fallback


def _flag(raw: Any, key: str, fallback: bool, strict: bool) -> bool:
    value = raw.get(key, fallback) if isinstance(raw, dict) else fallback
    if isinstance(value, bool):
        return value
    if strict and isinstance(raw, dict) and key in raw:
        raise ValueError(f"{key} must be true or false")
    return fallback


def normalize_profile(raw: Any, *, strict: bool = False) -> JsonDict:
    base = default_profile()
    if strict and not isinstance(raw, dict):
        raise ValueError("preferences must be an object")
    categories = raw.get("categories") if isinstance(raw, dict) else None
    if strict and categories is not None and not isinstance(categories, dict):
        raise ValueError("categories must be an object")
    return {
        "profile": _choice(raw, "profile", PROFILES, base["profile"], strict),
        "quiet": _flag(raw, "quiet", base["quiet"], strict),
        "mining_target_alerts": _flag(raw, "mining_target_alerts", False, strict),
        "overlay_glances": _flag(raw, "overlay_glances", False, strict),
        "duration": _choice(raw, "duration", DURATIONS, base["duration"], strict),
        "categories": {
            name: _flag(categories, name, True, strict) for name in CATEGORIES
        },
    }


def normalize_device(raw: Any, *, strict: bool = False) -> JsonDict:
    base = default_device()
    return {
        "overlay": _flag(raw, "overlay", base["overlay"], strict),
        "text_scale": _choice(raw, "text_scale", TEXT_SCALES, 100, strict),
        "reduced_motion": _choice(raw, "reduced_motion", MOTION, "system", strict),
    }


class NotificationPreferenceStore:
    def __init__(self, vault: Any) -> None:
        self._vault = vault

    def _all(self) -> JsonDict:
        raw = self._vault.get(VAULT_KEY) if self._vault is not None else None
        try:
            data = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            data = {}
        return data if isinstance(data, dict) else {}

    def _profiles(self) -> JsonDict:
        profiles = self._all().get("profiles")
        return profiles if isinstance(profiles, dict) else {}

    def _write(self, profiles: JsonDict, device: JsonDict) -> None:
        payload = {"version": 1, "profiles": profiles, "device": device}
        if self._vault is None or not self._vault.set(VAULT_KEY, json.dumps(payload)):
            raise OSError("Notification preferences could not be saved")

    def get(self, profile_key: str | None) -> JsonDict:
        profiles = self._profiles()
        raw = profiles.get(profile_key or DEFAULT_PROFILE_KEY)
        if raw is None:
            raw = profiles.get(DEFAULT_PROFILE_KEY)
        return normalize_profile(raw)

    def has_own(self, profile_key: str) -> bool:
        return profile_key in self._profiles()

    def device(self) -> JsonDict:
        return normalize_device(self._all().get("device"))

    def set(self, profile_key: str | None, prefs: Any) -> JsonDict:
        clean = normalize_profile(prefs, strict=True)
        profiles = self._profiles()
        profiles[profile_key or DEFAULT_PROFILE_KEY] = clean
        self._write(profiles, self.device())
        return clean

    def set_device(self, device: Any) -> JsonDict:
        clean = normalize_device({**self.device(), **(device or {})}, strict=True)
        self._write(self._profiles(), clean)
        return clean

    def reset(self, profile_key: str | None) -> JsonDict:
        """Reset one Commander's attention choices to Minimal; nothing else."""
        profiles = self._profiles()
        profiles.pop(profile_key or DEFAULT_PROFILE_KEY, None)
        if self._vault is not None:
            self._write(profiles, self.device())
        return self.get(profile_key)

    def forget(self, profile_key: str) -> None:
        profiles = self._profiles()
        if profiles.pop(profile_key, None) is not None:
            self._write(profiles, self.device())


def effective(stored: JsonDict, device: JsonDict) -> Preferences:
    """Settings record → the Director's attention contract.

    Presets select categories; Custom uses the explicit switches. The noncritical
    overlay lane stays a separate opt-in that no preset implies.
    """
    disabled = (
        frozenset(name for name, on in stored["categories"].items() if not on)
        if stored["profile"] == "Custom"
        else frozenset()
    )
    return Preferences(
        profile=stored["profile"],
        overlay=device["overlay"],
        overlay_glances=stored["overlay_glances"],
        quiet=stored["quiet"],
        mining_target_alerts=stored["mining_target_alerts"],
        duration=stored["duration"],
        disabled=disabled,
    )
