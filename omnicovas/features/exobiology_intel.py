"""Exobiology intelligence — Phase 13 Intel exploration fact domain.

Fact first, candidate second. That ordering is the whole design.

After a DSS map Elite reports the biological signal **count** on a body
(`SAASignalsFound.Signals[]`) and, in Odyssey, the **genera present**
(`Genuses[]`). Those are observed facts. A tool that predicts a signal count
when the journal already reported one has thrown away a fact in favour of a
guess, so this module reads the journal first and only reaches for condition
matching where the journal is silent.

What is genuinely predictive — which species within a genus, and what a sample
is worth — is labelled a candidate or an estimate and sourced to a KB entry
carrying `needs_review`. Observed `SellOrganicData` values always outrank the
reference figure.

Derived from JournalEvent rows the recorder already stores. The one piece of
persistence in this domain belongs to the Rule Sentinel, which keeps evidence
about contradicted rules; see `omnicovas.features.exobiology_sentinel`. No
providers, and nothing here reaches the network.

See: knowledge_base/exobiology_mechanics.json
See: PB13-01 / PB13-02 planning scope
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import JournalEvent
from omnicovas.features import exobiology_ruleset, exobiology_sentinel

TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
TRUTH_KNOWLEDGE_REFERENCE = "knowledge_reference"
SOURCE_FLIGHT_RECORDER = "Local session database (flight recorder)"
KB_ENTRY_CONDITIONS = "exobiology_mechanics/genus_spawn_conditions"
#: Mirrors the `needs_review` flag on that KB entry. A test asserts the two
#: agree, so this cannot drift into claiming a review state the KB contradicts.
KB_ENTRY_NEEDS_REVIEW = False

SIGNALS_EVENTS = ("SAASignalsFound",)
ORGANIC_SCAN_EVENTS = ("ScanOrganic",)
BODY_SCAN_EVENTS = ("Scan",)

BIOLOGICAL_SIGNAL_TYPE = "biological"

DEFAULT_LIMIT = 100
MAX_LIMIT = 500

# Prediction is no longer expressed here. The flattened genus table and the
# universal 0.28g ceiling that used to live at this point were both falsified by
# the Phase 13 research and its independent audit: 23 of the 91 researched
# species exceed 0.28g, Stratum Tectonicas by more than double, and gating is
# species-level rather than genus-level. Both were retired rather than left
# dormant, so there is exactly one mechanical source of occurrence rules —
# omnicovas/data/exobiology_species_ruleset.json, evaluated by
# omnicovas.features.exobiology_ruleset.

_SIGNALS_CAVEAT = (
    "Biological signal counts and genera are read from recorded SAASignalsFound "
    "events — observed facts, not predictions. A body absent here has not been "
    "surface-mapped on this machine; that is not proof it holds no life."
)
_CANDIDATE_CAVEAT = (
    "Candidates are matched from the body's own recorded scan values against "
    "community-derived species-level occurrence rules (KB "
    "exobiology_mechanics/genus_spawn_conditions). They indicate where "
    "conditions look suitable — never that a species is present. A genus is "
    "offered only where at least one of its species satisfies every rule that "
    "could be checked; species whose rules depend on something this machine "
    "cannot observe are left undecided rather than counted as matches. Where "
    "the journal already reported genera for a body, those observed genera are "
    "shown instead and no prediction is made. Where this Commander's own "
    "confirmed samples have contradicted a rule, that rule stops excluding "
    "locally and is flagged for review rather than quietly rewritten."
)


def _clamp_limit(value: int | None, default: int, maximum: int) -> int:
    if value is None:
        return default
    return max(1, min(int(value), maximum))


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _localised(raw: str | None) -> str | None:
    """Turn '$Codex_Ent_Stratum_Genus;' into 'Stratum' when no _Localised."""
    if not raw:
        return None
    token = raw.strip().strip("$;")
    if not token.lower().startswith("codex_ent_"):
        return raw
    parts = [p for p in token.split("_") if p]
    # Codex Ent <Name> [Genus|Name]
    meaningful = [p for p in parts[2:] if p.lower() not in ("genus", "name")]
    return " ".join(meaningful) or raw


def _normalise(value: Any) -> str:
    return str(value or "").strip().lower()


def candidate_genera(
    body: dict[str, Any], overlay: dict[str, set[str]] | None = None
) -> list[dict[str, Any]]:
    """Candidate genera for one body, derived from matching species.

    A thin seam over the species ruleset, kept so existing callers and tests
    keep their entry point. Genera come only from species that returned MATCH;
    a species left INDETERMINATE never promotes its genus, so unknown does not
    become a positive finding (Law 5).

    The optional overlay carries predicates this Commander's own telemetry has
    falsified. A rule proved wrong must stop excluding, so those predicates are
    read as UNKNOWN rather than as bounds. It never adds a match on its own.
    """
    genera: list[dict[str, Any]] = exobiology_ruleset.evaluate_body(body, overlay)[
        "candidate_genera"
    ]
    return genera


async def biological_signals(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    star_system: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Bodies with observed biological signals, plus candidate genera.

    Observed signal counts and genera come first and are labelled fact.
    Candidates are only offered where the journal did not already name the
    genera present.
    """
    bounded_limit = _clamp_limit(limit, DEFAULT_LIMIT, MAX_LIMIT)

    # Predicates this Commander's own telemetry has falsified, and the Sentinel's
    # read-only state. Both derive from the local evidence store; neither reaches
    # the network, and neither alters the canonical ruleset.
    overlay = await exobiology_sentinel.active_overlay(session_factory)
    sentinel_state = await exobiology_sentinel.diagnostics(session_factory)

    async with session_factory() as db:
        conditions: list[Any] = [JournalEvent.event_type.in_(SIGNALS_EVENTS)]
        if star_system:
            conditions.append(
                func.json_extract(JournalEvent.raw_json, "$.StarSystem") == star_system
            )
        signal_rows = (
            await db.execute(
                select(JournalEvent.raw_json, JournalEvent.timestamp)
                .where(*conditions)
                .order_by(JournalEvent.timestamp.desc())
                .limit(bounded_limit)
            )
        ).all()

        scan_rows = (
            await db.execute(
                select(JournalEvent.raw_json).where(
                    JournalEvent.event_type.in_(BODY_SCAN_EVENTS)
                )
            )
        ).all()

        sampled_rows = (
            await db.execute(
                select(JournalEvent.raw_json).where(
                    JournalEvent.event_type.in_(ORGANIC_SCAN_EVENTS)
                )
            )
        ).all()

    # Primary star class per system, for star-gated genera. The primary is the
    # star scanned at zero arrival distance; where none was recorded the system
    # simply has no primary on file and star-gated genera are not offered.
    primary_star: dict[str, str] = {}
    for row in scan_rows:
        try:
            event = json.loads(row.raw_json)
        except (TypeError, ValueError):
            continue
        star_type = event.get("StarType")
        system = event.get("StarSystem")
        if not star_type or not system:
            continue
        distance = event.get("DistanceFromArrivalLS")
        if distance is not None and float(distance) > 0.0:
            continue
        primary_star.setdefault(str(system), str(star_type))

    # Latest recorded scan values per body, for condition matching.
    scans: dict[str, dict[str, Any]] = {}
    for row in scan_rows:
        try:
            event = json.loads(row.raw_json)
        except (TypeError, ValueError):
            continue
        name = event.get("BodyName")
        if not name:
            continue
        existing = scans.setdefault(name, {})
        for key, field in (
            ("planet_class", "PlanetClass"),
            ("atmosphere", "Atmosphere"),
            # Applied after Atmosphere so it wins where both exist. It is the token
            # the rules are written in, and for an airless body it says "None" where
            # Atmosphere says "" — a stated fact rather than an absent one.
            ("atmosphere", "AtmosphereType"),
            ("volcanism", "Volcanism"),
            ("star_system", "StarSystem"),
        ):
            if event.get(field) is not None:
                existing[key] = event[field]
        if event.get("AtmosphereComposition"):
            # Recepta is gated on a minimum sulphur dioxide fraction. The Scan event
            # already carries the breakdown, so reading it decides those species
            # instead of leaving them undecided on a fact the journal did supply.
            existing["atmosphere_components"] = {
                entry.get("Name"): entry.get("Percent")
                for entry in event["AtmosphereComposition"]
                if entry.get("Name") is not None
            }
        if event.get("SurfaceTemperature") is not None:
            existing["surface_temperature"] = event["SurfaceTemperature"]
        if event.get("SurfaceGravity") is not None:
            # Journal reports m/s^2 scaled; Elite's SurfaceGravity is in m/s^2.
            existing["surface_gravity_g"] = round(
                float(event["SurfaceGravity"]) / 9.80665, 3
            )
        if event.get("SurfacePressure") is not None:
            # Elite reports pressure in pascals; the ruleset is in atmospheres.
            # Already present on the Scan event, so this is a unit conversion on
            # a local fact rather than a new source of data.
            existing["surface_pressure_atm"] = (
                float(event["SurfacePressure"]) / exobiology_ruleset.PASCALS_PER_ATM
            )
        if event.get("DistanceFromArrivalLS") is not None:
            # Already read below to identify the primary star; kept per body
            # because one species carries a real distance-from-arrival gate.
            existing["distance_from_arrival_ls"] = float(event["DistanceFromArrivalLS"])
        if event.get("Landable") is not None:
            existing["landable"] = bool(event["Landable"])

    # Every species this Commander has ever logged on this machine, and the
    # Log/Sample/Analyse progress per body. Both are facts drawn from the
    # Commander's own history — no reference data, no prediction. "Have I
    # logged this before?" is the question that decides whether a landing is
    # worth the time, and the recorder can answer it outright.
    sampled_species: dict[str, set[str]] = {}
    species_ever_logged: set[str] = set()
    sample_progress: dict[tuple[str, str], set[str]] = {}
    for row in sampled_rows:
        try:
            event = json.loads(row.raw_json)
        except (TypeError, ValueError):
            continue
        species = event.get("Species_Localised") or _localised(event.get("Species"))
        body = event.get("Body_Localised") or event.get("BodyName")
        if not species:
            continue
        species = str(species)
        species_ever_logged.add(species)
        sampled_species.setdefault(str(body or ""), set()).add(species)
        scan_type = _normalise(event.get("ScanType"))
        if scan_type:
            sample_progress.setdefault((str(body or ""), species), set()).add(scan_type)

    bodies: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signal_row in signal_rows:
        try:
            event = json.loads(signal_row.raw_json)
        except (TypeError, ValueError):
            continue
        body_name = event.get("BodyName")
        if not body_name or body_name in seen:
            continue
        seen.add(body_name)

        bio_count: int | None = None
        for signal in event.get("Signals") or []:
            if BIOLOGICAL_SIGNAL_TYPE in _normalise(signal.get("Type")):
                bio_count = int(signal.get("Count") or 0)
                break
        if bio_count is None:
            continue

        observed_genera = [
            _localised(entry.get("Genus_Localised") or entry.get("Genus"))
            for entry in (event.get("Genuses") or [])
        ]
        observed_genera = [g for g in observed_genera if g]

        scan = dict(scans.get(body_name, {}))
        system_name = event.get("StarSystem") or scan.get("star_system")
        if system_name and system_name in primary_star:
            scan["parent_star_class"] = primary_star[str(system_name)]
        # Only predict where the journal did not already answer.
        candidates = [] if observed_genera else candidate_genera(scan, overlay)

        # First-logged opportunity: a genus named here that this Commander has
        # never logged any species from. Derived from their own ScanOrganic
        # history, so it is a fact about this machine's record — not a claim
        # about the galaxy, and never about who logged it first overall.
        named_genera = observed_genera or [c["genus"] for c in candidates]
        unlogged = [
            genus
            for genus in named_genera
            if not any(_normalise(genus) in _normalise(s) for s in species_ever_logged)
        ]

        sampling = [
            {
                "species": species,
                "stages_recorded": sorted(stages),
                # Elite needs three samples; Analyse closes it out.
                "analysed": "analyse" in stages,
            }
            for (body, species), stages in sorted(sample_progress.items())
            if body == body_name
        ]

        bodies.append(
            {
                "body_name": body_name,
                "star_system": event.get("StarSystem") or scan.get("star_system"),
                "biological_signal_count": bio_count,
                "observed_genera": observed_genera,
                "genera_observed": bool(observed_genera),
                "candidate_genera": candidates,
                "species_sampled_here": sorted(sampled_species.get(body_name, set())),
                "sampling_progress": sampling,
                # Genera named here that this Commander has never logged.
                "genera_never_logged_by_commander": unlogged,
                "planet_class": scan.get("planet_class"),
                "atmosphere": scan.get("atmosphere"),
                "surface_temperature": scan.get("surface_temperature"),
                "surface_gravity_g": scan.get("surface_gravity_g"),
                "landable": scan.get("landable"),
                "parent_star_class": scan.get("parent_star_class"),
                "signals_recorded_at": _iso_or_none(signal_row.timestamp),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": f"{_SIGNALS_CAVEAT} {_CANDIDATE_CAVEAT}",
        "candidate_basis": {
            "truth_class": TRUTH_KNOWLEDGE_REFERENCE,
            "kb_entry": KB_ENTRY_CONDITIONS,
            "needs_review": KB_ENTRY_NEEDS_REVIEW,
            **exobiology_ruleset.ruleset_summary(),
            "sentinel": sentinel_state,
        },
        "source_events": [*SIGNALS_EVENTS, *BODY_SCAN_EVENTS, *ORGANIC_SCAN_EVENTS],
        "star_system": star_system,
        "returned": len(bodies),
        "limit": bounded_limit,
        "bodies": bodies,
        "nullprovider_safe": True,
    }
