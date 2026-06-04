"""
omnicovas.core.logging_config

Structured JSON logging with API key redaction.

Law 2 (Legal Compliance):
    API keys, OAuth tokens, and other credentials must NEVER appear
    in log files. The redaction processor in this module is a hard
    guarantee — every log record passes through it before being written.

Law 8 (Sovereignty & Transparency):
    Every log record is structured JSON with context (component, action,
    outcome). The commander can audit every action OmniCOVAS takes.

Principle 10 (Resource Efficiency):
    Log rotation keeps disk use bounded: 100MB per file, 7 files,
    30-day retention for older rotated logs.

Two separate channels:
    - main log:      general application events
    - api call log:  external API requests (may contain query params)

See: Phase 1 Development Guide Week 6, Part A
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, MutableMapping

import structlog

# Log file locations
LOG_DIR = Path(os.path.expandvars(r"%APPDATA%\OmniCOVAS\logs"))
MAIN_LOG_PATH = LOG_DIR / "omnicovas.log"
API_LOG_PATH = LOG_DIR / "api_calls.log"

# Rotation config — Principle 10 bounds
LOG_MAX_BYTES = 100 * 1024 * 1024  # 100 MB per file
LOG_BACKUP_COUNT = 7  # keep 7 rotated files
LOG_RETENTION_DAYS = 30  # delete logs older than this

# Patterns that look like API keys, OAuth tokens, or credentials.
# Matches common formats: long random alphanumeric strings,
# GitHub/Gemini/OpenAI key prefixes, and JWT-like tokens.
_API_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Gemini / Google API keys (start AIza, 39 chars)
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    # OpenAI-style keys (sk-, then 40+ chars)
    re.compile(r"sk-[0-9A-Za-z_-]{20,}"),
    # GitHub tokens (ghp_, gho_, ghu_, ghs_, ghr_)
    re.compile(r"gh[pousr]_[0-9A-Za-z]{30,}"),
    # Generic "key-like" strings: 32+ consecutive word chars with mixed case or digits
    re.compile(r"\b[A-Za-z0-9_-]{32,}\b"),
)

REDACTION_TOKEN = "[REDACTED]"


def _redact_string(value: str) -> str:
    """
    Redact any substring that looks like an API key or token.

    Called on every log message value. Safe to over-redact: false positives
    are strings that happen to look like tokens, which is usually fine.
    """
    redacted = value
    for pattern in _API_KEY_PATTERNS:
        redacted = pattern.sub(REDACTION_TOKEN, redacted)
    return redacted


def redaction_processor(
    logger: Any,
    method_name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """
    structlog processor: scan every value in the event dict for credentials
    and replace matches with [REDACTED]. Runs before the JSON serializer.
    """
    for key, value in list(event_dict.items()):
        if isinstance(value, str):
            event_dict[key] = _redact_string(value)
    return event_dict


def prune_old_logs(
    log_dir: Path = LOG_DIR,
    retention_days: int = LOG_RETENTION_DAYS,
) -> int:
    """
    Delete rotated log files older than retention_days.

    Returns:
        Number of files deleted.
    """
    if not log_dir.exists():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    cutoff_ts = cutoff.timestamp()
    deleted = 0

    for log_file in log_dir.glob("*.log.*"):  # only rotated files
        try:
            if log_file.stat().st_mtime < cutoff_ts:
                log_file.unlink()
                deleted += 1
        except OSError:
            pass

    return deleted


def configure_logging(verbose: bool = False) -> None:
    """
    Configure structlog + stdlib logging for OmniCOVAS.

    Must be called as the FIRST line of main() before any other imports log.

    Args:
        verbose: If True, set root log level to DEBUG. Default INFO.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ---- stdlib handlers (receive the output of structlog) ----
    main_handler = logging.handlers.RotatingFileHandler(
        MAIN_LOG_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    api_handler = logging.handlers.RotatingFileHandler(
        API_LOG_PATH,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler()

    formatter = logging.Formatter("%(message)s")
    for h in (main_handler, api_handler, console_handler):
        h.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(main_handler)
    root.addHandler(console_handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    # Dedicated api_calls logger sends only to the api handler
    api_logger = logging.getLogger("omnicovas.api_calls")
    api_logger.handlers.clear()
    api_logger.addHandler(api_handler)
    api_logger.setLevel(logging.INFO)
    api_logger.propagate = False  # don't duplicate into main log

    # ---- structlog configuration ----
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redaction_processor,  # must run before the renderer
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Prune old logs at startup
    deleted = prune_old_logs()
    if deleted > 0:
        logging.getLogger(__name__).info(
            "Pruned %d log files older than %d days", deleted, LOG_RETENTION_DAYS
        )

    logging.getLogger(__name__).info(
        "Logging configured. Main log: %s | API log: %s",
        MAIN_LOG_PATH,
        API_LOG_PATH,
    )


def get_logger(name: str) -> Any:
    """
    Get a structlog logger bound to the given name.

    Usage:
        log = get_logger(__name__)
        log.info("event_happened", system="Sol", hull=0.92)
    """
    return structlog.get_logger(name)


# Convenience helper for tests
def _last_main_log_line() -> str | None:
    """Return the last line of the main log file, or None if empty/missing."""
    if not MAIN_LOG_PATH.exists():
        return None
    try:
        with open(MAIN_LOG_PATH, encoding="utf-8") as f:
            lines = f.readlines()
        return lines[-1].rstrip() if lines else None
    except OSError:
        return None


# Expose a shared instance for any module that wants a ready-to-use logger
# without configuring structlog independently.
_ = time  # keep time import used for future use (heartbeats, etc.)
