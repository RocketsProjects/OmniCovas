"""
omnicovas.features.squadrons

Phase 7 Squadrons local-only feature logic.
Owns local share-scope write/revoke helpers for the commander-confirmed write flow.
Models live in omnicovas.core.state_manager.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.state_manager import (
    EmergencySecurityNote,
    EmergencySecurityState,
    InviteCode,
    PeerState,
    RoleAuthority,
    SharedNavigationLink,
    SharedOperationLink,
    SquadronLogEntry,
    SquadronProvenance,
    SquadronState,
    StateManager,
    TelemetrySource,
)
from omnicovas.db.models import SquadronCampaignNote

logger = logging.getLogger(__name__)

_LOCAL_CAVEAT = "Commander-entered local context"
_LOCAL_FALLBACK = "Local-only — no outbound"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _commander_provenance() -> SquadronProvenance:
    return SquadronProvenance(
        source="local",
        freshness="fresh",
        truth_class="commander_entered",
        caveat=_LOCAL_CAVEAT,
        fallback_wording=_LOCAL_FALLBACK,
        local_only=True,
        transport_attempted=False,
        timestamp=_now(),
    )


def get_squadron_snapshot(state: StateManager) -> SquadronState:
    """Return the current local-only squadron state snapshot."""
    return state.snapshot.squadron


def _replace_squadron(state: StateManager, new_snap: SquadronState) -> None:
    state.update_field("squadron", new_snap, TelemetrySource.JOURNAL)


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


def create_roster_member(
    state: StateManager,
    commander_name: str,
    role: str | None,
) -> PeerState:
    peer = PeerState(
        commander_name=commander_name or None,
        role=role or None,
        provenance=_commander_provenance(),
    )
    snap = get_squadron_snapshot(state)
    _replace_squadron(
        state,
        SquadronState(
            peers=[*snap.peers, peer],
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=snap.roles,
            shared_operations=snap.shared_operations,
            shared_navigation=snap.shared_navigation,
            emergency_security=snap.emergency_security,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return peer


def revoke_roster_member(state: StateManager, member_id: str) -> bool:
    snap = get_squadron_snapshot(state)
    new_peers = [p for p in snap.peers if p.id != member_id]
    if len(new_peers) == len(snap.peers):
        return False
    _replace_squadron(
        state,
        SquadronState(
            peers=new_peers,
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=snap.roles,
            shared_operations=snap.shared_operations,
            shared_navigation=snap.shared_navigation,
            emergency_security=snap.emergency_security,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


def create_invite_code(
    state: StateManager,
    code: str,
) -> InviteCode:
    invite = InviteCode(
        code=code or None,
        created_at=_now(),
        provenance=_commander_provenance(),
    )
    snap = get_squadron_snapshot(state)
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=[*snap.invites, invite],
            roles=snap.roles,
            shared_operations=snap.shared_operations,
            shared_navigation=snap.shared_navigation,
            emergency_security=snap.emergency_security,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return invite


def revoke_invite_code(state: StateManager, invite_id: str) -> bool:
    snap = get_squadron_snapshot(state)
    new_invites = [i for i in snap.invites if i.id != invite_id]
    if len(new_invites) == len(snap.invites):
        return False
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=new_invites,
            roles=snap.roles,
            shared_operations=snap.shared_operations,
            shared_navigation=snap.shared_navigation,
            emergency_security=snap.emergency_security,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


def create_role(
    state: StateManager,
    role_name: str,
    permissions: list[str],
) -> RoleAuthority:
    role = RoleAuthority(
        role_name=role_name or None,
        permissions=permissions,
        provenance=_commander_provenance(),
    )
    snap = get_squadron_snapshot(state)
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=[*snap.roles, role],
            shared_operations=snap.shared_operations,
            shared_navigation=snap.shared_navigation,
            emergency_security=snap.emergency_security,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return role


def revoke_role(state: StateManager, role_id: str) -> bool:
    snap = get_squadron_snapshot(state)
    new_roles = [r for r in snap.roles if r.id != role_id]
    if len(new_roles) == len(snap.roles):
        return False
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=new_roles,
            shared_operations=snap.shared_operations,
            shared_navigation=snap.shared_navigation,
            emergency_security=snap.emergency_security,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Shared operations
# ---------------------------------------------------------------------------


def create_shared_operation(
    state: StateManager,
    operation_id: str,
    label: str,
) -> SharedOperationLink:
    link = SharedOperationLink(
        operation_id=operation_id or None,
        label=label or None,
        provenance=_commander_provenance(),
    )
    snap = get_squadron_snapshot(state)
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=snap.roles,
            shared_operations=[*snap.shared_operations, link],
            shared_navigation=snap.shared_navigation,
            emergency_security=snap.emergency_security,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return link


def revoke_shared_operation(state: StateManager, link_id: str) -> bool:
    snap = get_squadron_snapshot(state)
    new_ops = [o for o in snap.shared_operations if o.id != link_id]
    if len(new_ops) == len(snap.shared_operations):
        return False
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=snap.roles,
            shared_operations=new_ops,
            shared_navigation=snap.shared_navigation,
            emergency_security=snap.emergency_security,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Shared navigation
# ---------------------------------------------------------------------------


def create_shared_navigation(
    state: StateManager,
    system_name: str,
    objective: str | None,
) -> SharedNavigationLink:
    link = SharedNavigationLink(
        system_name=system_name or None,
        objective=objective or None,
        provenance=_commander_provenance(),
    )
    snap = get_squadron_snapshot(state)
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=snap.roles,
            shared_operations=snap.shared_operations,
            shared_navigation=[*snap.shared_navigation, link],
            emergency_security=snap.emergency_security,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return link


def revoke_shared_navigation(state: StateManager, link_id: str) -> bool:
    snap = get_squadron_snapshot(state)
    new_nav = [n for n in snap.shared_navigation if n.id != link_id]
    if len(new_nav) == len(snap.shared_navigation):
        return False
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=snap.roles,
            shared_operations=snap.shared_operations,
            shared_navigation=new_nav,
            emergency_security=snap.emergency_security,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Emergency / security notes
# ---------------------------------------------------------------------------


def create_emergency_note(
    state: StateManager,
    note_text: str,
) -> EmergencySecurityNote:
    note = EmergencySecurityNote(
        note_text=note_text or None,
        created_at=_now(),
        provenance=_commander_provenance(),
    )
    snap = get_squadron_snapshot(state)
    new_emergency = EmergencySecurityState(
        active=snap.emergency_security.active,
        reason=snap.emergency_security.reason,
        notes=[*snap.emergency_security.notes, note],
        provenance=snap.emergency_security.provenance,
    )
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=snap.roles,
            shared_operations=snap.shared_operations,
            shared_navigation=snap.shared_navigation,
            emergency_security=new_emergency,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return note


def revoke_emergency_note(state: StateManager, note_id: str) -> bool:
    snap = get_squadron_snapshot(state)
    new_notes = [n for n in snap.emergency_security.notes if n.id != note_id]
    if len(new_notes) == len(snap.emergency_security.notes):
        return False
    new_emergency = EmergencySecurityState(
        active=snap.emergency_security.active,
        reason=snap.emergency_security.reason,
        notes=new_notes,
        provenance=snap.emergency_security.provenance,
    )
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=snap.roles,
            shared_operations=snap.shared_operations,
            shared_navigation=snap.shared_navigation,
            emergency_security=new_emergency,
            log=snap.log,
            integrations=snap.integrations,
        ),
    )
    return True


# ---------------------------------------------------------------------------
# Squadron log
# ---------------------------------------------------------------------------


def append_log_entry(
    state: StateManager,
    event_type: str,
    summary: str,
) -> SquadronLogEntry:
    entry = SquadronLogEntry(
        timestamp=_now(),
        event_type=event_type or None,
        summary=summary or None,
        provenance=_commander_provenance(),
    )
    snap = get_squadron_snapshot(state)
    _replace_squadron(
        state,
        SquadronState(
            peers=snap.peers,
            telemetry_sync=snap.telemetry_sync,
            invites=snap.invites,
            roles=snap.roles,
            shared_operations=snap.shared_operations,
            shared_navigation=snap.shared_navigation,
            emergency_security=snap.emergency_security,
            log=[*snap.log, entry],
            integrations=snap.integrations,
        ),
    )
    return entry


# ---------------------------------------------------------------------------
# Phase 9 — Squadron local campaign notes (PB09-05)
# DB-backed local-only notes; bypass SquadronState entirely.
# visibility is always 'local_only'. exported is always False.
# author is always 'local_commander'.
# No FK to CampaignObjectiveRef. No outbound. No shared state.
# ---------------------------------------------------------------------------

_NOTE_VISIBILITY: Final[str] = "local_only"
_NOTE_AUTHOR: Final[str] = "local_commander"
_LINK_UNSET: object = object()  # sentinel: do not modify linked_campaign_id
_NOTE_WORKFLOW_TYPES: Final[frozenset[str]] = frozenset({"bgs", "powerplay"})
_NOTE_MAX_TEXT_LENGTH: Final[int] = 4000


@dataclass(frozen=True)
class SquadronCampaignNoteRecord:
    """Read model for a local Phase 9 squadron campaign note."""

    note_id: str
    workflow_type: str
    linked_campaign_id: str | None
    note_text: str
    visibility: str
    exported: bool
    author: str
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


def _note_record(row: SquadronCampaignNote) -> SquadronCampaignNoteRecord:
    return SquadronCampaignNoteRecord(
        note_id=row.note_id,
        workflow_type=row.workflow_type,
        linked_campaign_id=row.linked_campaign_id,
        note_text=row.note_text,
        visibility=row.visibility,
        exported=row.exported,
        author=row.author,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def _validate_workflow_type(value: str) -> str:
    clean = value.strip().lower()
    if clean not in _NOTE_WORKFLOW_TYPES:
        raise ValueError(
            f"workflow_type must be one of: {sorted(_NOTE_WORKFLOW_TYPES)}"
        )
    return clean


def _validate_note_text(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("note_text is required")
    if len(text) > _NOTE_MAX_TEXT_LENGTH:
        raise ValueError("note_text is too long")
    return text


async def create_campaign_note(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_type: str,
    note_text: str,
    linked_campaign_id: str | None = None,
) -> SquadronCampaignNoteRecord:
    """Create a local-only squadron campaign note. No outbound. No shared state."""
    now = datetime.now(timezone.utc)
    row = SquadronCampaignNote(
        note_id=str(uuid4()),
        workflow_type=_validate_workflow_type(workflow_type),
        linked_campaign_id=linked_campaign_id or None,
        note_text=_validate_note_text(note_text),
        visibility=_NOTE_VISIBILITY,
        exported=False,
        author=_NOTE_AUTHOR,
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    async with session_factory() as db:
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _note_record(row)


async def list_campaign_notes(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_type: str | None = None,
    include_archived: bool = False,
) -> list[SquadronCampaignNoteRecord]:
    """List local squadron campaign notes. Excludes archived by default."""
    async with session_factory() as db:
        stmt = select(SquadronCampaignNote)
        if not include_archived:
            stmt = stmt.where(SquadronCampaignNote.archived_at.is_(None))
        if workflow_type is not None:
            clean = workflow_type.strip().lower()
            stmt = stmt.where(SquadronCampaignNote.workflow_type == clean)
        stmt = stmt.order_by(SquadronCampaignNote.created_at.desc())
        result = await db.execute(stmt)
        rows = result.scalars().all()
    return [_note_record(r) for r in rows]


async def update_campaign_note(
    session_factory: async_sessionmaker[AsyncSession],
    note_id: str,
    *,
    note_text: str | None = None,
    linked_campaign_id: str | None | object = _LINK_UNSET,
) -> SquadronCampaignNoteRecord | None:
    """Update note_text and/or linked_campaign_id for an active note.

    Pass linked_campaign_id=None to explicitly unlink.
    Pass linked_campaign_id=_LINK_UNSET (default) to leave it unchanged.
    """
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        result = await db.execute(
            select(SquadronCampaignNote).where(
                SquadronCampaignNote.note_id == note_id,
                SquadronCampaignNote.archived_at.is_(None),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if note_text is not None:
            row.note_text = _validate_note_text(note_text)
        if linked_campaign_id is not _LINK_UNSET:
            row.linked_campaign_id = (
                linked_campaign_id if isinstance(linked_campaign_id, str) else None
            )
        row.updated_at = now
        await db.commit()
        await db.refresh(row)
    return _note_record(row)


async def archive_campaign_note(
    session_factory: async_sessionmaker[AsyncSession],
    note_id: str,
) -> bool:
    """Soft-archive a local squadron campaign note. Returns True if found."""
    now = datetime.now(timezone.utc)
    async with session_factory() as db:
        result = await db.execute(
            select(SquadronCampaignNote).where(
                SquadronCampaignNote.note_id == note_id,
                SquadronCampaignNote.archived_at.is_(None),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False
        row.archived_at = now
        row.updated_at = now
        await db.commit()
    return True
