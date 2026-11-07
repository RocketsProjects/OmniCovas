"""Independent exobiology evidence: ranking species from recorded journal sightings.

What this is. A compact aggregate of **positive** sightings: how many distinct bodies
each of 91 species was confirmed on, grouped by the planet class, atmosphere and a
10 K surface-temperature band that the game itself recorded for those bodies. It was
compiled for OmniCOVAS from Frontier journal events (``Scan``, ``ScanOrganic``,
``CodexEntry``, ``SAASignalsFound``) relayed by EDDN and archived by EDGalaxyData. It
holds no commander identities, no system or body identifiers and no raw messages.

What this is not. It is not a set of spawn rules and carries no thresholds or
exclusions. A species never seen under some conditions in the sample is **not** ruled
out there; it simply has less evidence. Counts describe where confirmed sightings
happened, not the probability of finding a species on an arbitrary planet. No
occurrence content from the legacy ruleset, EDMC-BioScan or any other prediction table
was used to build or tune it.

How it is used.

* Before the game names genera, suggestions are *preliminary*: genera and species
  that have been confirmed on bodies with the same recorded conditions.
* After ``SAASignalsFound`` names a genus, that genus is fact. Every species of the
  genus stays a candidate; they are ordered by same-temperature-band sightings, then
  same planet/atmosphere sightings, then genus-wide sightings.
* ``ScanOrganic`` is proof and always outranks any suggestion (handled by the caller).

Validation (research pack, 2026-11-07): with the genus known, the confirmed species
was in the top three suggestions for 99.19% (5,414/5,458) and 99.34% (2,727/2,745) of
out-of-period positive holdouts. That is identification recall among real discoveries,
not a spawn probability.

Everything here is offline and deterministic: standard library only, no network.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

SCHEMA: Final = "omnicovas-positive-journal-evidence-v1"
TEMPERATURE_BAND_K: Final = 10

ASSET_PATH: Final = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "exobiology_journal_evidence_v1.json"
)

#: Hash of the asset as delivered by the FU-021 research pack. A test asserts the
#: shipped copy still matches, so a data change is a deliberate, recorded act.
ASSET_SHA256: Final = "1589c19912ffb2a5dcbaceee5c9a55cb46f83e8705f810b031fe94a250b6384e"

#: Fewer distinct bodies than this and a species carries a sparse-evidence warning.
SPARSE_BODY_THRESHOLD: Final = 10

#: How many ranked species are presented as the strongest suggestions. Three is the
#: depth the out-of-period validation measured; the rest stay available.
SUGGESTION_DEPTH: Final = 3

STRENGTH_STRONG: Final = "strong"
STRENGTH_MODERATE: Final = "moderate"
STRENGTH_LIMITED: Final = "limited"
STRENGTH_GENUS_ONLY: Final = "genus_only"
STRENGTH_NONE: Final = "none"

BASIS_TEMPERATURE: Final = "temperature_band"
BASIS_PLANET_ATMOSPHERE: Final = "planet_atmosphere"
BASIS_GENUS_WIDE: Final = "genus_wide"

STATE_AVAILABLE: Final = "available"
STATE_UNAVAILABLE: Final = "unavailable"
REASON_NOT_INCLUDED: Final = "not_included"
REASON_INVALID: Final = "invalid"

SOURCE_ATTRIBUTION: Final = (
    "Independent aggregate of positive sightings compiled for OmniCOVAS from "
    "Frontier Elite Dangerous journal events relayed by the Elite Dangerous Data "
    "Network (EDDN) and archived by EDGalaxyData."
)

METHOD_NOTE: Final = (
    "Counts are distinct bodies where a species was confirmed, grouped by the "
    "game-recorded planet class, atmosphere and a 10 K temperature band. They rank "
    "suggestions; they are not spawn probabilities and never rule a species out."
)

VARIANT_NOTE: Final = (
    "Ranking is species-level. Colour variants are shown when the journal confirms "
    "them with ScanOrganic; this build does not predict variants."
)

#: Provenance credited in THIRD_PARTY_NOTICES and the Intel card.
SOURCES: Final[tuple[dict[str, str], ...]] = (
    {
        "name": "Frontier Developments: Elite Dangerous Player Journal v37",
        "url": "https://hosting.zaonce.net/community/journal/v37/Journal_Manual_v37.pdf",
        "use": (
            "field definitions for Scan, ScanOrganic, CodexEntry and SAASignalsFound"
        ),
    },
    {
        "name": "Elite Dangerous Data Network (EDDN)",
        "url": "https://github.com/EDCD/EDDN",
        "use": "relay of commander-uploaded game journal events",
    },
    {
        "name": "EDGalaxyData historical EDDN archives",
        "url": "https://edgalaxydata.space/EDDN/",
        "use": "daily raw-event archives for 2026-10-01 to 2026-10-03",
    },
)


class EvidenceUnavailable(Exception):
    """The evidence asset is absent or failed validation.

    ``reason`` is ``not_included`` for an absent file — a build may legitimately ship
    without it — and ``invalid`` for a present but unusable one, which is a defect.
    """

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Journal normalisation
# ---------------------------------------------------------------------------

_ATMOSPHERE_QUALIFIERS: Final[tuple[str, ...]] = (
    "hot thin ",
    "hot thick ",
    "very thin ",
    "very thick ",
    "thin ",
    "thick ",
    "hot ",
)
_NON_ALNUM: Final = re.compile(r"[^a-z0-9]")


def planet_key(value: Any) -> str | None:
    """Reduce a journal PlanetClass ("Rocky ice body") to a comparison key."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = re.sub(r"\s+body$", "", value.strip().lower())
    return _NON_ALNUM.sub("", raw) or None


def atmosphere_key(value: Any) -> str | None:
    """Reduce either journal atmosphere spelling to one comparison key.

    ``Atmosphere`` is prose ("thin carbon dioxide rich atmosphere") and
    ``AtmosphereType`` is a token ("CarbonDioxideRich"); both reduce to
    "carbondioxiderich". An airless body ("None", "No atmosphere") is "none", a stated
    fact distinct from ``None``, which means nothing was recorded.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().lower()
    if raw in ("none", "no atmosphere", "no atmospheres"):
        return "none"
    for prefix in _ATMOSPHERE_QUALIFIERS:
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    raw = re.sub(r"\s+atmospheres?$", "", raw)
    return _NON_ALNUM.sub("", raw) or None


def genus_key(value: Any) -> str | None:
    """Accept both ``$Codex_Ent_X_Genus;`` and ``$Codex_Ent_X_Genus_Name;``."""
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower().replace("_genus_name;", "_genus;")


def token_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().lower()


def temperature_band(temperature_k: Any) -> int | None:
    try:
        value = float(temperature_k)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return math.floor(value / TEMPERATURE_BAND_K)


def band_label(band: int | None) -> str | None:
    if band is None:
        return None
    low = band * TEMPERATURE_BAND_K
    return f"{low}–{low + TEMPERATURE_BAND_K} K"


# ---------------------------------------------------------------------------
# Evidence index
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Species:
    token: str
    genus_token: str
    name: str
    observed_bodies: int


@dataclass
class EvidenceIndex:
    """Validated, query-ready form of the aggregate asset."""

    sha256: str
    provenance: dict[str, Any]
    species: dict[str, Species] = field(default_factory=dict)
    genus_names: dict[str, str] = field(default_factory=dict)
    genus_species: dict[str, list[str]] = field(default_factory=dict)
    environment: dict[tuple[str, str], Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    band: dict[tuple[str, str, int], Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    environment_groups: int = 0
    _genus_alias: dict[str, str] = field(default_factory=dict)
    _species_alias: dict[str, str] = field(default_factory=dict)

    @property
    def observed_bodies(self) -> int:
        return sum(s.observed_bodies for s in self.species.values())

    # -- identity ----------------------------------------------------------

    def resolve_genus(self, token: Any, localised: Any = None) -> str | None:
        """Map a journal genus (token first, then display name) to a known genus.

        An unrecognised genus resolves to None. It is never mapped onto a
        different genus, because the game's report outranks this index.
        """
        for candidate in (genus_key(token), _casefold(localised), _casefold(token)):
            if candidate and candidate in self._genus_alias:
                return self._genus_alias[candidate]
        return None

    def resolve_species(self, token: Any, localised: Any = None) -> Species | None:
        for candidate in (token_key(token), _casefold(localised)):
            if candidate and candidate in self._species_alias:
                return self.species[self._species_alias[candidate]]
        return None

    # -- ranking -----------------------------------------------------------

    def rank_genus(
        self,
        genus_token: str,
        *,
        planet: str | None,
        atmosphere: str | None,
        band: int | None,
    ) -> tuple[list[dict[str, Any]], str, int | None]:
        """Rank every species of a game-confirmed genus.

        Returns the ranked candidates, the deepest basis that had any sightings,
        and the genus's total sightings at that basis (the denominator a reader
        needs to judge a count). No species is ever dropped.
        """
        env = (
            self.environment.get((planet, atmosphere), Counter())
            if planet and atmosphere
            else Counter()
        )
        local = (
            self.band.get((planet, atmosphere, band), Counter())
            if planet and atmosphere and band is not None
            else Counter()
        )
        members = self.genus_species.get(genus_token, [])
        rows = [self._candidate(token, local[token], env[token]) for token in members]
        rows.sort(
            key=lambda r: (
                -r["similar_temperature_bodies"],
                -r["same_planet_atmosphere_bodies"],
                -r["total_observed_bodies"],
                r["species_token"],
            )
        )
        local_total = sum(local[t] for t in members)
        env_total = sum(env[t] for t in members)
        if local_total:
            return rows, BASIS_TEMPERATURE, local_total
        if env_total:
            return rows, BASIS_PLANET_ATMOSPHERE, env_total
        return rows, BASIS_GENUS_WIDE, None

    def preliminary_genera(
        self, *, planet: str | None, atmosphere: str | None, band: int | None
    ) -> list[dict[str, Any]]:
        """Genera confirmed on bodies with these conditions, strongest first.

        Only genera with same planet/atmosphere sightings are returned. Genera
        with none are not "excluded"; there is simply nothing local to suggest.
        """
        if not planet or not atmosphere:
            return []
        env = self.environment.get((planet, atmosphere), Counter())
        local = (
            self.band.get((planet, atmosphere, band), Counter())
            if band is not None
            else Counter()
        )
        out: list[dict[str, Any]] = []
        for genus_token, members in self.genus_species.items():
            env_total = sum(env[t] for t in members)
            if not env_total:
                continue
            local_total = sum(local[t] for t in members)
            ranked = sorted(
                (t for t in members if env[t]),
                key=lambda t: (-local[t], -env[t], t),
            )
            out.append(
                {
                    "genus": self.genus_names[genus_token],
                    "genus_token": genus_token,
                    "similar_temperature_bodies": local_total,
                    "same_planet_atmosphere_bodies": env_total,
                    "evidence_strength": _strength(local_total, env_total, 1),
                    "top_species": [self.species[t].name for t in ranked[:2]],
                }
            )
        out.sort(
            key=lambda r: (
                -r["similar_temperature_bodies"],
                -r["same_planet_atmosphere_bodies"],
                r["genus"],
            )
        )
        return out

    def _candidate(self, token: str, local: int, env: int) -> dict[str, Any]:
        species = self.species[token]
        return {
            "species": species.name,
            "species_token": species.token,
            "evidence_strength": _strength(local, env, species.observed_bodies),
            "similar_temperature_bodies": local,
            "same_planet_atmosphere_bodies": env,
            "total_observed_bodies": species.observed_bodies,
            "sparse": species.observed_bodies < SPARSE_BODY_THRESHOLD,
        }

    def summary(self) -> dict[str, Any]:
        return {
            "dataset_id": SCHEMA,
            "dataset_sha256": self.sha256,
            "species_count": len(self.species),
            "genus_count": len(self.genus_species),
            "observed_bodies": self.observed_bodies,
            "environment_groups": self.environment_groups,
            "archive_partitions": list(self.provenance.get("archive_partitions") or []),
            "sparse_species": sorted(
                s.name
                for s in self.species.values()
                if s.observed_bodies < SPARSE_BODY_THRESHOLD
            ),
        }


def _casefold(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip().casefold()


def _strength(local: int, env: int, genus_wide: int) -> str:
    """Plain evidence label. Describes sightings, never likelihood."""
    if local >= 10:
        return STRENGTH_STRONG
    if local or env >= 10:
        return STRENGTH_MODERATE
    if env:
        return STRENGTH_LIMITED
    if genus_wide:
        return STRENGTH_GENUS_ONLY
    return STRENGTH_NONE


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise EvidenceUnavailable(REASON_INVALID, detail)


def _is_count(value: Any, minimum: int) -> bool:
    return type(value) is int and value >= minimum


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def build_index(asset: Any, sha256: str = "") -> EvidenceIndex:
    """Validate an asset and index it. Fails closed on any inconsistency."""
    _require(isinstance(asset, dict), "asset is not an object")
    _require(asset.get("schema") == SCHEMA, "unrecognised schema")
    _require(
        asset.get("temperature_band_width_k") == TEMPERATURE_BAND_K,
        "unsupported temperature band width",
    )
    rows = asset.get("species")
    _require(isinstance(rows, list) and bool(rows), "missing species registry")
    provenance = asset.get("provenance")
    index = EvidenceIndex(
        sha256=sha256, provenance=provenance if isinstance(provenance, dict) else {}
    )
    for row in rows:
        _require(isinstance(row, dict), "species entry is not an object")
        token, genus, name = (
            row.get("species_token"),
            row.get("genus_token"),
            row.get("name"),
        )
        count = row.get("observed_bodies")
        _require(
            _is_text(token) and _is_text(genus) and _is_text(name),
            "species entry lacks token, genus or name",
        )
        _require(_is_count(count, 0), "invalid observed body count")
        _require(token not in index.species, f"duplicate species {token}")
        species = Species(token, genus, name, count)
        index.species[token] = species
        index.genus_species.setdefault(genus, []).append(token)
        # The genus display name is the first word of its species' names, which is
        # also the game's English Genus_Localised ("Bacterium", "Frutexa").
        display = name.split()[0]
        _require(
            index.genus_names.setdefault(genus, display) == display,
            f"genus {genus} has inconsistent species names",
        )
        for alias, target, table in (
            (token_key(token), token, index._species_alias),
            (_casefold(name), token, index._species_alias),
            (genus_key(genus), genus, index._genus_alias),
            (_casefold(display), genus, index._genus_alias),
        ):
            assert alias is not None
            _require(
                table.setdefault(alias, target) == target, f"ambiguous alias {alias}"
            )

    per_env: Counter[str] = Counter()
    per_band: Counter[str] = Counter()
    groups: set[tuple[str, str]] = set()
    for entry in asset.get("environment") or []:
        _require(isinstance(entry, list) and len(entry) == 4, "bad environment row")
        token, planet, atmosphere, count = entry
        _require(token in index.species, "environment row for unknown species")
        _require(_is_text(planet) and _is_text(atmosphere), "bad environment keys")
        _require(_is_count(count, 1), "bad environment count")
        index.environment[(planet, atmosphere)][token] += count
        groups.add((planet, atmosphere))
        per_env[token] += count
    for entry in asset.get("temperature_band") or []:
        _require(
            isinstance(entry, list) and len(entry) == 5, "bad temperature-band row"
        )
        token, planet, atmosphere, band, count = entry
        _require(token in index.species, "band row for unknown species")
        _require(_is_text(planet) and _is_text(atmosphere), "bad band keys")
        _require(_is_count(band, 0) and _is_count(count, 1), "bad band value")
        index.band[(planet, atmosphere, band)][token] += count
        per_band[token] += count
    totals = Counter(
        {
            s.token: s.observed_bodies
            for s in index.species.values()
            if s.observed_bodies
        }
    )
    _require(
        per_env == totals and per_band == totals, "aggregate counts are inconsistent"
    )
    index.environment_groups = len(groups)
    # Freeze the defaultdicts so lookups of unseen conditions never grow them.
    index.environment = dict(index.environment)
    index.band = dict(index.band)
    return index


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

_cache: EvidenceIndex | EvidenceUnavailable | None = None


def load(path: Path | None = None) -> EvidenceIndex:
    """The validated index, cached. Raises EvidenceUnavailable."""
    global _cache
    if path is None and _cache is not None:
        if isinstance(_cache, EvidenceUnavailable):
            raise _cache
        return _cache
    target = path or ASSET_PATH
    try:
        raw = target.read_bytes()
    except FileNotFoundError:
        result: EvidenceIndex | EvidenceUnavailable = EvidenceUnavailable(
            REASON_NOT_INCLUDED, f"{target.name} is not in this build"
        )
    except OSError as exc:
        result = EvidenceUnavailable(REASON_INVALID, str(exc))
    else:
        try:
            result = build_index(
                json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
            )
        except EvidenceUnavailable as exc:
            result = exc
        except (ValueError, UnicodeDecodeError) as exc:
            result = EvidenceUnavailable(REASON_INVALID, f"unreadable JSON: {exc}")
    if path is None:
        _cache = result
    if isinstance(result, EvidenceUnavailable):
        raise result
    return result


def reset_cache() -> None:
    global _cache
    _cache = None


def availability() -> tuple[EvidenceIndex | None, str | None]:
    """(index, None) when usable, else (None, reason). Never raises."""
    try:
        return load(), None
    except EvidenceUnavailable as exc:
        return None, exc.reason


def notice_markdown() -> list[str]:
    """Attribution section for THIRD_PARTY_NOTICES."""
    lines = [
        "## Exobiology journal evidence",
        "",
        f"`omnicovas/data/{ASSET_PATH.name}` is an original OmniCOVAS aggregate of "
        "confirmed exobiology sightings, compiled from Frontier Elite Dangerous "
        "journal events relayed by the Elite Dangerous Data Network (EDDN) and "
        "archived by EDGalaxyData. It contains counts of distinct bodies per "
        "species and game-recorded "
        "planet class, atmosphere and temperature band only: no commander names, "
        "uploader identifiers, system or body identifiers, or raw messages. No "
        "third-party prediction tables or occurrence rules were used.",
        "",
    ]
    for source in SOURCES:
        lines.append(f"- {source['name']}: <{source['url']}> ({source['use']})")
    lines.append("")
    return lines
