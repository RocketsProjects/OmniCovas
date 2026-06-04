"""
omnicovas.core.confirmation_gate

The Confirmation Gate — the single most important component in OmniCOVAS.

Law 1 (Confirmation Gate):
    The AI will NEVER perform, trigger, or initiate any in-game action
    without explicit commander confirmation.

    This is non-negotiable. It cannot be disabled by settings, macros,
    scripts, or any other mechanism. Every AI-suggested action passes
    through this middleware before reaching any output.

Architecture:
    AI Recommendation
        → ConfirmationGate.require_confirmation(action_type, details)
            → Logs the action intent
            → Phase 1: Auto-confirms (allows testing of the full pipeline)
            → Phase 3: Blocks pending UI confirmation from commander
            → Returns bool: True if approved, False if rejected/pending
    Action proceeds only if gate returns True.

Phase 1 Scope:
    The gate is wired into the critical path RIGHT NOW.
    Phase 1 auto-confirms so we can test the full pipeline end-to-end.
    Phase 3 replaces auto-confirmation with real UI prompts.
    The gate interface does not change between phases — only the
    _await_commander_response() implementation.

Law 8 (Sovereignty & Transparency):
    Every confirmation request is logged to the Activity Log
    (added in Week 6) for full audit trail.

See: Master Blueprint v4.0 Section 0 (Law 1)
See: Phase 1 Development Guide Week 4, Part C
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """
    Every kind of AI-suggested action must be explicitly defined here.

    Adding a new action type is a deliberate design decision —
    it forces a review of whether that action should exist at all.

    Naming convention: VERB_NOUN (e.g. PLOT_ROUTE, SUGGEST_TRADE).
    """

    # Navigation
    PLOT_ROUTE = "plot_route"
    SUGGEST_JUMP_TARGET = "suggest_jump_target"
    BOOKMARK_LOCATION = "bookmark_location"

    # Combat
    COMBAT_ALERT = "combat_alert"
    SUGGEST_RETREAT = "suggest_retreat"
    TARGET_RECOMMENDATION = "target_recommendation"

    # Trading
    SUGGEST_TRADE_ROUTE = "suggest_trade_route"
    MARKET_ADVISORY = "market_advisory"

    # Engineering
    ENGINEERING_RECOMMENDATION = "engineering_recommendation"
    MATERIAL_ADVISORY = "material_advisory"

    # BGS / Powerplay
    BGS_SUGGESTION = "bgs_suggestion"
    POWERPLAY_SUGGESTION = "powerplay_suggestion"

    # Exobiology / Exploration
    SCAN_TARGET_SUGGESTION = "scan_target_suggestion"
    BIO_PREDICTION = "bio_prediction"

    # Meta
    SYSTEM_ADVISORY = "system_advisory"
    INFORMATION_ONLY = "information_only"


class ConfirmationDecision(str, Enum):
    """
    Result of a confirmation request.

    APPROVED:  commander explicitly confirmed (or Phase 1 auto-confirm)
    REJECTED:  commander explicitly declined
    TIMED_OUT: no response within the allowed window
    """

    APPROVED = "approved"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ConfirmationRecord:
    """
    Full audit record of one confirmation event.

    Immutable — every record is a permanent part of the audit trail.
    """

    action_type: ActionType
    summary: str
    details: dict[str, Any]
    decision: ConfirmationDecision
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ConfirmationGate:
    """
    Middleware that blocks every AI-suggested action until the commander approves.

    Phase 1 behavior: auto-approves, logs the event, returns True.
    Phase 3 behavior: presents the request to the commander via UI,
                      waits for explicit yes/no, returns the result.

    The interface is stable across phases. Downstream code does not change.

    Usage:
        gate = ConfirmationGate()
        approved = await gate.require_confirmation(
            action_type=ActionType.PLOT_ROUTE,
            summary="Plot route to Colonia",
            details={"destination": "Colonia", "jumps_estimated": 22},
        )
        if approved:
            # proceed with the action
    """

    def __init__(self, auto_approve: bool = True) -> None:
        """
        Args:
            auto_approve: Phase 1 default. Set False to simulate UI blocking
                          (used in tests).
        """
        self._auto_approve = auto_approve
        self._audit_log: list[ConfirmationRecord] = []

    async def require_confirmation(
        self,
        action_type: ActionType,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """
        Ask the commander to confirm an AI-suggested action.

        Args:
            action_type: Category of action, from ActionType enum
            summary: One-sentence human-readable description
            details: Structured data about the action (destination, target, etc.)

        Returns:
            True if approved, False if rejected or timed out.

        Law 1 (Confirmation Gate):
            There is no bypass. Every AI-suggested action MUST call this
            method before producing any output. Calling this method is
            not optional — the dispatcher enforces it.

        Law 8 (Sovereignty & Transparency):
            Every confirmation request is recorded permanently. The
            commander can inspect the audit log at any time.
        """
        details = details or {}

        # Log the request (pre-decision)
        logger.info(
            "[CONFIRMATION REQUEST] %s: %s",
            action_type.value,
            summary,
        )

        # Phase 1: resolve the decision
        decision = await self._await_commander_response(
            action_type=action_type,
            summary=summary,
            details=details,
        )

        # Record the outcome
        record = ConfirmationRecord(
            action_type=action_type,
            summary=summary,
            details=dict(details),
            decision=decision,
        )
        self._audit_log.append(record)

        approved = decision == ConfirmationDecision.APPROVED

        logger.info(
            "[CONFIRMATION %s] %s: %s",
            decision.value.upper(),
            action_type.value,
            summary,
        )

        return approved

    async def _await_commander_response(
        self,
        action_type: ActionType,
        summary: str,
        details: dict[str, Any],
    ) -> ConfirmationDecision:
        """
        Resolve the commander's decision on a confirmation request.

        Phase 1: always returns APPROVED when auto_approve is True.
                 The full pipeline is exercised end-to-end; the UI
                 replacement in Phase 3 slots in here unchanged.

        Phase 3: will display UI prompt and await commander response.

        Args:
            action_type: The kind of action being requested
            summary: Human-readable description
            details: Structured action details

        Returns:
            APPROVED, REJECTED, or TIMED_OUT
        """
        if self._auto_approve:
            return ConfirmationDecision.APPROVED

        # When auto_approve is False we treat it as an immediate reject.
        # This is used by tests to verify the "no bypass" guarantee.
        return ConfirmationDecision.REJECTED

    @property
    def audit_log(self) -> list[ConfirmationRecord]:
        """
        Read-only view of the full confirmation audit trail.

        Law 8: the commander can always inspect every confirmation decision.
        """
        return list(self._audit_log)

    @property
    def total_requests(self) -> int:
        """Count of confirmation requests seen since startup."""
        return len(self._audit_log)
