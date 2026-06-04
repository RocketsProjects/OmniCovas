"""Source queue — in-memory skeleton for external request queuing.

No outbound calls are made here. The queue stores QueueEntry records for
future dispatch; it contains no network code, no background tasks, and no
asyncio workers. drain_for_test() is the only way to consume entries
(test instrumentation only — no live dispatch in Phase 5 foundation).

Authority:
    Backend Blueprint v1.0 — cache/queue/request budget (Section L)
    Source Capability Routing Reference v1 — Section 1, Rules 6–7
    Master Blueprint v5.0 — Law 3 (API Respect), Law 10 (Unified Independent Operation)
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class QueueEntryStatus(str, Enum):
    """Lifecycle state of a queue entry."""

    PENDING = "pending"
    DRAINED = "drained"


@dataclass(frozen=True)
class QueueEntry:
    """Immutable record of an enqueued external request.

    No network dispatch occurs when this entry is created or held.
    dispatch_at is None in the foundation; future playbooks may populate it.
    """

    entry_id: str
    source_id: str
    call_type: str
    workflow_id: str
    enqueued_at: datetime
    status: QueueEntryStatus
    payload: dict[str, Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceQueue:
    """In-memory deque of QueueEntry records.

    enqueue() adds a new PENDING entry.
    inspect() returns a read-only list without consuming entries.
    drain_for_test() removes and returns all entries (test use only).
    No outbound dispatch is performed — this is a skeleton for Phase 5 foundation.
    """

    def __init__(self) -> None:
        self._queue: deque[QueueEntry] = deque()

    def enqueue(
        self,
        *,
        source_id: str,
        call_type: str,
        workflow_id: str,
        payload: dict[str, Any],
        enqueued_at: datetime | None = None,
    ) -> QueueEntry:
        """Add a new PENDING entry and return it.

        entry_id is a new UUID4. No network call is made.
        """
        entry = QueueEntry(
            entry_id=str(uuid.uuid4()),
            source_id=source_id,
            call_type=call_type,
            workflow_id=workflow_id,
            enqueued_at=enqueued_at or _utc_now(),
            status=QueueEntryStatus.PENDING,
            payload=dict(payload),
        )
        self._queue.append(entry)
        return entry

    def inspect(self) -> list[QueueEntry]:
        """Return a snapshot of all pending entries without consuming them."""
        return list(self._queue)

    def drain_for_test(self) -> list[QueueEntry]:
        """Remove and return all entries in FIFO order.

        Intended for test assertions only. Entries are returned with their
        original status; callers may inspect them but should not dispatch.
        """
        drained: list[QueueEntry] = []
        while self._queue:
            drained.append(self._queue.popleft())
        return drained

    def __len__(self) -> int:
        return len(self._queue)
