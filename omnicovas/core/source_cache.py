"""Source cache — in-memory freshness-labeled cache for sourced data.

No outbound calls are made here. The cache stores data that callers have
already retrieved; it does not fetch anything itself. Hit/miss counters are
telemetry hooks for Activity Log observers — no HTTP is involved.

FreshnessLabel is imported from provenance.py (provenance is the owning concept).

Authority:
    Backend Blueprint v1.0 — cache/queue/request budget (Section L)
    Source Capability Routing Reference v1 — Section 1, Rule 6 (cache before calling)
    Master Blueprint v5.0 — Law 6 (Performance Priority)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from omnicovas.core.provenance import FreshnessLabel


@dataclass(frozen=True)
class CacheKey:
    """Composite key scoping a cache entry to source, call-type, and entity."""

    source_id: str
    call_type: str
    entity_id: str | None


@dataclass(frozen=True)
class CacheEntry:
    """Immutable snapshot of a cached value with freshness metadata."""

    key: CacheKey
    data: dict[str, Any]
    fetched_at: datetime
    freshness_label: FreshnessLabel
    hit_count: int
    miss_count: int


@dataclass
class _MutableCacheSlot:
    """Internal mutable slot — not part of the public API."""

    data: dict[str, Any]
    fetched_at: datetime
    freshness_label: FreshnessLabel
    hit_count: int = field(default=0)
    miss_count: int = field(default=0)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SourceCache:
    """In-memory cache mapping CacheKey → CacheEntry.

    Callers set entries after a successful source read. The cache never
    fetches data itself. Freshness labels are set by callers; the cache
    does not enforce TTLs (that belongs to the future request dispatcher).

    hit_count and miss_count are incremented by get() for telemetry.
    """

    def __init__(self) -> None:
        self._store: dict[CacheKey, _MutableCacheSlot] = {}

    def get(self, key: CacheKey) -> CacheEntry | None:
        """Return the CacheEntry for key, incrementing hit_count, or None.

        If no entry exists, the caller's miss is not tracked here — callers
        should call record_miss() explicitly when they know a fetch is needed.
        """
        slot = self._store.get(key)
        if slot is None:
            return None
        slot.hit_count += 1
        return CacheEntry(
            key=key,
            data=dict(slot.data),
            fetched_at=slot.fetched_at,
            freshness_label=slot.freshness_label,
            hit_count=slot.hit_count,
            miss_count=slot.miss_count,
        )

    def set(
        self,
        key: CacheKey,
        data: dict[str, Any],
        freshness_label: FreshnessLabel,
        fetched_at: datetime | None = None,
    ) -> CacheEntry:
        """Store or replace data for key.

        Returns a CacheEntry snapshot reflecting the stored state.
        """
        existing = self._store.get(key)
        slot = _MutableCacheSlot(
            data=dict(data),
            fetched_at=fetched_at or _utc_now(),
            freshness_label=freshness_label,
            hit_count=existing.hit_count if existing else 0,
            miss_count=existing.miss_count if existing else 0,
        )
        self._store[key] = slot
        return CacheEntry(
            key=key,
            data=dict(slot.data),
            fetched_at=slot.fetched_at,
            freshness_label=slot.freshness_label,
            hit_count=slot.hit_count,
            miss_count=slot.miss_count,
        )

    def mark_stale(self, key: CacheKey) -> bool:
        """Mark an existing entry STALE without evicting it.

        Returns True if entry was found and marked; False if not present.
        """
        slot = self._store.get(key)
        if slot is None:
            return False
        slot.freshness_label = FreshnessLabel.STALE
        return True

    def invalidate(self, key: CacheKey) -> bool:
        """Remove the entry for key.

        Returns True if an entry was removed; False if key was absent.
        """
        return self._store.pop(key, None) is not None

    def record_miss(self, key: CacheKey) -> None:
        """Increment miss_count for key if present; no-op otherwise."""
        slot = self._store.get(key)
        if slot is not None:
            slot.miss_count += 1

    def stats(self) -> dict[str, int]:
        """Return aggregate hit/miss totals across all entries."""
        total_hits = sum(s.hit_count for s in self._store.values())
        total_misses = sum(s.miss_count for s in self._store.values())
        return {
            "total_hits": total_hits,
            "total_misses": total_misses,
            "entry_count": len(self._store),
        }

    def __len__(self) -> int:
        return len(self._store)
