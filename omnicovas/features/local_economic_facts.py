"""Local economic fact snapshot helpers for PB06-03.

Backend-only projection surface. Reads existing cargo StateManager data and
approved local companion JSON snapshots on demand. No watcher, no provider
client, no network call, no state mutation, and no Activity Log writes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from omnicovas.core.source_registry import SourceRegistry, SourceState
from omnicovas.core.state_manager import FieldSource, StateManager, TelemetrySource
from omnicovas.features.provider_lookups import register_providers

UNKNOWN = "Unknown"
NOT_LOADED = "Not Loaded"
NO_LOCAL_STATION_SNAPSHOT = "No local snapshot for this station"
NO_VERIFIED_SOURCE = "No Verified Source"

FRESH = "fresh"
STALE = "stale"
NOT_LOADED_FRESHNESS = "not_loaded"

TRUTH_UNKNOWN = "unknown"
TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
TRUTH_LOCAL_SCREEN_SNAPSHOT = "local_screen_snapshot"

JOURNAL_SOURCE = "Journal"

MARKET_FILE = "Market.json"
OUTFITTING_FILE = "Outfitting.json"
SHIPYARD_FILE = "Shipyard.json"


def snapshot_payload(
    state: StateManager | None,
    *,
    market_path: Path | None = None,
    outfitting_path: Path | None = None,
    shipyard_path: Path | None = None,
) -> dict[str, Any]:
    """Return the local economic snapshot for read-only API consumers."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cargo": cargo_summary_payload(state),
        "market": market_snapshot_payload(
            MARKET_FILE,
            market_path,
            state=state,
            collection_key="Items",
            item_mapper=_market_item,
            caveat=(
                "Local station market snapshot only; not live or global market truth."
            ),
        ),
        "outfitting": market_snapshot_payload(
            OUTFITTING_FILE,
            outfitting_path,
            state=state,
            collection_key="Items",
            item_mapper=_outfitting_item,
            caveat=(
                "Local station outfitting snapshot only; not global or guaranteed "
                "module availability."
            ),
        ),
        "shipyard": market_snapshot_payload(
            SHIPYARD_FILE,
            shipyard_path,
            state=state,
            collection_key="PriceList",
            item_mapper=_shipyard_item,
            caveat=(
                "Local station shipyard snapshot only; not global or guaranteed "
                "ship stock."
            ),
        ),
        "disabled_external_context": disabled_external_context_payload(),
        "nullprovider_safe": True,
    }


def cargo_summary_payload(state: StateManager | None) -> dict[str, Any]:
    """Return journal-derived cargo summary with explicit provenance."""
    source = _cargo_field_source(state)
    if state is None or source is None:
        return {
            "source": JOURNAL_SOURCE,
            "timestamp": None,
            "freshness": NOT_LOADED_FRESHNESS,
            "truth_class": TRUTH_UNKNOWN,
            "caveat": "No verified local cargo snapshot has been observed.",
            "fallback": NOT_LOADED,
            "items": None,
            "total_count": None,
            "commodity_types": None,
            "nullprovider_safe": True,
        }

    inventory = dict(state.snapshot.cargo_inventory)
    total_count = state.snapshot.cargo_count
    if total_count is None:
        total_count = sum(inventory.values())

    return {
        "source": JOURNAL_SOURCE,
        "timestamp": source.timestamp,
        "freshness": FRESH,
        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
        "caveat": "Known local cargo only; no market recommendation is implied.",
        "fallback": None,
        "items": [
            {"name": name, "count": count}
            for name, count in sorted(inventory.items(), key=lambda item: item[0])
        ],
        "total_count": total_count,
        "commodity_types": len(inventory),
        "nullprovider_safe": True,
    }


def market_snapshot_payload(
    filename: str,
    path: Path | None,
    *,
    state: StateManager | None,
    collection_key: str,
    item_mapper: Any,
    caveat: str,
) -> dict[str, Any]:
    """Return a local station companion snapshot payload."""
    raw = _read_companion_json(filename, path)
    if raw is None:
        return _not_loaded_station_payload(filename, collection_key, caveat)

    stale_reasons = _station_stale_reasons(raw, state)
    freshness = STALE if stale_reasons else FRESH
    collection = raw.get(collection_key)
    items = _sanitize_collection(collection, item_mapper)

    return {
        "source": filename,
        "timestamp": _string_or_none(raw.get("timestamp")),
        "freshness": freshness,
        "truth_class": TRUTH_LOCAL_SCREEN_SNAPSHOT,
        "caveat": _snapshot_caveat(caveat, stale_reasons),
        "fallback": None,
        "market_id": raw.get("MarketID"),
        "station_name": _string_or_none(raw.get("StationName")),
        "star_system": _string_or_none(raw.get("StarSystem")),
        _payload_collection_key(collection_key): items,
        "nullprovider_safe": True,
    }


def disabled_external_context_payload() -> dict[str, Any]:
    """Expose PB06-02 provider lock posture as inert metadata only."""
    registry = SourceRegistry()
    register_providers(registry)
    sources = []
    for source in registry.list_all():
        sources.append(
            {
                "source_id": source.source_id,
                "display_name": source.display_name,
                "state": source.state.value,
                "fallback": _fallback_for_source_state(source.state),
                "requires_auth": source.requires_auth,
                "requires_consent": source.requires_consent,
                "capabilities": sorted(cap.value for cap in source.capabilities),
            }
        )
    return {
        "phase6_local_only": True,
        "fallback": NO_VERIFIED_SOURCE,
        "sources": sources,
    }


def _cargo_field_source(state: StateManager | None) -> FieldSource | None:
    if state is None:
        return None
    source = state.get_field_source("cargo_inventory")
    if source is None or source.source != TelemetrySource.JOURNAL:
        return None
    return source


def _default_companion_path(filename: str) -> Path | None:
    profile = os.environ.get("USERPROFILE", "")
    if not profile:
        return None
    return (
        Path(profile)
        / "Saved Games"
        / "Frontier Developments"
        / "Elite Dangerous"
        / filename
    )


def _read_companion_json(filename: str, path: Path | None) -> dict[str, Any] | None:
    snapshot_path = path if path is not None else _default_companion_path(filename)
    if snapshot_path is None or not snapshot_path.exists():
        return None
    try:
        raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _not_loaded_station_payload(
    filename: str,
    collection_key: str,
    caveat: str,
) -> dict[str, Any]:
    return {
        "source": filename,
        "timestamp": None,
        "freshness": NOT_LOADED_FRESHNESS,
        "truth_class": TRUTH_UNKNOWN,
        "caveat": (f"{caveat} Missing companion files are not proof of absence."),
        "fallback": NO_LOCAL_STATION_SNAPSHOT,
        "market_id": None,
        "station_name": None,
        "star_system": None,
        _payload_collection_key(collection_key): None,
        "nullprovider_safe": True,
    }


def _station_stale_reasons(
    snapshot: dict[str, Any],
    state: StateManager | None,
) -> list[str]:
    if state is None:
        return []

    current = state.snapshot
    reasons: list[str] = []
    if current.is_docked is False:
        reasons.append("commander has undocked since the station snapshot")

    station_name = _string_or_none(snapshot.get("StationName"))
    if (
        current.current_station
        and station_name
        and current.current_station != station_name
    ):
        reasons.append(
            f"current station is {current.current_station}, snapshot station is "
            f"{station_name}"
        )

    star_system = _string_or_none(snapshot.get("StarSystem"))
    if current.current_system and star_system and current.current_system != star_system:
        reasons.append(
            f"current system is {current.current_system}, snapshot system is "
            f"{star_system}"
        )

    return reasons


def _snapshot_caveat(caveat: str, stale_reasons: list[str]) -> str:
    if not stale_reasons:
        return caveat
    return f"{caveat} Stale: {'; '.join(stale_reasons)}."


def _sanitize_collection(raw: Any, item_mapper: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, list):
        return None
    items: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        items.append(item_mapper(entry))
    return items


def _market_item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id"),
        "name": _string_or_none(raw.get("Name")),
        "category": _string_or_none(raw.get("Category")),
        "buy_price": raw.get("BuyPrice"),
        "sell_price": raw.get("SellPrice"),
        "mean_price": raw.get("MeanPrice"),
        "stock_bracket": raw.get("StockBracket"),
        "demand_bracket": raw.get("DemandBracket"),
        "stock": raw.get("Stock"),
        "demand": raw.get("Demand"),
        "consumer": raw.get("Consumer"),
        "producer": raw.get("Producer"),
        "rare": raw.get("Rare"),
    }


def _outfitting_item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id"),
        "name": _string_or_none(raw.get("Name")),
        "buy_price": raw.get("BuyPrice"),
    }


def _shipyard_item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("id"),
        "ship_type": _string_or_none(raw.get("ShipType")),
        "ship_price": raw.get("ShipPrice"),
    }


def _payload_collection_key(collection_key: str) -> str:
    return "price_list" if collection_key == "PriceList" else "items"


def _fallback_for_source_state(state: SourceState) -> str:
    if state == SourceState.REQUIRES_AUTH:
        return "Requires Authorization"
    if state == SourceState.REQUIRES_CONSENT:
        return "Requires Consent"
    if state == SourceState.DISABLED:
        return "Disabled"
    return NO_VERIFIED_SOURCE


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None
