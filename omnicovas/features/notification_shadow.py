"""Notification Director service: bounded admission, arbitration and presentation.

Observers normalize and enqueue only. One worker serializes arbitration,
persistence and presentation. Two admission lanes keep critical safety state
apart from ordinary traffic:

* conditions (hull, fuel, heat, shields, modules, interdiction) coalesce into a
  small map keyed by scope generation and condition, latest evidence winning, so
  no volume of ordinary frames can displace a warning or its resolution;
* everything else waits in a bounded queue that drops its oldest frames under
  pressure, with the count reported.

Each pass also reconciles hull/fuel against StateManager's accepted fields, so a
condition whose original frame never arrived is still recovered from current,
fresh state. Presentation ownership is explicit: the Director presents only when
configured to and healthy; otherwise the legacy overlay path stays authoritative
and the Director keeps evaluating in shadow.
"""

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.config.vault import ConfigVault
from omnicovas.core.activity_log import ActivityEntry
from omnicovas.core.broadcaster import ShipStateBroadcaster, ShipStateEvent
from omnicovas.core.dispatcher import EventDispatcher
from omnicovas.core.journal_watcher import is_startup_replay
from omnicovas.core.observation import (
    CURRENT_OBSERVATION,
    Scope,
    fingerprint,
    timestamp,
)
from omnicovas.core.state_manager import StateManager
from omnicovas.db.models import (
    CommanderMemoryProfile,
    CommanderMemorySettings,
    NotificationShadowCheckpoint,
    NotificationShadowDecision,
)
from omnicovas.features import commander_context, galactic_intelligence
from omnicovas.features import notification_adapters as adapters
from omnicovas.features.commander_memory import PROFILE_EVENTS, profile_key_for_event
from omnicovas.features.galactic_intelligence import GalacticIntelligence
from omnicovas.features.notification_contracts import (
    POLICY_VERSION,
    Candidate,
    Preferences,
)
from omnicovas.features.notification_director import (
    MAX_CONDITIONS,
    MAX_PROFILES,
    MAX_SEEN,
    RETENTION,
    Condition,
    Director,
)
from omnicovas.features.notification_preferences import (
    ANCHORS,
    NotificationPreferenceStore,
    effective,
)
from omnicovas.features.notification_presenter import OWNERS, Presenter

logger = logging.getLogger(__name__)
QUEUE_LIMIT = 256
CRITICAL_LIMIT = MAX_CONDITIONS
DISK_LIMIT = 4096
OWNER_KEY = "notification_presentation_owner"
PREFERENCE_KEYS = (
    "overlay_events",
    "settings_notifications",
    "settings_galactic_intelligence",
)
FAILURES_BEFORE_FALLBACK = 3
# Combat context must be current: an inferred combat flag left by replayed or
# long-past hostility does not hold notices indefinitely.
COMBAT_RECENCY = 120.0


@dataclass(frozen=True)
class Frame:
    scope: Scope
    candidates: tuple[Candidate, ...]
    combat: bool
    live: bool
    observed_at: float
    # GKI-08 closeout: fingerprints of the Commander Context's current places
    # (system; station while docked), or None when the location is unknown.
    presence: frozenset[str] | None = None


class NotificationShadow:
    """Only the worker mutates policy. Observer callbacks do bounded, no-I/O work."""

    def __init__(
        self,
        state: StateManager,
        factory: async_sessionmaker[AsyncSession] | None,
        vault: ConfigVault,
        intelligence: GalacticIntelligence,
        profile_provider: Callable[[], str | None],
        *,
        clock: Callable[[], float] = time.time,
        enabled: bool | None = None,
    ) -> None:
        self.state, self.factory, self.vault = state, factory, vault
        self.intelligence, self.profile_provider, self.clock = (
            intelligence,
            profile_provider,
            clock,
        )
        self.enabled = (
            enabled
            if enabled is not None
            else os.getenv("OMNICOVAS_NOTIFICATION_SHADOW", "1").lower()
            not in {"0", "false", "off"}
        )
        self.director = Director()
        self.scope = Scope()
        self.live = False
        self.telemetry_at = 0.0
        self.pending: deque[Frame] = deque()
        self.wake = asyncio.Event()
        self.task: asyncio.Task[None] | None = None
        self.stopping = False
        self.lock = asyncio.Lock()
        self.failures = 0
        self.dropped = 0
        self.evaluated = 0
        self.max_pending = 0
        self.last_context = 0.0
        self.last_compaction = 0.0
        self.clear_requested = False
        self.restored: set[str] = set()
        self.opportunity_providers: tuple[Callable[[], list[dict[str, Any]]], ...] = ()
        self.preferences_override: Preferences | None = (
            None  # injected offline tests; never a UI setting
        )
        # Critical lane: latest evidence per (scope generation, condition).
        self.critical: OrderedDict[str, Candidate] = OrderedDict()
        self.coalesced = 0
        self.stale_coalesced = 0
        self.critical_evicted = 0
        self.max_critical = 0
        self.reconciled: dict[str, float] = {}
        self.recovered = 0
        self.scope_started_at = 0.0
        self.consecutive_failures = 0
        self.last_success = 0.0
        self._context_key: tuple[Any, ...] | None = None
        self.latest_context: Frame | None = None
        self.store = NotificationPreferenceStore(vault)
        self._prefs_cache: tuple[tuple[Any, ...], Preferences] | None = None
        self._display_cache: tuple[tuple[Any, ...], dict[str, Any]] | None = None
        self.presenter = Presenter(self.configured_owner())
        self.publish: Callable[[dict[str, Any]], Awaitable[None]] | None = None

    def capture_scope(self, event: dict[str, Any]) -> Scope:
        if not self.enabled:
            return Scope()
        name = event.get("event")
        profile, ship = self.scope.commander, self.scope.ship
        session = self.scope.session
        if name == "Fileheader":
            session = (
                fingerprint(str(event.get("timestamp")))
                if timestamp(event.get("timestamp")) is not None
                else None
            )
        if name in PROFILE_EVENTS:
            profile = profile_key_for_event(event)[0]
        if (
            name in {"LoadGame", "Loadout"}
            and isinstance(event.get("ShipID"), int)
            and not isinstance(event.get("ShipID"), bool)
        ):
            ship = fingerprint(str(event["ShipID"]))
        if profile != self.scope.commander:
            ship = (
                fingerprint(str(event["ShipID"]))
                if isinstance(event.get("ShipID"), int)
                else None
            )
        boundary = name in {"Shutdown", "Died", "Resurrect"}
        if (
            profile != self.scope.commander
            or ship != self.scope.ship
            or session != self.scope.session
            or boundary
        ):
            self.scope = Scope(profile, ship, self.scope.generation + 1, session)
            self.scope_started_at = timestamp(event.get("timestamp")) or self.clock()
            self.live = False
        observed = timestamp(event.get("timestamp"))
        fresh = observed is not None and 0 <= self.clock() - observed <= 3
        # Any fresh (<=3 s), non-replayed observation for an identified
        # commander shows the game is running: LoadGame and Status, but also a
        # docking or jump when OmniCOVAS started after the game (the LoadGame
        # was replayed) and Status.json has not changed since.
        if (
            name != "Fileheader"
            and fresh
            and not is_startup_replay()
            and profile
            and not boundary
        ):
            self.live = True
        if boundary:
            self.live = False
        if observed is not None and fresh and not is_startup_replay():
            self.telemetry_at = max(self.telemetry_at, observed)
        return self.scope

    # ── Admission ───────────────────────────────────────────────────────────

    def _frame(
        self, scope: Scope, candidates: list[Candidate], observed_at: float | None
    ) -> None:
        if not self.enabled:
            return
        # A non-identity Name on this baseline can corrupt upstream Memory identity.
        # Never adopt it: only identity events select a notification profile.
        verified = (
            scope.commander is not None and self.profile_provider() == scope.commander
        )
        demand = self.high_demand()
        live = self.live and verified and 0 <= self.clock() - self.telemetry_at <= 10
        observed = observed_at or 0
        presence = self.presence()
        ordinary: list[Candidate] = []
        for c in candidates[:128]:
            if c.condition:
                self._admit_condition(c)
            else:
                ordinary.append(c)
        context = (scope, demand, live, presence)
        self.latest_context = Frame(scope, (), demand, live, observed, presence)
        if ordinary or context != self._context_key:
            self._context_key = context
            if len(self.pending) >= QUEUE_LIMIT:
                # Ordinary work only: conditions never wait in this queue.
                self.pending.popleft()
                self.dropped += 1
            self.pending.append(
                Frame(scope, tuple(ordinary), demand, live, observed, presence)
            )
        self.max_pending = max(self.max_pending, len(self.pending))
        self.wake.set()

    def presence(self) -> frozenset[str] | None:
        """Where the Commander is now, from the existing Commander Context.

        Reads the same StateManager projections Galactic Intelligence uses; no
        location of its own.  Liveness is judged by the frame, so the context is
        built as of now.  Any failure reads as unknown, never as a place.
        """
        try:
            context = commander_context.build(
                self.state,
                profile_key=self.scope.commander,
                last_journal_event_at=datetime.fromtimestamp(
                    self.clock(), timezone.utc
                ),
                now=datetime.fromtimestamp(self.clock(), timezone.utc),
            )
            keys = galactic_intelligence.presence_keys(context)
        except Exception:
            return None
        return frozenset(fingerprint(k) for k in keys) if keys else None

    def high_demand(self) -> bool:
        """Interdiction, or hostility observed within COMBAT_RECENCY seconds."""
        combat = self.state.snapshot.combat
        now = self.clock()

        def current(field: Any) -> bool:
            at = timestamp(field.timestamp)
            return (
                field.value is True
                and at is not None
                and 0 <= now - at <= COMBAT_RECENCY
            )

        return (
            current(combat.workflow.interdiction_active)
            or current(combat.threat.under_attack)
            or current(combat.session.active)
        )

    def _admit_condition(self, c: Candidate) -> None:
        """Coalesce condition evidence; never displaced by ordinary traffic."""
        key = f"{c.scope.generation}:{c.condition}"
        prior = self.critical.get(key)
        if prior is not None:
            if (c.observed_at or 0, c.revision) < (
                prior.observed_at or 0,
                prior.revision,
            ):
                self.stale_coalesced += 1
                return
            self.coalesced += 1
        elif len(self.critical) >= CRITICAL_LIMIT:
            # Only reachable with >128 distinct conditions waiting at once.
            # Prefer work for an inactive scope, then non-interrupt samples.
            victim = next(
                (
                    k
                    for k, v in self.critical.items()
                    if v.scope.generation != c.scope.generation
                ),
                None,
            ) or next(
                (k for k, v in self.critical.items() if v.level != "interrupt"),
                next(iter(self.critical)),
            )
            del self.critical[victim]
            self.critical_evicted += 1
        self.critical[key] = c
        self.critical.move_to_end(key)
        self.max_critical = max(self.max_critical, len(self.critical))

    def has_work(self) -> bool:
        return bool(self.pending or self.critical)

    async def observe_projection(self, event: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            o = CURRENT_OBSERVATION.get()
            if o is not None:
                candidates = adapters.projection(event, self.state, o)
                if o.event_type != "Status":
                    for provider in self.opportunity_providers:
                        for payload in provider()[:50]:
                            trigger = payload.get("trigger", {})
                            if (
                                isinstance(trigger, dict)
                                and trigger.get("event") == o.event_type
                                and timestamp(trigger.get("observed_at"))
                                == o.observed_at
                                and payload.get("profile_key") == o.scope.commander
                            ):
                                candidate = adapters.narrative(payload, o.scope)
                                candidates.append(
                                    replace(
                                        candidate, replay=o.replay or candidate.replay
                                    )
                                )
                self._frame(o.scope, candidates, o.observed_at)
        except Exception:
            self.failures += 1

    async def observe_broadcast(self, event: ShipStateEvent) -> None:
        if not self.enabled:
            return
        try:
            candidates = adapters.broadcast(event)
            if candidates:
                self._frame(candidates[0].scope, candidates, candidates[0].observed_at)
        except Exception:
            self.failures += 1

    def observe_bridge(self, event: dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            candidate = adapters.briefing(event, CURRENT_OBSERVATION.get())
            if candidate:
                self._frame(candidate.scope, [candidate], candidate.observed_at)
        except Exception:
            self.failures += 1

    def observe_activity(self, entry: ActivityEntry) -> None:
        if not self.enabled:
            return
        try:
            if entry.event_type in {
                "COMMANDER_MEMORY_CLEARED",
                "COMMANDER_MEMORY_CATEGORY_DELETED",
            }:
                self.clear_requested = True
                self.pending.clear()
                self.critical.clear()
                self.wake.set()
                return
            candidate = adapters.activity(entry, self.scope)
            if candidate:
                self._frame(candidate.scope, [candidate], candidate.observed_at)
        except Exception:
            self.failures += 1

    # ── Preferences and ownership ───────────────────────────────────────────

    def _preference_stamp(self, commander: str | None) -> tuple[Any, ...] | None:
        """Cheap change detector: the vault's stored (still encrypted) values.

        Any write through Settings, the overlay API or GKI changes the stamp, so
        a cached result is never stale; nothing is decrypted when unchanged.
        """
        data = getattr(self.vault, "_data", None)
        if not isinstance(data, dict):
            return None
        return (
            commander,
            id(self.preferences_override),
            *(data.get(key) for key in PREFERENCE_KEYS),
        )

    async def preferences(self, commander: str | None) -> Preferences:
        stamp = self._preference_stamp(commander)
        cached = self._prefs_cache
        if stamp is not None and cached and cached[0] == stamp:
            return cached[1]
        disabled: set[str] = set()
        raw = self.vault.get("overlay_events")
        if raw:
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = None  # corrupted switches read as defaults (all on)
            if isinstance(parsed, dict):
                disabled |= {
                    key
                    for key, value in parsed.items()
                    if value is False and key in adapters.OVERLAY_TYPES
                }
        base = self.preferences_override or effective(
            self.store.get(commander), self.store.device()
        )
        if commander is None:
            prefs = replace(base, disabled_events=base.disabled_events | disabled)
        else:
            gki = await self.intelligence.preferences_for(commander)
            disabled |= {
                "gki:" + key
                for key, value in gki.get("content", {}).items()
                if value is False
            }
            prefs = replace(
                base,
                disabled_events=base.disabled_events | frozenset(disabled),
                lore=bool(gki.get("enabled")) and gki.get("frequency") != "off",
                spoilers=not bool(gki.get("spoiler_protection", True)),
            )
        if stamp is not None:
            # Forgetting a commander invalidates explicitly (after_forget).
            self._prefs_cache = (stamp, prefs)
        return prefs

    def invalidate_preferences(self) -> None:
        self._prefs_cache = None

    def configured_owner(self) -> str:
        env = os.getenv("OMNICOVAS_NOTIFICATION_OWNER", "").strip().lower()
        if env in OWNERS:
            return env
        try:
            stored = self.vault.get(OWNER_KEY)
        except Exception:
            stored = None
        return stored if stored in OWNERS else "director"

    def display(self) -> dict[str, Any]:
        """Device presentation settings sent with every snapshot.

        Cached on the stored (encrypted) vault values, so an unchanged setting
        costs no decryption on the worker's per-second pass.
        """
        data = getattr(self.vault, "_data", None)
        stamp = (
            tuple(
                data.get(key)
                for key in (
                    "settings_overlay_anchor",
                    "settings_overlay_opacity",
                    "settings_notifications",
                )
            )
            if isinstance(data, dict)
            else None
        )
        if (
            stamp is not None
            and self._display_cache
            and self._display_cache[0] == stamp
        ):
            return self._display_cache[1]
        device = self.store.device()
        anchor, opacity = "tr", 0.95
        try:
            stored = self.vault.get("settings_overlay_anchor")
            if stored in ANCHORS:
                anchor = stored
            raw = self.vault.get("settings_overlay_opacity")
            if raw is not None and 0.5 <= float(raw) <= 1.0:
                opacity = float(raw)
        except (TypeError, ValueError):
            pass
        result = {
            "anchor": anchor,
            "opacity": opacity,
            "text_scale": device["text_scale"],
            "reduced_motion": device["reduced_motion"],
            "overlay": device["overlay"],
        }
        if stamp is not None:
            self._display_cache = (stamp, result)
        return result

    def healthy(self) -> tuple[bool, str]:
        if not self.enabled:
            return False, "director_disabled"
        if self.consecutive_failures >= FAILURES_BEFORE_FALLBACK:
            return False, "worker_failing"
        if self.task is not None and self.task.done():
            return False, "worker_stopped"
        if self.task is None and not (
            self.last_success and 0 <= self.clock() - self.last_success <= 5
        ):
            # Not started (or driven manually and idle): nothing presents.
            return False, "worker_stopped"
        return True, "healthy"

    async def _publish(self) -> None:
        if self.publish is None:
            return
        try:
            await self.publish(self.presenter.snapshot())
        except Exception:
            # A disconnected client cannot fail arbitration; receipts show it.
            logger.debug("Notification presentation publish failed")

    async def degrade(self, reason: str) -> None:
        """Hand presentation back to the legacy path and tell every client."""
        if self.presenter.evaluate_owner(healthy=False, reason=reason):
            self.presenter.tick(self.director, self.clock())
            await self._publish()

    def presentation_snapshot(self) -> dict[str, Any]:
        healthy, reason = self.healthy()
        if not healthy and self.presenter.owner == "director":
            self.presenter.evaluate_owner(healthy=False, reason=reason)
            self.presenter.tick(self.director, self.clock())
        return self.presenter.snapshot()

    async def acknowledge(self, presentation_id: str, client: str) -> bool:
        async with self.lock:
            now = self.clock()
            done = self.director.acknowledge(presentation_id, now)
            if done:
                p = self.presenter.presentations.get(presentation_id)
                if p:
                    p.add("acknowledge_requested", client, now)
                if self.presenter.tick(self.director, now):
                    await self._publish()
            return done

    async def receipt(
        self, presentation_id: str | None, client: str, status: str, detail: str = ""
    ) -> bool:
        async with self.lock:
            now = self.clock()
            accepted = self.presenter.receipt(
                presentation_id, client, status, now, detail
            )
            if accepted and self.presenter.owner == "director":
                self.director.set_overlay_available(
                    self.presenter.overlay_usable(), now
                )
                if self.presenter.tick(self.director, now):
                    await self._publish()
            return accepted

    async def set_owner(self, owner: str) -> dict[str, Any]:
        if owner not in OWNERS:
            raise ValueError("owner must be director or legacy")
        if not self.vault.set(OWNER_KEY, owner):
            raise OSError("Presentation owner could not be saved")
        async with self.lock:
            self.presenter.configured_owner = owner
            healthy, reason = self.healthy()
            # An explicit choice applies on the next healthy confirmation.
            self.presenter.healthy_passes = 2
            self.presenter.evaluate_owner(healthy=healthy, reason=reason)
            self.presenter.tick(self.director, self.clock())
            await self._publish()
        return self.presenter.snapshot()

    # ── Worker ──────────────────────────────────────────────────────────────

    async def _restore(self, commander: str | None, now: float) -> None:
        if not commander or commander in self.restored or self.factory is None:
            return
        async with self.factory() as db:
            rows = await db.execute(
                select(
                    NotificationShadowDecision.candidate_id,
                    NotificationShadowDecision.evaluated_at,
                )
                .where(
                    NotificationShadowDecision.commander == commander,
                    NotificationShadowDecision.evaluated_at >= now - RETENTION,
                )
                .order_by(NotificationShadowDecision.id.desc())
                .limit(MAX_SEEN)
            )
            for identity, at in reversed(rows.all()):
                self.director.state.seen[identity] = at
            checkpoint = await db.get(NotificationShadowCheckpoint, commander)
            if checkpoint and checkpoint.updated_at >= now - RETENTION:
                try:
                    payload = json.loads(checkpoint.state_json)
                except (TypeError, ValueError):
                    payload = {}
                if (
                    isinstance(payload, dict)
                    and payload.get("policy") == POLICY_VERSION
                ):
                    for item in payload.get("conditions", [])[:128]:
                        try:
                            raw = dict(item["candidate"])
                            raw["scope"] = Scope(**raw["scope"])
                            raw["surfaces"] = tuple(raw["surfaces"])
                            candidate = Candidate(**raw)
                        except (KeyError, TypeError, ValueError):
                            continue  # corrupted checkpoint rows are skipped
                        # Restart never restores an active warning: fresh
                        # evidence is required before anything is presented.
                        self.director.state.conditions[candidate.condition] = Condition(
                            candidate,
                            "unknown",
                            item.get("ack")
                            if self.scope.session is not None
                            and candidate.scope.session == self.scope.session
                            else None,
                        )
                    for key, at in payload.get("cooldowns", [])[:128]:
                        if (
                            isinstance(key, str)
                            and isinstance(at, (float, int))
                            and 0 <= now - at < 60
                        ):
                            self.director.state.last_shown[key] = at
                    for at in payload.get("glance_times", [])[-2:]:
                        if isinstance(at, (float, int)) and 0 <= now - at < 60:
                            self.director.state.glance_times.append(at)
        self.restored.add(commander)
        if len(self.restored) > MAX_PROFILES:
            self.restored = {commander}

    async def process(self) -> None:
        """One bounded worker batch; also used by deterministic integration tests."""
        if self.clear_requested:
            await self.clear()
            self.clear_requested = False
        async with self.lock:
            if not self.enabled:
                return
            now = self.clock()
            if self.scope != self.director.scope:
                self.last_context = 0
            self.director.activate(self.scope, now)
            await self._restore(self.scope.commander, now)
            if await self.intelligence.is_forgotten(self.scope.commander or "default"):
                self.pending.clear()
                self.critical.clear()
                self.director.forget(self.scope.commander or "default")
                return
            director_owned = self.presenter.owner == "director"
            self.director.presentation_mode = "director" if director_owned else "shadow"
            # In shadow the overlay is assumed for comparison; when the Director
            # presents, only a ready overlay that renders counts as available.
            if director_owned:
                self.director.set_overlay_available(
                    self.presenter.overlay_usable(), now
                )
            else:
                self.director.overlay_available = True
            self.director.configure(await self.preferences(self.scope.commander), now)
            # Conditions first, in observed order: they never wait behind
            # ordinary frames and cannot be crowded out by them.
            batch = sorted(
                self.critical.values(), key=lambda c: (c.observed_at or 0, c.revision)
            )
            self.critical.clear()
            for c in batch:
                self.director.ingest(c, now)
                self.evaluated += 1
            for _ in range(min(64, len(self.pending))):
                frame = self.pending.popleft()
                if frame.scope == self.scope and frame.observed_at >= self.last_context:
                    self.last_context = frame.observed_at
                    self.director.context(
                        now,
                        combat=frame.combat,
                        live=frame.live,
                        presence=frame.presence,
                    )
                for c in frame.candidates:
                    self.director.ingest(c, now)
                    self.evaluated += 1
            latest = self.latest_context
            if (
                latest is not None
                and latest.scope == self.scope
                and latest.observed_at >= self.last_context
            ):
                self.last_context = latest.observed_at
            if latest is not None and latest.scope == self.scope:
                # Re-evaluated every pass: combat recency can lapse without a
                # new frame (starting the post-combat settling period), and a
                # session with no observation for 10 s is no longer known live.
                self.director.context(
                    now,
                    combat=self.high_demand(),
                    live=latest.live and now - self.last_context <= 10,
                    presence=latest.presence,
                )
            elif now - self.last_context > 10:
                self.director.context(
                    now, combat=self.director.state.combat, live=False
                )
            self._reconcile(now)
            self.director.tick(now)
            await self._persist(now)
            self.consecutive_failures = 0
            self.last_success = now
            changed = self.presenter.evaluate_owner(healthy=True, reason="healthy")
            self.presenter.display = self.display()
            updated = self.presenter.tick(self.director, now)
            if (
                self.presenter.owner == "director"
                and self.director.overlay_available
                and not self.presenter.overlay_usable()
            ):
                # The overlay missed its render deadline: move the alert to the
                # desktop in this same pass rather than waiting another second.
                self.director.set_overlay_available(False, now)
                updated = self.presenter.tick(self.director, now) or updated
            if updated or changed:
                await self._publish()

    def _reconcile(self, now: float) -> None:
        """Recover conditions from accepted current state (hull, fuel).

        Skipped during startup replay; candidates keep the field's provenance
        time, so only fresh state can become a live condition.
        """
        if is_startup_replay() or not self.scope.commander or not self.scope.ship:
            return
        for c in adapters.reconcile(self.state, self.scope):
            if c.observed_at is None or c.observed_at < self.scope_started_at:
                continue
            if self.reconciled.get(c.condition) == c.observed_at:
                continue
            existing = self.director.state.conditions.get(c.condition)
            if existing and (existing.candidate.observed_at or 0) >= c.observed_at:
                continue
            if not self.director.fresh(c, now):
                continue
            self.reconciled[c.condition] = c.observed_at
            self.director.ingest(c, now)
            current = self.director.state.conditions.get(c.condition)
            if current and current.candidate.candidate_id == c.candidate_id:
                self.recovered += 1

    async def _persist(self, now: float) -> None:
        records = list(self.director.decisions)
        if self.factory is None:
            return
        if not records and now - self.last_compaction < 60:
            return
        async with self.factory() as db:
            paused = bool(
                await db.scalar(select(CommanderMemorySettings.paused).limit(1))
            )
            paused_profiles = set(
                await db.scalars(
                    select(CommanderMemoryProfile.profile_key).where(
                        CommanderMemoryProfile.paused.is_(True)
                    )
                )
            )
            for d in records:
                if paused or d.candidate.scope.commander in paused_profiles:
                    continue
                db.add(
                    NotificationShadowDecision(
                        commander=d.candidate.scope.commander,
                        candidate_id=d.candidate.candidate_id,
                        evaluated_at=d.evaluated_at,
                        record_json=json.dumps(d.record(), separators=(",", ":")),
                    )
                )
            for commander, profile in self.director.profiles.items():
                if commander == "unknown" or paused or commander in paused_profiles:
                    continue
                if commander != self.scope.commander:
                    # Idle profiles must age out; another commander's traffic
                    # must never refresh their retention deadline.
                    continue
                checkpoint = await db.get(NotificationShadowCheckpoint, commander)
                if checkpoint is None:
                    checkpoint = NotificationShadowCheckpoint(commander=commander)
                    db.add(checkpoint)
                checkpoint.updated_at = now
                checkpoint.state_json = json.dumps(
                    {
                        "policy": POLICY_VERSION,
                        "cooldowns": list(profile.last_shown.items()),
                        "glance_times": list(profile.glance_times),
                        "conditions": [
                            {
                                "candidate": c.candidate.record(),
                                "ack": c.acknowledged_priority,
                            }
                            for c in profile.conditions.values()
                        ],
                    }
                )
            await db.flush()
            await db.execute(
                delete(NotificationShadowDecision).where(
                    NotificationShadowDecision.evaluated_at < now - RETENTION
                )
            )
            keep = (
                select(NotificationShadowDecision.id)
                .order_by(NotificationShadowDecision.id.desc())
                .limit(DISK_LIMIT)
            )
            await db.execute(
                delete(NotificationShadowDecision).where(
                    NotificationShadowDecision.id.not_in(keep)
                )
            )
            keep_profiles = (
                select(NotificationShadowCheckpoint.commander)
                .order_by(NotificationShadowCheckpoint.updated_at.desc())
                .limit(MAX_PROFILES)
            )
            await db.execute(
                delete(NotificationShadowCheckpoint).where(
                    NotificationShadowCheckpoint.commander.not_in(keep_profiles)
                )
            )
            await db.execute(
                delete(NotificationShadowCheckpoint).where(
                    NotificationShadowCheckpoint.updated_at < now - RETENTION
                )
            )
            await db.commit()
        self.director.decisions.clear()
        self.last_compaction = now

    async def _run(self) -> None:
        while self.enabled and not self.stopping:
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()
            try:
                await self.process()
            except Exception:
                # Do not log raw inputs, identity, titles or source paths.
                self.failures += 1
                self.consecutive_failures += 1
                logger.warning(
                    "Notification Director batch failed; legacy alerts unaffected"
                )
                if self.consecutive_failures >= FAILURES_BEFORE_FALLBACK:
                    await self.degrade("worker_failing")
            if self.has_work():
                self.wake.set()
            await asyncio.sleep(0)

    async def start(self) -> None:
        if self.enabled and self.task is None:
            self.stopping = False
            self.task = asyncio.create_task(self._run(), name="notification-shadow")
            self.task.add_done_callback(self._worker_done)

    def _worker_done(self, task: "asyncio.Task[None]") -> None:
        # An unexpected worker exit must not leave clients waiting on a
        # Director that no longer presents anything.
        if self.stopping:
            return
        try:
            asyncio.get_running_loop().create_task(self.degrade("worker_stopped"))
        except RuntimeError:
            pass

    async def stop(self) -> None:
        self.stopping = True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        self.pending.clear()
        self.critical.clear()

    async def set_enabled(self, enabled: bool) -> None:
        await self.stop()
        self.enabled = enabled
        self.director = Director()
        self.scope = Scope(generation=self.scope.generation + 1)
        self.live = False
        self.last_context = 0
        self.restored.clear()
        self.reconciled.clear()
        if not enabled:
            # Kill switch: the legacy path owns presentation immediately.
            await self.degrade("director_disabled")
        await self.start()

    async def purge_profile(self, db: AsyncSession, commander: str) -> None:
        await db.execute(
            delete(NotificationShadowDecision).where(
                NotificationShadowDecision.commander == commander
            )
        )
        await db.execute(
            delete(NotificationShadowCheckpoint).where(
                NotificationShadowCheckpoint.commander == commander
            )
        )

    async def after_forget(self, commander: str) -> None:
        async with self.lock:
            self.pending = deque(
                f for f in self.pending if f.scope.commander != commander
            )
            self.critical = OrderedDict(
                (k, c)
                for k, c in self.critical.items()
                if c.scope.commander != commander
            )
            self.director.forget(commander)
            self.presenter.forget(commander)
            self.store.forget(commander)
            self.invalidate_preferences()
            self.restored.discard(commander)
            if self.scope.commander == commander:
                self.scope = Scope(generation=self.scope.generation + 1)
                self.live = False
            # A batch that began before the forget commit may have completed a
            # write; erase again after acquiring the worker lock.
            if self.factory:
                async with self.factory() as db:
                    await self.purge_profile(db, commander)
                    await db.commit()

    async def clear(self) -> None:
        async with self.lock:
            self.pending.clear()
            self.critical.clear()
            self.director = Director()
            self.restored.clear()
            if self.factory:
                async with self.factory() as db:
                    await db.execute(delete(NotificationShadowDecision))
                    await db.execute(delete(NotificationShadowCheckpoint))
                    await db.commit()

    async def records(self, limit: int = 100) -> list[dict[str, Any]]:
        if self.factory is None:
            return [
                d.record()
                for d in self.director.decisions
                if d.candidate.scope.commander == self.scope.commander
            ][-max(1, min(limit, 200)) :]
        async with self.factory() as db:
            rows = await db.scalars(
                select(NotificationShadowDecision.record_json)
                .where(
                    NotificationShadowDecision.commander == self.scope.commander,
                    NotificationShadowDecision.evaluated_at >= self.clock() - RETENTION,
                )
                .order_by(NotificationShadowDecision.id.desc())
                .limit(max(1, min(limit, 200)))
            )
            return [json.loads(row) for row in rows]

    def diagnostics(self) -> dict[str, Any]:
        director_owned = self.presenter.owner == "director"
        return {
            "mode": "director" if director_owned else "shadow",
            "enabled": self.enabled,
            "policy": POLICY_VERSION,
            "owner": self.presenter.owner,
            "configured_owner": self.presenter.configured_owner,
            "owner_reason": self.presenter.owner_reason,
            "queued": len(self.pending),
            "queue_limit": QUEUE_LIMIT,
            "max_pending": self.max_pending,
            "dropped": self.dropped,
            "critical_queued": len(self.critical),
            "critical_limit": CRITICAL_LIMIT,
            "max_critical": self.max_critical,
            "coalesced": self.coalesced,
            "stale_coalesced": self.stale_coalesced,
            "critical_evicted": self.critical_evicted,
            "recovered": self.recovered,
            "failures": self.failures,
            "evaluated": self.evaluated,
            "disk_limit": DISK_LIMIT,
            "retention_seconds": RETENTION,
            "production_presentation": "see_delivery_receipts"
            if director_owned
            else "unavailable",
            "receipts": dict(self.presenter.counters),
            "overlay_ready": self.presenter.overlay_usable(),
            "policy_state": self.director.summary(),
        }


def wire(
    dispatcher: EventDispatcher,
    broadcaster: ShipStateBroadcaster,
    service: NotificationShadow,
) -> None:
    dispatcher.register_observer(service.observe_projection, service.capture_scope)
    for kind in adapters.BROADCAST_TYPES:
        broadcaster.subscribe(kind, service.observe_broadcast)
