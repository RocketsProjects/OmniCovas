"""Operations Commander objective lifecycle — PB14-R1.

Operations gains one real answer to "what is the Commander currently trying to
accomplish?". That answer is Commander-entered, persisted, and never inferred.

What this is not
----------------
The Operations *mode* (Combat, Mining, Trading, ...) answers "what workflow am
I viewing?". *Readiness* answers "am I ready?". *Blockers* answer "what is in
the way?". *Next actions* answer "what should I do next?". None of those is an
objective, and this module never derives one from them: a package name, a mode
name and a recommendation are all rejected as sources of Commander intent.

Law 8 (Sovereignty & Transparency):
    Authored intent is the Commander's own data. It is stored locally in the
    session database, exported on demand, and destroyed on demand — and
    destroying it is a protected action, because nothing in the app can
    reconstruct a sentence the Commander wrote.

Deliberately outside Commander Memory, for the reason
``omnicovas.features.system_notes`` already documents: Memory is derived and a
rebuild deletes and re-derives every record, so authored text parked there
would be erased by a maintenance action the Commander is told is safe.

Lifecycle
---------
``set -> change -> complete -> clear``. The state vocabulary is the Phase 9
campaign vocabulary, reused rather than forked; only ``active``, ``completed``
and ``archived`` arise here. There is no proposal step, and an objective is
never ``blocked`` — a blocker is derived from readiness, and an objective does
not become one.

Identity
--------
``objective_id`` is generated once, when the objective is created, and never
regenerated on read, render, restart or mode change. **Changing the text edits
the same record.** A Commander who rewords their goal has restated one
intention, not finished one and begun another; closing and replacing the record
would manufacture a completion they never declared and would make "completed"
mean two different things in the same log.

Proof ordering
--------------
The persisted mutation commits *before* the Activity Log entry is written, and
the correlation id is written back afterwards. This is deliberately the reverse
of the Phase 9 campaign producer, which logs first: a proof event that outruns
its write would claim a change that did not happen, and R3's truth lock forbids
exactly that. A failed write therefore leaves the prior objective intact and
emits no success event.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Final
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityEntry, ActivityLog
from omnicovas.core.event_types import (
    OPERATIONS_OBJECTIVE_CHANGED,
    OPERATIONS_OBJECTIVE_CLEARED,
    OPERATIONS_OBJECTIVE_COMPLETED,
    OPERATIONS_OBJECTIVE_CREATED,
    OPERATIONS_OBJECTIVE_EXPORTED,
    OPERATIONS_OBJECTIVE_PURGED,
)
from omnicovas.db.models import OperationsObjectiveRef
from omnicovas.features.readiness import OPERATION_PROFILES

logger = logging.getLogger(__name__)

#: An objective is a sentence about intent, not a document. Over-length text is
#: rejected rather than truncated, following the Phase 9 campaign rule: silently
#: storing something other than what the Commander typed is its own dishonesty.
OBJECTIVE_MAX_LENGTH: Final[int] = 280

#: The one source class this module may ever write (PB14-R1 section 7).
SOURCE_COMMANDER_ENTERED: Final[str] = "commander_entered"
TRUTH_COMMANDER_ENTERED: Final[str] = "commander_entered"

STATE_ACTIVE: Final[str] = "active"
STATE_COMPLETED: Final[str] = "completed"
STATE_ARCHIVED: Final[str] = "archived"

#: Subset of `campaign.CAMPAIGN_STATES` reused verbatim. See module docstring.
OBJECTIVE_STATES: Final[frozenset[str]] = frozenset(
    {STATE_ACTIVE, STATE_COMPLETED, STATE_ARCHIVED}
)

#: A mode can hold an objective; "idle" is the absence of a selected operation
#: and therefore has nothing to be trying to accomplish.
OBJECTIVE_OPERATIONS: Final[frozenset[str]] = frozenset(OPERATION_PROFILES) - {"idle"}

OBJECTIVE_CAVEAT: Final[str] = (
    "You entered this. OmniCOVAS did not verify it. It is your stated intent, "
    "not observed telemetry, and it never outranks live local state."
)

#: Returned when the store cannot be read. Unknown is not the same as Not Set,
#: and this text is what keeps the two apart on the surface.
UNAVAILABLE_CAVEAT: Final[str] = (
    "The local objective store did not answer, so whether an objective is set "
    "is unknown. This is not the same as having none."
)


class ObjectiveError(ValueError):
    """Invalid objective input or a transition the lifecycle does not allow."""


class ObjectiveConflict(ObjectiveError):
    """The mode already holds a current objective; changing it is gated."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def normalize_operation(value: Any) -> str:
    """Return a supported operation key, or raise."""
    key = str(value or "").strip().lower()
    if key not in OBJECTIVE_OPERATIONS:
        raise ObjectiveError(
            "operation is not an Operations mode that holds objectives"
        )
    return key


def normalize_text(value: Any) -> str:
    """Return storable objective text, or raise.

    Empty and whitespace-only input are rejected rather than stored: a blank
    objective would render as a set objective that says nothing. Over-length
    input is rejected rather than truncated.
    """
    if not isinstance(value, str):
        raise ObjectiveError("objective text is required")
    text = value.strip()
    if not text:
        raise ObjectiveError("objective text is required")
    if len(text) > OBJECTIVE_MAX_LENGTH:
        raise ObjectiveError(
            f"objective text is too long (maximum {OBJECTIVE_MAX_LENGTH} characters)"
        )
    return text


TARGET_COMMODITY_MAX_LENGTH: Final[int] = 64
TARGET_QUANTITY_MAX: Final[int] = 100_000


def normalize_target_commodity(value: Any) -> str | None:
    """Return a storable target commodity, or None.

    This is a Commander SELECTION, not a parse. Nothing here reads the
    objective sentence: the commodity arrives because the Commander chose it,
    and an empty choice stays empty rather than being guessed at.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ObjectiveError("target commodity must be text")
    token = value.strip()
    if not token:
        return None
    if len(token) > TARGET_COMMODITY_MAX_LENGTH:
        raise ObjectiveError(
            f"target commodity is too long (maximum "
            f"{TARGET_COMMODITY_MAX_LENGTH} characters)"
        )
    return token


def normalize_target_quantity(value: Any) -> int | None:
    """Return a storable target quantity in tonnes, or None."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObjectiveError("target quantity must be a whole number of tonnes")
    if value <= 0:
        raise ObjectiveError("target quantity must be greater than zero")
    if value > TARGET_QUANTITY_MAX:
        raise ObjectiveError(
            f"target quantity is too large (maximum {TARGET_QUANTITY_MAX} t)"
        )
    return int(value)


def _record(row: OperationsObjectiveRef) -> dict[str, Any]:
    """Public shape of one objective. Text is included; this is a local read."""
    return {
        "objective_id": row.objective_id,
        "operation": row.operation,
        "text": row.text,
        "state": row.state,
        "source": row.source,
        "kind": SOURCE_COMMANDER_ENTERED,
        # R6: the Commander's structured selection, kept apart from the
        # sentence so no surface can confuse a choice with a guess.
        "target_commodity": row.target_commodity,
        "target_quantity": row.target_quantity,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
        "completed_at": _iso(row.completed_at),
        "archived_at": _iso(row.archived_at),
        "last_activity_log_event_id": row.last_activity_log_event_id,
    }


class OperationsObjectiveService:
    """Single owner of Commander-entered Operations objectives."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        activity_log: ActivityLog | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._activity_log = activity_log

    # -- proof ------------------------------------------------------------

    def log_proof(
        self, event_type: str, summary: str, payload: dict[str, Any]
    ) -> str | None:
        """Record proof of a completed transition, never the authored text.

        The payload carries identity, mode, transition and length. Repeating
        the Commander's sentence would put private local text into a surface
        built to be read, exported and shared.
        """
        if self._activity_log is None:
            return None
        event_id = str(uuid4())
        self._activity_log.append(
            ActivityEntry(
                event_type=event_type,
                timestamp=_iso(_utcnow()) or "",
                summary=summary,
                payload={**payload, "redacted": True},
                source_chain=[
                    {
                        "source": SOURCE_COMMANDER_ENTERED,
                        "truth_class": TRUTH_COMMANDER_ENTERED,
                        "freshness": "manual",
                        "kind": "operations_objective",
                    }
                ],
                redaction_state="redacted_summary_only",
                is_fact=False,
                linked_entity_refs={"objective_id": payload.get("objective_id")},
                surface_origin="operations",
                correlation_id=event_id,
                event_id=event_id,
                source=SOURCE_COMMANDER_ENTERED,
            )
        )
        return event_id

    async def _write_back_event_id(
        self, objective_id: str, event_id: str | None
    ) -> None:
        """Point the row at its proof. Best effort — the proof already stands."""
        if not event_id:
            return
        try:
            async with self._session_factory() as db:
                row = await db.scalar(
                    select(OperationsObjectiveRef).where(
                        OperationsObjectiveRef.objective_id == objective_id
                    )
                )
                if row is not None:
                    row.last_activity_log_event_id = event_id
                    await db.commit()
        except Exception:  # pragma: no cover - correlation only, never truth
            logger.warning(
                "Could not correlate objective %s with its proof event", objective_id
            )

    # -- reads ------------------------------------------------------------

    async def _current_row(
        self, db: AsyncSession, operation: str
    ) -> OperationsObjectiveRef | None:
        row: OperationsObjectiveRef | None = await db.scalar(
            select(OperationsObjectiveRef).where(
                OperationsObjectiveRef.operation == operation,
                OperationsObjectiveRef.state != STATE_ARCHIVED,
            )
        )
        return row

    async def get_current(self, operation: str) -> dict[str, Any]:
        """Return the mode's current objective, or an honest absence.

        ``available`` is False only when the store could not be read. A read
        that succeeds and finds nothing reports ``objective: None`` with
        ``available: True`` — Not Set. The two are never collapsed.
        """
        key = normalize_operation(operation)
        try:
            async with self._session_factory() as db:
                row = await self._current_row(db, key)
                record = _record(row) if row is not None else None
        except Exception:
            logger.exception("Operations objective store could not be read")
            return {
                "operation": key,
                "available": False,
                "objective": None,
                "caveat": UNAVAILABLE_CAVEAT,
                "source": SOURCE_COMMANDER_ENTERED,
                "truth_class": TRUTH_COMMANDER_ENTERED,
                "nullprovider_safe": True,
            }
        return {
            "operation": key,
            "available": True,
            "objective": record,
            "caveat": OBJECTIVE_CAVEAT,
            "source": SOURCE_COMMANDER_ENTERED,
            "truth_class": TRUTH_COMMANDER_ENTERED,
            "nullprovider_safe": True,
        }

    async def list_current(self) -> dict[str, Any]:
        """Every mode's current objective, keyed by mode."""
        try:
            async with self._session_factory() as db:
                rows = (
                    (
                        await db.execute(
                            select(OperationsObjectiveRef)
                            .where(OperationsObjectiveRef.state != STATE_ARCHIVED)
                            .order_by(OperationsObjectiveRef.updated_at.desc())
                        )
                    )
                    .scalars()
                    .all()
                )
        except Exception:
            logger.exception("Operations objective store could not be read")
            return {
                "available": False,
                "objectives": {},
                "caveat": UNAVAILABLE_CAVEAT,
                "source": SOURCE_COMMANDER_ENTERED,
                "truth_class": TRUTH_COMMANDER_ENTERED,
                "nullprovider_safe": True,
            }
        return {
            "available": True,
            "objectives": {row.operation: _record(row) for row in rows},
            "caveat": OBJECTIVE_CAVEAT,
            "source": SOURCE_COMMANDER_ENTERED,
            "truth_class": TRUTH_COMMANDER_ENTERED,
            "nullprovider_safe": True,
        }

    # -- lifecycle --------------------------------------------------------

    async def set_first(
        self,
        operation: str,
        text: str,
        *,
        target_commodity: Any = None,
        target_quantity: Any = None,
    ) -> dict[str, Any]:
        """Create the mode's first objective. Not gated (PB14-R1 section 4).

        Stating an intention for the first time destroys nothing and can be
        undone by stating another. Replacing one the Commander already holds is
        a different act, and goes through :meth:`change`.
        """
        key = normalize_operation(operation)
        clean = normalize_text(text)
        commodity = normalize_target_commodity(target_commodity)
        quantity = normalize_target_quantity(target_quantity)

        async with self._session_factory() as db:
            existing = await self._current_row(db, key)
            if existing is not None:
                raise ObjectiveConflict(
                    "This operation already holds an objective; changing it "
                    "requires confirmation."
                )
            now = _utcnow()
            row = OperationsObjectiveRef(
                objective_id=str(uuid4()),
                operation=key,
                text=clean,
                state=STATE_ACTIVE,
                source=SOURCE_COMMANDER_ENTERED,
                target_commodity=commodity,
                target_quantity=quantity,
                last_activity_log_event_id=None,
                created_at=now,
                updated_at=now,
                completed_at=None,
                archived_at=None,
            )
            db.add(row)
            await db.commit()
            objective_id = row.objective_id

        event_id = self.log_proof(
            OPERATIONS_OBJECTIVE_CREATED,
            "Commander objective set for this operation",
            {
                "objective_id": objective_id,
                "operation": key,
                "transition": "set",
                "state": STATE_ACTIVE,
                "text_length": len(clean),
                # The selection is a choice from a bounded vocabulary, not
                # authored prose, so naming it in the proof leaks nothing the
                # Commander did not pick from a list.
                "target_commodity": commodity,
                "target_quantity": quantity,
            },
        )
        await self._write_back_event_id(objective_id, event_id)
        return await self.get_current(key)

    async def change(
        self,
        operation: str,
        text: str,
        *,
        target_commodity: Any = None,
        target_quantity: Any = None,
    ) -> dict[str, Any]:
        """Replace the text of the current objective. Gated.

        The record and its identity survive: see the module docstring. An
        unchanged sentence is a no-op and emits nothing.
        """
        key = normalize_operation(operation)
        clean = normalize_text(text)
        commodity = normalize_target_commodity(target_commodity)
        quantity = normalize_target_quantity(target_quantity)

        async with self._session_factory() as db:
            row = await self._current_row(db, key)
            if row is None:
                raise ObjectiveError("This operation holds no objective to change.")
            if row.state != STATE_ACTIVE:
                raise ObjectiveError(
                    "A completed objective cannot be reworded; clear it and set "
                    "a new one."
                )
            unchanged = (
                row.text == clean
                and row.target_commodity == commodity
                and row.target_quantity == quantity
            )
            if unchanged:
                return {**await self.get_current(key), "changed": False}
            objective_id = row.objective_id
            previous_length = len(row.text)
            row.text = clean
            # The selection travels with the change and through the same gate:
            # replacing a stated target is as much a Commander decision as
            # replacing the sentence.
            row.target_commodity = commodity
            row.target_quantity = quantity
            row.updated_at = _utcnow()
            await db.commit()

        event_id = self.log_proof(
            OPERATIONS_OBJECTIVE_CHANGED,
            "Commander objective changed for this operation",
            {
                "objective_id": objective_id,
                "operation": key,
                "transition": "change",
                "state": STATE_ACTIVE,
                "previous_text_length": previous_length,
                "text_length": len(clean),
                "target_commodity": commodity,
                "target_quantity": quantity,
            },
        )
        await self._write_back_event_id(objective_id, event_id)
        return {**await self.get_current(key), "changed": True}

    async def complete(self, operation: str) -> dict[str, Any]:
        """Mark the current objective completed. Gated.

        Completion is declared by the Commander and never inferred from
        telemetry. The objective stays in the slot, visibly completed, until it
        is cleared.
        """
        key = normalize_operation(operation)
        async with self._session_factory() as db:
            row = await self._current_row(db, key)
            if row is None:
                raise ObjectiveError("This operation holds no objective to complete.")
            if row.state == STATE_COMPLETED:
                return {**await self.get_current(key), "changed": False}
            objective_id = row.objective_id
            now = _utcnow()
            row.state = STATE_COMPLETED
            row.completed_at = now
            row.updated_at = now
            await db.commit()

        event_id = self.log_proof(
            OPERATIONS_OBJECTIVE_COMPLETED,
            "Commander objective completed for this operation",
            {
                "objective_id": objective_id,
                "operation": key,
                "transition": "complete",
                "state": STATE_COMPLETED,
            },
        )
        await self._write_back_event_id(objective_id, event_id)
        return {**await self.get_current(key), "changed": True}

    async def clear(self, operation: str) -> dict[str, Any]:
        """Remove the objective from the mode's current slot. Gated.

        The row is archived, not deleted. The Activity Log proof of what the
        Commander did points at an objective id, and that id must keep meaning
        something. Destroying the text entirely is a separate, privacy-scoped
        action: :meth:`purge_all`.
        """
        key = normalize_operation(operation)
        async with self._session_factory() as db:
            row = await self._current_row(db, key)
            if row is None:
                return {**await self.get_current(key), "changed": False}
            objective_id = row.objective_id
            previous_state = row.state
            now = _utcnow()
            row.state = STATE_ARCHIVED
            row.archived_at = now
            row.updated_at = now
            await db.commit()

        event_id = self.log_proof(
            OPERATIONS_OBJECTIVE_CLEARED,
            "Commander objective cleared for this operation",
            {
                "objective_id": objective_id,
                "operation": key,
                "transition": "clear",
                "state": STATE_ARCHIVED,
                "previous_state": previous_state,
            },
        )
        await self._write_back_event_id(objective_id, event_id)
        return {**await self.get_current(key), "changed": True}

    # -- privacy lifecycle ------------------------------------------------

    async def count(self) -> int:
        async with self._session_factory() as db:
            return int(
                await db.scalar(
                    select(func.count()).select_from(OperationsObjectiveRef)
                )
                or 0
            )

    async def export_payload(self) -> dict[str, Any]:
        """Stage every objective, including archived history, for local download."""
        async with self._session_factory() as db:
            rows = (
                (
                    await db.execute(
                        select(OperationsObjectiveRef).order_by(
                            OperationsObjectiveRef.created_at.asc()
                        )
                    )
                )
                .scalars()
                .all()
            )
        payload = {
            "exported_at": _iso(_utcnow()),
            "format": "omnicovas_operations_objectives_v1",
            "posture": "local_private_commander_entered",
            "source": SOURCE_COMMANDER_ENTERED,
            "truth_class": TRUTH_COMMANDER_ENTERED,
            "caveat": OBJECTIVE_CAVEAT,
            "returned": len(rows),
            "objectives": [_record(row) for row in rows],
            "nullprovider_safe": True,
        }
        self.log_proof(
            OPERATIONS_OBJECTIVE_EXPORTED,
            "Commander objectives export staged for local download",
            {
                "objective_id": None,
                "objective_count": len(rows),
                "destination": "local_file",
                "outbound": False,
            },
        )
        return payload

    async def purge_all(self) -> int:
        """Destroy every objective, current and archived. Protected.

        Nothing in OmniCOVAS can reconstruct these: the flight recorder never
        held them.
        """
        async with self._session_factory() as db:
            existing = await db.scalar(
                select(func.count()).select_from(OperationsObjectiveRef)
            )
            await db.execute(delete(OperationsObjectiveRef))
            await db.commit()
        removed = int(existing or 0)
        self.log_proof(
            OPERATIONS_OBJECTIVE_PURGED,
            "All Commander objectives destroyed at Commander request",
            {
                "objective_id": None,
                "deleted_objectives": removed,
                "transition": "purge",
            },
        )
        return removed
