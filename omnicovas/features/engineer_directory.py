"""Bundled, read-only reference directory of ship-engineering engineers.

This is *reference* information, kept apart from the Commander's own Journal
observations: it never changes what ``EngineerProgress`` reported and is never
changed by it.  Only fields that were cross-checked are present; everything
else (specializations, grade ceilings, discovery, invitation and unlock
requirements, referrals) is listed under ``unsupported_fields`` and stays
unknown rather than being inferred.  Nothing is downloaded at runtime.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

SEED_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "engineer_directory_v1.json"
)

# Distribution is fail-closed: the only recognised state keeps the file out of every
# public, preview and release channel (enforced by the repo-channel scripts and the
# build configuration, and tested in tests/test_engineering_directory_distribution.py).
DISTRIBUTION_STATUS = "development_only"
IDENTITY_STATUSES = {"documented", "community_sourced"}
LOCATION_STATUSES = {"verified", "system_only", "unverified"}


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _optional_text(value: Any, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _evidence(value: Any, field: str, source_ids: set[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field} needs at least one source")
    unknown = [item for item in value if item not in source_ids]
    if unknown:
        raise ValueError(f"{field} cites unknown source {unknown[0]}")
    return [str(item) for item in value]


def validate_directory(raw: Any) -> JsonDict:
    """Return the directory in its public shape, or raise ``ValueError``."""
    if not isinstance(raw, dict) or raw.get("schema_version") != "1":
        raise ValueError("Unsupported engineer directory schema")
    sources = raw.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources are required")
    source_rows: list[JsonDict] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"sources[{index}] must be an object")
        source_rows.append(
            {
                key: _text(source.get(key), f"sources[{index}].{key}")
                for key in ("id", "kind", "name", "url", "accessed", "role")
            }
        )
    source_ids = {row["id"] for row in source_rows}
    if len(source_ids) != len(source_rows):
        raise ValueError("Duplicate source id")

    engineers: list[JsonDict] = []
    seen_ids: set[int] = set()
    seen_names: set[str] = set()
    for index, entry in enumerate(raw.get("engineers") or []):
        if not isinstance(entry, dict):
            raise ValueError(f"engineers[{index}] must be an object")
        engineer_id = entry.get("engineer_id")
        if isinstance(engineer_id, bool) or not isinstance(engineer_id, int):
            raise ValueError(f"engineers[{index}].engineer_id must be an integer")
        if engineer_id <= 0 or engineer_id in seen_ids:
            raise ValueError(f"engineers[{index}].engineer_id is not unique")
        name = _text(entry.get("name"), f"engineers[{index}].name")
        if name.casefold() in seen_names:
            raise ValueError(f"Duplicate engineer name: {name}")
        seen_ids.add(engineer_id)
        seen_names.add(name.casefold())
        label = f"engineer {engineer_id}"
        identity = entry.get("identity") or {}
        if identity.get("status") not in IDENTITY_STATUSES:
            raise ValueError(f"{label} identity status is not recognised")
        location = entry.get("location") or {}
        status = location.get("status")
        if status not in LOCATION_STATUSES:
            raise ValueError(f"{label} location status is not recognised")
        system = _optional_text(location.get("system"), f"{label} system")
        base = _optional_text(location.get("base"), f"{label} base")
        # An unverified fact must not carry a value, and a verified base needs a
        # verified system: the directory never offers half a claim as certain.
        if status == "unverified" and (system or base):
            raise ValueError(f"{label} is unverified but names a location")
        if status == "verified" and not (system and base):
            raise ValueError(f"{label} is verified but incomplete")
        if status == "system_only" and (not system or base):
            raise ValueError(f"{label} system_only needs a system and no base")
        engineers.append(
            {
                "engineer_id": engineer_id,
                "name": name,
                "kind": _text(entry.get("kind"), f"{label} kind"),
                "identity": {
                    "status": identity["status"],
                    "evidence": _evidence(
                        identity.get("evidence"), f"{label} identity", source_ids
                    ),
                },
                "location": {
                    "status": status,
                    "system": system,
                    "base": base,
                    "evidence": _evidence(
                        location.get("evidence"), f"{label} location", source_ids
                    ),
                    "notes": [
                        _text(note, f"{label} note")
                        for note in location.get("notes") or []
                    ],
                },
            }
        )
    if not engineers:
        raise ValueError("The directory lists no engineers")
    distribution = raw.get("distribution")
    if not isinstance(distribution, dict) or (
        distribution.get("status") != DISTRIBUTION_STATUS
    ):
        raise ValueError("The directory must declare development_only distribution")
    if any(
        distribution.get(channel) != "excluded"
        for channel in ("public_repository", "preview_repository", "release_build")
    ):
        raise ValueError("Every distribution channel must be excluded")

    unsupported = [
        {
            "field": _text(row.get("field"), "unsupported_fields.field"),
            "reason": _text(row.get("reason"), "unsupported_fields.reason"),
        }
        for row in raw.get("unsupported_fields") or []
        if isinstance(row, dict)
    ]
    return {
        "state": "bundled_verified_subset",
        "directory_id": _text(raw.get("directory_id"), "directory_id"),
        "version": _text(raw.get("version"), "version"),
        "reviewed_at": _text(raw.get("reviewed_at"), "reviewed_at"),
        "scope": _text(raw.get("scope"), "scope"),
        "rights_basis": _text(raw.get("rights_basis"), "rights_basis"),
        "distribution": {
            "status": DISTRIBUTION_STATUS,
            "decision_record": _text(
                distribution.get("decision_record"), "distribution.decision_record"
            ),
        },
        "sources": source_rows,
        "unsupported_fields": unsupported,
        "coverage": {
            "engineers": len(engineers),
            "identity_documented": sum(
                row["identity"]["status"] == "documented" for row in engineers
            ),
            "location_verified": sum(
                row["location"]["status"] == "verified" for row in engineers
            ),
            "location_system_only": sum(
                row["location"]["status"] == "system_only" for row in engineers
            ),
            "location_unverified": sum(
                row["location"]["status"] == "unverified" for row in engineers
            ),
        },
        "engineers": engineers,
    }


@lru_cache(maxsize=1)
def _bundled() -> str:
    directory = validate_directory(json.loads(SEED_PATH.read_text(encoding="utf-8")))
    return json.dumps(directory)


def snapshot() -> JsonDict:
    """The validated bundled directory (a fresh copy; callers may not mutate it)."""
    loaded: JsonDict = json.loads(_bundled())
    return loaded


def safe_snapshot() -> JsonDict:
    """``snapshot`` that degrades to an explicit 'unavailable' instead of failing.

    ``reason`` separates the expected case (the file is not part of this build, as
    in any public, preview or release build) from a defect (the file is present but
    invalid), so the UI never reports a deliberate exclusion as an error.
    """
    reason = "invalid"
    try:
        return snapshot()
    except FileNotFoundError:
        reason = "not_included"
    except (OSError, ValueError):
        pass
    return {
        "state": "unavailable",
        "reason": reason,
        "engineers": [],
        "sources": [],
        "unsupported_fields": [],
        "coverage": {"engineers": 0},
    }
