"""Phase 9 AI campaign draft contract.

Owns: prompt construction, KB excerpt loading, output validation,
NullProvider deterministic response, and forbidden-claim scanning.

campaign.py orchestrates persistence and gate flow; this module owns
the AI safety contract only.

PB09-06 authority:
  authority_files/documents/07_phase_guides_playbooks/ai-workflow/Phase-9/
  PB09-06_Knowledge_Base_Reference_And_AI_Recommendation_Posture.md

Invariants preserved:
  - is_fact=False on every path (enforced by OmniCOVAS, not trusted from AI output).
  - source_chain from local linked IDs only — no fabricated fact metadata.
  - No raw commander private text in prompts (title/description/blockers/notes).
  - No outbound calls; no httpx; no requests; no provider_lookups; no source_router.
  - Powerplay exact merit values blocked while needs_review=true.
  - Live BGS tick-time claims blocked.
  - Disabled-provider claims blocked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final, TypedDict

# ---------------------------------------------------------------------------
# PB09-01 §5 — Canonical unsupported-fact list (verbatim)
# ---------------------------------------------------------------------------

UNSUPPORTED_FACTS: Final[list[str]] = [
    "Official Powerplay 2.0 strategy or canonical 'correct' play for a Power.",
    "Official BGS strategy or canonical 'correct' play for a faction.",
    "Real-time provider-derived faction influence percentages.",
    (
        "Real-time provider-derived BGS tick timing "
        "(KB tick reference is community consensus material, not a live tick clock)."
    ),
    "Aggregate cross-commander Powerplay merit totals.",
    "Aggregate cross-commander faction influence change rates.",
    (
        "Exact Powerplay 2.0 merit values per activity "
        "(KB entry pp2_merit_system needs_review: true)."
    ),
    "Shared squadron campaign aggregate state (Phase 7 squadron backend reserved).",
    "Galaxy-wide Powerplay/BGS lookup (no enabled provider supports it).",
    (
        "'Best campaign target' for the commander's Power without enumerating "
        "the sourced facts that informed the recommendation."
    ),
    (
        "'Optimal BGS objective' for a faction without enumerating "
        "the sourced facts that informed the recommendation."
    ),
    "Any Powerplay/BGS fact attributed to 'AI' without source_chain disclosure.",
    (
        "EliteBGS / EDSM / Inara / Spansh data presented as if currently retrieved "
        "when the provider is DISABLED."
    ),
    "KB content presented without KB-version / review-status disclosure.",
]

# ---------------------------------------------------------------------------
# PB09-01 §6 — Canonical fallback wording vocabulary (verbatim)
# ---------------------------------------------------------------------------

FALLBACK_VOCABULARY: Final[dict[str, str]] = {
    "Unknown": "No local or external evidence at all.",
    "Not Loaded": (
        "Local source has not yet been read this session, "
        "or a companion JSON file does not exist."
    ),
    "Disabled": (
        "Provider is configured DISABLED. Default for every external Phase 9 source."
    ),
    "Stale": "Local snapshot exists but freshness exceeds the documented threshold.",
    "Requires Authorization": (
        "Provider requires consent / auth / whitelist that has not been granted."
    ),
    "Unsupported": (
        "Provider exists but its documented capability does not include this fact."
    ),
    "No Verified Source": (
        "No provider has been verified for this fact. "
        "Default for Powerplay 2.0 strategic facts."
    ),
}

# ---------------------------------------------------------------------------
# Forbidden provider phrases — disabled-provider citation deny-list.
# These constants define what must NOT appear as accepted claims in AI output.
# Their presence in this module is intentional (deny-list definition).
# They must NOT appear in production code paths as accepted/pass-through claims.
# ---------------------------------------------------------------------------

FORBIDDEN_PROVIDER_PHRASES: Final[list[str]] = [
    "EliteBGS confirms",
    "EliteBGS reports",
    "EliteBGS shows",
    "EDSM reports",
    "EDSM confirms",
    "EDSM shows",
    "Inara shows",
    "Inara reports",
    "Inara confirms",
    "CAPI says",
    "CAPI reports",
    "CAPI confirms",
    "EDDN reports",
    "EDDN shows",
    "EDDN confirms",
    "Spansh says",
    "Spansh reports",
    "Spansh shows",
    "EDAstro reports",
    "EDAstro shows",
    "Ardent reports",
    "Ardent shows",
    "Ardent confirms",
]

# ---------------------------------------------------------------------------
# Validation patterns
# ---------------------------------------------------------------------------

# Matches specific Powerplay merit value claims adjacent to numeric digits.
# Targets: "10 merits", "earn 50 merits", "50 merit points", "merit value of 100"
# Does NOT match: IDs, timestamps, counts, generic ordering, non-merit numbers.
_MERIT_VALUE_RE: Final[re.Pattern[str]] = re.compile(
    r"\b\d+\s+merits?\b"  # "10 merits", "5 merit"
    r"|\bmerits?\s+value\s+of\s+\d+\b"  # "merit value of 100"
    r"|\bearn(?:ing|s|ed)?\s+\d+\s+merits?\b"  # "earning 50 merits"
    r"|\b\d+\s+merit\s+points?\b",  # "50 merit points"
    re.IGNORECASE,
)

# Matches live BGS tick time claims: time-of-day adjacent to tick/BGS-cycle keywords.
# Handles both orderings:
#   "14:30 UTC tick"               — time before keyword
#   "tick at 14:30"                — keyword then at|is|around then time
#   "tick is at 14:30"             — keyword then two qualifiers then time
#   "BGS reset is at 07:00 UTC"    — BGS-phrase then qualifiers then time
_BGS_TICK_TIME_RE: Final[re.Pattern[str]] = re.compile(
    # Time-of-day immediately followed by tick keyword
    r"\b\d{1,2}:\d{2}\s*(?:UTC|GMT|Z|BST)?\s*(?:tick|BGS\s+(?:cycle|reset|update))\b"
    # OR: tick/BGS-cycle keyword followed by up to 2 qualifiers then time
    r"|\b(?:tick|BGS\s+(?:cycle|reset|update|tick))"
    r"(?:\s+(?:is|at|around|time)){0,2}\s+\d{1,2}:\d{2}\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# NullProvider message
# ---------------------------------------------------------------------------

NULLPROVIDER_DRAFT_MESSAGE: Final[str] = (
    "AI drafting disabled. Use the commander-entered notes and the linked Intel "
    "facts to plan your next step."
)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class KBExcerpt(TypedDict):
    """A KB entry excerpt with full metadata for use in prompts and responses."""

    kb_file: str
    entry_id: str
    kb_version: str  # patch_verified value from KBEntry
    confidence: str
    needs_review: bool
    last_updated: str
    excerpt_text: str


class DraftValidationError:
    """Rejection result from validate_draft_output."""

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def __repr__(self) -> str:
        return f"DraftValidationError({self.reason!r})"


# ---------------------------------------------------------------------------
# KB excerpt loading
# ---------------------------------------------------------------------------

_DEFAULT_KB_DIR: Path = Path(__file__).parent.parent / "knowledge_base"

# Maps campaign workflow type to relevant KB categories.
_WORKFLOW_KB_CATEGORIES: Final[dict[str, list[str]]] = {
    "bgs": ["bgs_mechanics"],
    "powerplay": ["powerplay2_mechanics"],
}


def load_campaign_kb_excerpts(
    workflow_type: str,
    kb_dir: Path | None = None,
) -> list[KBExcerpt]:
    """Load KB excerpts for the given campaign workflow type.

    Returns excerpts with full metadata; caller must honor needs_review.
    Returns empty list if KB dir is unavailable or has no matching entries.
    Does not raise — missing KB degrades gracefully (Principle 5).
    """
    from omnicovas.knowledge_base.loader import (  # noqa: I001, PLC0415
        KBSchemaError,
        load_knowledge_base,
    )

    resolved = kb_dir if kb_dir is not None else _DEFAULT_KB_DIR
    try:
        kb = load_knowledge_base(resolved)
    except (KBSchemaError, OSError, ValueError):
        return []

    target_categories = _WORKFLOW_KB_CATEGORIES.get(workflow_type, [])
    excerpts: list[KBExcerpt] = []
    for entry in kb.all_entries():
        if entry.category in target_categories:
            excerpts.append(
                KBExcerpt(
                    kb_file=f"{entry.category}.json",
                    entry_id=entry.id,
                    kb_version=entry.patch_verified,
                    confidence=entry.confidence,
                    needs_review=entry.needs_review,
                    last_updated=entry.last_updated,
                    excerpt_text=entry.content,
                )
            )
    return excerpts


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(
    *,
    workflow_type: str,
    target_subject: str | None,
    target_system: str | None,
    linked_fact_ids: list[str],
    blocker_count: int,
    next_action_count: int,
    kb_excerpts: list[KBExcerpt],
) -> str:
    """Build an AI campaign draft prompt per PB09-06 §5.2 prompt discipline.

    Redaction rules:
      - No raw campaign title, description, blockers, or notes.
      - No commander credentials, API keys, or private identifiers.
      - Linked Intel facts are weak ID references only (metadata is Not Loaded).
      - Structural counts replace private text.
      - KB excerpts include full metadata including needs_review.
    """
    lines: list[str] = []

    lines.append(
        "You are an OmniCOVAS campaign drafting assistant. "
        "You may draft a campaign plan ONLY from the sourced facts "
        "and KB excerpts below. "
        "You may NOT invent power-merit values, faction-influence numbers, "
        "BGS tick times, or any external fact not provided in the inputs. "
        "Every recommendation must cite which sourced fact or KB entry informed it. "
        "You are not a source of facts. "
        "is_fact must always be false in your output."
    )
    lines.append("")

    lines.append("REQUIRED OUTPUT FORMAT (JSON object only):")
    lines.append(
        '  {"draft_text": "<suggestion>", '
        '"source_chain": [{"fact_id": "<id>"}], '
        '"kb_references": [{"kb_file": "<f>", "entry_id": "<id>", "needs_review": <bool>}],'  # noqa: E501
        ' "confidence_label": "low|medium|high", "is_fact": false}'
    )
    lines.append("")

    lines.append("FACTS YOU MUST NEVER STATE AS FACT OR INVENT:")
    for item in UNSUPPORTED_FACTS:
        lines.append(f"  - {item}")
    lines.append("")

    lines.append("FALLBACK WORDING TO USE WHEN INFORMATION IS NOT AVAILABLE:")
    for word, description in FALLBACK_VOCABULARY.items():
        lines.append(f"  {word}: {description}")
    lines.append("")

    lines.append("CAMPAIGN CONTEXT (structural counts only; no raw private text):")
    lines.append(f"  workflow_type: {workflow_type}")
    lines.append(f"  target_subject: {target_subject if target_subject else 'Not set'}")
    lines.append(f"  target_system: {target_system if target_system else 'Not set'}")
    lines.append(f"  linked_intel_fact_count: {len(linked_fact_ids)}")
    lines.append(f"  blocker_count: {blocker_count}")
    lines.append(f"  next_action_count: {next_action_count}")
    lines.append("")

    lines.append(
        "LINKED INTEL FACT IDs "
        "(local references only; full fact metadata is Not Loaded from this context):"
    )
    if linked_fact_ids:
        for fid in linked_fact_ids:
            lines.append(f"  - {fid}")
    else:
        lines.append("  (none linked)")
    lines.append("")

    lines.append("KNOWLEDGE BASE EXCERPTS:")
    if kb_excerpts:
        for exc in kb_excerpts:
            lines.append(f"  KB File: {exc['kb_file']}")
            lines.append(f"  Entry ID: {exc['entry_id']}")
            lines.append(f"  Confidence: {exc['confidence']}")
            lines.append(f"  Patch Verified: {exc['kb_version']}")
            lines.append(f"  Last Updated: {exc['last_updated']}")
            lines.append(f"  Needs Review: {exc['needs_review']}")
            if exc["needs_review"]:
                lines.append(
                    "  *** UNDER REVIEW: Do NOT cite specific merit values from "
                    "this entry as fact. Do NOT invent exact numeric merit values. ***"
                )
            lines.append(f"  Excerpt: {exc['excerpt_text']}")
            lines.append("")
    else:
        lines.append("  (no KB excerpts available for this workflow type)")
        lines.append("")

    lines.append("REFUSAL RULES:")
    lines.append(
        "  If the request requires exact Powerplay merit values and the KB entry "
        "has needs_review: true, output a stub using 'No Verified Source' wording."
    )
    lines.append(
        "  If the request requires a live BGS tick time, output: "
        "'No Verified Source — BGS tick time is community-tracked, not live.'"
    )
    lines.append(
        "  If any fact would require a DISABLED provider "
        "(EliteBGS, EDSM, CAPI, Inara, EDDN, Spansh, EDAstro, Ardent), "
        "use 'Disabled' wording."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------


def validate_draft_output(
    raw_output: str,
    *,
    allowed_fact_ids: frozenset[str],
    allowed_kb_ids: frozenset[tuple[str, str]],
    has_powerplay_needs_review: bool,
) -> DraftValidationError | None:
    """Validate AI draft output before accepting it.

    Returns None if valid, DraftValidationError(reason) if rejected.

    Validation strategy:
      - For structured JSON output: check is_fact, source_chain, kb_references.
      - For all output (JSON or plain text): scan for forbidden provider phrases,
        exact merit value claims (when needs_review), live BGS tick-time claims.

    This design allows existing plain-text AI responses to pass text-based checks
    while strictly validating any structured output the AI provides.

    Rejection criteria (PB09-06 §5.3 + amendments §6):
      JSON structure checks (when output is valid JSON dict):
        - is_fact field present but not False.
        - source_chain entry references fact_id not in allowed_fact_ids.
        - kb_references entry references (kb_file, entry_id) not in allowed_kb_ids.
      Content checks (all output):
        - draft_text contains a forbidden provider phrase (disabled provider claim).
        - draft_text contains a clear exact merit value claim while needs_review.
        - draft_text contains a live BGS tick-time claim.

    Does NOT reject:
      - IDs, counts, dates, timestamps, generic ordering, non-merit numbers.
      - Plain text output lacking JSON structure (text-only checks applied).
    """
    # --- Try to parse as structured JSON ---
    parsed: dict[str, Any] | None = None
    try:
        candidate: Any = json.loads(raw_output)
        if isinstance(candidate, dict):
            parsed = candidate
    except (json.JSONDecodeError, ValueError):
        pass

    if parsed is not None:
        # Structural checks only apply to JSON output.
        # is_fact: if present and not False, reject.
        if "is_fact" in parsed and parsed["is_fact"] is not False:
            return DraftValidationError("is_fact_not_false")

        # source_chain: each fact_id must be in allowed set.
        source_chain = parsed.get("source_chain")
        if isinstance(source_chain, list):
            for entry in source_chain:
                if isinstance(entry, dict):
                    fid = entry.get("fact_id")
                    if fid is not None and fid not in allowed_fact_ids:
                        return DraftValidationError(
                            f"source_chain_unknown_fact_id:{fid}"
                        )

        # kb_references: each (kb_file, entry_id) must be in allowed set.
        kb_refs = parsed.get("kb_references")
        if isinstance(kb_refs, list):
            for ref in kb_refs:
                if isinstance(ref, dict):
                    kb_file = ref.get("kb_file", "")
                    entry_id = ref.get("entry_id", "")
                    if (
                        kb_file
                        and entry_id
                        and (kb_file, entry_id) not in allowed_kb_ids
                    ):
                        return DraftValidationError(
                            f"kb_reference_unknown:{kb_file}/{entry_id}"
                        )

        # Use draft_text from parsed for content scans.
        text_to_scan = parsed.get("draft_text", "") or ""
        if not isinstance(text_to_scan, str):
            text_to_scan = ""
    else:
        # Plain text: apply content scans to the full raw output.
        text_to_scan = raw_output

    # --- Content scans (apply to all output forms) ---
    lower_text = text_to_scan.lower()

    for phrase in FORBIDDEN_PROVIDER_PHRASES:
        if phrase.lower() in lower_text:
            return DraftValidationError(f"forbidden_provider_claim:{phrase}")

    if has_powerplay_needs_review and _MERIT_VALUE_RE.search(text_to_scan):
        return DraftValidationError("exact_merit_value_claim_while_needs_review")

    if _BGS_TICK_TIME_RE.search(text_to_scan):
        return DraftValidationError("live_bgs_tick_time_claim")

    return None


# ---------------------------------------------------------------------------
# NullProvider response builder
# ---------------------------------------------------------------------------


def build_nullprovider_response(
    linked_fact_ids: list[str],
    kb_excerpts: list[KBExcerpt],
) -> dict[str, Any]:
    """Build the NullProvider draft response dict.

    No prompt constructed. No outbound call. Deterministic message.
    is_fact=False. source_chain from local linked IDs. KB refs disclosed.
    needs_review disclosed where applicable.
    """
    if linked_fact_ids:
        source_chain: list[dict[str, Any]] = [
            {
                "fact_id": fid,
                "truth_class": "local_event_history",
                "freshness": "last_known",
            }
            for fid in linked_fact_ids
        ]
    else:
        source_chain = [
            {
                "source": "ai_provider",
                "truth_class": "disabled_source",
                "freshness": "not_loaded",
                "kind": "ai_draft",
            }
        ]

    kb_refs: list[dict[str, Any]] = [
        {
            "kb_file": exc["kb_file"],
            "entry_id": exc["entry_id"],
            "kb_version": exc["kb_version"],
            "confidence": exc["confidence"],
            "needs_review": exc["needs_review"],
            "last_updated": exc["last_updated"],
        }
        for exc in kb_excerpts
    ]

    return {
        "status": "nullprovider",
        "draft_text": None,
        "nullprovider_message": NULLPROVIDER_DRAFT_MESSAGE,
        "is_fact": False,
        "source_chain": source_chain,
        "kb_references": kb_refs,
        "confidence_label": None,
        "nullprovider_safe": True,
    }
