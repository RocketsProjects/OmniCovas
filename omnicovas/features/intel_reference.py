"""Intel Reference Library payload — Phase 13 slice (PB13-02).

Workflow-scoped curated reference from the local Knowledge Base — never a
wiki clone, never live game data, never provider-backed. Truth class is
knowledge_reference throughout.

Guard (PB13-03): entries flagged ``needs_review`` have their content
withheld entirely — surfacing flagged content on a reference surface would
promote unreviewed material. The entry's topic remains listed with an
explicit withheld notice so the gap is honest rather than invisible.

Read-only over the validated KB loader; no persistence, no providers,
no AI generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omnicovas.knowledge_base import KnowledgeBase, load_knowledge_base

TRUTH_KNOWLEDGE_REFERENCE = "knowledge_reference"

_REFERENCE_CAVEAT = (
    "Curated, workflow-scoped local knowledge reference material. Not live "
    "game data, not provider-backed, and not guaranteed current — verify "
    "against the current game patch. Entries cite their reference source "
    "and the patch they were verified for."
)
_WITHHELD_NOTICE = (
    "Withheld pending knowledge-base review. Flagged entries are not "
    "displayed on reference surfaces."
)

_kb_cache: KnowledgeBase | None = None
_kb_cache_dir: Path | None = None


def _default_kb_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "knowledge_base"


def _get_kb(kb_dir: Path | None) -> KnowledgeBase:
    global _kb_cache, _kb_cache_dir  # noqa: PLW0603
    resolved = kb_dir or _default_kb_dir()
    if _kb_cache is None or _kb_cache_dir != resolved:
        _kb_cache = load_knowledge_base(resolved)
        _kb_cache_dir = resolved
    return _kb_cache


def reset_reference_cache() -> None:
    """Clear the module cache (focused tests only)."""
    global _kb_cache, _kb_cache_dir  # noqa: PLW0603
    _kb_cache = None
    _kb_cache_dir = None


def _category_label(category: str) -> str:
    words = category.replace("_", " ").split()
    return " ".join(
        word.upper() if word.lower() == "bgs" else word.capitalize() for word in words
    )


def reference_library_payload(kb_dir: Path | None = None) -> dict[str, Any]:
    """Compose the workflow-scoped reference library payload."""
    kb = _get_kb(kb_dir)

    by_category: dict[str, list[dict[str, Any]]] = {}
    withheld_count = 0
    for entry in kb.all_entries():
        if entry.needs_review:
            withheld_count += 1
            row: dict[str, Any] = {
                "id": entry.id,
                "topic": entry.topic,
                "category": entry.category,
                "status": "needs_review",
                "content": None,
                "withheld_reason": _WITHHELD_NOTICE,
                "patch_verified": entry.patch_verified,
                "reference_source": None,
                "last_updated": entry.last_updated,
                "confidence": None,
            }
        else:
            row = {
                "id": entry.id,
                "topic": entry.topic,
                "category": entry.category,
                "status": "available",
                "content": entry.content,
                "withheld_reason": None,
                "patch_verified": entry.patch_verified,
                "reference_source": entry.source,
                "last_updated": entry.last_updated,
                "confidence": entry.confidence,
            }
        by_category.setdefault(entry.category, []).append(row)

    categories = [
        {
            "category": category,
            "label": _category_label(category),
            "entry_count": len(rows),
            "entries": sorted(rows, key=lambda row: str(row["topic"]).lower()),
        }
        for category, rows in sorted(by_category.items())
    ]
    total = sum(len(rows) for rows in by_category.values())

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Local knowledge base (curated reference)",
        "truth_class": TRUTH_KNOWLEDGE_REFERENCE,
        "caveat": _REFERENCE_CAVEAT,
        "total_entries": total,
        "withheld_count": withheld_count,
        "categories": categories,
        "nullprovider_safe": True,
    }
