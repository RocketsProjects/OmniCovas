"""Exobiology Rule Sentinel — empirical contradiction detection from local telemetry.

The occurrence rules OmniCOVAS predicts from are community reconstructions, not
published mechanics. They are wrong in places, and the Commander's own journal is the
thing most likely to prove it.

A confirmed `ScanOrganic` proves the species **was there**, under whatever conditions
the journal recorded for that body. So when the rules say that body could not hold
that species, the rules lost. Telemetry defines live reality; a prediction never
outranks an observation.

What this is not: it is not a learner, and it is not an editor of canonical rules.
It draws exactly one inference, and it is the only one a single observation supports —
*this exclusion is false*. It never infers the replacement bound, never widens a
categorical set, and never writes to the shipped dataset.

Three classifications, taken at the moment of a confirmed observation:

    SUPPORTING_OBSERVATION   the rules said MATCH. The model held.
    NEW_EMPIRICAL_EVIDENCE   the rules said INDETERMINATE. The species can occur under
                             the recorded conditions, but the unresolved predicates
                             stay unresolved — this settles less than it looks like.
    RULE_CONTRADICTION       the rules said NO_MATCH. At least one exclusion predicate
                             is false or incomplete, and it is suspended locally.

The suspension is the safety half. A predicate a confirmed observation has falsified
must stop producing NO_MATCH locally, or OmniCOVAS keeps telling the Commander that
what they are standing on cannot exist. It degrades to UNKNOWN — an open end, never
the observed value, because a maximum observed value is not a maximum allowed value.
The canonical rule stays in the dataset, untouched, for provenance and review.

Everything here is local. No network, no upload, no external dependency.

See: evidence/research/exobiology-ruleset-20260817/
     EXOBIOLOGY_RULE_SENTINEL_DESIGN_AND_VERIFICATION.md
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.core.activity_log import ActivityEntry
from omnicovas.core.event_types import EXOBIOLOGY_RULE_CONTRADICTION_DETECTED
from omnicovas.db.models import ExobiologyRuleEvidence, JournalEvent
from omnicovas.features import exobiology_ruleset
from omnicovas.features.exobiology_ruleset import INDETERMINATE, MATCH, NO_MATCH

logger = logging.getLogger(__name__)

SUPPORTING_OBSERVATION: Final = "SUPPORTING_OBSERVATION"
NEW_EMPIRICAL_EVIDENCE: Final = "NEW_EMPIRICAL_EVIDENCE"
RULE_CONTRADICTION: Final = "RULE_CONTRADICTION"

REVIEW_OPEN: Final = "OPEN"
REVIEW_CORROBORATED: Final = "CORROBORATED"
REVIEW_UPDATE_PROPOSED: Final = "CANONICAL_UPDATE_PROPOSED"
REVIEW_REJECTED: Final = "REJECTED_BAD_EVIDENCE"
REVIEW_RESOLVED: Final = "RESOLVED"

#: The local state a falsified predicate carries until a human reviews it.
FALSIFIED_PENDING_REVIEW: Final = "FALSIFIED_PENDING_REVIEW"

SOURCE_LOCAL_JOURNAL: Final = "local_journal"

ORGANIC_SCAN_EVENTS: Final = ("ScanOrganic",)
BODY_SCAN_EVENTS: Final = ("Scan",)

#: Predicates the Sentinel is allowed to suspend. Confined on purpose: a numeric bound
#: is falsified by a single observation outside it, which is a sound inference. A
#: categorical set is not — one observation on an unlisted body class could equally
#: mean the species list is incomplete or that the observation is mis-associated, and
#: widening a category on that basis is exactly the silent rewrite this must not do.
SUSPENDABLE_PREDICATES: Final[frozenset[str]] = frozenset(
    {
        "gravity_g.min",
        "gravity_g.max",
        "temperature_k.min",
        "temperature_k.max",
        "pressure_atm.min",
        "pressure_atm.max",
        "distance_from_arrival_ls.min",
        "distance_from_arrival_ls.max",
    }
)

_REASON_TO_PREDICATE: Final[dict[str, str]] = {
    "gravity": "gravity_g",
    "temperature": "temperature_k",
    "atmospheric pressure": "pressure_atm",
    "distance from arrival": "distance_from_arrival_ls",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _localised(raw: str | None) -> str | None:
    """Turn '$Codex_Ent_Osseus_02_Name;' into something human when no _Localised."""
    if not raw:
        return None
    token = raw.strip().strip("$;")
    if not token.lower().startswith("codex_ent_"):
        return raw
    parts = [p for p in token.split("_") if p]
    meaningful = [p for p in parts[2:] if p.lower() not in ("genus", "name")]
    return " ".join(meaningful) or raw


def ruleset_fingerprint() -> tuple[str, str]:
    """Version and content hash of the ruleset that produced a verdict."""
    digest = hashlib.sha256(
        open(exobiology_ruleset.RULESET_PATH, "rb").read()
    ).hexdigest()
    return exobiology_ruleset.ruleset_version(), digest


def resolve_species(event: dict[str, Any]) -> dict[str, Any] | None:
    """Map a ScanOrganic event onto a species record.

    Matched on the codex identifier first. That token is what Elite actually writes and
    it is stable across localisations, so it is a far better key than a display name
    that differs between sources — the maintained rules call one species Unicus while
    Canonn calls it Unica, and a name match would miss it.
    """
    codex = _text(event.get("Species"))
    display = _text(event.get("Species_Localised") or _localised(event.get("Species")))
    by_codex: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for record in exobiology_ruleset.species_records():
        if isinstance(record.get("internal_codex_name"), str):
            by_codex[_text(record["internal_codex_name"])] = record
        by_name[_text(record["canonical_display_name"])] = record
    if codex and codex in by_codex:
        return by_codex[codex]
    if display and display in by_name:
        return by_name[display]
    return None


def body_facts_from_scan(scan: dict[str, Any]) -> dict[str, Any]:
    """Normalise a recorded Scan event into the body shape the evaluator reads."""
    facts: dict[str, Any] = {
        "planet_class": scan.get("PlanetClass"),
        "atmosphere": scan.get("AtmosphereType") or scan.get("Atmosphere"),
        "volcanism": scan.get("Volcanism"),
        "landable": bool(scan.get("Landable"))
        if scan.get("Landable") is not None
        else None,
    }
    if scan.get("AtmosphereComposition"):
        facts["atmosphere_components"] = {
            entry.get("Name"): entry.get("Percent")
            for entry in scan["AtmosphereComposition"]
            if entry.get("Name") is not None
        }
    if scan.get("SurfaceTemperature") is not None:
        facts["surface_temperature"] = float(scan["SurfaceTemperature"])
    if scan.get("SurfaceGravity") is not None:
        # The journal reports m/s^2; every rule is in Earth-g.
        facts["surface_gravity_g"] = (
            float(scan["SurfaceGravity"])
            / exobiology_ruleset.METRES_PER_SECOND_SQUARED_PER_G
        )
    if scan.get("SurfacePressure") is not None:
        facts["surface_pressure_atm"] = (
            float(scan["SurfacePressure"]) / exobiology_ruleset.PASCALS_PER_ATM
        )
    if scan.get("DistanceFromArrivalLS") is not None:
        facts["distance_from_arrival_ls"] = float(scan["DistanceFromArrivalLS"])
    if scan.get("OrbitalPeriod") is not None:
        facts["orbital_period_s"] = float(scan["OrbitalPeriod"])
    return facts


def _contradicted(
    record: dict[str, Any], facts: dict[str, Any]
) -> tuple[str | None, str | None]:
    """Find the single suspendable predicate standing between the body and a branch.

    Only a branch that fails on exactly one suspendable numeric bound is actionable.
    A branch failing on body class, or on two predicates at once, is not something one
    observation can repair — suspending a predicate there would be guesswork.
    """
    evaluation = exobiology_ruleset.evaluate_species(record, facts)
    for result in evaluation["branch_verdicts"]:
        if result["verdict"] != NO_MATCH or len(result["reasons"]) != 1:
            continue
        field = _REASON_TO_PREDICATE.get(result["reasons"][0])
        if field is None:
            continue
        branch = next(b for b in record["rule_branches"] if b["id"] == result["branch"])
        bounds = branch.get(field)
        if not isinstance(bounds, dict):
            continue
        value = {
            "gravity_g": facts.get("gravity_g"),
            "temperature_k": facts.get("temperature_k"),
            "pressure_atm": facts.get("pressure_atm"),
            "distance_from_arrival_ls": facts.get("distance_from_arrival_ls"),
        }[field]
        if value is None:
            continue
        low, high = bounds.get("min"), bounds.get("max")
        end = None
        if isinstance(high, (int, float)) and value > high:
            end = "max"
        elif isinstance(low, (int, float)) and value < low:
            end = "min"
        if end and f"{field}.{end}" in SUSPENDABLE_PREDICATES:
            return result["branch"], f"{field}.{end}"
    return None, None


def classify(record: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """Weigh one confirmed observation against the rules in force.

    The verdict recorded is the one the rules gave *before* the observation was taken
    into account, which is what makes the evidence meaningful later.
    """
    facts = exobiology_ruleset.facts_from_body(body)
    evaluation = exobiology_ruleset.evaluate_species(record, facts)
    verdict = evaluation["verdict"]

    if verdict == MATCH:
        classification = SUPPORTING_OBSERVATION
        branch, predicate = None, None
    elif verdict == INDETERMINATE:
        classification = NEW_EMPIRICAL_EVIDENCE
        branch, predicate = None, None
    else:
        classification = RULE_CONTRADICTION
        branch, predicate = _contradicted(record, facts)

    return {
        "classification": classification,
        "evaluation_before_observation": verdict,
        "contradicted_branch": branch,
        "contradicted_predicate": predicate,
        "facts": facts,
        "reasons": evaluation["reasons"],
    }


def build_overlay(rows: list[ExobiologyRuleEvidence]) -> dict[str, set[str]]:
    """Local safety overlay: suspended branch predicates, keyed species:branch.

    Only contradictions still awaiting or undergoing review suspend anything. Evidence
    a Commander rejected as bad, or that a later ruleset resolved, stops applying —
    but the row stays, because the history is the point.
    """
    overlay: dict[str, set[str]] = {}
    for row in rows:
        if row.classification != RULE_CONTRADICTION:
            continue
        if row.review_state in (REVIEW_REJECTED, REVIEW_RESOLVED):
            continue
        if not row.contradicted_branch or not row.contradicted_predicate:
            continue
        if row.contradicted_predicate not in SUSPENDABLE_PREDICATES:
            continue
        overlay.setdefault(f"{row.species_id}:{row.contradicted_branch}", set()).add(
            row.contradicted_predicate
        )
    return overlay


async def load_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[ExobiologyRuleEvidence]:
    """Every evidence row recorded under the ruleset currently in force.

    Scoped to the current ruleset hash on purpose. A contradiction recorded against an
    older ruleset must not suspend a predicate in a newer one that may already have
    fixed it; the old row survives as history and is simply no longer operative.
    """
    _, digest = ruleset_fingerprint()
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(ExobiologyRuleEvidence).where(
                    ExobiologyRuleEvidence.ruleset_sha256 == digest
                )
            )
        ).scalars()
        return list(rows)


async def active_overlay(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, set[str]]:
    """The safety overlay currently in force."""
    return build_overlay(await load_evidence(session_factory))


async def record_observation(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    event: dict[str, Any],
    body: dict[str, Any],
    activity_log: Any = None,
) -> dict[str, Any] | None:
    """Classify one confirmed ScanOrganic and persist the evidence.

    Returns a summary of what was recorded, or None where the species could not be
    resolved. Repeat scans of the same colony increment `observation_count` rather
    than filing a second finding, so the Activity Log is not flooded by the three
    samples Elite requires to complete one species.
    """
    record = resolve_species(event)
    if record is None:
        logger.debug("sentinel_species_unresolved species=%s", event.get("Species"))
        return None

    outcome = classify(record, body)
    version, digest = ruleset_fingerprint()
    now = _now()

    body_name = body.get("body_name") or event.get("Body_Localised")
    identity = (
        ExobiologyRuleEvidence.species_id == record["id"],
        ExobiologyRuleEvidence.body_name == body_name,
        ExobiologyRuleEvidence.contradicted_predicate
        == outcome["contradicted_predicate"],
        ExobiologyRuleEvidence.ruleset_sha256 == digest,
    )

    async with session_factory() as db:
        existing = (
            await db.execute(select(ExobiologyRuleEvidence).where(*identity))
        ).scalar_one_or_none()

        if existing is not None:
            existing.last_seen = now
            existing.observation_count += 1
            await db.commit()
            return {
                "classification": existing.classification,
                "species_id": existing.species_id,
                "new": False,
                "observation_count": existing.observation_count,
                "contradicted_predicate": existing.contradicted_predicate,
            }

        row = ExobiologyRuleEvidence(
            classification=outcome["classification"],
            review_state=(
                REVIEW_OPEN
                if outcome["classification"] == RULE_CONTRADICTION
                else REVIEW_RESOLVED
            ),
            species_id=record["id"],
            species_name=record["canonical_display_name"],
            genus=record["genus"],
            variant=event.get("Variant_Localised") or event.get("Variant"),
            star_system=body.get("star_system"),
            system_address=(
                str(event.get("SystemAddress"))
                if event.get("SystemAddress") is not None
                else None
            ),
            body_name=body_name,
            body_id=str(event.get("Body")) if event.get("Body") is not None else None,
            evaluation_before_observation=outcome["evaluation_before_observation"],
            contradicted_branch=outcome["contradicted_branch"],
            contradicted_predicate=outcome["contradicted_predicate"],
            observed_facts=json.dumps(outcome["facts"], sort_keys=True, default=str),
            ruleset_version=version,
            ruleset_sha256=digest,
            source=SOURCE_LOCAL_JOURNAL,
            first_seen=now,
            last_seen=now,
            observation_count=1,
        )
        db.add(row)
        await db.commit()

    if outcome["classification"] == RULE_CONTRADICTION and activity_log is not None:
        _log_contradiction(activity_log, record, outcome)

    return {
        "classification": outcome["classification"],
        "species_id": record["id"],
        "new": True,
        "observation_count": 1,
        "contradicted_predicate": outcome["contradicted_predicate"],
    }


def _log_contradiction(
    activity_log: Any, record: dict[str, Any], outcome: dict[str, Any]
) -> None:
    """Announce a newly detected contradiction once.

    Only newly recorded contradictions reach here; repeats increment a count and stay
    quiet. Supporting observations never announce at all — the model working as
    intended is not news.

    Logged as a fact, because it is one: the Commander scanned the organism and the
    journal recorded the body. The prediction is the part that was wrong.
    """
    predicate = outcome["contradicted_predicate"]
    detail = (
        f"exclusion on {predicate} suspended locally pending review"
        if predicate
        else "no single suspendable predicate identified; recorded for review"
    )
    activity_log.append(
        ActivityEntry(
            event_type=EXOBIOLOGY_RULE_CONTRADICTION_DETECTED,
            timestamp=_now().isoformat().replace("+00:00", "Z"),
            summary=(
                f"Exobiology rule contradiction detected: confirmed "
                f"{record['canonical_display_name']} observation exceeds the current "
                f"community-derived rules. Rule {detail}."
            ),
            payload={
                "species_id": record["id"],
                "genus": record["genus"],
                "contradicted_branch": outcome["contradicted_branch"],
                "contradicted_predicate": predicate,
                "predicate_state": FALSIFIED_PENDING_REVIEW,
                "canonical_dataset_modified": False,
                "source": SOURCE_LOCAL_JOURNAL,
            },
            is_fact=True,
            surface_origin="intel",
            source=SOURCE_LOCAL_JOURNAL,
        )
    )


def empirical_envelopes(
    rows: list[ExobiologyRuleEvidence],
) -> dict[str, dict[str, Any]]:
    """Observed ranges per species, from local evidence.

    These are OBSERVED ENVELOPES, not spawn limits. A maximum observed gravity is the
    highest this Commander has seen the species at — nothing more. The true bound is
    whatever it is, and stays UNKNOWN.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        try:
            facts = json.loads(row.observed_facts)
        except (TypeError, ValueError):
            continue
        bucket = out.setdefault(
            row.species_id,
            {
                "species": row.species_name,
                "observation_count": 0,
                "observed_body_classes": set(),
                "observed_atmospheres": set(),
                "_note": (
                    "OBSERVED ENVELOPE from local telemetry. Not a spawn limit. A "
                    "maximum observed value is not a maximum allowed value."
                ),
            },
        )
        bucket["observation_count"] += row.observation_count
        if facts.get("body_class"):
            bucket["observed_body_classes"].add(facts["body_class"])
        if facts.get("atmosphere"):
            bucket["observed_atmospheres"].add(facts["atmosphere"])
        for key, label in (
            ("gravity_g", "gravity_g"),
            ("temperature_k", "temperature_k"),
            ("pressure_atm", "pressure_atm"),
        ):
            value = facts.get(key)
            if not isinstance(value, (int, float)):
                continue
            lo = bucket.get(f"min_observed_{label}")
            hi = bucket.get(f"max_observed_{label}")
            bucket[f"min_observed_{label}"] = value if lo is None else min(lo, value)
            bucket[f"max_observed_{label}"] = value if hi is None else max(hi, value)
    for bucket in out.values():
        bucket["observed_body_classes"] = sorted(bucket["observed_body_classes"])
        bucket["observed_atmospheres"] = sorted(bucket["observed_atmospheres"])
    return out


async def diagnostics(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """Read-only Sentinel state, for the Intel basis block.

    Deliberately a summary. It answers "are the rules being contradicted, and where",
    not "here is the ruleset" — a rule dump does not belong on a Commander's screen.
    """
    version, digest = ruleset_fingerprint()
    rows = await load_evidence(session_factory)
    overlay = build_overlay(rows)
    contradictions = [r for r in rows if r.classification == RULE_CONTRADICTION]
    open_rows = [
        r
        for r in contradictions
        if r.review_state not in (REVIEW_REJECTED, REVIEW_RESOLVED)
    ]
    return {
        "ruleset_version": version,
        "ruleset_sha256": digest,
        "evidence_records": len(rows),
        "supporting_observations": sum(
            1 for r in rows if r.classification == SUPPORTING_OBSERVATION
        ),
        "new_empirical_evidence": sum(
            1 for r in rows if r.classification == NEW_EMPIRICAL_EVIDENCE
        ),
        "rule_contradictions": len(contradictions),
        "open_contradictions": len(open_rows),
        "suspended_predicates": sum(len(v) for v in overlay.values()),
        "affected_species": sorted({r.species_id for r in open_rows}),
        "predicate_state": FALSIFIED_PENDING_REVIEW if open_rows else None,
        "canonical_dataset_modified": False,
        "source": SOURCE_LOCAL_JOURNAL,
        "note": (
            "Contradictions are detected from this machine's own journal and stay on "
            "this machine. A falsified exclusion is suspended locally so it cannot "
            "produce false negatives; the canonical rule is preserved unchanged for "
            "review, and no bound is ever inferred from an observation."
        ),
    }


async def scan_recorded_history(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    activity_log: Any = None,
) -> dict[str, Any]:
    """Weigh every ScanOrganic already in the flight recorder against the rules.

    Used after a ruleset change, and to seed the store on first run. Re-evaluating
    under a new ruleset can resolve an old contradiction; the old row is left in place
    under its own ruleset hash rather than deleted, so the history of what was believed
    when survives the correction.
    """
    async with session_factory() as db:
        scan_rows = (
            await db.execute(
                select(JournalEvent.raw_json).where(
                    JournalEvent.event_type.in_(BODY_SCAN_EVENTS)
                )
            )
        ).all()
        organic_rows = (
            await db.execute(
                select(JournalEvent.raw_json)
                .where(JournalEvent.event_type.in_(ORGANIC_SCAN_EVENTS))
                .order_by(JournalEvent.timestamp.asc())
            )
        ).all()

    scans_by_name: dict[str, dict[str, Any]] = {}
    scans_by_id: dict[tuple[str, str], dict[str, Any]] = {}
    for row in scan_rows:
        try:
            event = json.loads(row.raw_json)
        except (TypeError, ValueError):
            continue
        if not event.get("BodyName"):
            continue
        scanned = body_facts_from_scan(event)
        scanned["body_name"] = event["BodyName"]
        scanned["star_system"] = event.get("StarSystem")
        scans_by_name[str(event["BodyName"])] = scanned
        if event.get("SystemAddress") is not None and event.get("BodyID") is not None:
            scans_by_id[(str(event["SystemAddress"]), str(event["BodyID"]))] = scanned

    counts: dict[str, int] = {"considered": 0, "unassociated": 0, "unresolved": 0}
    results: dict[str, int] = {}
    for row in organic_rows:
        try:
            event = json.loads(row.raw_json)
        except (TypeError, ValueError):
            continue
        counts["considered"] += 1
        # SystemAddress + Body is the reliable join; ScanOrganic carries a numeric body
        # id, not a name, so the name path is only a fallback.
        body: dict[str, Any] | None = None
        if event.get("SystemAddress") is not None and event.get("Body") is not None:
            body = scans_by_id.get((str(event["SystemAddress"]), str(event["Body"])))
        if body is None and event.get("Body_Localised"):
            body = scans_by_name.get(str(event["Body_Localised"]))
        if body is None:
            counts["unassociated"] += 1
            continue
        outcome = await record_observation(
            session_factory, event=event, body=body, activity_log=activity_log
        )
        if outcome is None:
            counts["unresolved"] += 1
            continue
        results[outcome["classification"]] = (
            results.get(outcome["classification"], 0) + 1
        )

    return {**counts, **results}


async def evidence_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> int:
    """Total evidence rows, across every ruleset version."""
    async with session_factory() as db:
        total = (
            await db.execute(select(func.count()).select_from(ExobiologyRuleEvidence))
        ).scalar_one()
        return int(total)
