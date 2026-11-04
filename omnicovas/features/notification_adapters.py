"""Source-specific normalizers. Never open telemetry files or infer missing facts."""

import math
from dataclasses import replace
from typing import Any

from omnicovas.core.activity_log import ActivityEntry
from omnicovas.core.broadcaster import ShipStateEvent
from omnicovas.core.observation import Observation, Scope, fingerprint, timestamp
from omnicovas.core.state_manager import StateManager, TelemetrySource
from omnicovas.features.notification_contracts import Candidate

Json = dict[str, Any]
OVERLAY_TYPES = frozenset(
    {
        "HULL_CRITICAL_10",
        "HULL_CRITICAL_25",
        "FUEL_CRITICAL",
        "FUEL_LOW",
        "HEAT_WARNING",
        "HEAT_DAMAGE",
        "SHIELDS_DOWN",
        "MODULE_CRITICAL",
        "INTERDICTION_STARTED",
    }
)
BROADCAST_TYPES = OVERLAY_TYPES | {
    "HULL_DAMAGE",
    "SHIELDS_UP",
    "MODULE_DAMAGED",
    "INTERDICTION_ENDED",
}


def number(value: object, low: float = 0, high: float = 1000000) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) and low <= result <= high else None


def hull_percent(payload: Json) -> float | None:
    fraction = number(payload.get("health"), high=1)
    percent = number(payload.get("health_pct"), high=100)
    if (
        "health" in payload
        and fraction is None
        or "health_pct" in payload
        and percent is None
    ):
        return None
    if (
        fraction is not None
        and percent is not None
        and abs(fraction * 100 - percent) > 0.11
    ):
        return None
    return fraction * 100 if fraction is not None else percent


def base(
    o: Observation,
    kind: str,
    *,
    producer: str,
    category: str,
    copy: str,
    condition: str = "",
    level: str = "record",
    priority: int = 0,
    state: str = "active",
    value: float | None = None,
    supported: bool = True,
    preference: str = "",
    production: str = "unavailable",
) -> Candidate:
    key = f"{o.scope.ship or 'unknown'}:{condition}" if condition else ""
    identity = fingerprint(f"{o.event_id}:{condition or kind}")
    return Candidate(
        identity,
        o.scope,
        producer,
        kind,
        category,
        level,
        o.observed_at,
        o.event_id,
        copy,
        source=o.source,
        replay=o.replay,
        supported=supported,
        condition=key,
        state=state,
        priority=priority,
        value=value,
        preference_key=preference or kind,
        production=production,
        semantic_key=key or identity,
    )


def broadcast(event: ShipStateEvent) -> list[Candidate]:
    kind, p = event.event_type, event.payload
    if kind not in BROADCAST_TYPES:
        return []
    o = event.observation or Observation(
        fingerprint(f"{kind}:{event.timestamp.isoformat()}"),
        kind,
        None,
        event.source,
        False,
        Scope(),
    )
    production = (
        "inferred_overlay_eligibility" if kind in OVERLAY_TYPES else "producer_observed"
    )
    args: Json = {
        "producer": "ship_broadcaster",
        "category": "combat",
        "copy": "routine",
        "production": production,
    }
    if kind.startswith("HULL_"):
        value = hull_percent(p)
        critical = value is not None and value < 10
        # Below 25% keeps the existing overlay's warning tier (HULL_CRITICAL_25)
        # as a lower-priority interrupt; at or above 25% is fresh recovery.
        warning = value is not None and not critical and value < 25
        args.update(
            copy="hull",
            condition="hull",
            value=value,
            supported=value is not None,
            priority=95 if critical else 65,
            level="interrupt" if critical or warning else "record",
            state="resolved" if value is not None and value >= 25 else "active",
            preference="HULL_CRITICAL_10" if critical else "HULL_CRITICAL_25",
        )
    elif kind.startswith("FUEL_"):
        total, capacity = (
            number(p.get("fuel_main")),
            number(p.get("fuel_capacity_main")),
        )
        fraction = number(p.get("fuel_fraction"), high=1)
        valid = (
            total is not None
            and capacity is not None
            and capacity > 0
            and total <= capacity
            and fraction is not None
            and abs(total / capacity - fraction) < 0.001
        )
        critical = valid and fraction is not None and fraction < 0.1
        low = valid and fraction is not None and not critical and fraction < 0.25
        args.update(
            copy="fuel",
            condition="fuel",
            value=fraction,
            supported=valid,
            priority=80 if critical else 60,
            level="interrupt" if critical or low else "record",
            state="resolved"
            if valid and fraction is not None and fraction >= 0.25
            else "active",
            preference="FUEL_CRITICAL" if critical else "FUEL_LOW",
        )
    elif kind.startswith("HEAT_"):
        value = number(p.get("heat"), high=10)
        damage = (
            kind == "HEAT_DAMAGE"
            and p.get("state") == "damage"
            and o.source == "journal"
        )
        warning = not damage and (
            (value is not None and value >= 0.8)
            or (value is None and p.get("state") == "warning")
        )
        args.update(
            copy="heat",
            condition="heat",
            value=value,
            supported=damage or value is not None or p.get("state") == "warning",
            priority=90 if damage else 55,
            level="interrupt" if damage or warning else "record",
            preference="HEAT_DAMAGE" if damage else "HEAT_WARNING",
        )
    elif kind.startswith("MODULE_"):
        # Subscriber reads shared state asynchronously: payload alone cannot prove
        # it belongs to its originating Loadout. Post-dispatch adapter owns facts.
        args.update(copy="module", supported=False)
    elif kind in {"SHIELDS_DOWN", "SHIELDS_UP"}:
        # Fit and resolved/current state are validated by the projection adapter.
        args.update(copy="shields", supported=False)
    elif kind.startswith("INTERDICTION_"):
        args.update(
            copy="interdiction",
            condition="interdiction",
            priority=85,
            level="interrupt",
            state="resolved" if kind.endswith("ENDED") else "active",
        )
    return [base(o, kind, **args)]


def projection(event: Json, state: StateManager, o: Observation) -> list[Candidate]:
    """After handlers, use only explicitly observed fields accepted into state."""
    name = str(event.get("event", ""))
    snap = state.snapshot
    found: list[Candidate] = []

    def condition(
        key: str,
        value: float | None,
        *,
        critical: bool,
        resolved: bool,
        priority: int,
        supported: bool = True,
        preference: str = "",
    ) -> None:
        projected_condition = base(
            o,
            name,
            producer="state_projection",
            category="combat",
            copy=key,
            condition=key,
            value=value,
            level="interrupt" if critical else "record",
            priority=priority,
            state="unknown" if value is None else "resolved" if resolved else "active",
            supported=supported,
            preference=preference,
        )
        found.append(projected_condition)

    def accepted(field: str) -> bool:
        provenance = state.get_field_source(field)
        return (
            provenance is not None
            and timestamp(provenance.timestamp) == o.observed_at
            and o.observed_at is not None
        )

    if name == "Status":
        if "Heat" in event and accepted("heat_level"):
            heat = number(snap.heat_level, high=10)
            # Numeric status can resolve a supported heat episode; shadow keeps
            # existing warning evidence separate from verified HeatDamage.
            condition(
                "heat",
                heat,
                critical=False,
                resolved=heat is not None and heat < 0.8,
                priority=70,
                preference="HEAT_WARNING",
            )
        flags = event.get("Flags")
        if (
            isinstance(flags, int)
            and not isinstance(flags, bool)
            and accepted("shield_up")
        ):
            fit = any(
                "shieldgenerator" in m.item.lower() for m in snap.modules.values()
            )
            condition(
                "shields",
                float(bool(snap.shield_up)) if fit else None,
                critical=fit and snap.shield_up is False,
                resolved=snap.shield_up is True,
                priority=75,
                preference="SHIELDS_DOWN",
            )
        # No absent Flags field is interpreted as an interdiction recovery.
        if isinstance(flags, int) and not isinstance(flags, bool):
            active = snap.combat.workflow.interdiction_active.value
            if isinstance(active, bool):
                condition(
                    "interdiction",
                    float(active),
                    critical=active,
                    resolved=not active,
                    priority=85,
                    preference="INTERDICTION_STARTED",
                )
    if name in {
        "Status",
        "FuelScoop",
        "RefuelAll",
        "RefuelPartial",
        "FSDJump",
    } and accepted("fuel_main"):
        total, capacity = number(snap.fuel_main), number(snap.fuel_capacity_main)
        fraction = (
            total / capacity
            if total is not None and capacity and total <= capacity
            else None
        )
        critical = fraction is not None and fraction < 0.1
        condition(
            "fuel",
            fraction,
            critical=fraction is not None and fraction < 0.25,
            resolved=fraction is not None and fraction >= 0.25,
            priority=80 if critical else 60,
            preference="FUEL_CRITICAL" if critical else "FUEL_LOW",
        )
    if name == "Loadout" and isinstance(event.get("Modules"), list):
        for raw in event["Modules"][:128]:
            if not isinstance(raw, dict):
                continue
            slot = raw.get("Slot")
            module = snap.modules.get(slot) if isinstance(slot, str) else None
            if module is None:
                continue
            health = number(raw.get("Health"), high=1)
            valid = health is not None and health == number(module.health, high=1)
            found.append(
                base(
                    o,
                    name,
                    producer="loadout_projection",
                    category="combat",
                    copy="module",
                    condition="module:" + fingerprint(str(slot)),
                    value=health,
                    supported=valid,
                    priority=70,
                    level="interrupt"
                    if valid and health is not None and health < 0.2
                    else "record",
                    state="resolved"
                    if valid and health is not None and health >= 0.8
                    else "active",
                    preference="MODULE_CRITICAL",
                )
            )
    if name in {"EscapeInterdiction", "Interdicted"}:
        active = snap.combat.workflow.interdiction_active.value
        if active is False:
            condition(
                "interdiction",
                0,
                critical=False,
                resolved=True,
                priority=85,
                preference="INTERDICTION_STARTED",
            )
    if name in {
        "MaterialCollected",
        "Materials",
        "Cargo",
        "FSDJump",
        "NavRoute",
        "NavRouteClear",
        "Scan",
        "SAAScanComplete",
        "ScanOrganic",
    }:
        category = (
            "engineering"
            if name.startswith("Material")
            else "mining"
            if name == "Cargo"
            else "navigation"
            if name in {"FSDJump", "NavRoute", "NavRouteClear"}
            else "exploration"
        )
        milestone = (
            name == "SAAScanComplete"
            and isinstance(event.get("BodyID"), int)
            or name == "ScanOrganic"
            and event.get("ScanType") == "Analyse"
            and bool(event.get("Species"))
        )
        milestone_candidate = base(
            o,
            name,
            producer="journal_projection",
            category=category,
            copy="biology"
            if name == "ScanOrganic"
            else "mapped"
            if name == "SAAScanComplete"
            else "routine",
            level="glance" if milestone else "record",
        )
        if (
            milestone
            and isinstance(event.get("SystemAddress"), int)
            and isinstance(event.get("BodyID"), int)
        ):
            semantic = (
                f"{name}:{event['SystemAddress']}:{event['BodyID']}:"
                f"{event.get('Species', '')}"
            )
            milestone_candidate = replace(
                milestone_candidate, semantic_key=fingerprint(semantic)
            )
        found.append(milestone_candidate)
    return found


def reconcile(state: StateManager, scope: Scope) -> list[Candidate]:
    """Current accepted hull/fuel state as condition evidence.

    The Director normally learns these from the originating observation. This
    path recovers a condition when that observation never reached arbitration
    (an observer failure or a lost frame). It carries the field's own provenance
    time, so stale or replayed state stays stale; it never invents a value.
    """
    snap = state.snapshot
    found: list[Candidate] = []

    def observed(field: str) -> tuple[float, str] | None:
        src = state.get_field_source(field)
        if src is None:
            return None
        at = timestamp(src.timestamp)
        kind = {
            TelemetrySource.JOURNAL: "journal",
            TelemetrySource.STATUS_JSON: "status_json",
        }.get(src.source)
        return (at, kind) if at is not None and kind else None

    hull = number(snap.hull_health, high=1)
    hull_seen = observed("hull_health")
    if hull is not None and hull_seen is not None:
        at, source = hull_seen
        value = hull * 100
        critical, warning = value < 10, 10 <= value < 25
        o = Observation(
            fingerprint(f"reconcile:hull:{at}"), "Reconcile", at, source, False, scope
        )
        found.append(
            base(
                o,
                "Reconcile",
                producer="state_reconciliation",
                category="combat",
                copy="hull",
                condition="hull",
                value=value,
                priority=95 if critical else 65,
                level="interrupt" if critical or warning else "record",
                state="resolved" if value >= 25 else "active",
                preference="HULL_CRITICAL_10" if critical else "HULL_CRITICAL_25",
            )
        )
    total, capacity = number(snap.fuel_main), number(snap.fuel_capacity_main)
    fuel_seen = observed("fuel_main")
    if total is not None and capacity and total <= capacity and fuel_seen:
        at, source = fuel_seen
        fraction = total / capacity
        critical, low = fraction < 0.1, 0.1 <= fraction < 0.25
        o = Observation(
            fingerprint(f"reconcile:fuel:{at}"), "Reconcile", at, source, False, scope
        )
        found.append(
            base(
                o,
                "Reconcile",
                producer="state_reconciliation",
                category="combat",
                copy="fuel",
                condition="fuel",
                value=fraction,
                priority=80 if critical else 60,
                level="interrupt" if critical or low else "record",
                state="resolved" if fraction >= 0.25 else "active",
                preference="FUEL_CRITICAL" if critical else "FUEL_LOW",
            )
        )
    return found


def briefing(event: Json, o: Observation | None) -> Candidate | None:
    if event.get("event_type") != "GALACTIC_INTELLIGENCE_BRIEFING":
        return None
    p = event.get("payload")
    if (
        not isinstance(p, dict)
        or not isinstance(p.get("briefing_id"), str)
        or o is None
    ):
        return None
    observed = replace(o, observed_at=timestamp(p.get("observed_at")))
    return replace(
        base(
            observed,
            "GALACTIC_INTELLIGENCE_BRIEFING",
            producer="galactic_intelligence",
            category="knowledge",
            copy="story",
            level="glance",
            production="bridge_observed",
        ),
        candidate_id=fingerprint(p["briefing_id"]),
        subject=p["briefing_id"][:160],
        semantic_key=fingerprint(str(p.get("encounter_key") or p["briefing_id"])),
        context_key=fingerprint(
            str(p.get("presence_key") or p.get("location_key") or "")
        )
        if (p.get("presence_key") or p.get("location_key"))
        else "",
        preference_key="gki:" + str(p.get("category", "unknown")),
        source="galactic_intelligence",
        surfaces=("desktop",),
        destination="intel",
    )


def narrative(payload: Json, scope: Scope) -> Candidate:
    """Normalize actual GKI-06/07 opportunities without granting delivery consent."""
    if payload.get("contract") != "narrative-opportunity-v1" or payload.get(
        "version"
    ) not in {1, "galactic-expeditions-v1", "galactic-historian-v1"}:
        raise ValueError("Unsupported narrative contract")
    if (
        payload.get("profile_key") != scope.commander
        or not isinstance(payload.get("opportunity_id"), str)
        or not payload["opportunity_id"]
    ):
        raise ValueError("Missing/mismatched narrative identity")
    trigger, presentation = payload.get("trigger"), payload.get("presentation")
    if not isinstance(trigger, dict) or not isinstance(presentation, dict):
        raise ValueError("Missing narrative evidence/presentation")
    o = Observation(
        fingerprint(payload["opportunity_id"]),
        "narrative-opportunity-v1",
        timestamp(trigger.get("observed_at")),
        "galactic_knowledge",
        trigger.get("replayed") is not False,
        scope,
    )
    passage = payload.get("passage")
    spoiler = (
        not isinstance(passage, dict)
        or passage.get("spoiler", True) is not False
        or passage.get("spoiler_hidden") is True
    )
    prefs = payload.get("preferences") or {}
    prefs = prefs if isinstance(prefs, dict) else {}
    category = prefs.get("category", "expedition_stories")
    category = category if isinstance(category, str) else "expedition_stories"
    declared = presentation.get("surfaces")
    desktop = True
    if isinstance(declared, dict):
        desktop_policy = declared.get("desktop")
        desktop = (
            isinstance(desktop_policy, dict) and desktop_policy.get("eligible") is True
        )
    return replace(
        base(
            o,
            o.event_type,
            producer="historian_contract"
            if payload.get("source") == "historian"
            else "expedition_contract",
            category="knowledge",
            copy="story",
            level="glance",
        ),
        automatic=False,
        domain_eligible=presentation.get("eligible") is True
        and prefs.get("mode") != "quiet",
        spoiler=spoiler,
        surfaces=("desktop",) if desktop else (),
        # A Historian moment opens Intel (Atlas and Chronicle); an expedition
        # moment opens its expedition in Navigation (GKI-06/07 merge record, 2).
        destination="intel" if payload.get("source") == "historian" else "navigation",
        preference_key="gki:" + category,
    )


def activity(entry: ActivityEntry, scope: Scope) -> Candidate | None:
    completed_transition = (
        entry.event_type
        in {
            "engineering.goal.state_changed",
            "engineering.acquisition_plan.state_changed",
        }
        and (entry.payload or {}).get("state") == "completed"
    )
    if (
        entry.event_type
        not in {
            "engineering.goal.completed",
            "operations.objective.completed",
            "engineering.acquisition_plan.completed_via_operations",
        }
        and not completed_transition
    ):
        return None
    if not entry.event_id:
        return None
    o = Observation(
        fingerprint(entry.event_id),
        entry.event_type,
        timestamp(entry.timestamp),
        "commander_entered",
        False,
        scope,
    )
    return replace(
        base(
            o,
            entry.event_type,
            producer="activity_log",
            category="engineering",
            copy="objective",
            level="glance",
            production="activity_record_observed",
        ),
        confidence="commander_declared",
        destination="engineering",
    )
