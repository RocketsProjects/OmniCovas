"""Event Home Matrix parser and home-status coverage gate.

PB-EHM-01 foundation only: this module reads the committed Markdown matrix and
classifies its rows for tests and later playbook checks. It does not read Elite
Saved Games files, activate providers, or claim runtime implementation coverage.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

DEFAULT_MATRIX_PATH = (
    Path(__file__).resolve().parents[2]
    / "authority_files"
    / "documents"
    / "03_backend_source_compliance"
    / "OmniCOVAS_Elite_Event_Home_Matrix_v1_0.md"
)

REQUIRED_V1_1_CORRECTION_EVENTS = frozenset(
    {
        "Fileheader",
        "CarrierLocation",
        "DeliverPowerMicroResources",
        "RequestPowerMicroResources",
        "PowerplayMerits",
        "PowerplayRank",
        "SuitLoadout",
        "ShipRedeemed",
        "ShipyardBuy",
        "ShipyardRedeem",
    }
)

DEFERRED_LOCAL_SURFACES = frozenset(
    {"Backpack.json", "ShipLocker.json", "FCMaterials.json"}
)

_COMPANION_SURFACES = (
    "Cargo.json",
    "Market.json",
    "Outfitting.json",
    "Shipyard.json",
    "ModulesInfo.json",
    "NavRoute.json",
    "Backpack.json",
    "ShipLocker.json",
    "FCMaterials.json",
)

_ROUTE_HOME_MARKERS = (
    "Dashboard",
    "Command Surface",
    "Operations",
    "Intel",
    "Navigation",
    "Systems",
    "Settings",
    "Overlay",
    "Wallet",
    "Cargo Watch",
    "Ship Watch",
    "Combat Watch",
    "Fuel Watch",
    "Legal Watch",
    "Route Watch",
)

_DEFERRED_MARKERS = (
    "deferred",
    "future",
    "reserved",
    "proof-first",
    "raw-only",
)

_CONFLICT_MARKERS = (
    "conflict",
    "ambiguous",
    "needs authority review",
    "must be repo/manual verified",
    "do not treat as frontier source",
)

_EVENT_TABLE_HEADER = (
    "Event",
    "Collectable data",
    "Primary home",
    "Usability / consumers",
)
_SURFACE_TABLE_HEADER = (
    "Surface",
    "Local audit result",
    "Current repo classification from audit",
    "Declared homes",
    "Data harvested / notes",
)
_STATUS_TABLE_HEADER = (
    "Field / family",
    "Declared homes",
    "Data harvested",
    "Implementation note",
)


class CoverageClassification(str, Enum):
    """PB-EHM coverage vocabulary."""

    END_TO_END_ACTIVE = "END_TO_END_ACTIVE"
    BACKEND_ACTIVE_NO_UI = "BACKEND_ACTIVE_NO_UI"
    RAW_LOG_ONLY = "RAW_LOG_ONLY"
    REGISTERED_UNHANDLED = "REGISTERED_UNHANDLED"
    HANDLED_NO_TEST = "HANDLED_NO_TEST"
    UI_ONLY_NO_SOURCE = "UI_ONLY_NO_SOURCE"
    MATRIX_ONLY_MISSING = "MATRIX_ONLY_MISSING"
    DEFERRED_OR_RESERVED = "DEFERRED_OR_RESERVED"
    CONFLICT_OR_AMBIGUOUS = "CONFLICT_OR_AMBIGUOUS"


class HomeStatus(str, Enum):
    """Home-status categories accepted by the PB-EHM-01 gate."""

    ROUTE_HOME = "route_home"
    RAW_PROOF_HOME = "raw_proof_home"
    DEFERRED_OR_RESERVED = "deferred_or_reserved"
    CONFLICT_OR_AMBIGUOUS = "conflict_or_ambiguous"


class MatrixRowKind(str, Enum):
    """Kinds of matrix rows that PB-EHM-01 treats as coverage rows."""

    EVENT = "event"
    LOCAL_SOURCE_SURFACE = "local_source_surface"
    STATUS_FIELD = "status_field"


@dataclass(frozen=True)
class MarkdownTableRow:
    section: str
    header: tuple[str, ...]
    cells: tuple[str, ...]
    line_number: int

    def cell(self, key: str) -> str:
        return dict(zip(self.header, self.cells, strict=True)).get(key, "")


@dataclass(frozen=True)
class MatrixCoverageRow:
    """Parsed matrix event/source row with derived PB-EHM-01 gate fields."""

    kind: MatrixRowKind
    section: str
    line_number: int
    name_cell: str
    names: tuple[str, ...]
    source_surface: str
    declared_home: str
    notes: str
    classification: CoverageClassification
    home_statuses: frozenset[HomeStatus]
    deferred_reason: str | None
    conflict_reason: str | None
    implementation_priority: str
    test_proof_expectation: str

    @property
    def primary_name(self) -> str:
        if self.names:
            return self.names[0]
        return _plain_text(self.name_cell)

    @property
    def has_home_status(self) -> bool:
        return bool(self.home_statuses)


@dataclass(frozen=True)
class CoverageGateReport:
    """Counters and row sets for the Event Home coverage gate."""

    rows: tuple[MatrixCoverageRow, ...]

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    @property
    def rows_with_declared_home_status(self) -> tuple[MatrixCoverageRow, ...]:
        return tuple(row for row in self.rows if row.has_home_status)

    @property
    def homeless_rows(self) -> tuple[MatrixCoverageRow, ...]:
        return tuple(row for row in self.rows if not row.has_home_status)

    @property
    def deferred_reserved_rows(self) -> tuple[MatrixCoverageRow, ...]:
        return tuple(
            row
            for row in self.rows
            if HomeStatus.DEFERRED_OR_RESERVED in row.home_statuses
        )

    @property
    def deferred_rows_missing_reason(self) -> tuple[MatrixCoverageRow, ...]:
        return tuple(
            row
            for row in self.deferred_reserved_rows
            if row.deferred_reason is None or not row.deferred_reason.strip()
        )

    @property
    def conflict_ambiguous_rows(self) -> tuple[MatrixCoverageRow, ...]:
        return tuple(
            row
            for row in self.rows
            if HomeStatus.CONFLICT_OR_AMBIGUOUS in row.home_statuses
        )

    @property
    def proof_home_rows(self) -> tuple[MatrixCoverageRow, ...]:
        return tuple(
            row for row in self.rows if HomeStatus.RAW_PROOF_HOME in row.home_statuses
        )

    @property
    def route_home_rows(self) -> tuple[MatrixCoverageRow, ...]:
        return tuple(
            row for row in self.rows if HomeStatus.ROUTE_HOME in row.home_statuses
        )

    @property
    def passes_home_status_gate(self) -> bool:
        return not self.homeless_rows and not self.deferred_rows_missing_reason

    def counters(self) -> dict[str, int]:
        return {
            "TOTAL_MATRIX_EVENTS": self.total_rows,
            "OBSERVED_LOCAL_EVENTS": len(
                [row for row in self.rows if _is_observed_local(row)]
            ),
            "EVENTS_WITH_RAW_HOME": len(self.proof_home_rows),
            "EVENTS_WITH_NORMALIZED_HOME": len(
                [
                    row
                    for row in self.rows
                    if row.classification
                    in {
                        CoverageClassification.END_TO_END_ACTIVE,
                        CoverageClassification.BACKEND_ACTIVE_NO_UI,
                        CoverageClassification.HANDLED_NO_TEST,
                    }
                ]
            ),
            "EVENTS_WITH_ROUTE_UI_HOME": len(self.route_home_rows),
            "EVENTS_WITH_PROOF_HOME": len(self.proof_home_rows),
            "EVENTS_WITH_TESTS": len(
                [
                    row
                    for row in self.rows
                    if row.classification
                    in {
                        CoverageClassification.END_TO_END_ACTIVE,
                        CoverageClassification.HANDLED_NO_TEST,
                    }
                    or "test" in row.test_proof_expectation.lower()
                ]
            ),
            "EVENTS_DEFERRED_WITH_REASON": len(self.deferred_reserved_rows)
            - len(self.deferred_rows_missing_reason),
            "EVENTS_MISSING_HOME": len(self.homeless_rows),
            "EVENTS_CONFLICT_OR_AMBIGUOUS": len(self.conflict_ambiguous_rows),
        }

    def rows_matching_name(self, name: str) -> tuple[MatrixCoverageRow, ...]:
        return tuple(row for row in self.rows if name in row.names)


def load_event_home_report(
    matrix_path: Path = DEFAULT_MATRIX_PATH,
) -> CoverageGateReport:
    """Read the matrix file and return a PB-EHM-01 coverage report."""
    text = matrix_path.read_text(encoding="utf-8")
    return parse_event_home_matrix(text)


def parse_event_home_matrix(text: str) -> CoverageGateReport:
    """Parse matrix Markdown into event/source rows for gate checks."""
    rows = tuple(_coverage_rows(parse_markdown_table_rows(text)))
    return CoverageGateReport(rows=rows)


def parse_markdown_table_rows(text: str) -> tuple[MarkdownTableRow, ...]:
    """Parse Markdown table rows while tolerating blank lines between rows."""
    rows: list[MarkdownTableRow] = []
    section = ""
    pending_header: tuple[str, ...] | None = None
    active_header: tuple[str, ...] | None = None

    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip()
            pending_header = None
            active_header = None
            continue
        if not stripped.startswith("|"):
            continue

        cells = _split_table_row(stripped)
        if not cells:
            continue
        if _is_separator_row(cells):
            if pending_header is not None:
                active_header = pending_header
            continue
        if active_header is None:
            pending_header = cells
            continue
        if len(cells) != len(active_header):
            continue
        rows.append(
            MarkdownTableRow(
                section=section,
                header=active_header,
                cells=cells,
                line_number=line_number,
            )
        )
    return tuple(rows)


def _coverage_rows(
    markdown_rows: tuple[MarkdownTableRow, ...],
) -> tuple[MatrixCoverageRow, ...]:
    rows: list[MatrixCoverageRow] = []
    for row in markdown_rows:
        header = row.header
        if header == _EVENT_TABLE_HEADER:
            rows.append(_event_coverage_row(row))
        elif header == _SURFACE_TABLE_HEADER:
            rows.append(_surface_coverage_row(row))
        elif header == _STATUS_TABLE_HEADER:
            rows.append(_status_coverage_row(row))
    return tuple(rows)


def _event_coverage_row(row: MarkdownTableRow) -> MatrixCoverageRow:
    name_cell = row.cell("Event")
    data = row.cell("Collectable data")
    home = row.cell("Primary home")
    notes = row.cell("Usability / consumers")
    row_text = " ".join((name_cell, data, home, notes))
    classification = _classify_row(row_text, explicit_text="")
    return _build_coverage_row(
        kind=MatrixRowKind.EVENT,
        section=row.section,
        line_number=row.line_number,
        name_cell=name_cell,
        source_surface=_event_source_surface(row_text),
        declared_home=home,
        notes=notes,
        classification=classification,
        row_text=row_text,
    )


def _surface_coverage_row(row: MarkdownTableRow) -> MatrixCoverageRow:
    name_cell = row.cell("Surface")
    audit_result = row.cell("Local audit result")
    explicit = row.cell("Current repo classification from audit")
    home = row.cell("Declared homes")
    notes = row.cell("Data harvested / notes")
    row_text = " ".join((name_cell, audit_result, explicit, home, notes))
    return _build_coverage_row(
        kind=MatrixRowKind.LOCAL_SOURCE_SURFACE,
        section=row.section,
        line_number=row.line_number,
        name_cell=name_cell,
        source_surface=_plain_text(name_cell),
        declared_home=home,
        notes=notes,
        classification=_classify_row(row_text, explicit_text=explicit),
        row_text=row_text,
    )


def _status_coverage_row(row: MarkdownTableRow) -> MatrixCoverageRow:
    name_cell = row.cell("Field / family")
    home = row.cell("Declared homes")
    harvested = row.cell("Data harvested")
    notes = row.cell("Implementation note")
    row_text = " ".join((name_cell, home, harvested, notes))
    return _build_coverage_row(
        kind=MatrixRowKind.STATUS_FIELD,
        section=row.section,
        line_number=row.line_number,
        name_cell=name_cell,
        source_surface="Status.json",
        declared_home=home,
        notes=notes,
        classification=_classify_row(row_text, explicit_text=""),
        row_text=row_text,
    )


def _build_coverage_row(
    *,
    kind: MatrixRowKind,
    section: str,
    line_number: int,
    name_cell: str,
    source_surface: str,
    declared_home: str,
    notes: str,
    classification: CoverageClassification,
    row_text: str,
) -> MatrixCoverageRow:
    home_statuses = _home_statuses(
        declared_home=declared_home,
        notes=notes,
        classification=classification,
        row_text=row_text,
        kind=kind,
    )
    deferred_reason = _reason_for_status(
        HomeStatus.DEFERRED_OR_RESERVED, home_statuses, notes, row_text
    )
    conflict_reason = _reason_for_status(
        HomeStatus.CONFLICT_OR_AMBIGUOUS, home_statuses, notes, row_text
    )
    return MatrixCoverageRow(
        kind=kind,
        section=section,
        line_number=line_number,
        name_cell=name_cell,
        names=_event_names(name_cell),
        source_surface=source_surface,
        declared_home=declared_home,
        notes=notes,
        classification=classification,
        home_statuses=home_statuses,
        deferred_reason=deferred_reason,
        conflict_reason=conflict_reason,
        implementation_priority=_implementation_priority(row_text, classification),
        test_proof_expectation=_test_proof_expectation(home_statuses, classification),
    )


def _split_table_row(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return tuple(cell.strip() for cell in stripped.split("|"))


def _is_separator_row(cells: tuple[str, ...]) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _event_names(cell: str) -> tuple[str, ...]:
    names = tuple(match.strip() for match in re.findall(r"`([^`]+)`", cell))
    if names:
        return names
    plain = _plain_text(cell)
    return (plain,) if plain else ()


def _plain_text(value: str) -> str:
    plain = re.sub(r"`([^`]+)`", r"\1", value)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain


def _classify_row(
    row_text: str,
    *,
    explicit_text: str,
) -> CoverageClassification:
    explicit_upper = explicit_text.upper()
    for classification in CoverageClassification:
        if classification.value in explicit_upper:
            return classification
    lowered = row_text.lower()
    if "matrix_candidate_needs_authority_review" in explicit_upper.lower():
        return CoverageClassification.CONFLICT_OR_AMBIGUOUS
    if any(marker in lowered for marker in _CONFLICT_MARKERS):
        return CoverageClassification.CONFLICT_OR_AMBIGUOUS
    if "raw-only" in lowered or "raw-log-only" in lowered:
        return CoverageClassification.RAW_LOG_ONLY
    if any(marker in lowered for marker in ("future", "deferred", "reserved")):
        return CoverageClassification.DEFERRED_OR_RESERVED
    return CoverageClassification.REGISTERED_UNHANDLED


def _home_statuses(
    *,
    declared_home: str,
    notes: str,
    classification: CoverageClassification,
    row_text: str,
    kind: MatrixRowKind,
) -> frozenset[HomeStatus]:
    # PB-EHM-02 locks Activity Log as the universal fallback/proof home for
    # every parsed matrix row, including local source/status surfaces that do
    # not yet have a route-specific UI.
    statuses: set[HomeStatus] = {HomeStatus.RAW_PROOF_HOME}
    lowered = row_text.lower()
    home_plain = _plain_text(declared_home)

    if home_plain and home_plain.lower() != "none":
        statuses.add(HomeStatus.ROUTE_HOME)
    if any(marker.lower() in declared_home.lower() for marker in _ROUTE_HOME_MARKERS):
        statuses.add(HomeStatus.ROUTE_HOME)

    if (
        "activity log" in lowered
        or "proof" in lowered
        or "raw-only" in lowered
        or kind == MatrixRowKind.EVENT
    ):
        statuses.add(HomeStatus.RAW_PROOF_HOME)

    if classification == CoverageClassification.DEFERRED_OR_RESERVED or any(
        marker in lowered for marker in _DEFERRED_MARKERS
    ):
        statuses.add(HomeStatus.DEFERRED_OR_RESERVED)

    if classification == CoverageClassification.CONFLICT_OR_AMBIGUOUS or any(
        marker in lowered for marker in _CONFLICT_MARKERS
    ):
        statuses.add(HomeStatus.CONFLICT_OR_AMBIGUOUS)

    return frozenset(statuses)


def _reason_for_status(
    status: HomeStatus,
    home_statuses: frozenset[HomeStatus],
    notes: str,
    row_text: str,
) -> str | None:
    if status not in home_statuses:
        return None
    if notes.strip():
        return _plain_text(notes)
    return _plain_text(row_text)


def _implementation_priority(
    row_text: str,
    classification: CoverageClassification,
) -> str:
    if any(name in row_text for name in REQUIRED_V1_1_CORRECTION_EVENTS):
        return "P0_V1_1_CORRECTION_LOCK"
    if classification == CoverageClassification.CONFLICT_OR_AMBIGUOUS:
        return "P0_MATRIX_REPAIR_REQUIRED"
    if "P1" in row_text:
        return "P1_MATRIX_PRIORITY"
    if classification == CoverageClassification.DEFERRED_OR_RESERVED:
        return "P3_DEFERRED_PROOF_FIRST"
    return "MATRIX_DECLARED_BASELINE"


def _test_proof_expectation(
    home_statuses: frozenset[HomeStatus],
    classification: CoverageClassification,
) -> str:
    if HomeStatus.CONFLICT_OR_AMBIGUOUS in home_statuses:
        return "Report conflict; block row implementation until matrix/docs repair."
    if HomeStatus.DEFERRED_OR_RESERVED in home_statuses:
        return "Keep proof-visible with explicit deferred/reserved reason."
    if HomeStatus.RAW_PROOF_HOME in home_statuses:
        return "Activity Log raw/proof home must remain testable."
    if classification == CoverageClassification.END_TO_END_ACTIVE:
        return "Regression tests should preserve active route/proof behavior."
    return "Parser gate must keep declared home/status visible."


def _event_source_surface(row_text: str) -> str:
    for surface in _COMPANION_SURFACES:
        if surface in row_text:
            return f"Journal / {surface}"
    return "Journal"


def _is_observed_local(row: MatrixCoverageRow) -> bool:
    text = " ".join((row.name_cell, row.declared_home, row.notes)).lower()
    return (
        "observed" in text
        or row.source_surface in _COMPANION_SURFACES
        or row.source_surface == "Status.json"
        or row.source_surface == "Journal"
    )
