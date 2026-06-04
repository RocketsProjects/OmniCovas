"""
omnicovas.api.squadrons

Phase 7 Squadrons local-only API endpoints.

Read endpoints (PB07-03): all ten GET paths.
Write endpoints (PB07-07): local-only create/revoke flows using a scoped
proposal/confirm/cancel queue. No write mutates state before explicit
commander confirmation. No outbound calls. No transport.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import (
    ActivityEntry,
    ActivityLog,
    normalize_phase9_payload,
)
from omnicovas.core.event_types import (
    PHASE_9_SQUADRON_LOCAL_NOTE_ARCHIVED,
    PHASE_9_SQUADRON_LOCAL_NOTE_CREATED,
    PHASE_9_SQUADRON_LOCAL_NOTE_LINKED_TO_CAMPAIGN,
    PHASE_9_SQUADRON_LOCAL_NOTE_UNLINKED_FROM_CAMPAIGN,
    PHASE_9_SQUADRON_LOCAL_NOTE_UPDATED,
    SQUADRON_EMERGENCY_NOTE_CREATED,
    SQUADRON_EMERGENCY_NOTE_REVOKED,
    SQUADRON_INVITE_CREATED,
    SQUADRON_INVITE_REVOKED,
    SQUADRON_LOG_APPENDED,
    SQUADRON_RESERVED_INTENT_BLOCKED,
    SQUADRON_ROLE_CREATED,
    SQUADRON_ROLE_REVOKED,
    SQUADRON_ROSTER_CREATED,
    SQUADRON_ROSTER_REVOKED,
    SQUADRON_SHARED_NAV_CREATED,
    SQUADRON_SHARED_NAV_REVOKED,
    SQUADRON_SHARED_OP_CREATED,
    SQUADRON_SHARED_OP_REVOKED,
)
from omnicovas.features import squadrons as sq_features
from omnicovas.features.squadrons import (
    _LINK_UNSET,
    SquadronCampaignNoteRecord,
    archive_campaign_note,
    create_campaign_note,
    list_campaign_notes,
    update_campaign_note,
)

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/squadrons", tags=["squadrons"])

_state: StateManager | None = None
_activity_log: ActivityLog | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# Scoped proposal queue for commander-confirmed writes.
# Proposals are created on POST/DELETE write requests.
# State is only mutated after a matching confirm request.
_pending_proposals: dict[str, dict[str, Any]] = {}

_RESERVED_INTENT_FEATURES: dict[str, dict[str, str]] = {
    "telemetry_sync": {
        "name": "Telemetry Sync",
        "reason": "Reserved — requires future security doctrine",
    },
    "top_secret_mode": {
        "name": "Top Secret Mode",
        "reason": "Reserved — requires future security doctrine",
    },
    "burn_command": {
        "name": "Burn Command",
        "reason": "Reserved — requires future security doctrine",
    },
    "three_tier_cross_squadron_model": {
        "name": "Three-Tier Cross-Squadron Model",
        "reason": "Reserved — requires future security doctrine",
    },
    "loot_coordination": {
        "name": "Loot Coordination",
        "reason": "Reserved — requires future security doctrine",
    },
    "stun_p2p": {
        "name": "STUN P2P",
        "reason": "Reserved — requires future security doctrine",
    },
    "peer_relay_fallback": {
        "name": "Peer-Relay Fallback",
        "reason": "Reserved — requires future security doctrine",
    },
    "discord_integration": {
        "name": "Discord",
        "reason": "Reserved — requires provider enablement playbook",
    },
    "capi_commander_profile": {
        "name": "CAPI commander profile",
        "reason": "Reserved — requires provider enablement playbook",
    },
    "inara_get_commander_profile": {
        "name": "Inara getCommanderProfile",
        "reason": "Reserved — requires provider enablement playbook",
    },
    "edsm_commander_api": {
        "name": "EDSM commander API",
        "reason": "Reserved — requires provider enablement playbook",
    },
}


def set_state_manager(state: StateManager) -> None:
    """Inject the live StateManager into this router."""
    global _state  # noqa: PLW0603
    _state = state


def set_activity_log(log: ActivityLog | None) -> None:
    """Inject the shared ActivityLog for write-proof emission."""
    global _activity_log  # noqa: PLW0603
    _activity_log = log


def set_session_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    """Inject the async session factory for Phase 9 campaign note persistence."""
    global _session_factory  # noqa: PLW0603
    _session_factory = session_factory


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_proposal_id() -> str:
    return uuid4().hex


def _require_state() -> "StateManager":
    if _state is None:
        raise HTTPException(status_code=500, detail="StateManager not initialised")
    return _state


def _record_activity(event_type: str, record_id: str, label: str) -> None:
    if _activity_log is None:
        return
    _activity_log.append(
        ActivityEntry(
            event_type=event_type,
            timestamp=_utc_now(),
            summary=(
                f"{event_type} | id={record_id} | label={label}"
                " | local_only=True | transport_attempted=False"
            ),
        )
    )


def _record_reserved_intent_activity(
    feature_id: str,
    feature_name: str,
    reason: str,
) -> None:
    if _activity_log is None:
        return
    _activity_log.append(
        ActivityEntry(
            event_type=SQUADRON_RESERVED_INTENT_BLOCKED,
            timestamp=_utc_now(),
            summary=(
                f"{SQUADRON_RESERVED_INTENT_BLOCKED}"
                f" | feature_id={feature_id}"
                f" | feature={feature_name}"
                " | intent_recorded_but_blocked=True"
                " | local_only=True"
                " | transport_attempted=False"
                f" | reason={reason}"
            ),
        )
    )


def _get_proposal(proposal_id: str) -> dict[str, Any]:
    proposal = _pending_proposals.get(proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail=f"Proposal not found or already resolved: {proposal_id}",
        )
    return proposal


# ---------------------------------------------------------------------------
# Read endpoints (PB07-03)
# ---------------------------------------------------------------------------


@router.get("/overview")
async def get_overview() -> dict[str, Any]:
    """Return the local-only squadron overview."""
    if _state is None:
        return {}
    return asdict(sq_features.get_squadron_snapshot(_state))


@router.get("/roster")
async def get_roster() -> dict[str, Any]:
    """Return the local-only squadron roster."""
    if _state is None:
        return {"peers": []}
    snap = sq_features.get_squadron_snapshot(_state)
    return {"peers": [asdict(p) for p in snap.peers]}


@router.get("/invites")
async def get_invites() -> dict[str, Any]:
    """Return the local-only squadron invite codes."""
    if _state is None:
        return {"invites": []}
    snap = sq_features.get_squadron_snapshot(_state)
    return {"invites": [asdict(i) for i in snap.invites]}


@router.get("/telemetry-sync")
async def get_telemetry_sync() -> dict[str, Any]:
    """Return the local-only telemetry sync state."""
    if _state is None:
        return {}
    snap = sq_features.get_squadron_snapshot(_state)
    return asdict(snap.telemetry_sync)


@router.get("/roles")
async def get_roles() -> dict[str, Any]:
    """Return the local-only role authority state."""
    if _state is None:
        return {"roles": []}
    snap = sq_features.get_squadron_snapshot(_state)
    return {"roles": [asdict(r) for r in snap.roles]}


@router.get("/shared-operations")
async def get_shared_operations() -> dict[str, Any]:
    """Return the local-only shared operations links."""
    if _state is None:
        return {"shared_operations": []}
    snap = sq_features.get_squadron_snapshot(_state)
    return {"shared_operations": [asdict(o) for o in snap.shared_operations]}


@router.get("/shared-navigation")
async def get_shared_navigation() -> dict[str, Any]:
    """Return the local-only shared navigation links."""
    if _state is None:
        return {"shared_navigation": []}
    snap = sq_features.get_squadron_snapshot(_state)
    return {"shared_navigation": [asdict(n) for n in snap.shared_navigation]}


@router.get("/emergency-security")
async def get_emergency_security() -> dict[str, Any]:
    """Return the local-only emergency security state."""
    if _state is None:
        return {}
    snap = sq_features.get_squadron_snapshot(_state)
    return asdict(snap.emergency_security)


@router.get("/log")
async def get_log() -> dict[str, Any]:
    """Return the local-only squadron log entries."""
    if _state is None:
        return {"log": []}
    snap = sq_features.get_squadron_snapshot(_state)
    return {"log": [asdict(e) for e in snap.log]}


@router.get("/integrations")
async def get_integrations() -> dict[str, Any]:
    """Return the local-only squadron integration state."""
    if _state is None:
        return {"integrations": []}
    snap = sq_features.get_squadron_snapshot(_state)
    return {"integrations": [asdict(i) for i in snap.integrations]}


@router.post("/reserved-intent")
async def record_reserved_intent(body: dict[str, Any]) -> dict[str, Any]:
    """Record commander intent for a reserved feature without enabling it."""
    feature_id = str(body.get("feature_id") or "").strip()
    feature = _RESERVED_INTENT_FEATURES.get(feature_id)
    if feature is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown reserved feature id: {feature_id or 'missing'}",
        )

    feature_name = feature["name"]
    reason = feature["reason"]
    _record_reserved_intent_activity(feature_id, feature_name, reason)
    return {
        "status": "blocked",
        "intent_recorded_but_blocked": True,
        "feature_id": feature_id,
        "feature": feature_name,
        "local_only": True,
        "transport_attempted": False,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Roster — create / revoke (PB07-07)
# ---------------------------------------------------------------------------


@router.post("/roster")
async def propose_roster_create(body: dict[str, Any]) -> dict[str, Any]:
    """Propose creating a local roster member. Returns a proposal_id."""
    commander_name = str(body.get("commander_name") or "").strip()
    if not commander_name:
        raise HTTPException(status_code=422, detail="commander_name is required")
    role = str(body.get("role") or "").strip() or None
    pid = _new_proposal_id()
    suggestion = f"Add roster member: {commander_name}" + (f" ({role})" if role else "")
    _pending_proposals[pid] = {
        "action": "roster.create",
        "commander_name": commander_name,
        "role": role,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/roster/confirm/{proposal_id}")
async def confirm_roster_create(proposal_id: str) -> dict[str, Any]:
    """Confirm a roster-create proposal and execute the write."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "roster.create":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    peer = sq_features.create_roster_member(
        state,
        commander_name=proposal["commander_name"],
        role=proposal.get("role"),
    )
    del _pending_proposals[proposal_id]
    label = peer.commander_name or "unnamed"
    _record_activity(SQUADRON_ROSTER_CREATED, peer.id, label)
    return {"status": "confirmed", "id": peer.id}


@router.post("/roster/cancel/{proposal_id}")
async def cancel_roster_create(proposal_id: str) -> dict[str, Any]:
    """Cancel a roster-create proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


@router.delete("/roster/{member_id}")
async def propose_roster_revoke(member_id: str) -> dict[str, Any]:
    """Propose revoking a roster member. Returns a proposal_id."""
    pid = _new_proposal_id()
    suggestion = f"Remove roster member: {member_id}"
    _pending_proposals[pid] = {
        "action": "roster.revoke",
        "member_id": member_id,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/roster/revoke-confirm/{proposal_id}")
async def confirm_roster_revoke(proposal_id: str) -> dict[str, Any]:
    """Confirm a roster-revoke proposal and execute the removal."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "roster.revoke":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    member_id = proposal["member_id"]
    removed = sq_features.revoke_roster_member(state, member_id)
    del _pending_proposals[proposal_id]
    if not removed:
        return {"status": "not_found"}
    _record_activity(SQUADRON_ROSTER_REVOKED, member_id, member_id)
    return {"status": "confirmed"}


@router.post("/roster/revoke-cancel/{proposal_id}")
async def cancel_roster_revoke(proposal_id: str) -> dict[str, Any]:
    """Cancel a roster-revoke proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# Invites — create / revoke (PB07-07)
# ---------------------------------------------------------------------------


@router.post("/invites")
async def propose_invite_create(body: dict[str, Any]) -> dict[str, Any]:
    """Propose creating a local invite code label. Returns a proposal_id."""
    code = str(body.get("code") or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="code is required")
    pid = _new_proposal_id()
    suggestion = f"Add local invite code: {code}"
    _pending_proposals[pid] = {
        "action": "invite.create",
        "code": code,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/invites/confirm/{proposal_id}")
async def confirm_invite_create(proposal_id: str) -> dict[str, Any]:
    """Confirm an invite-create proposal and execute the write."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "invite.create":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    invite = sq_features.create_invite_code(state, code=proposal["code"])
    del _pending_proposals[proposal_id]
    _record_activity(SQUADRON_INVITE_CREATED, invite.id, invite.code or "")
    return {"status": "confirmed", "id": invite.id}


@router.post("/invites/cancel/{proposal_id}")
async def cancel_invite_create(proposal_id: str) -> dict[str, Any]:
    """Cancel an invite-create proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


@router.delete("/invites/{invite_id}")
async def propose_invite_revoke(invite_id: str) -> dict[str, Any]:
    """Propose revoking an invite code. Returns a proposal_id."""
    pid = _new_proposal_id()
    suggestion = f"Remove local invite code: {invite_id}"
    _pending_proposals[pid] = {
        "action": "invite.revoke",
        "invite_id": invite_id,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/invites/revoke-confirm/{proposal_id}")
async def confirm_invite_revoke(proposal_id: str) -> dict[str, Any]:
    """Confirm an invite-revoke proposal and execute the removal."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "invite.revoke":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    invite_id = proposal["invite_id"]
    removed = sq_features.revoke_invite_code(state, invite_id)
    del _pending_proposals[proposal_id]
    if not removed:
        return {"status": "not_found"}
    _record_activity(SQUADRON_INVITE_REVOKED, invite_id, invite_id)
    return {"status": "confirmed"}


@router.post("/invites/revoke-cancel/{proposal_id}")
async def cancel_invite_revoke(proposal_id: str) -> dict[str, Any]:
    """Cancel an invite-revoke proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# Roles — create / revoke (PB07-07)
# ---------------------------------------------------------------------------


@router.post("/roles")
async def propose_role_create(body: dict[str, Any]) -> dict[str, Any]:
    """Propose creating a local role assignment. Returns a proposal_id."""
    role_name = str(body.get("role_name") or "").strip()
    if not role_name:
        raise HTTPException(status_code=422, detail="role_name is required")
    raw_perms = body.get("permissions") or []
    permissions = [str(p).strip() for p in raw_perms if str(p).strip()]
    pid = _new_proposal_id()
    suggestion = f"Add role: {role_name}"
    _pending_proposals[pid] = {
        "action": "role.create",
        "role_name": role_name,
        "permissions": permissions,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/roles/confirm/{proposal_id}")
async def confirm_role_create(proposal_id: str) -> dict[str, Any]:
    """Confirm a role-create proposal and execute the write."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "role.create":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    role = sq_features.create_role(
        state,
        role_name=proposal["role_name"],
        permissions=proposal.get("permissions", []),
    )
    del _pending_proposals[proposal_id]
    _record_activity(SQUADRON_ROLE_CREATED, role.id, role.role_name or "")
    return {"status": "confirmed", "id": role.id}


@router.post("/roles/cancel/{proposal_id}")
async def cancel_role_create(proposal_id: str) -> dict[str, Any]:
    """Cancel a role-create proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


@router.delete("/roles/{role_id}")
async def propose_role_revoke(role_id: str) -> dict[str, Any]:
    """Propose revoking a role. Returns a proposal_id."""
    pid = _new_proposal_id()
    suggestion = f"Remove role: {role_id}"
    _pending_proposals[pid] = {
        "action": "role.revoke",
        "role_id": role_id,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/roles/revoke-confirm/{proposal_id}")
async def confirm_role_revoke(proposal_id: str) -> dict[str, Any]:
    """Confirm a role-revoke proposal and execute the removal."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "role.revoke":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    role_id = proposal["role_id"]
    removed = sq_features.revoke_role(state, role_id)
    del _pending_proposals[proposal_id]
    if not removed:
        return {"status": "not_found"}
    _record_activity(SQUADRON_ROLE_REVOKED, role_id, role_id)
    return {"status": "confirmed"}


@router.post("/roles/revoke-cancel/{proposal_id}")
async def cancel_role_revoke(proposal_id: str) -> dict[str, Any]:
    """Cancel a role-revoke proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# Shared operations — create / revoke (PB07-07)
# ---------------------------------------------------------------------------


@router.post("/shared-operations")
async def propose_shared_op_create(body: dict[str, Any]) -> dict[str, Any]:
    """Propose creating a local shared-operation link. Returns a proposal_id."""
    operation_id = str(body.get("operation_id") or "").strip()
    label = str(body.get("label") or "").strip()
    if not operation_id and not label:
        raise HTTPException(status_code=422, detail="operation_id or label is required")
    pid = _new_proposal_id()
    suggestion = f"Add shared operation link: {label or operation_id}"
    _pending_proposals[pid] = {
        "action": "shared_op.create",
        "operation_id": operation_id,
        "label": label,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/shared-operations/confirm/{proposal_id}")
async def confirm_shared_op_create(proposal_id: str) -> dict[str, Any]:
    """Confirm a shared-op-create proposal and execute the write."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "shared_op.create":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    link = sq_features.create_shared_operation(
        state,
        operation_id=proposal["operation_id"],
        label=proposal["label"],
    )
    del _pending_proposals[proposal_id]
    _record_activity(
        SQUADRON_SHARED_OP_CREATED, link.id, link.label or link.operation_id or ""
    )
    return {"status": "confirmed", "id": link.id}


@router.post("/shared-operations/cancel/{proposal_id}")
async def cancel_shared_op_create(proposal_id: str) -> dict[str, Any]:
    """Cancel a shared-op-create proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


@router.delete("/shared-operations/{link_id}")
async def propose_shared_op_revoke(link_id: str) -> dict[str, Any]:
    """Propose revoking a shared-operation link. Returns a proposal_id."""
    pid = _new_proposal_id()
    suggestion = f"Remove shared operation link: {link_id}"
    _pending_proposals[pid] = {
        "action": "shared_op.revoke",
        "link_id": link_id,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/shared-operations/revoke-confirm/{proposal_id}")
async def confirm_shared_op_revoke(proposal_id: str) -> dict[str, Any]:
    """Confirm a shared-op-revoke proposal and execute the removal."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "shared_op.revoke":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    link_id = proposal["link_id"]
    removed = sq_features.revoke_shared_operation(state, link_id)
    del _pending_proposals[proposal_id]
    if not removed:
        return {"status": "not_found"}
    _record_activity(SQUADRON_SHARED_OP_REVOKED, link_id, link_id)
    return {"status": "confirmed"}


@router.post("/shared-operations/revoke-cancel/{proposal_id}")
async def cancel_shared_op_revoke(proposal_id: str) -> dict[str, Any]:
    """Cancel a shared-op-revoke proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# Shared navigation — create / revoke (PB07-07)
# ---------------------------------------------------------------------------


@router.post("/shared-navigation")
async def propose_shared_nav_create(body: dict[str, Any]) -> dict[str, Any]:
    """Propose creating a local shared-navigation link. Returns a proposal_id."""
    system_name = str(body.get("system_name") or "").strip()
    if not system_name:
        raise HTTPException(status_code=422, detail="system_name is required")
    objective = str(body.get("objective") or "").strip() or None
    pid = _new_proposal_id()
    suggestion = f"Add shared navigation: {system_name}"
    _pending_proposals[pid] = {
        "action": "shared_nav.create",
        "system_name": system_name,
        "objective": objective,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/shared-navigation/confirm/{proposal_id}")
async def confirm_shared_nav_create(proposal_id: str) -> dict[str, Any]:
    """Confirm a shared-nav-create proposal and execute the write."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "shared_nav.create":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    link = sq_features.create_shared_navigation(
        state,
        system_name=proposal["system_name"],
        objective=proposal.get("objective"),
    )
    del _pending_proposals[proposal_id]
    _record_activity(SQUADRON_SHARED_NAV_CREATED, link.id, link.system_name or "")
    return {"status": "confirmed", "id": link.id}


@router.post("/shared-navigation/cancel/{proposal_id}")
async def cancel_shared_nav_create(proposal_id: str) -> dict[str, Any]:
    """Cancel a shared-nav-create proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


@router.delete("/shared-navigation/{link_id}")
async def propose_shared_nav_revoke(link_id: str) -> dict[str, Any]:
    """Propose revoking a shared-navigation link. Returns a proposal_id."""
    pid = _new_proposal_id()
    suggestion = f"Remove shared navigation link: {link_id}"
    _pending_proposals[pid] = {
        "action": "shared_nav.revoke",
        "link_id": link_id,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/shared-navigation/revoke-confirm/{proposal_id}")
async def confirm_shared_nav_revoke(proposal_id: str) -> dict[str, Any]:
    """Confirm a shared-nav-revoke proposal and execute the removal."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "shared_nav.revoke":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    link_id = proposal["link_id"]
    removed = sq_features.revoke_shared_navigation(state, link_id)
    del _pending_proposals[proposal_id]
    if not removed:
        return {"status": "not_found"}
    _record_activity(SQUADRON_SHARED_NAV_REVOKED, link_id, link_id)
    return {"status": "confirmed"}


@router.post("/shared-navigation/revoke-cancel/{proposal_id}")
async def cancel_shared_nav_revoke(proposal_id: str) -> dict[str, Any]:
    """Cancel a shared-nav-revoke proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# Emergency / security notes — create / revoke (PB07-07)
# ---------------------------------------------------------------------------


@router.post("/emergency-security/note")
async def propose_emergency_note_create(body: dict[str, Any]) -> dict[str, Any]:
    """Propose creating a local emergency/security note. Returns a proposal_id."""
    note_text = str(body.get("note_text") or "").strip()
    if not note_text:
        raise HTTPException(status_code=422, detail="note_text is required")
    pid = _new_proposal_id()
    suggestion = f"Add local emergency note: {note_text[:60]}"
    _pending_proposals[pid] = {
        "action": "emergency_note.create",
        "note_text": note_text,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/emergency-security/note/confirm/{proposal_id}")
async def confirm_emergency_note_create(proposal_id: str) -> dict[str, Any]:
    """Confirm an emergency-note-create proposal and execute the write."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "emergency_note.create":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    note = sq_features.create_emergency_note(state, note_text=proposal["note_text"])
    del _pending_proposals[proposal_id]
    _record_activity(
        SQUADRON_EMERGENCY_NOTE_CREATED,
        note.id,
        (note.note_text or "")[:60],
    )
    return {"status": "confirmed", "id": note.id}


@router.post("/emergency-security/note/cancel/{proposal_id}")
async def cancel_emergency_note_create(proposal_id: str) -> dict[str, Any]:
    """Cancel an emergency-note-create proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


@router.delete("/emergency-security/note/{note_id}")
async def propose_emergency_note_revoke(note_id: str) -> dict[str, Any]:
    """Propose revoking a local emergency/security note. Returns a proposal_id."""
    pid = _new_proposal_id()
    suggestion = f"Remove local emergency note: {note_id}"
    _pending_proposals[pid] = {
        "action": "emergency_note.revoke",
        "note_id": note_id,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/emergency-security/note/revoke-confirm/{proposal_id}")
async def confirm_emergency_note_revoke(proposal_id: str) -> dict[str, Any]:
    """Confirm an emergency-note-revoke proposal and execute the removal."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "emergency_note.revoke":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    note_id = proposal["note_id"]
    removed = sq_features.revoke_emergency_note(state, note_id)
    del _pending_proposals[proposal_id]
    if not removed:
        return {"status": "not_found"}
    _record_activity(SQUADRON_EMERGENCY_NOTE_REVOKED, note_id, note_id)
    return {"status": "confirmed"}


@router.post("/emergency-security/note/revoke-cancel/{proposal_id}")
async def cancel_emergency_note_revoke(proposal_id: str) -> dict[str, Any]:
    """Cancel an emergency-note-revoke proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# Squadron log — append (PB07-07)
# ---------------------------------------------------------------------------


@router.post("/log")
async def propose_log_append(body: dict[str, Any]) -> dict[str, Any]:
    """Propose appending a local squadron log entry. Returns a proposal_id."""
    event_type = str(body.get("event_type") or "").strip()
    summary = str(body.get("summary") or "").strip()
    if not summary:
        raise HTTPException(status_code=422, detail="summary is required")
    pid = _new_proposal_id()
    suggestion = f"Append squadron log: {summary[:60]}"
    _pending_proposals[pid] = {
        "action": "log.append",
        "event_type": event_type,
        "summary": summary,
        "suggestion_text": suggestion,
    }
    return {"proposal_id": pid, "suggestion_text": suggestion, "status": "pending"}


@router.post("/log/confirm/{proposal_id}")
async def confirm_log_append(proposal_id: str) -> dict[str, Any]:
    """Confirm a log-append proposal and execute the write."""
    proposal = _get_proposal(proposal_id)
    if proposal.get("action") != "log.append":
        raise HTTPException(status_code=400, detail="Proposal action mismatch")
    state = _require_state()
    entry = sq_features.append_log_entry(
        state,
        event_type=proposal["event_type"],
        summary=proposal["summary"],
    )
    del _pending_proposals[proposal_id]
    _record_activity(SQUADRON_LOG_APPENDED, entry.id, entry.summary or "")
    return {"status": "confirmed", "id": entry.id}


@router.post("/log/cancel/{proposal_id}")
async def cancel_log_append(proposal_id: str) -> dict[str, Any]:
    """Cancel a log-append proposal. No state change."""
    _pending_proposals.pop(proposal_id, None)
    return {"status": "cancelled"}


# ---------------------------------------------------------------------------
# Phase 9 — Squadron local campaign notes (PB09-05)
# No proposal/confirm gate: local-only notes are not protected actions.
# Per PB09-05 §12: no shared state exists; soft archive requires no gate.
# ---------------------------------------------------------------------------


def _record_campaign_note_activity(
    event_type: str,
    note_id: str,
    *,
    linked_campaign_id: str | None = None,
    workflow_type: str | None = None,
) -> None:
    """Emit a redacted Activity Log entry for a campaign note event.

    Payload contains note_id, visibility, and redacted=True only.
    Raw note_text is never included. No CMDR names. No external handles.
    """
    if _activity_log is None:
        return
    parts = [
        event_type,
        f"note_id={note_id}",
        "visibility=local_only",
        "exported=False",
        "redacted=True",
    ]
    if workflow_type:
        parts.append(f"workflow_type={workflow_type}")
    if linked_campaign_id:
        parts.append(f"linked_campaign_id={linked_campaign_id}")
    source_chain = [
        {
            "source": "commander_entered",
            "source_type": "local_squadron_campaign_note",
            "truth_class": "commander_entered",
            "freshness": "manual",
            "workflow_type": workflow_type or "squadron",
        }
    ]
    _activity_log.append(
        ActivityEntry(
            event_type=event_type,
            timestamp=_utc_now(),
            summary=" | ".join(parts),
            payload=normalize_phase9_payload(
                {
                    "note_id": note_id,
                    "workflow_type": workflow_type,
                    "linked_campaign_id": linked_campaign_id,
                    "visibility": "local_only",
                    "exported": False,
                }
            ),
            source_chain=source_chain,
            redaction_state="redacted_summary_only",
            is_fact=False,
            surface_origin="squadrons",
            source="commander_entered",
        )
    )


def _note_to_response(note: SquadronCampaignNoteRecord) -> dict[str, Any]:
    """Serialize a SquadronCampaignNoteRecord to a safe API response dict."""
    return {
        "note_id": note.note_id,
        "workflow_type": note.workflow_type,
        "linked_campaign_id": note.linked_campaign_id,
        "note_text": note.note_text,
        "visibility": note.visibility,
        "exported": note.exported,
        "author": note.author,
        "local_only": True,
        "nullprovider_safe": True,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
        "archived_at": note.archived_at.isoformat() if note.archived_at else None,
    }


@router.get("/campaign-notes")
async def list_phase9_campaign_notes(
    workflow_type: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> dict[str, Any]:
    """List local Phase 9 squadron campaign notes. Excludes archived by default."""
    if _session_factory is None:
        return {
            "notes": [],
            "local_only": True,
            "nullprovider_safe": True,
            "source": "Not Loaded",
        }
    notes = await list_campaign_notes(
        _session_factory,
        workflow_type=workflow_type,
        include_archived=include_archived,
    )
    return {
        "notes": [_note_to_response(n) for n in notes],
        "local_only": True,
        "nullprovider_safe": True,
    }


@router.post("/campaign-notes")
async def create_phase9_campaign_note(body: dict[str, Any]) -> dict[str, Any]:
    """Create a local Phase 9 squadron campaign note. No shared state."""
    if _session_factory is None:
        raise HTTPException(
            status_code=503,
            detail="Session factory not initialised — campaign notes unavailable",
        )
    workflow_type = str(body.get("workflow_type") or "").strip()
    note_text = str(body.get("note_text") or "").strip()
    linked_campaign_id = str(body.get("linked_campaign_id") or "").strip() or None

    if not workflow_type:
        raise HTTPException(status_code=422, detail="workflow_type is required")
    if not note_text:
        raise HTTPException(status_code=422, detail="note_text is required")

    try:
        note = await create_campaign_note(
            _session_factory,
            workflow_type=workflow_type,
            note_text=note_text,
            linked_campaign_id=linked_campaign_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _record_campaign_note_activity(
        PHASE_9_SQUADRON_LOCAL_NOTE_CREATED,
        note.note_id,
        workflow_type=note.workflow_type,
    )
    if note.linked_campaign_id:
        _record_campaign_note_activity(
            PHASE_9_SQUADRON_LOCAL_NOTE_LINKED_TO_CAMPAIGN,
            note.note_id,
            linked_campaign_id=note.linked_campaign_id,
            workflow_type=note.workflow_type,
        )
    return _note_to_response(note)


@router.patch("/campaign-notes/{note_id}")
async def update_phase9_campaign_note(
    note_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """Update note_text and/or linked_campaign_id for an active campaign note."""
    if _session_factory is None:
        raise HTTPException(
            status_code=503,
            detail="Session factory not initialised — campaign notes unavailable",
        )
    new_text: str | None = None
    if "note_text" in body:
        new_text = str(body["note_text"] or "").strip() or None

    # Sentinel: _LINK_UNSET means "do not touch"; None means "explicitly unlink"
    new_linked: str | None | object = _LINK_UNSET
    prev_linked: str | None = None
    if "linked_campaign_id" in body:
        raw = body["linked_campaign_id"]
        new_linked = str(raw).strip() if raw else None

    existing = await list_campaign_notes(_session_factory, include_archived=False)
    prev_record = next((n for n in existing if n.note_id == note_id), None)
    if prev_record:
        prev_linked = prev_record.linked_campaign_id

    try:
        note = await update_campaign_note(
            _session_factory,
            note_id,
            note_text=new_text,
            linked_campaign_id=new_linked,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if note is None:
        raise HTTPException(
            status_code=404,
            detail=f"Campaign note not found or already archived: {note_id}",
        )

    _record_campaign_note_activity(
        PHASE_9_SQUADRON_LOCAL_NOTE_UPDATED,
        note.note_id,
        workflow_type=note.workflow_type,
    )
    if new_linked is not _LINK_UNSET:
        new_linked_str = new_linked if isinstance(new_linked, str) else None
        if new_linked_str and not prev_linked:
            _record_campaign_note_activity(
                PHASE_9_SQUADRON_LOCAL_NOTE_LINKED_TO_CAMPAIGN,
                note.note_id,
                linked_campaign_id=note.linked_campaign_id,
                workflow_type=note.workflow_type,
            )
        elif not new_linked_str and prev_linked:
            _record_campaign_note_activity(
                PHASE_9_SQUADRON_LOCAL_NOTE_UNLINKED_FROM_CAMPAIGN,
                note.note_id,
                workflow_type=note.workflow_type,
            )

    return _note_to_response(note)


@router.delete("/campaign-notes/{note_id}")
async def archive_phase9_campaign_note(note_id: str) -> dict[str, Any]:
    """Soft-archive a local Phase 9 squadron campaign note. No hard delete."""
    if _session_factory is None:
        raise HTTPException(
            status_code=503,
            detail="Session factory not initialised — campaign notes unavailable",
        )
    removed = await archive_campaign_note(_session_factory, note_id)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"Campaign note not found or already archived: {note_id}",
        )
    _record_campaign_note_activity(
        PHASE_9_SQUADRON_LOCAL_NOTE_ARCHIVED,
        note_id,
    )
    return {
        "status": "archived",
        "note_id": note_id,
        "local_only": True,
        "nullprovider_safe": True,
    }
