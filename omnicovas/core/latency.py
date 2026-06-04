"""
omnicovas.core.latency

Latency Budget Framework -- Phase 2 Pattern 2.

Every event type has a budget. Dispatches that exceed it are logged as
warnings in Weeks 7-8. In Week 9, the enforcement flips to CI hard-fail
via tests/test_latency_budgets.py with a 2x CI tolerance multiplier.

Architecture:
    main() creates a BudgetedDispatcher wrapping the EventDispatcher.
    JournalWatcher and StatusReader call BudgetedDispatcher.dispatch()
    instead of EventDispatcher.dispatch() directly.

Why a 2x CI tolerance multiplier:
    GitHub Actions shared runners show 2-3x performance variance vs
    dedicated hardware. The 2x multiplier prevents flaky CI without
    loosening real discipline on local development. Do NOT raise the
    multiplier to mask actual slowness -- fix the handler instead.

Latency budgets (local):
    HullDamage    100ms  -- combat-speed; immediate feedback required
    ShieldsDown   100ms  -- combat-speed
    FSDJump       200ms  -- navigation; sub-second acceptable
    Docked        200ms  -- navigation
    Undocked      100ms  -- navigation
    Loadout       500ms  -- outfitting; commander expects slight delay
    Status        100ms  -- Status.json polling; must be fast

See: Master Blueprint v4.1 Section 14 (Performance Commitments)
See: Phase 2 Development Guide Week 7, Part F
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Coroutine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Budget definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LatencyBudget:
    """A single event type's latency budget.

    Args:
        event_type: Journal or synthetic event type string.
        budget_ms: Maximum acceptable dispatch time in milliseconds
                   on a local development machine. CI applies a 2x
                   multiplier via in_ci_environment().
    """

    event_type: str
    budget_ms: int


# All budgeted event types. Keys match the journal event type strings that
# the EventDispatcher receives. Add new entries here when new event types
# are introduced -- do not hardcode budgets inside test files.
BUDGETS: dict[str, LatencyBudget] = {
    # Combat events -- must be sub-100ms; pilots react in real time
    "HullDamage": LatencyBudget("HullDamage", 100),
    "ShieldsDown": LatencyBudget("ShieldsDown", 100),
    # Navigation events -- sub-200ms; frame transitions are visible
    "FSDJump": LatencyBudget("FSDJump", 200),
    "Docked": LatencyBudget("Docked", 200),
    "Undocked": LatencyBudget("Undocked", 100),
    # Outfitting -- heavier parsing; 500ms acceptable at a station
    "Loadout": LatencyBudget("Loadout", 500),
    # Status.json synthetic event -- polled at 500ms; must be well under
    "Status": LatencyBudget("Status", 100),
    # Week 9 additions -- Extended Events, Hull Triggers, Cargo
    "Cargo": LatencyBudget("Cargo", 200),
    "CommitCrime": LatencyBudget("CommitCrime", 150),
    "Bounty": LatencyBudget("Bounty", 150),
    "ShipDestroyed": LatencyBudget("ShipDestroyed", 150),
    "Died": LatencyBudget("Died", 150),
    "ShieldsUp": LatencyBudget("ShieldsUp", 100),
}


# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------


def in_ci_environment() -> bool:
    """Return True if running inside GitHub Actions (or any CI that sets CI=true).

    GitHub Actions sets the CI environment variable automatically.
    The 2x tolerance multiplier for CI budgets is applied here.
    """
    return os.environ.get("CI", "").lower() in ("true", "1", "yes")


def effective_budget_ms(event_type: str) -> int | None:
    """Return the effective budget for event_type given the current environment.

    Returns None if the event type has no registered budget (unknown types
    pass through without measurement -- not a failure).

    Args:
        event_type: Journal event type string.

    Returns:
        Budget in milliseconds (2x in CI), or None if not budgeted.
    """
    budget = BUDGETS.get(event_type)
    if budget is None:
        return None
    multiplier = 2 if in_ci_environment() else 1
    return budget.budget_ms * multiplier


# ---------------------------------------------------------------------------
# Budgeted dispatcher wrapper
# ---------------------------------------------------------------------------


class BudgetedDispatcher:
    """Wraps EventDispatcher.dispatch() with latency measurement.

    Replaces the raw dispatcher.dispatch in main() so every journal line
    passes through budget measurement without modifying EventDispatcher.

    Phase 2 behavior: log a warning on breach (Week 9 flips to hard-fail).

    Usage in main():
        budgeted = BudgetedDispatcher(dispatcher)
        journal_watcher = JournalWatcher(dispatch_fn=budgeted.dispatch)
        status_reader = StatusReader(dispatch_fn=budgeted.dispatch)
    """

    def __init__(self, dispatcher: Any) -> None:
        self._dispatcher = dispatcher

    async def dispatch(self, raw_line: str) -> None:
        """Parse the raw journal line, measure dispatch time, log on breach.

        Args:
            raw_line: Raw JSON string from journal or Status.json.
        """
        import json as _json

        # Parse event type before dispatch so we can look up the budget.
        # On malformed JSON the dispatcher handles the error internally --
        # we still call it and measure (the budget will be irrelevant).
        try:
            event_type = _json.loads(raw_line).get("event", "Unknown")
        except (_json.JSONDecodeError, AttributeError):
            event_type = "Unknown"

        start = time.perf_counter()
        await self._dispatcher.dispatch(raw_line)
        elapsed_ms = (time.perf_counter() - start) * 1000

        budget_ms = effective_budget_ms(event_type)
        if budget_ms is not None and elapsed_ms > budget_ms:
            logger.warning(
                "latency_budget_exceeded",
                extra={
                    "event_type": event_type,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "budget_ms": budget_ms,
                    "ci": in_ci_environment(),
                },
            )

    @property
    def events_processed(self) -> int:
        """Proxy to underlying dispatcher counter."""
        return int(self._dispatcher.events_processed)


# ---------------------------------------------------------------------------
# Standalone measurement helper (for tests and future use)
# ---------------------------------------------------------------------------


async def measure(
    event_type: str,
    coro: Coroutine[Any, Any, None],
) -> float:
    """Run a coroutine and return elapsed milliseconds.

    Checks elapsed against the budget for event_type and logs a warning
    if exceeded. Returns elapsed_ms regardless so callers can assert on it.

    Args:
        event_type: Used for budget lookup and log fields.
        coro: The coroutine to time.

    Returns:
        Elapsed time in milliseconds.
    """
    start = time.perf_counter()
    await coro
    elapsed_ms = (time.perf_counter() - start) * 1000

    budget_ms = effective_budget_ms(event_type)
    if budget_ms is not None and elapsed_ms > budget_ms:
        logger.warning(
            "latency_budget_exceeded",
            extra={
                "event_type": event_type,
                "elapsed_ms": round(elapsed_ms, 2),
                "budget_ms": budget_ms,
                "ci": in_ci_environment(),
            },
        )

    return elapsed_ms
