"""Per-rule ratchet files ("floors").

Some rules gate a backlog rather than a defect class: existing offenders are
recorded per model in a JSON file and only growth fails. The files keep the
shape their teams already use: a mapping from a model key (the
``*.SemanticModel`` folder relative to the scanned root, with or without the
suffix) to a list of accepted objects or to per-class counts.

Shrinking is never automatic: a recorded entry that no longer fails produces
a tighten hint, and raising a floor is a human edit.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional


class RatchetFileError(ValueError):
    """The ratchet file is missing or unreadable."""


def load_floors(path: str | Path, missing_ok: bool = False) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        if missing_ok:
            return {}
        raise RatchetFileError(f"baseline file {p} not found")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RatchetFileError(f"cannot read baseline file {p} ({exc})") from exc
    if not isinstance(data, dict):
        raise RatchetFileError(f"baseline file {p} must hold a JSON object")
    return data


def _norm(key: str) -> str:
    key = key.replace("\\", "/").strip("/")
    return key[: -len(".SemanticModel")] if key.endswith(".SemanticModel") else key


def _tail(key: str, segments: int) -> str:
    """The last ``segments`` path segments of a key."""
    return "/".join(_norm(key).split("/")[-segments:])


def matching_key(floors: dict[str, Any], model_key: str) -> Optional[str]:
    """The floors key that names this model, or None when no key does.

    A key matches only when it IS the model key (with or without the
    ``.SemanticModel`` suffix), or when the model key is the last path
    segments of the key and exactly one key in the file says so: a run on a
    sub-folder finds the floor of the model it scans, and never the floor of
    another model whose name ends the same way.
    """
    want = _norm(model_key)
    for key in floors:
        if _norm(key) == want:
            return key
    segments = len(want.split("/"))
    candidates = [key for key in floors if _tail(key, segments) == want]
    if len(candidates) == 1:
        return candidates[0]
    return None


def entry_for(floors: dict[str, Any], model_key: str) -> tuple[bool, Any]:
    """``(found, value)`` of the floors entry for a model key."""
    key = matching_key(floors, model_key)
    if key is None:
        return False, None
    return True, floors[key]


def write_floors(path: str | Path, data: dict[str, Any], indent: Optional[int] = 2) -> None:
    Path(path).write_text(json.dumps(data, indent=indent, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Capturing a floor file from today's findings
# ---------------------------------------------------------------------------

#: The rules whose floor file can be captured, and the file they read.
CAPTURED_RULES = ("O007", "R008", "R016")


def _model_key(ctx, model, with_suffix: bool = True) -> str:
    key = ctx.model_key(model)
    if with_suffix:
        return key
    return key[: -len(".SemanticModel")] if key.endswith(".SemanticModel") else key


def capture_floors(rule_id: str, ctx, options: dict[str, Any]) -> tuple[dict[str, Any], int, str]:
    """``(floors, entry count, message)`` of the floor file of a rule.

    The floors hold what the rule finds today, so a team can start the
    ratchet from the file the tool writes instead of writing it by hand.
    """
    from .roles import fact_tables
    from .rules.organization import table_reads

    if rule_id == "O007":
        floors: dict[str, Any] = {}
        for model in ctx.models:
            exprs = [m.expression for m in model.all_measures() if m.expression]
            dead = sorted(name for name in fact_tables(model)
                          if table_reads(name, exprs)[0] == 0)
            if dead:
                floors[ctx.model_key(model)] = dead
        entries = sum(len(v) for v in floors.values())
        message = (f"[dead-fact-table floor] captured {entries} entries across "
                   f"{len(floors)} models")
        return floors, entries, message
    if rule_id == "R008":
        dim = options.get("dimension_table") or ""
        key = options.get("key_column") or ""
        floors = {}
        for model in ctx.models:
            flagged = []
            for name in fact_tables(model):
                joined = any(
                    r.is_active and r.from_table == name and r.to_table == dim
                    and r.to_column == key
                    for r in model.relationships
                )
                if not joined:
                    flagged.append(name)
            floors[_model_key(ctx, model, with_suffix=False)] = sorted(flagged)
        entries = sum(len(v) for v in floors.values())
        message = (f"[account-key floor] captured {entries} entries across "
                   f"{len(floors)} models")
        return floors, entries, message
    if rule_id == "R016":
        from .rules.topology import filter_graph, reachable

        floors = {}
        for model in ctx.models:
            graph = filter_graph(model)
            dead = []
            for path in sorted((model.definition_path / "tables").glob("*.tmdl")):
                stem = path.stem
                if not (stem.startswith("__") and stem.endswith("Calendar")):
                    continue
                if not reachable(graph, stem, int(options.get("max_hops") or 2)):
                    dead.append(stem)
            if dead:
                floors[ctx.model_key(model)] = sorted(dead)
        entries = sum(len(v) for v in floors.values())
        message = (f"[dead-anchor-calendar floor] captured {entries} across "
                   f"{len(floors)} models")
        return floors, entries, message
    raise ValueError(rule_id)
