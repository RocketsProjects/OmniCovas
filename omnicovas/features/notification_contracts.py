"""Notification candidate v1: source facts, not permission to present.

Only reviewed adapters construct candidates. Copy is an allowlisted template key;
diagnostics contain no commander names, locations, stories or raw Journal data.
"""

import math
from dataclasses import asdict, dataclass
from typing import Any

from omnicovas.core.observation import Scope

POLICY_VERSION = "nhi-director-1"
CATEGORIES = frozenset(
    {"combat", "navigation", "exploration", "mining", "engineering", "knowledge", "app"}
)
COPY_KEYS = frozenset(
    {
        "hull",
        "fuel",
        "heat",
        "shields",
        "module",
        "interdiction",
        "route",
        "routine",
        "biology",
        "mapped",
        "objective",
        "story",
        "materials",
        "summary",
        "prospector",
    }
)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    scope: Scope
    producer: str
    event_type: str
    category: str
    level: str
    observed_at: float | None
    evidence_ref: str
    copy_key: str
    source: str = "journal"
    confidence: str = "verified"
    replay: bool = False
    supported: bool = True
    condition: str = ""
    state: str = "active"
    revision: int = 0
    priority: int = 0
    ttl: float = 120
    freshness: float = 10
    semantic_key: str = ""
    aggregation_key: str = ""
    quantity: int = 1
    spoiler: bool = False
    automatic: bool = True
    domain_eligible: bool = True
    preference_key: str = ""
    surfaces: tuple[str, ...] = ("desktop", "overlay")
    value: float | None = None
    destination: str = "activity-log"
    production: str = "unavailable"
    schema_version: int = 1
    # Opaque owner reference a presenter may hand back to the owning surface
    # (e.g. a GKI briefing id). Never a name, title, location or passage.
    subject: str = ""
    # Opaque fingerprint of the place a knowledge moment describes (GKI-08). A
    # newer moment at another place supersedes one still waiting, so a held
    # briefing never appears as if it described the commander's new arrival.
    context_key: str = ""

    def __post_init__(self) -> None:
        if (
            self.schema_version != 1
            or self.category not in CATEGORIES
            or self.copy_key not in COPY_KEYS
        ):
            raise ValueError("Unsupported candidate schema/category/copy")
        if self.level not in {"record", "glance", "interrupt"} or self.state not in {
            "active",
            "resolved",
            "unknown",
        }:
            raise ValueError("Invalid attention or condition state")
        if not self.candidate_id or not self.producer or not self.event_type:
            raise ValueError("Missing candidate identity")
        for value in (
            self.candidate_id,
            self.producer,
            self.event_type,
            self.evidence_ref,
            self.condition,
            self.semantic_key,
            self.aggregation_key,
            self.subject,
            self.context_key,
        ):
            if not isinstance(value, str) or len(value) > 160:
                raise ValueError("Unbounded candidate identifier")
        if (
            not 0 <= self.priority <= 100
            or not 0 <= self.revision
            or not 1 <= self.quantity <= 100000
        ):
            raise ValueError("Invalid priority/revision/quantity")
        for number in (self.observed_at, self.value, self.ttl, self.freshness):
            if number is not None and (
                isinstance(number, bool)
                or not isinstance(number, (float, int))
                or not math.isfinite(number)
            ):
                raise ValueError("Invalid numeric evidence")
        if not 0 < self.ttl <= 3600 or not 0 < self.freshness <= 60:
            raise ValueError("Invalid age budget")
        if not set(self.surfaces) <= {"desktop", "overlay"}:
            raise ValueError("Unsupported surface")
        if self.production not in {
            "unavailable",
            "producer_observed",
            "bridge_observed",
            "inferred_overlay_eligibility",
            "activity_record_observed",
        }:
            raise ValueError("Unsupported production observation")

    def record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Preferences:
    """Effective attention preferences; built by the service from Settings owners."""

    profile: str = "Minimal"
    overlay: bool = True
    overlay_glances: bool = False
    quiet: bool = False
    lore: bool = False
    spoilers: bool = False
    disabled: frozenset[str] = frozenset()
    disabled_events: frozenset[str] = frozenset()
    duration: float = 4
    interval: float = 20
    max_per_minute: int = 2
    mining_target_alerts: bool = False

    def __post_init__(self) -> None:
        if self.profile not in {"Minimal", "Flightdeck", "Explorer", "Custom"}:
            raise ValueError("Unknown notification profile")
        if (
            not 4 <= self.duration <= 30
            or not 20 <= self.interval <= 600
            or not 1 <= self.max_per_minute <= 2
        ):
            raise ValueError("Unsafe attention budget")

    def denial(self, c: Candidate) -> str | None:
        if not c.automatic:
            return "automatic_delivery_forbidden"
        if not c.domain_eligible:
            return "domain_ineligible"
        if c.category in self.disabled or c.preference_key in self.disabled_events:
            return "category_disabled"
        if c.level == "interrupt":
            return None
        if self.quiet:
            return "quiet_mode"
        if c.category == "knowledge":
            # Historical storytelling has its own consent (Galactic Intelligence),
            # independent of the attention profile. It never widens surfaces.
            if not self.lore:
                return "lore_disabled"
            if c.spoiler and not self.spoilers:
                return "spoiler_protected"
            return None
        if c.copy_key == "prospector":
            return None if self.mining_target_alerts else "mining_targets_disabled"
        if self.profile == "Minimal":
            return "minimal_profile"
        if self.profile == "Explorer" and c.category not in {
            "exploration",
            "engineering",
            "knowledge",
            "app",
        }:
            return "profile_category"
        return None

    def record(self) -> dict[str, Any]:
        result = asdict(self)
        result["disabled"] = sorted(self.disabled)
        result["disabled_events"] = sorted(self.disabled_events)
        return result


@dataclass(frozen=True)
class Decision:
    candidate: Candidate
    evaluated_at: float
    decision: str
    reason: str
    surface: str | None
    condition_state: str
    preferences: Preferences
    combat: bool
    live: bool
    expires_at: float | None
    arbitration: dict[str, Any]
    cooldown_until: float | None = None
    policy_version: str = POLICY_VERSION
    presentation_mode: str = "shadow"

    def record(self) -> dict[str, Any]:
        result = asdict(self)
        result["preferences"] = self.preferences.record()
        # A decision is never evidence of display. In director mode the actual
        # outcome lives in the presenter's delivery receipts.
        result["production_presentation"] = (
            "see_delivery_receipts"
            if self.presentation_mode == "director"
            else "unavailable"
        )
        result["comparison"] = {
            "observation": (
                "producer_observed"
                if self.candidate.production == "inferred_overlay_eligibility"
                else self.candidate.production
            ),
            "configured_overlay_event_enabled": (
                self.candidate.preference_key not in self.preferences.disabled_events
                if self.candidate.production == "inferred_overlay_eligibility"
                else None
            ),
            "scope": "event-toggle inference; actual display unavailable",
            "shadow_outcome": self.decision,
            "reason": self.reason,
        }
        return result
