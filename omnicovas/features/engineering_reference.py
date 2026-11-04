"""Commander-initiated, private reference ingestion; no vendored game dataset.

Only the pinned public file is read. Remote JavaScript is never executed.
All non-hidden module families in the pinned source use the canonical catalogue
and fitting rules. Missing source mechanics remain explicit unknowns.
"""

from __future__ import annotations

import asyncio
import hashlib
import urllib.request
from datetime import datetime, timezone
from typing import Any

from omnicovas.features import engineering_catalog

REVISION = "ea787cf805f2c38f72c8d5f168fa1063341ebd9a"
SOURCE_URL = f"https://raw.githubusercontent.com/taleden/EDSY/{REVISION}/eddb.js"
SOURCE_SHA256 = "071f3c63bab630b0db33e7d77061c1dcd7c0d06426c507ab52bf87e9a1c99da2"
CATALOG_ID = "edsy-local-outfitting"
VERSION = "2026-10-20-ea787cf8-v4"
MAX_BYTES = 1_000_000
NOTICE = (
    "Private non-commercial reference use only. EDSY by taleden: CC BY-NC 4.0 "
    "for its code; Elite Dangerous game data remains Frontier Developments plc's "
    "property. EDSY cites Frontier's media-usage permission. This is not a grant "
    "to redistribute the game dataset or a claim of Frontier endorsement."
)


def decode_reference(content: bytes) -> dict[str, Any]:
    """Convert a digest-verified source to the existing canonical pack schema."""
    if len(content) > MAX_BYTES or hashlib.sha256(content).hexdigest() != SOURCE_SHA256:
        raise ValueError("Reference digest mismatch; existing catalogue was preserved.")
    from omnicovas.features.outfitting_reference import convert

    data = convert(content.decode("utf-8-sig"))
    return engineering_catalog.normalize_catalog(
        {
            "schema_version": "1",
            "catalog_id": CATALOG_ID,
            "version": VERSION,
            "title": "Local outfitting reference - EDSY 2026-10-20",
            "provenance": {
                "source_name": "EDSY / taleden; Frontier game data",
                "source_url": SOURCE_URL,
                "license": "CC BY-NC 4.0 code; Frontier retains game data rights",
                "rights_basis": (
                    "Commander-requested private non-commercial local ingestion; "
                    "no dataset bundled. Redistribution permission remains unverified."
                ),
                "acquired_at": datetime.now(timezone.utc).isoformat(),
                "verification_notes": (
                    f"Source SHA-256 {SOURCE_SHA256}. All source module families; "
                    "explicit slot, hull, module-count and operating constraints. "
                    + NOTICE
                ),
            },
            **data,
        }
    )


async def download_reference() -> dict[str, Any]:
    """One bounded public request, off the event loop, with no commander payload."""

    def read() -> bytes:
        request = urllib.request.Request(
            SOURCE_URL, headers={"User-Agent": "OmniCOVAS-local-reference/1"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            if response.geturl() != SOURCE_URL:
                raise ValueError("Unexpected reference redirect")
            return bytes(response.read(MAX_BYTES + 1))

    return await asyncio.to_thread(lambda: decode_reference(read()))
