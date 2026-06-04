"""Phase 9 local-only Operations campaign workflow helpers.

CampaignObjective owns the BGS and Powerplay campaign workflow for PB09-03.
Intel owns facts. Navigation owns circuit routes. Activity Log owns proof.

This module is local-only:
  - No outbound network calls.
  - No provider activation.
  - No AI facts. AI drafts carry is_fact=False and source_chain always.
  - NullProvider mode fully supported.
  - Hard delete not supported: DELETE endpoint = soft archive only.

State lifecycle:
    proposed -> active -> blocked <-> active -> completed -> archived
    proposed -> archived (discard without activating)
    any      -> archived (archive at any time)

PB09-03 authority:
  authority_files/documents/07_phase_guides_playbooks/ai-workflow/Phase-9/
  PB09-03_Operations_Campaign_Workflow_And_Objective_Model.md
PB09-07 owns canonical Activity Log payload taxonomy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, TypedDict, cast
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import (
    ActivityEntry,
    ActivityLog,
    normalize_phase9_payload,
)
from omnicovas.core.event_types import (
    PHASE_9_CAMPAIGN_AI_DRAFT_CANCELED_GATE,
    PHASE_9_CAMPAIGN_AI_DRAFT_CONFIRMED_GATE,
    PHASE_9_CAMPAIGN_AI_DRAFT_EMITTED,
    PHASE_9_CAMPAIGN_AI_DRAFT_REQUESTED_GATE_SHOWN,
    PHASE_9_CAMPAIGN_AI_DRAFT_VALIDATION_FAILED,
    PHASE_9_CAMPAIGN_INTEL_FACT_LINKED,
    PHASE_9_CAMPAIGN_INTEL_FACT_UNLINKED,
    PHASE_9_CAMPAIGN_NAVIGATION_CIRCUIT_LINKED,
    PHASE_9_CAMPAIGN_NAVIGATION_CIRCUIT_UNLINKED,
    PHASE_9_CAMPAIGN_OBJECTIVE_ARCHIVED,
    PHASE_9_CAMPAIGN_OBJECTIVE_BLOCKED,
    PHASE_9_CAMPAIGN_OBJECTIVE_COMPLETED,
    PHASE_9_CAMPAIGN_OBJECTIVE_CREATED,
    PHASE_9_CAMPAIGN_OBJECTIVE_STATE_CHANGED,
    PHASE_9_CAMPAIGN_OBJECTIVE_UPDATED,
)
from omnicovas.db.models import CampaignObjectiveRef

JsonDict = dict[str, Any]
JsonList = list[Any]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAMPAIGN_WORKFLOW_TYPES: Final[frozenset[str]] = frozenset({"bgs", "powerplay"})
CAMPAIGN_STATES: Final[frozenset[str]] = frozenset(
    {"proposed", "active", "blocked", "completed", "archived"}
)

# Maps a current state to the set of states it may transition to.
# "archived" is terminal — empty set means no transitions allowed.
ALLOWED_TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    "proposed": frozenset({"active", "archived"}),
    "active": frozenset({"blocked", "completed", "archived"}),
    "blocked": frozenset({"active", "archived"}),
    "completed": frozenset({"archived"}),
    "archived": frozenset(),
}

DEFAULT_LIMIT: Final[int] = 100
MAX_LIMIT: Final[int] = 500
MAX_TITLE_LENGTH: Final[int] = 128
MAX_NOTE_LENGTH: Final[int] = 4000
MAX_LABEL_LENGTH: Final[int] = 128
MAX_LIST_ITEMS: Final[int] = 50
MAX_ID_LENGTH: Final[int] = 128  # fact/circuit id max length

NULLPROVIDER_DRAFT_MESSAGE: Final[str] = (
    "AI drafting disabled. Use the commander-entered notes and the linked Intel "
    "facts to plan your next step."
)


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class CampaignCreate(TypedDict, total=False):
    """Input for creating a new campaign objective."""

    workflow_type: str  # required
    title: str  # required
    description: str | None
    target_subject: str | None
    target_system: str | None
    state: str  # defaults to "proposed"


class CampaignUpdate(TypedDict, total=False):
    """Allowed partial update fields for a campaign objective."""

    title: str
    description: str | None
    target_subject: str | None
    target_system: str | None
    blockers: list[str]
    next_actions: list[str]


@dataclass(frozen=True)
class AiDraftEntry:
    """One AI draft history entry, always carrying is_fact=False."""

    is_fact: bool  # always False — enforced on creation
    draft_text: str | None  # None for NullProvider
    source_chain: list[JsonDict]
    kb_references: list[JsonDict]  # KB excerpts cited in this draft (PB09-06)
    confidence_label: str | None  # "low" | "medium" | "high" | None
    timestamp: str  # UTC ISO 8601


@dataclass(frozen=True)
class CampaignRecord:
    """Read model for a local campaign objective."""

    campaign_id: str
    workflow_type: str
    title: str
    description: str | None
    target_subject: str | None
    target_system: str | None
    state: str
    blockers: list[str]
    next_actions: list[str]
    linked_intel_facts: list[str]
    linked_navigation_circuits: list[str]
    ai_draft_history: list[JsonDict]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


@dataclass(frozen=True)
class AiDraftResult:
    """Result of an AI draft request."""

    # "emitted" | "nullprovider" | "gate_canceled" | "validation_failed" | "not_found"
    status: str
    draft_text: str | None
    is_fact: bool  # always False
    source_chain: list[JsonDict]
    kb_references: list[JsonDict]
    confidence_label: str | None
    campaign_id: str
    nullprovider_message: str | None = None  # set on nullprovider path (PB09-06)
    validation_error: str | None = None  # set on validation_failed path (PB09-06)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _new_id() -> str:
    return str(uuid4())


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _json_list(text: str | None) -> JsonList:
    if not text:
        return []
    loaded = json.loads(text)
    return loaded if isinstance(loaded, list) else []


def _json_string_list(text: str | None) -> list[str]:
    return [str(item) for item in _json_list(text) if item]


def _json_dict_list(text: str | None) -> list[JsonDict]:
    return [cast(JsonDict, item) for item in _json_list(text) if isinstance(item, dict)]


def _clean_text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
    required: bool = False,
) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    text = value.strip()
    if not text:
        if required:
            raise ValueError(f"{field_name} is required")
        return None
    if len(text) > max_length:
        raise ValueError(f"{field_name} is too long")
    return text


def _required_text(value: str, *, field_name: str, max_length: int) -> str:
    result = _clean_text(
        value, field_name=field_name, max_length=max_length, required=True
    )
    if result is None:
        raise ValueError(f"{field_name} is required")
    return result


def _validate_choice(value: str, choices: frozenset[str], field_name: str) -> str:
    clean = _required_text(value, field_name=field_name, max_length=96)
    if clean not in choices:
        raise ValueError(f"{field_name} must be one of: {sorted(choices)}")
    return clean


def _validate_string_list(
    items: list[str],
    *,
    field_name: str,
    max_item_length: int = MAX_LABEL_LENGTH,
    max_items: int = MAX_LIST_ITEMS,
) -> list[str]:
    if len(items) > max_items:
        raise ValueError(f"{field_name} exceeds maximum item count")
    result: list[str] = []
    for item in items:
        text = _clean_text(str(item), field_name=field_name, max_length=max_item_length)
        if text:
            result.append(text)
    return result


def _validate_limit(limit: int) -> int:
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError("limit is out of range")
    return limit


def _source_chain_commander_entered(kind: str) -> list[JsonDict]:
    return [
        {
            "source": "commander_entered",
            "truth_class": "commander_entered",
            "freshness": "manual",
            "kind": kind,
        }
    ]


def _provider_name(ai_provider: Any) -> str:
    if ai_provider is None:
        return "NullProvider"
    try:
        return str(ai_provider.name())
    except Exception:
        return "Unknown"


def _activity_rejection_reason(reason: str) -> str:
    return reason.split(":", 1)[0]


def _source_chain_disabled() -> list[JsonDict]:
    return [
        {
            "source": "ai_provider",
            "truth_class": "disabled_source",
            "freshness": "not_loaded",
            "kind": "ai_draft",
        }
    ]


def _campaign_record(row: CampaignObjectiveRef) -> CampaignRecord:
    return CampaignRecord(
        campaign_id=row.campaign_id,
        workflow_type=row.workflow_type,
        title=row.title,
        description=row.description,
        target_subject=row.target_subject,
        target_system=row.target_system,
        state=row.state,
        blockers=_json_string_list(row.blockers_json),
        next_actions=_json_string_list(row.next_actions_json),
        linked_intel_facts=_json_string_list(row.linked_intel_facts_json),
        linked_navigation_circuits=_json_string_list(
            row.linked_navigation_circuits_json
        ),
        ai_draft_history=_json_dict_list(row.ai_draft_history_json),
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def _append_activity(
    activity_log: ActivityLog | None,
    *,
    event_type: str,
    summary: str,
    payload: JsonDict | None = None,
    source_chain: list[JsonDict] | None = None,
    linked_entity_refs: JsonDict | None = None,
    is_fact: bool = False,
    source: str = "commander_entered",
) -> str | None:
    """Append a redacted Activity Log entry. No raw private text in payload."""
    if activity_log is None:
        return None
    event_id = _new_id()
    entry_source_chain = source_chain or _source_chain_commander_entered("campaign")
    entry_payload = normalize_phase9_payload(payload or {})
    if event_type.startswith("phase_9.campaign.ai_draft"):
        entry_payload.setdefault("is_fact", False)
        entry_payload.setdefault("source_chain", entry_source_chain)
    activity_log.append(
        ActivityEntry(
            event_type=event_type,
            timestamp=_timestamp(),
            summary=summary,
            payload=entry_payload,
            source_chain=entry_source_chain,
            redaction_state="redacted_summary_only",
            is_fact=is_fact,
            linked_entity_refs=linked_entity_refs or {},
            surface_origin="operations",
            correlation_id=event_id,
            event_id=event_id,
            source=source,
        )
    )
    return event_id


# ---------------------------------------------------------------------------
# CRUD functions
# ---------------------------------------------------------------------------


async def create_campaign(
    session_factory: async_sessionmaker[AsyncSession],
    payload: CampaignCreate,
    *,
    activity_log: ActivityLog | None = None,
) -> CampaignRecord:
    """Create a new local campaign objective. Initial state defaults to 'proposed'."""
    now = _utc_now()
    workflow_type = _validate_choice(
        payload.get("workflow_type", ""),
        CAMPAIGN_WORKFLOW_TYPES,
        "workflow_type",
    )
    title = _required_text(
        payload.get("title", ""),
        field_name="title",
        max_length=MAX_TITLE_LENGTH,
    )
    initial_state = _validate_choice(
        payload.get("state", "proposed"),
        CAMPAIGN_STATES,
        "state",
    )
    row = CampaignObjectiveRef(
        campaign_id=_new_id(),
        workflow_type=workflow_type,
        title=title,
        description=_clean_text(
            payload.get("description"),
            field_name="description",
            max_length=MAX_NOTE_LENGTH,
        ),
        target_subject=_clean_text(
            payload.get("target_subject"),
            field_name="target_subject",
            max_length=MAX_LABEL_LENGTH,
        ),
        target_system=_clean_text(
            payload.get("target_system"),
            field_name="target_system",
            max_length=MAX_LABEL_LENGTH,
        ),
        state=initial_state,
        blockers_json="[]",
        next_actions_json="[]",
        linked_intel_facts_json="[]",
        linked_navigation_circuits_json="[]",
        ai_draft_history_json="[]",
        last_activity_log_event_id=None,
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    event_id = _append_activity(
        activity_log,
        event_type=PHASE_9_CAMPAIGN_OBJECTIVE_CREATED,
        summary="Campaign objective created",
        payload={
            "campaign_id": row.campaign_id,
            "workflow_type": row.workflow_type,
            "state": row.state,
            "title_length": len(row.title),
            "redacted": True,
        },
        linked_entity_refs={"campaign_id": row.campaign_id},
    )
    row.last_activity_log_event_id = event_id
    async with session_factory() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _campaign_record(row)


async def list_campaigns(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_type: str | None = None,
    state: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> list[CampaignRecord]:
    """List campaign objectives with optional filters.

    All results returned when filters are set; caller controls state inclusion.
    """
    validated_limit = _validate_limit(limit)
    async with session_factory() as db:
        query = select(CampaignObjectiveRef).order_by(
            CampaignObjectiveRef.updated_at.desc()
        )
        if workflow_type is not None:
            _validate_choice(workflow_type, CAMPAIGN_WORKFLOW_TYPES, "workflow_type")
            query = query.where(CampaignObjectiveRef.workflow_type == workflow_type)
        if state is not None:
            _validate_choice(state, CAMPAIGN_STATES, "state")
            query = query.where(CampaignObjectiveRef.state == state)
        query = query.limit(validated_limit)
        result = await db.execute(query)
        rows = cast(list[CampaignObjectiveRef], result.scalars().all())
    return [_campaign_record(row) for row in rows]


async def get_campaign(
    session_factory: async_sessionmaker[AsyncSession],
    campaign_id: str,
) -> CampaignRecord | None:
    """Fetch a single campaign objective by id."""
    async with session_factory() as db:
        row = await db.get(CampaignObjectiveRef, campaign_id)
    return _campaign_record(row) if row is not None else None


async def update_campaign(
    session_factory: async_sessionmaker[AsyncSession],
    campaign_id: str,
    changes: CampaignUpdate,
    *,
    activity_log: ActivityLog | None = None,
) -> CampaignRecord | None:
    """Patch allowed fields of a campaign objective."""
    async with session_factory() as db:
        row = await db.get(CampaignObjectiveRef, campaign_id)
        if row is None:
            return None
        if "title" in changes and changes.get("title") is not None:
            row.title = _required_text(
                changes["title"],
                field_name="title",
                max_length=MAX_TITLE_LENGTH,
            )
        if "description" in changes:
            row.description = _clean_text(
                changes.get("description"),
                field_name="description",
                max_length=MAX_NOTE_LENGTH,
            )
        if "target_subject" in changes:
            row.target_subject = _clean_text(
                changes.get("target_subject"),
                field_name="target_subject",
                max_length=MAX_LABEL_LENGTH,
            )
        if "target_system" in changes:
            row.target_system = _clean_text(
                changes.get("target_system"),
                field_name="target_system",
                max_length=MAX_LABEL_LENGTH,
            )
        if "blockers" in changes and changes.get("blockers") is not None:
            validated = _validate_string_list(
                changes["blockers"],
                field_name="blockers",
            )
            row.blockers_json = _json_dump(validated)
        if "next_actions" in changes and changes.get("next_actions") is not None:
            validated_actions = _validate_string_list(
                changes["next_actions"],
                field_name="next_actions",
            )
            row.next_actions_json = _json_dump(validated_actions)
        row.updated_at = _utc_now()
        event_id = _append_activity(
            activity_log,
            event_type=PHASE_9_CAMPAIGN_OBJECTIVE_UPDATED,
            summary="Campaign objective updated",
            payload={
                "campaign_id": row.campaign_id,
                "workflow_type": row.workflow_type,
                "changed_fields": sorted(changes.keys()),
                "title_length": len(row.title),
                "redacted": True,
            },
            linked_entity_refs={"campaign_id": row.campaign_id},
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()
        await db.refresh(row)
    return _campaign_record(row)


async def transition_state(
    session_factory: async_sessionmaker[AsyncSession],
    campaign_id: str,
    new_state: str,
    *,
    activity_log: ActivityLog | None = None,
) -> CampaignRecord | None:
    """Transition campaign state according to allowed transition matrix.

    Raises ValueError for disallowed transitions or if already archived.
    Returns None if campaign_id not found.
    """
    validated_new_state = _validate_choice(new_state, CAMPAIGN_STATES, "state")
    async with session_factory() as db:
        row = await db.get(CampaignObjectiveRef, campaign_id)
        if row is None:
            return None
        current = row.state
        allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
        if validated_new_state not in allowed:
            raise ValueError(
                f"Transition from '{current}' to '{validated_new_state}' is not allowed"
            )
        row.state = validated_new_state
        now = _utc_now()
        row.updated_at = now
        if validated_new_state == "archived":
            row.archived_at = now

        # Select the most specific event type for the transition
        if validated_new_state == "archived":
            event_type = PHASE_9_CAMPAIGN_OBJECTIVE_ARCHIVED
        elif validated_new_state == "completed":
            event_type = PHASE_9_CAMPAIGN_OBJECTIVE_COMPLETED
        elif validated_new_state == "blocked":
            event_type = PHASE_9_CAMPAIGN_OBJECTIVE_BLOCKED
        else:
            event_type = PHASE_9_CAMPAIGN_OBJECTIVE_STATE_CHANGED

        event_id = _append_activity(
            activity_log,
            event_type=event_type,
            summary=f"Campaign objective state changed to {validated_new_state}",
            payload={
                "campaign_id": row.campaign_id,
                "workflow_type": row.workflow_type,
                "previous_state": current,
                "state": row.state,
                "title_length": len(row.title),
                "redacted": True,
            },
            linked_entity_refs={"campaign_id": row.campaign_id},
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()
        await db.refresh(row)
    return _campaign_record(row)


async def link_intel_fact(
    session_factory: async_sessionmaker[AsyncSession],
    campaign_id: str,
    fact_id: str,
    *,
    link: bool = True,
    activity_log: ActivityLog | None = None,
) -> CampaignRecord | None:
    """Attach or detach a linked Intel fact id (weak link, no FK constraint).

    link=True: add fact_id to linked_intel_facts (idempotent).
    link=False: remove fact_id from linked_intel_facts.
    Returns None if campaign_id not found.
    """
    validated_fact_id = _required_text(
        fact_id, field_name="fact_id", max_length=MAX_ID_LENGTH
    )
    async with session_factory() as db:
        row = await db.get(CampaignObjectiveRef, campaign_id)
        if row is None:
            return None
        facts = _json_string_list(row.linked_intel_facts_json)
        if link:
            if validated_fact_id not in facts:
                facts.append(validated_fact_id)
            event_type = PHASE_9_CAMPAIGN_INTEL_FACT_LINKED
            summary = "Intel fact linked to campaign"
        else:
            facts = [f for f in facts if f != validated_fact_id]
            event_type = PHASE_9_CAMPAIGN_INTEL_FACT_UNLINKED
            summary = "Intel fact unlinked from campaign"
        row.linked_intel_facts_json = _json_dump(facts)
        row.updated_at = _utc_now()
        event_id = _append_activity(
            activity_log,
            event_type=event_type,
            summary=summary,
            payload={
                "campaign_id": row.campaign_id,
                "workflow_type": row.workflow_type,
                "fact_id": validated_fact_id,
                "linked_count": len(facts),
            },
            linked_entity_refs={"campaign_id": row.campaign_id},
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()
        await db.refresh(row)
    return _campaign_record(row)


async def link_navigation_circuit(
    session_factory: async_sessionmaker[AsyncSession],
    campaign_id: str,
    circuit_id: str,
    *,
    link: bool = True,
    activity_log: ActivityLog | None = None,
) -> CampaignRecord | None:
    """Attach or detach a linked Navigation circuit id (weak link per PB09-03).

    Navigation circuit model is deferred to PB09-04. These are weak string refs only.
    link=True: add circuit_id (idempotent).
    link=False: remove circuit_id.
    Returns None if campaign_id not found.
    """
    validated_circuit_id = _required_text(
        circuit_id, field_name="circuit_id", max_length=MAX_ID_LENGTH
    )
    async with session_factory() as db:
        row = await db.get(CampaignObjectiveRef, campaign_id)
        if row is None:
            return None
        circuits = _json_string_list(row.linked_navigation_circuits_json)
        if link:
            if validated_circuit_id not in circuits:
                circuits.append(validated_circuit_id)
            event_type = PHASE_9_CAMPAIGN_NAVIGATION_CIRCUIT_LINKED
            summary = "Navigation circuit linked to campaign"
        else:
            circuits = [c for c in circuits if c != validated_circuit_id]
            event_type = PHASE_9_CAMPAIGN_NAVIGATION_CIRCUIT_UNLINKED
            summary = "Navigation circuit unlinked from campaign"
        row.linked_navigation_circuits_json = _json_dump(circuits)
        row.updated_at = _utc_now()
        event_id = _append_activity(
            activity_log,
            event_type=event_type,
            summary=summary,
            payload={
                "campaign_id": row.campaign_id,
                "workflow_type": row.workflow_type,
                "circuit_id": validated_circuit_id,
                "linked_count": len(circuits),
            },
            linked_entity_refs={"campaign_id": row.campaign_id},
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()
        await db.refresh(row)
    return _campaign_record(row)


async def archive_campaign(
    session_factory: async_sessionmaker[AsyncSession],
    campaign_id: str,
    *,
    activity_log: ActivityLog | None = None,
) -> bool:
    """Soft-archive a campaign objective. No hard delete path.

    Sets state='archived', archived_at=now. Row is retained.
    Returns False if campaign_id not found or already archived.
    """
    async with session_factory() as db:
        row = await db.get(CampaignObjectiveRef, campaign_id)
        if row is None:
            return False
        if row.state == "archived":
            return False
        now = _utc_now()
        row.state = "archived"
        row.archived_at = now
        row.updated_at = now
        event_id = _append_activity(
            activity_log,
            event_type=PHASE_9_CAMPAIGN_OBJECTIVE_ARCHIVED,
            summary="Campaign objective archived",
            payload={
                "campaign_id": row.campaign_id,
                "workflow_type": row.workflow_type,
                "state": "archived",
                "title_length": len(row.title),
                "redacted": True,
            },
            linked_entity_refs={"campaign_id": row.campaign_id},
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()
    return True


async def request_ai_draft(
    session_factory: async_sessionmaker[AsyncSession],
    campaign_id: str,
    *,
    ai_provider: Any,
    gate: Any,
    activity_log: ActivityLog | None = None,
    kb_dir: Path | None = None,
) -> AiDraftResult:
    """Request an AI campaign draft.

    AI draft contract (PB09-03 §7 + PB09-06 hardening):
    - is_fact=False always (enforced by OmniCOVAS, never trusted from AI output).
    - source_chain always present.
    - KB excerpts loaded locally; needs_review disclosed.
    - NullProvider returns deterministic message + KB refs.
    - Confirmation Gate required before AIProvider invocation.
    - Output validated before persistence (PB09-06).
    - No invented merit values.
    - No invented BGS tick times.
    - No AI facts.
    - No outbound provider calls in Phase 9 default.

    ai_provider: AIProvider instance (may be NullProvider / None).
    gate: ConfirmationGate instance.
    kb_dir: override KB directory for testing; None uses default path.
    """
    from omnicovas.core.confirmation_gate import ActionType
    from omnicovas.features import campaign_drafter  # noqa: PLC0415

    async with session_factory() as db:
        row = await db.get(CampaignObjectiveRef, campaign_id)
        if row is None:
            return AiDraftResult(
                status="not_found",
                draft_text=None,
                is_fact=False,
                source_chain=[],
                kb_references=[],
                confidence_label=None,
                campaign_id=campaign_id,
            )

        linked_facts = _json_string_list(row.linked_intel_facts_json)
        source_chain_for_gate = [
            {
                "fact_id": fid,
                "truth_class": "local_event_history",
                "freshness": "last_known",
            }
            for fid in linked_facts
        ]

        # Load KB excerpts before gate so counts are available for gate display.
        kb_excerpts = campaign_drafter.load_campaign_kb_excerpts(
            row.workflow_type, kb_dir=kb_dir
        )
        needs_review_count = sum(1 for e in kb_excerpts if e["needs_review"])
        ai_provider_name = _provider_name(ai_provider)

        action_type = (
            ActionType.BGS_SUGGESTION
            if row.workflow_type == "bgs"
            else ActionType.POWERPLAY_SUGGESTION
        )
        gate_details: dict[str, Any] = {
            "campaign_id": campaign_id,
            "workflow_type": row.workflow_type,
            "title_length": len(row.title),
            "linked_intel_fact_count": len(linked_facts),
            "linked_navigation_circuit_count": len(
                _json_string_list(row.linked_navigation_circuits_json)
            ),
            "kb_excerpt_count": len(kb_excerpts),
            "needs_review_count": needs_review_count,
            "ai_provider_name": ai_provider_name,
        }

        _append_activity(
            activity_log,
            event_type=PHASE_9_CAMPAIGN_AI_DRAFT_REQUESTED_GATE_SHOWN,
            summary="AI campaign draft gate shown",
            payload={
                "campaign_id": campaign_id,
                "workflow_type": row.workflow_type,
                "is_fact": False,
                "linked_intel_fact_count": len(linked_facts),
                "linked_navigation_circuit_count": len(
                    _json_string_list(row.linked_navigation_circuits_json)
                ),
                "kb_excerpt_count": len(kb_excerpts),
                "needs_review_count": needs_review_count,
                "ai_provider_name": ai_provider_name,
            },
            source_chain=source_chain_for_gate,
            linked_entity_refs={"campaign_id": campaign_id},
            is_fact=False,
        )

        approved = await gate.require_confirmation(
            action_type=action_type,
            summary=(
                f"AI campaign draft request for {row.workflow_type} objective "
                f"(title length: {len(row.title)} chars)"
            ),
            details=gate_details,
        )

        if not approved:
            _append_activity(
                activity_log,
                event_type=PHASE_9_CAMPAIGN_AI_DRAFT_CANCELED_GATE,
                summary="AI campaign draft canceled at gate",
                payload={
                    "campaign_id": campaign_id,
                    "workflow_type": row.workflow_type,
                    "state": row.state,
                    "is_fact": False,
                    "ai_provider_name": ai_provider_name,
                },
                source_chain=_source_chain_disabled(),
                linked_entity_refs={"campaign_id": campaign_id},
                source="commander_entered",
            )
            return AiDraftResult(
                status="gate_canceled",
                draft_text=None,
                is_fact=False,
                source_chain=[],
                kb_references=[],
                confidence_label=None,
                campaign_id=campaign_id,
            )

        _append_activity(
            activity_log,
            event_type=PHASE_9_CAMPAIGN_AI_DRAFT_CONFIRMED_GATE,
            summary="AI campaign draft gate confirmed",
            payload={
                "campaign_id": campaign_id,
                "workflow_type": row.workflow_type,
                "is_fact": False,
                "linked_intel_fact_count": len(linked_facts),
                "kb_excerpt_count": len(kb_excerpts),
                "needs_review_count": needs_review_count,
                "ai_provider_name": ai_provider_name,
            },
            source_chain=source_chain_for_gate,
            linked_entity_refs={"campaign_id": campaign_id},
            is_fact=False,
        )

        # Try AI provider (NullProvider or None returns None)
        ai_result: str | None = None
        if ai_provider is not None:
            try:
                is_available = await ai_provider.is_available()
            except Exception:
                is_available = False
            if is_available:
                prompt = campaign_drafter.build_prompt(
                    workflow_type=row.workflow_type,
                    target_subject=row.target_subject,
                    target_system=row.target_system,
                    linked_fact_ids=linked_facts,
                    blocker_count=len(_json_string_list(row.blockers_json)),
                    next_action_count=len(_json_string_list(row.next_actions_json)),
                    kb_excerpts=kb_excerpts,
                )
                try:
                    ai_result = await ai_provider.query(
                        prompt,
                        context={
                            "campaign_id": campaign_id,
                            "workflow_type": row.workflow_type,
                            "linked_intel_fact_count": len(linked_facts),
                        },
                    )
                except Exception:
                    ai_result = None

        if ai_result is None:
            # NullProvider path: deterministic message + KB refs disclosed.
            null_resp = campaign_drafter.build_nullprovider_response(
                linked_facts, kb_excerpts
            )
            return AiDraftResult(
                status="nullprovider",
                draft_text=None,
                is_fact=False,
                source_chain=null_resp["source_chain"],
                kb_references=null_resp["kb_references"],
                confidence_label=None,
                campaign_id=campaign_id,
                nullprovider_message=NULLPROVIDER_DRAFT_MESSAGE,
            )

        # Validate AI output before persisting (PB09-06 §5.3).
        allowed_fact_ids = frozenset(linked_facts)
        allowed_kb_ids = frozenset((e["kb_file"], e["entry_id"]) for e in kb_excerpts)
        has_pp_needs_review = any(
            e["needs_review"]
            for e in kb_excerpts
            if e["kb_file"].startswith("powerplay")
        )
        validation_err = campaign_drafter.validate_draft_output(
            ai_result,
            allowed_fact_ids=allowed_fact_ids,
            allowed_kb_ids=allowed_kb_ids,
            has_powerplay_needs_review=has_pp_needs_review,
        )

        if validation_err is not None:
            # Validation failure: no persistence; minimal redacted Activity Log entry.
            _append_activity(
                activity_log,
                event_type=PHASE_9_CAMPAIGN_AI_DRAFT_VALIDATION_FAILED,
                summary="AI campaign draft rejected by validation",
                payload={
                    "campaign_id": campaign_id,
                    "workflow_type": row.workflow_type,
                    "is_fact": False,
                    "rejection_reason": _activity_rejection_reason(
                        validation_err.reason
                    ),
                    "source_count": len(linked_facts),
                    "kb_reference_count": len(kb_excerpts),
                    "needs_review_count": needs_review_count,
                    "ai_provider_name": ai_provider_name,
                    "redacted": True,
                },
                source_chain=_source_chain_disabled(),
                linked_entity_refs={"campaign_id": campaign_id},
                source="commander_entered",
            )
            return AiDraftResult(
                status="validation_failed",
                draft_text=None,
                is_fact=False,
                source_chain=source_chain_for_gate,
                kb_references=[],
                confidence_label=None,
                campaign_id=campaign_id,
                validation_error=validation_err.reason,
            )

        # Valid AI response: extract structured fields where available.
        try:
            parsed_output: dict[str, Any] = json.loads(ai_result)
        except (json.JSONDecodeError, ValueError):
            parsed_output = {}

        kb_refs_for_history: list[JsonDict] = [
            dict(r)
            for r in parsed_output.get("kb_references", [])
            if isinstance(r, dict)
        ]
        raw_confidence = parsed_output.get("confidence_label", "low")
        confidence: str = (
            raw_confidence if raw_confidence in ("low", "medium", "high") else "low"
        )
        draft_text_for_history: str = parsed_output.get("draft_text") or ai_result

        entry = AiDraftEntry(
            is_fact=False,
            draft_text=draft_text_for_history,
            source_chain=source_chain_for_gate,
            kb_references=kb_refs_for_history,
            confidence_label=confidence,
            timestamp=_timestamp(),
        )
        history = _json_dict_list(row.ai_draft_history_json)
        history.append(
            {
                "is_fact": entry.is_fact,
                "draft_text": entry.draft_text,
                "source_chain": entry.source_chain,
                "kb_references": entry.kb_references,
                "confidence_label": entry.confidence_label,
                "timestamp": entry.timestamp,
            }
        )
        row.ai_draft_history_json = _json_dump(history)
        row.updated_at = _utc_now()
        event_id = _append_activity(
            activity_log,
            event_type=PHASE_9_CAMPAIGN_AI_DRAFT_EMITTED,
            summary="AI campaign draft emitted",
            payload={
                "campaign_id": campaign_id,
                "workflow_type": row.workflow_type,
                "is_fact": False,
                "confidence_label": entry.confidence_label,
                "linked_intel_fact_count": len(linked_facts),
                "kb_reference_count": len(kb_refs_for_history),
                "needs_review_count": needs_review_count,
                "ai_provider_name": ai_provider_name,
                "redacted": True,
            },
            source_chain=source_chain_for_gate,
            linked_entity_refs={"campaign_id": campaign_id},
            is_fact=False,
        )
        row.last_activity_log_event_id = event_id or row.last_activity_log_event_id
        await db.commit()

    return AiDraftResult(
        status="emitted",
        draft_text=draft_text_for_history,
        is_fact=False,
        source_chain=source_chain_for_gate,
        kb_references=kb_refs_for_history,
        confidence_label=entry.confidence_label,
        campaign_id=campaign_id,
    )
