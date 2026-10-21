"""Lightweight DAX text utilities.

None of this is a DAX parser. The functions here do exactly the amount of
lexing needed for structural checks: they understand strings, quoted table
identifiers, bracketed member identifiers and the three comment forms, so
that delimiters and commas inside those regions are never miscounted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

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
            # block comment: to closing */; an unterminated one is ordinary
            # text, so the delimiters after it are still checked
            end = text.find("*/", i + 2)
            if end == -1:
                tags.append(CODE)
                i += 1
                continue
            stop = end + 2
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
    """Blank out the *contents* of string literals (quotes survive).

    An escaped double quote inside a string is blanked as two spaces, so the
    length of the text never changes. The escape only counts inside a string:
    the first quote of a pair opens it, the second one closes it.
    """
    tags = classify(text)
    out = []
    in_string = False
    i, n = 0, len(text)
    while i < n:
        ch, tag = text[i], tags[i]
        if tag == STRING and ch == '"':
            escaped = in_string and i + 1 < n and text[i + 1] == '"' and tags[i + 1] == STRING
            if escaped:
                out.append(" ")
                out.append(" ")
                i += 2
                continue
            in_string = not in_string
            out.append(ch)
            i += 1
            continue
        if tag == STRING and ch not in "\r\n":
            out.append(" ")
        else:
            out.append(ch)
        i += 1
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

    Every error names the delimiter kind and the character offset of the
    offending character inside the expression text. Comments are blanked out
    first, so the offsets are the ones a reader sees in the file.

    The closers come first, in text order and with the kinds mixed. Then,
    for each kind that is still open, only its earliest opener is reported,
    in the order parenthesis, bracket, brace, double quote, single quote.

    A bracketed name is one region: an apostrophe or a parenthesis inside it
    belongs to the name, not to the code. A ``]`` that closes no name is a
    stray closer, and every ``]`` outside a name counts on its own.
    """
    text = strip_comments(text)
    errors: list[str] = []
    stack: list[tuple[str, int]] = []
    brackets: list[int] = []
    double_quote: Optional[int] = None
    single_quote: Optional[int] = None

    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            end, closed = _string_end(text, i)
            if not closed and double_quote is None:
                double_quote = i
            i = end
            continue
        if ch == "'":
            if i + 1 < n and text[i + 1] == "'":
                i += 2  # an escaped apostrophe
                continue
            end, closed = _quoted_name_end(text, i)
            if not closed and single_quote is None:
                single_quote = i
            i = end
            continue
        if ch == "[":
            end = _name_end(text, i)
            if end == -1:
                brackets.append(i)
                i += 1  # an unterminated name: its content is code again
                continue
            i = end + 1
            continue
        if ch == "]":
            if brackets:
                brackets.pop()
            else:
                errors.append(f"Unmatched closing bracket ']' at position {i}")
            i += 1
            continue
        if ch in _PAIRS:
            stack.append((ch, i))
            i += 1
            continue
        if ch in _CLOSERS:
            if stack and stack[-1][0] == _CLOSERS[ch]:
                stack.pop()
            else:
                errors.append(f"Unmatched closing {_NAMES[ch]} '{ch}' at position {i}")
            i += 1
            continue
        i += 1

    openers = _open_positions(stack)
    paren_at = openers.get("(")
    if paren_at is not None:
        errors.append(f"Unmatched opening parenthesis '(' at position {paren_at}")
    if brackets:
        errors.append(f"Unmatched opening bracket '[' at position {brackets[0]}")
    brace_at = openers.get("{")
    if brace_at is not None:
        errors.append(f"Unmatched opening brace '{{' at position {brace_at}")
    if double_quote is not None:
        errors.append(f"Unmatched opening double quote at position {double_quote}")
    if single_quote is not None:
        errors.append(f"Unmatched opening single quote at position {single_quote}")
    return errors


def _open_positions(stack: list[tuple[str, int]]) -> dict[str, int]:
    """The earliest still-open position of every delimiter kind on the stack."""
    out: dict[str, int] = {}
    for ch, pos in stack:
        out.setdefault(ch, pos)
    return out


def _string_end(text: str, start: int) -> tuple[int, bool]:
    """``(end offset, closed)`` for the string literal opening at ``start``.

    A doubled quote inside the string is an escaped quote, so it does not
    close the string.
    """
    i, n = start + 1, len(text)
    while i < n:
        if text[i] == '"':
            if i + 1 < n and text[i + 1] == '"':
                i += 2
                continue
            return i + 1, True
        i += 1
    return n, False


def _quoted_name_end(text: str, start: int) -> tuple[int, bool]:
    """``(end offset, closed)`` for the quoted table name opening at ``start``."""
    i, n = start + 1, len(text)
    while i < n:
        if text[i] == "'":
            if i + 1 < n and text[i + 1] == "'":
                i += 2
                continue
            return i + 1, True
        i += 1
    return n, False


def _name_end(text: str, start: int) -> int:
    """The offset of the ``]`` that closes the name opening at ``start``.

    The brackets nest, so the name ends at the ``]`` that closes them all.
    -1 when the name never closes.
    """
    depth = 1
    i, n = start + 1, len(text)
    while i < n:
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


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
    r"(?:'(?P<qtable>(?:[^'\"]|'')+)'|(?P<table>[A-Za-z_][\w ]*?))?"
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


# ---------------------------------------------------------------------------
# Object references (tables, columns, measures)
# ---------------------------------------------------------------------------

# Words that can sit right before a bracketed identifier without naming a
# table (``RETURN [Revenue]``, ``VAR x = [Units]``...).
DAX_KEYWORDS = frozenset(
    {
        "VAR", "RETURN", "IN", "NOT", "AND", "OR", "TRUE", "FALSE", "ASC",
        "DESC", "DEFINE", "MEASURE", "EVALUATE", "ORDER", "BY", "START", "AT",
        "COLUMN", "TABLE", "FUNCTION",
    }
)

_WORD_CHAR_RE = re.compile(r"\w")
_VAR_RE = re.compile(r"\bVAR\s+([^\W\d]\w*)", re.IGNORECASE | re.UNICODE)


@dataclass
class DaxReference:
    """One object reference found in a DAX expression.

    ``kind`` is ``"table"`` for a bare ``'Table'``, ``"column"`` for a
    qualified ``'Table'[Member]`` / ``Table[Member]``, and ``"bare"`` for an
    unqualified ``[Member]``. For a bare reference, ``prev_word`` holds the
    word that precedes it across whitespace (``Sales [Amount]``), if any.
    """

    kind: str
    table: Optional[str]
    member: Optional[str]
    pos: int
    line: int
    prev_word: Optional[str] = None


def _region_end(tags: str, start: int, tag: str) -> int:
    j = start
    while j < len(tags) and tags[j] == tag:
        j += 1
    return j


def code_only(text: str) -> str:
    """Length-preserving copy with everything except CODE blanked out."""
    tags = classify(text)
    return "".join(
        ch if tag == CODE or ch in "\r\n" else " " for ch, tag in zip(text, tags)
    )


def string_literals(text: str) -> set[str]:
    """Contents of every string literal in ``text`` (escapes resolved)."""
    tags = classify(text)
    out: set[str] = set()
    i, n = 0, len(text)
    while i < n:
        if tags[i] == STRING:
            j = _region_end(tags, i, STRING)
            region = text[i:j]
            if len(region) >= 2 and region.endswith('"'):
                out.add(region[1:-1].replace('""', '"'))
            i = j
        else:
            i += 1
    return out


def variable_names(text: str) -> set[str]:
    """Lower-cased names of every ``VAR`` declared in ``text``."""
    return {m.group(1).lower() for m in _VAR_RE.finditer(code_only(text))}


def extract_references(text: str) -> list[DaxReference]:
    """Every table, qualified-column and bare-member reference in ``text``.

    Uses the region classifier, so quotes, brackets and comment markers
    inside strings, comments and other identifiers never produce phantom
    references. Unterminated regions are skipped (D001 reports them).
    """
    tags = classify(text)
    refs: list[DaxReference] = []
    i, n = 0, len(text)
    while i < n:
        tag = tags[i]
        if tag == IDENT:
            j = _region_end(tags, i, IDENT)
            region = text[i:j]
            if not _closed(region, "'"):
                i = j
                continue
            name = region[1:-1].replace("''", "'")
            k = j
            while k < n and tags[k] == CODE and text[k].isspace():
                k += 1
            if k < n and tags[k] == BRACKET:
                m = _region_end(tags, k, BRACKET)
                bregion = text[k:m]
                if bregion.endswith("]") and len(bregion) >= 2:
                    member = bregion[1:-1].replace("]]", "]")
                    refs.append(DaxReference("column", name, member, i, _line_of(text, i)))
                i = m
                continue
            refs.append(DaxReference("table", name, None, i, _line_of(text, i)))
            i = j
            continue
        if tag == BRACKET:
            j = _region_end(tags, i, BRACKET)
            region = text[i:j]
            if not (region.endswith("]") and len(region) >= 2):
                i = j
                continue
            member = region[1:-1].replace("]]", "]")
            # a word glued to the bracket qualifies it: Sales[Amount]
            w = i
            while w > 0 and tags[w - 1] == CODE and _WORD_CHAR_RE.match(text[w - 1]):
                w -= 1
            word = text[w:i]
            if word and not word[0].isdigit() and (w == 0 or text[w - 1] not in ".@"):
                if word.upper() not in DAX_KEYWORDS:
                    refs.append(DaxReference("column", word, member, w, _line_of(text, w)))
                    i = j
                    continue
            prev_word = None
            if not word:
                k = i
                while k > 0 and tags[k - 1] == CODE and text[k - 1].isspace():
                    k -= 1
                e = k
                while k > 0 and tags[k - 1] == CODE and _WORD_CHAR_RE.match(text[k - 1]):
                    k -= 1
                if e > k and e < i and not text[k].isdigit():
                    prev_word = text[k:e]
            refs.append(
                DaxReference("bare", None, member, i, _line_of(text, i), prev_word=prev_word)
            )
            i = j
            continue
        i += 1
    return refs


# ---------------------------------------------------------------------------
# Variables declared twice in one scope
# ---------------------------------------------------------------------------

_SCOPE_TOKEN_RE = re.compile(r"[()]|\bVAR\s+([^\W\d]\w*)", re.IGNORECASE | re.UNICODE)


def find_outer_scope_duplicate_vars(text: str) -> list[tuple[str, int]]:
    """``(name, line)`` for every ``VAR`` re-declared at parenthesis depth 0.

    The same name inside separate nested sub-expressions (each with its own
    RETURN) is legal and never reported. Comments and strings are ignored.
    """
    code = code_only(text)
    depth = 0
    seen: set[str] = set()
    out: list[tuple[str, int]] = []
    for m in _SCOPE_TOKEN_RE.finditer(code):
        tok = m.group(0)
        if tok == "(":
            depth += 1
        elif tok == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            name = m.group(1).lower()
            if name in seen:
                out.append((m.group(1), _line_of(text, m.start())))
            seen.add(name)
    return out


# ---------------------------------------------------------------------------
# Table constructors: { (..), (..) } rows in calculated-table sources
# ---------------------------------------------------------------------------


@dataclass
class ConstructorIssue:
    """A structural defect in a ``{ ... }`` table constructor.

    ``kind`` is ``"missing_separator"`` (``pos`` is where the comma belongs,
    right after the previous row's closing parenthesis), ``"trailing_comma"``
    (``pos`` is the comma before ``}``) or ``"ragged"`` (``widths`` lists
    each row's column count; ``pos`` is the opening brace).
    """

    kind: str
    pos: int
    line: int
    widths: tuple[int, ...] = ()


def scan_table_constructors(text: str) -> list[ConstructorIssue]:
    """Find missing row separators, trailing commas and ragged rows.

    Rows may span several lines, and two rows may share one line; commas
    inside nested calls (``NAMEOF(...)``), strings and comments never count.
    Runs of commas (F001's territory) are left alone here.
    """
    tags = classify(text)
    issues: list[ConstructorIssue] = []
    # frame: [kind, data]; kind "{" carries state, "(" carries tuple info
    stack: list[dict] = []
    for pos, (ch, tag) in enumerate(zip(text, tags)):
        top = stack[-1] if stack else None
        if tag == COMMENT or (tag == CODE and ch.isspace()):
            continue
        if tag != CODE:
            # string / identifier / bracket content is element content
            if top is not None and top["kind"] == "{":
                if top["state"] != "in_element":
                    top["state"] = "in_element"
                    top["all_tuples"] = False
            continue
        if ch == "{":
            if top is not None and top["kind"] == "{":
                top["state"] = "in_element"
                top["all_tuples"] = False
            stack.append(
                {"kind": "{", "pos": pos, "state": "open", "comma": None,
                 "widths": [], "all_tuples": True, "last_tuple_end": None}
            )
            continue
        if ch == "(":
            tuple_row = False
            if top is not None and top["kind"] == "{":
                if top["state"] == "after_tuple":
                    issues.append(
                        ConstructorIssue(
                            "missing_separator", top["last_tuple_end"],
                            _line_of(text, top["last_tuple_end"]),
                        )
                    )
                tuple_row = top["state"] in ("open", "comma", "after_tuple")
                if not tuple_row:
                    top["all_tuples"] = False
                top["state"] = "in_tuple" if tuple_row else "in_element"
            stack.append({"kind": "(", "tuple": tuple_row, "commas": 0})
            continue
        if ch == ")":
            if top is None or top["kind"] != "(":
                continue  # unbalanced: D001 reports it
            stack.pop()
            parent = stack[-1] if stack else None
            if top["tuple"] and parent is not None and parent["kind"] == "{":
                parent["widths"].append(top["commas"] + 1)
                parent["state"] = "after_tuple"
                parent["last_tuple_end"] = pos + 1
            continue
        if ch == "}":
            if top is None or top["kind"] != "{":
                continue
            stack.pop()
            if top["state"] == "comma" and top["comma"] is not None:
                issues.append(
                    ConstructorIssue("trailing_comma", top["comma"], _line_of(text, top["comma"]))
                )
            widths = top["widths"]
            if top["all_tuples"] and len(set(widths)) > 1:
                issues.append(
                    ConstructorIssue("ragged", top["pos"], _line_of(text, top["pos"]), tuple(widths))
                )
            parent = stack[-1] if stack else None
            if parent is not None and parent["kind"] == "{":
                parent["state"] = "in_element"
            continue
        if ch == ",":
            if top is None:
                continue
            if top["kind"] == "(":
                if top["tuple"]:
                    top["commas"] += 1
                continue
            top["state"] = "comma"
            top["comma"] = pos
            continue
        # any other code character is part of a scalar element
        if top is not None and top["kind"] == "{":
            if top["state"] == "after_tuple":
                top["state"] = "in_element"
                top["all_tuples"] = False
            elif top["state"] != "in_tuple":
                top["state"] = "in_element"
                top["all_tuples"] = False
    return issues


def insert_missing_row_separators(text: str) -> tuple[str, int]:
    """Insert a comma after every row that is missing one."""
    positions = sorted(
        {i.pos for i in scan_table_constructors(text) if i.kind == "missing_separator"},
        reverse=True,
    )
    for p in positions:
        text = text[:p] + "," + text[p:]
    return text, len(positions)


def remove_trailing_row_commas(text: str) -> tuple[str, int]:
    """Delete every comma that sits directly before a closing ``}``."""
    positions = sorted(
        {i.pos for i in scan_table_constructors(text) if i.kind == "trailing_comma"},
        reverse=True,
    )
    for p in positions:
        text = text[:p] + text[p + 1 :]
    return text, len(positions)
