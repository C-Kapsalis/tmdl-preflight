"""What format does a measure name resolve to in a format calculation group?

Many models format measures through a calculation group whose dynamic format
string is a ``SWITCH(TRUE(), CONTAINSSTRING(SELECTEDMEASURENAME(), "cost"),
"#,##0 EUR", ...)`` chain. The first matching arm wins, not the best one, so a
rename can move a measure into an earlier arm and silently change how it
renders. :func:`resolve` evaluates that chain for one name, optionally with a
field-parameter axis in scope, and never guesses: an arm it cannot read
makes the answer :data:`UNKNOWN`.

Supported grammar: string literals, ``&`` concatenation (a non-literal part
becomes ``<cur>``), nested ``SWITCH(TRUE(), ...)``; conditions ``TRUE()``,
``||``, ``&&``, ``NOT``, ``ISINSCOPE('T'[c])``, ``CONTAINSSTRING(hay,
"needle")``, ``ISSELECTEDMEASURE([a], [b])`` and ``ISBLANK(hay)``, with the
haystacks ``SELECTEDMEASURENAME()`` and ``SELECTEDVALUE('T'[c], ...)``.
Anything after the first ``RETURN`` is evaluated; variables are not tracked.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

UNKNOWN = "<unknown>"
CURRENCY_MARK = "<cur>"

_OBJECT_START = ("calculationItem", "measure", "column", "table", "annotation")
_ISINSCOPE_RE = re.compile(r"ISINSCOPE\s*\(\s*'((?:[^']|'')+)'\s*\[", re.IGNORECASE)


class _Unreadable(Exception):
    pass


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def format_definition(text: str) -> Optional[str]:
    """The first ``formatStringDefinition`` of a calculation-group file."""
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("formatStringDefinition"):
            continue
        rest = stripped[len("formatStringDefinition"):].lstrip()
        if not rest.startswith("="):
            continue
        rest = rest[1:].strip()
        if rest and rest != "```":
            return rest
        body = []
        for nxt in lines[idx + 1:]:
            head = nxt.lstrip("\t").strip()
            if head.startswith(_OBJECT_START) or head.startswith("```"):
                if head.startswith("```"):
                    continue
                break
            body.append(nxt.strip())
        return "\n".join(body).strip()
    return None


def _drop_line_comments(text: str) -> str:
    out, quoted, i = [], False, 0
    while i < len(text):
        ch = text[i]
        if quoted:
            out.append(ch)
            if ch == '"':
                if text[i + 1:i + 2] == '"':
                    out.append('"')
                    i += 1
                else:
                    quoted = False
        elif ch == '"':
            quoted = True
            out.append(ch)
        elif text.startswith("--", i):
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def branched_axes(text: str) -> list[str]:
    """Quoted tables the file tests with ISINSCOPE, in order of appearance."""
    seen: list[str] = []
    for m in _ISINSCOPE_RE.finditer(text):
        name = m.group(1).replace("''", "'")
        if name not in seen:
            seen.append(name)
    return seen


# ---------------------------------------------------------------------------
# Lexing helpers
# ---------------------------------------------------------------------------


def _split_top(text: str, sep: str) -> list[str]:
    """Split on ``sep`` outside strings, quoted names, brackets and parens."""
    parts, buf, level, i = [], [], 0, 0
    quote: Optional[str] = None
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                if text[i + 1:i + 2] == quote:
                    buf.append(quote)
                    i += 1
                else:
                    quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "[":
            quote = "]"
        elif ch in "({":
            level += 1
        elif ch in ")}":
            level -= 1
        if level == 0 and text.startswith(sep, i):
            parts.append("".join(buf))
            buf = []
            i += len(sep)
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts]


def _closing(text: str, open_idx: int) -> int:
    """Index of the parenthesis that closes the one at ``open_idx`` (strings,
    quoted names and brackets skipped), or -1."""
    level, i = 0, open_idx
    quote: Optional[str] = None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                if quote != "]" and text[i + 1:i + 2] == quote:
                    i += 1
                else:
                    quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "[":
            quote = "]"
        elif ch == "(":
            level += 1
        elif ch == ")":
            level -= 1
            if level == 0:
                return i
        i += 1
    return -1


def _call(text: str, name: str) -> Optional[list[str]]:
    """Arguments of ``NAME( ... )`` when the call spans all of ``text``."""
    m = re.match(rf"^{name}\s*\(", text, re.IGNORECASE)
    if not m or _closing(text, m.end() - 1) != len(text) - 1:
        return None
    inner = text[m.end():-1]
    return [] if not inner.strip() else _split_top(inner, ",")


def _literal(text: str) -> Optional[str]:
    if len(text) >= 2 and text[0] == text[-1] == '"' and '"' not in text[1:-1].replace('""', ""):
        return text[1:-1].replace('""', '"')
    return None


def _table_of(ref: str) -> Optional[str]:
    m = re.match(r"^'((?:[^']|'')+)'\s*\[", ref)
    return m.group(1).replace("''", "'") if m else None


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class _Context:
    def __init__(self, name: str, label: Optional[str], axis: Optional[str]):
        self.name = name
        self.label = label if label is not None else name
        self.axis = axis
        self.unresolved: list[str] = []


def _haystack(text: str, c: _Context) -> Optional[str]:
    if _call(text, "SELECTEDMEASURENAME") == []:
        return c.name
    args = _call(text, "SELECTEDVALUE")
    if args:
        table = _table_of(args[0])
        if table is None:
            return None
        return c.label if c.axis is not None and table == c.axis else ""
    return None


def _condition(text: str, c: _Context) -> Optional[bool]:
    text = text.strip()
    if text.startswith("(") and _closing(text, 0) == len(text) - 1:
        return _condition(text[1:-1], c)
    ors = _split_top(text, "||")
    if len(ors) > 1:
        vals = [_condition(p, c) for p in ors]
        return True if True in vals else (None if None in vals else False)
    ands = _split_top(text, "&&")
    if len(ands) > 1:
        vals = [_condition(p, c) for p in ands]
        return False if False in vals else (None if None in vals else True)
    if _call(text, "TRUE") == []:
        return True
    if _call(text, "FALSE") == []:
        return False
    args = _call(text, "NOT")
    if args is not None and len(args) == 1:
        inner = _condition(args[0], c)
        return None if inner is None else not inner
    args = _call(text, "ISINSCOPE")
    if args is not None and len(args) == 1:
        table = _table_of(args[0])
        if table is None:
            raise _Unreadable(text)
        return c.axis is not None and table == c.axis
    args = _call(text, "CONTAINSSTRING")
    if args is not None:
        needle = _literal(args[1]) if len(args) == 2 else None
        if needle is None:
            raise _Unreadable(text)
        hay = _haystack(args[0], c)
        return None if hay is None else needle.lower() in hay.lower()
    args = _call(text, "ISSELECTEDMEASURE")
    if args is not None:
        names = []
        for a in args:
            m = re.search(r"\[([^\]]+)\]\s*$", a)
            if not m:
                raise _Unreadable(text)
            names.append(m.group(1).lower())
        return c.name.lower() in names
    args = _call(text, "ISBLANK")
    if args is not None and len(args) == 1:
        hay = _haystack(args[0], c)
        return None if hay is None else hay == ""
    raise _Unreadable(text)


def _value(text: str, c: _Context) -> str:
    text = text.strip()
    lit = _literal(text)
    if lit is not None:
        return lit
    args = _call(text, "SWITCH")
    if args is not None:
        return _switch(args, c)
    parts = _split_top(text, "&")
    if len(parts) > 1 and _literal(parts[0]) is not None:
        pieces = [_literal(p) for p in parts]
        joined = "".join(p for p in pieces if p is not None)
        return joined + (CURRENCY_MARK if any(p is None for p in pieces) else "")
    c.unresolved.append(text[:80])
    return UNKNOWN


def _switch(args: list[str], c: _Context) -> str:
    if not args or re.sub(r"\s+", "", args[0]).upper() != "TRUE()":
        c.unresolved.append(f"SWITCH selector is not TRUE(): {args[0][:60] if args else ''}")
        return UNKNOWN
    rest = args[1:]
    pairs, default = rest[: len(rest) // 2 * 2], (rest[-1] if len(rest) % 2 else None)
    for i in range(0, len(pairs), 2):
        try:
            hit = _condition(pairs[i], c)
        except _Unreadable as exc:
            c.unresolved.append(str(exc)[:80])
            return UNKNOWN
        if hit is None:
            return UNKNOWN
        if hit:
            return _value(pairs[i + 1], c)
    if default is not None:
        return _value(default, c)
    return UNKNOWN


def evaluate_definition(source, measure_name, axis=None, label=None):
    """Evaluate a dynamic format-string expression for one measure name."""
    expr = _drop_line_comments(source)
    after_return = re.search(r"\bRETURN\b", expr, re.IGNORECASE)
    if after_return:
        expr = expr[after_return.end():]
    c = _Context(measure_name, label, axis)
    try:
        result = _value(expr, c)
    except _Unreadable as exc:
        c.unresolved.append(str(exc)[:80])
        result = UNKNOWN
    return result, c.unresolved


def resolve(calc_group_file, measure_name, axis=None, label=None):
    """``(format string or UNKNOWN, unresolved conditions)`` for one name,
    read from the first formatStringDefinition of ``calc_group_file``."""
    definition = format_definition(Path(calc_group_file).read_text(encoding="utf-8-sig"))
    if definition is None:
        return UNKNOWN, ["no formatStringDefinition found"]
    return evaluate_definition(definition, measure_name, axis, label)


def decimals(fmt: Optional[str]) -> Optional[int]:
    """Decimal places a format string renders, or None when not numeric."""
    if fmt is None or fmt == UNKNOWN:
        return None
    stripped = fmt.strip()
    m = re.fullmatch(r"P(\d+)", stripped)
    if m:
        return int(m.group(1))
    m = re.search(r"[#0]*\.([0#]+)", stripped)
    if m:
        return len(m.group(1))
    if "#" in stripped or "0" in stripped:
        return 0
    return None
