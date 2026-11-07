"""Exobiology intelligence — Intel exploration fact domain.

Fact first, suggestion second, and the journal always wins.

Three game observations drive this surface, in increasing authority:

``FSSBodySignals`` / ``SAASignalsFound`` signal counts
    Elite reports how many biological signals a body carries. A fact.
``SAASignalsFound.Genuses``
    After a surface map, the genera present. A fact; never predicted over.
``ScanOrganic``
    The species (and colour variant) the Commander actually logged, with
    Log/Sample/Analyse progress. Proof, and it outranks everything else.

Suggestions fill the gaps between those facts and come from one place: the
independent journal-evidence aggregate in
:mod:`omnicovas.features.exobiology_evidence`. Before the genera are named they
are labelled *preliminary*. Once a genus is named, every species of that genus
stays a candidate, ranked by how often it was confirmed on bodies with the same
recorded conditions; the strongest few lead and the rest stay available. Once a
species is confirmed on a body, no suggestion is shown for its genus there.

Missing or unreadable evidence is a stated condition (``candidate_basis.state``
``unavailable``), never an HTTP 500 and never "no candidates". Everything here is
read from JournalEvent rows the recorder already stores. Nothing reaches the
network, and nothing depends on an AI provider.

Body identity. Real journals identify a body by ``SystemAddress`` plus
``BodyID`` (``Body`` on ``ScanOrganic``). ``ScanOrganic`` carries no body name and
``SAASignalsFound`` carries no system name, so both are joined on that address
and named from the recorded ``Scan``/signal events and the jump history.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import JournalEvent
from omnicovas.features import exobiology_evidence as evidence
from omnicovas.features.exobiology_evidence import EvidenceIndex

TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
TRUTH_KNOWLEDGE_REFERENCE = "knowledge_reference"
SOURCE_FLIGHT_RECORDER = "Local session database (flight recorder)"
KB_ENTRY_CONDITIONS = "exobiology_mechanics/genus_spawn_conditions"
#: Mirrors the `needs_review` flag on that KB entry. A test asserts the two
#: agree, so this cannot drift into claiming a review state the KB contradicts.
KB_ENTRY_NEEDS_REVIEW = False

SIGNALS_EVENTS = ("SAASignalsFound",)
FSS_SIGNALS_EVENTS = ("FSSBodySignals",)
ORGANIC_SCAN_EVENTS = ("ScanOrganic",)
BODY_SCAN_EVENTS = ("Scan",)
SYSTEM_NAME_EVENTS = ("FSDJump", "Location", "CarrierJump")

BIOLOGICAL_SIGNAL_TYPE = "biological"

DEFAULT_LIMIT = 100
MAX_LIMIT = 500

STAGE_GENERA_REPORTED = "genera_reported"
STAGE_PRELIMINARY = "preliminary"
STAGE_INSUFFICIENT = "insufficient_conditions"
STAGE_UNAVAILABLE = "unavailable"
STAGE_CONFIRMED = "confirmed"

GENUS_CONFIRMED = "confirmed"
GENUS_RANKED = "ranked"
GENUS_UNRECOGNIZED = "unrecognized"
GENUS_UNAVAILABLE = "unavailable"

_SIGNALS_CAVEAT = (
    "Biological signal counts, reported genera and logged species are read from "
    "recorded FSSBodySignals, SAASignalsFound and ScanOrganic events — observed "
    "facts, not predictions. A body absent here has no signals recorded on this "
    "machine; that is not proof it holds no life."
)
_UNAVAILABLE_CAVEAT = (
    "Species suggestions are unavailable in this build, so only what the journal "
    "reported is shown. That says nothing about what else is on a body."
)
_SUGGESTION_CAVEAT = (
    "Suggestions are ranked from an independent aggregate of confirmed sightings "
    "recorded in Elite journal events (relayed by EDDN, archived by EDGalaxyData). "
    "Counts show where a species has been confirmed under the same recorded "
    "conditions; they are not spawn probabilities, and a species with few or no "
    "sightings under these conditions is not ruled out. Before the game names the "
    "genera, suggestions are preliminary. A species you log with ScanOrganic is "
    "shown as confirmed and replaces any suggestion for its genus."
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


def _loads(raw: str) -> dict[str, Any] | None:
    try:
        event = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return event if isinstance(event, dict) else None


def _int_or_none(value: Any) -> int | None:
    return value if type(value) is int else None


def _bio_count(event: dict[str, Any]) -> int | None:
    for signal in event.get("Signals") or []:
        if not isinstance(signal, dict):
            continue
        if BIOLOGICAL_SIGNAL_TYPE in _normalise(signal.get("Type")):
            try:
                return max(0, int(signal.get("Count") or 0))
            except (TypeError, ValueError):
                return None
    return None


# ---------------------------------------------------------------------------
# Body assembly
# ---------------------------------------------------------------------------

BodyKey = tuple[Any, ...]


@dataclass
class _Organic:
    species: str
    species_token: str | None
    genus_token: str | None
    genus_display: str | None
    variant: str | None = None
    stages: set[str] = field(default_factory=set)
    last_seen: datetime | None = None


@dataclass
class _Body:
    key: BodyKey
    name: str | None = None
    system_address: int | None = None
    star_system: str | None = None
    scan: dict[str, Any] = field(default_factory=dict)
    signal_count: int | None = None
    signal_source: str | None = None
    signals_at: datetime | None = None
    reported_genera: list[tuple[str | None, str | None]] = field(default_factory=list)
    organics: dict[str, _Organic] = field(default_factory=dict)
    last_activity: datetime | None = None

    def touch(self, when: datetime | None) -> None:
        if when is not None and (
            self.last_activity is None or when > self.last_activity
        ):
            self.last_activity = when


class _Registry:
    """Joins events about one body, by address where the journal gives one."""

    def __init__(self) -> None:
        self.bodies: dict[BodyKey, _Body] = {}
        self._by_name: dict[str, BodyKey] = {}

    def register_name(self, event: dict[str, Any], body_field: str) -> None:
        address = _int_or_none(event.get("SystemAddress"))
        body_id = _int_or_none(event.get(body_field))
        name = event.get("BodyName")
        if (
            address is not None
            and body_id is not None
            and isinstance(name, str)
            and name
        ):
            self._by_name.setdefault(name, ("addr", address, body_id))

    def get(self, event: dict[str, Any], body_field: str) -> _Body | None:
        address = _int_or_none(event.get("SystemAddress"))
        body_id = _int_or_none(event.get(body_field))
        name = event.get("BodyName") or event.get("Body_Localised")
        name = name if isinstance(name, str) and name else None
        key: BodyKey | None
        if address is not None and body_id is not None:
            key = ("addr", address, body_id)
        elif name is not None:
            key = self._by_name.get(name, ("name", name))
        else:
            return None
        body = self.bodies.get(key)
        if body is None:
            body = self.bodies[key] = _Body(key=key)
            if key[0] == "addr":
                body.system_address = key[1]
        if name and not body.name:
            body.name = name
        system = event.get("StarSystem")
        if isinstance(system, str) and system and not body.star_system:
            body.star_system = system
        return body


def _apply_scan(body: _Body, event: dict[str, Any]) -> None:
    facts = body.scan
    for key, source in (
        ("planet_class", "PlanetClass"),
        ("atmosphere", "Atmosphere"),
        # Applied after Atmosphere so it wins where both exist. For an airless body it
        # says "None" where Atmosphere says "" — a stated fact, not an absent one.
        ("atmosphere", "AtmosphereType"),
        ("volcanism", "Volcanism"),
    ):
        value = event.get(source)
        if value is not None and (value != "" or key not in facts):
            facts[key] = value
    prose = event.get("Atmosphere")
    if isinstance(prose, str) and prose.strip():
        # The journal's own wording ("thin carbon dioxide atmosphere"), shown to
        # the Commander in preference to the AtmosphereType token.
        facts["atmosphere_text"] = prose.strip()
    if event.get("SurfaceTemperature") is not None:
        facts["surface_temperature"] = event["SurfaceTemperature"]
    if event.get("SurfaceGravity") is not None:
        # Journal SurfaceGravity is m/s^2; shown to the Commander in Earth g.
        try:
            facts["surface_gravity_g"] = round(
                float(event["SurfaceGravity"]) / 9.80665, 3
            )
        except (TypeError, ValueError):
            pass
    if event.get("Landable") is not None:
        facts["landable"] = bool(event["Landable"])


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


def _conditions(body: _Body) -> dict[str, Any]:
    scan = body.scan
    band = evidence.temperature_band(scan.get("surface_temperature"))
    planet = evidence.planet_key(scan.get("planet_class"))
    atmosphere = evidence.atmosphere_key(scan.get("atmosphere"))
    return {
        "planet": planet,
        "atmosphere": atmosphere,
        "band": band,
        "public": {
            "planet_class": scan.get("planet_class"),
            "atmosphere": scan.get("atmosphere_text") or scan.get("atmosphere"),
            "temperature_band": evidence.band_label(band),
            "complete": bool(planet and atmosphere and band is not None),
        },
    }


def _organic_genus(index: EvidenceIndex | None, organic: _Organic) -> str | None:
    """The evidence genus a confirmed organism belongs to, where known."""
    if index is None:
        return None
    if organic.species_token or organic.species:
        species = index.resolve_species(organic.species_token, organic.species)
        if species is not None:
            return species.genus_token
    return index.resolve_genus(organic.genus_token, organic.genus_display)


def _genus_display(organic: _Organic) -> str:
    if organic.genus_display:
        return organic.genus_display
    if organic.genus_token:
        return _localised(organic.genus_token) or organic.genus_token
    return organic.species.split()[0] if organic.species else "Unknown genus"


def _logged(
    candidate: dict[str, Any], logged_tokens: set[str], logged_names: set[str]
) -> bool:
    return (
        _normalise(candidate.get("species_token")) in logged_tokens
        or _normalise(candidate.get("species")) in logged_names
    )


def _sampling_row(organic: _Organic) -> dict[str, Any]:
    return {
        "species": organic.species,
        "variant": organic.variant,
        "stages_recorded": sorted(organic.stages),
        # Elite needs three samples; Analyse closes it out.
        "analysed": "analyse" in organic.stages,
    }


def _genus_predictions(
    body: _Body,
    index: EvidenceIndex | None,
    cond: dict[str, Any],
    logged_tokens: set[str],
    logged_names: set[str],
) -> list[dict[str, Any]]:
    """One entry per genus known on this body: reported by scan or confirmed."""
    entries: list[dict[str, Any]] = []
    claimed: set[str] = set()

    confirmed_by_genus: dict[str, list[_Organic]] = {}
    unplaced: list[_Organic] = []
    for organic in body.organics.values():
        genus = _organic_genus(index, organic)
        if genus is not None:
            confirmed_by_genus.setdefault(genus, []).append(organic)
        else:
            unplaced.append(organic)

    def confirmed_rows(items: list[_Organic]) -> list[dict[str, Any]]:
        return [_sampling_row(o) for o in sorted(items, key=lambda o: o.species)]

    for token, localised in body.reported_genera:
        resolved = index.resolve_genus(token, localised) if index else None
        display = (
            index.genus_names[resolved]
            if index and resolved
            else (localised or _localised(token) or "Unknown genus")
        )
        dedupe = resolved or _normalise(display)
        if dedupe in claimed:
            continue
        claimed.add(dedupe)

        entry: dict[str, Any] = {
            "genus": display,
            "genus_token": resolved or token,
            "reported_by_scan": True,
            "status": GENUS_UNAVAILABLE,
            "confirmed_species": [],
            "suggestions": [],
            "other_candidates": [],
            "candidate_count": 0,
            "ranking_basis": None,
            "similar_bodies_in_genus": None,
            "note": None,
        }
        confirmed = list(confirmed_by_genus.get(resolved or "", []))
        # A non-target organism can only be placed by its genus display name.
        for organic in list(unplaced):
            if _normalise(_genus_display(organic)) == _normalise(display):
                confirmed.append(organic)
                unplaced.remove(organic)
        if confirmed:
            entry["status"] = GENUS_CONFIRMED
            entry["confirmed_species"] = confirmed_rows(confirmed)
            entry["note"] = "Confirmed by ScanOrganic."
        elif index is None:
            entry["note"] = "Species suggestions are unavailable in this build."
        elif resolved is None:
            entry["status"] = GENUS_UNRECOGNIZED
            entry["note"] = (
                "Reported by the game. No independent species evidence for this "
                "genus is included, so no species is suggested."
            )
        else:
            ranked, basis, denominator = index.rank_genus(
                resolved,
                planet=cond["planet"],
                atmosphere=cond["atmosphere"],
                band=cond["band"],
            )
            for row in ranked:
                row["logged_by_commander"] = _logged(row, logged_tokens, logged_names)
            entry.update(
                status=GENUS_RANKED,
                suggestions=ranked[: evidence.SUGGESTION_DEPTH],
                other_candidates=ranked[evidence.SUGGESTION_DEPTH :],
                candidate_count=len(ranked),
                ranking_basis=basis,
                similar_bodies_in_genus=denominator,
                note=(
                    None
                    if basis != evidence.BASIS_GENUS_WIDE
                    else (
                        "No confirmed sightings of this genus under these recorded "
                        "conditions; ranked by sightings elsewhere."
                        if cond["public"]["complete"]
                        else "This body's conditions are not fully recorded; "
                        "ranked by sightings elsewhere."
                    )
                ),
            )
        entries.append(entry)

    # Organisms the Commander logged in a genus the scan did not name (or before
    # any surface map). Proof stands on its own.
    for genus, items in sorted(confirmed_by_genus.items()):
        if genus in claimed:
            continue
        claimed.add(genus)
        entries.append(
            _confirmed_only(index.genus_names[genus] if index else genus, genus, items)
        )
    leftovers: dict[str, list[_Organic]] = {}
    for organic in unplaced:
        leftovers.setdefault(_genus_display(organic), []).append(organic)
    for display, items in sorted(leftovers.items()):
        if _normalise(display) in claimed:
            continue
        token = items[0].genus_token
        entries.append(_confirmed_only(display, token, items))
    return entries


def _confirmed_only(
    display: str, token: str | None, items: list[_Organic]
) -> dict[str, Any]:
    return {
        "genus": display,
        "genus_token": token,
        "reported_by_scan": False,
        "status": GENUS_CONFIRMED,
        "confirmed_species": [
            _sampling_row(o) for o in sorted(items, key=lambda o: o.species)
        ],
        "suggestions": [],
        "other_candidates": [],
        "candidate_count": 0,
        "ranking_basis": None,
        "similar_bodies_in_genus": None,
        "note": "Confirmed by ScanOrganic.",
    }


# ---------------------------------------------------------------------------
# Public read
# ---------------------------------------------------------------------------


def _candidate_basis(index: EvidenceIndex | None, reason: str | None) -> dict[str, Any]:
    """Where suggestions come from, or the plain reason there are none."""
    basis: dict[str, Any] = {
        "state": evidence.STATE_UNAVAILABLE
        if index is None
        else evidence.STATE_AVAILABLE,
        "reason": reason,
        "truth_class": TRUTH_KNOWLEDGE_REFERENCE,
        "kb_entry": KB_ENTRY_CONDITIONS,
        "needs_review": KB_ENTRY_NEEDS_REVIEW,
        "source_attribution": evidence.SOURCE_ATTRIBUTION,
        "method_note": evidence.METHOD_NOTE,
        "variant_note": evidence.VARIANT_NOTE,
        "sparse_body_threshold": evidence.SPARSE_BODY_THRESHOLD,
        "suggestion_depth": evidence.SUGGESTION_DEPTH,
    }
    if index is not None:
        basis.update(index.summary())
    return basis


async def _read_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[list[Any], dict[int, str]]:
    async with session_factory() as db:
        rows = (
            await db.execute(
                select(
                    JournalEvent.event_type,
                    JournalEvent.raw_json,
                    JournalEvent.timestamp,
                )
                .where(
                    JournalEvent.event_type.in_(
                        (
                            *SIGNALS_EVENTS,
                            *FSS_SIGNALS_EVENTS,
                            *BODY_SCAN_EVENTS,
                            *ORGANIC_SCAN_EVENTS,
                        )
                    )
                )
                .order_by(JournalEvent.timestamp.asc(), JournalEvent.id.asc())
            )
        ).all()
        # Only the two small fields are pulled from jump history, so a long career
        # of jumps costs a narrow distinct scan rather than a full JSON read.
        jumps = (
            await db.execute(
                select(
                    func.json_extract(JournalEvent.raw_json, "$.SystemAddress"),
                    func.json_extract(JournalEvent.raw_json, "$.StarSystem"),
                )
                .where(JournalEvent.event_type.in_(SYSTEM_NAME_EVENTS))
                .distinct()
            )
        ).all()
    systems: dict[int, str] = {}
    for address, name in jumps:
        if type(address) is int and isinstance(name, str) and name:
            systems.setdefault(address, name)
    return list(rows), systems


async def biological_signals(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    star_system: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Bodies with recorded biology, each with facts first and suggestions after."""
    bounded_limit = _clamp_limit(limit, DEFAULT_LIMIT, MAX_LIMIT)
    index, unavailable = evidence.availability()
    rows, systems = await _read_events(session_factory)

    parsed: list[tuple[str, dict[str, Any], datetime | None]] = []
    for event_type, raw, timestamp in rows:
        event = _loads(raw)
        if event is not None:
            parsed.append((event_type, event, timestamp))

    registry = _Registry()
    # Pass 1: learn address -> name from events that carry both, so name-only
    # events (older or hand-written fixtures) still join the right body.
    for event_type, event, _ in parsed:
        if event_type != "ScanOrganic":
            registry.register_name(event, "BodyID")

    primary_star: dict[str, str] = {}
    logged_tokens: set[str] = set()
    logged_names: set[str] = set()
    logged_genus_names: set[str] = set()

    for event_type, event, timestamp in parsed:
        system = event.get("StarSystem")
        if event_type == "Scan":
            address = _int_or_none(event.get("SystemAddress"))
            if address is not None and isinstance(system, str) and system:
                systems.setdefault(address, system)
            star_type = event.get("StarType")
            if star_type and system:
                # The primary is the star scanned at zero arrival distance.
                try:
                    primary = float(event.get("DistanceFromArrivalLS") or 0.0) <= 0.0
                except (TypeError, ValueError):
                    primary = False
                if primary:
                    primary_star.setdefault(str(system), str(star_type))
                continue
            if not event.get("PlanetClass"):
                continue
            body = registry.get(event, "BodyID")
            if body is not None:
                _apply_scan(body, event)
        elif event_type in SIGNALS_EVENTS or event_type in FSS_SIGNALS_EVENTS:
            count = _bio_count(event)
            if count is None:
                continue
            body = registry.get(event, "BodyID")
            if body is None:
                continue
            is_saa = event_type in SIGNALS_EVENTS
            # A surface map supersedes the FSS reading; an FSS reading never
            # overwrites a surface map.
            if is_saa or body.signal_source != "SAASignalsFound":
                body.signal_count = count
                body.signal_source = event_type
                body.signals_at = timestamp
            if is_saa:
                reported = [
                    (entry.get("Genus"), entry.get("Genus_Localised"))
                    for entry in (event.get("Genuses") or [])
                    if isinstance(entry, dict)
                    and (entry.get("Genus") or entry.get("Genus_Localised"))
                ]
                if reported:
                    body.reported_genera = reported
            body.touch(timestamp)
        elif event_type in ORGANIC_SCAN_EVENTS:
            species_token = event.get("Species")
            species_name = event.get("Species_Localised") or _localised(species_token)
            if index is not None:
                resolved = index.resolve_species(species_token, species_name)
                if resolved is not None:
                    species_name = resolved.name
            if not species_name:
                continue
            species_name = str(species_name)
            logged_names.add(_normalise(species_name))
            if species_token:
                logged_tokens.add(_normalise(species_token))
            genus_display = event.get("Genus_Localised") or _localised(
                event.get("Genus")
            )
            if genus_display:
                logged_genus_names.add(_normalise(genus_display))
            body = registry.get(event, "Body")
            if body is None:
                continue
            organic = body.organics.get(species_name)
            if organic is None:
                organic = body.organics[species_name] = _Organic(
                    species=species_name,
                    species_token=species_token
                    if isinstance(species_token, str)
                    else None,
                    genus_token=event.get("Genus")
                    if isinstance(event.get("Genus"), str)
                    else None,
                    genus_display=str(genus_display) if genus_display else None,
                )
            variant = event.get("Variant_Localised") or None
            if isinstance(variant, str) and variant:
                organic.variant = variant
            scan_type = _normalise(event.get("ScanType"))
            if scan_type:
                organic.stages.add(scan_type)
            organic.last_seen = timestamp
            body.touch(timestamp)

    out: list[dict[str, Any]] = []
    candidates = [
        b for b in registry.bodies.values() if b.signal_count is not None or b.organics
    ]
    for body in candidates:
        if not body.star_system and body.system_address is not None:
            body.star_system = systems.get(body.system_address)
        if body.name is None:
            # A ScanOrganic with no recorded Scan or signal event for its body.
            body.name = (
                f"{body.star_system} body {body.key[2]}"
                if body.star_system and body.key[0] == "addr"
                else None
            )
    candidates = [b for b in candidates if b.name]
    if star_system:
        candidates = [b for b in candidates if b.star_system == star_system]
    # Most recent activity first. ISO text compares correctly and never mixes
    # naive with aware datetimes.
    candidates.sort(
        key=lambda b: (_iso_or_none(b.last_activity) or "", b.name or ""), reverse=True
    )

    for body in candidates[:bounded_limit]:
        cond = _conditions(body)
        genera = _genus_predictions(body, index, cond, logged_tokens, logged_names)
        observed = [g["genus"] for g in genera]
        confirmed_genus_count = sum(1 for g in genera if g["status"] == GENUS_CONFIRMED)

        preliminary: list[dict[str, Any]] = []
        if body.reported_genera:
            stage = STAGE_GENERA_REPORTED
        elif body.signal_count is None or body.signal_count <= confirmed_genus_count:
            stage = STAGE_CONFIRMED
        elif index is None:
            stage = STAGE_UNAVAILABLE
        elif not (cond["planet"] and cond["atmosphere"]):
            stage = STAGE_INSUFFICIENT
        else:
            stage = STAGE_PRELIMINARY
            confirmed_tokens = {g["genus_token"] for g in genera}
            for row in index.preliminary_genera(
                planet=cond["planet"], atmosphere=cond["atmosphere"], band=cond["band"]
            ):
                if row["genus_token"] in confirmed_tokens:
                    continue
                preliminary.append(
                    {
                        "genus": row["genus"],
                        "basis": "independent_journal_evidence",
                        "note": (
                            "Preliminary — the game has not named this body's genera."
                        ),
                        "evidence_strength": row["evidence_strength"],
                        "similar_temperature_bodies": row["similar_temperature_bodies"],
                        "same_planet_atmosphere_bodies": row[
                            "same_planet_atmosphere_bodies"
                        ],
                        "top_species": row["top_species"],
                    }
                )

        if body.star_system and body.star_system in primary_star:
            body.scan["parent_star_class"] = primary_star[body.star_system]

        # Genera named here that this Commander has never logged anywhere: a fact
        # about their own record, never a claim about galactic firsts.
        unlogged = [
            g["genus"]
            for g in genera
            if g["status"] != GENUS_CONFIRMED
            and _normalise(g["genus"]) not in logged_genus_names
            and not any(_normalise(g["genus"]) in name for name in logged_names)
        ]
        sampling = [_sampling_row(o) for _, o in sorted(body.organics.items())]

        out.append(
            {
                "body_name": body.name,
                "star_system": body.star_system,
                "biological_signal_count": body.signal_count,
                "signal_source": body.signal_source or "ScanOrganic",
                "observed_genera": observed,
                "genera_observed": bool(observed),
                "prediction_stage": stage,
                "ranking_conditions": cond["public"],
                "genus_predictions": genera,
                "candidate_genera": preliminary,
                "species_sampled_here": sorted(body.organics),
                "sampling_progress": sampling,
                "genera_never_logged_by_commander": unlogged,
                "planet_class": body.scan.get("planet_class"),
                "atmosphere": body.scan.get("atmosphere"),
                "surface_temperature": body.scan.get("surface_temperature"),
                "surface_gravity_g": body.scan.get("surface_gravity_g"),
                "landable": body.scan.get("landable"),
                "parent_star_class": body.scan.get("parent_star_class"),
                "signals_recorded_at": _iso_or_none(body.signals_at),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE_FLIGHT_RECORDER,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": (
            f"{_SIGNALS_CAVEAT} "
            f"{_UNAVAILABLE_CAVEAT if index is None else _SUGGESTION_CAVEAT}"
        ),
        "candidate_basis": _candidate_basis(index, unavailable),
        "source_events": [
            *FSS_SIGNALS_EVENTS,
            *SIGNALS_EVENTS,
            *BODY_SCAN_EVENTS,
            *ORGANIC_SCAN_EVENTS,
        ],
        "star_system": star_system,
        "returned": len(out),
        "limit": bounded_limit,
        "bodies": out,
        "nullprovider_safe": True,
    }
