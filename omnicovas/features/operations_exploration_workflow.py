"""Operations exploration workflow depth (Phase 14 R5).

PB05-08 gave Operations an exploration snapshot built from one fact: whether a
route is loaded. It could say "Transit to Colonia" and nothing else, and its
exobiology checklist was five rows hardcoded to `unknown` whose own docstring
admitted no journal event was ever read. This module is the workflow layer that
was missing — a stage, meaningful progress, a concrete derived step, honest
work-remaining, genuine blockers, and a completion-readiness rule.

Ownership is unchanged and deliberately narrow:

  * **Operations** owns the workflow — what stage am I at, what work remains,
    what is blocking me, what should I do next, is this effectively finished.
  * **Intel** owns the facts — the system record, the body table, biology,
    candidate genera, scan value. This module *reads* Intel-owned services and
    reports counts and one-line summaries; it never rebuilds their browsers.
  * **Navigation** owns routes. This module reads the active route reference
    that PB05-08 already consumed and plans nothing.

Every number here comes from the Commander's own journal, recorded in the local
flight recorder. Nothing is fetched, nothing is predicted into fact, and the
three exobiology truth levels stay separated end to end:

    observed genus  ->  fact       (SAASignalsFound named it)
    candidate genus ->  prediction (the ruleset thinks it could be here)
    unknown         ->  unknown    (the journal has not said)

A candidate never counts toward completed biology, and an unrecorded body count
never becomes "0 bodies remaining".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.features import exobiology_intel, exploration_history

# ---------------------------------------------------------------------------
# Stage vocabulary
# ---------------------------------------------------------------------------
#
# The smallest set of stages that local data can actually prove, expressed as
# an ordered ladder of gates: the stage is the FIRST gate whose work is still
# open. That makes it deterministic — the same journal facts always produce the
# same stage — and explainable, because every stage names the fact that put the
# Commander in it.
#
# This is not a quest state machine and there are no transitions to fire. There
# is no persisted stage to drift out of step with the journal, because the
# stage is a reading of the journal.

STAGE_UNKNOWN = "unknown"
STAGE_TRANSIT = "transit"
STAGE_ARRIVED = "arrived"
STAGE_SYSTEM_SURVEY = "system_survey"
STAGE_SURFACE_SURVEY = "surface_survey"
STAGE_BIOLOGY = "biology"
STAGE_DEPARTURE_READY = "departure_ready"

STAGE_ORDER: tuple[str, ...] = (
    STAGE_UNKNOWN,
    STAGE_TRANSIT,
    STAGE_ARRIVED,
    STAGE_SYSTEM_SURVEY,
    STAGE_SURFACE_SURVEY,
    STAGE_BIOLOGY,
    STAGE_DEPARTURE_READY,
)

STAGE_LABELS: dict[str, str] = {
    STAGE_UNKNOWN: "Unknown",
    STAGE_TRANSIT: "In transit",
    STAGE_ARRIVED: "Arrived",
    STAGE_SYSTEM_SURVEY: "System survey",
    STAGE_SURFACE_SURVEY: "Surface survey",
    STAGE_BIOLOGY: "Biology",
    STAGE_DEPARTURE_READY: "Departure ready",
}

# ---------------------------------------------------------------------------
# Completion readiness
# ---------------------------------------------------------------------------
#
# "Exploration complete" is a claim this product cannot make: it would require
# knowing the coverage of facts it has never seen. What it CAN say is how much
# locally-known work is left, and when the honest answer is "I do not know how
# much there is", it says that instead.

COMPLETION_UNKNOWN_COVERAGE = "unknown_coverage"
COMPLETION_WORK_REMAINING = "work_remaining"
COMPLETION_NO_KNOWN_WORK = "no_known_work_remaining"

COMPLETION_LABELS: dict[str, str] = {
    COMPLETION_UNKNOWN_COVERAGE: "Work remaining unknown",
    COMPLETION_WORK_REMAINING: "Work remaining",
    COMPLETION_NO_KNOWN_WORK: "No additional locally-known work detected",
}

# Work-item kinds. `work` is proven outstanding; `opportunity` is offered by a
# prediction or an estimate and never counted as proven; `unknown` is a fact the
# journal has not supplied and must not be reported as zero.
WORK_KIND_WORK = "work"
WORK_KIND_OPPORTUNITY = "opportunity"
WORK_KIND_UNKNOWN = "unknown"

# Checklist item states.
ITEM_COMPLETE = "complete"
ITEM_ACTIVE = "active"
ITEM_UNKNOWN = "unknown"

TRUTH_LOCAL_EVENT_HISTORY = exploration_history.TRUTH_LOCAL_EVENT_HISTORY
TRUTH_KNOWLEDGE_REFERENCE = exobiology_intel.TRUTH_KNOWLEDGE_REFERENCE
SOURCE_FLIGHT_RECORDER = exploration_history.SOURCE_FLIGHT_RECORDER

# A body only earns "worth mapping" from an estimate, so the wording that
# reaches the Commander must carry the estimate with it.
MAPPING_VALUE_CLASSES = frozenset({"high", "very_high"})

_BODY_SAMPLE_LIMIT = 500

WORKFLOW_CAVEAT = (
    "Exploration workflow derived from this machine's own journal history. "
    "Observed biology is fact; candidate biology is a prediction and is never "
    "counted as sampled. A body count the journal never recorded stays Unknown "
    "rather than being read as nothing remaining."
)

UNAVAILABLE_CAVEAT = (
    "The local exploration history could not be read, so no exploration "
    "progress is claimed. This is Unknown, not an empty system."
)


def _normalise(value: Any) -> str:
    return str(value or "").strip().lower()


def _genus_sampled(genus: str, species_names: list[str]) -> bool:
    """Has any species of this genus been logged on this body?

    Uses the same genus/species name containment the Intel biology surface
    already uses for `genera_never_logged_by_commander`, so one rule decides
    the relationship in both places rather than two that can disagree.
    """
    token = _normalise(genus)
    return bool(token) and any(token in _normalise(name) for name in species_names)


# ---------------------------------------------------------------------------
# Derived identity
# ---------------------------------------------------------------------------
#
# R1 made these identities deterministic and R5 keeps that contract: the ID is
# the kind plus the semantic target, never the reading that produced it. The
# derived step for a system survey of Colonia carries one identity for the whole
# survey, so a surface can correlate, and a restart reproduces it exactly.


def _identity(kind: str, target: str | None = None) -> str:
    from omnicovas.features.operations_exploration import objective_identity

    return objective_identity(kind, target)


# ---------------------------------------------------------------------------
# Fact gathering
# ---------------------------------------------------------------------------


async def _gather(
    session_factory: async_sessionmaker[AsyncSession],
    star_system: str | None,
) -> dict[str, Any]:
    """Read every Intel-owned exploration fact this workflow needs, once."""
    systems = await exploration_history.explored_systems(
        session_factory, star_system=star_system
    )
    record = None
    for entry in systems.get("systems") or []:
        if entry.get("star_system") == star_system:
            record = entry
            break

    bodies = await exploration_history.scanned_bodies(
        session_factory, star_system=star_system, limit=_BODY_SAMPLE_LIMIT
    )
    biology = await exobiology_intel.biological_signals(
        session_factory, star_system=star_system
    )
    earnings = await exploration_history.exploration_earnings(session_factory)
    return {
        "record": record,
        "bodies": bodies,
        "biology": biology,
        "earnings": earnings,
    }


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


def _system_progress(record: dict[str, Any] | None) -> dict[str, Any]:
    if record is None:
        return {
            "bodies_scanned": 0,
            "bodies_in_system": None,
            "body_count_known": False,
            "survey_complete": False,
            "first_discoveries": 0,
            "bodies_with_discovery_flag": 0,
            "any_evidence": False,
        }
    return {
        "bodies_scanned": int(record.get("bodies_scanned") or 0),
        # None means the honk was never recorded here. It is rendered as
        # Unknown; it is never rendered as "everything is scanned".
        "bodies_in_system": record.get("bodies_in_system"),
        "body_count_known": bool(record.get("body_count_known")),
        "survey_complete": bool(record.get("survey_complete")),
        "first_discoveries": int(record.get("first_discoveries") or 0),
        "bodies_with_discovery_flag": int(
            record.get("bodies_with_discovery_flag") or 0
        ),
        "any_evidence": bool(record.get("bodies_scanned")),
    }


def _mapping_progress(
    record: dict[str, Any] | None, bodies_payload: dict[str, Any]
) -> dict[str, Any]:
    bodies = list(bodies_payload.get("bodies") or [])
    mapped = int((record or {}).get("bodies_surface_mapped") or 0)

    unmapped_valuable: list[dict[str, Any]] = []
    for body in bodies:
        if body.get("surface_mapped_by_commander") is True:
            continue
        estimate = body.get("value_estimate")
        if not estimate:
            continue
        if estimate.get("value_class") in MAPPING_VALUE_CLASSES:
            unmapped_valuable.append(
                {
                    "body_name": body.get("body_name"),
                    "value_class": estimate.get("value_class"),
                    "estimated_low": estimate.get("estimated_low"),
                    "estimated_high": estimate.get("estimated_high"),
                }
            )
    # Highest estimate first, then by name, so repeated reads of unchanged
    # facts produce the same order and the same "map this next" answer.
    unmapped_valuable.sort(
        key=lambda entry: (-int(entry["estimated_high"] or 0), str(entry["body_name"]))
    )
    return {
        "bodies_surface_mapped": mapped,
        # Bodies whose class was never recorded cannot be judged worth mapping.
        # They are reported, not silently treated as worthless.
        "bodies_unvalued": int(
            (bodies_payload.get("value_estimate_summary") or {}).get(
                "bodies_unvalued", 0
            )
        ),
        "unmapped_valuable": unmapped_valuable,
        "unmapped_valuable_count": len(unmapped_valuable),
    }


def _biology_progress(biology_payload: dict[str, Any]) -> dict[str, Any]:
    bodies = list(biology_payload.get("bodies") or [])

    bodies_with_signals = len(bodies)
    bodies_observed = 0
    bodies_candidate_only = 0
    genera_observed = 0
    genera_unsampled: list[dict[str, Any]] = []
    species_sampled = 0
    species_analysed = 0
    species_incomplete: list[dict[str, Any]] = []
    candidate_genera_total = 0

    for body in bodies:
        observed = [g for g in (body.get("observed_genera") or []) if g]
        candidates = list(body.get("candidate_genera") or [])
        sampled_here = [str(s) for s in (body.get("species_sampled_here") or [])]

        if observed:
            bodies_observed += 1
            genera_observed += len(observed)
        elif candidates:
            # Predicted, not seen. Counted in its own column so it can never be
            # added to the observed total by a later reader.
            bodies_candidate_only += 1
        candidate_genera_total += len(candidates)

        for genus in observed:
            if not _genus_sampled(genus, sampled_here):
                genera_unsampled.append(
                    {"body_name": body.get("body_name"), "genus": genus}
                )

        for entry in body.get("sampling_progress") or []:
            species_sampled += 1
            if entry.get("analysed") is True:
                species_analysed += 1
            else:
                species_incomplete.append(
                    {
                        "body_name": body.get("body_name"),
                        "species": entry.get("species"),
                        "stages_recorded": list(entry.get("stages_recorded") or []),
                    }
                )

    # A recorded biological signal is a FACT even before a genus is named:
    # Elite reports the count on SAASignalsFound and only names genera later.
    # A body carrying signals with nothing named and nothing sampled therefore
    # has real outstanding work, and saying "nothing remains" there would be
    # false. What is UNKNOWN is which organism it is, not whether one is there.
    signals_unresolved = [
        {"body_name": body.get("body_name")}
        for body in bodies
        if not (body.get("observed_genera") or [])
        and not (body.get("species_sampled_here") or [])
    ]
    signals_unresolved.sort(key=lambda e: str(e["body_name"]))

    genera_unsampled.sort(key=lambda e: (str(e["body_name"]), str(e["genus"])))
    species_incomplete.sort(key=lambda e: (str(e["body_name"]), str(e["species"])))

    sentinel = (biology_payload.get("candidate_basis") or {}).get("sentinel") or {}
    return {
        "bodies_with_signals": bodies_with_signals,
        "bodies_with_observed_genera": bodies_observed,
        "bodies_candidate_only": bodies_candidate_only,
        "bodies_signals_unresolved": signals_unresolved,
        "genera_observed": genera_observed,
        "genera_observed_unsampled": genera_unsampled,
        "candidate_genera": candidate_genera_total,
        "species_sampled": species_sampled,
        "species_analysed": species_analysed,
        "species_sampling_incomplete": species_incomplete,
        # The Sentinel's own read-only verdict, carried so a surface can refuse
        # to present a suspended predicate as authoritative. R5 consumes it and
        # never modifies the canonical ruleset.
        "sentinel_predicate_state": sentinel.get("predicate_state"),
        "sentinel_open_contradictions": sentinel.get("open_contradictions"),
    }


def _footfall_progress(record: dict[str, Any] | None) -> dict[str, Any]:
    """First-discovery evidence — deliberately not a first-footfall claim.

    `WasDiscovered: false` on a body scan proves nobody had scanned it before.
    That is a real, local, checkable fact and it is reported as exactly that.
    It is NOT first footfall: landing first is a different event and the journal
    carries no verified signal for it, so that stays Unknown (P14-F04 remains
    deferred, and R5 does not promote a neighbouring fact into its place).
    """
    system = _system_progress(record)
    scanned = system["bodies_scanned"]
    flagged = system["bodies_with_discovery_flag"]
    firsts = system["first_discoveries"]
    return {
        "first_discoveries": firsts,
        "bodies_with_discovery_flag": flagged,
        # True only when the journal flagged every scanned body and every one
        # came back undiscovered. Silence is not evidence of virgin territory.
        "no_prior_discovery_recorded": bool(
            scanned and flagged == scanned and firsts == scanned
        ),
        "discovery_flag_coverage_complete": bool(scanned and flagged == scanned),
        "first_footfall": "Unknown",
        "first_footfall_reason": (
            "First footfall has no verified local source. Landing order is not "
            "recorded in the journal, and no provider is enabled."
        ),
    }


# ---------------------------------------------------------------------------
# Stage derivation
# ---------------------------------------------------------------------------


def derive_stage(
    *,
    star_system: str | None,
    system: dict[str, Any],
    mapping: dict[str, Any],
    biology: dict[str, Any],
    route_active: bool,
    route_destination: str | None,
) -> tuple[str, str]:
    """Return `(stage, detail)` — the first gate with open work.

    Pure over the facts handed to it, so two reads of unchanged state always
    agree, and a test can drive every branch without a database.
    """
    if not star_system:
        return (
            STAGE_UNKNOWN,
            "Current system not reported by local telemetry, so no exploration "
            "stage is claimed.",
        )

    if not system["any_evidence"]:
        if route_active and route_destination and route_destination != star_system:
            return (
                STAGE_TRANSIT,
                f"En route to {route_destination}. Nothing scanned yet in "
                f"{star_system}.",
            )
        return (
            STAGE_ARRIVED,
            f"In {star_system}. No scan recorded here yet.",
        )

    if not system["survey_complete"]:
        if system["body_count_known"]:
            remaining = max(
                0, int(system["bodies_in_system"] or 0) - system["bodies_scanned"]
            )
            return (
                STAGE_SYSTEM_SURVEY,
                f"{system['bodies_scanned']} of {system['bodies_in_system']} "
                f"bodies scanned in {star_system}"
                + (f"; {remaining} not yet scanned." if remaining else "."),
            )
        return (
            STAGE_SYSTEM_SURVEY,
            f"{system['bodies_scanned']} bodies scanned in {star_system}. The "
            "system body count was never recorded, so how many remain is "
            "Unknown.",
        )

    if mapping["unmapped_valuable_count"] > 0:
        lead = mapping["unmapped_valuable"][0]["body_name"]
        return (
            STAGE_SURFACE_SURVEY,
            f"Survey complete. {mapping['unmapped_valuable_count']} scanned "
            f"bod{'y' if mapping['unmapped_valuable_count'] == 1 else 'ies'} "
            f"with a high estimated value carry no surface map — {lead} is the "
            "highest estimate.",
        )

    if (
        biology["genera_observed_unsampled"]
        or biology["species_sampling_incomplete"]
        or biology["bodies_signals_unresolved"]
    ):
        return (
            STAGE_BIOLOGY,
            f"Survey complete. Biological signals in {star_system} have "
            "sampling still outstanding.",
        )

    return (
        STAGE_DEPARTURE_READY,
        f"No additional locally-known exploration work detected in {star_system}.",
    )


# ---------------------------------------------------------------------------
# Derived step (the workflow objective)
# ---------------------------------------------------------------------------


def derive_step(
    *,
    stage: str,
    star_system: str | None,
    system: dict[str, Any],
    mapping: dict[str, Any],
    biology: dict[str, Any],
    route_destination: str | None,
) -> dict[str, Any] | None:
    """The one concrete thing to do now, named after the thing itself.

    R1 made this identity stable; R5 makes it useful. It is a DERIVED step and
    says so: `owner` is `derived`, never `commander_entered`. It exists beside
    the Commander's own objective and never replaces, overwrites or interprets
    it — no free text is read here, and no classifier decides anything.
    """
    if stage == STAGE_UNKNOWN:
        return None

    if stage == STAGE_TRANSIT:
        target = route_destination or "route destination"
        return {
            "objective_id": _identity("destination_transit", route_destination),
            "kind": "destination_transit",
            "label": f"Continue to {target}",
            "state": "active",
            "target": route_destination,
            "target_kind": "system",
            "owner": "derived",
            "source_id": "local_navroute",
        }

    if stage == STAGE_ARRIVED:
        return {
            "objective_id": _identity("system_survey", star_system),
            "kind": "system_survey",
            "label": f"Run a system survey in {star_system}",
            "state": "active",
            "target": star_system,
            "target_kind": "system",
            "owner": "derived",
            "source_id": TRUTH_LOCAL_EVENT_HISTORY,
        }

    if stage == STAGE_SYSTEM_SURVEY:
        label = (
            f"Review unscanned bodies in {star_system}"
            if system["body_count_known"]
            else f"Continue the survey of {star_system}"
        )
        return {
            "objective_id": _identity("system_survey", star_system),
            "kind": "system_survey",
            "label": label,
            "state": "active",
            "target": star_system,
            "target_kind": "system",
            "owner": "derived",
            "source_id": TRUTH_LOCAL_EVENT_HISTORY,
        }

    if stage == STAGE_SURFACE_SURVEY:
        lead = mapping["unmapped_valuable"][0]
        return {
            "objective_id": _identity("surface_map", lead["body_name"]),
            "kind": "surface_map",
            "label": f"Map {lead['body_name']}",
            "state": "active",
            "target": lead["body_name"],
            "target_kind": "body",
            "owner": "derived",
            # The body is a fact; "worth mapping" is a reference estimate, and
            # the step carries both classes rather than blurring them.
            "source_id": TRUTH_LOCAL_EVENT_HISTORY,
            "priority_basis": TRUTH_KNOWLEDGE_REFERENCE,
        }

    if stage == STAGE_BIOLOGY:
        if biology["genera_observed_unsampled"]:
            lead = biology["genera_observed_unsampled"][0]
            label = f"Sample {lead['genus']} on {lead['body_name']}"
            target = lead["body_name"]
        elif biology["species_sampling_incomplete"]:
            lead = biology["species_sampling_incomplete"][0]
            label = f"Finish sampling {lead['species']} on {lead['body_name']}"
            target = lead["body_name"]
        else:
            # Signals recorded, no genus named. The step says investigate, not
            # "sample <candidate>": naming a prediction here would present it as
            # the thing that is actually down there.
            lead = biology["bodies_signals_unresolved"][0]
            label = f"Investigate biology on {lead['body_name']}"
            target = lead["body_name"]
        return {
            "objective_id": _identity("biology_sampling", target),
            "kind": "biology_sampling",
            "label": label,
            "state": "active",
            "target": target,
            "target_kind": "body",
            "owner": "derived",
            "source_id": TRUTH_LOCAL_EVENT_HISTORY,
        }

    # STAGE_DEPARTURE_READY
    if route_destination:
        return {
            "objective_id": _identity("destination_transit", route_destination),
            "kind": "destination_transit",
            "label": f"Continue to {route_destination}",
            "state": "active",
            "target": route_destination,
            "target_kind": "system",
            "owner": "derived",
            "source_id": "local_navroute",
        }
    return {
        "objective_id": _identity("plot_next_leg", star_system),
        "kind": "plot_next_leg",
        "label": "Plot the next leg in Navigation",
        "state": "active",
        "target": None,
        "target_kind": None,
        "owner": "derived",
        "source_id": "local_navroute",
    }


# ---------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------


def derive_checklist(
    *,
    star_system: str | None,
    system: dict[str, Any],
    mapping: dict[str, Any],
    biology: dict[str, Any],
    sample_stages: dict[str, bool],
) -> list[dict[str, Any]]:
    """The exobiology/exploration checklist, advanced by evidence only.

    PB05-08's five rows could never change state, and two of them never can:
    exobiology valuation has no verified source and first footfall has no local
    signal at all. Rather than keep two permanently-`unknown` rows so the list
    looks longer, both are withdrawn from the checklist. What they were
    gesturing at survives where it is truthful — actual and estimated value in
    `value`, first-discovery evidence in `footfall` — and each says plainly what
    it does not know.

    Every remaining row names the journal event that advances it. A row advances
    on recorded evidence and on nothing else: never on a prediction, never on a
    missing file, and never on the absence of contrary evidence.
    """
    if not star_system:
        return [
            {
                "item_id": item_id,
                "label": label,
                "state": ITEM_UNKNOWN,
                "evidence": None,
                "source_event": event,
                "caveat": (
                    "Current system not reported by local telemetry, so no "
                    "checklist progress is claimed."
                ),
            }
            for item_id, label, event in (
                ("system_survey", "System survey recorded", "FSSDiscoveryScan"),
                ("bodies_scanned", "Bodies scanned", "Scan"),
                ("surface_map", "Surface map recorded", "SAAScanComplete"),
                ("biology_signals", "Biological signals detected", "SAASignalsFound"),
                ("bio_log", "First bio sample logged", "ScanOrganic"),
                ("bio_sample", "Second bio sample taken", "ScanOrganic"),
                ("bio_analyse", "Bio sample analysed", "ScanOrganic"),
            )
        ]

    items: list[dict[str, Any]] = []

    items.append(
        {
            "item_id": "system_survey",
            "label": "System survey recorded",
            "state": ITEM_COMPLETE if system["body_count_known"] else ITEM_UNKNOWN,
            "evidence": (
                f"{system['bodies_in_system']} bodies reported in {star_system}"
                if system["body_count_known"]
                else None
            ),
            "source_event": "FSSDiscoveryScan",
            "caveat": (
                None
                if system["body_count_known"]
                else "No system survey recorded here, so the body count is Unknown."
            ),
        }
    )

    if system["survey_complete"]:
        bodies_state, bodies_evidence = (
            ITEM_COMPLETE,
            f"All bodies found in {star_system}",
        )
    elif system["bodies_scanned"]:
        bodies_state, bodies_evidence = (
            ITEM_ACTIVE,
            f"{system['bodies_scanned']} scanned"
            + (
                f" of {system['bodies_in_system']}"
                if system["body_count_known"]
                else " (total Unknown)"
            ),
        )
    else:
        bodies_state, bodies_evidence = ITEM_UNKNOWN, None
    items.append(
        {
            "item_id": "bodies_scanned",
            "label": "Bodies scanned",
            "state": bodies_state,
            "evidence": bodies_evidence,
            "source_event": "Scan / FSSAllBodiesFound",
            "caveat": (
                None
                if system["body_count_known"] or not system["bodies_scanned"]
                else "How many bodies remain is Unknown without a system survey."
            ),
        }
    )

    mapped = mapping["bodies_surface_mapped"]
    items.append(
        {
            "item_id": "surface_map",
            "label": "Surface map recorded",
            "state": ITEM_COMPLETE if mapped else ITEM_UNKNOWN,
            "evidence": f"{mapped} surface-mapped here" if mapped else None,
            "source_event": "SAAScanComplete",
            "caveat": (
                None
                if mapped
                else "No surface map recorded here. Mapping is selective, so "
                "this is not a shortfall."
            ),
        }
    )

    signals = biology["bodies_with_signals"]
    observed = biology["bodies_with_observed_genera"]
    if observed:
        signal_state = ITEM_COMPLETE
        signal_evidence = f"{observed} bod{'y' if observed == 1 else 'ies'} "
        signal_evidence += "with observed genera"
    elif signals:
        # Signals detected but no genus named, so the biology here is still a
        # prediction. It stays `active`, never `complete`.
        signal_state = ITEM_ACTIVE
        signal_evidence = f"{signals} bod{'y' if signals == 1 else 'ies'} with signals"
    else:
        signal_state = ITEM_UNKNOWN
        signal_evidence = None
    items.append(
        {
            "item_id": "biology_signals",
            "label": "Biological signals detected",
            "state": signal_state,
            "evidence": signal_evidence,
            "source_event": "SAASignalsFound",
            "caveat": (
                None
                if observed
                else "Candidate genera are a prediction and do not advance this row."
            ),
        }
    )

    for item_id, label, stage_key in (
        ("bio_log", "First bio sample logged", "log"),
        ("bio_sample", "Second bio sample taken", "sample"),
        ("bio_analyse", "Bio sample analysed", "analyse"),
    ):
        recorded = bool(sample_stages.get(stage_key))
        items.append(
            {
                "item_id": item_id,
                "label": label,
                "state": ITEM_COMPLETE if recorded else ITEM_UNKNOWN,
                "evidence": (
                    f"ScanOrganic {stage_key.title()} recorded in {star_system}"
                    if recorded
                    else None
                ),
                "source_event": "ScanOrganic",
                "caveat": (
                    None
                    if recorded
                    else "Advances only on a recorded ScanOrganic event."
                ),
            }
        )

    return items


def _sample_stages(biology_payload: dict[str, Any]) -> dict[str, bool]:
    """Which ScanOrganic stages this system's bodies actually recorded."""
    stages = {"log": False, "sample": False, "analyse": False}
    for body in biology_payload.get("bodies") or []:
        for entry in body.get("sampling_progress") or []:
            for stage in entry.get("stages_recorded") or []:
                key = _normalise(stage)
                if key in stages:
                    stages[key] = True
    return stages


# ---------------------------------------------------------------------------
# Work remaining, blockers, completion
# ---------------------------------------------------------------------------


def derive_work_remaining(
    *,
    star_system: str | None,
    system: dict[str, Any],
    mapping: dict[str, Any],
    biology: dict[str, Any],
) -> list[dict[str, Any]]:
    """A concise workflow-level answer to "what is left here?".

    Never a body table — Intel owns that, and a handoff carries the Commander
    there. Each entry declares whether it is proven work, an opportunity offered
    by a prediction or an estimate, or a fact the journal never recorded.
    """
    if not star_system:
        return [
            {
                "id": "work.unknown.no_system",
                "label": "Work remaining unknown",
                "detail": "Current system not reported by local telemetry.",
                "kind": WORK_KIND_UNKNOWN,
            }
        ]

    items: list[dict[str, Any]] = []

    if not system["body_count_known"]:
        items.append(
            {
                "id": "work.unknown.body_count",
                "label": "Bodies in system unknown",
                "detail": (
                    "No system survey recorded here, so how many bodies remain "
                    "cannot be stated."
                ),
                "kind": WORK_KIND_UNKNOWN,
            }
        )
    elif not system["survey_complete"]:
        remaining = max(
            0, int(system["bodies_in_system"] or 0) - system["bodies_scanned"]
        )
        if remaining:
            items.append(
                {
                    "id": "work.system.unscanned_bodies",
                    "label": (
                        f"{remaining} unscanned bod"
                        f"{'y remains' if remaining == 1 else 'ies remain'}"
                    ),
                    "detail": (
                        f"{system['bodies_scanned']} of "
                        f"{system['bodies_in_system']} scanned."
                    ),
                    "kind": WORK_KIND_WORK,
                }
            )

    count = mapping["unmapped_valuable_count"]
    if count:
        items.append(
            {
                "id": "work.mapping.unmapped_valuable",
                "label": (
                    f"{count} high-value unmapped bod"
                    f"{'y remains' if count == 1 else 'ies remain'}"
                ),
                "detail": (
                    "Highest estimate: "
                    f"{mapping['unmapped_valuable'][0]['body_name']}. Value is "
                    "a reference estimate, not credits earned."
                ),
                "kind": WORK_KIND_OPPORTUNITY,
            }
        )

    unsampled = biology["genera_observed_unsampled"]
    if unsampled:
        items.append(
            {
                "id": "work.biology.observed_unsampled",
                "label": (
                    f"{len(unsampled)} observed "
                    f"{'genus' if len(unsampled) == 1 else 'genera'} not yet sampled"
                ),
                "detail": (
                    f"{unsampled[0]['genus']} on {unsampled[0]['body_name']}. "
                    "Observed in the journal, so this is a fact."
                ),
                "kind": WORK_KIND_WORK,
            }
        )

    incomplete = biology["species_sampling_incomplete"]
    if incomplete:
        items.append(
            {
                "id": "work.biology.sampling_incomplete",
                "label": (f"{len(incomplete)} species sampled but not analysed"),
                "detail": (
                    f"{incomplete[0]['species']} on {incomplete[0]['body_name']} "
                    f"recorded {', '.join(incomplete[0]['stages_recorded']) or 'no'} "
                    "stage(s)."
                ),
                "kind": WORK_KIND_WORK,
            }
        )

    unresolved = biology["bodies_signals_unresolved"]
    if unresolved:
        items.append(
            {
                "id": "work.biology.signals_unresolved",
                "label": (
                    f"{len(unresolved)} bod"
                    f"{'y' if len(unresolved) == 1 else 'ies'} with biological "
                    "signals not yet sampled"
                ),
                "detail": (
                    f"{unresolved[0]['body_name']} recorded a biological signal. "
                    "Which organism is there is Unknown until it is scanned."
                ),
                "kind": WORK_KIND_WORK,
            }
        )

    if biology["bodies_candidate_only"]:
        items.append(
            {
                "id": "work.biology.candidate_only",
                "label": (
                    f"{biology['bodies_candidate_only']} bod"
                    f"{'y' if biology['bodies_candidate_only'] == 1 else 'ies'} "
                    "may hold biology"
                ),
                "detail": (
                    "Candidate genera only — a prediction from the local "
                    "ruleset. Nothing has been observed on these bodies."
                ),
                "kind": WORK_KIND_OPPORTUNITY,
            }
        )

    return items


def derive_blockers(
    *,
    star_system: str | None,
    available: bool,
    stage: str,
    route_active: bool,
    navroute_loaded: bool,
) -> list[dict[str, Any]]:
    """Only conditions that actually block THIS workflow.

    Work remaining is not a blocker: an unmapped body is work, and saying so in
    the Blockers slot would make the word meaningless. A missing route is not a
    blocker while there is still work in this system — it becomes one only when
    continuing the route is the only remaining step.

    An unsupported fact is likewise not a blocker. PB05-08 emitted "Exobiology
    valuation: No Verified Source" as a blocker in all three of its branches; it
    impedes nothing, and it is carried as a caveat instead.
    """
    from omnicovas.features.operations_exploration import blocker_identity

    blockers: list[dict[str, Any]] = []

    if not available:
        blockers.append(
            {
                "blocker_id": blocker_identity(
                    "source_unavailable", "exploration_history"
                ),
                "label": "Local exploration history unavailable",
                "detail": (
                    "The flight recorder did not answer, so exploration "
                    "progress cannot be read."
                ),
                "kind": "source_unavailable",
                "source_id": None,
                "condition_id": "exploration_source",
            }
        )
        return blockers

    if not star_system:
        blockers.append(
            {
                "blocker_id": blocker_identity("source_unavailable", "current_system"),
                "label": "Current system unknown",
                "detail": (
                    "Local telemetry has not reported a system, so no "
                    "exploration work can be resolved."
                ),
                "kind": "source_unavailable",
                "source_id": None,
                "condition_id": "exploration_source",
            }
        )
        return blockers

    # The stage ladder already answers "is continuing the only step left?" —
    # that is exactly what `departure_ready` means. Deriving the blocker from
    # the same ladder keeps the two from ever disagreeing, which is how a
    # cockpit ends up saying "map this body" and "nothing remains" at once.
    if stage == STAGE_DEPARTURE_READY and not route_active:
        blockers.append(
            {
                "blocker_id": blocker_identity(
                    "no_route",
                    "navroute_not_loaded" if not navroute_loaded else "none_plotted",
                ),
                "label": (
                    "No active route"
                    + ("" if navroute_loaded else " — NavRoute.json not found")
                ),
                "detail": (
                    "No locally-known work remains here, so continuing needs a "
                    "route. Navigation owns route planning."
                ),
                "kind": "no_route",
                "source_id": "local_navroute",
                "condition_id": "exploration_route",
            }
        )

    return blockers


def derive_completion(
    *,
    star_system: str | None,
    available: bool,
    stage: str,
    system: dict[str, Any],
    work_remaining: list[dict[str, Any]],
) -> dict[str, Any]:
    """When is this workflow effectively finished?

    Never "Exploration complete". The strongest claim available is "no
    additional locally-known work detected", and even that is withheld when the
    coverage of what is known is itself unknown.

    Read off the same stage ladder that produced the current step, so the two
    can never contradict one another. A cockpit that names the next thing to do
    and simultaneously reports nothing left to do is worse than one that says
    neither.
    """
    if not available or not star_system:
        return {
            "state": COMPLETION_UNKNOWN_COVERAGE,
            "label": COMPLETION_LABELS[COMPLETION_UNKNOWN_COVERAGE],
            "reason": (
                "Exploration history unavailable."
                if not available
                else "Current system not reported by local telemetry."
            ),
        }

    if not system["body_count_known"]:
        return {
            "state": COMPLETION_UNKNOWN_COVERAGE,
            "label": COMPLETION_LABELS[COMPLETION_UNKNOWN_COVERAGE],
            "reason": (
                "No system survey recorded here, so the number of bodies is "
                "Unknown and completeness cannot be judged."
            ),
        }

    if stage != STAGE_DEPARTURE_READY:
        proven = [item for item in work_remaining if item["kind"] == WORK_KIND_WORK]
        opportunities = [
            item for item in work_remaining if item["kind"] == WORK_KIND_OPPORTUNITY
        ]
        # Proven work is named first when there is any; otherwise the reason
        # says outright that what remains rests on an estimate or a prediction,
        # so "work remaining" is never read as a hard fact it is not.
        if proven:
            reason = proven[0]["label"] + "."
        elif opportunities:
            reason = (
                opportunities[0]["label"]
                + " — from an estimate or prediction, not proven work."
            )
        else:
            reason = "This exploration stage has work outstanding."
        return {
            "state": COMPLETION_WORK_REMAINING,
            "label": COMPLETION_LABELS[COMPLETION_WORK_REMAINING],
            "reason": reason,
        }

    remaining_opportunities = [
        item for item in work_remaining if item["kind"] == WORK_KIND_OPPORTUNITY
    ]
    if remaining_opportunities:
        return {
            "state": COMPLETION_NO_KNOWN_WORK,
            "label": COMPLETION_LABELS[COMPLETION_NO_KNOWN_WORK],
            "reason": (
                f"{len(remaining_opportunities)} opportunit"
                f"{'y' if len(remaining_opportunities) == 1 else 'ies'} remain "
                "from estimates and predictions, which are not proven work."
            ),
        }

    return {
        "state": COMPLETION_NO_KNOWN_WORK,
        "label": COMPLETION_LABELS[COMPLETION_NO_KNOWN_WORK],
        "reason": (
            f"Survey complete in {star_system} with no outstanding mapping or "
            "biology recorded."
        ),
    }


# ---------------------------------------------------------------------------
# Value
# ---------------------------------------------------------------------------


def derive_value(
    *, bodies_payload: dict[str, Any], earnings_payload: dict[str, Any]
) -> dict[str, Any]:
    """Four separate columns that must never be summed together.

    Credits received, an estimate of what scans here might fetch, an estimate of
    biology value, and unknown. Adding an estimate to an earning turns a guess
    into an account balance, so each keeps its own field and its own label.
    """
    summary = bodies_payload.get("value_estimate_summary") or {}
    exploration = earnings_payload.get("exploration") or {}
    exobiology = earnings_payload.get("exobiology") or {}
    return {
        "actual_earnings": {
            # None means no sale was ever recorded — which is not the same claim
            # as "sold for nothing".
            "exploration_credits": exploration.get("credits_earned"),
            "exobiology_credits": exobiology.get("credits_earned"),
            "sales_recorded": int(exploration.get("sales_recorded") or 0)
            + int(exobiology.get("sales_recorded") or 0),
            "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
            "label": "Credits received",
        },
        "estimated_scan_value": {
            "estimated_low": summary.get("estimated_low_total"),
            "estimated_high": summary.get("estimated_high_total"),
            "bodies_valued": int(summary.get("bodies_valued") or 0),
            "bodies_unvalued": int(summary.get("bodies_unvalued") or 0),
            "is_estimate": True,
            "truth_class": TRUTH_KNOWLEDGE_REFERENCE,
            "label": "Estimated scan value (not earned)",
        },
        "estimated_biology_value": {
            "estimated_low": None,
            "estimated_high": None,
            "is_estimate": True,
            "truth_class": None,
            "label": "Estimated exobiology value",
            "unavailable_reason": (
                "Exobiology valuation has no verified source and no provider is "
                "enabled, so no estimate is offered."
            ),
        },
        "unknown": [
            "Exobiology valuation: No Verified Source.",
            "Bodies whose class was never recorded carry no estimate.",
        ],
    }


# ---------------------------------------------------------------------------
# Handoffs
# ---------------------------------------------------------------------------


def derive_handoffs(
    *,
    star_system: str | None,
    step: dict[str, Any] | None,
    biology: dict[str, Any],
) -> list[dict[str, Any]]:
    """Where to go for the detail Operations refuses to duplicate.

    Each carries the stable context the target needs to land on the right thing:
    a route, a section the target actually renders, and the entity in question.
    Nothing here is Commander-authored text, and nothing leaves the machine.
    """
    handoffs: list[dict[str, Any]] = [
        {
            "id": "intel_system",
            "label": "Review system in Intel",
            "route": "/intel",
            "section_id": "intel-exploration-card",
            "entity_id": star_system,
            "reason": "Intel owns the system and body record.",
        }
    ]

    if biology["bodies_with_signals"]:
        body = None
        if step and step.get("target_kind") == "body":
            body = step.get("target")
        handoffs.append(
            {
                "id": "intel_biology",
                "label": "Review biology in Intel",
                "route": "/intel",
                "section_id": "intel-biology-card",
                "entity_id": body or star_system,
                "reason": "Intel owns observed genera and candidate predictions.",
            }
        )

    handoffs.append(
        {
            "id": "intel_value",
            "label": "Review exploration value in Intel",
            "route": "/intel",
            "section_id": "intel-exploration-earnings",
            "entity_id": star_system,
            "reason": "Intel owns earnings and value estimates.",
        }
    )
    handoffs.append(
        {
            "id": "navigation_route",
            "label": "Plot next route in Navigation",
            "route": "/navigation",
            "section_id": "navigation-current-route",
            "entity_id": None,
            "reason": "Navigation owns route planning.",
        }
    )
    handoffs.append(
        {
            "id": "activity_log",
            "label": "Open Activity Log",
            "route": "/activity-log",
            # No landing section: the Activity Log is the proof record as a
            # whole, and naming a section it does not render would produce an
            # arrival banner pointing at nothing.
            "section_id": None,
            "entity_id": None,
            "reason": "Activity Log owns the proof record.",
        }
    )
    return handoffs


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def unavailable_workflow(reason: str) -> dict[str, Any]:
    """An honest 'I could not read this' — never an empty exploration."""
    return {
        "available": False,
        "star_system": None,
        "star_system_known": False,
        "stage": STAGE_UNKNOWN,
        "stage_label": STAGE_LABELS[STAGE_UNKNOWN],
        "stage_detail": reason,
        "step": None,
        "progress": None,
        "checklist": [],
        "work_remaining": [
            {
                "id": "work.unknown.unavailable",
                "label": "Work remaining unknown",
                "detail": reason,
                "kind": WORK_KIND_UNKNOWN,
            }
        ],
        "blockers": derive_blockers(
            star_system=None,
            available=False,
            stage=STAGE_UNKNOWN,
            route_active=False,
            navroute_loaded=False,
        ),
        "value": None,
        "completion": {
            "state": COMPLETION_UNKNOWN_COVERAGE,
            "label": COMPLETION_LABELS[COMPLETION_UNKNOWN_COVERAGE],
            "reason": reason,
        },
        "debrief_facts": None,
        "handoffs": derive_handoffs(
            star_system=None,
            step=None,
            biology={"bodies_with_signals": 0},
        ),
        "caveat": UNAVAILABLE_CAVEAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


async def build_workflow(
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    star_system: str | None,
    route_destination: str | None,
    route_active: bool,
    navroute_loaded: bool,
) -> dict[str, Any]:
    """Compose the Operations exploration workflow from local facts only."""
    if session_factory is None:
        return unavailable_workflow(
            "Local exploration history is not wired in this session."
        )

    try:
        facts = await _gather(session_factory, star_system)
    except Exception:  # noqa: BLE001 - a read failure is Unknown, not "no work"
        return unavailable_workflow("The local exploration history could not be read.")

    record = facts["record"]
    system = _system_progress(record)
    mapping = _mapping_progress(record, facts["bodies"])
    biology = _biology_progress(facts["biology"])
    footfall = _footfall_progress(record)
    value = derive_value(
        bodies_payload=facts["bodies"], earnings_payload=facts["earnings"]
    )

    stage, stage_detail = derive_stage(
        star_system=star_system,
        system=system,
        mapping=mapping,
        biology=biology,
        route_active=route_active,
        route_destination=route_destination,
    )
    step = derive_step(
        stage=stage,
        star_system=star_system,
        system=system,
        mapping=mapping,
        biology=biology,
        route_destination=route_destination,
    )
    work_remaining = derive_work_remaining(
        star_system=star_system, system=system, mapping=mapping, biology=biology
    )
    completion = derive_completion(
        star_system=star_system,
        available=True,
        stage=stage,
        system=system,
        work_remaining=work_remaining,
    )
    blockers = derive_blockers(
        star_system=star_system,
        available=True,
        stage=stage,
        route_active=route_active,
        navroute_loaded=navroute_loaded,
    )
    checklist = derive_checklist(
        star_system=star_system,
        system=system,
        mapping=mapping,
        biology=biology,
        sample_stages=_sample_stages(facts["biology"]),
    )

    return {
        "available": True,
        "star_system": star_system,
        "star_system_known": bool(star_system),
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "stage_detail": stage_detail,
        "step": step,
        "progress": {
            "system": system,
            "mapping": mapping,
            "biology": biology,
            "footfall": footfall,
            "route": {
                "destination": route_destination,
                "active": route_active,
                "navroute_loaded": navroute_loaded,
            },
        },
        "checklist": checklist,
        "work_remaining": work_remaining,
        "blockers": blockers,
        "value": value,
        "completion": completion,
        # R5-14: the facts a debrief will need, recorded now so R9 can build the
        # mature loop over them. Deliberately a small summary, not a proof dump.
        "debrief_facts": {
            "star_system": star_system,
            "bodies_scanned": system["bodies_scanned"],
            "bodies_surface_mapped": mapping["bodies_surface_mapped"],
            "first_discoveries": system["first_discoveries"],
            "genera_observed": biology["genera_observed"],
            "species_sampled": biology["species_sampled"],
            "species_analysed": biology["species_analysed"],
            "estimated_scan_value_high": value["estimated_scan_value"][
                "estimated_high"
            ],
            "exploration_credits_earned": value["actual_earnings"][
                "exploration_credits"
            ],
            "exobiology_credits_earned": value["actual_earnings"]["exobiology_credits"],
            "first_footfall": footfall["first_footfall"],
        },
        "handoffs": derive_handoffs(
            star_system=star_system, step=step, biology=biology
        ),
        "caveat": WORKFLOW_CAVEAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
