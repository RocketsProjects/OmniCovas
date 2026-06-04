"""Source router — maps call-type requests to WorkflowSourcePlan decisions.

The router consults the SourceRegistry to find the best source for a given
call-type, then returns a RouterDecision containing a WorkflowSourcePlan and
a FallbackDecision. No outbound calls are made; the router only plans.

Resolution priority (Source Capability Routing Reference v1, Section 1):
  1. ENABLED local sources
  2. ENABLED external sources (disabled in Phase 5 foundation)
  3. Fallback: DISABLED → REQUIRES_AUTHORIZATION → NO_VERIFIED_SOURCE → UNKNOWN

NullProvider mode: all plans produced here are nullprovider_safe=True because
source-routing is data routing, not AI routing. AI is never the source of facts.

Authority:
    Backend Blueprint v1.0 — source routing contract
    Source Capability Routing Reference v1 — Section 2 (call-type router)
    Master Blueprint v5.0 — Law 4 (AI Agnosticism), Law 5 (Zero Hallucination)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from omnicovas.core.provenance import EntityRef
from omnicovas.core.source_plan import FallbackDecision, WorkflowSourcePlan
from omnicovas.core.source_registry import (
    SourceCapability,
    SourceDefinition,
    SourceRegistry,
    SourceState,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RouterDecision:
    """Immutable result of a SourceRouter.resolve() call."""

    plan: WorkflowSourcePlan
    is_supported: bool
    reason: str


class SourceRouter:
    """Maps call-type strings to WorkflowSourcePlan decisions.

    The router never calls any provider — it only inspects the registry and
    returns a plan. All decisions are deterministic given registry state.
    """

    def __init__(self, registry: SourceRegistry) -> None:
        self._registry = registry

    def resolve(
        self,
        call_type: str,
        *,
        entity_ref: EntityRef | None = None,
        workflow_id: str | None = None,
        nullprovider_mode: bool = False,
    ) -> RouterDecision:
        """Resolve call_type to a RouterDecision.

        call_type must match a SourceCapability enum value. If it does not,
        the decision is UNSUPPORTED. All plans are nullprovider_safe because
        source routing does not depend on an AI provider.
        """
        effective_workflow_id = workflow_id or str(uuid.uuid4())

        cap = self._capability_for(call_type)
        if cap is None:
            plan = WorkflowSourcePlan.make(
                call_type=call_type,
                primary_source_id=None,
                fallback_decision=FallbackDecision.UNSUPPORTED,
                workflow_id=effective_workflow_id,
                entity_ref=entity_ref,
                notes=f"call_type '{call_type}' is not a known SourceCapability",
                nullprovider_safe=True,
            )
            return RouterDecision(
                plan=plan,
                is_supported=False,
                reason=f"Unsupported call_type: {call_type!r}",
            )

        candidates = self._registry.list_by_capability(cap)
        if not candidates:
            plan = WorkflowSourcePlan.make(
                call_type=call_type,
                primary_source_id=None,
                fallback_decision=FallbackDecision.NO_VERIFIED_SOURCE,
                workflow_id=effective_workflow_id,
                entity_ref=entity_ref,
                notes=f"No source registered for capability {cap.value!r}",
                nullprovider_safe=True,
            )
            return RouterDecision(
                plan=plan,
                is_supported=False,
                reason=f"No verified source for capability: {cap.value}",
            )

        best = self._select_best(candidates)
        if best is not None:
            plan = WorkflowSourcePlan.make(
                call_type=call_type,
                primary_source_id=best.source_id,
                fallback_decision=FallbackDecision.SUPPORTED,
                workflow_id=effective_workflow_id,
                entity_ref=entity_ref,
                requires_auth=best.requires_auth,
                requires_consent=best.requires_consent,
                notes="",
                nullprovider_safe=True,
            )
            return RouterDecision(
                plan=plan,
                is_supported=True,
                reason=f"Resolved to source: {best.source_id}",
            )

        fallback, reason = self._fallback_decision(candidates)
        plan = WorkflowSourcePlan.make(
            call_type=call_type,
            primary_source_id=None,
            fallback_decision=fallback,
            workflow_id=effective_workflow_id,
            entity_ref=entity_ref,
            notes=reason,
            nullprovider_safe=True,
        )
        return RouterDecision(plan=plan, is_supported=False, reason=reason)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _capability_for(call_type: str) -> SourceCapability | None:
        """Return the SourceCapability whose value matches call_type, or None."""
        try:
            return SourceCapability(call_type)
        except ValueError:
            return None

    @staticmethod
    def _select_best(candidates: list[SourceDefinition]) -> SourceDefinition | None:
        """Return the best ENABLED source, preferring local sources."""
        enabled = [c for c in candidates if c.state == SourceState.ENABLED]
        if not enabled:
            return None
        local = [c for c in enabled if c.is_local]
        return local[0] if local else enabled[0]

    @staticmethod
    def _fallback_decision(
        candidates: list[SourceDefinition],
    ) -> tuple[FallbackDecision, str]:
        """Determine the most specific fallback given a non-empty candidate list."""
        states = {c.state for c in candidates}
        if (
            SourceState.REQUIRES_AUTH in states
            or SourceState.REQUIRES_CONSENT in states
        ):
            return (
                FallbackDecision.REQUIRES_AUTHORIZATION,
                "Source requires authorization",
            )
        if SourceState.DISABLED in states:
            return FallbackDecision.DISABLED, "Source is disabled"
        if SourceState.BLOCKED in states:
            return FallbackDecision.DISABLED, "Source is blocked"
        return FallbackDecision.UNKNOWN, "Source state unknown"
