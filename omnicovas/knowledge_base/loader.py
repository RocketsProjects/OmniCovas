"""
omnicovas.knowledge_base.loader

Loads, validates, and queries Knowledge Base JSON files.

Every entry must conform to the KB schema:
    - id: unique identifier within its category
    - topic: short human-readable topic name
    - content: the actual knowledge text (what the AI may cite)
    - patch_verified: ED patch version this was verified against
    - source: where the information came from
    - last_updated: ISO date string
    - confidence: 'high' | 'medium' | 'low'
    - needs_review: boolean

Law 5 (Zero Hallucination):
    The KB is the AI's only source of truth. If an entry is missing,
    the AI must respond "I don't have verified data on that."

Principle 6 (KB Stewardship):
    This loader enforces schema at load time. Tests run it in CI
    so schema violations block merges.

Principle 8 (Defensive Update):
    When a new ED patch is detected, entries with older patch_verified
    values are flagged for re-verification.

See: Phase 1 Development Guide Week 4, Part B
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Required fields on every KB entry
REQUIRED_FIELDS = {
    "id",
    "topic",
    "content",
    "patch_verified",
    "source",
    "last_updated",
    "confidence",
    "needs_review",
}

# Valid values for the 'confidence' field
VALID_CONFIDENCE_LEVELS = {"high", "medium", "low"}


class KBSchemaError(ValueError):
    """Raised when a KB entry or metadata file violates the schema."""

    pass


@dataclass(frozen=True)
class KBEntry:
    """
    A single Knowledge Base entry.

    Immutable — once loaded, entries are never mutated.
    Updates require editing the source JSON and reloading.
    """

    id: str
    topic: str
    content: str
    patch_verified: str
    source: str
    last_updated: str
    confidence: str
    needs_review: bool
    category: str  # Injected from the file that contained this entry


class KnowledgeBase:
    """
    In-memory collection of validated KB entries, keyed by category and id.

    Usage:
        kb = load_knowledge_base(Path("omnicovas/knowledge_base"))
        entry = kb.get("combat_mechanics", "hull_integrity_basics")
        if entry is not None:
            grounded_prompt = f"Using this knowledge: {entry.content}\\n\\nQ: ..."
    """

    def __init__(
        self,
        entries: dict[str, dict[str, KBEntry]],
        metadata: dict[str, Any],
    ) -> None:
        self._entries = entries
        self._metadata = metadata

    def get(self, category: str, entry_id: str) -> KBEntry | None:
        """
        Retrieve a specific entry by category and id.

        Returns:
            The KBEntry if present, else None. Law 5: callers must handle None
            as "I don't have verified data on that."
        """
        category_entries = self._entries.get(category)
        if category_entries is None:
            return None
        return category_entries.get(entry_id)

    def all_entries(self) -> list[KBEntry]:
        """Return a flat list of every entry across all categories."""
        return [
            entry
            for category_entries in self._entries.values()
            for entry in category_entries.values()
        ]

    def entries_needing_review(self) -> list[KBEntry]:
        """Return all entries flagged with needs_review=True."""
        return [e for e in self.all_entries() if e.needs_review]

    @property
    def metadata(self) -> dict[str, Any]:
        """Return the _metadata.json contents."""
        return dict(self._metadata)

    @property
    def total_entries(self) -> int:
        """Total count of entries across all categories."""
        return len(self.all_entries())


def _validate_entry(raw: dict[str, Any], category: str, source_file: str) -> KBEntry:
    """
    Validate one raw entry dict and convert it to a KBEntry.

    Raises:
        KBSchemaError if any required field is missing or invalid.
    """
    missing = REQUIRED_FIELDS - set(raw.keys())
    if missing:
        raise KBSchemaError(
            f"{source_file} entry missing required fields: "
            f"{sorted(missing)}. Got keys: {sorted(raw.keys())}"
        )

    confidence = raw["confidence"]
    if confidence not in VALID_CONFIDENCE_LEVELS:
        raise KBSchemaError(
            f"{source_file} entry '{raw.get('id', '?')}' has invalid "
            f"confidence '{confidence}'. Must be one of "
            f"{sorted(VALID_CONFIDENCE_LEVELS)}."
        )

    if not isinstance(raw["needs_review"], bool):
        raise KBSchemaError(
            f"{source_file} entry '{raw.get('id', '?')}' has non-boolean "
            f"needs_review: {raw['needs_review']!r}"
        )

    for string_field in (
        "id",
        "topic",
        "content",
        "patch_verified",
        "source",
        "last_updated",
    ):
        if not isinstance(raw[string_field], str) or not raw[string_field]:
            raise KBSchemaError(
                f"{source_file} entry '{raw.get('id', '?')}' has invalid "
                f"{string_field}: must be non-empty string"
            )

    return KBEntry(
        id=raw["id"],
        topic=raw["topic"],
        content=raw["content"],
        patch_verified=raw["patch_verified"],
        source=raw["source"],
        last_updated=raw["last_updated"],
        confidence=confidence,
        needs_review=raw["needs_review"],
        category=category,
    )


def _load_category_file(path: Path) -> tuple[str, dict[str, KBEntry]]:
    """
    Load a single category JSON file and validate its entries.

    Returns:
        Tuple of (category_name, dict of entry_id -> KBEntry)

    Raises:
        KBSchemaError on any violation.
    """
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise KBSchemaError(f"{path.name} is not valid JSON: {e}") from e

    if not isinstance(data, dict):
        raise KBSchemaError(f"{path.name} root must be a JSON object")

    category = data.get("category")
    if not isinstance(category, str) or not category:
        raise KBSchemaError(f"{path.name} must have a non-empty 'category' field")

    raw_entries = data.get("entries", [])
    if not isinstance(raw_entries, list):
        raise KBSchemaError(f"{path.name} 'entries' must be a list")

    validated: dict[str, KBEntry] = {}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise KBSchemaError(f"{path.name} contains a non-object entry: {raw!r}")
        entry = _validate_entry(raw, category=category, source_file=path.name)
        if entry.id in validated:
            raise KBSchemaError(f"{path.name} contains duplicate entry id '{entry.id}'")
        validated[entry.id] = entry

    return category, validated


def load_knowledge_base(kb_dir: Path) -> KnowledgeBase:
    """
    Load and validate every KB category file in kb_dir.

    Args:
        kb_dir: Path to the knowledge_base directory

    Returns:
        Validated KnowledgeBase instance.

    Raises:
        KBSchemaError if any file fails validation.
    """
    if not kb_dir.exists():
        raise KBSchemaError(f"KB directory not found: {kb_dir}")

    # Load metadata
    metadata_path = kb_dir / "_metadata.json"
    if not metadata_path.exists():
        raise KBSchemaError(f"KB metadata missing: {metadata_path}")

    try:
        with open(metadata_path, encoding="utf-8") as f:
            metadata = json.load(f)
    except json.JSONDecodeError as e:
        raise KBSchemaError(f"_metadata.json is not valid JSON: {e}") from e

    if not isinstance(metadata, dict):
        raise KBSchemaError("_metadata.json root must be a JSON object")

    # Load every *.json except _metadata.json
    entries: dict[str, dict[str, KBEntry]] = {}
    category_files = sorted(
        p for p in kb_dir.glob("*.json") if p.name != "_metadata.json"
    )

    for path in category_files:
        category, category_entries = _load_category_file(path)
        if category in entries:
            raise KBSchemaError(
                f"Duplicate category '{category}' across files: "
                f"already loaded earlier, found again in {path.name}"
            )
        entries[category] = category_entries
        logger.debug(
            "Loaded %d entries from %s (%s)",
            len(category_entries),
            path.name,
            category,
        )

    total = sum(len(e) for e in entries.values())
    logger.info(
        "Knowledge Base loaded: %d categories, %d total entries",
        len(entries),
        total,
    )

    return KnowledgeBase(entries=entries, metadata=metadata)
