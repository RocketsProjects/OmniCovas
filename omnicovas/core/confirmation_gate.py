"""
omnicovas.core.confirmation_gate

The Confirmation Gate — the single most important component in OmniCOVAS.

Law 1 (Confirmation Gate):
    The AI will NEVER perform, trigger, or initiate any in-game action
    without explicit commander confirmation.

    This is non-negotiable. It cannot be disabled by settings, macros,
    scripts, or any other mechanism. Every AI-suggested action passes
    through this middleware before reaching any output.

Current scope:
    This class is a fail-closed policy boundary for two advisory production
    callers. It may approve producing a draft, never a Commander-impacting
    action. ``REQUIRE_COMMANDER`` is not wired to the Week 13 queue and safely
    rejects until that integration exists. The protected Activity Log export
    is the reference two-step Commander confirmation flow.

Law 8 (Sovereignty & Transparency):
    This object retains process-lifetime diagnostic records. Durable proof is
    owned by the shared Activity Log / Week 13 lifecycle, not this list.

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

    APPROVED:  the configured policy approved producing an advisory draft
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

    Immutable after creation, but retained only for this gate object's lifetime.
    This record is not persistent Activity Log evidence.
    """

    action_type: ActionType
    summary: str
    details: dict[str, Any]
    decision: ConfirmationDecision
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GatePolicy(Enum):
    """How a `ConfirmationGate` instance resolves a confirmation request.

    There is deliberately no "approve anything" policy. Phase 10 reconciliation
    (PB10-R6) removed the previous `auto_approve: bool = True` default, under
    which omitting a constructor argument silently approved every request while
    the class docstring still promised non-bypassable confirmation.
    """

    #: Fail closed. The default for any gate whose policy was not stated.
    DENY = "deny"

    #: The request is an advisory, non-side-effecting step — drafting or
    #: labelling text that performs no action on the Commander's behalf, in the
    #: game, on local state, or against any external service. Approving it
    #: authorises *producing the draft*, never performing an action.
    ADVISORY_NO_SIDE_EFFECT = "advisory_no_side_effect"

    #: The request would change something for the Commander and therefore needs
    #: a real decision. This class cannot obtain one: commander-facing
    #: confirmation is owned by the Week 13 confirmation queue
    #: (`omnicovas/api/week13.py`) and its two-step propose/authorize flow (see
    #: `omnicovas/api/activity_log.py` export lifecycle). A gate configured this
    #: way fails closed until it is wired to that queue.
    REQUIRE_COMMANDER = "require_commander"


class ConfirmationGate:
    """
    Confirmation boundary for AI-suggested steps (Law 1).

    Scope, stated precisely:

    - This class resolves *advisory* steps — AI drafting and proposal
      labelling — and records process-lifetime diagnostics. Both production
      call sites are advisory and perform no action: the Phase 9 campaign AI
      draft (`omnicovas/features/campaign.py`, `is_fact=False`) and the
      route-activation *review* proposal (`omnicovas/features/navigation.py`,
      "review only, no in-game action").

    - Genuine Commander-impacting confirmation is **not** owned here. It is
      owned by the Week 13 confirmation queue and its two-step
      propose → commander decision → authorize flow, which refuses declined,
      expired, unknown, mismatched and already-consumed decisions. The Activity
      Log export lifecycle is the reference implementation.

    A gate with no stated policy denies. Constructing one and forgetting to say
    what it is for can never approve anything.

    Usage:
        gate = ConfirmationGate.for_advisory_drafting()
        approved = await gate.require_confirmation(
            action_type=ActionType.PLOT_ROUTE,
            summary="Draft a route review to Colonia",
            details={"destination": "Colonia"},
        )
        if approved:
            # produce the draft; performing an action still requires the
            # Week 13 commander confirmation queue
    """

    def __init__(self, policy: GatePolicy = GatePolicy.DENY) -> None:
        """
        Args:
            policy: What this gate is for. Defaults to `GatePolicy.DENY` so an
                    unconfigured gate fails closed rather than approving.
        """
        self._policy = policy
        self._audit_log: list[ConfirmationRecord] = []

    @classmethod
    def for_advisory_drafting(cls) -> ConfirmationGate:
        """A gate for AI drafting / proposal labelling that performs no action.

        Named rather than boolean so every production call site declares, at the
        construction point, that it is authorising a draft and not an action.
        """
        return cls(GatePolicy.ADVISORY_NO_SIDE_EFFECT)

    @classmethod
    def denying(cls) -> ConfirmationGate:
        """A gate that refuses everything. Useful for tests and safe defaults."""
        return cls(GatePolicy.DENY)

    @property
    def policy(self) -> GatePolicy:
        """The policy this gate was constructed with."""
        return self._policy

    @property
    def approves_side_effecting_actions(self) -> bool:
        """Always False.

        No policy on this class authorises a Commander-impacting action. Kept
        explicit so the guarantee is assertable from tests and readable at call
        sites.
        """
        return False

    async def require_confirmation(
        self,
        action_type: ActionType,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> bool:
        """
        Resolve an AI-suggested step under the configured policy.

        Args:
            action_type: Category of action, from ActionType enum
            summary: One-sentence human-readable description
            details: Structured data about the action (destination, target, etc.)

        Returns:
            True if approved, False if rejected or timed out.

        Law 1 (Confirmation Gate):
            This class cannot approve a side-effecting action. A future caller
            requiring Commander authority must first wire ``REQUIRE_COMMANDER``
            to the Week 13 queue or use the owning two-step lifecycle directly.

        Law 8 (Sovereignty & Transparency):
            Requests are retained in memory for the lifetime of this object.
            Persistent proof belongs in the shared Activity Log lifecycle.
        """
        details = details or {}

        # Log the request (pre-decision)
        logger.info(
            "[CONFIRMATION REQUEST] %s: %s",
            action_type.value,
            summary,
        )

        # Resolve under the explicit, fail-closed policy.
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
        Resolve the decision for a confirmation request.

        Policy-driven and fail-closed (PB10-R6):

        - `ADVISORY_NO_SIDE_EFFECT` approves producing a draft. It does not
          authorise any action.
        - `REQUIRE_COMMANDER` refuses, because a genuine Commander decision
          lives in the Week 13 confirmation queue and this class has no channel
          to it. Wiring that channel is the only way this policy may ever
          approve.
        - `DENY` refuses.

        There is no path here that approves a Commander-impacting action.

        Args:
            action_type: The kind of action being requested
            summary: Human-readable description
            details: Structured action details

        Returns:
            APPROVED, REJECTED, or TIMED_OUT
        """
        if self._policy is GatePolicy.ADVISORY_NO_SIDE_EFFECT:
            # Authorises producing a draft. The caller must not perform an
            # action on the strength of this decision.
            return ConfirmationDecision.APPROVED

        if self._policy is GatePolicy.REQUIRE_COMMANDER:
            # Fail closed. A real Commander decision lives in the Week 13
            # confirmation queue; this class has no channel to it, so it must
            # never manufacture an approval on the Commander's behalf.
            logger.warning(
                "[CONFIRMATION DENIED] %s: %s — REQUIRE_COMMANDER gate is not "
                "wired to the Week 13 confirmation queue; refusing rather than "
                "approving without a Commander decision.",
                action_type.value,
                summary,
            )
            return ConfirmationDecision.REJECTED

        return ConfirmationDecision.REJECTED

    @property
    def audit_log(self) -> list[ConfirmationRecord]:
        """
        Copy of the process-lifetime confirmation diagnostic records.

        This is not persistent proof. Commander-inspectable durable evidence is
        owned by the Activity Log / Week 13 lifecycle.
        """
        return list(self._audit_log)

    @property
    def total_requests(self) -> int:
        """Count of confirmation requests seen since startup."""
        return len(self._audit_log)
