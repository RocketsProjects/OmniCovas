"""Local-first Combat workflow for Operations (Phase 14 R7).

Phase 4 built a real combat backend: `combat_state.py` holds target, threat,
session focus and the interdiction/escape workflow; `combat_session.py` holds
mission session, conflict context, RedeemVoucher session totals and combat rank;
`pvp_encounter.py` holds durable local PvP records; `readiness.py` already owns
hull, shields, fuel, rebuy and modules. All of it was reachable from an
Operations Combat shell that the Phase 7.5 v2 command-surface rebuild (`d1edf75`)
removed, leaving the backend correct and unread.

This module does not rebuild any of that. It reads those existing services and
answers the workflow questions the cockpit actually needs: what situation am I
in, what is my supported safety posture, what is blocking me, what should I do
next, and what factual record exists from this session.

What this module will and will not claim
----------------------------------------

**Combat mode being open is not an engagement.** The stage is derived from
observed telemetry only. With no combat telemetry at all the stage is Unknown,
never `idle` — "quiet" and "not reported" are different answers.

**Threat is what local detection observed, not the state of local space.** An
explicit `under_attack=false` is a supported fact and is reported as "No hostile
contact detected"; a missing reading is Unknown. The verb is deliberate and is
the same one `deriveHostileContact` uses in the cockpit, so the workflow card and
the watch strip cannot disagree.

**Combat zones stay unsupported.** `combat_session.py` records
`local_conflict_context` from `Location`/`FSDJump` `Conflicts[]` — a fact about
the system's political state. It is not evidence the Commander is in a combat
zone, and no CZ presence, kind or intensity is derived from it, from mission
type, from hostile events or from combat bonds.

**Munitions stay unsupported.** No verified local source reports ammunition
counts. This module reports that absence and never converts it into a readiness
row, a zero, or a blocker.

**AX and Odyssey stay unlabelled.** Generic hull, shield, fuel and module facts
apply to any ship and remain visible as generic facts. Nothing here is described
as AX-ready, Thargoid-ready or Odyssey-ready.

**Absence of module evidence is not absence of the module.** Role fit reports
what was seen fitted; a capability not seen is Unknown. R0 shield doctrine is
the precedent and `readiness.shield_generator_fitted` is its one implementation.

**PvP records are factual and local.** Encounter rows describe what the journal
observed. No player is characterised, no reputation is scored, nothing is looked
up remotely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import JournalEvent, PvpEncounter
from omnicovas.features import readiness

if TYPE_CHECKING:
    from omnicovas.core.state_manager import StateManager

UNKNOWN = "Unknown"

TRUTH_LOCAL_TELEMETRY = "local_telemetry"
TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
TRUTH_UNKNOWN = "unknown"

# ---------------------------------------------------------------------------
# Stage vocabulary
# ---------------------------------------------------------------------------

STAGE_UNKNOWN = "unknown"
STAGE_IDLE = "idle"
STAGE_PREPARATION = "preparation"
STAGE_INTERDICTED = "interdicted"
STAGE_ENGAGED = "engaged"
STAGE_RECOVERY = "recovery"
STAGE_POST_ENGAGEMENT = "post_engagement"
STAGE_REVIEW_READY = "review_ready"

STAGE_ORDER: tuple[str, ...] = (
    STAGE_UNKNOWN,
    STAGE_IDLE,
    STAGE_PREPARATION,
    STAGE_INTERDICTED,
    STAGE_ENGAGED,
    STAGE_RECOVERY,
    STAGE_POST_ENGAGEMENT,
    STAGE_REVIEW_READY,
)

STAGE_LABELS: dict[str, str] = {
    STAGE_UNKNOWN: "Combat state Unknown",
    STAGE_IDLE: "Idle",
    STAGE_PREPARATION: "Preparation",
    STAGE_INTERDICTED: "Interdiction",
    STAGE_ENGAGED: "Engaged",
    STAGE_RECOVERY: "Recovery",
    STAGE_POST_ENGAGEMENT: "Post-engagement",
    STAGE_REVIEW_READY: "Review ready",
}

# Threat states. These labels are shared with the cockpit's `deriveHostileContact`
# so the workflow card and the watch strip state one answer, not two.
THREAT_HOSTILE = "hostile"
THREAT_CLEAR = "clear"
THREAT_UNKNOWN = "unknown"

# Blocker condition ids. `blockingConditionsFor('combat')` decides relevance;
# declaring the id here is what makes a condition eligible at all.
CONDITION_HULL = "combat_hull"
CONDITION_MODULES = "combat_modules"
CONDITION_ESCAPE_ROUTE = "combat_escape_route"

# Readiness fact states. Three, always — never two.
FACT_GOOD = "good"
FACT_PROBLEM = "problem"
FACT_UNKNOWN = "unknown"

# The two source boundaries this slice is required to hold. Both were already
# held by the Phase 4 backend; they are restated here because this module is
# what a Commander actually reads.
MUNITIONS_BOUNDARY = (
    "Ammunition and munitions counts have no verified local source. No journal "
    "or Status field reports them, so OmniCOVAS reports neither a count nor a "
    "zero, and no readiness row or blocker is derived from their absence."
)
CZ_BOUNDARY = (
    "Combat zone presence and intensity are not known. No verified local source "
    "reports whether a combat zone is active or whether it is low, medium or "
    "high, so none is claimed. System conflict state, when observed, describes "
    "the system's politics — not the Commander's location."
)
AX_ODYSSEY_BOUNDARY = (
    "AX and on-foot combat detail are not supported locally. Hull, shields, fuel "
    "and module facts below are generic ship facts and are not a statement that "
    "the ship is equipped for Thargoid or on-foot combat."
)
BASE_CAVEAT = (
    "Combat workflow derived from observed combat telemetry, the local loadout "
    "and recorded journal events. Threat state describes what local detection "
    "observed, not the state of local space. Equipment not seen in the loadout "
    "is Unknown, never confirmed absent."
)
PVP_CAVEAT = (
    "PvP records are local journal observations kept on this machine. No player "
    "is characterised or scored, and no external source is consulted."
)

# Journal events read here, each confirmed present in real local data before use.
DEATH_EVENTS: tuple[str, ...] = ("Died",)
RESURRECT_EVENTS: tuple[str, ...] = ("Resurrect",)
HULL_DAMAGE_EVENTS: tuple[str, ...] = ("HullDamage",)
INTERDICTION_EVENTS: tuple[str, ...] = ("Interdicted", "EscapeInterdiction")


def _identity(kind: str, target: str | None = None) -> str:
    """A stable derived id. Deterministic over the same facts, never random."""
    slug = (target or "").strip().lower().replace(" ", "-")
    return f"combat.objective.{kind}" + (f".{slug}" if slug else "")


# ---------------------------------------------------------------------------
# Reading the Phase 4 combat state
# ---------------------------------------------------------------------------


def _field(combat: Any, group: str, name: str) -> Any:
    """One CombatField value, or None when the field was never written."""
    section = getattr(combat, group, None)
    if section is None:
        return None
    entry = getattr(section, name, None)
    return getattr(entry, "value", None)


def derive_threat(state: StateManager | None) -> dict[str, Any]:
    """Supported hostile-contact state, in the cockpit's own vocabulary.

    The gate order matches `deriveHostileContact` exactly: an active interdiction
    is hostile contact whether or not the hull has been hit yet; `under_attack`
    is the next positive reading; an explicit `false` is reportable as clear; a
    missing reading is Unknown.
    """
    if state is None:
        return {
            "state": THREAT_UNKNOWN,
            "label": "Hostile contact: Unknown",
            "detail": "Local combat telemetry has not reported threat state.",
            "source_id": TRUTH_UNKNOWN,
            "observed": False,
        }

    combat = state.snapshot.combat
    interdiction = _field(combat, "workflow", "interdiction_active")
    under_attack = _field(combat, "threat", "under_attack")

    if interdiction is True:
        return {
            "state": THREAT_HOSTILE,
            "label": "Hostile interdiction",
            "detail": "Interdiction in progress.",
            "source_id": TRUTH_LOCAL_TELEMETRY,
            "observed": True,
        }
    if under_attack is True:
        return {
            "state": THREAT_HOSTILE,
            "label": "Hostile contact",
            "detail": "Hostile contact engaged.",
            "source_id": TRUTH_LOCAL_TELEMETRY,
            "observed": True,
        }
    if under_attack is False:
        # A supported negative. The verb is "detected" because that is the only
        # claim the evidence carries: `under_attack=false` is written at an
        # observed session boundary and raised again only by HullDamage, so a
        # hostile that has not yet hit the hull is not represented.
        return {
            "state": THREAT_CLEAR,
            "label": "No hostile contact detected",
            "detail": (
                "Local combat telemetry has detected no hostile contact since "
                "the last observed session boundary."
            ),
            "source_id": TRUTH_LOCAL_TELEMETRY,
            "observed": True,
        }
    return {
        "state": THREAT_UNKNOWN,
        "label": "Hostile contact: Unknown",
        "detail": "Local combat telemetry has not reported threat state.",
        "source_id": TRUTH_UNKNOWN,
        "observed": False,
    }


def derive_interdiction(state: StateManager | None) -> dict[str, Any]:
    """Interdiction and escape context, entirely from observed workflow fields."""
    if state is None:
        return {
            "observed": False,
            "active": None,
            "started_at": None,
            "ended_at": None,
            "escape_outcome": None,
            "label": "Interdiction state Unknown",
            "detail": "Local combat telemetry has not reported interdiction state.",
        }

    combat = state.snapshot.combat
    active = _field(combat, "workflow", "interdiction_active")
    started = _field(combat, "workflow", "interdiction_started_at")
    ended = _field(combat, "workflow", "interdiction_ended_at")
    outcome = _field(combat, "workflow", "escape_outcome")

    if active is True:
        label = "Interdiction detected"
        detail = "Status.json reported an interdiction in progress."
    elif outcome == "escaped":
        label = "Interdiction escaped"
        detail = "The journal recorded an escape from the last interdiction."
    elif outcome == "submitted":
        label = "Interdiction submitted"
        detail = "The journal recorded a submission to the last interdiction."
    elif outcome == "unknown" and ended is not None:
        # `record_interdiction_boundary_clear` writes exactly this when a
        # session boundary cleared an interdiction whose end was never observed.
        label = "Interdiction ended, outcome Unknown"
        detail = (
            "An interdiction was cleared at a session boundary without an "
            "observed outcome event."
        )
    elif active is False:
        label = "No interdiction detected"
        detail = "Local combat telemetry reports no interdiction in progress."
    else:
        label = "Interdiction state Unknown"
        detail = "Local combat telemetry has not reported interdiction state."

    return {
        "observed": active is not None or outcome is not None,
        "active": active,
        "started_at": started,
        "ended_at": ended,
        "escape_outcome": outcome,
        "label": label,
        "detail": detail,
    }


def derive_session(state: StateManager | None) -> dict[str, Any]:
    """Combat session context, owned by the Phase 4 StateManager fields.

    No session row is created here and no identity is minted at render time.
    The session's identity is the one the StateManager already holds; where a
    session has never started there is nothing to identify and the answer says
    so rather than inventing a handle.
    """
    if state is None:
        return {
            "observed": False,
            "active": None,
            "mode_hint": None,
            "started_at": None,
            "target_ship": None,
            "hostile_events": None,
            "last_hostile_at": None,
            "conflict_context": None,
            "reason": "Combat telemetry is not available in this session.",
        }

    combat = state.snapshot.combat
    hostile_count = _field(combat, "threat", "recent_hostile_events_count")
    return {
        "observed": True,
        "active": _field(combat, "session", "active"),
        "mode_hint": _field(combat, "session", "mode_hint"),
        # `session_started_at` is written by the mission-session helpers, which
        # is the only session start the local data actually timestamps.
        "started_at": _field(combat, "cz_missions", "session_started_at"),
        "target_ship": _field(combat, "target", "ship_type"),
        "hostile_events": hostile_count if isinstance(hostile_count, int) else None,
        "last_hostile_at": _field(combat, "threat", "last_hostile_timestamp"),
        "conflict_context": _field(combat, "cz_missions", "local_conflict_context"),
        "reason": None,
    }


def derive_missions(state: StateManager | None) -> dict[str, Any]:
    """Concise mission context. Not a mission manager.

    Counts and the few destinations already held in combat state. Reward totals
    and full mission lifecycle aggregation remain deferred — nothing here sums
    `MissionCompleted.Reward`, which PB04-06 explicitly forbids counting as a
    combat reward.
    """
    if state is None:
        return {"observed": False, "active_count": None, "entries": [], "session": None}

    combat = state.snapshot.combat
    entries = list(getattr(combat, "active_missions", []) or [])
    return {
        "observed": True,
        "active_count": len(entries),
        "session": _field(combat, "cz_missions", "mission_session_active"),
        "entries": [
            {
                "mission_id": entry.mission_id,
                "name": entry.name,
                "faction": entry.faction,
                "destination_system": entry.destination_system,
                "destination_station": entry.destination_station,
                "status": entry.status,
            }
            # Bounded on purpose: Operations summarises, the Missions surface
            # would list. Three rows is context; forty rows is a table.
            for entry in entries[:3]
        ],
    }


def derive_rewards(state: StateManager | None) -> dict[str, Any]:
    """Session bounty and combat-bond totals, from RedeemVoucher only.

    These are credits the journal recorded being redeemed. They are not an
    estimate of what a fight was worth and are never combined with anything
    else into a single "earned" number.
    """
    if state is None:
        return {
            "observed": False,
            "bounty_credits": None,
            "bond_credits": None,
            "combat_rank": None,
            "rank_progress": None,
            "summary_at": None,
        }

    combat = state.snapshot.combat
    return {
        "observed": True,
        "bounty_credits": _field(combat, "rewards", "bounty_session_credits"),
        "bond_credits": _field(combat, "rewards", "combat_bond_session_credits"),
        "combat_rank": _field(combat, "rewards", "combat_rank"),
        "rank_progress": _field(combat, "rewards", "combat_rank_progress"),
        "summary_at": _field(combat, "rewards", "session_summary_at"),
        "source": "RedeemVoucher Type=bounty / Type=CombatBond",
    }


# ---------------------------------------------------------------------------
# Readiness, through the one readiness engine
# ---------------------------------------------------------------------------


def _fact(
    fact_id: str,
    label: str,
    value: str,
    fact_state: str,
    detail: str | None,
    read_from: str,
) -> dict[str, Any]:
    return {
        "id": fact_id,
        "label": label,
        "value": value,
        "state": fact_state,
        "detail": detail,
        "read_from": read_from,
    }


def derive_readiness(state: StateManager | None) -> dict[str, Any]:
    """Combat readiness, evaluated by `readiness.py` and translated three-state.

    `readiness.evaluate(operation="combat")` already owns the combat profile
    (hull, shields, fuel, rebuy, modules) and its thresholds. This function does
    not re-decide any of them; it maps `ready`/`attention`/`unknown` onto the
    workflow's three states and adds the loadout evidence from `role_fit`.
    """
    if state is None:
        return {
            "observed": False,
            "facts": [],
            "role": None,
            "reason": "Local telemetry is not available in this session.",
            "unknown_count": 0,
            "problem_count": 0,
            "caveat": AX_ODYSSEY_BOUNDARY,
        }

    evaluation = readiness.evaluate(state, operation="combat")
    facts: list[dict[str, Any]] = []
    for check in evaluation.get("checks") or []:
        status = check.get("status")
        if status == readiness.STATUS_READY:
            fact_state = FACT_GOOD
        elif status == readiness.STATUS_ATTENTION:
            fact_state = FACT_PROBLEM
        else:
            fact_state = FACT_UNKNOWN
        facts.append(
            _fact(
                str(check.get("id")),
                str(check.get("label")),
                str(check.get("value") or UNKNOWN),
                fact_state,
                check.get("note"),
                str(check.get("read_from") or "unknown"),
            )
        )

    fit = readiness.role_fit(state)
    combat_role = next(
        (entry for entry in fit.get("roles") or [] if entry.get("role") == "combat"),
        None,
    )
    role: dict[str, Any] | None = None
    if combat_role is not None:
        loadout_observed = bool(fit.get("loadout_observed"))
        role = {
            "loadout_observed": loadout_observed,
            "modules_observed": fit.get("modules_observed"),
            "fitted": list(combat_role.get("fitted") or []),
            # "not observed" — never "missing". An observed loadout may still be
            # partial, and no combat capability is declared required, so nothing
            # here becomes a blocker.
            "not_observed": list(combat_role.get("not_observed") or []),
            "caveat": fit.get("caveat"),
        }

    return {
        "observed": True,
        "facts": facts,
        "role": role,
        "reason": None,
        "unknown_count": sum(1 for f in facts if f["state"] == FACT_UNKNOWN),
        "problem_count": sum(1 for f in facts if f["state"] == FACT_PROBLEM),
        "caveat": AX_ODYSSEY_BOUNDARY,
    }


def derive_module_damage(state: StateManager | None) -> dict[str, Any]:
    """Modules the journal reported destroyed.

    `health == 0.0` is a factual state the journal reports, not a threshold this
    module invented. Damaged-but-alive modules are deliberately not counted:
    there is no local authority for what counts as "too damaged".
    """
    if state is None:
        return {"observed": False, "destroyed": [], "modules_observed": 0}
    modules = getattr(state.snapshot, "modules", None) or {}
    destroyed = [
        {"slot": slot, "item": getattr(module, "item_localised", None) or slot}
        for slot, module in modules.items()
        if getattr(module, "health", None) == 0.0
    ]
    return {
        "observed": bool(modules),
        "destroyed": sorted(destroyed, key=lambda entry: entry["slot"]),
        "modules_observed": len(modules),
    }


def munitions_boundary() -> dict[str, Any]:
    """The ammunition answer: not a count, not a zero, not a readiness row."""
    return {
        "supported": False,
        "value": None,
        "label": "Munitions: no verified source",
        "source": "no_verified_source",
        "detail": MUNITIONS_BOUNDARY,
    }


def cz_boundary(conflict_context: str | None) -> dict[str, Any]:
    """The combat-zone answer, plus the system conflict fact if one was observed.

    The conflict string is reported as what it is — a system political fact from
    `Conflicts[]` — and explicitly not as CZ presence.
    """
    return {
        "supported": False,
        "active": None,
        "intensity": None,
        "conflict_context": conflict_context,
        "label": "Combat zone state: not supported locally",
        "detail": CZ_BOUNDARY,
    }


# ---------------------------------------------------------------------------
# Journal history and PvP
# ---------------------------------------------------------------------------


async def _current_session_id(db: AsyncSession) -> int | None:
    row = (
        await db.execute(select(func.max(JournalEvent.session_id)))
    ).scalar_one_or_none()
    return int(row) if row is not None else None


async def session_combat_history(
    session_factory: async_sessionmaker[AsyncSession] | None,
) -> dict[str, Any]:
    """Combat events the recorder logged during the current recorded session.

    Scoped by `journal_events.session_id` so a fight from last month never
    presents as this session's engagement. An unavailable recorder is Unknown,
    never zero.
    """
    empty: dict[str, Any] = {
        "observed": False,
        "session_id": None,
        "hull_damage_events": None,
        "interdiction_events": None,
        "deaths": None,
        "resurrections": None,
        "reason": "The local recorder is not available in this session.",
    }
    if session_factory is None:
        return empty
    try:
        async with session_factory() as db:
            session_id = await _current_session_id(db)
            if session_id is None:
                return {**empty, "reason": "No recorded session was found."}
            counts: dict[str, int] = {}
            rows = (
                await db.execute(
                    select(
                        JournalEvent.event_type,
                        func.count(JournalEvent.id).label("total"),
                    )
                    .where(
                        JournalEvent.session_id == session_id,
                        JournalEvent.event_type.in_(
                            HULL_DAMAGE_EVENTS
                            + INTERDICTION_EVENTS
                            + DEATH_EVENTS
                            + RESURRECT_EVENTS
                        ),
                    )
                    .group_by(JournalEvent.event_type)
                )
            ).all()
            for event_type, event_total in rows:
                counts[str(event_type)] = int(event_total)
    except Exception:  # noqa: BLE001 - an unreadable recorder is Unknown, not zero
        return {**empty, "reason": "The local recorder did not answer."}

    def tally(events: tuple[str, ...]) -> int:
        return sum(counts.get(name, 0) for name in events)

    return {
        "observed": True,
        "session_id": session_id,
        "hull_damage_events": tally(HULL_DAMAGE_EVENTS),
        "interdiction_events": tally(INTERDICTION_EVENTS),
        "deaths": tally(DEATH_EVENTS),
        "resurrections": tally(RESURRECT_EVENTS),
        "reason": None,
    }


async def pvp_records(
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    limit: int = 3,
) -> dict[str, Any]:
    """Local PvP encounters, newest first, bounded to a workflow summary.

    Reads the durable Phase 4 store. Records keep the identity that store
    assigned them; none is minted here. Wording stays factual — the encounter
    type is what the journal observed, and no player is characterised.
    """
    empty: dict[str, Any] = {
        "observed": False,
        "total": None,
        "entries": [],
        "reason": "The local recorder is not available in this session.",
        "caveat": PVP_CAVEAT,
    }
    if session_factory is None:
        return empty
    try:
        async with session_factory() as db:
            total = (
                await db.execute(select(func.count(PvpEncounter.id)))
            ).scalar_one_or_none()
            rows = (
                (
                    await db.execute(
                        select(PvpEncounter)
                        .order_by(PvpEncounter.timestamp.desc())
                        .limit(max(0, limit))
                    )
                )
                .scalars()
                .all()
            )
    except Exception:  # noqa: BLE001
        return {**empty, "reason": "The local recorder did not answer."}

    return {
        "observed": True,
        "total": int(total or 0),
        "entries": [
            {
                "id": row.id,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "commander_name": row.commander_name,
                "system": row.system,
                "encounter_type": row.encounter_type,
                "source_label": row.source_label,
                "provenance_event_type": row.provenance_event_type,
            }
            for row in rows
        ],
        "reason": None,
        "caveat": PVP_CAVEAT,
    }


# ---------------------------------------------------------------------------
# Stage
# ---------------------------------------------------------------------------


def _encounter_observed(
    session: dict[str, Any],
    interdiction: dict[str, Any],
    rewards: dict[str, Any],
    history: dict[str, Any],
) -> bool:
    """Whether THIS session recorded a combat encounter.

    Deliberately excludes the PvP store: those records are durable history, and
    an encounter from last month must not make the cockpit say the Commander has
    just been in a fight.
    """
    if isinstance(session.get("hostile_events"), int) and session["hostile_events"] > 0:
        return True
    if interdiction.get("ended_at") is not None:
        return True
    if interdiction.get("escape_outcome") is not None:
        return True
    for key in ("bounty_credits", "bond_credits"):
        value = rewards.get(key)
        if isinstance(value, int) and value > 0:
            return True
    if history.get("observed"):
        for key in ("hull_damage_events", "interdiction_events", "deaths"):
            value = history.get(key)
            if isinstance(value, int) and value > 0:
                return True
    return False


def _safety_problem(
    readiness_facts: dict[str, Any], damage: dict[str, Any]
) -> list[str]:
    """Confirmed safety problems only. Unknown is not a problem."""
    problems = [
        fact["label"]
        for fact in readiness_facts.get("facts") or []
        if fact["state"] == FACT_PROBLEM and fact["id"] in ("hull", "shields")
    ]
    if damage.get("destroyed"):
        problems.append("Modules")
    return problems


def derive_stage(
    *,
    threat: dict[str, Any],
    interdiction: dict[str, Any],
    session: dict[str, Any],
    missions: dict[str, Any],
    rewards: dict[str, Any],
    history: dict[str, Any],
    readiness_facts: dict[str, Any],
    damage: dict[str, Any],
    objective: dict[str, Any] | None,
) -> tuple[str, str]:
    """The one place a combat stage is decided. Ordered gates, first gate wins.

    Ordering is by urgency, not by narrative order. A live interdiction outranks
    everything; a damaged ship outranks reviewing the fight that damaged it; and
    reviewing a fight outranks preparing for the next one, because a Commander
    who has just landed from an engagement is not "preparing".
    """
    if not session.get("observed"):
        return (
            STAGE_UNKNOWN,
            "Combat telemetry is not available, so no combat situation is claimed.",
        )

    if interdiction.get("active") is True:
        return (
            STAGE_INTERDICTED,
            "Status.json reports an interdiction in progress.",
        )

    if threat.get("state") == THREAT_HOSTILE:
        return (STAGE_ENGAGED, "Local telemetry reports hostile contact.")

    encounter = _encounter_observed(session, interdiction, rewards, history)
    problems = _safety_problem(readiness_facts, damage)

    if encounter and problems:
        return (
            STAGE_RECOVERY,
            f"This session recorded combat and {_join(problems).lower()} "
            "needs attention.",
        )

    if encounter and session.get("active") is True:
        return (
            STAGE_POST_ENGAGEMENT,
            "This session recorded combat and the combat session is still active.",
        )

    if encounter:
        return (
            STAGE_REVIEW_READY,
            "This session recorded combat and an observed session boundary has "
            "since closed it.",
        )

    # No encounter this session. Preparation requires declared intent — a
    # Commander Objective for Combat, or missions the journal actually recorded.
    # Opening Combat mode is not intent and never reaches this gate.
    if objective is not None:
        return (
            STAGE_PREPARATION,
            "A Commander Objective is set for Combat and no engagement has been "
            "recorded this session.",
        )
    active_count = missions.get("active_count")
    if isinstance(active_count, int) and active_count > 0:
        return (
            STAGE_PREPARATION,
            f"{active_count} active mission(s) recorded and no engagement this "
            "session.",
        )

    if threat.get("state") == THREAT_UNKNOWN:
        return (
            STAGE_UNKNOWN,
            "Local combat telemetry has not reported threat state, so no combat "
            "situation is claimed.",
        )
    return (
        STAGE_IDLE,
        "No engagement recorded this session and no hostile contact detected.",
    )


def _join(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return ", ".join(values[:-1]) + " and " + values[-1]


# ---------------------------------------------------------------------------
# Step, work remaining, blockers, completion
# ---------------------------------------------------------------------------


def derive_step(
    stage: str,
    *,
    threat: dict[str, Any],
    interdiction: dict[str, Any],
    readiness_facts: dict[str, Any],
    damage: dict[str, Any],
    pvp: dict[str, Any],
) -> dict[str, Any] | None:
    """The single current workflow step. Never a Commander Objective.

    Every step carries `owner: derived` so no surface can mistake it for
    something the Commander authored.
    """
    problems = _safety_problem(readiness_facts, damage)

    if stage == STAGE_UNKNOWN:
        return None

    if stage == STAGE_INTERDICTED:
        return _step(
            "review-escape",
            "Review escape context and ship safety",
            "escape",
            TRUTH_LOCAL_TELEMETRY,
        )
    if stage == STAGE_ENGAGED:
        return _step(
            "review-safety",
            "Review ship safety while hostile contact is detected",
            "safety",
            TRUTH_LOCAL_TELEMETRY,
        )
    if stage == STAGE_RECOVERY:
        return _step(
            "recover",
            f"Recover ship safety — {_join(problems).lower()}"
            if problems
            else "Recover ship safety",
            "safety",
            TRUTH_LOCAL_TELEMETRY,
        )
    if stage in (STAGE_POST_ENGAGEMENT, STAGE_REVIEW_READY):
        if pvp.get("observed") and (pvp.get("total") or 0) > 0:
            return _step(
                "review-encounter",
                "Review this session's combat record",
                "review",
                TRUTH_LOCAL_EVENT_HISTORY,
            )
        return _step(
            "review-session",
            "Review this session's combat record",
            "review",
            TRUTH_LOCAL_EVENT_HISTORY,
        )
    if stage in (STAGE_PREPARATION, STAGE_IDLE):
        unknowns = [
            fact["label"]
            for fact in readiness_facts.get("facts") or []
            if fact["state"] == FACT_UNKNOWN
        ]
        # A confirmed safety problem is a real step in either stage. Visual
        # acceptance caught the gap: an idle ship with shields confirmed down
        # rendered "Work remaining: Shields Down" beside "no combat step
        # derived", which reads as the card disagreeing with itself.
        if problems:
            return _step(
                "fix-readiness",
                f"Resolve {_join(problems).lower()} before engaging",
                "safety",
                TRUTH_LOCAL_TELEMETRY,
            )
        if stage == STAGE_IDLE:
            # Nothing is happening and nothing is confirmed wrong. There is no
            # combat step, and naming one would imply a workflow that is not
            # running. Unknown readiness is not chased here either: a Commander
            # who has declared no combat intent is not asked to prepare for one.
            return None
        if unknowns:
            return _step(
                "confirm-readiness",
                f"Confirm {_join(unknowns).lower()} — not reported locally",
                "readiness",
                TRUTH_UNKNOWN,
            )
        return _step(
            "ready",
            "Ship readiness confirmed from local facts",
            "readiness",
            TRUTH_LOCAL_TELEMETRY,
        )
    return None


def _step(kind: str, label: str, target_kind: str, source_id: str) -> dict[str, Any]:
    return {
        "objective_id": _identity(kind),
        "kind": kind,
        "label": label,
        "state": "active",
        "target_kind": target_kind,
        "owner": "derived",
        "source_id": source_id,
    }


def derive_work_remaining(
    stage: str,
    *,
    readiness_facts: dict[str, Any],
    damage: dict[str, Any],
    missions: dict[str, Any],
    pvp: dict[str, Any],
    history: dict[str, Any],
) -> list[dict[str, Any]]:
    """Work the local evidence can actually name, plus what it cannot know.

    `kind: unknown` rows are coverage statements, not tasks. They exist so the
    Commander can tell "nothing to do" apart from "nothing observed".
    """
    work: list[dict[str, Any]] = []

    for fact in readiness_facts.get("facts") or []:
        if fact["state"] == FACT_PROBLEM:
            work.append(
                {
                    "id": f"combat.readiness.{fact['id']}",
                    "label": f"{fact['label']}: {fact['value']}",
                    "detail": fact["detail"] or "",
                    "kind": "work",
                }
            )

    for module in damage.get("destroyed") or []:
        work.append(
            {
                "id": f"combat.module.{module['slot']}",
                "label": f"{module['item']} destroyed",
                "detail": "The journal reported this module at zero health.",
                "kind": "work",
            }
        )

    if stage in (STAGE_POST_ENGAGEMENT, STAGE_REVIEW_READY):
        if pvp.get("observed") and (pvp.get("total") or 0) > 0:
            work.append(
                {
                    "id": "combat.review.pvp",
                    "label": f"{pvp['total']} local PvP record(s) to review",
                    "detail": PVP_CAVEAT,
                    "kind": "work",
                }
            )
        deaths = history.get("deaths")
        if isinstance(deaths, int) and deaths > 0:
            work.append(
                {
                    "id": "combat.review.rebuy",
                    "label": f"{deaths} ship loss recorded this session",
                    "detail": (
                        "The journal recorded a Died event during this recorded "
                        "session."
                    ),
                    "kind": "work",
                }
            )

    unknown_facts = [
        fact["label"]
        for fact in readiness_facts.get("facts") or []
        if fact["state"] == FACT_UNKNOWN
    ]
    if unknown_facts:
        work.append(
            {
                "id": "combat.readiness.unknown",
                "label": f"{len(unknown_facts)} readiness fact(s) Unknown",
                "detail": (
                    f"{_join(unknown_facts)} not reported by local telemetry. "
                    "That is not a claim the ship has a problem."
                ),
                "kind": "unknown",
            }
        )

    role = readiness_facts.get("role")
    if role is not None and not role.get("loadout_observed"):
        work.append(
            {
                "id": "combat.loadout.unknown",
                "label": "Combat loadout Unknown",
                "detail": (
                    "No loadout has been observed, so fitted weapons and shield "
                    "generator cannot be judged. That is not a claim the ship "
                    "lacks them."
                ),
                "kind": "unknown",
            }
        )

    work.append(
        {
            "id": "combat.munitions.unsupported",
            "label": "Munitions not known",
            "detail": MUNITIONS_BOUNDARY,
            "kind": "unknown",
        }
    )
    work.append(
        {
            "id": "combat.zone.unsupported",
            "label": "Combat zone state not known",
            "detail": CZ_BOUNDARY,
            "kind": "unknown",
        }
    )

    if missions.get("observed") and not missions.get("active_count"):
        # Not a blocker and not a task: simply the absence of mission context.
        work.append(
            {
                "id": "combat.missions.none",
                "label": "No active missions recorded",
                "detail": (
                    "The journal has not recorded an active mission this session."
                ),
                "kind": "unknown",
            }
        )

    return work


def derive_blockers(
    stage: str,
    *,
    readiness_facts: dict[str, Any],
    damage: dict[str, Any],
    route_active: bool,
) -> list[dict[str, Any]]:
    """Conditions preventing the CURRENT combat workflow. Nothing else.

    Three things are deliberately not blockers here: Unknown readiness (absence
    of evidence), an unsupported munitions or CZ fact (a source boundary), and a
    hostile contact (that is a threat, and the workflow it belongs to is exactly
    the one running).
    """
    blockers: list[dict[str, Any]] = []

    hull = next(
        (f for f in readiness_facts.get("facts") or [] if f["id"] == "hull"), None
    )
    if hull is not None and hull["state"] == FACT_PROBLEM:
        # Relevant in EVERY stage, including Unknown. A hull below the existing
        # critical threshold is a confirmed safety fact read straight from
        # telemetry; it does not stop being one because combat telemetry has not
        # reported a threat. Suppressing it while the stage is Unknown would
        # hide a known danger behind an unrelated unknown.
        blockers.append(
            {
                "blocker_id": "combat.blocker.hull",
                "label": f"Hull {hull['value']}",
                "detail": hull["detail"] or "Hull below the critical threshold.",
                "kind": "safety",
                "source_id": TRUTH_LOCAL_TELEMETRY,
                "condition_id": CONDITION_HULL,
            }
        )

    # Equipment, unlike hull, is stage-scoped: a destroyed module impedes
    # specific combat workflows, and with the stage Unknown there is no workflow
    # to declare impeded.
    destroyed = damage.get("destroyed") or []
    if destroyed and stage in (
        STAGE_INTERDICTED,
        STAGE_ENGAGED,
        STAGE_RECOVERY,
        STAGE_PREPARATION,
    ):
        blockers.append(
            {
                "blocker_id": "combat.blocker.modules",
                "label": f"{len(destroyed)} module(s) destroyed",
                "detail": "The journal reported these modules at zero health.",
                "kind": "equipment",
                "source_id": TRUTH_LOCAL_TELEMETRY,
                "condition_id": CONDITION_MODULES,
            }
        )

    if stage == STAGE_INTERDICTED and not route_active:
        # Only while escape is the current step. Outside it, "no route plotted"
        # is an ordinary state, not an impediment.
        blockers.append(
            {
                "blocker_id": "combat.blocker.escape-route",
                "label": "No route plotted",
                "detail": (
                    "Escape movement is Navigation's to plan and no route is "
                    "currently active."
                ),
                "kind": "route",
                "source_id": TRUTH_LOCAL_TELEMETRY,
                "condition_id": CONDITION_ESCAPE_ROUTE,
            }
        )

    return blockers


def derive_attention(
    *,
    threat: dict[str, Any],
    interdiction: dict[str, Any],
    history: dict[str, Any],
) -> list[dict[str, Any]]:
    """Notable current conditions. Distinct from blockers and from readiness.

    A hostile contact is an attention, not a blocker: it does not prevent the
    combat workflow, it *is* the combat workflow.
    """
    notes: list[dict[str, Any]] = []
    if threat.get("state") == THREAT_HOSTILE:
        notes.append(
            {
                "id": "combat.attention.threat",
                "label": threat["label"],
                "detail": threat["detail"],
                "kind": "threat",
            }
        )
    if interdiction.get("active") is True:
        notes.append(
            {
                "id": "combat.attention.interdiction",
                "label": interdiction["label"],
                "detail": interdiction["detail"],
                "kind": "threat",
            }
        )
    deaths = history.get("deaths")
    if isinstance(deaths, int) and deaths > 0:
        notes.append(
            {
                "id": "combat.attention.rebuy",
                "label": f"{deaths} ship loss recorded this session",
                "detail": "The journal recorded a Died event this recorded session.",
                "kind": "outcome",
            }
        )
    return notes


def derive_completion(
    stage: str,
    *,
    blockers: list[dict[str, Any]],
    work_remaining: list[dict[str, Any]],
) -> dict[str, Any]:
    """When the locally-supported combat workflow appears finished.

    Only `idle` and `review_ready` can report no known work, and only with no
    blockers and no `work` rows. Unknown coverage never blocks completion — it
    is stated as coverage, not counted as a task.
    """
    real_work = [entry for entry in work_remaining if entry["kind"] == "work"]

    # Blockers are judged FIRST, before the Unknown stage. A confirmed blocker is
    # a definite fact, and reporting "completion cannot be judged" in the same
    # frame as a critical hull would be the cockpit contradicting itself.
    if blockers:
        return {
            "state": "blocked",
            "label": "Blocked",
            "reason": blockers[0]["label"] + ".",
        }
    if stage == STAGE_UNKNOWN:
        # Deliberately neutral about *why*: the stage reaches Unknown both when
        # no telemetry exists at all and when telemetry exists but has not
        # reported. The stage detail says which; this row must not contradict it.
        return {
            "state": "unknown",
            "label": "Unknown",
            "reason": ("Combat state is Unknown, so completion cannot be judged."),
        }
    if real_work:
        return {
            "state": "work_remaining",
            "label": "Work remaining",
            "reason": real_work[0]["label"] + ".",
        }
    if stage == STAGE_REVIEW_READY:
        return {
            "state": "no_known_work_remaining",
            "label": "Ready for review",
            "reason": (
                "This session's combat record is complete and no ship safety "
                "problem is reported."
            ),
        }
    if stage == STAGE_IDLE:
        return {
            "state": "no_known_work_remaining",
            "label": "No known work remaining",
            "reason": (
                "No engagement recorded this session and no ship safety problem "
                "is reported."
            ),
        }
    return {
        "state": "work_remaining",
        "label": "Workflow active",
        "reason": STAGE_LABELS.get(stage, UNKNOWN) + " in progress.",
    }


# ---------------------------------------------------------------------------
# Handoffs and debrief inputs
# ---------------------------------------------------------------------------


def derive_handoffs(stage: str, session: dict[str, Any]) -> list[dict[str, Any]]:
    """Where to go for deeper factual context. Operations never absorbs them.

    Navigation owns movement. Intel owns system facts. The Activity Log owns
    proof. Nothing here plans a route or re-states a fact those routes own.
    """
    handoffs: list[dict[str, Any]] = [
        {
            "id": "activity_log",
            "label": "Open Activity Log",
            "route": "/activity-log",
            "section_id": None,
            "entity_id": None,
            "query": None,
            "reason": "Activity Log owns the proof record.",
        }
    ]
    if stage in (STAGE_INTERDICTED, STAGE_ENGAGED, STAGE_RECOVERY):
        handoffs.insert(
            0,
            {
                "id": "navigation_route",
                "label": "Plot a route",
                "route": "/navigation",
                "section_id": "navigation-current-route",
                "entity_id": None,
                "query": None,
                "reason": "Navigation owns route planning.",
            },
        )
    conflict = session.get("conflict_context")
    if conflict:
        handoffs.insert(
            0,
            {
                "id": "intel_system",
                "label": "Review system in Intel",
                "route": "/intel",
                "section_id": "intel-domain-search",
                "entity_id": "system",
                "query": None,
                "reason": "Intel owns system facts.",
            },
        )
    return handoffs


def derive_debrief_facts(
    *,
    session: dict[str, Any],
    rewards: dict[str, Any],
    missions: dict[str, Any],
    history: dict[str, Any],
    pvp: dict[str, Any],
    readiness_facts: dict[str, Any],
) -> dict[str, Any]:
    """The factual summary a debrief will need. R9 owns the loop; this is input.

    No narrative, no AI-written summary, no completion transition. Earnings are
    only what `RedeemVoucher` recorded — nothing is estimated and nothing is
    combined into a single "earned" number.
    """
    return {
        "session_started_at": session.get("started_at"),
        "session_active": session.get("active"),
        "hostile_events": session.get("hostile_events"),
        "last_hostile_at": session.get("last_hostile_at"),
        "interdiction_events": history.get("interdiction_events"),
        "hull_damage_events": history.get("hull_damage_events"),
        "ship_losses": history.get("deaths"),
        "bounty_credits": rewards.get("bounty_credits"),
        "bond_credits": rewards.get("bond_credits"),
        "earnings_source": rewards.get("source"),
        "combat_rank": rewards.get("combat_rank"),
        "active_missions": missions.get("active_count"),
        "pvp_records": pvp.get("total"),
        "readiness_problems": readiness_facts.get("problem_count"),
        "readiness_unknown": readiness_facts.get("unknown_count"),
        "caveat": (
            "Session facts only. Credits are what RedeemVoucher recorded being "
            "redeemed, not an estimate of what an engagement was worth. Mission "
            "reward totals are not aggregated."
        ),
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def unavailable_workflow(reason: str) -> dict[str, Any]:
    """The honest answer when combat state cannot be read at all."""
    return {
        "available": False,
        "reason": reason,
        "stage": STAGE_UNKNOWN,
        "stage_label": STAGE_LABELS[STAGE_UNKNOWN],
        "stage_detail": reason,
        "step": None,
        "threat": derive_threat(None),
        "interdiction": derive_interdiction(None),
        "session": derive_session(None),
        "readiness": derive_readiness(None),
        "module_damage": derive_module_damage(None),
        "missions": derive_missions(None),
        "rewards": derive_rewards(None),
        "munitions": munitions_boundary(),
        "combat_zone": cz_boundary(None),
        "pvp": {
            "observed": False,
            "total": None,
            "entries": [],
            "reason": reason,
            "caveat": PVP_CAVEAT,
        },
        "history": {"observed": False, "reason": reason},
        "attention": [],
        "work_remaining": [],
        "blockers": [],
        "completion": {
            "state": "unknown",
            "label": "Unknown",
            "reason": reason,
        },
        "handoffs": [],
        "debrief_facts": None,
        "caveat": BASE_CAVEAT,
        "ax_odyssey": AX_ODYSSEY_BOUNDARY,
    }


async def build_workflow(
    state: StateManager | None,
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    objective: dict[str, Any] | None = None,
    route_active: bool = False,
) -> dict[str, Any]:
    """Assemble the Operations Combat workflow from local facts only.

    Deterministic: the same state and the same recorded events produce the same
    payload, including every derived id. Nothing is persisted and no id is
    minted at read time.
    """
    if state is None:
        return unavailable_workflow(
            "Combat telemetry is not available in this session."
        )

    threat = derive_threat(state)
    interdiction = derive_interdiction(state)
    session = derive_session(state)
    missions = derive_missions(state)
    rewards = derive_rewards(state)
    readiness_facts = derive_readiness(state)
    damage = derive_module_damage(state)
    history = await session_combat_history(session_factory)
    pvp = await pvp_records(session_factory)

    stage, stage_detail = derive_stage(
        threat=threat,
        interdiction=interdiction,
        session=session,
        missions=missions,
        rewards=rewards,
        history=history,
        readiness_facts=readiness_facts,
        damage=damage,
        objective=objective,
    )

    work_remaining = derive_work_remaining(
        stage,
        readiness_facts=readiness_facts,
        damage=damage,
        missions=missions,
        pvp=pvp,
        history=history,
    )
    blockers = derive_blockers(
        stage,
        readiness_facts=readiness_facts,
        damage=damage,
        route_active=route_active,
    )

    return {
        "available": True,
        "reason": None,
        "stage": stage,
        "stage_label": STAGE_LABELS[stage],
        "stage_detail": stage_detail,
        "step": derive_step(
            stage,
            threat=threat,
            interdiction=interdiction,
            readiness_facts=readiness_facts,
            damage=damage,
            pvp=pvp,
        ),
        "threat": threat,
        "interdiction": interdiction,
        "session": session,
        "readiness": readiness_facts,
        "module_damage": damage,
        "missions": missions,
        "rewards": rewards,
        "munitions": munitions_boundary(),
        "combat_zone": cz_boundary(session.get("conflict_context")),
        "pvp": pvp,
        "history": history,
        "attention": derive_attention(
            threat=threat, interdiction=interdiction, history=history
        ),
        "work_remaining": work_remaining,
        "blockers": blockers,
        "completion": derive_completion(
            stage, blockers=blockers, work_remaining=work_remaining
        ),
        "handoffs": derive_handoffs(stage, session),
        "debrief_facts": derive_debrief_facts(
            session=session,
            rewards=rewards,
            missions=missions,
            history=history,
            pvp=pvp,
            readiness_facts=readiness_facts,
        ),
        "caveat": BASE_CAVEAT,
        "ax_odyssey": AX_ODYSSEY_BOUNDARY,
    }
