"""Baselines: accept today's violations, fail only on new ones.

A baseline file records violation *identities*: rule id, project-relative
file and object, plus how many violations share that identity. Line numbers
are deliberately left out, so editing an unrelated part of a file does not
turn a known violation into a "new" one.

Rules whose violations stop a model from opening or deploying at all
declare ``baselinable = False``; they can never be written to a baseline,
and entries for them in a hand-edited file are ignored (and reported).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from .rules.base import RuleSet, Violation

BASELINE_FILENAME = ".tmdl-preflight-baseline.json"
FORMAT_VERSION = 1

Identity = tuple[str, str, str]


class BaselineError(ValueError):
    """The baseline file is missing, unreadable or malformed."""


@dataclass
class BaselineResult:
    """What applying a baseline to a run did."""

    suppressed: list[Violation] = field(default_factory=list)
    # entries whose violations have (partly) gone away: identity, baseline
    # count, current count
    fixed: list[tuple[Identity, int, int]] = field(default_factory=list)
    # entries that can never match: unknown or non-baselinable rule
    stale: list[tuple[Identity, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "suppressed": len(self.suppressed),
            "fixed": [
                {"rule": i[0], "path": i[1], "object": i[2], "baseline": b, "current": c}
                for i, b, c in self.fixed
            ],
            "stale": [
                {"rule": i[0], "path": i[1], "object": i[2], "reason": why}
                for i, why in self.stale
            ],
        }


def count_identities(violations: Iterable[Violation], ruleset: RuleSet) -> Counter:
    """Identity counts of the baselinable violations in a run."""
    baselinable = {r.id for r in ruleset.rules if r.baselinable}
    return Counter(v.identity() for v in violations if v.rule_id in baselinable)


def entries_from_counts(counts: Counter) -> list[dict]:
    return [
        {"rule": rule, "path": path, "object": obj, "count": n}
        for (rule, path, obj), n in sorted(counts.items())
        if n > 0
    ]


def write_baseline(path: Path, counts: Counter, tool_version: str) -> None:
    payload = {
        "tool": "tmdl-preflight",
        "tool_version": tool_version,
        "format": FORMAT_VERSION,
        "entries": entries_from_counts(counts),
    }
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_baseline(path: Path) -> Counter:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise BaselineError(f"{path}: baseline file not found") from None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        raise BaselineError(f"{path}: cannot read baseline ({exc})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        raise BaselineError(f"{path}: not a tmdl-preflight baseline (no 'entries' list)")
    counts: Counter = Counter()
    for n, entry in enumerate(data["entries"], start=1):
        if not isinstance(entry, dict) or not isinstance(entry.get("rule"), str):
            raise BaselineError(f"{path}: entries[{n}] is malformed")
        count = entry.get("count", 1)
        if not isinstance(count, int) or count < 1:
            raise BaselineError(f"{path}: entries[{n}].count must be a positive integer")
        key = (entry["rule"], entry.get("path") or "", entry.get("object") or "")
        counts[key] += count
    return counts


def apply_baseline(
    violations: list[Violation], baseline: Counter, ruleset: RuleSet,
    selected_ids: Optional[set[str]] = None,
) -> tuple[list[Violation], BaselineResult]:
    """Split ``violations`` into new ones (returned) and suppressed ones.

    For each identity the first ``count`` violations (by line) are known;
    any beyond that are new. Entries for rules that did not run in this
    invocation (``selected_ids``) are neither fixed nor stale.
    """
    rules = {r.id: r for r in ruleset.rules}
    result = BaselineResult()
    remaining = dict(baseline)
    for identity in list(remaining):
        rule = rules.get(identity[0])
        if rule is None:
            result.stale.append((identity, "rule does not exist"))
            del remaining[identity]
        elif not rule.baselinable:
            result.stale.append((identity, "rule can never be baselined"))
            del remaining[identity]
    kept: list[Violation] = []
    for v in sorted(violations, key=lambda v: (v.identity(), v.line or 0)):
        key = v.identity()
        if remaining.get(key, 0) > 0:
            remaining[key] -= 1
            result.suppressed.append(v)
        else:
            kept.append(v)
    for identity, left in remaining.items():
        if left > 0 and (selected_ids is None or identity[0] in selected_ids):
            result.fixed.append((identity, baseline[identity], baseline[identity] - left))
    # keep the caller's ordering for the new violations
    order = {id(v): n for n, v in enumerate(violations)}
    kept.sort(key=lambda v: order[id(v)])
    return kept, result


def update_counts(old: Counter, current: Counter, accept_new: bool) -> Counter:
    """Shrink a baseline to what still exists; grow it only on request."""
    new: Counter = Counter()
    keys = set(old) | (set(current) if accept_new else set())
    for key in keys:
        n = current.get(key, 0) if accept_new else min(old.get(key, 0), current.get(key, 0))
        if n > 0:
            new[key] = n
    return new
