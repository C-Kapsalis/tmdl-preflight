"""Lightweight DAX text utilities.

None of this is a DAX parser. The functions here do exactly the amount of
lexing needed for structural checks: they understand strings, quoted table
identifiers, bracketed member identifiers and the three comment forms, so
that delimiters and commas inside those regions are never miscounted.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Character-class scanner
# ---------------------------------------------------------------------------

# Scanner region codes
CODE = "c"        # plain DAX code
STRING = "s"      # inside "..." (with "" escapes)
IDENT = "i"       # inside '...' (table identifier, with '' escapes)
BRACKET = "b"     # inside [...] (member identifier, with ]] escapes)
COMMENT = "x"     # inside --, // or /* */ comments


def classify(text: str) -> str:
    """Return a string the same length as ``text`` where each position is
    tagged with the region it belongs to (see the CODE/STRING/... constants).

    Delimiter characters that *open or close* a region are tagged as part of
    that region, except the brackets of a member identifier, which are tagged
    BRACKET so a balance check can still see them.
    """
    tags = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""

        if ch == '"':
            # string literal: consume to closing quote, honoring "" escapes
            tags.append(STRING)
            i += 1
            while i < n:
                if text[i] == '"':
                    if i + 1 < n and text[i + 1] == '"':
                        tags.extend([STRING, STRING])
                        i += 2
                        continue
                    tags.append(STRING)
                    i += 1
                    break
                tags.append(STRING)
                i += 1
            continue

        if ch == "'":
            # quoted table identifier, honoring '' escapes
            tags.append(IDENT)
            i += 1
            while i < n:
                if text[i] == "'":
                    if i + 1 < n and text[i + 1] == "'":
                        tags.extend([IDENT, IDENT])
                        i += 2
                        continue
                    tags.append(IDENT)
                    i += 1
                    break
                tags.append(IDENT)
                i += 1
            continue

        if ch == "[":
            # bracketed member identifier, honoring ]] escapes
            tags.append(BRACKET)
            i += 1
            while i < n:
                if text[i] == "]":
                    if i + 1 < n and text[i + 1] == "]":
                        tags.extend([BRACKET, BRACKET])
                        i += 2
                        continue
                    tags.append(BRACKET)
                    i += 1
                    break
                tags.append(BRACKET)
                i += 1
            continue

        if (ch == "-" and nxt == "-") or (ch == "/" and nxt == "/"):
            # line comment: to end of line
            while i < n and text[i] not in "\r\n":
                tags.append(COMMENT)
                i += 1
            continue

        if ch == "/" and nxt == "*":
            # block comment: to closing */ (or end of text if unterminated)
            end = text.find("*/", i + 2)
            stop = (end + 2) if end != -1 else n
            tags.extend([COMMENT] * (stop - i))
            i = stop
            continue

        tags.append(CODE)
        i += 1

    return "".join(tags)


def strip_comments(text: str) -> str:
    """Blank out comments (positions preserved); strings survive intact."""
    tags = classify(text)
    return "".join(
        " " if tag == COMMENT and ch not in "\r\n" else ch
        for ch, tag in zip(text, tags)
    )


def strip_strings(text: str) -> str:
    """Blank out the *contents* of string literals (quotes survive)."""
    tags = classify(text)
    out = []
    for ch, tag in zip(text, tags):
        if tag == STRING and ch != '"' and ch not in "\r\n":
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------
# Delimiter balance
# ---------------------------------------------------------------------------

_PAIRS = {"(": ")", "{": "}"}
_CLOSERS = {v: k for k, v in _PAIRS.items()}
_NAMES = {"(": "parenthesis", "{": "brace", ")": "parenthesis", "}": "brace"}


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def check_balanced_delimiters(text: str) -> list[str]:
    """Return a list of human-readable balance errors (empty = clean).

    Checks parentheses and braces in code regions, unterminated strings and
    quoted identifiers, and unterminated bracketed identifiers. Comments are
    ignored. Brackets are validated by the scanner itself: an unterminated
    ``[`` shows up as a bracket region that never closes.
    """
    errors: list[str] = []
    tags = classify(text)

    # Unterminated string / identifier / bracket regions: the scanner ended
    # the text while still inside the region.
    errors.extend(_unterminated_regions(text, tags))

    stack: list[tuple[str, int]] = []
    for pos, (ch, tag) in enumerate(zip(text, tags)):
        if tag != CODE:
            continue
        if ch in _PAIRS:
            stack.append((ch, pos))
        elif ch in _CLOSERS:
            if stack and stack[-1][0] == _CLOSERS[ch]:
                stack.pop()
            else:
                errors.append(
                    f"unmatched closing {_NAMES[ch]} '{ch}' at line {_line_of(text, pos)}"
                )
    for ch, pos in stack:
        errors.append(
            f"unmatched opening {_NAMES[ch]} '{ch}' at line {_line_of(text, pos)}"
        )
    return errors


def _unterminated_regions(text: str, tags: str) -> list[str]:
    """Detect string/identifier/bracket regions that never close."""
    errors: list[str] = []
    i, n = 0, len(text)
    while i < n:
        tag = tags[i]
        if tag == STRING:
            j = i
            while j < n and tags[j] == STRING:
                j += 1
            region = text[i:j]
            # a closed string ends with a quote that is not part of an escape
            if not _closed(region, '"'):
                errors.append(f"unterminated string starting at line {_line_of(text, i)}")
            i = j
        elif tag == IDENT:
            j = i
            while j < n and tags[j] == IDENT:
                j += 1
            if not _closed(text[i:j], "'"):
                errors.append(
                    f"unterminated quoted identifier starting at line {_line_of(text, i)}"
                )
            i = j
        elif tag == BRACKET:
            j = i
            while j < n and tags[j] == BRACKET:
                j += 1
            region = text[i:j]
            if not (len(region) >= 2 and region.endswith("]")):
                errors.append(
                    f"unterminated bracket '[' at line {_line_of(text, i)}"
                )
            i = j
        else:
            i += 1
    return errors


def _closed(region: str, quote: str) -> bool:
    """True if a quoted region (starting with the quote char) is terminated."""
    if len(region) < 2 or not region.endswith(quote):
        return False
    # count trailing quotes: an odd run means the last one is the closer
    run = 0
    for ch in reversed(region[1:]):
        if ch == quote:
            run += 1
        else:
            break
    return run % 2 == 1


# ---------------------------------------------------------------------------
# NAMEOF reference extraction
# ---------------------------------------------------------------------------

_NAMEOF_RE = re.compile(
    r"NAMEOF\s*\(\s*"
    r"(?:'(?P<qtable>(?:[^']|'')+)'|(?P<table>[A-Za-z_][\w ]*?))?"
    r"\s*\[(?P<member>[^\]]+)\]\s*\)",
    re.IGNORECASE,
)


def extract_nameof_references(text: str) -> list[tuple[str | None, str, int]]:
    """Return ``(table_or_None, member, line)`` for each NAMEOF() call.

    ``table_or_None`` is None for the bare-measure form ``NAMEOF([X])``.
    Comments are stripped first so parked rows do not count.
    """
    clean = strip_comments(text)
    refs = []
    for m in _NAMEOF_RE.finditer(clean):
        table = m.group("qtable")
        if table is not None:
            table = table.replace("''", "'")
        elif m.group("table"):
            table = m.group("table").strip()
        member = m.group("member").strip()
        refs.append((table or None, member, _line_of(clean, m.start())))
    return refs


# ---------------------------------------------------------------------------
# Stray structural commas
# ---------------------------------------------------------------------------

_COMMA_RUN_RE = re.compile(r",(\s*,)+")


def mask_comments(text: str) -> str:
    """Length-preserving copy with comment characters replaced by spaces."""
    return strip_comments(text)


def find_comma_runs(text: str) -> list[tuple[int, int]]:
    """Return ``(line, orphan_count)`` for every run of 2+ commas separated
    only by whitespace. Commas inside comments are exempt (a commented-out
    row is intentionally parked, not a defect)."""
    masked = mask_comments(text)
    runs = []
    for m in _COMMA_RUN_RE.finditer(masked):
        runs.append((_line_of(text, m.start()), m.group(0).count(",") - 1))
    return runs


def collapse_comma_runs(text: str) -> tuple[str, int]:
    """Remove the orphan commas of every run, keeping each run's first comma
    (the live separator). Whitespace and comments are untouched. Returns
    ``(new_text, removed_count)``."""
    masked = mask_comments(text)
    drop: set[int] = set()
    for m in _COMMA_RUN_RE.finditer(masked):
        positions = [m.start() + k for k, ch in enumerate(m.group(0)) if ch == ","]
        drop.update(positions[1:])
    if not drop:
        return text, 0
    return "".join(ch for k, ch in enumerate(text) if k not in drop), len(drop)
