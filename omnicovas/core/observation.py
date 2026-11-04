"""Immutable dispatch provenance carried across asynchronous producer tasks."""

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256


def fingerprint(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()[:32]


def timestamp(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo is not None else None
    except (ValueError, OverflowError, OSError):
        return None


@dataclass(frozen=True)
class Scope:
    commander: str | None = None
    ship: str | None = None
    generation: int = 0
    session: str | None = None


@dataclass(frozen=True)
class Observation:
    event_id: str
    event_type: str
    observed_at: float | None
    source: str
    replay: bool
    scope: Scope


CURRENT_OBSERVATION: ContextVar[Observation | None] = ContextVar(
    "notification_observation", default=None
)
