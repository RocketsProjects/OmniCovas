"""
omnicovas.config.vault

Windows DPAPI-encrypted configuration vault.

Uses the Windows Data Protection API (the same system browsers use for
saved passwords). Encryption is tied to the user's Windows login — no
key management, no password prompts. The user's Windows account IS the key.

Law 2 (Legal Compliance):
    API keys are never stored in plaintext. Never logged.
    Stored exclusively in encrypted form in AppData.

Law 8 (Sovereignty & Transparency):
    Config file is in AppData — fully owned by the commander.
    Can be deleted at any time via File Explorer or the UI.

Security Note:
    DPAPI encryption is tied to the current Windows user.
    If the user changes account or the machine is reimaged, the vault
    cannot be decrypted. This is the correct behavior — credentials
    should not follow a hijacked account.

See: Master Blueprint v4.0 Section 10 (Security Protocol)
See: Phase 1 Development Guide Week 5, Part B
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VAULT_DIR = Path(os.path.expandvars(r"%APPDATA%\OmniCOVAS"))
VAULT_FILE = VAULT_DIR / "config.vault"


# Known config keys — documented so mypy helps catch typos
# Callers should use these constants, not hand-typed strings
# Phase 3 Week 13 extends this with settings_* and privacy_* keys.
CONFIG_KEYS = frozenset(
    {
        "journal_path",
        "ai_provider_type",
        "gemini_api_key",
        "gemini_model",
        "inara_api_key",
        "edsm_api_key",
        "eddn_submission_enabled",
        "edsm_tracking_enabled",
        "spansh_enabled",
        "voice_enabled",
        "first_run_complete",
        # Phase 3 Week 13 onboarding and settings
        "first_run_completed",
        "first_run_completed_at",
        "settings_preset",
        "settings_ai_provider",
        "settings_overlay_opacity",
        "settings_overlay_anchor",
        # Phase 3.1 overlay event toggles and click-through persistence
        "overlay_events",
        "overlay_click_through",
        # Privacy toggles (all default OFF)
        "privacy_eddn_submission",
        "privacy_edsm_tracking",
        "privacy_squadron_telemetry",
        "privacy_ai_provider_calls",
        "privacy_crash_reports",
        "privacy_usage_analytics",
    }
)


class ConfigVault:
    """
    Encrypted key-value store for OmniCOVAS configuration.

    Each value is individually DPAPI-encrypted before being written to disk.
    The file on disk is a JSON map of {key: base64_encrypted_value}.

    Reads transparently decrypt. Writes transparently encrypt.

    Usage:
        vault = ConfigVault()
        vault.set("gemini_api_key", "AIza...")
        key = vault.get("gemini_api_key")  # returns decrypted string
    """

    def __init__(self, vault_path: Path | None = None) -> None:
        self._path = vault_path or VAULT_FILE
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, str] = self._load_from_disk()

    def _load_from_disk(self) -> dict[str, str]:
        """Load the encrypted JSON blob from disk."""
        if not self._path.exists():
            return {}

        try:
            with open(self._path, encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {}
                raw: Any = json.loads(content)
                if not isinstance(raw, dict):
                    logger.warning("Config vault file is not a JSON object, resetting.")
                    return {}
                # Only keep keys whose values are strings (base64 encrypted blobs)
                return {k: v for k, v in raw.items() if isinstance(v, str)}
        except (OSError, json.JSONDecodeError) as e:
            logger.error(
                "Failed to read config vault at %s: %s. Starting empty.",
                self._path,
                e,
            )
            return {}

    def _save_to_disk(self) -> None:
        """Persist the current encrypted data back to disk."""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError as e:
            logger.error("Failed to write config vault at %s: %s", self._path, e)

    def _encrypt(self, plaintext: str) -> str | None:
        """
        Encrypt a string using Windows DPAPI.

        Returns:
            Base64-encoded encrypted blob, or None if DPAPI unavailable.
        """
        try:
            import win32crypt  # type: ignore[import-untyped,unused-ignore]

            encrypted_bytes: bytes = win32crypt.CryptProtectData(
                plaintext.encode("utf-8"),
                "OmniCOVAS",  # Description (stored in blob)
                None,  # Optional entropy
                None,
                None,
                0,
            )
            return base64.b64encode(encrypted_bytes).decode("ascii")
        except ImportError:
            logger.error(
                "pywin32 not installed; cannot encrypt. Vault is Windows-only."
            )
            return None
        except Exception as e:
            logger.error("DPAPI encryption failed: %s", e)
            return None

    def _decrypt(self, ciphertext_b64: str) -> str | None:
        """
        Decrypt a base64-encoded DPAPI blob.

        Returns:
            Decrypted plaintext, or None if decryption failed.
        """
        try:
            import win32crypt  # type: ignore[import-untyped,unused-ignore]

            encrypted_bytes = base64.b64decode(ciphertext_b64.encode("ascii"))
            # CryptUnprotectData returns (description, data)
            _description, data = win32crypt.CryptUnprotectData(
                encrypted_bytes, None, None, None, 0
            )
            decrypted: str = data.decode("utf-8")
            return decrypted
        except ImportError:
            logger.error(
                "pywin32 not installed; cannot decrypt. Vault is Windows-only."
            )
            return None
        except Exception as e:
            logger.error("DPAPI decryption failed: %s", e)
            return None

    def get(self, key: str) -> str | None:
        """
        Retrieve a value from the vault.

        Args:
            key: Configuration key name

        Returns:
            Decrypted plaintext value, or None if missing or decryption failed.
        """
        if key not in CONFIG_KEYS:
            logger.warning("Vault.get called with unknown key: %s", key)

        encrypted = self._data.get(key)
        if encrypted is None:
            return None

        return self._decrypt(encrypted)

    def set(self, key: str, value: str) -> bool:
        """
        Store a value in the vault (encrypted).

        Args:
            key: Configuration key name
            value: Plaintext value to encrypt and store

        Returns:
            True if stored successfully, False if encryption failed.
        """
        if key not in CONFIG_KEYS:
            logger.warning("Vault.set called with unknown key: %s", key)

        encrypted = self._encrypt(value)
        if encrypted is None:
            return False

        self._data[key] = encrypted
        self._save_to_disk()
        logger.debug("Vault stored key: %s", key)
        return True

    def delete(self, key: str) -> bool:
        """
        Remove a value from the vault.

        Args:
            key: Configuration key name

        Returns:
            True if removed, False if it was not present.
        """
        if key in self._data:
            del self._data[key]
            self._save_to_disk()
            logger.debug("Vault deleted key: %s", key)
            return True
        return False

    def has(self, key: str) -> bool:
        """Check whether a key exists in the vault (without decrypting)."""
        return key in self._data

    def keys(self) -> list[str]:
        """Return the list of keys currently stored (useful for UI/debug)."""
        return list(self._data.keys())

    def list_keys(self) -> list[str]:
        """Return the list of keys currently stored.

        Alias for keys(); used by Week 13 export APIs.
        """
        return self.keys()

    def clear_all(self) -> None:
        """Wipe all keys from the vault (destructive operation).

        Used by the /privacy/delete endpoint (Law 8: Sovereignty).
        Requires user confirmation before calling.
        """
        self._data.clear()
        self._save_to_disk()
        logger.warning("Vault cleared entirely")
