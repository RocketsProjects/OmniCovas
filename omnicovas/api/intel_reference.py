"""Read-only Intel Reference Library endpoint (PB13-02 slice).

Workflow-scoped curated reference from the validated local Knowledge
Base. Truth class knowledge_reference; needs_review entries are withheld
(PB13-03 guard). No providers, no persistence, no AI generation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from omnicovas.features import intel_reference

router = APIRouter(prefix="/intel", tags=["intel"])

_kb_dir: Path | None = None


def set_kb_dir(kb_dir: Path | None) -> None:
    """Override the knowledge-base directory (focused tests only)."""
    global _kb_dir  # noqa: PLW0603
    _kb_dir = kb_dir
    intel_reference.reset_reference_cache()


class ReferenceEntryRow(BaseModel):
    """One curated reference entry (content withheld when flagged)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    topic: str
    category: str
    status: str
    content: str | None
    withheld_reason: str | None
    patch_verified: str | None
    reference_source: str | None
    last_updated: str | None
    confidence: str | None


class ReferenceCategory(BaseModel):
    """One knowledge-base category with its entries."""

    model_config = ConfigDict(extra="forbid")

    category: str
    label: str
    entry_count: int
    entries: list[ReferenceEntryRow]


class ReferenceLibraryResponse(BaseModel):
    """Workflow-scoped curated reference library."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    total_entries: int
    withheld_count: int
    categories: list[ReferenceCategory]
    nullprovider_safe: bool


@router.get("/reference", response_model=ReferenceLibraryResponse)
async def get_reference_library() -> dict[str, Any]:
    """Curated local knowledge reference (workflow-scoped, never live data)."""
    return intel_reference.reference_library_payload(_kb_dir)
