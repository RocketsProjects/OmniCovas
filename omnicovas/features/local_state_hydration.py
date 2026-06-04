"""Bounded local-file hydration for last-known Elite Dangerous state.

This module repairs cold-start context without external providers. It scans a
small set of recent Journal files plus local companion snapshots, then applies
only missing StateManager fields. It never copies raw journal data and never
parses the full journal corpus.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omnicovas.core.state_manager import (
    FieldSource,
    LocalStationContext,
    LocalSystemContext,
    StateManager,
    TelemetrySource,
)
from omnicovas.features import loadout, local_context_facts, ship_state

logger = logging.getLogger(__name__)

MAX_RECENT_JOURNAL_FILES = 5
MAX_JOURNAL_BYTES_PER_FILE = 4 * 1024 * 1024
ACTIVE_JOURNAL_MTIME_SECONDS = 120

_JOURNAL_RE = re.compile(
    r"^Journal\.(\d{4}-\d{2}-\d{2}T\d{2}:?\d{2}:?\d{2})\.\d+\.log$"
)


@dataclass
class HydrationScanResult:
    """Recent local-file evidence used by local-context snapshot builders."""

    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, FieldSource] = field(default_factory=dict)
    journal_files_scanned: tuple[str, ...] = ()
    last_journal_event_at: str | None = None
    last_journal_event_type: str | None = None
    last_journal_file: str | None = None
    last_journal_file_mtime_at: str | None = None
    recent_journal_activity: bool = False
    companion_activity_at: str | None = None
    companion_activity_file: str | None = None
    files_available: bool = False
    caveat: str = (
        "No recent local Journal or companion snapshot was available for "
        "startup hydration."
    )


_SCAN_CACHE: dict[tuple[Any, ...], HydrationScanResult] = {}


def hydrate_local_state_if_needed(
    state: StateManager | None,
    *,
    journal_dir_path: Path | None = None,
    status_path: Path | None = None,
    market_path: Path | None = None,
    outfitting_path: Path | None = None,
    shipyard_path: Path | None = None,
    cargo_path: Path | None = None,
    modules_info_path: Path | None = None,
) -> HydrationScanResult:
    """Scan bounded local files and apply missing state fields.

    Existing live state wins. This is a repair pass for empty startup context,
    not a second event pipeline.
    """
    result = scan_recent_local_state(
        journal_dir_path=journal_dir_path,
        status_path=status_path,
        market_path=market_path,
        outfitting_path=outfitting_path,
        shipyard_path=shipyard_path,
        cargo_path=cargo_path,
        modules_info_path=modules_info_path,
    )
    if state is not None:
        _apply_missing_values(state, result)
    return result


def scan_recent_local_state(
    *,
    journal_dir_path: Path | None = None,
    status_path: Path | None = None,
    market_path: Path | None = None,
    outfitting_path: Path | None = None,
    shipyard_path: Path | None = None,
    cargo_path: Path | None = None,
    modules_info_path: Path | None = None,
) -> HydrationScanResult:
    """Return a cached bounded scan of recent local Elite files."""
    journal_dir = journal_dir_path or _default_elite_dir()
    status = status_path or _default_companion_path("Status.json")
    market = market_path or _default_companion_path("Market.json")
    outfitting = outfitting_path or _default_companion_path("Outfitting.json")
    shipyard = shipyard_path or _default_companion_path("Shipyard.json")
    cargo = cargo_path or _default_companion_path("Cargo.json")
    modules_info = modules_info_path or _default_companion_path("ModulesInfo.json")

    journal_files = _recent_journal_files(journal_dir)
    cache_key = _scan_cache_key(
        journal_files, (status, market, outfitting, shipyard, cargo, modules_info)
    )
    cached = _SCAN_CACHE.get(cache_key)
    if cached is not None:
        return cached

    result = HydrationScanResult(
        journal_files_scanned=tuple(path.name for path in journal_files)
    )
    for path in sorted(journal_files, key=_journal_sort_key):
        _scan_journal_file(path, result)

    _apply_status_snapshot(status, result)
    _record_companion_activity(
        market, outfitting, shipyard, cargo, modules_info, result
    )
    result.files_available = (
        bool(journal_files) or result.companion_activity_at is not None
    )

    if journal_files:
        newest = max(journal_files, key=lambda p: p.stat().st_mtime)
        result.last_journal_file_mtime_at = _timestamp_from_mtime(newest)
        result.recent_journal_activity = _is_recent_mtime(newest)
        result.caveat = (
            "Startup hydration uses a bounded scan of recent Journal files "
            f"(max {MAX_RECENT_JOURNAL_FILES} files, "
            f"{MAX_JOURNAL_BYTES_PER_FILE // (1024 * 1024)} MiB per file)."
        )
    elif result.companion_activity_at is not None:
        result.caveat = (
            "Only companion snapshots were available; no recent Journal file "
            "was available for event-history hydration."
        )

    _SCAN_CACHE.clear()
    _SCAN_CACHE[cache_key] = result
    return result


def _scan_journal_file(path: Path, result: HydrationScanResult) -> None:
    try:
        lines = _bounded_journal_lines(path)
    except OSError as exc:
        logger.debug("Journal hydration read skipped for %s: %s", path.name, exc)
        return

    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("event")
        if not isinstance(event_type, str):
            continue
        ts = _string_or_none(event.get("timestamp"))
        result.last_journal_event_at = ts
        result.last_journal_event_type = event_type
        result.last_journal_file = path.name
        _apply_journal_event(event, path.name, result)


def _bounded_journal_lines(path: Path) -> list[str]:
    size = path.stat().st_size
    with path.open(encoding="utf-8") as handle:
        if size > MAX_JOURNAL_BYTES_PER_FILE:
            handle.seek(size - MAX_JOURNAL_BYTES_PER_FILE)
            handle.readline()
        return [line.strip() for line in handle if line.strip()]


def _apply_journal_event(
    event: dict[str, Any],
    source_file: str,
    result: HydrationScanResult,
) -> None:
    event_type = str(event.get("event"))
    ts = _string_or_none(event.get("timestamp"))

    if event_type == "Docked":
        station_ctx = local_context_facts.build_local_station_context(
            event, source_event="Docked", source_file=source_file
        )
        _set(result, "local_station_context", station_ctx, ts, source_file)
        _set(result, "is_docked", True, ts, source_file)
        _set_if_present(
            result, "current_station", event.get("StationName"), ts, source_file
        )
        _set_if_present(
            result, "current_system", event.get("StarSystem"), ts, source_file
        )
        return

    if event_type == "Location":
        _apply_location_event(event, source_file, result)
        return

    if event_type == "FSDJump":
        system_ctx = local_context_facts.build_local_system_context(
            event, source_event="FSDJump", source_file=source_file
        )
        _set(result, "local_system_context", system_ctx, ts, source_file)
        _set_if_present(
            result, "current_system", event.get("StarSystem"), ts, source_file
        )
        _invalidate_station(result, ts, source_file)
        _set(result, "is_in_supercruise", True, ts, source_file)
        return

    if event_type == "CarrierJump":
        system_ctx = local_context_facts.build_local_system_context(
            event, source_event="CarrierJump", source_file=source_file
        )
        _set(result, "local_system_context", system_ctx, ts, source_file)
        _set_if_present(
            result, "current_system", event.get("StarSystem"), ts, source_file
        )
        return

    if event_type in {"Undocked", "SupercruiseEntry", "StartJump"}:
        _invalidate_station(result, ts, source_file)
        return

    if event_type == "LoadGame":
        _apply_load_game(event, source_file, result)
        return

    if event_type == "Loadout":
        _apply_loadout(event, source_file, result)
        return

    if event_type == "Cargo":
        _apply_cargo(event, source_file, result)


def _apply_location_event(
    event: dict[str, Any],
    source_file: str,
    result: HydrationScanResult,
) -> None:
    ts = _string_or_none(event.get("timestamp"))
    docked = event.get("Docked")
    if docked is True:
        station_ctx = local_context_facts.build_local_station_context(
            event, source_event="Location", source_file=source_file
        )
        _set(result, "local_station_context", station_ctx, ts, source_file)
        _set(result, "is_docked", True, ts, source_file)
        _set(result, "is_in_supercruise", False, ts, source_file)
        _set_if_present(
            result, "current_station", event.get("StationName"), ts, source_file
        )
    elif docked is False:
        _invalidate_station(result, ts, source_file)

    existing = result.values.get("local_system_context")
    if not isinstance(existing, LocalSystemContext):
        existing = None
    if local_context_facts.should_apply_location_system_context(existing, event):
        system_ctx = local_context_facts.build_local_system_context(
            event, source_event="Location", source_file=source_file
        )
        _set(result, "local_system_context", system_ctx, ts, source_file)
    _set_if_present(result, "current_system", event.get("StarSystem"), ts, source_file)


def _apply_load_game(
    event: dict[str, Any],
    source_file: str,
    result: HydrationScanResult,
) -> None:
    ts = _string_or_none(event.get("timestamp"))
    mapping = {
        "current_ship_type": event.get("Ship"),
        "current_ship_id": event.get("ShipID"),
        "current_ship_name": event.get("ShipName"),
        "current_ship_ident": event.get("ShipIdent"),
        "commander_name": event.get("Commander"),
        "credit_balance": event.get("Credits"),
        "loan": event.get("Loan"),
    }
    for field_name, value in mapping.items():
        _set_if_present(result, field_name, value, ts, source_file)


def _apply_loadout(
    event: dict[str, Any],
    source_file: str,
    result: HydrationScanResult,
) -> None:
    ts = _string_or_none(event.get("timestamp"))
    mapping = {
        "current_ship_type": event.get("Ship"),
        "current_ship_id": event.get("ShipID"),
        "current_ship_name": event.get("ShipName"),
        "current_ship_ident": event.get("ShipIdent"),
        "hull_health": event.get("HullHealth"),
        "jump_range_ly": event.get("MaxJumpRange"),
        "hull_value": event.get("HullValue"),
        "modules_value": event.get("ModulesValue"),
        "rebuy_cost": event.get("Rebuy"),
        "cargo_capacity": event.get("CargoCapacity"),
    }
    for field_name, value in mapping.items():
        _set_if_present(result, field_name, value, ts, source_file)

    fuel_capacity = event.get("FuelCapacity")
    if isinstance(fuel_capacity, dict):
        _set_if_present(
            result, "fuel_capacity_main", fuel_capacity.get("Main"), ts, source_file
        )
        _set_if_present(
            result,
            "fuel_capacity_reserve",
            fuel_capacity.get("Reserve"),
            ts,
            source_file,
        )

    modules = loadout.modules_from_loadout_event(event)
    if modules:
        _set(result, "modules", modules, ts, source_file)
    modules_raw = event.get("Modules", [])
    _set(
        result,
        "loadout_hash",
        ship_state.compute_loadout_hash(
            modules_raw if isinstance(modules_raw, list) else []
        ),
        ts,
        source_file,
    )


def _apply_cargo(
    event: dict[str, Any],
    source_file: str,
    result: HydrationScanResult,
) -> None:
    ts = _string_or_none(event.get("timestamp"))
    vessel = event.get("Vessel")
    if vessel is not None and vessel != "Ship":
        return
    inventory_raw = event.get("Inventory", [])
    inventory: dict[str, int] = {}
    if isinstance(inventory_raw, list):
        for entry in inventory_raw:
            if not isinstance(entry, dict):
                continue
            name = entry.get("Name")
            count = entry.get("Count")
            if name is None or count is None:
                continue
            try:
                inventory[str(name)] = int(count)
            except (TypeError, ValueError):
                continue
    count = event.get("Count")
    if isinstance(count, (int, float)) and not isinstance(count, bool):
        _set(result, "cargo_count", int(count), ts, source_file)
    elif inventory:
        _set(result, "cargo_count", sum(inventory.values()), ts, source_file)
    _set(result, "cargo_inventory", inventory, ts, source_file)
    snapshot = local_context_facts.build_cargo_hold_snapshot(
        event,
        capacity=_int_or_none(result.values.get("cargo_capacity")),
        source_event="Cargo",
        source_file=source_file,
    )
    _set(result, "cargo_hold_snapshot", snapshot, ts, source_file)


def _apply_status_snapshot(
    status_path: Path | None,
    result: HydrationScanResult,
) -> None:
    raw = _read_json_file(status_path)
    if raw is None:
        return
    ts = _string_or_none(raw.get("timestamp"))
    source_file = status_path.name if status_path is not None else "Status.json"
    balance = raw.get("Balance")
    if isinstance(balance, (int, float)) and not isinstance(balance, bool):
        _set(
            result,
            "credit_balance",
            int(balance),
            ts,
            source_file,
            source=TelemetrySource.STATUS_JSON,
        )
    _record_companion_timestamp(status_path, raw, result)


def _record_companion_activity(
    market_path: Path | None,
    outfitting_path: Path | None,
    shipyard_path: Path | None,
    cargo_path: Path | None,
    modules_info_path: Path | None,
    result: HydrationScanResult,
) -> None:
    for path in (
        market_path,
        outfitting_path,
        shipyard_path,
        cargo_path,
        modules_info_path,
    ):
        raw = _read_json_file(path)
        if raw is None:
            continue
        _record_companion_timestamp(path, raw, result)


def _record_companion_timestamp(
    path: Path | None,
    raw: dict[str, Any],
    result: HydrationScanResult,
) -> None:
    if path is None:
        return
    ts = _string_or_none(raw.get("timestamp")) or _timestamp_from_mtime(path)
    if ts is None:
        return
    if result.companion_activity_at is None or ts > result.companion_activity_at:
        result.companion_activity_at = ts
        result.companion_activity_file = path.name


def _apply_missing_values(state: StateManager, result: HydrationScanResult) -> None:
    field_names = sorted(
        result.values,
        key=lambda name: 0 if name in {"is_docked", "is_in_supercruise"} else 1,
    )
    for field_name in field_names:
        value = result.values[field_name]
        if not _should_apply_field(state, result, field_name, value):
            continue
        source = result.sources.get(field_name)
        state.update_field(
            field_name,
            value,
            source.source if source is not None else TelemetrySource.JOURNAL,
            source.timestamp if source is not None else None,
            source.source_file if source is not None else None,
        )


def _should_apply_field(
    state: StateManager,
    result: HydrationScanResult,
    field_name: str,
    value: Any,
) -> bool:
    if value is None and field_name != "is_docked":
        return False
    if not hasattr(state.snapshot, field_name):
        return False
    current = getattr(state.snapshot, field_name)
    if field_name in {"is_docked", "is_in_supercruise"}:
        return _should_apply_boolean_context_field(
            state, result, field_name, current, value
        )
    if field_name == "local_station_context":
        return (
            isinstance(value, LocalStationContext)
            and current is None
            and state.snapshot.is_docked is not False
        )
    if field_name in {"local_system_context", "cargo_hold_snapshot"}:
        return current is None and value is not None
    if field_name in {"modules", "cargo_inventory"}:
        return not current and bool(value)
    return current is None and value is not None


def _should_apply_boolean_context_field(
    state: StateManager,
    result: HydrationScanResult,
    field_name: str,
    current: Any,
    value: Any,
) -> bool:
    if value is None:
        return current is None
    if not isinstance(value, bool):
        return False
    if current is None:
        return True
    if current == value:
        return False
    current_source = state.get_field_source(field_name)
    incoming_source = result.sources.get(field_name)
    if current_source is None or incoming_source is None:
        return False
    return incoming_source.source < current_source.source


def _invalidate_station(
    result: HydrationScanResult,
    ts: str | None,
    source_file: str,
) -> None:
    _set(result, "is_docked", False, ts, source_file)
    _set(result, "current_station", None, ts, source_file)
    _set(result, "local_station_context", None, ts, source_file)


def _set(
    result: HydrationScanResult,
    field_name: str,
    value: Any,
    timestamp: str | None,
    source_file: str,
    *,
    source: TelemetrySource = TelemetrySource.JOURNAL,
) -> None:
    result.values[field_name] = value
    result.sources[field_name] = FieldSource(
        source=source,
        timestamp=timestamp,
        source_file=source_file,
    )


def _set_if_present(
    result: HydrationScanResult,
    field_name: str,
    value: Any,
    timestamp: str | None,
    source_file: str,
) -> None:
    if value is None:
        return
    if isinstance(value, bool) and field_name not in {"is_docked", "is_in_supercruise"}:
        return
    if field_name.endswith("_id") or field_name in {
        "credit_balance",
        "loan",
        "rebuy_cost",
        "cargo_capacity",
        "hull_value",
        "modules_value",
    }:
        coerced = _int_or_none(value)
        if coerced is None:
            return
        _set(result, field_name, coerced, timestamp, source_file)
        return
    if field_name in {
        "hull_health",
        "jump_range_ly",
        "fuel_capacity_main",
        "fuel_capacity_reserve",
    }:
        coerced_float = _float_or_none(value)
        if coerced_float is None:
            return
        _set(result, field_name, coerced_float, timestamp, source_file)
        return
    _set(result, field_name, str(value), timestamp, source_file)


def _recent_journal_files(journal_dir: Path | None) -> list[Path]:
    if journal_dir is None or not journal_dir.exists():
        return []
    files = [
        path
        for path in journal_dir.iterdir()
        if path.is_file()
        and path.name.startswith("Journal.")
        and path.name.endswith(".log")
    ]
    return sorted(files, key=_journal_sort_key, reverse=True)[:MAX_RECENT_JOURNAL_FILES]


def _journal_sort_key(path: Path) -> tuple[int, float]:
    parsed = _parse_journal_filename_time(path.name)
    if parsed is not None:
        return (1, parsed.timestamp())
    try:
        return (0, path.stat().st_mtime)
    except OSError:
        return (0, 0.0)


def _parse_journal_filename_time(filename: str) -> datetime | None:
    match = _JOURNAL_RE.match(filename)
    if not match:
        return None
    ts = match.group(1).replace(":", "")
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _scan_cache_key(
    journal_files: list[Path],
    companion_files: tuple[Path | None, ...],
) -> tuple[Any, ...]:
    journal_sig = tuple(_file_signature(path) for path in journal_files)
    companion_sig = tuple(_file_signature(path) for path in companion_files)
    return (journal_sig, companion_sig)


def _file_signature(path: Path | None) -> tuple[str, str, int, int] | None:
    if path is None or not path.exists():
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return (str(path), path.name, stat.st_mtime_ns, stat.st_size)


def _read_json_file(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _default_elite_dir() -> Path | None:
    profile = os.environ.get("USERPROFILE", "")
    if not profile:
        return None
    return Path(profile) / "Saved Games" / "Frontier Developments" / "Elite Dangerous"


def _default_companion_path(filename: str) -> Path | None:
    root = _default_elite_dir()
    return None if root is None else root / filename


def _is_recent_mtime(path: Path) -> bool:
    try:
        age = datetime.now(UTC).timestamp() - path.stat().st_mtime
    except OSError:
        return False
    return age <= ACTIVE_JOURNAL_MTIME_SECONDS


def _timestamp_from_mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
    except OSError:
        return None


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
