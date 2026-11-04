"""Versioned Material Trader exchange-rules contract (Materials 03B).

OmniCOVAS ships no exchange table: no source examined (see
docs/material-trader-rules-source-record-20261029.md) is official, complete,
current and cleared for redistribution.  This module defines what a
Commander-installed reference pack must state for its rules to be accepted, and
evaluates one declared rule deterministically.  It never supplies a rate.

A pack opts into the strict contract by adding ``trader_rule_set`` beside its
``trader_rules``.  Without it the legacy 03A shape (pay/receive and a free-text
category) is still read, and its rules are reported as ``declared_unverified``.
With it, malformed, incomplete, contradictory or unsupported rules are rejected
instead of being silently interpreted.

What the contract does not claim (open evidence questions, not defaults):

* that a ratio follows any formula over grades or groups: every exchange is stated
  explicitly, in whole lots, by the pack;
* that an absent pair means "not allowed": only ``completeness.state == complete``
  speaks for the categories it covers;
* storage caps, trader availability and game-version drift.
"""

from __future__ import annotations

import math
from typing import Any

JsonDict = dict[str, Any]

SCHEMA = "material-trader-rules-v1"
CATEGORIES = ("raw", "manufactured", "encoded")
VERIFICATION = ("declared_unverified", "community_reported", "independently_verified")
EVIDENCE_KINDS = (
    "official_documentation",
    "observed_in_game",
    "community_reference",
    "derived_from_observation",
    "assumption",
)
# Only these can establish that a rule is true in the game.  A calculator, wiki or
# forum post is a reference to check, and a pattern read out of MaterialTrade
# events proves that particular trades happened, not the rules behind them.
VERIFYING_KINDS = {"official_documentation", "observed_in_game"}
ROUNDING = ("whole_lots",)
MAX_QUANTITY = 10_000

# Weakest first: a combination of rule sets is only as strong as its weakest.
STATUS_ORDER = {name: index for index, name in enumerate(VERIFICATION)}
RULE_STATUS = {
    "declared_unverified": "pack_declared_unverified",
    "community_reported": "pack_community_reported",
    "independently_verified": "pack_independently_verified",
}

_SET_KEYS = {
    "schema",
    "id",
    "version",
    "game_version",
    "verification",
    "completeness",
    "evidence",
    "limitations",
}
_EVIDENCE_KEYS = {"id", "kind", "name", "url", "accessed", "note"}
_RULE_KEYS = {
    "id",
    "category",
    "trader_type",
    "from_material_id",
    "from_display_name",
    "from_category",
    "from_group",
    "from_grade",
    "to_material_id",
    "to_display_name",
    "to_category",
    "to_group",
    "to_grade",
    "pay",
    "receive",
    "rounding",
    "evidence_refs",
    "notes",
}
# Present (as None) on every normalized rule so readers need no special cases.
EXTENSION_DEFAULTS: JsonDict = {
    "trader_type": None,
    "from_category": None,
    "to_category": None,
    "from_group": None,
    "to_group": None,
    "from_grade": None,
    "to_grade": None,
    "rounding": "whole_lots",
    "evidence_refs": [],
}


def _text(value: Any, field: str, limit: int = 128, *, required: bool = True) -> Any:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    clean = value.strip()
    if len(clean) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return clean


def _only(raw: Any, allowed: set[str], field: str) -> JsonDict:
    if not isinstance(raw, dict):
        raise ValueError(f"{field} must be an object")
    unsupported = sorted(set(raw) - allowed)
    if unsupported:
        raise ValueError(f"{field} has unsupported field {unsupported[0]}")
    return raw


def _quantity(value: Any, field: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= MAX_QUANTITY
    ):
        raise ValueError(f"{field} must be an integer from 1 to {MAX_QUANTITY}")
    return int(value)


def _category(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value.strip().casefold() not in CATEGORIES:
        raise ValueError(f"{field} must be one of {', '.join(CATEGORIES)}")
    return value.strip().casefold()


def _pair(
    raw: JsonDict, left: str, right: str, rule_id: str, kind: str
) -> tuple[Any, Any]:
    first, second = raw.get(left), raw.get(right)
    if (first is None) != (second is None):
        raise ValueError(f"rule {rule_id} must give both {left} and {right} or neither")
    if kind == "grade" and first is not None:
        for value, name in ((first, left), (second, right)):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= 5
            ):
                raise ValueError(f"rule {rule_id} {name} must be a grade from 1 to 5")
    if kind == "group" and first is not None:
        first = _text(first, f"rule {rule_id} {left}", 64)
        second = _text(second, f"rule {rule_id} {right}", 64)
    return first, second


def normalize_rule_set(raw: Any) -> JsonDict:
    """Validate the ``trader_rule_set`` object and return its public form."""
    meta = _only(raw, _SET_KEYS, "trader_rule_set")
    if meta.get("schema") != SCHEMA:
        raise ValueError(f"trader_rule_set.schema must be {SCHEMA}")
    verification = meta.get("verification")
    if verification not in VERIFICATION:
        raise ValueError(
            "trader_rule_set.verification must be one of " + ", ".join(VERIFICATION)
        )

    evidence: list[JsonDict] = []
    seen: set[str] = set()
    raw_evidence = meta.get("evidence", [])
    if not isinstance(raw_evidence, list) or len(raw_evidence) > 32:
        raise ValueError(
            "trader_rule_set.evidence must be a list of at most 32 entries"
        )
    for index, item in enumerate(raw_evidence):
        entry = _only(item, _EVIDENCE_KEYS, f"trader_rule_set.evidence[{index}]")
        evidence_id = _text(entry.get("id"), "evidence id", 64)
        if evidence_id.casefold() in seen:
            raise ValueError(f"Duplicate evidence id: {evidence_id}")
        seen.add(evidence_id.casefold())
        kind = entry.get("kind")
        if kind not in EVIDENCE_KINDS:
            raise ValueError(
                f"evidence {evidence_id} kind must be one of "
                + ", ".join(EVIDENCE_KINDS)
            )
        evidence.append(
            {
                "id": evidence_id,
                "kind": kind,
                "name": _text(entry.get("name"), f"evidence {evidence_id} name", 160),
                "url": _text(entry.get("url"), "evidence url", 512, required=False),
                "accessed": _text(
                    entry.get("accessed"), "evidence accessed", 32, required=False
                ),
                "note": _text(entry.get("note"), "evidence note", 500, required=False),
            }
        )
    kinds = {item["kind"] for item in evidence}
    if verification != "declared_unverified" and "assumption" in kinds:
        raise ValueError(
            "A rule set resting on an assumption cannot claim more than "
            "declared_unverified"
        )
    if verification == "community_reported" and "community_reference" not in kinds:
        raise ValueError(
            "community_reported needs at least one community_reference evidence entry"
        )
    if verification == "independently_verified" and not kinds & VERIFYING_KINDS:
        raise ValueError(
            "independently_verified needs official_documentation or observed_in_game "
            "evidence; community references and trades inferred from the Journal "
            "do not qualify"
        )

    completeness = _only(
        meta.get("completeness"), {"state", "covers"}, "trader_rule_set.completeness"
    )
    state = completeness.get("state")
    if state not in {"complete", "partial"}:
        raise ValueError(
            "trader_rule_set.completeness.state must be complete or partial"
        )
    covers_raw = completeness.get("covers", [])
    if not isinstance(covers_raw, list):
        raise ValueError("trader_rule_set.completeness.covers must be a list")
    found = {_category(item, "completeness.covers entry") for item in covers_raw}
    covers = sorted(item for item in found if item is not None)
    if None in found:
        raise ValueError(
            "trader_rule_set.completeness.covers entries must be categories"
        )
    if state == "complete" and not covers:
        raise ValueError("A complete rule set must say which categories it covers")
    limitations = meta.get("limitations", [])
    if not isinstance(limitations, list) or len(limitations) > 16:
        raise ValueError(
            "trader_rule_set.limitations must be a list of at most 16 entries"
        )
    return {
        "schema": SCHEMA,
        "id": _text(meta.get("id"), "trader_rule_set.id", 96),
        "version": _text(meta.get("version"), "trader_rule_set.version", 64),
        "game_version": _text(
            meta.get("game_version"), "game_version", 64, required=False
        ),
        "verification": verification,
        "completeness": {"state": state, "covers": covers},
        "evidence": evidence,
        "limitations": [_text(item, "limitation", 500) for item in limitations],
    }


def normalize_rules(raw_rules: Any, rule_set: JsonDict) -> list[JsonDict]:
    """Validate rules against the strict contract; reject rather than interpret."""
    if not isinstance(raw_rules, list) or len(raw_rules) > 512:
        raise ValueError("trader_rules must be a list of at most 512 rules")
    evidence_ids = {item["id"].casefold() for item in rule_set["evidence"]}
    rules: list[JsonDict] = []
    seen_ids: set[str] = set()
    pair_seen: dict[tuple[str, str], tuple[int, int]] = {}
    for index, item in enumerate(raw_rules):
        raw = _only(item, _RULE_KEYS, f"trader_rules[{index}]")
        rule_id = _text(raw.get("id"), "trader rule id", 128)
        if rule_id.casefold() in seen_ids:
            raise ValueError(f"Duplicate trader rule id: {rule_id}")
        seen_ids.add(rule_id.casefold())
        pay = _quantity(raw.get("pay"), f"rule {rule_id} pay")
        receive = _quantity(raw.get("receive"), f"rule {rule_id} receive")
        source = _text(raw.get("from_material_id"), f"rule {rule_id} source material")
        target = _text(
            raw.get("to_material_id"), f"rule {rule_id} destination material"
        )
        if source.casefold() == target.casefold():
            raise ValueError(f"rule {rule_id} exchanges a material for itself")
        from_category = _category(
            raw.get("from_category"), f"rule {rule_id} from_category"
        )
        to_category = _category(raw.get("to_category"), f"rule {rule_id} to_category")
        if from_category is None or to_category is None:
            raise ValueError(f"rule {rule_id} must state from_category and to_category")
        if from_category != to_category:
            raise ValueError(
                f"rule {rule_id} crosses categories "
                f"({from_category} to {to_category}); a Material Trader deals in "
                "one category and no examined source supports an exchange "
                "between them"
            )
        trader_type = _category(raw.get("trader_type"), f"rule {rule_id} trader_type")
        if trader_type is not None and trader_type != from_category:
            raise ValueError(f"rule {rule_id} trader_type contradicts its categories")
        legacy = raw.get("category")
        if (
            legacy is not None
            and _category(legacy, f"rule {rule_id} category") != from_category
        ):
            raise ValueError(f"rule {rule_id} category contradicts from_category")
        rounding = raw.get("rounding", "whole_lots")
        if rounding not in ROUNDING:
            raise ValueError(f"rule {rule_id} rounding {rounding!r} is not supported")
        from_group, to_group = _pair(raw, "from_group", "to_group", rule_id, "group")
        from_grade, to_grade = _pair(raw, "from_grade", "to_grade", rule_id, "grade")
        refs = raw.get("evidence_refs", [])
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
            raise ValueError(
                f"rule {rule_id} evidence_refs must be a list of evidence ids"
            )
        for ref in refs:
            if ref.casefold() not in evidence_ids:
                raise ValueError(f"rule {rule_id} cites unknown evidence {ref}")
        pair = (source.casefold(), target.casefold())
        if pair in pair_seen:
            detail = "restates" if pair_seen[pair] == (pay, receive) else "contradicts"
            raise ValueError(
                f"rule {rule_id} {detail} another rule for {source} to {target}"
            )
        pair_seen[pair] = (pay, receive)
        rules.append(
            {
                "id": rule_id,
                "category": from_category,
                "from_material_id": source,
                "from_display_name": _text(
                    raw.get("from_display_name", source), "source display name"
                ),
                "to_material_id": target,
                "to_display_name": _text(
                    raw.get("to_display_name", target), "destination display name"
                ),
                "pay": pay,
                "receive": receive,
                "notes": _text(raw.get("notes"), "trader notes", 500, required=False),
                "trader_type": trader_type or from_category,
                "from_category": from_category,
                "to_category": to_category,
                "from_group": from_group,
                "to_group": to_group,
                "from_grade": from_grade,
                "to_grade": to_grade,
                "rounding": rounding,
                "evidence_refs": list(refs),
            }
        )
    completeness = rule_set["completeness"]
    if completeness["state"] == "complete":
        missing = [
            c
            for c in completeness["covers"]
            if not any(r["from_category"] == c for r in rules)
        ]
        if missing:
            raise ValueError(
                "A complete rule set must state at least one exchange for each "
                f"category it covers; none for {missing[0]}"
            )
    return rules


def with_defaults(rule: JsonDict) -> JsonDict:
    """A legacy (03A-shape) rule with the contract's optional fields as None."""
    return {**EXTENSION_DEFAULTS, **rule}


def rule_status(verification: str | None) -> str:
    return RULE_STATUS[
        verification if verification in RULE_STATUS else "declared_unverified"
    ]


def weakest(statuses: list[str]) -> str:
    return min(statuses, key=lambda value: STATUS_ORDER.get(value, 0))


def declared_categories(rule: JsonDict) -> tuple[str | None, str | None]:
    """The categories a rule declares for its source and destination, if any."""
    source = rule.get("from_category")
    target = rule.get("to_category")
    text = str(rule.get("category") or "").strip().casefold()
    legacy = text if text in CATEGORIES else None
    return (source or legacy, target or legacy)


def evaluate_exchange(
    rule: JsonDict,
    shortage: int,
    unreserved: int,
    observed: tuple[str, str],
) -> JsonDict:
    """One exchange in whole lots from stock nobody has reserved.

    ``lots_wanted`` rounds the need up, ``lots_available`` rounds the stock down, and
    the trade is the smaller, so a proposal never spends more than ``unreserved``
    and may deliver more than ``shortage`` (reported, not trimmed).  The declared
    categories must not contradict the categories the Journal observed.
    """
    pay, receive = int(rule["pay"]), int(rule["receive"])
    lots_wanted = max(math.ceil(shortage / receive), 0)
    lots_available = max(unreserved, 0) // pay
    lots = min(lots_wanted, lots_available)
    declared = declared_categories(rule)
    conflict = any(
        want in CATEGORIES and seen in CATEGORIES and want != seen
        for want, seen in zip(declared, observed, strict=True)
    )
    reason = (
        "category_conflict"
        if conflict
        else ("insufficient_unreserved_stock" if lots < 1 else None)
    )
    feasible = reason is None
    return {
        "feasible": feasible,
        "reason": reason,
        "lots_wanted": lots_wanted,
        "lots_available": lots_available,
        "lots": lots if feasible else 0,
        "pay_total": lots * pay if feasible else 0,
        "receive_total": lots * receive if feasible else 0,
        "pay_needed": lots_wanted * pay,
    }
