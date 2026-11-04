"""Bounded deterministic arbitration, adapted from NHI-01's verified core.

No I/O, provider, game control or presentation callback. UTC seconds and immutable
inputs are supplied by the service. Condition truth is separate from scheduling:
a condition's validity comes from its evidence rule, and the single attention
slot's lifetime belongs only to the presentation currently holding it.
"""

from collections import OrderedDict, deque
from dataclasses import dataclass, field, replace
from typing import Any

from omnicovas.core.observation import Scope, fingerprint
from omnicovas.features.notification_contracts import Candidate, Decision, Preferences

MAX_PROFILES = 8
MAX_SEEN = 4096
MAX_CONDITIONS = 128
MAX_DEFERRED = 20
MAX_RECORDS = 1024
RETENTION = 86400


@dataclass(frozen=True)
class ConditionRule:
    """How long a condition's evidence stays current, and how long it may hold
    the attention slot per episode.

    ``persistent`` conditions (hull, fuel, shields, module health) do not change
    without a new Journal/Status observation, so they stay valid until superseding
    evidence or a scope boundary. Transient ones (heat, interdiction) become
    unknown after ``validity`` seconds without fresh evidence. ``attention`` is a
    presentation budget, never a claim that the condition has ended.
    """

    persistent: bool
    validity: float
    attention: float
    warning_attention: float


# Below this priority an interrupt is a warning (hull <25%, fuel <25%, heat
# warning); at or above it, critical. Attention budgets keep the legacy overlay's
# per-alert durations as their starting point.
CRITICAL_PRIORITY = 70
RULES: dict[str, ConditionRule] = {
    "hull": ConditionRule(True, 0, 30, 10),
    "fuel": ConditionRule(True, 0, 30, 10),
    "shields": ConditionRule(True, 0, 5, 5),
    "module": ConditionRule(True, 0, 15, 15),
    "interdiction": ConditionRule(False, 60, 8, 8),
    "heat": ConditionRule(False, 10, 15, 8),
}
DEFAULT_RULE = ConditionRule(False, 10, 15, 8)


def rule_for(condition: str) -> ConditionRule:
    """Condition keys are ``<ship>:<kind>[:<detail>]``."""
    parts = condition.split(":")
    return RULES.get(parts[1] if len(parts) > 1 else "", DEFAULT_RULE)


def attention_for(c: Candidate) -> float:
    r = rule_for(c.condition)
    return r.attention if c.priority >= CRITICAL_PRIORITY else r.warning_attention


@dataclass
class Condition:
    candidate: Candidate
    state: str = "newly_observed"
    acknowledged_priority: int | None = None
    # Priority whose attention window already elapsed this episode. Escalation
    # above it rearms presentation; unchanged evidence does not.
    retired_priority: int | None = None
    episode: int = 0


@dataclass
class Profile:
    preferences: Preferences = field(default_factory=Preferences)
    seen: OrderedDict[str, float] = field(default_factory=OrderedDict)
    conditions: OrderedDict[str, Condition] = field(default_factory=OrderedDict)
    deferred: OrderedDict[str, Candidate] = field(default_factory=OrderedDict)
    aggregates: OrderedDict[str, tuple[Candidate, int, float]] = field(
        default_factory=OrderedDict
    )
    last_shown: OrderedDict[str, float] = field(default_factory=OrderedDict)
    glance_times: deque[float] = field(default_factory=lambda: deque(maxlen=2))
    visible: Candidate | None = None
    surface: str | None = None
    visible_until: float = 0
    presentation_id: str | None = None
    presented_at: float = 0
    combat: bool = False
    live: bool = False
    settle_until: float = 0
    # GKI-08 closeout: fingerprints of the places the Commander Context shows as
    # current; None while the location is not known.  ``presence_tracked`` stays
    # False until a presence is supplied, so callers without one keep the old
    # behaviour.
    presence: frozenset[str] | None = None
    presence_tracked: bool = False


UNCHANGED: Any = object()


class Director:
    def __init__(self) -> None:
        self.scope = Scope()
        self.profiles: OrderedDict[str, Profile] = OrderedDict()
        self.decisions: deque[Decision] = deque(maxlen=MAX_RECORDS)
        self.overlay_available = True
        # "shadow" while legacy presentation owns the screen; "director" when the
        # presenter delivers this slot. Recorded on every decision.
        self.presentation_mode = "shadow"
        # Incremented whenever the attention slot changes; presenters compare it.
        self.slot_version = 0
        self._presentations = 0
        # Bounded history of presentations that left the slot, for receipts.
        self.retired: deque[tuple[str, str, float]] = deque(maxlen=64)

    @property
    def state(self) -> Profile:
        key = self.scope.commander or "unknown"
        if key not in self.profiles:
            if len(self.profiles) >= MAX_PROFILES:
                self.profiles.popitem(last=False)
            self.profiles[key] = Profile()
        self.profiles.move_to_end(key)
        return self.profiles[key]

    def activate(self, scope: Scope, now: float) -> None:
        if self.scope == scope:
            return
        self._clear_slot(now, "scope_changed")
        self.state.deferred.clear()
        self.state.aggregates.clear()
        previous_scope = self.scope
        self.scope = scope
        s = self.state
        self._clear_slot(now, "scope_changed")
        s.live, s.combat = False, False
        s.presence, s.presence_tracked = None, False
        s.deferred.clear()
        s.aggregates.clear()
        for condition in s.conditions.values():
            if (
                previous_scope.session != scope.session
                or previous_scope.ship != scope.ship
            ):
                condition.acknowledged_priority = None
                condition.retired_priority = None
            if condition.state not in {"resolved", "unknown"}:
                condition.state = "unknown"

    def emit(
        self,
        c: Candidate,
        now: float,
        decision: str,
        reason: str,
        surface: str | None = None,
    ) -> None:
        s = self.state
        condition = s.conditions.get(c.condition)
        self.decisions.append(
            Decision(
                c,
                now,
                decision,
                reason,
                surface,
                condition.state if condition else c.state,
                s.preferences,
                s.combat,
                s.live,
                c.observed_at + c.ttl if c.observed_at is not None else None,
                {
                    "scope_generation": self.scope.generation,
                    "visible_id": s.visible.candidate_id if s.visible else None,
                    "visible_priority": s.visible.priority if s.visible else None,
                    "presentation_id": s.presentation_id if s.visible else None,
                    "surface": s.surface if s.visible else None,
                    "settle_until": s.settle_until,
                    "glance_times": list(s.glance_times),
                    "deferred_ids": [item.candidate_id for item in s.deferred.values()],
                    "condition_revision": condition.candidate.revision
                    if condition
                    else None,
                    "condition_observed_at": condition.candidate.observed_at
                    if condition
                    else None,
                    "acknowledged_priority": condition.acknowledged_priority
                    if condition
                    else None,
                    "retired_priority": condition.retired_priority
                    if condition
                    else None,
                    "episode": condition.episode if condition else None,
                },
                s.last_shown.get(c.semantic_key, -60) + 60
                if c.semantic_key in s.last_shown
                else None,
                presentation_mode=self.presentation_mode,
            )
        )

    # ── Attention slot ──────────────────────────────────────────────────────

    def _show(
        self, c: Candidate, surface: str, now: float, reason: str, until: float
    ) -> None:
        s = self.state
        self._presentations += 1
        s.visible, s.surface = c, surface
        key = c.condition or c.candidate_id
        s.presentation_id = fingerprint(
            f"{self.scope.generation}:{self._presentations}:{key}"
        )
        s.presented_at, s.visible_until = now, until
        self.slot_version += 1
        self.emit(c, now, "would_present", reason, surface)

    def _clear_slot(self, now: float, outcome: str) -> None:
        s = self.state
        if s.visible is None:
            return
        if s.presentation_id:
            self.retired.append((s.presentation_id, outcome, now))
        s.visible, s.surface, s.presentation_id = None, None, None
        self.slot_version += 1

    def _update_visible(self, c: Candidate) -> None:
        """Same-condition sample: new value, same presentation, no reanimation."""
        self.state.visible = c
        self.slot_version += 1

    def interrupt_surface(self, c: Candidate) -> str | None:
        prefs = self.state.preferences
        if prefs.overlay and self.overlay_available and "overlay" in c.surfaces:
            return "overlay"
        return "desktop" if "desktop" in c.surfaces else None

    def set_overlay_available(self, available: bool, now: float) -> None:
        """A failed/absent overlay moves the current critical to the desktop."""
        if self.overlay_available == available:
            return
        self.overlay_available = available
        s = self.state
        if s.visible and s.visible.level == "interrupt":
            surface = self.interrupt_surface(s.visible)
            if surface and surface != s.surface:
                s.surface = surface
                self.slot_version += 1
                self.emit(s.visible, now, "would_present", "surface_fallback", surface)
        self.tick(now)

    # ── Evidence ────────────────────────────────────────────────────────────

    def fresh(self, c: Candidate, now: float) -> bool:
        limit = min(c.freshness, 3 if c.source == "status_json" else 10)
        return bool(
            c.supported
            and c.confidence == "verified"
            and c.evidence_ref
            and not c.replay
            and c.source in {"journal", "status_json"}
            and c.observed_at is not None
            and 0 <= now - c.observed_at <= limit
        )

    def current(self, condition: Condition, now: float) -> bool:
        """Is this condition's last accepted evidence still current?"""
        r = rule_for(condition.candidate.condition)
        observed = condition.candidate.observed_at
        return observed is not None and (
            r.persistent or 0 <= now - observed <= r.validity
        )

    def configure(self, prefs: Preferences, now: float) -> None:
        self.state.preferences = prefs
        self.tick(now)

    def context(
        self, now: float, *, combat: bool, live: bool, presence: Any = UNCHANGED
    ) -> None:
        s = self.state
        if s.combat and not combat:
            s.settle_until = now + 10
        s.combat, s.live = combat, live
        if presence is not UNCHANGED and (
            not s.presence_tracked or presence != s.presence
        ):
            s.presence_tracked, s.presence = True, presence
            self.retire_elsewhere(now)
        if s.visible and s.visible.level == "glance" and (combat or not live):
            visible = s.visible
            self._clear_slot(now, "superseded")
            self.defer(visible, now, "context_hold")
        self.tick(now)

    def ingest(self, c: Candidate, now: float) -> None:
        s = self.state
        if c.scope.commander is None:
            self.emit(c, now, "record", "commander_unknown")
            return
        if c.scope != self.scope:
            self.emit(c, now, "record", "inactive_generation")
            return
        self.tick(now)
        if c.candidate_id in s.seen:
            self.emit(c, now, "record", "duplicate")
            return
        s.seen[c.candidate_id] = now
        while len(s.seen) > MAX_SEEN:
            s.seen.popitem(last=False)
        if c.replay:
            self.emit(c, now, "record", "replay")
            return
        if (
            not c.supported
            or not c.evidence_ref
            or c.confidence not in {"verified", "commander_declared"}
        ):
            self.emit(c, now, "record", "unsupported_evidence")
            return
        if c.observed_at is None or not 0 <= now - c.observed_at < c.ttl:
            self.emit(c, now, "record", "expired_or_missing_time")
            return
        if c.condition:
            self._condition(c, now)
            return
        if c.level == "interrupt":
            self.emit(c, now, "record", "missing_condition")
        elif c.aggregation_key:
            prior = s.aggregates.get(c.aggregation_key)
            if not prior and len(s.aggregates) >= MAX_DEFERRED:
                self.emit(c, now, "record", "aggregation_capacity")
                return
            s.aggregates[c.aggregation_key] = (
                c,
                min(100000, (prior[1] if prior else 0) + c.quantity),
                prior[2] if prior else now,
            )
            self.emit(c, now, "aggregate", "collecting")
        elif c.level == "record":
            self.emit(c, now, "record", "routine")
        else:
            self.offer(c, now)

    def _condition(self, c: Candidate, now: float) -> None:
        s = self.state
        if not c.scope.ship or not self.fresh(c, now):
            self.emit(c, now, "record", "stale_or_unscoped_condition")
            return
        old = s.conditions.get(c.condition)
        if old and (
            c.observed_at is None
            or c.observed_at < (old.candidate.observed_at or 0)
            or (
                c.observed_at == old.candidate.observed_at
                and c.revision <= old.candidate.revision
            )
        ):
            self.emit(c, now, "record", "out_of_order")
            return
        if old is None and len(s.conditions) >= MAX_CONDITIONS:
            removable = next(
                (
                    key
                    for key, value in s.conditions.items()
                    if value.state in {"resolved", "unknown"}
                ),
                None,
            )
            if removable is None:
                self.emit(c, now, "record", "condition_capacity")
                return
            del s.conditions[removable]
        ack = old.acknowledged_priority if old else None
        retired = old.retired_priority if old else None
        episode = old.episode if old else 0
        if c.state == "resolved" or (ack is not None and c.priority > ack):
            ack = None
        if c.state != "active" or (retired is not None and c.priority > retired):
            retired = None
        if c.state == "active" and (
            old is None or old.state in {"resolved", "unknown", "newly_observed"}
        ):
            # A new episode. After a recovery, or a transient condition's
            # evidence lapsing, an earlier acknowledgement/presentation does not
            # silence it. A persistent condition only becomes unknown at a scope
            # boundary, where activate() already reset ship/session state.
            episode += 1
            lapsed = (
                old is not None
                and old.state == "unknown"
                and not rule_for(c.condition).persistent
            )
            if old is None or old.state == "resolved" or lapsed:
                ack = retired = None
        state = (
            c.state
            if c.state != "active"
            else "acknowledged"
            if ack is not None
            else "active"
        )
        s.conditions[c.condition] = Condition(c, state, ack, retired, episode)
        if s.visible and s.visible.condition == c.condition:
            if state == "active" and c.level == "interrupt":
                # A new sample updates an already-visible episode without a
                # second presentation; escalation extends its attention window.
                if c.priority > s.visible.priority:
                    s.presented_at = now
                    s.visible_until = now + attention_for(c)
                self._update_visible(c)
            else:
                self._clear_slot(now, "resolved" if state == "resolved" else "expired")
        self.emit(c, now, "condition", state)
        self.tick(now)

    def here(self, c: Candidate) -> bool | None:
        """Is the place a knowledge moment describes still where the Commander is?

        None when that cannot be told: no place key, presence not tracked, or the
        current location unknown (which proves neither presence nor departure).
        """
        s = self.state
        if not (self.owner_paced(c) and c.context_key and s.presence_tracked):
            return None
        if s.presence is None:
            return None
        return c.context_key in s.presence

    def retire_elsewhere(self, now: float) -> None:
        """Retire briefings about a place the Commander has observably left.

        Waiting ones are dropped and a visible one leaves the slot, so neither is
        delivered or kept as if it described the present.  The Galactic
        Intelligence record keeps them for reading; a later return never
        resurrects them (their identities stay in ``seen``).
        """
        s = self.state
        for key, item in list(s.deferred.items()):
            if self.here(item) is False:
                del s.deferred[key]
                self.emit(item, now, "expire", "place_left")
        if s.visible is not None and self.here(s.visible) is False:
            visible = s.visible
            self.emit(visible, now, "expire", "place_left")
            self._clear_slot(now, "superseded")

    def supersede_places(self, c: Candidate, now: float) -> None:
        """Drop waiting briefings about another place once a newer one arrives.

        A briefing held through combat or a busy slot describes where the
        commander was; after a newer moment elsewhere it would read as the new
        arrival.  The Galactic Intelligence record keeps it for reading.
        """
        if not (self.owner_paced(c) and c.context_key):
            return
        s = self.state
        for key, item in list(s.deferred.items()):
            if (
                self.owner_paced(item)
                and item.context_key
                and item.context_key != c.context_key
                and (item.observed_at or 0) <= (c.observed_at or 0)
            ):
                del s.deferred[key]
                self.emit(item, now, "expire", "superseded_by_newer_place")

    def defer(self, c: Candidate, now: float, reason: str) -> None:
        s = self.state
        key = c.semantic_key or c.candidate_id
        if key not in s.deferred and len(s.deferred) >= MAX_DEFERRED:
            self.emit(c, now, "record", "deferred_capacity")
            return
        s.deferred[key] = c
        self.emit(c, now, "defer", reason)

    @staticmethod
    def owner_paced(c: Candidate) -> bool:
        """A briefing whose owner (Galactic Intelligence) already paces it.

        GKI applies its own frequency, encounter cooldowns and active limit, so
        the Director only times it (combat/unknown hold, one slot) and releases
        it individually: never rate-limited away or merged into a summary,
        which would lose the briefing it refers to.
        """
        return c.category == "knowledge" and bool(c.subject)

    def offer(self, c: Candidate, now: float) -> None:
        s, prefs = self.state, self.state.preferences
        denial = prefs.denial(c)
        if denial:
            self.emit(c, now, "record", denial)
            return
        self.supersede_places(c, now)
        if self.owner_paced(c) and c.context_key and self.state.presence_tracked:
            if self.state.presence is None:
                # Not knowing where the Commander is now proves nothing either
                # way: hold the briefing rather than present it as current.
                self.defer(c, now, "location_unknown")
                return
            if c.context_key not in self.state.presence:
                self.emit(c, now, "expire", "place_left")
                return
        if c.observed_at is None or now >= c.observed_at + c.ttl:
            self.emit(c, now, "expire", "candidate_expired")
            return
        if s.combat or not s.live or now < s.settle_until:
            self.defer(c, now, "combat_or_unknown_or_settling")
            return
        key = c.semantic_key or c.candidate_id
        paced = self.owner_paced(c)
        if not paced and now - s.last_shown.get(key, -100000) < 60:
            self.emit(c, now, "record", "semantic_cooldown")
            return
        if s.visible or (
            not paced
            and (
                (s.glance_times and now - s.glance_times[-1] < prefs.interval)
                or len(s.glance_times) >= prefs.max_per_minute
            )
        ):
            self.defer(c, now, "attention_budget")
            return
        surface = (
            "overlay"
            if prefs.overlay
            and prefs.overlay_glances
            and self.overlay_available
            and "overlay" in c.surfaces
            else "desktop"
        )
        if surface not in c.surfaces:
            self.emit(c, now, "record", "no_permitted_surface")
            return
        if not paced:
            s.glance_times.append(now)
            s.last_shown[key] = now
            while len(s.last_shown) > MAX_CONDITIONS:
                s.last_shown.popitem(last=False)
        self._show(c, surface, now, "eligible", now + prefs.duration)

    def acknowledge(self, identity: str, now: float) -> bool:
        """Acknowledge by candidate or presentation identity.

        Acknowledgement dismisses the presentation, never the condition: an
        acknowledged critical stays in the condition ledger until fresh evidence
        resolves it, and material escalation can present it again.
        """
        s = self.state
        if s.visible is None or identity not in {
            s.visible.candidate_id,
            s.presentation_id,
        }:
            return False
        c = s.visible
        if c.condition and c.condition in s.conditions:
            condition = s.conditions[c.condition]
            condition.acknowledged_priority = c.priority
            condition.state = "acknowledged"
        self._clear_slot(now, "acknowledged" if c.condition else "dismissed")
        self.emit(c, now, "acknowledge", "commander")
        self.tick(now)
        return True

    def tick(self, now: float) -> None:
        s, prefs = self.state, self.state.preferences
        while s.seen and next(iter(s.seen.values())) < now - RETENTION:
            s.seen.popitem(last=False)
        while s.glance_times and now - s.glance_times[0] >= 60:
            s.glance_times.popleft()
        if s.visible and (
            prefs.denial(s.visible)
            or (s.visible.level == "glance" and now >= s.visible_until)
        ):
            self.emit(s.visible, now, "expire", "preferences_or_duration")
            self._clear_slot(now, "expired")
        for condition in s.conditions.values():
            c = condition.candidate
            if condition.state not in {"unknown", "resolved"} and not self.current(
                condition, now
            ):
                condition.state = "unknown"
                if s.visible and s.visible.condition == c.condition:
                    self._clear_slot(now, "expired")
                self.emit(c, now, "condition", "unknown")
        if (
            s.visible
            and s.visible.level == "interrupt"
            and now >= s.presented_at + attention_for(s.visible)
        ):
            visible = s.visible
            held = s.conditions.get(visible.condition)
            if held:
                held.retired_priority = visible.priority
            self.emit(visible, now, "expire", "attention_window")
            self._clear_slot(now, "expired")
        for key, condition in list(s.conditions.items()):
            if (
                condition.candidate.observed_at is not None
                and now - condition.candidate.observed_at >= RETENTION
            ):
                del s.conditions[key]
        visible_condition = s.visible.condition if s.visible else None
        active = sorted(
            (
                v.candidate
                for v in s.conditions.values()
                if v.state == "active"
                and v.candidate.level == "interrupt"
                and not prefs.denial(v.candidate)
                and (
                    v.retired_priority is None
                    or v.candidate.priority > v.retired_priority
                )
            ),
            # Ties keep the presentation already on screen, so an update to an
            # equal-priority condition never flips the slot back and forth.
            key=lambda c: (
                -c.priority,
                0 if c.condition == visible_condition else 1,
                c.observed_at or 0,
                c.condition,
            ),
        )
        if active:
            top = active[0]
            surface = self.interrupt_surface(top)
            if surface and (s.visible is None or s.visible.condition != top.condition):
                if s.visible and s.visible.level == "glance":
                    glance = s.visible
                    self._clear_slot(now, "superseded")
                    self.defer(glance, now, "critical_preemption")
                elif s.visible:
                    self.emit(s.visible, now, "supersede", "higher_priority")
                    self._clear_slot(now, "superseded")
                self._show(
                    top,
                    surface,
                    now,
                    "critical_priority",
                    now + attention_for(top),
                )
        for key, (c, total, started) in list(s.aggregates.items()):
            if now - started >= 6:
                del s.aggregates[key]
                self.offer(
                    replace(
                        c,
                        level="glance",
                        copy_key="materials",
                        quantity=total,
                        semantic_key=key,
                    ),
                    now,
                )
        for key, c in list(s.deferred.items()):
            if c.observed_at is None or now >= c.observed_at + c.ttl or prefs.denial(c):
                del s.deferred[key]
                self.emit(c, now, "expire", "deferred_expired_or_disabled")
        if (
            s.deferred
            and not s.visible
            and not s.combat
            and s.live
            and now >= s.settle_until
        ):
            paced = next(
                (k for k, item in s.deferred.items() if self.owner_paced(item)), None
            )
            if paced is not None:
                # Briefings are released one at a time, as themselves.
                self.offer(s.deferred.pop(paced), now)
            elif (
                not s.glance_times or now - s.glance_times[-1] >= prefs.interval
            ) and len(s.glance_times) < prefs.max_per_minute:
                items = list(s.deferred.values())
                s.deferred.clear()
                c = items[0]
                # Underlying candidates/decisions remain in the evidence ledger.
                if len(items) > 1 or c.semantic_key in s.last_shown:
                    c = replace(
                        c,
                        copy_key="summary",
                        category="app",
                        semantic_key="deferred-summary",
                        quantity=len(items),
                        destination="activity-log",
                        subject="",
                    )
                self.offer(c, now)

    def forget(self, commander: str) -> None:
        if self.scope.commander == commander:
            self._clear_slot(0, "scope_changed")
        self.profiles.pop(commander, None)
        self.decisions = deque(
            (d for d in self.decisions if d.candidate.scope.commander != commander),
            maxlen=MAX_RECORDS,
        )
        if self.scope.commander == commander:
            self.scope = Scope(generation=self.scope.generation + 1)

    def summary(self) -> dict[str, Any]:
        s = self.state
        return {
            "scope": {
                "commander": self.scope.commander,
                "ship": self.scope.ship,
                "generation": self.scope.generation,
            },
            "visible_candidate": s.visible.candidate_id if s.visible else None,
            "presentation_id": s.presentation_id if s.visible else None,
            "surface": s.surface if s.visible else None,
            "overlay_available": self.overlay_available,
            "conditions": {key: value.state for key, value in s.conditions.items()},
            "deferred": len(s.deferred),
            "seen": len(s.seen),
            "profiles": len(self.profiles),
        }
