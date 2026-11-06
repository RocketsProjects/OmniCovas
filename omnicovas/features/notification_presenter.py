"""Director-owned presentation: snapshot contract, copy, ownership and receipts.

The Director decides *what* holds the single attention slot. The presenter turns
that slot into a versioned snapshot for the native overlay and the desktop
window, and records what those surfaces actually report back. A receipt is the
only evidence that something appeared; a candidate or a broadcast is not.

Pure, bounded state: no I/O. The notification service supplies the clock,
publishes snapshots through the existing bridge and calls ``tick``.
"""

import math
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from typing import Any

from omnicovas.features.notification_contracts import Candidate
from omnicovas.features.notification_director import (
    CRITICAL_PRIORITY,
    Director,
    attention_for,
)

CONTRACT = "nhi-presentation-1"
OWNERS = ("director", "legacy")
CLIENTS = ("overlay", "desktop")
CLIENT_STATUSES = frozenset({"ready", "rendered", "visible", "hidden", "failed"})
RENDER_DEADLINE = 3.0
MAX_PRESENTATIONS = 256
MAX_EVENTS_PER_PRESENTATION = 16
HEALTHY_PASSES_TO_RECOVER = 3
UNHEALTHY_FAILURES = 3

# Copy keys → commander-facing text. Plain sentence case, no raw event names,
# no names/locations/passages. Values are formatted once, here.
_GLANCE_COPY: dict[str, tuple[str, str, str]] = {
    "mapped": (
        "Exploration",
        "Body mapped",
        "Detailed surface scan complete.",
    ),
    "biology": (
        "Exploration",
        "Biology sample complete",
        "Final sample analysed.",
    ),
    "objective": (
        "Engineering",
        "Objective complete",
        "A tracked objective is ready to review.",
    ),
    "story": (
        "Galactic Intelligence",
        "A place with history",
        "A briefing is ready to read.",
    ),
    "materials": (
        "Engineering",
        "Materials secured",
        "{n} units toward a tracked plan.",
    ),
    "summary": ("OmniCOVAS", "While you were busy", "{n} notices ready to review."),
}

# Condition kind and priority → the legacy overlay event this presentation
# corresponds to. Used only to hand an active alert to the fallback path.
_LEGACY_EVENTS = {
    ("hull", True): "HULL_CRITICAL_10",
    ("hull", False): "HULL_CRITICAL_25",
    ("fuel", True): "FUEL_CRITICAL",
    ("fuel", False): "FUEL_LOW",
    ("heat", True): "HEAT_DAMAGE",
    ("heat", False): "HEAT_WARNING",
    ("shields", True): "SHIELDS_DOWN",
    ("module", True): "MODULE_CRITICAL",
    ("interdiction", True): "INTERDICTION_STARTED",
}


def _kind(c: Candidate) -> str:
    parts = c.condition.split(":")
    return parts[1] if len(parts) > 1 else c.copy_key


def _percent(c: Candidate) -> int | None:
    """Unit conversion happens once, from the adapter's declared units.

    Hull values are percentages; fuel, heat and module values are fractions.
    Floors so a "below 10%" alert never reads "10%". None stays None.
    """
    v = c.value
    if v is None or not math.isfinite(v):
        return None
    pct = v if _kind(c) == "hull" else v * 100
    if not 0 <= pct <= 1000:
        return None
    return int(math.floor(pct))


def copy_for(c: Candidate) -> dict[str, Any]:
    kind = _kind(c)
    critical = c.priority >= CRITICAL_PRIORITY
    pct = _percent(c)
    value = (
        {"kind": "percent", "amount": pct, "text": f"{pct}%"}
        if pct is not None
        else None
    )
    if c.level == "interrupt":
        severity = "critical" if critical else "warning"
        heading, body = "Ship condition", ""
        if kind == "hull":
            heading = "Hull critically damaged" if critical else "Hull integrity low"
            body = (
                f"Hull {pct}%. Consider disengaging."
                if pct is not None and critical
                else f"Hull {pct}%."
                if pct is not None
                else "Hull integrity reported low."
            )
        elif kind == "fuel":
            heading = "Fuel critical" if critical else "Fuel low"
            body = (
                f"Main tank {pct}%. Plan a refuel."
                if pct is not None
                else "Main tank reported low."
            )
        elif kind == "heat":
            heading = "Ship overheating" if critical else "Heat high"
            body = (
                "Heat is damaging modules."
                if critical
                else f"Heat {pct}%."
                if pct is not None
                else "Heat warning reported."
            )
            if critical:
                value = None
        elif kind == "shields":
            heading, body, value = "Shields offline", "Shield generator is down.", None
        elif kind == "module":
            heading = "Module critical"
            body = (
                f"A module is at {pct}% integrity."
                if pct is not None
                else "A module reported critical damage."
            )
        elif kind == "interdiction":
            heading, body, value = (
                "Interdiction detected",
                "You are being pulled from supercruise.",
                None,
            )
        label = "OmniCOVAS · Critical" if critical else "OmniCOVAS · Warning"
        return {
            "severity": severity,
            "label": label,
            "heading": heading,
            "body": body,
            "value": value,
            "live": "assertive",
        }
    area, heading, body = _GLANCE_COPY.get(
        c.copy_key, ("OmniCOVAS", "Notice", "Ready to review.")
    )
    if c.copy_key == "prospector":
        area, heading = "Mining", "Mining target found"
        body = (
            f"Target mineral reported at {c.value:g}%."
            if c.value is not None
            else "Target core mineral reported."
        ) + " Review the latest prospector report in Mining."
    return {
        "severity": "notice",
        "label": f"OmniCOVAS · {area}",
        "heading": heading,
        "body": body.format(n=c.quantity),
        "value": None,
        "live": "polite",
    }


@dataclass
class Presentation:
    presentation_id: str
    candidate_id: str
    condition: str
    level: str
    commander: str | None
    generation: int
    surface: str | None
    accepted_at: float
    events: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=MAX_EVENTS_PER_PRESENTATION)
    )
    rendered: set[str] = field(default_factory=set)
    outcome: str | None = None

    def add(self, status: str, client: str, at: float, detail: str = "") -> None:
        self.events.append(
            {"status": status, "client": client, "at": at, "detail": detail[:80]}
        )

    def record(self) -> dict[str, Any]:
        return {
            "presentation_id": self.presentation_id,
            "candidate_id": self.candidate_id,
            "condition": self.condition,
            "level": self.level,
            "generation": self.generation,
            "surface": self.surface,
            "accepted_at": self.accepted_at,
            "rendered_by": sorted(self.rendered),
            "outcome": self.outcome,
            "events": list(self.events),
        }


class Presenter:
    def __init__(self, configured_owner: str = "director") -> None:
        self.configured_owner = (
            configured_owner if configured_owner in OWNERS else "director"
        )
        self.owner = "legacy"
        self.owner_reason = "starting"
        self.owner_generation = 0
        self.seq = 0
        self.healthy_passes = 0
        self.presentations: OrderedDict[str, Presentation] = OrderedDict()
        self.overlay_ready_at: float | None = None
        self.overlay_failed = False
        self.counters = {
            "accepted": 0,
            "rendered": 0,
            "visible": 0,
            "acknowledged": 0,
            "dismissed": 0,
            "expired": 0,
            "superseded": 0,
            "resolved": 0,
            "failed": 0,
            "rejected_receipts": 0,
        }
        self._last_version: tuple[Any, ...] | None = None
        self.display: dict[str, Any] = {}
        self._snapshot: dict[str, Any] = self._empty()

    def _empty(self) -> dict[str, Any]:
        return {
            "type": "notification_presentation",
            "contract": CONTRACT,
            "owner": self.owner,
            "owner_reason": self.owner_reason,
            "owner_generation": self.owner_generation,
            "seq": self.seq,
            "slot": None,
            "watch": [],
            "display": self.display,
        }

    # ── Ownership ───────────────────────────────────────────────────────────

    def evaluate_owner(self, *, healthy: bool, reason: str) -> bool:
        """Effective owner from configuration and Director health.

        Director ownership needs a running, recently successful service. Recovery
        after a failure needs several consecutive healthy passes, so a flapping
        worker cannot bounce presentation between paths.
        """
        if self.configured_owner == "legacy":
            target, why = "legacy", "configured_legacy"
        elif not healthy:
            self.healthy_passes = 0
            target, why = "legacy", reason
        else:
            self.healthy_passes += 1
            # First start needs one healthy pass; recovery after a failure needs
            # several, so a flapping worker cannot bounce between paths.
            recovering = self.owner == "legacy" and self.owner_reason != "starting"
            if recovering and self.healthy_passes < HEALTHY_PASSES_TO_RECOVER:
                target, why = "legacy", "recovering"
            else:
                target, why = "director", "healthy"
        changed = target != self.owner
        if changed:
            self.owner_generation += 1
        self.owner, self.owner_reason = target, why
        return changed

    # ── Receipts ────────────────────────────────────────────────────────────

    def _remember(self, p: Presentation) -> None:
        self.presentations[p.presentation_id] = p
        self.presentations.move_to_end(p.presentation_id)
        while len(self.presentations) > MAX_PRESENTATIONS:
            self.presentations.popitem(last=False)

    def receipt(
        self,
        presentation_id: str | None,
        client: str,
        status: str,
        now: float,
        detail: str = "",
    ) -> bool:
        if client not in CLIENTS or status not in CLIENT_STATUSES:
            self.counters["rejected_receipts"] += 1
            return False
        if status == "ready":
            if client == "overlay":
                self.overlay_ready_at, self.overlay_failed = now, False
            return True
        p = self.presentations.get(presentation_id or "")
        if p is None:
            self.counters["rejected_receipts"] += 1
            return False
        if status == "failed":
            p.add("failed", client, now, detail)
            self.counters["failed"] += 1
            if client == "overlay":
                self.overlay_failed = True
            return True
        if status in {"rendered", "visible"}:
            if client == "overlay":
                self.overlay_failed = False
            if status == "rendered":
                if client in p.rendered:
                    return True
                p.rendered.add(client)
        p.add(status, client, now, detail)
        self.counters[status] = self.counters.get(status, 0) + 1
        return True

    def overlay_usable(self) -> bool:
        return self.overlay_ready_at is not None and not self.overlay_failed

    def receipts(
        self, limit: int = 50, commander: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [
            p.record()
            for p in reversed(self.presentations.values())
            if commander is None or p.commander == commander
        ]
        return rows[: max(1, min(limit, MAX_PRESENTATIONS))]

    def forget(self, commander: str) -> None:
        for key in [
            k for k, p in self.presentations.items() if p.commander == commander
        ]:
            del self.presentations[key]

    # ── Snapshot ────────────────────────────────────────────────────────────

    def tick(self, director: Director, now: float) -> bool:
        """Sync from the Director; returns True when the snapshot changed."""
        for pid, outcome, at in list(director.retired):
            p = self.presentations.get(pid)
            if p and p.outcome is None:
                p.outcome = outcome
                p.add(outcome, "director", at)
                if outcome in self.counters:
                    self.counters[outcome] += 1
        director.retired.clear()
        s = director.state
        slot = None
        if s.visible and s.presentation_id:
            p = self.presentations.get(s.presentation_id)
            if p is None:
                p = Presentation(
                    s.presentation_id,
                    s.visible.candidate_id,
                    s.visible.condition,
                    s.visible.level,
                    director.scope.commander,
                    director.scope.generation,
                    s.surface,
                    now,
                )
                p.add("accepted", "director", now, s.surface or "")
                self.counters["accepted"] += 1
                self._remember(p)
            elif p.surface != s.surface:
                p.surface = s.surface
                p.add("accepted", "director", now, f"fallback:{s.surface}")
            # Overlay said nothing in time: treat as failed to display and move
            # the alert to the desktop instead of assuming it appeared.
            if (
                self.owner == "director"
                and s.surface == "overlay"
                and "overlay" not in p.rendered
                and now - p.accepted_at >= RENDER_DEADLINE
                and not any(e["status"] == "failed" for e in p.events)
            ):
                p.add("failed", "director", now, "no_render_receipt")
                self.counters["failed"] += 1
                self.overlay_failed = True
            slot = self._slot(director, s.visible, now)
        watch = [
            {
                "kind": _kind(cond.candidate),
                "state": cond.state,
                "severity": "critical"
                if cond.candidate.priority >= CRITICAL_PRIORITY
                else "warning",
                "value": copy_for(cond.candidate)["value"],
                "observed_at": cond.candidate.observed_at,
            }
            for cond in s.conditions.values()
            if cond.state in {"active", "acknowledged"}
            and cond.candidate.level == "interrupt"
        ][:16]
        version = (
            self.owner,
            self.owner_generation,
            director.slot_version,
            s.surface,
            tuple((w["kind"], w["state"], str(w["value"])) for w in watch),
            tuple(sorted(self.display.items())),
        )
        if version == self._last_version:
            return False
        self._last_version = version
        self.seq += 1
        self._snapshot = {
            **self._empty(),
            "seq": self.seq,
            "issued_at": now,
            "slot": slot,
            "watch": watch,
        }
        return True

    def _slot(self, director: Director, c: Candidate, now: float) -> dict[str, Any]:
        s = director.state
        text = copy_for(c)
        kind = _kind(c)
        return {
            "presentation_id": s.presentation_id,
            "candidate_id": c.candidate_id,
            "level": c.level,
            "surface": s.surface,
            "category": c.category,
            "destination": c.destination,
            "subject": c.subject or None,
            "observed_at": c.observed_at,
            "presented_at": s.presented_at,
            "until": s.presented_at + attention_for(c)
            if c.level == "interrupt"
            else s.visible_until,
            "legacy_event": _LEGACY_EVENTS.get((kind, c.priority >= CRITICAL_PRIORITY))
            if c.level == "interrupt"
            else None,
            **text,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            **self._snapshot,
            "owner": self.owner,
            "owner_reason": self.owner_reason,
        }
