"""Species-level exobiology occurrence prediction, evaluated branch by branch.

The single mechanical source for "could this body hold that species". It reads one
structured ruleset — `omnicovas/data/exobiology_species_ruleset.json`, an exact copy
of the independently verified branch-accurate research dataset — and evaluates each of
its 91 species against the facts the journal recorded for a body.

Occurrence is OR-of-AND. A species carries one or more **rule branches**; each branch
is a set of predicates that hold *together*, and the species occurs where at least one
whole branch is satisfied:

    species MATCH          at least one branch matched
    species NO_MATCH       every branch has a definitively violated predicate
    species INDETERMINATE  no branch matched, but at least one is still possible
                           because a required fact, or the rule itself, is missing

That structure is not decoration. Osseus Discus occurs on Icy-adjacent bodies under
Argon *and* on Rocky bodies under Methane, at different gravities and temperatures.
Unioning those into species-wide arrays admits Argon on a Rocky body at the Methane
branch's gravity — a combination no source rule allows. The previous flattened
representation did exactly that, for 15 species and 67 body/atmosphere pairs, while
simultaneously excluding 34 pairs that are real. Branches remove both errors.

INDETERMINATE never becomes MATCH. A species gated on galactic region is not a
candidate just because OmniCOVAS cannot see galactic region. Exclusion still outranks
ignorance: a branch definitively outside its gravity band is closed even if its region
is unknowable, because one violated predicate settles that branch.

A falsified predicate is not an exclusion. Where a confirmed observation has proved a
bound wrong, the bound is degraded to UNKNOWN and the canonical value is kept for
provenance — in the dataset for counterexamples documented in tracked evidence, and at
runtime via a safety overlay for contradictions found in this Commander's own
telemetry. See `omnicovas.features.exobiology_sentinel`.

These are community-derived empirical occurrence mechanics, not Frontier-published
spawn rules, and a match means candidate — never confirmed presence. Observed journal
and DSS biology always outranks anything here.

See: evidence/research/exobiology-ruleset-20260817/
     EXOBIOLOGY_BRANCH_RULESET_VERIFICATION.md
     EXOBIOLOGY_KNOWN_COUNTEREXAMPLES.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Final

MATCH: Final = "MATCH"
NO_MATCH: Final = "NO_MATCH"
INDETERMINATE: Final = "INDETERMINATE"

UNKNOWN: Final = "UNKNOWN"
UNRESTRICTED: Final = "UNRESTRICTED"
NOT_APPLICABLE: Final = "NOT_APPLICABLE"

#: The exact verified dataset this module was built against. Asserted by test, so the
#: production copy cannot drift from the verified research artifact unnoticed.
#: Changing the data means re-running the audit/verification cycle and updating this
#: constant deliberately.
RULESET_SHA256: Final = (
    "aff9f50ea7de488fca85a3f93027e6753e59968e40ed6897860cdfa7f366b9e4"
)

RULESET_PATH: Final = (
    Path(__file__).resolve().parent.parent / "data" / "exobiology_species_ruleset.json"
)

PASCALS_PER_ATM: Final = 101325.0

#: The journal reports SurfaceGravity in m/s^2. Every gravity rule is in Earth-g, so
#: the raw field must be divided before comparison — treating it as g overstates
#: gravity roughly tenfold, which is how a 0.0596 g body came to be read as 0.5848 g.
METRES_PER_SECOND_SQUARED_PER_G: Final = 9.80665

# Journal PlanetClass to the dataset's body-type vocabulary. Matched by exact token
# rather than substring: "rocky" is a substring of "Rocky ice body", so a substring
# test would quietly qualify every rocky-ice body for every rocky-only species.
_BODY_CLASSES: Final[tuple[tuple[str, str], ...]] = (
    ("high metal content", "high metal content"),
    ("rocky ice", "rocky ice"),
    ("metal rich", "metal rich"),
    ("rocky", "rocky"),
    ("icy", "icy"),
)

# Thickness and temperature qualifiers the journal prefixes onto an atmosphere. They
# describe the same gas, so they are stripped before comparison.
_ATMOSPHERE_QUALIFIERS: Final[tuple[str, ...]] = (
    "hot thick",
    "hot thin",
    "very thin",
    "very thick",
    "thick",
    "thin",
    "hot",
)

# Volcanism intensity words. Branch rules record the material, sometimes qualified by
# intensity; the journal records intensity plus material.
_VOLCANISM_INTENSITY: Final[tuple[str, ...]] = ("major", "minor")

# Splits "SulphurDioxide" into "Sulphur Dioxide". Matches the seam between a lowercase
# character and the uppercase one that follows it, which is the only boundary Elite's
# AtmosphereType tokens use.
_CAMEL_BOUNDARY: Final[re.Pattern[str]] = re.compile(r"(?<=[a-z])(?=[A-Z])")

_cache: dict[str, Any] | None = None


def load_ruleset() -> dict[str, Any]:
    """Load and cache the canonical species ruleset."""
    global _cache
    if _cache is None:
        with open(RULESET_PATH, encoding="utf-8") as handle:
            loaded: dict[str, Any] = json.load(handle)
        _cache = loaded
    return _cache


def species_records() -> list[dict[str, Any]]:
    """Every species record in the canonical ruleset."""
    records: list[dict[str, Any]] = load_ruleset()["species"]
    return records


def ruleset_version() -> str:
    """Version string of the canonical ruleset, recorded against every evaluation."""
    version: str = load_ruleset()["ruleset_version"]
    return version


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def body_class_token(planet_class: Any) -> str | None:
    """Reduce a journal PlanetClass to the dataset's body-type vocabulary."""
    raw = _text(planet_class)
    if not raw:
        return None
    for needle, token in _BODY_CLASSES:
        if needle in raw:
            return token
    return raw.replace(" body", "").strip() or None


def atmosphere_token(atmosphere: Any) -> str | None:
    """Reduce a journal Atmosphere to the dataset's atmosphere vocabulary.

    Handles both spellings Elite uses for the same gas: the prose `Atmosphere`
    ("thin sulphur dioxide atmosphere") and the token `AtmosphereType`
    ("SulphurDioxide"). The second is split on its case boundaries first, or it would
    reduce to "sulphurdioxide" and match nothing.

    Returns "" for a body the journal positively describes as having no atmosphere —
    a fact, distinct from None, which means nothing was recorded.
    """
    raw = _text(_CAMEL_BOUNDARY.sub(" ", str(atmosphere or "")))
    if not raw:
        return None
    raw = raw.replace(" atmosphere", "").strip()
    if not raw or raw in ("none", "no"):
        return ""
    for qualifier in _ATMOSPHERE_QUALIFIERS:
        if raw.startswith(f"{qualifier} "):
            raw = raw[len(qualifier) + 1 :]
            break
    # The journal writes "argon rich"; the dataset writes "argon-rich".
    return raw.replace(" rich", "-rich").strip()


def _component_token(name: Any) -> str:
    """Normalise an atmospheric component name from either spelling."""
    return _text(_CAMEL_BOUNDARY.sub(" ", str(name or "")))


def _categorical(rule: Any, token: str | None) -> bool | None:
    """Test a fact against a categorical branch predicate.

    UNRESTRICTED states no constraint and is satisfied. UNKNOWN states a requirement
    whose content was never established, so it is undecidable — never satisfied.
    """
    if rule == UNRESTRICTED or rule == NOT_APPLICABLE:
        return True
    if not isinstance(rule, list):
        return None
    if token is None:
        return None
    return token in rule


def _bound(value: float | None, bounds: Any) -> bool | None:
    """Test a numeric fact against a {min, max} branch rule.

    True satisfied, False violated, None not decidable. An UNKNOWN on one end of a
    real bound is simply an open end, not an undecidable rule; a bound that is UNKNOWN
    at both ends states no constraint at all.
    """
    if not isinstance(bounds, dict):
        return True
    raw_low = bounds.get("min")
    raw_high = bounds.get("max")
    low = float(raw_low) if isinstance(raw_low, (int, float)) else None
    high = float(raw_high) if isinstance(raw_high, (int, float)) else None
    if low is None and high is None:
        return True
    if value is None:
        return None
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True


def _volcanism_material(volcanism: str) -> str:
    text = volcanism.replace(" volcanism", "")
    for word in _VOLCANISM_INTENSITY:
        text = text.replace(f"{word} ", "")
    return text.strip()


def _check_volcanism(rule: Any, volcanism: Any) -> bool | None:
    """Volcanism gating for one branch.

    Elite writes an empty Volcanism string for a body it scanned and found
    non-volcanic, so "" is a recorded fact meaning none — distinct from None, which
    means the body was never scanned for it.
    """
    if not isinstance(rule, dict):
        return True
    relationship = rule.get("relationship")
    if relationship in (UNKNOWN, UNRESTRICTED, NOT_APPLICABLE):
        # The branch states no volcanism requirement, so it cannot exclude a body.
        return True
    if volcanism is None:
        return None
    observed = _text(volcanism)
    none_observed = not observed or "no volcanism" in observed
    if relationship == "excluded":
        return none_observed
    if relationship in ("required_any", "required_material"):
        if none_observed:
            return False
        required = [_text(r) for r in rule.get("required_materials") or []]
        if not required:
            return True
        material = _volcanism_material(observed)
        return any(item in material or material in item for item in required)
    return True


def _check_star(rule: Any, star_class: Any) -> bool | None:
    """Parent-star gating for one branch."""
    if not isinstance(rule, list) or not rule:
        return True
    accepted = {_text(entry) for entry in rule}
    observed = _text(star_class)
    if not observed:
        return None
    # Journal star codes against the dataset's class letters.
    return observed in accepted


def _check_atmosphere_components(rule: Any, components: Any) -> bool | None:
    """Minimum-percentage gating on a named atmospheric component."""
    if not isinstance(rule, dict):
        return True
    if components is None:
        return None
    # The journal names components in the same CamelCase the atmosphere type uses
    # ("SulphurDioxide"), so both sides go through the same normalisation or the
    # gate silently never matches.
    observed = {_component_token(name): pct for name, pct in (components or {}).items()}
    for name, spec in rule.items():
        minimum = spec.get("min_pct") if isinstance(spec, dict) else None
        if not isinstance(minimum, (int, float)):
            continue
        present = observed.get(_component_token(name))
        if present is None:
            return False
        if float(present) < float(minimum):
            return False
    return True


def _gates_on(value: Any) -> bool:
    """True when a field states a real constraint rather than a non-gate."""
    return value not in (UNKNOWN, UNRESTRICTED, NOT_APPLICABLE)


def _apply_overlay(
    branch: dict[str, Any], overlay: dict[str, set[str]] | None, species_id: str
) -> dict[str, Any]:
    """Degrade locally falsified predicates on one branch to UNKNOWN.

    The canonical branch is never mutated. A predicate a confirmed observation has
    proved wrong must stop producing exclusions, but it must not be replaced by the
    observed value either, so it becomes UNKNOWN — an open end, not a new bound.
    """
    keys = overlay.get(f"{species_id}:{branch['id']}") if overlay else None
    if not keys:
        return branch
    patched = dict(branch)
    for key in keys:
        field, _, end = key.partition(".")
        if field not in patched:
            continue
        if end and isinstance(patched[field], dict):
            patched[field] = {**patched[field], end: UNKNOWN}
        else:
            patched[field] = UNKNOWN
    return patched


def evaluate_branch(branch: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one rule branch against one body's recorded facts.

    Every predicate in a branch is an AND. One violation closes the branch; one
    unevaluable predicate leaves it open but undecided.
    """
    violations: list[str] = []
    unevaluable: list[str] = []

    def judge(outcome: bool | None, label: str) -> None:
        if outcome is False:
            violations.append(label)
        elif outcome is None:
            unevaluable.append(label)

    judge(_categorical(branch["body_types"], facts.get("body_class")), "body type")
    judge(_categorical(branch["atmospheres"], facts.get("atmosphere")), "atmosphere")
    judge(
        _check_atmosphere_components(
            branch["atmosphere_components"], facts.get("atmosphere_components")
        ),
        "atmosphere composition",
    )
    judge(_bound(facts.get("temperature_k"), branch["temperature_k"]), "temperature")
    judge(_bound(facts.get("gravity_g"), branch["gravity_g"]), "gravity")
    judge(
        _bound(facts.get("pressure_atm"), branch["pressure_atm"]),
        "atmospheric pressure",
    )
    judge(
        _bound(
            facts.get("distance_from_arrival_ls"), branch["distance_from_arrival_ls"]
        ),
        "distance from arrival",
    )
    judge(_check_volcanism(branch["volcanism"], facts.get("volcanism")), "volcanism")
    judge(
        _check_star(branch["parent_star_classes"], facts.get("star_class")),
        "parent star class",
    )
    if _gates_on(branch["max_orbital_period_s"]):
        judge(
            _bound(
                facts.get("orbital_period_s"),
                {"min": UNKNOWN, "max": branch["max_orbital_period_s"]},
            ),
            "orbital period",
        )

    # Dimensions OmniCOVAS cannot observe locally. Where a branch is gated on one, the
    # branch stays undecided — never a match, and never invented.
    if _gates_on(branch["regions"]):
        unevaluable.append("galactic region")
    if _gates_on(branch["nebula_rule"]):
        unevaluable.append("nebula proximity")
    if _gates_on(branch["location_rule"]):
        unevaluable.append("location restriction")

    if violations:
        verdict = NO_MATCH
        reasons = violations
    elif unevaluable:
        verdict = INDETERMINATE
        reasons = unevaluable
    else:
        verdict = MATCH
        reasons = []
    return {"branch": branch["id"], "verdict": verdict, "reasons": reasons}


def evaluate_species(
    record: dict[str, Any],
    facts: dict[str, Any],
    overlay: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Evaluate one species against one body's recorded facts.

    MATCH as soon as any branch matches. NO_MATCH only when every branch is
    definitively closed. INDETERMINATE where nothing matched but something remains
    open, which is the state that keeps an unknown from becoming a candidate.
    """
    branch_results = [
        evaluate_branch(_apply_overlay(branch, overlay, record["id"]), facts)
        for branch in record["rule_branches"]
    ]

    matched = [r for r in branch_results if r["verdict"] == MATCH]
    open_branches = [r for r in branch_results if r["verdict"] == INDETERMINATE]

    if matched:
        verdict = MATCH
        reasons: list[str] = []
    elif open_branches:
        verdict = INDETERMINATE
        # Report the shortest set of missing facts; that is the nearest branch to a
        # decision and the most useful thing to tell a Commander.
        reasons = min((r["reasons"] for r in open_branches), key=len)
    else:
        verdict = NO_MATCH
        reasons = sorted({reason for r in branch_results for reason in r["reasons"]})

    return {
        "id": record["id"],
        "genus": record["genus"],
        "species": record["canonical_display_name"],
        "verdict": verdict,
        "reasons": reasons,
        "confidence": record["confidence"],
        "matched_branches": [r["branch"] for r in matched],
        "branch_verdicts": branch_results,
    }


def facts_from_body(body: dict[str, Any]) -> dict[str, Any]:
    """Normalise one body's recorded scan values into predicate inputs."""
    return {
        "body_class": body_class_token(body.get("planet_class")),
        "atmosphere": atmosphere_token(body.get("atmosphere")),
        "atmosphere_components": body.get("atmosphere_components"),
        "temperature_k": body.get("surface_temperature"),
        "gravity_g": body.get("surface_gravity_g"),
        "pressure_atm": body.get("surface_pressure_atm"),
        "volcanism": body.get("volcanism"),
        "star_class": body.get("parent_star_class"),
        "distance_from_arrival_ls": body.get("distance_from_arrival_ls"),
        "orbital_period_s": body.get("orbital_period_s"),
    }


def evaluate_body(
    body: dict[str, Any], overlay: dict[str, set[str]] | None = None
) -> dict[str, Any]:
    """Evaluate every species against one body.

    Candidate genera are derived from matching species only. A genus is never promoted
    on the strength of an INDETERMINATE species, because that would be exactly the
    "unknown became a finding" failure the three-state model exists to prevent.
    """
    if not body.get("landable"):
        # Odyssey surface biology is sampled on foot; an unlandable body is a
        # definitive exclusion, not a gap in the record.
        return {"matched": [], "indeterminate": [], "candidate_genera": []}

    facts = facts_from_body(body)
    matched: list[dict[str, Any]] = []
    indeterminate: list[dict[str, Any]] = []
    for record in species_records():
        result = evaluate_species(record, facts, overlay)
        if result["verdict"] == MATCH:
            matched.append(result)
        elif result["verdict"] == INDETERMINATE:
            indeterminate.append(result)

    genera: list[dict[str, Any]] = []
    for genus in sorted({row["genus"] for row in matched}):
        species = sorted(row["species"] for row in matched if row["genus"] == genus)
        genera.append(
            {
                "genus": genus,
                "basis": (
                    "recorded scan values matched to community-derived "
                    "species-level occurrence rules"
                ),
                "note": (
                    f"{len(species)} candidate species: {', '.join(species)}"
                    if species
                    else None
                ),
            }
        )
    return {
        "matched": matched,
        "indeterminate": indeterminate,
        "candidate_genera": genera,
    }


def ruleset_summary() -> dict[str, Any]:
    """Provenance of the ruleset backing prediction, for the API's basis block."""
    data = load_ruleset()
    return {
        "species_count": len(data["species"]),
        "genus_count": len({s["genus"] for s in data["species"]}),
        "rule_branch_count": sum(len(s["rule_branches"]) for s in data["species"]),
        "ruleset_version": data["ruleset_version"],
        "ruleset_sha256": RULESET_SHA256,
    }
