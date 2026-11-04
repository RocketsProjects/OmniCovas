"""Normalized Odyssey Backpack / ShipLocker inventory.

Backpack.json and ShipLocker.json are write-triggered local snapshots with the
same four list containers (Items, Components, Consumables, Data).  This module
turns the raw entries into one record shape without losing what the source
file said:

* every raw entry stays its own record, so rows that differ by ownership,
  mission or category are never merged;
* the storage location (Backpack or ShipLocker) is carried on every record
  and the two snapshots are never summed together, because nothing
  establishes that they were written at the same moment;
* a quantity is the entry's own ``Count``; a missing or invalid ``Count`` is an
  unknown quantity, never zero and never one.

Whether a loaded snapshot is still current is a separate question.  The Local
Data Surface Reference (section 7.7) defines the stale signal as newer Journal
Odyssey inventory events than the file ``timestamp``; OmniCOVAS has no verified
Odyssey inventory event list to evaluate that with, so freshness is reported
as unknown rather than guessed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

JsonDict = dict[str, Any]

STORAGE_BACKPACK = "backpack"
STORAGE_SHIP_LOCKER = "ship_locker"

# Source file container name -> normalized category key.
CATEGORIES: dict[str, str] = {
    "Items": "items",
    "Components": "components",
    "Consumables": "consumables",
    "Data": "data",
}

FRESHNESS_UNKNOWN = "unknown"
FRESHNESS_POLICY = (
    "Currency is not established. Local Data Surface Reference 7.7 treats an "
    "Odyssey snapshot as stale once a newer Journal inventory event exists; "
    "OmniCOVAS has no verified Odyssey inventory event list to check that "
    "against, and no age threshold is assumed."
)

# Source availability.
SOURCE_AVAILABLE = "available"
SOURCE_PARTIAL = "partial"
SOURCE_MISSING = "missing"
SOURCE_MALFORMED = "malformed"
SOURCE_UNREADABLE = "unreadable"

# Observation-time provenance.
TIME_FILE_TIMESTAMP = "file_timestamp"
TIME_MISSING = "missing"
TIME_UNPARSEABLE = "unparseable"
TIME_UNAVAILABLE = "unavailable"

# Category quantity states.
CATEGORY_UNKNOWN = "unknown"
CATEGORY_EMPTY = "explicitly_empty"
CATEGORY_KNOWN = "quantities_known"
CATEGORY_PARTIAL = "partially_unknown"
CATEGORY_QUANTITY_UNKNOWN = "quantity_unknown"


def observation_time(raw_timestamp: Any) -> tuple[str | None, str]:
    """Return the file timestamp only when it is a parseable instant."""
    if not isinstance(raw_timestamp, str) or not raw_timestamp.strip():
        return None, TIME_MISSING
    text = raw_timestamp.strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, TIME_UNPARSEABLE
    return text, TIME_FILE_TIMESTAMP


def entry_quantity(entry: JsonDict) -> int | None:
    """The entry's own non-negative integer ``Count``, else unknown (None)."""
    value = entry.get("Count")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _record(
    entry: JsonDict,
    *,
    category: str,
    index: int,
    storage_location: str,
    source_file: str,
    observed_at: str | None,
) -> JsonDict:
    name = _text(entry.get("Name"))
    quantity = entry_quantity(entry)
    mission_id = _int_or_none(entry.get("MissionID"))
    return {
        "material_id": name.casefold() if name else None,
        "name": name,
        "display_name": _text(entry.get("Name_Localised")) or name,
        "category": category,
        "storage_location": storage_location,
        "quantity": quantity,
        "quantity_state": "observed" if quantity is not None else "unknown",
        "owner_id": _int_or_none(entry.get("OwnerID")),
        "mission_id": mission_id,
        # True only when the entry records a MissionID.  Absence of the field
        # is how ordinary items appear; it is not a separate assertion.
        "mission_bound": mission_id is not None,
        "source_file": source_file,
        "observed_at": observed_at,
        "source_index": index,
    }


def _category_summary(records: list[JsonDict], malformed: int) -> JsonDict:
    entry_count = len(records)
    unknown = sum(1 for record in records if record["quantity"] is None) + malformed
    known = [r["quantity"] for r in records if r["quantity"] is not None]
    if entry_count == 0 and malformed == 0:
        state = CATEGORY_EMPTY
    elif unknown == 0:
        state = CATEGORY_KNOWN
    elif known:
        state = CATEGORY_PARTIAL
    else:
        state = CATEGORY_QUANTITY_UNKNOWN
    return {
        "state": state,
        "entry_count": entry_count,
        "malformed_entry_count": malformed,
        # With no known quantity the sum would read as zero; leave it unknown.
        "known_quantity_total": sum(known)
        if known or state == CATEGORY_EMPTY
        else None,
        "unknown_quantity_entries": unknown,
    }


def _unloaded_summary() -> JsonDict:
    return {
        "state": CATEGORY_UNKNOWN,
        "entry_count": None,
        "malformed_entry_count": None,
        "known_quantity_total": None,
        "unknown_quantity_entries": None,
    }


def normalize_snapshot(
    raw: JsonDict,
    *,
    storage_location: str,
    source_file: str,
    observed_at: str | None,
) -> JsonDict:
    """Normalize one loaded snapshot.  Containers that are absent or not lists
    stay unknown rather than becoming empty."""
    materials: list[JsonDict] = []
    categories: dict[str, JsonDict] = {}
    for container, category in CATEGORIES.items():
        entries = raw.get(container)
        if not isinstance(entries, list):
            categories[category] = _unloaded_summary()
            continue
        records: list[JsonDict] = []
        malformed = 0
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                malformed += 1
                continue
            records.append(
                _record(
                    entry,
                    category=category,
                    index=index,
                    storage_location=storage_location,
                    source_file=source_file,
                    observed_at=observed_at,
                )
            )
        materials.extend(records)
        categories[category] = _category_summary(records, malformed)

    complete = all(
        summary["state"] in {CATEGORY_EMPTY, CATEGORY_KNOWN}
        for summary in categories.values()
    )
    return {
        "materials": materials,
        "categories": categories,
        "malformed_entry_count": sum(
            summary["malformed_entry_count"] or 0 for summary in categories.values()
        ),
        "quantities_complete": complete,
    }


def unavailable_snapshot() -> JsonDict:
    """Normalized fields for a source that could not be read at all."""
    return {
        "materials": None,
        "categories": {
            category: _unloaded_summary() for category in CATEGORIES.values()
        },
        "malformed_entry_count": None,
        "quantities_complete": None,
    }
