"""Deterministic power-group simulation over the canonical resolved ship rows.

No telemetry writes, module catalogue, engineering formulas or game actions.
Source resolution belongs to ship_performance; this module owns priority cuts.
"""

from __future__ import annotations

import copy
import itertools
import math
from collections.abc import Iterable
from typing import Any

JsonDict = dict[str, Any]
VERSION = "ship-power-v1"
SOURCES: list[JsonDict] = [
    {
        "name": "Frontier Player Guide, printed page 38: complete priority groups",
        "url": (
            "https://hosting.zaonce.net/elite/website/assets/English-Play"
            "ersGuide_v2.00-Horizons.pdf"
        ),
    },
    {
        "name": "Frontier Journal Loadout/ModuleInfo; priorities are zero-based",
        "url": "https://hosting.zaonce.net/community/journal/v26/Journal-Manual-v26.pdf",
    },
    {
        "name": "EDSY ea787cf8: deployment, power locks and independent power totals",
        "url": (
            "https://github.com/taleden/EDSY/tree/ea787cf805f2c38f72c8d5f"
            "168fa1063341ebd9a"
        ),
    },
    {
        "name": "PvE Combat Wiki: independently documented player-ship damage states",
        "url": "https://sites.google.com/view/ed-pve-combat/outfitting/power-priorities",
    },
]
SCENARIOS: list[JsonDict] = [
    {
        "id": "normal",
        "label": "Normal · 100%",
        "percent": 100,
        "description": (
            "Normal plant output. This is a planning simulation, not live"
            " module status."
        ),
    },
    {
        "id": "malfunction",
        "label": "Malfunction · 40%",
        "percent": 40,
        "description": (
            "Community-verified temporary malfunction of a damaged "
            "player-ship plant. Not a continuous health-to-output curve; "
            "trigger chance/duration are not predicted."
        ),
    },
    {
        "id": "disabled",
        "label": "Zero integrity · 50%",
        "percent": 50,
        "description": (
            "Community-verified persistent output after a player-ship "
            "plant reaches zero integrity and recovers from collapse, "
            "until repaired. Not an NPC damage model."
        ),
    },
    {
        "id": "collapse",
        "label": "Collapse / malfunction at zero · 20%",
        "percent": 20,
        "description": (
            "Community-documented temporary collapse or malfunction at "
            "zero integrity. Not a prediction of timing, duration or "
            "explosion risk."
        ),
    },
    {
        "id": "custom",
        "label": "Custom · hypothetical",
        "percent": None,
        "description": (
            "Commander-selected hypothetical output, not a documented damage state."
        ),
    },
]
SCENARIO_IDS = {s["id"] for s in SCENARIOS}
CONTEXTS = {f"{s}:{d}" for s in SCENARIO_IDS for d in ("retracted", "deployed")}


def normalize_plan(value: JsonDict | None, rows: list[JsonDict]) -> JsonDict:
    "Validate only commander overrides; defaults remain in the observed slots."
    value = value or {}
    if set(value) - {"modules", "scenario", "deployment", "custom_percent", "protect"}:
        raise ValueError("Unknown power-plan fields.")
    scenario = value.get("scenario", "normal")
    deployment = value.get("deployment", "deployed")
    custom = value.get("custom_percent", 100)
    if (
        not isinstance(scenario, str)
        or not isinstance(deployment, str)
        or scenario not in SCENARIO_IDS
        or deployment not in {"retracted", "deployed"}
    ):
        raise ValueError("Unknown power scenario or deployment state.")
    if (
        isinstance(custom, bool)
        or not isinstance(custom, (int, float))
        or not math.isfinite(custom)
        or not 0 <= custom <= 100
    ):
        raise ValueError("Custom output must be a finite percentage from 0 to 100.")
    protect = value.get("protect", [f"{scenario}:{deployment}"])
    if (
        not isinstance(protect, list)
        or len(protect) > 10
        or any(not isinstance(p, str) or p not in CONTEXTS for p in protect)
    ):
        raise ValueError("Unknown power-planning scenario.")
    settings = value.get("modules", [])
    if not isinstance(settings, list) or len(settings) > 128:
        raise ValueError("Power plan must contain at most 128 slot settings.")
    by_slot = {r["slot"]: r for r in rows}
    seen = set()
    normalized = []
    for row in settings:
        if not isinstance(row, dict) or set(row) - {
            "slot",
            "enabled",
            "priority",
            "required_in",
        }:
            raise ValueError("Invalid power module settings.")
        slot = row.get("slot")
        if not isinstance(slot, str) or slot not in by_slot or slot in seen:
            raise ValueError(f"Unknown or repeated power slot: {slot}.")
        seen.add(slot)
        item: JsonDict = {"slot": slot}
        if ("enabled" in row or "priority" in row) and not by_slot[slot].get(
            "controls_verified", True
        ):
            raise ValueError(
                f"{slot}: update the local catalogue for verified power-control rules."
            )
        if "enabled" in row:
            if not isinstance(row["enabled"], bool):
                raise ValueError("Enabled state must be true or false.")
            if by_slot[slot].get("draw_mw") == 0 and row["enabled"] != by_slot[
                slot
            ].get("enabled"):
                raise ValueError(f"{slot} has no switchable electrical load.")
            if by_slot[slot].get("power_lock") and not row["enabled"]:
                raise ValueError(
                    f"{slot} cannot be switched off (reference power lock)."
                )
            item["enabled"] = row["enabled"]
        if "priority" in row:
            priority = row["priority"]
            if (
                isinstance(priority, bool)
                or not isinstance(priority, int)
                or not 1 <= priority <= 5
            ):
                raise ValueError("Power priority must be an integer from 1 to 5.")
            if (
                by_slot[slot].get("power_lock")
                and priority != by_slot[slot]["power_lock"]
            ):
                raise ValueError(
                    f"{slot} is locked to priority {by_slot[slot]['power_lock']}."
                )
            item["priority"] = priority
        required = row.get("required_in", [])
        if (
            not isinstance(required, list)
            or len(required) > 10
            or any(not isinstance(k, str) or k not in CONTEXTS for k in required)
        ):
            raise ValueError("Unknown required-module context.")
        item["required_in"] = sorted(set(required))
        normalized.append(item)
    return {
        "modules": normalized,
        "scenario": scenario,
        "deployment": deployment,
        "custom_percent": float(custom),
        "protect": sorted(set(protect)),
    }


def requested(rows: list[JsonDict], deployment: str) -> tuple[float | None, list[str]]:
    loads = []
    missing = []
    for row in rows:
        if row.get("enabled") is False or row.get("empty"):
            continue
        if row.get("enabled") is None:
            missing.append(f"{row['slot']}: enabled state")
            continue
        draw = row.get("draw_mw")
        if draw is None:
            missing.append(f"{row['slot']}: power draw")
        elif (
            deployment == "retracted" and draw and row.get("deployment_policy") is None
        ):
            missing.append(f"{row['slot']}: deployment behavior")
        elif (
            deployment == "deployed" or row.get("deployment_policy") != "deployed_only"
        ):
            loads.append(draw)
    return (None if missing else math.fsum(loads)), missing


def simulate(
    rows: list[JsonDict],
    generation: float | None,
    *,
    deployment: str,
    percent: float,
    context: str,
    requirements: JsonDict,
) -> JsonDict:
    output = generation * percent / 100 if generation is not None else None
    total, missing = requested(rows, deployment)
    active = []
    statuses = []
    for original in rows:
        row = dict(original)
        draw = row.get("draw_mw")
        if row.get("empty"):
            state = "empty"
        elif row.get("enabled") is False:
            state = "switched_off"
        elif row.get("enabled") is None or draw is None:
            state = "unknown"
        elif draw == 0:
            state = "passive"
        elif (
            deployment == "retracted"
            and row.get("deployment_policy") == "deployed_only"
        ):
            state = "not_drawing"
        elif deployment == "retracted" and row.get("deployment_policy") is None:
            state = "unknown"
        elif row.get("priority") not in range(1, 6):
            state = "unknown"
            missing.append(f"{row['slot']}: power priority")
        else:
            state = "powered"
            active.append(row)
        row["state"] = state
        row["required"] = context in requirements.get(row["slot"], [])
        statuses.append(row)
    if output is None:
        missing.append("Power plant generation")
    missing = sorted(set(missing))
    cut = 6
    effective: float | None = None
    shed = []
    if not missing and output is not None and total is not None:
        effective = total
        # Whole groups are removed lowest first. No lower group is revived just
        # because removing a higher one left spare MW; this is an ordered cut.
        for priority in range(5, 0, -1):
            if effective <= output + 1e-10:
                break
            members = [r for r in active if r["priority"] == priority]
            if members:
                effective -= math.fsum(r["draw_mw"] for r in members)
                shed.append(priority)
            cut = priority
        effective = math.fsum(r["draw_mw"] for r in active if r["priority"] < cut)
    else:
        effective = None
    for row in statuses:
        if row["state"] == "powered":
            row["state"] = (
                "unknown"
                if missing
                else (
                    "insufficient_power"
                    if row["priority"] == 1
                    else "priority_shutdown"
                )
                if row["priority"] >= cut
                else "powered"
            )
    groups = []
    for priority in range(1, 6):
        members = [r for r in statuses if r.get("priority") == priority]
        loads = [r for r in active if r["priority"] == priority]
        groups.append(
            {
                "priority": priority,
                "slots": [r["slot"] for r in members],
                "requested_mw": None
                if any(r["state"] == "unknown" for r in members)
                else math.fsum(r["draw_mw"] for r in loads),
                "shutdown": priority >= cut and bool(loads) if not missing else None,
            }
        )
    required = [r for r in statuses if r["required"]]
    lost = [r["slot"] for r in required if r["state"] not in {"powered", "passive"}]
    if missing:
        conclusion = "cannot_verify"
    elif lost:
        conclusion = "required_lost"
    elif not required:
        conclusion = "requirements_not_set"
    elif shed:
        conclusion = "nonessential_shed"
    else:
        conclusion = "all_required_powered"
    return {
        "generation_mw": output,
        "requested_mw": total,
        "requested_percent": total / output * 100
        if total is not None and output
        else None,
        "headroom_mw": output - total
        if output is not None and total is not None
        else None,
        "effective_mw": effective,
        "effective_percent": effective / output * 100
        if effective is not None and output
        else None,
        "remaining_headroom_mw": output - effective
        if output is not None and effective is not None
        else None,
        "shutdown_groups": sorted(shed),
        "modules": [
            {
                **{k: r[k] for k in ("slot", "state", "required")},
                "requested_mw": None
                if r["state"] == "unknown"
                else r["draw_mw"]
                if r["state"] in {"powered", "priority_shutdown", "insufficient_power"}
                else 0.0,
                "effective_mw": r["draw_mw"]
                if r["state"] == "powered"
                else None
                if r["state"] == "unknown"
                else 0.0,
            }
            for r in statuses
        ],
        "groups": groups,
        "missing": missing,
        "conclusion": conclusion,
        "required_lost": lost,
        "context": context,
        "deployment": deployment,
        "output_percent": percent,
    }


def compare(
    installed: list[JsonDict],
    planned: list[JsonDict],
    installed_generation: float | None,
    planned_generation: float | None,
    plan: JsonDict | None,
) -> JsonDict:
    normalized = normalize_plan(plan, planned)
    overrides = {r["slot"]: r for r in normalized["modules"]}
    requirements = {slot: r["required_in"] for slot, r in overrides.items()}
    planned = [
        {
            **r,
            **{
                k: v
                for k, v in overrides.get(r["slot"], {}).items()
                if k in {"enabled", "priority"}
            },
        }
        for r in planned
    ]
    cases = []
    for scenario in SCENARIOS:
        percent = (
            normalized["custom_percent"]
            if scenario["id"] == "custom"
            else scenario["percent"]
        )
        for deployment in ("retracted", "deployed"):
            key = f"{scenario['id']}:{deployment}"
            cases.append(
                {
                    "id": key,
                    "scenario": scenario["id"],
                    "label": scenario["label"],
                    "installed": simulate(
                        installed,
                        installed_generation,
                        deployment=deployment,
                        percent=percent,
                        context=key,
                        requirements=requirements,
                    ),
                    "planned": simulate(
                        planned,
                        planned_generation,
                        deployment=deployment,
                        percent=percent,
                        context=key,
                        requirements=requirements,
                    ),
                }
            )
    return {
        "version": VERSION,
        "plan": normalized,
        "scenarios": SCENARIOS,
        "cases": cases,
        "selected": f"{normalized['scenario']}:{normalized['deployment']}",
        "sources": SOURCES,
        "installed_modules": installed,
        "planned_modules": planned,
        "hypothetical": True,
        "limitations": [
            (
                "Steady electrical availability only: excludes capacitor "
                "depletion, ammunition, reboot/spin-up timing, module damage,"
                " heat and explosion probability. Powered is not a promise "
                "that a weapon can fire indefinitely."
            )
        ],
    }


def _label(comparison: JsonDict, key: str) -> str:
    scenario, _, deployment = key.partition(":")
    name = next(
        (s["label"] for s in comparison.get("scenarios", []) if s["id"] == scenario),
        scenario,
    )
    return f"{name} · {deployment}"


def _outcome(
    case: JsonDict, before: JsonDict, after: JsonDict, names: dict[str, str]
) -> JsonDict:
    "Reviewable result: who stays powered and who shuts down, before and after."

    def split(result: JsonDict) -> JsonDict:
        modules = result["modules"]
        return {
            "powered": [r["slot"] for r in modules if r["state"] == "powered"],
            "shutdown": [
                r["slot"]
                for r in modules
                if r["state"] in {"priority_shutdown", "insufficient_power"}
            ],
            "effective_mw": result["effective_mw"],
            "conclusion": result["conclusion"],
            "states": {r["slot"]: r["state"] for r in modules},
        }

    return {
        "context": case["id"],
        "label": case["label"],
        "deployment": after["deployment"],
        "generation_mw": after["generation_mw"],
        "requested_mw": after["requested_mw"],
        "names": names,
        "before": split(before),
        "after": split(after),
    }


def propose(comparison: JsonDict) -> JsonDict:
    """Bounded, deterministic assignment search; simulate before offering a plan.

    The selected scenario is always considered. Other protected scenarios count
    only when the commander has marked required modules in them, so a stale
    default scenario can never hide the marks made in the one being viewed.
    Nothing is applied here; the caller reviews the returned changes first.
    """
    plan = copy.deepcopy(comparison["plan"])
    selected = comparison.get("selected")
    marked = {k for r in plan["modules"] for k in r.get("required_in", [])}
    keys = sorted(({*plan["protect"], selected} - {None}) & marked)
    if not keys:
        where = _label(comparison, selected) if selected else "the selected scenario"
        return {
            "state": "requirements_needed",
            "reason": (
                f"Mark the modules that must stay powered in {where} "
                "(Analysis → Power → Required here), then suggest again."
            ),
        }
    plan["protect"] = keys
    cases = [c for c in comparison["cases"] if c["id"] in keys]
    if any(c["planned"]["missing"] for c in cases):
        return {
            "state": "unverified",
            "reason": "Missing power data prevents a verified proposal.",
        }
    rows = comparison["planned_modules"]
    if any(r.get("draw_mw") and not r.get("controls_verified", True) for r in rows):
        return {
            "state": "unverified",
            "reason": (
                "Update the local catalogue for verified power-control rules "
                "before requesting a proposal."
            ),
        }
    by_slot = {r["slot"]: r for r in rows}
    names = {r["slot"]: r.get("name") or r["slot"] for r in rows}
    required = {
        r["slot"]: tuple(sorted(set(r["required_in"]) & set(keys)))
        for r in plan["modules"]
        if set(r["required_in"]) & set(keys)
    }
    for case in cases:
        states = {r["slot"]: r["state"] for r in case["planned"]["modules"]}
        needed = [
            r
            for r in rows
            if case["id"] in required.get(r["slot"], ()) or r.get("power_lock")
        ]
        if any(
            r.get("draw_mw") is None
            or (
                r.get("draw_mw")
                and case["planned"]["deployment"] == "retracted"
                and r.get("deployment_policy") is None
            )
            for r in needed
        ):
            return {
                "state": "unverified",
                "reason": "A required module lacks verified power or deployment data.",
            }
        # A module the commander switched off stays off: never re-enable it
        # on their behalf, and say so instead of proposing around it.
        off = [
            names[r["slot"]]
            for r in needed
            if r["slot"] in required
            and r.get("enabled") is False
            and r.get("draw_mw")
            and not r["empty"]
        ]
        if off:
            return {
                "state": "required_switched_off",
                "reason": (
                    f"{', '.join(off)} {'is' if len(off) == 1 else 'are'} marked "
                    "Keep powered but switched off. Suggest priorities will not "
                    "switch equipment on: switch it on yourself or remove Keep "
                    "powered."
                ),
            }
        if any(
            r["empty"] or states[r["slot"]] == "not_drawing"
            for r in needed
            if r["slot"] in required
        ):
            return {
                "state": "impossible",
                "reason": (
                    f"A required module is absent or retracted in {case['label']}."
                ),
            }
        drawing = [
            r
            for r in needed
            if case["planned"]["deployment"] == "deployed"
            or r["deployment_policy"] != "deployed_only"
        ]
        load = math.fsum(r["draw_mw"] for r in drawing)
        if load > case["planned"]["generation_mw"] + 1e-10:
            culprits = ", ".join(names[r["slot"]] for r in drawing if r["draw_mw"])
            return {
                "state": "impossible",
                "reason": (
                    "Changing priorities cannot keep these modules powered in "
                    f"{_label(comparison, case['id'])}: required and fixed-priority "
                    f"equipment ({culprits}) requests {load:.6g} MW but only "
                    f"{case['planned']['generation_mw']:.6g} MW is generated. "
                    "Priorities cannot supply missing MW; switch off other "
                    "equipment, change the scenario or change the fit."
                ),
            }

    def run(candidate: list[JsonDict]) -> list[JsonDict]:
        return [
            simulate(
                candidate,
                c["planned"]["generation_mw"],
                deployment=c["planned"]["deployment"],
                percent=100,
                context=c["id"],
                requirements={s: list(v) for s, v in required.items()},
            )
            for c in cases
        ]

    def satisfied(results: list[JsonDict]) -> bool:
        return all(
            r["conclusion"] in {"all_required_powered", "nonessential_shed"}
            for r in results
        )

    def with_changes(changed: dict[str, tuple[int, bool | None]]) -> list[JsonDict]:
        return [
            {**r, "priority": changed[r["slot"]][0], "enabled": changed[r["slot"]][1]}
            if r["slot"] in changed
            else r
            for r in rows
        ]

    current = run(rows)
    if satisfied(current):
        return {
            "state": "no_change_needed",
            "plan": plan,
            "reason": (
                "Every required module is already powered in "
                + ", ".join(_label(comparison, k) for k in keys)
                + ". No power-priority adjustment is necessary."
            ),
            "outcomes": [
                _outcome(c, cur, cur, names)
                for c, cur in zip(cases, current, strict=True)
            ],
        }

    signatures = sorted(set(required.values()))
    choices: tuple[int | None, ...] = (None, 1, 2, 3, 4)
    assignments: Iterable[tuple[int | None, ...]]
    if len(choices) ** len(signatures) > 4096:
        assignments = [tuple(1 for _ in signatures)]
    else:
        assignments = itertools.product(choices, repeat=len(signatures))
    best: tuple[tuple[int, int, int], dict[str, tuple[int, bool | None]]] | None = None
    best_results: list[JsonDict] = []
    attempt = 0
    for assignment in assignments:
        tiers = dict(zip(signatures, assignment, strict=True))
        # Prefer leaving everything else alone; demoting it is the fallback.
        for demote in (False, True):
            attempt += 1
            changed: dict[str, tuple[int, bool | None]] = {}
            for slot, row in by_slot.items():
                if row.get("empty") or not row.get("draw_mw") or row.get("power_lock"):
                    continue
                target, enabled = row["priority"], row.get("enabled")
                if slot in required:
                    tier = tiers[required[slot]]
                    target = target if tier is None else tier
                elif demote and enabled:
                    target = 5
                if (target, enabled) != (row["priority"], row.get("enabled")):
                    changed[slot] = (target, enabled)
            results = run(with_changes(changed))
            if not satisfied(results):
                continue
            score = (
                len(changed),
                sum(abs(v[0] - by_slot[s]["priority"]) for s, v in changed.items()),
                attempt,
            )
            if best is None or score < best[0]:
                best, best_results = (score, changed), results
    if best is None:
        return {
            "state": "no_verified_proposal",
            "reason": (
                "No priority assignment was found that keeps every required "
                "module powered. This search is bounded and does not prove that "
                "none exists."
            ),
        }
    # Keep only the changes the simulation proves are needed: undo each one
    # (unrelated modules first, in slot order) and keep the undo if every
    # required module is still powered.
    kept = dict(best[1])
    for slot in sorted(kept, key=lambda s: (s in required, s)):
        trial = {k: v for k, v in kept.items() if k != slot}
        trial_results = run(with_changes(trial))
        if satisfied(trial_results):
            kept, best_results = trial, trial_results
    if not kept:
        return {
            "state": "no_change_needed",
            "plan": plan,
            "reason": "No power-priority adjustment is necessary.",
            "outcomes": [
                _outcome(c, cur, cur, names)
                for c, cur in zip(cases, current, strict=True)
            ],
        }
    settings = {r["slot"]: dict(r) for r in plan["modules"]}
    changes = []
    for slot, (priority, enabled) in kept.items():
        row = by_slot[slot]
        setting = settings.setdefault(slot, {"slot": slot, "required_in": []})
        if priority != row["priority"]:
            setting["priority"] = priority
        if enabled != row.get("enabled"):
            setting["enabled"] = enabled
        changes.append(
            {
                "slot": slot,
                "name": names[slot],
                "current_priority": row["priority"],
                "proposed_priority": priority,
                "current_enabled": row.get("enabled"),
                "proposed_enabled": enabled,
                "required": slot in required,
            }
        )
    return {
        "state": "verified_proposal",
        "plan": {**plan, "modules": list(settings.values())},
        "results": best_results,
        "changes": changes,
        "outcomes": [
            _outcome(c, cur, new, names)
            for c, cur, new in zip(cases, current, best_results, strict=True)
        ],
        "attempts": attempt,
        "reason": (
            "Required equipment stays powered with the fewest assignment changes "
            "found; every selected scenario was simulated. Review, then Apply or "
            "Cancel. Nothing changes until you apply."
        ),
    }
