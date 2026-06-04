"""WorkflowSourcePlan and ExternalRequestBundle — source routing data contracts.

WorkflowSourcePlan is produced by the SourceRouter and records how a workflow
intends to source data: which source, which call-type, the fallback decision,
and whether the plan is safe without an AI provider.

ExternalRequestBundle wraps a WorkflowSourcePlan with a request payload for
future dispatch. Construction requires a WorkflowSourcePlan — creating a bundle
without a plan raises ValueError at runtime and is a type error at check-time.

No outbound calls are made here.

Authority:
    Backend Blueprint v1.0 — source routing contract
    Source Capability Routing Reference v1 — Section 6 (external request design)
    Master Blueprint v5.0 — Law 1 (Confirmation Gate), Law 4 (AI Agnosticism)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from omnicovas.core.provenance import EntityRef


class FallbackDecision(str, Enum):
    """Router outcome for a call-type request.

    SUPPORTED means a usable source was found.
    All other values are fallback outcomes with specific reasons.
    """

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    NO_VERIFIED_SOURCE = "no_verified_source"
    DISABLED = "disabled"
    REQUIRES_AUTHORIZATION = "requires_authorization"
    UNKNOWN = "unknown"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class WorkflowSourcePlan:
    """Immutable record of how a workflow will source data.

    Produced by SourceRouter.resolve(). Records the intended source, fallback
    decision, and whether the plan is valid when no AI provider is active.
    primary_source_id is None when the fallback_decision is not SUPPORTED.
    """

    workflow_id: str
    call_type: str
    primary_source_id: str | None
    fallback_decision: FallbackDecision
    entity_ref: EntityRef | None
    created_at: datetime
    requires_auth: bool
    requires_consent: bool
    notes: str
    nullprovider_safe: bool

    @classmethod
    def make(
        cls,
        call_type: str,
        primary_source_id: str | None,
        fallback_decision: FallbackDecision,
        *,
        workflow_id: str | None = None,
        entity_ref: EntityRef | None = None,
        requires_auth: bool = False,
        requires_consent: bool = False,
        notes: str = "",
        nullprovider_safe: bool = True,
        created_at: datetime | None = None,
    ) -> WorkflowSourcePlan:
        """Convenience factory — generates a workflow_id when not provided."""
        return cls(
            workflow_id=workflow_id or str(uuid.uuid4()),
            call_type=call_type,
            primary_source_id=primary_source_id,
            fallback_decision=fallback_decision,
            entity_ref=entity_ref,
            created_at=created_at or _utc_now(),
            requires_auth=requires_auth,
            requires_consent=requires_consent,
            notes=notes,
            nullprovider_safe=nullprovider_safe,
        )


@dataclass(frozen=True)
class ExternalRequestBundle:
    """Wraps a WorkflowSourcePlan with request payload for future dispatch.

    plan is required — construction without a WorkflowSourcePlan raises
    ValueError at runtime. This enforces the plan-before-bundle invariant:
    every external request must be preceded by a source routing decision.
    """

    plan: WorkflowSourcePlan
    request_payload: dict[str, Any]
    enqueued_at: datetime
    priority: int

    def __post_init__(self) -> None:
        if not isinstance(self.plan, WorkflowSourcePlan):
            raise ValueError(
                "ExternalRequestBundle requires a WorkflowSourcePlan; "
                f"got {type(self.plan).__name__}"
            )

    @classmethod
    def make(
        cls,
        plan: WorkflowSourcePlan,
        request_payload: dict[str, Any],
        *,
        priority: int = 0,
        enqueued_at: datetime | None = None,
    ) -> ExternalRequestBundle:
        """Convenience factory with sane defaults."""
        return cls(
            plan=plan,
            request_payload=dict(request_payload),
            enqueued_at=enqueued_at or _utc_now(),
            priority=priority,
        )
