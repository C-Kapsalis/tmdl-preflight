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


def entry_for(floors: dict[str, Any], model_key: str) -> tuple[bool, Any]:
    """``(found, value)`` of the floors entry for a model key."""
    want = _norm(model_key)
    for key, value in floors.items():
        k = _norm(key)
        if k == want or want.endswith("/" + k) or k.endswith("/" + want):
            return True, value
    return False, None


def write_floors(path: str | Path, data: dict[str, Any], indent: Optional[int] = 2) -> None:
    Path(path).write_text(json.dumps(data, indent=indent, sort_keys=True) + "\n", encoding="utf-8")
