"""PB13-02 source-class vocabulary — the nine classes, defined once.

PB13-02 requires that a known-facts result identify its source class as one
of nine: live local, local snapshot, observed history, commander-entered,
authority reference, imported dataset, disabled provider, unsupported, or
unknown.

Before this module those nine were split across two axes in two files and
neither held all of them. ``core/provenance.TruthClass`` carried five
confidence values; the feature modules emitted their own ``truth_class``
string literals; and ``ui/utils/freshness.js`` carried the imported /
disabled / unsupported end. Nothing enumerated the nine, and nothing
checked that an emitted value was one of them.

This module is the single definition. It does not replace ``truth_class``
— surfaces and tests depend on those values, and several are named in
ratified authority records — it maps every emitted value onto the PB13-02
class it belongs to.

``resolve`` deliberately returns ``None`` for a value it does not know,
rather than bucketing it into ``unknown``. An unrecognised class name is a
defect in the emitter, and ``unknown`` is a real answer meaning "we do not
know this fact" — collapsing the two would hide the bug behind a valid
label. ``test_source_class.py`` sweeps every Intel route and fails on any
``None``, which is what makes the PB13-02 requirement enforceable rather
than aspirational.

See: PB13-02 Intel Search, Reference, and Known Facts Workflow
See: ui/utils/source-class.js (mirror; parity is tested)
"""

from __future__ import annotations

from typing import Final

# The nine, in the order PB13-02 lists them.
LIVE_LOCAL: Final = "live_local"
LOCAL_SNAPSHOT: Final = "local_snapshot"
OBSERVED_HISTORY: Final = "observed_history"
COMMANDER_ENTERED: Final = "commander_entered"
AUTHORITY_REFERENCE: Final = "authority_reference"
IMPORTED_DATASET: Final = "imported_dataset"
DISABLED_PROVIDER: Final = "disabled_provider"
UNSUPPORTED: Final = "unsupported"
UNKNOWN: Final = "unknown"

SOURCE_CLASSES: Final[tuple[str, ...]] = (
    LIVE_LOCAL,
    LOCAL_SNAPSHOT,
    OBSERVED_HISTORY,
    COMMANDER_ENTERED,
    AUTHORITY_REFERENCE,
    IMPORTED_DATASET,
    DISABLED_PROVIDER,
    UNSUPPORTED,
    UNKNOWN,
)

# Human labels. Short enough to sit on a card without wrapping.
SOURCE_CLASS_LABELS: Final[dict[str, str]] = {
    LIVE_LOCAL: "Live local",
    LOCAL_SNAPSHOT: "Local snapshot",
    OBSERVED_HISTORY: "Observed history",
    COMMANDER_ENTERED: "Commander-entered",
    AUTHORITY_REFERENCE: "Reference",
    IMPORTED_DATASET: "Imported dataset",
    DISABLED_PROVIDER: "Provider disabled",
    UNSUPPORTED: "Unsupported",
    UNKNOWN: "Unknown",
}

# What a Commander should understand the class to mean. These are the words
# the surface uses, so they state the limit as well as the source.
SOURCE_CLASS_MEANINGS: Final[dict[str, str]] = {
    LIVE_LOCAL: "Read from this machine's live telemetry now.",
    LOCAL_SNAPSHOT: (
        "Read from a companion file this machine wrote. Current as of the "
        "last time the game wrote it, not necessarily now."
    ),
    OBSERVED_HISTORY: (
        "Derived from what this machine recorded. Recorded sessions only — "
        "absence is never proof something did not happen."
    ),
    COMMANDER_ENTERED: "You entered this. OmniCOVAS did not verify it.",
    AUTHORITY_REFERENCE: (
        "Curated local reference material, not live game data. Verify "
        "against the current game patch."
    ),
    IMPORTED_DATASET: ("From an imported dataset, subordinate to current local truth."),
    DISABLED_PROVIDER: (
        "A source that could supply this is switched off. Nothing was "
        "fetched and nothing was guessed."
    ),
    UNSUPPORTED: "OmniCOVAS cannot supply this fact.",
    UNKNOWN: "Not known. No value is being implied.",
}

# Every ``truth_class`` value emitted anywhere in the app, mapped to its
# PB13-02 class. Several of these names are fixed by ratified authority
# records (``local_observed_history`` is named in PB11-R2 and PB11-R4), so
# they are mapped rather than renamed.
_TRUTH_CLASS_TO_SOURCE_CLASS: Final[dict[str, str]] = {
    # Live local telemetry
    "live_local_telemetry": LIVE_LOCAL,
    "local_telemetry": LIVE_LOCAL,
    # Companion-file snapshots
    "local_screen_snapshot": LOCAL_SNAPSHOT,
    "local_snapshot": LOCAL_SNAPSHOT,
    # Recorded local history
    "local_event_history": OBSERVED_HISTORY,
    "local_observed_history": OBSERVED_HISTORY,
    # Commander input
    "commander_entered": COMMANDER_ENTERED,
    # Curated knowledge base
    "knowledge_reference": AUTHORITY_REFERENCE,
    # Imported / gated datasets
    "imported_current_galaxy": IMPORTED_DATASET,
    "imported_dataset": IMPORTED_DATASET,
    # Providers that exist but are off
    "disabled_source": DISABLED_PROVIDER,
    "disabled_provider": DISABLED_PROVIDER,
    # Explicit non-answers
    "unsupported": UNSUPPORTED,
    "unknown": UNKNOWN,
}


def resolve(truth_class: str | None) -> str | None:
    """Map an emitted ``truth_class`` onto its PB13-02 source class.

    Returns ``None`` for an unrecognised value. That is deliberate: an
    unmapped class name means an emitter introduced a value this vocabulary
    has never heard of, and silently calling it ``unknown`` would hide the
    defect behind a legitimate label.
    """
    if not truth_class:
        return None
    return _TRUTH_CLASS_TO_SOURCE_CLASS.get(str(truth_class).strip().lower())


def label(source_class: str | None) -> str:
    """Human label for a source class; falls back to the Unknown label."""
    return SOURCE_CLASS_LABELS.get(
        str(source_class or ""), SOURCE_CLASS_LABELS[UNKNOWN]
    )


def meaning(source_class: str | None) -> str:
    """What the class means for the Commander, limit included."""
    return SOURCE_CLASS_MEANINGS.get(
        str(source_class or ""), SOURCE_CLASS_MEANINGS[UNKNOWN]
    )


def known_truth_classes() -> tuple[str, ...]:
    """Every ``truth_class`` value this vocabulary recognises."""
    return tuple(sorted(_TRUTH_CLASS_TO_SOURCE_CLASS))
