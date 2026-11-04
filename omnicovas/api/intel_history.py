"""Read-only Intel terminal endpoints over the local flight recorder.

Phase 13 Intel terminal core (PB13-01/PB13-02; LNA-002/003/004/005):
journal event search plus commander-observed system/station visit
catalogs. Local-only bounded queries over existing tables — no new
persistence, no migrations, no providers, no Activity Log producers
(ordinary reads create no proof entries per the established read-polling
posture).

See: Engineering Standards v1.0 §12 API module standards
See: omnicovas/api/navigation_bookmarks.py (session-factory pattern)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.features import exobiology_intel, exploration_history, intel_history

router = APIRouter(prefix="/intel", tags=["intel"])

_session_factory: async_sessionmaker[AsyncSession] | None = None
_system_notes: Any = None


def set_session_factory(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> None:
    """Inject the live async session factory into this router."""
    global _session_factory  # noqa: PLW0603
    _session_factory = session_factory


def set_system_note_service(service: Any) -> None:
    """Inject the Commander system-note service (LNA-004 notes slice).

    Optional: the visit history is derived from the flight recorder and stays
    correct without it, so an absent service means "no notes", never an error.
    """
    global _system_notes  # noqa: PLW0603
    _system_notes = service


def _ensure_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Flight recorder persistence not initialized",
        )
    return _session_factory


def _parse_optional_timestamp(value: str | None, field_name: str) -> Any:
    if value is None:
        return None
    try:
        return intel_history.parse_iso_timestamp(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{field_name} is not a valid ISO-8601 timestamp",
        ) from exc


# --- Response models ---------------------------------------------------------


class JournalEventRow(BaseModel):
    """One recorded journal event (raw line preserved verbatim)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    session_id: int
    timestamp: str | None
    event_type: str
    raw_json: str


class JournalSearchFilters(BaseModel):
    """Echo of the bounded filters applied to a search."""

    model_config = ConfigDict(extra="forbid")

    event_type: str | None
    since: str | None
    until: str | None
    contains: str | None
    session_id: int | None
    limit: int


class JournalSearchResponse(BaseModel):
    """Bounded newest-first journal event search result."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    filters_applied: JournalSearchFilters
    total_matched: int
    returned: int
    events: list[JournalEventRow]
    nullprovider_safe: bool


class RecordedEventTypeRow(BaseModel):
    """One distinct recorded event type (verbatim from recorded rows)."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    recorded: int
    last_recorded: str | None


class RecordedEventTypesResponse(BaseModel):
    """Distinct recorded event types with counts (search presets)."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    returned: int
    limit: int
    event_types: list[RecordedEventTypeRow]
    nullprovider_safe: bool


class ExploredSystemRow(BaseModel):
    """One system's Commander-observed survey record."""

    model_config = ConfigDict(extra="forbid")

    star_system: str
    bodies_scanned: int
    bodies_with_discovery_flag: int
    # True only when the journal flagged every scanned body and every one came
    # back undiscovered. Silence is not evidence of virgin territory.
    no_prior_discovery_recorded: bool
    # None when no FSSDiscoveryScan was recorded for this system. Callers must
    # render unknown rather than treating bodies_scanned as the total, which
    # would show a partial survey as a complete one.
    bodies_in_system: int | None
    body_count_known: bool
    survey_complete: bool
    first_discoveries: int
    bodies_surface_mapped: int
    first_scan_at: str | None
    last_scan_at: str | None


class ExploredSystemsResponse(BaseModel):
    """Commander-observed exploration history by system (LNA-035)."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    source_events: list[str]
    returned: int
    limit: int
    systems: list[ExploredSystemRow]
    nullprovider_safe: bool


class ExplorationTripNote(BaseModel):
    """One Commander note for a system surveyed on this trip."""

    model_config = ConfigDict(extra="forbid")

    star_system: str
    note: str | None
    updated_at: str | None


class ExplorationTripRow(BaseModel):
    """One recorded session's exploration activity (LNA-034)."""

    model_config = ConfigDict(extra="forbid")

    session_id: int
    journal_filename: str | None
    commander_name: str | None
    ship_type: str | None
    started_at: str | None
    ended_at: str | None
    end_recorded: bool
    first_event_at: str | None
    last_event_at: str | None
    systems_visited: int
    systems_honked: int
    systems_surveyed: list[str]
    bodies_scanned: int
    first_discoveries: int
    surface_maps: int
    organic_scans: int
    jumps: int
    jump_distance_ly: float | None
    # "Sold during", never "earned by" — the sale events do not say which
    # trip gathered the data. None means nothing was sold on this trip.
    credits_sold_during_trip: int | None
    sales_recorded: int
    notes: list[ExplorationTripNote] = []
    notes_available: bool = False


class ExplorationTripsResponse(BaseModel):
    """Exploration timeline grouped by recorded session (LNA-034)."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    trip_unit: str
    source_events: list[str]
    returned: int
    limit: int
    # Reported so the timeline is never silently narrowed: sessions with no
    # exploration are excluded, and the reader is told how many.
    sessions_without_exploration: int
    trips: list[ExplorationTripRow]
    nullprovider_safe: bool


class ExplorationEarningsSlice(BaseModel):
    """Credits received for one data class. None means never sold here."""

    model_config = ConfigDict(extra="forbid")

    credits_earned: int | None
    sales_recorded: int
    first_sale_at: str | None
    last_sale_at: str | None


class ExobiologyEarningsSlice(ExplorationEarningsSlice):
    """Exobiology adds sampling counts alongside credits received."""

    samples_recorded: int
    distinct_species_sampled: int


class ExplorationEarningsResponse(BaseModel):
    """Credits actually received — never an estimate of unsold data."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    source_events: list[str]
    exploration: ExplorationEarningsSlice
    exobiology: ExobiologyEarningsSlice
    nullprovider_safe: bool


class CandidateGenusRow(BaseModel):
    """A genus whose conditions the body appears to meet. Never a confirmation."""

    model_config = ConfigDict(extra="forbid")

    genus: str
    basis: str
    note: str | None


class SentinelState(BaseModel):
    """Read-only Exobiology Rule Sentinel state.

    A diagnostic summary, not a rule dump: how many of this Commander's own
    confirmed samples the rules got wrong, and which exclusions are suspended
    as a result. `canonical_dataset_modified` is served explicitly because the
    guarantee it carries — that contradictions never rewrite the shipped rules
    — is the whole reason the suspension mechanism is safe.
    """

    model_config = ConfigDict(extra="forbid")

    ruleset_version: str
    ruleset_sha256: str
    evidence_records: int
    supporting_observations: int
    new_empirical_evidence: int
    rule_contradictions: int
    open_contradictions: int
    suspended_predicates: int
    affected_species: list[str]
    predicate_state: str | None
    canonical_dataset_modified: bool
    source: str
    note: str


class CandidateBasis(BaseModel):
    """Where candidate matching gets its rules, and how far to trust them.

    `max_gravity_g` was removed here rather than kept for compatibility: it
    published a universal 0.28g ceiling that the Phase 13 research and its
    independent audit falsified, so continuing to serve it would be publishing
    a known-wrong figure. The ruleset hash replaces it and lets a consumer tell
    exactly which verified dataset produced a prediction.

    `rule_branch_count` is served alongside the species count because occurrence
    is evaluated per branch, not per species: 91 species carry 225 correlated
    rule branches, and the branch count is what describes the real rule surface.
    """

    model_config = ConfigDict(extra="forbid")

    truth_class: str
    kb_entry: str
    needs_review: bool
    species_count: int
    genus_count: int
    rule_branch_count: int
    ruleset_version: str
    ruleset_sha256: str
    sentinel: SentinelState


class SamplingProgressRow(BaseModel):
    """Log/Sample/Analyse progress for one species on this body."""

    model_config = ConfigDict(extra="forbid")

    species: str
    stages_recorded: list[str]
    analysed: bool


class BiologicalSignalRow(BaseModel):
    """One body's observed biological signals plus, if needed, candidates."""

    model_config = ConfigDict(extra="forbid")

    body_name: str
    star_system: str | None
    # Observed fact from SAASignalsFound — never predicted.
    biological_signal_count: int
    observed_genera: list[str]
    genera_observed: bool
    # Populated only when the journal did not already name the genera.
    candidate_genera: list[CandidateGenusRow]
    species_sampled_here: list[str]
    sampling_progress: list[SamplingProgressRow]
    # Genera named here that this Commander has never logged on this machine.
    # A fact about their own record — never a claim about galactic firsts.
    genera_never_logged_by_commander: list[str]
    planet_class: str | None
    atmosphere: str | None
    surface_temperature: float | None
    surface_gravity_g: float | None
    landable: bool | None
    # Primary star of the system, where one was recorded. Some genera are
    # gated on it; absent means star-gated genera were not offered at all.
    parent_star_class: str | None
    signals_recorded_at: str | None


class BiologicalSignalsResponse(BaseModel):
    """Observed biological signals, with clearly separated candidate matching."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    candidate_basis: CandidateBasis
    source_events: list[str]
    star_system: str | None
    returned: int
    limit: int
    bodies: list[BiologicalSignalRow]
    nullprovider_safe: bool


class ScannedBodyRow(BaseModel):
    """One Commander-observed body scan."""

    model_config = ConfigDict(extra="forbid")

    body_name: str
    star_system: str | None
    planet_class: str | None
    star_type: str | None
    terraform_state: str | None
    landable: bool | None
    distance_from_arrival_ls: float | None
    scan_type: str | None
    # None when the journal did not report the flag — never defaulted, since
    # a missing WasDiscovered would otherwise manufacture discovery credit.
    first_discovered_by_commander: bool | None
    first_mapped_by_commander: bool | None
    surface_mapped_by_commander: bool
    scan_events_recorded: int
    first_scan_at: str | None
    last_scan_at: str | None
    # None when the body's class was never recorded — unclassified is unknown,
    # not worthless.
    value_estimate: ValueEstimate | None


class ValueEstimate(BaseModel):
    """A reference estimate — a class and a range, never a credit figure."""

    model_config = ConfigDict(extra="forbid")

    value_class: str
    base_class: str
    estimated_low: int
    estimated_high: int
    bonuses_applied: list[str]
    is_estimate: bool
    truth_class: str
    kb_entry: str


class HighestValueBody(ValueEstimate):
    """The best-estimated body in a result set."""

    body_name: str | None


class ValueEstimateSummary(BaseModel):
    """Aggregate estimate. bodies_unvalued is exposed, never hidden."""

    model_config = ConfigDict(extra="forbid")

    bodies_valued: int
    bodies_unvalued: int
    estimated_low_total: int | None
    estimated_high_total: int | None
    highest_value_body: HighestValueBody | None
    is_estimate: bool
    truth_class: str
    kb_entry: str
    caveat: str


class ScannedBodiesResponse(BaseModel):
    """Commander-observed body scan detail (LNA-035)."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    source_events: list[str]
    star_system: str | None
    returned: int
    limit: int
    bodies: list[ScannedBodyRow]
    value_estimate_summary: ValueEstimateSummary
    nullprovider_safe: bool


class SystemSourceEventRow(BaseModel):
    """One recorded event type behind a system's arrival count."""

    model_config = ConfigDict(extra="forbid")

    event_type: str
    recorded: int


class SystemDockedStationRow(BaseModel):
    """A station docked at within this system, from recorded Docked events."""

    model_config = ConfigDict(extra="forbid")

    station_name: str
    docked_count: int
    last_docked: str | None


class VisitedSystemRow(BaseModel):
    """Commander-observed system visit history row."""

    model_config = ConfigDict(extra="forbid")

    star_system: str
    observed_events: int
    first_seen: str | None
    last_seen: str | None
    source_events: list[SystemSourceEventRow]
    # Empty means visited but never docked — not "unknown".
    docked_stations: list[SystemDockedStationRow]
    # Commander-authored; None means nothing was written for this system.
    note: str | None
    note_updated_at: str | None


class VisitedSystemsResponse(BaseModel):
    """Commander-observed system visit catalog."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    source_events: list[str]
    returned: int
    limit: int
    systems: list[VisitedSystemRow]
    nullprovider_safe: bool


class VisitedStationRow(BaseModel):
    """Commander-observed station docking catalog row."""

    model_config = ConfigDict(extra="forbid")

    station_name: str
    star_system: str | None
    station_type: str | None
    docked_count: int
    first_docked: str | None
    last_docked: str | None


class VisitedStationsResponse(BaseModel):
    """Commander-observed station docking catalog."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    source_events: list[str]
    returned: int
    limit: int
    stations: list[VisitedStationRow]
    nullprovider_safe: bool


class SessionOperationRow(BaseModel):
    """Recorded count for one operation class within a session."""

    model_config = ConfigDict(extra="forbid")

    operation: str
    recorded: int


class SessionTimelineRow(BaseModel):
    """One recorded commander session (a sitting the recorder witnessed)."""

    model_config = ConfigDict(extra="forbid")

    session_id: int
    journal_filename: str
    commander_name: str | None
    ship_type: str | None
    started_at: str | None
    ended_at: str | None
    first_event_at: str | None
    last_event_at: str | None
    observed_duration_seconds: int | None
    end_recorded: bool
    event_count: int
    systems_visited: int
    stations_docked: int
    operations: list[SessionOperationRow]
    is_most_recent: bool
    freshness: str
    truth_class: str


class SessionTimelineResponse(BaseModel):
    """Bounded newest-first commander session timeline."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str
    source: str
    truth_class: str
    caveat: str
    operation: str | None
    operation_classes: list[str]
    returned: int
    total: int
    limit: int
    sessions: list[SessionTimelineRow]
    nullprovider_safe: bool


# --- Endpoints ---------------------------------------------------------------


@router.get("/sessions", response_model=SessionTimelineResponse)
async def get_session_timeline(
    operation: str | None = Query(default=None, max_length=32),
    limit: int | None = Query(default=None, ge=1, le=intel_history.SESSIONS_MAX_LIMIT),
) -> dict[str, Any]:
    """Commander session timeline (local flight recorder, bounded)."""
    factory = _ensure_session_factory()
    try:
        return await intel_history.session_timeline(
            factory, limit=limit, operation=operation
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/journal/search", response_model=JournalSearchResponse)
async def search_journal(
    event_type: str | None = Query(default=None, max_length=64),
    since: str | None = Query(default=None, max_length=40),
    until: str | None = Query(default=None, max_length=40),
    contains: str | None = Query(default=None, max_length=200),
    session_id: int | None = Query(default=None, ge=1),
    limit: int | None = Query(default=None, ge=1, le=intel_history.SEARCH_MAX_LIMIT),
) -> dict[str, Any]:
    """Search recorded journal events (local flight recorder, bounded)."""
    factory = _ensure_session_factory()
    return await intel_history.search_journal_events(
        factory,
        event_type=event_type,
        since=_parse_optional_timestamp(since, "since"),
        until=_parse_optional_timestamp(until, "until"),
        contains=contains,
        session_id=session_id,
        limit=limit,
    )


@router.get("/journal/event-types", response_model=RecordedEventTypesResponse)
async def get_recorded_event_types(
    limit: int | None = Query(
        default=None, ge=1, le=intel_history.EVENT_TYPES_MAX_LIMIT
    ),
) -> dict[str, Any]:
    """Distinct recorded event types with counts (local flight recorder)."""
    factory = _ensure_session_factory()
    return await intel_history.recorded_event_types(factory, limit=limit)


@router.get("/history/systems", response_model=VisitedSystemsResponse)
async def get_visited_systems(
    limit: int | None = Query(default=None, ge=1, le=intel_history.HISTORY_MAX_LIMIT),
) -> dict[str, Any]:
    """Commander-observed system visit history (local flight recorder)."""
    factory = _ensure_session_factory()
    payload = await intel_history.visited_systems(factory, limit=limit)
    systems = payload.get("systems", [])
    notes: dict[str, Any] = {}
    if _system_notes is not None and systems:
        notes = await _system_notes.notes_for(
            [row["star_system"] for row in systems if row.get("star_system")]
        )
    for row in systems:
        entry = notes.get(row.get("star_system"))
        row["note"] = entry["note"] if entry else None
        row["note_updated_at"] = entry["updated_at"] if entry else None
    return payload


@router.get("/history/stations", response_model=VisitedStationsResponse)
async def get_visited_stations(
    limit: int | None = Query(default=None, ge=1, le=intel_history.HISTORY_MAX_LIMIT),
) -> dict[str, Any]:
    """Commander-observed station docking catalog (local flight recorder)."""
    factory = _ensure_session_factory()
    return await intel_history.visited_stations(factory, limit=limit)


@router.get("/history/exploration/trips", response_model=ExplorationTripsResponse)
async def get_exploration_trips(
    limit: int | None = Query(
        default=None, ge=1, le=exploration_history.TRIPS_MAX_LIMIT
    ),
) -> dict[str, Any]:
    """Exploration timeline by recorded session, with the Commander's notes.

    The notes are the second half of LNA-034 ("trip timeline and discovery
    notes"). They are attached per trip for the systems surveyed on it, so a
    Commander reads what they wrote next to what they found. The note
    service is optional: without it a trip correctly reports no notes, which
    is not the same as having none.
    """
    factory = _ensure_session_factory()
    payload = await exploration_history.exploration_trips(factory, limit=limit)

    trips = payload.get("trips", [])
    notes: dict[str, Any] = {}
    if _system_notes is not None and trips:
        surveyed = sorted(
            {name for trip in trips for name in trip.get("systems_surveyed", [])}
        )
        if surveyed:
            notes = await _system_notes.notes_for(surveyed)
    for trip in trips:
        trip["notes"] = [
            {
                "star_system": name,
                "note": notes[name]["note"],
                "updated_at": notes[name]["updated_at"],
            }
            for name in trip.get("systems_surveyed", [])
            if notes.get(name)
        ]
        # Distinguishes "the note service is not wired" from "you wrote none".
        trip["notes_available"] = _system_notes is not None
    return payload


@router.get("/history/exploration/systems", response_model=ExploredSystemsResponse)
async def get_explored_systems(
    limit: int | None = Query(
        default=None, ge=1, le=exploration_history.EXPLORATION_MAX_LIMIT
    ),
) -> dict[str, Any]:
    """Per-system survey record: scanned bodies against the system's own count."""
    factory = _ensure_session_factory()
    return await exploration_history.explored_systems(factory, limit=limit)


@router.get("/history/exploration/earnings", response_model=ExplorationEarningsResponse)
async def get_exploration_earnings() -> dict[str, Any]:
    """Credits actually received for exploration and exobiology data."""
    factory = _ensure_session_factory()
    return await exploration_history.exploration_earnings(factory)


@router.get("/history/exploration/biology", response_model=BiologicalSignalsResponse)
async def get_biological_signals(
    star_system: str | None = Query(default=None, max_length=128),
    limit: int | None = Query(default=None, ge=1, le=exobiology_intel.MAX_LIMIT),
) -> dict[str, Any]:
    """Observed biological signals; candidate genera only where unreported."""
    factory = _ensure_session_factory()
    return await exobiology_intel.biological_signals(
        factory, star_system=star_system, limit=limit
    )


@router.get("/history/exploration/bodies", response_model=ScannedBodiesResponse)
async def get_scanned_bodies(
    star_system: str | None = Query(default=None, max_length=128),
    limit: int | None = Query(
        default=None, ge=1, le=exploration_history.BODIES_MAX_LIMIT
    ),
) -> dict[str, Any]:
    """Commander-observed body scan detail, optionally scoped to one system."""
    factory = _ensure_session_factory()
    return await exploration_history.scanned_bodies(
        factory, star_system=star_system, limit=limit
    )
