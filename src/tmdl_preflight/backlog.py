"""Editing the configuration's refresh-policy backlog in place.

The backlog holds the facts that are known to be missing a ``refreshPolicy``
(the coverage ratchet's floor). When the repair adds the policies, the
entries it fixed are pruned, so the ratchet tightens in the same run.

The edit is line by line on purpose: a re-serialised file would lose the
comments that carry the contract, and a config that churns on every repair
is a config nobody reads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Optional

#: the configuration section that holds the backlog
BACKLOG_SECTION = "refresh_policy"


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _value_end(text: str, i: int) -> int:
    """Index one past the value that starts at ``i`` (JSON, and TOML's
    arrays and strings, which share the syntax)."""
    c = text[i]
    if c == '"':
        i += 1
        while i < len(text):
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == '"':
                return i + 1
            i += 1
        raise ValueError("unterminated string")
    if c in "{[":
        depth = 0
        while i < len(text):
            ch = text[i]
            if ch == '"':
                i = _value_end(text, i)
                continue
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
        raise ValueError("unbalanced brackets")
    j = i
    while j < len(text) and text[j] not in ",}] \t\r\n":
        j += 1
    return j


def _object_items(text: str, start: int):
    """``(key, value_start, value_end)`` for every member of the object at
    ``start``."""
    i = _skip_ws(text, start)
    if i >= len(text) or text[i] != "{":
        return
    i += 1
    while True:
        i = _skip_ws(text, i)
        if i >= len(text) or text[i] == "}":
            return
        if text[i] == ",":
            i += 1
            continue
        key_end = _value_end(text, i)
        key = json.loads(text[i:key_end])
        i = _skip_ws(text, key_end)
        i = _skip_ws(text, i + 1)  # the ':'
        v_end = _value_end(text, i)
        yield key, i, v_end
        i = v_end


def _array_items(text: str, start: int):
    """``(value_start, value_end)`` for every element of the array at
    ``start``."""
    i = _skip_ws(text, start)
    if i >= len(text) or text[i] != "[":
        return
    i += 1
    while True:
        i = _skip_ws(text, i)
        if i >= len(text) or text[i] == "]":
            return
        if text[i] == ",":
            i += 1
            continue
        v_end = _value_end(text, i)
        yield i, v_end
        i = v_end


def _find_path(text: str, path: list[str]) -> Optional[tuple[int, int]]:
    """The span of the value at ``path`` in a JSON text, or None."""
    start = _skip_ws(text, 0)
    end = start
    for key in path:
        found = None
        for k, vs, ve in _object_items(text, start):
            if k == key:
                found = (vs, ve)
                break
        if found is None:
            return None
        start, end = found
    return (start, end)


def _element_span(text: str, s: int, e: int) -> tuple[int, int]:
    """The span to cut when the array element at ``[s, e)`` is removed."""
    line_start = text.rfind("\n", 0, s) + 1
    before = text[line_start:s]
    line_end = text.find("\n", e)
    if line_end < 0:
        line_end = len(text)
    after = text[e:line_end]
    if not before.strip() and not after.strip().rstrip(",").strip():
        # the element owns its line: cut the whole line
        return line_start, (line_end + 1 if line_end < len(text) else line_end)
    j = e
    while j < len(text) and text[j] in " \t\r\n":
        j += 1
    if j < len(text) and text[j] == ",":
        return s, j + 1
    j = s - 1
    while j >= 0 and text[j] in " \t\r\n":
        j -= 1
    if j >= 0 and text[j] == ",":
        return j, e
    return s, e


def _element_cuts(text: str, start: int, end: int, names: set[str]) -> list[tuple[int, int]]:
    """The spans to cut when the named elements are removed from the array
    at ``[start, end)``."""
    cuts: list[tuple[int, int]] = []
    for s, e in _array_items(text, start):
        try:
            value = json.loads(text[s:e])
        except ValueError:
            continue
        if isinstance(value, str) and value in names:
            cuts.append(_element_span(text, s, e))
    return cuts


def _apply_cuts(text: str, cuts: list[tuple[int, int]]) -> str:
    out = text
    for s, e in sorted(cuts, reverse=True):
        out = out[:s] + out[e:]
    return out


def _prune_json(text: str, model: str, names: set[str]) -> tuple[str, int]:
    path = [BACKLOG_SECTION, "backlog", model]
    span = _find_path(text, path)
    if span is None:
        return text, 0
    start, end = span
    if text[start:start + 1] != "[":
        return text, 0
    cuts = _element_cuts(text, start, end, names)
    if not cuts:
        return text, 0
    return _apply_cuts(text, cuts), len(cuts)


def _prune_toml(text: str, model: str, names: set[str]) -> tuple[str, int]:
    for header in (f"[{BACKLOG_SECTION}.backlog]",
                   f"[tool.tmdl-preflight.{BACKLOG_SECTION}.backlog]"):
        m = re.search(r"(?m)^[ \t]*" + re.escape(header) + r"[ \t]*$", text)
        if not m:
            continue
        sec_start = m.end()
        nxt = re.search(r"(?m)^[ \t]*\[", text[sec_start:])
        sec_end = sec_start + nxt.start() if nxt else len(text)
        section = text[sec_start:sec_end]
        km = re.search(r"(?m)^[ \t]*(?:'|\")?" + re.escape(model) + r"(?:'|\")?[ \t]*=",
                       section)
        if not km:
            continue
        arr_start = section.find("[", km.end())
        if arr_start < 0:
            continue
        arr_end = _value_end(section, arr_start)
        cuts = _element_cuts(section, arr_start, arr_end, names)
        if not cuts:
            return text, 0
        new_section = _apply_cuts(section, cuts)
        return text[:sec_start] + new_section + text[sec_end:], len(cuts)
    return text, 0


def prune_backlog(path: Path, model: str, names: Iterable[str]) -> int:
    """Remove ``names`` from ``model``'s backlog entry in the config file.

    Returns how many entries were removed. A file the tool cannot read, or
    an entry that is not there, is not an error: nothing is pruned.
    """
    wanted = {n for n in names if n}
    if not wanted:
        return 0
    path = Path(path)
    if not path.is_file():
        return 0
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0
    if path.suffix == ".json":
        new, count = _prune_json(text, model, wanted)
    else:
        new, count = _prune_toml(text, model, wanted)
    if count and new != text:
        try:
            path.write_text(new, encoding="utf-8", newline="")
        except OSError:
            return 0
    return count
