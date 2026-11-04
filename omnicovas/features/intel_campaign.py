"""Intel campaign fact surface — Phase 13 (PB13-03, LNA-039).

Read-only. Intel presents campaign facts and their source age; Operations
owns campaign execution and Navigation owns circuits, so nothing here
creates, advances, or completes an objective.

The honesty problem this module exists to solve
-----------------------------------------------
A campaign objective is Commander-entered text. Recorded journal activity
is observed fact. Joining them is neither: the journal records that an
event happened in a system, or named a faction or power, at a time. It
never records that the event advanced an objective — the game does not
report influence outcomes to the journal at all.

So this module reports **recorded activity matching a campaign's declared
target**, and says exactly that. The match basis is named in the payload
(which target, which journal fields were compared), the window is stated,
and the two bases are counted separately rather than summed, because one
event can satisfy both and a combined total would silently double-count.

A campaign with no target system and no target subject reports
``available: false`` with a reason. It does not report zero — zero reads
as "you did nothing", when the truth is "there is nothing to match on".

Every event name below is Frontier-native, already recorded by the
EventRecorder and already handled in omnicovas.core.handlers. No event
name is invented here; names are matched verbatim against recorded rows.

See: PB13-03 Intel BGS, Powerplay, and Campaign Maturation
See: omnicovas/features/intel_history.py (query idiom, caveat posture)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from omnicovas.db.models import CampaignObjectiveRef, JournalEvent

TRUTH_LOCAL_EVENT_HISTORY = "local_event_history"
TRUTH_COMMANDER_ENTERED = "commander_entered"
SOURCE_CAMPAIGN_STORE = "Local campaign objectives (Commander-entered)"

CAMPAIGN_DEFAULT_LIMIT = 25
CAMPAIGN_MAX_LIMIT = 100

# Recorded event types that can bear on a BGS campaign target. Presence in
# this tuple means "could be relevant activity", never "affects influence".
BGS_EVIDENCE_EVENTS: tuple[str, ...] = (
    "MissionCompleted",
    "MissionFailed",
    "Bounty",
    "FactionKillBond",
    "RedeemVoucher",
    "MarketBuy",
    "MarketSell",
    "SellExplorationData",
    "MultiSellExplorationData",
)

POWERPLAY_EVIDENCE_EVENTS: tuple[str, ...] = (
    "PowerplayCollect",
    "PowerplayDeliver",
    "PowerplayMerits",
    "PowerplayVoucher",
    "PowerplaySalary",
    "PowerplayJoin",
    "PowerplayLeave",
    "PowerplayDefect",
    "PowerplayVote",
    "PowerplayFastTrack",
)

# Journal fields compared against a campaign's target_subject. Declared
# rather than guessed, and echoed into the payload so a count can be traced
# to the fields that produced it.
BGS_SUBJECT_FIELDS: tuple[str, ...] = ("Faction", "AwardingFaction", "VictimFaction")
POWERPLAY_SUBJECT_FIELDS: tuple[str, ...] = ("Power",)

_CAMPAIGN_CAVEAT = (
    "Commander-entered campaign objectives shown with recorded activity that "
    "matches their declared target. A match is a name correspondence inside "
    "the stated window — never proof the activity advanced the objective. The "
    "journal does not record influence or merit outcomes, so no progress is "
    "claimed here. Activity recorded before the objective was entered is "
    "counted separately and never merged into it. Operations owns campaign "
    "execution; Navigation owns circuits; Activity Log owns proof."
)
_NO_TARGET_REASON = (
    "This objective declares no target system and no target subject, so there "
    "is nothing to match recorded activity against."
)


def _clamp_limit(limit: int | None, default: int, maximum: int) -> int:
    if limit is None:
        return default
    return max(1, min(int(limit), maximum))


def _iso_or_none(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _age_seconds(value: datetime | None, *, now: datetime) -> int | None:
    if value is None:
        return None
    return max(0, int((now - _as_utc(value)).total_seconds()))


def _evidence_events(workflow_type: str) -> tuple[str, ...]:
    return (
        POWERPLAY_EVIDENCE_EVENTS
        if workflow_type == "powerplay"
        else BGS_EVIDENCE_EVENTS
    )


def _subject_fields(workflow_type: str) -> tuple[str, ...]:
    return (
        POWERPLAY_SUBJECT_FIELDS if workflow_type == "powerplay" else BGS_SUBJECT_FIELDS
    )


async def _activity_for(
    db: AsyncSession,
    *,
    event_types: tuple[str, ...],
    window_start: datetime,
    condition: Any,
) -> dict[str, Any]:
    """Count recorded activity by event type under one match condition.

    Two counts, deliberately kept apart. ``events_recorded`` covers the
    window since the objective was entered — the only activity that could
    have been done for it. ``events_before_window`` covers everything
    matching the same target beforehand.

    Reporting only the first would make the surface useless in the ordinary
    case, where a Commander enters an objective describing work already
    underway and then sees zero. Merging them would be worse: it would
    credit an objective with activity that predates it. Both counts, kept
    separate and separately labelled, is the only honest way to be useful.
    """
    rows = (
        await db.execute(
            select(
                JournalEvent.event_type,
                func.count().label("recorded"),
                func.max(JournalEvent.timestamp).label("last_seen"),
            )
            .where(
                JournalEvent.event_type.in_(event_types),
                JournalEvent.timestamp >= window_start,
                condition,
            )
            .group_by(JournalEvent.event_type)
            .order_by(func.count().desc())
        )
    ).all()

    before = (
        await db.execute(
            select(func.count()).where(
                JournalEvent.event_type.in_(event_types),
                JournalEvent.timestamp < window_start,
                condition,
            )
        )
    ).scalar_one()

    by_event_type = [
        {
            "event_type": row.event_type,
            "recorded": int(row.recorded),
            "last_seen": _iso_or_none(row.last_seen),
        }
        for row in rows
    ]
    last_seen = max(
        (row["last_seen"] for row in by_event_type if row["last_seen"]),
        default=None,
    )
    return {
        "events_recorded": sum(row["recorded"] for row in by_event_type),
        "events_before_window": int(before or 0),
        "last_seen": last_seen,
        "by_event_type": by_event_type,
    }


async def campaign_facts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workflow_type: str | None = None,
    include_archived: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Campaign objectives as Intel facts, with source age and local evidence.

    Read-only over the Operations campaign store and the flight recorder.
    No writes, no Activity Log entries, no state transitions — an Intel read
    of a campaign must never look like campaign progress.
    """
    bounded_limit = _clamp_limit(limit, CAMPAIGN_DEFAULT_LIMIT, CAMPAIGN_MAX_LIMIT)
    now = datetime.now(timezone.utc)
    system_name = func.json_extract(JournalEvent.raw_json, "$.StarSystem")

    campaigns: list[dict[str, Any]] = []
    async with session_factory() as db:
        query = select(CampaignObjectiveRef).order_by(
            CampaignObjectiveRef.updated_at.desc()
        )
        if workflow_type is not None:
            query = query.where(CampaignObjectiveRef.workflow_type == workflow_type)
        if not include_archived:
            query = query.where(CampaignObjectiveRef.archived_at.is_(None))
        rows = (await db.execute(query.limit(bounded_limit))).scalars().all()

        for row in rows:
            event_types = _evidence_events(row.workflow_type)
            subject_fields = _subject_fields(row.workflow_type)
            # Compared against JournalEvent.timestamp, which is stored in the
            # same naive form by the recorder. Normalising this one side to
            # tz-aware would compare across two storage domains.
            window_start = row.created_at

            system_activity: dict[str, Any] | None = None
            if row.target_system:
                system_activity = {
                    "target": row.target_system,
                    "matched_field": "StarSystem",
                    **await _activity_for(
                        db,
                        event_types=event_types,
                        window_start=window_start,
                        condition=system_name == row.target_system,
                    ),
                }

            subject_activity: dict[str, Any] | None = None
            if row.target_subject:
                subject_activity = {
                    "target": row.target_subject,
                    "matched_fields": list(subject_fields),
                    **await _activity_for(
                        db,
                        event_types=event_types,
                        window_start=window_start,
                        condition=or_(
                            *[
                                func.json_extract(JournalEvent.raw_json, f"$.{field}")
                                == row.target_subject
                                for field in subject_fields
                            ]
                        ),
                    ),
                }

            has_target = system_activity is not None or subject_activity is not None
            campaigns.append(
                {
                    "campaign_id": row.campaign_id,
                    "workflow_type": row.workflow_type,
                    "title": row.title,
                    "state": row.state,
                    "target_subject": row.target_subject,
                    "target_system": row.target_system,
                    "created_at": _iso_or_none(row.created_at),
                    "updated_at": _iso_or_none(row.updated_at),
                    "archived_at": _iso_or_none(row.archived_at),
                    # PB13-03: Intel presents campaign facts *and source age*.
                    # Age is reported, not classified: when a Commander's own
                    # objective goes stale is the Commander's judgement, and
                    # inventing a threshold would put words in their mouth.
                    "record_age_seconds": _age_seconds(row.updated_at, now=now),
                    "freshness": TRUTH_COMMANDER_ENTERED,
                    "truth_class": TRUTH_COMMANDER_ENTERED,
                    # Activity Log owns proof; Intel only carries the link.
                    "proof_event_id": row.last_activity_log_event_id,
                    "evidence": {
                        "window_start": _iso_or_none(row.created_at),
                        "events_considered": list(event_types),
                        "system_activity": system_activity,
                        "subject_activity": subject_activity,
                        "available": has_target,
                        "unavailable_reason": None if has_target else _NO_TARGET_REASON,
                        "truth_class": TRUTH_LOCAL_EVENT_HISTORY,
                    },
                }
            )

    return {
        "generated_at": now.isoformat(),
        "source": SOURCE_CAMPAIGN_STORE,
        "truth_class": TRUTH_COMMANDER_ENTERED,
        "caveat": _CAMPAIGN_CAVEAT,
        "returned": len(campaigns),
        "limit": bounded_limit,
        "include_archived": include_archived,
        "campaigns": campaigns,
        # Stated in the payload so a consumer cannot mistake this for the
        # execution surface. Intel reads; Operations acts.
        "execution_owner": "operations",
        "proof_owner": "activity_log",
        "nullprovider_safe": True,
    }
