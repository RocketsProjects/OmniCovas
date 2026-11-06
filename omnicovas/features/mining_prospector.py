"""Observed prospector reports and target matches; no asteroid radar or game input.

Frontier Journal Manual v34 §13.33 supplies Materials/Proportion, optional
MotherlodeMaterial, Content and Remaining. No stable asteroid ID or position is
supplied: counts below are reports, never distinct asteroids or live tracking.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import replace
from typing import Any

from omnicovas.core.event_types import MINING_PROSPECTOR_UPDATED
from omnicovas.core.observation import (
    CURRENT_OBSERVATION,
    Observation,
    Scope,
    fingerprint,
)
from omnicovas.features.notification_adapters import base, number
from omnicovas.features.operations_economy import commodity_key

BOUNDARIES = {
    "Commander",
    "NewCommander",
    "LoadGame",
    "Loadout",
    "ShipyardSwap",
    "FSDJump",
    "CarrierJump",
    "SupercruiseEntry",
    "Shutdown",
    "Died",
    "Fileheader",
}


def target_key(record: dict[str, Any] | None) -> str:
    r = record or {}
    return fingerprint(
        str(
            (
                r.get("objective_id"),
                r.get("target_commodity"),
                r.get("target_quantity"),
                r.get("state"),
            )
        )
    )


def parse_report(event: dict[str, Any]) -> dict[str, Any]:
    rows = event.get("Materials")
    composition = []
    if isinstance(rows, list):
        for row in rows[:32]:
            if not isinstance(row, dict) or not isinstance(row.get("Name"), str):
                continue
            name = row["Name"][:128]
            composition.append(
                {
                    "key": commodity_key(name),
                    "name": str(row.get("Name_Localised") or name)[:128],
                    "proportion": number(row.get("Proportion"), high=100),
                }
            )
    core = event.get("MotherlodeMaterial")
    content = event.get("Content")
    return {
        "observed_at": event.get("timestamp"),
        "composition": composition,
        "composition_observed": isinstance(rows, list)
        and len(rows) <= 32
        and len(composition) == len(rows)
        and all(row["proportion"] is not None for row in composition),
        "remaining": number(event.get("Remaining"), high=100),
        "material_content": content
        if isinstance(content, str) and content in {"High", "Medium", "Low"}
        else None,
        "core": core[:128] if isinstance(core, str) and core.strip() else None,
    }


def match_report(report: dict[str, Any], target: str | None) -> dict[str, Any]:
    key = commodity_key(target)
    found = (
        next(
            (
                r
                for r in report["composition"]
                if (r["key"] == key or commodity_key(r["name"]) == key)
                and r["proportion"] is not None
                and r["proportion"] > 0
            ),
            None,
        )
        if key
        else None
    )
    core = bool(key and commodity_key(report["core"]) == key)
    depleted = report["remaining"] == 0
    return {
        "target": target,
        "matched": bool(found or core),
        "actionable": bool((found or core) and not depleted),
        "depleted": depleted,
        "proportion": found["proportion"] if found else None,
        "core_match": core,
    }


class MiningProspector:
    """Session-only, bounded source projection fed by the existing dispatcher."""

    def __init__(
        self,
        objectives: Any,
        shadow: Any,
        *,
        clock: Any = time.time,
        notify: Any = None,
    ) -> None:
        self.objectives, self.shadow, self.clock, self.notify = (
            objectives,
            shadow,
            clock,
            notify,
        )
        self.reports: deque[dict[str, Any]] = deque(maxlen=24)
        self.scope = Scope()
        self.target: str | None = None
        self.target_revision = ""
        self.latest_candidate: Any = None
        self._epoch = 0

    def clear(self) -> None:
        self.reports.clear()
        self.latest_candidate = None
        self._epoch += 1

    async def after_forget(self, profile: str) -> None:
        if profile == self.scope.commander:
            self.clear()
            self.scope = Scope()

    def observe_activity(self, entry: Any) -> None:
        if (
            str(entry.event_type).startswith("OPERATIONS_OBJECTIVE_")
            and entry.payload.get("operation") == "mining"
        ):
            self.clear()

    async def _target(self) -> tuple[str, str | None]:
        payload = await self.objectives.get_current("mining") if self.objectives else {}
        record = payload.get("objective") if payload.get("available") else None
        target = (
            record.get("target_commodity")
            if record and record.get("state") == "active"
            else None
        )
        return target_key(record), target

    async def observe(self, event: dict[str, Any]) -> None:
        o = CURRENT_OBSERVATION.get()
        if not o:
            return
        if event.get("event") in BOUNDARIES or o.scope != self.scope:
            self.clear()
            self.scope = o.scope
        if event.get("event") != "ProspectedAsteroid":
            return
        epoch = self._epoch
        revision, target = await self._target()
        if epoch != self._epoch:
            return
        if revision != self.target_revision:
            self.clear()
        self.target_revision, self.target = revision, target
        # Replayed, future, unscoped and out-of-order reports do not become a
        # fresh asteroid. Even historical reports never trigger a live alert.
        if (
            not o.scope.commander
            or not o.scope.ship
            or o.replay
            or o.observed_at is None
            or not 0 <= self.clock() - o.observed_at <= 10
        ):
            return
        if self.reports and o.observed_at < self.reports[0]["at_seconds"]:
            return
        ident = fingerprint(f"{o.scope.generation}:{o.event_id}:{revision}")
        if any(r["report_id"] == ident for r in self.reports):
            return
        self.latest_candidate = None
        report = parse_report(event)
        report.update(
            match_report(report, target),
            report_id=ident,
            at_seconds=o.observed_at,
            target_revision=revision,
        )
        self.reports.appendleft(report)
        if report["actionable"] and target:
            candidate = base(
                o,
                "ProspectedAsteroid",
                producer="mining_prospector",
                category="mining",
                copy="prospector",
                level="glance",
                priority=45,
                value=report["proportion"],
                production="producer_observed",
            )
            self.latest_candidate = replace(
                candidate,
                subject=ident,
                destination="mining",
                ttl=20,
                semantic_key=ident,
            )
        if self.notify:
            await self.notify(
                {
                    "event_type": MINING_PROSPECTOR_UPDATED,
                    "timestamp": event.get("timestamp"),
                    "payload": {"report_id": ident},
                }
            )

    def candidate_for(self, o: Observation) -> Any:
        c = self.latest_candidate
        return c if c and c.scope == o.scope and c.evidence_ref == o.event_id else None

    def current(self, candidate: Any) -> bool:
        return bool(
            self.latest_candidate
            and candidate.subject == self.latest_candidate.subject
            and candidate.scope == self.scope
        )

    async def snapshot(self) -> dict[str, Any]:
        revision, target = await self._target()
        if revision != self.target_revision:
            self.clear()
            self.target_revision, self.target = revision, target
        reports = list(self.reports)
        return {
            "target": target,
            "state": "observed" if reports else "waiting" if target else "no_target",
            "latest": reports[0] if reports else None,
            "reports": reports,
            "matching_reports": sum(1 for r in reports if r["matched"]),
            "scope": "Current Commander, ship and local session; latest 24 reports",
            "caveat": (
                "A prospector report is an observation, not a live asteroid identity "
                "or position. Remaining percentage can change after this report."
            ),
        }
