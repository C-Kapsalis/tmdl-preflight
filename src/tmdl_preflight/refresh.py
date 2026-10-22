"""Incremental refresh: read a table file's ``refreshPolicy`` block and
partitions straight from its lines, judge the policy's structure, and decide
whether a fact without a policy is eligible for one.

Both refresh rules (structure and coverage) and their fixers use this one
reader, so the gate and the repair never disagree about what a file holds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

KNOWN_SCALARS = ("policyType", "rollingWindowGranularity", "rollingWindowPeriods",
                 "incrementalGranularity", "incrementalPeriods")
GRANULARITIES = ("day", "month", "quarter", "year")
DEFAULT_WINDOW = {"policyType": "basic", "rollingWindowGranularity": "year",
                  "rollingWindowPeriods": 6, "incrementalGranularity": "month",
                  "incrementalPeriods": 3}
#: the closing fence of a written ``sourceExpression`` body: four tabs and
#: three backticks, whatever the partition's own fence is indented with.
FENCE = "\t\t\t\t```"

WINDOWED_ORPHAN_REASON = (
    "partition source is ALREADY windowed on RangeStart/RangeEnd but the "
    "refreshPolicy block is missing -- likely lost in a merge. Re-adding it is "
    "metadata-only (no XMLA full refresh owed).")
NO_TEMPLATE_REASON = "no inline_template configured"
UNFILTERED_REASON = "source is deliberately unfiltered / has no date column"
MULTILINE_TEMPLATE_REASON = "the inline_template must render to a single line"


def undecidable_reason(loader: Optional[str]) -> str:
    """Why a hand-written M source cannot get a derived window."""
    name = loader or "the configured loader"
    return (f"partition M does not call {name}(...) -- the window cannot be "
            f"derived; needs a hand-written policy")


_PARTITION_RE = re.compile(r"^\tpartition\s+(?P<name>'(?:[^']|'')+'|[^=\s]+)\s*(?:=\s*(?P<kind>\w+))?\s*$")
_SCALAR_RE = re.compile(r"^\t\t(?P<key>[A-Za-z_]\w*)\s*:\s*(?P<value>.*?)\s*$")
_EXPR_RE = re.compile(r"^\t\t(?P<key>source|sourceExpression)\s*=\s*(?P<fence>```)?\s*$")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip("\t"))


def _children(lines: list[str], start: int) -> int:
    """End index (exclusive) of the block whose header is ``lines[start]``:
    following lines that are blank or indented two tabs or more; trailing
    blank lines excluded."""
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or _indent(lines[end]) >= 2):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return end


@dataclass
class Body:
    header: int  # index of the ``source =`` / ``sourceExpression =`` line
    start: int
    end: int  # exclusive; for a fenced body the closing fence is at ``end``
    fenced: bool

    def lines(self, lines: list[str]) -> list[str]:
        return lines[self.start:self.end]

    @property
    def last(self) -> int:
        """Exclusive end of everything the body owns (closing fence too)."""
        return self.end + 1 if self.fenced else self.end


def _body(lines: list[str], header: int, limit: int, fenced: bool) -> Body:
    i = header + 1
    if fenced:
        while i < limit and lines[i].strip() != "```":
            i += 1
        end = i
    else:
        while i < limit and (not lines[i].strip() or _indent(lines[i]) >= 3):
            i += 1
        end = i
    while end > header + 1 and not lines[end - 1].strip():
        end -= 1
    return Body(header, header + 1, end, fenced)


@dataclass
class PartitionBlock:
    name: str
    kind: Optional[str]
    line: int
    mode: Optional[str] = None
    source: Optional[Body] = None


@dataclass
class PolicyBlock:
    line: int
    end: int
    scalars: dict[str, str] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)
    expression: Optional[Body] = None


@dataclass
class TableLayout:
    lines: list[str]
    policy: Optional[PolicyBlock]
    partitions: list[PartitionBlock]
    early_annotations: list[int]  # one-tab annotation lines before the policy

    def m_partitions(self) -> list[PartitionBlock]:
        return [p for p in self.partitions if (p.kind or "").lower() == "m"]

    def text_of(self, body: Optional[Body]) -> str:
        return "\n".join(body.lines(self.lines)) if body else ""


def read_layout(lines: list[str]) -> TableLayout:
    policy: Optional[PolicyBlock] = None
    partitions: list[PartitionBlock] = []
    for idx, line in enumerate(lines):
        if policy is None and line.rstrip() == "\trefreshPolicy":
            end = _children(lines, idx)
            policy = PolicyBlock(idx, end)
            i = idx + 1
            while i < end:
                ex = _EXPR_RE.match(lines[i])
                if ex and ex.group("key") == "sourceExpression":
                    policy.expression = _body(lines, i, end, bool(ex.group("fence")))
                    i = policy.expression.last
                    continue
                sc = _SCALAR_RE.match(lines[i])
                if sc:
                    if sc.group("key") in KNOWN_SCALARS:
                        policy.scalars[sc.group("key")] = sc.group("value")
                    else:
                        policy.unknown.append(sc.group("key"))
                i += 1
            continue
        m = _PARTITION_RE.match(line.rstrip("\r"))
        if m:
            end = _children(lines, idx)
            name = m.group("name")
            if name.startswith("'"):
                name = name[1:-1].replace("''", "'")
            part = PartitionBlock(name, m.group("kind"), idx)
            for i in range(idx + 1, end):
                mode = re.match(r"^\t\tmode:\s*(\S+)", lines[i])
                if mode and part.mode is None:
                    part.mode = mode.group(1)
                ex = _EXPR_RE.match(lines[i])
                if ex and ex.group("key") == "source" and part.source is None:
                    part.source = _body(lines, i, end, bool(ex.group("fence")))
            partitions.append(part)
    early = []
    if policy is not None:
        early = [i for i in range(policy.line)
                 if re.match(r"^\t(annotation|changedProperty)\b", lines[i])]
    return TableLayout(lines, policy, partitions, early)


def is_windowed(text: str, markers: list[str]) -> bool:
    return "RangeStart" in text and any(m in text for m in markers)


def first_difference(a: list[str], b: list[str]) -> Optional[tuple[int, int]]:
    """1-based (line, column) of the first difference, or None."""
    for n in range(max(len(a), len(b))):
        x = a[n] if n < len(a) else None
        y = b[n] if n < len(b) else None
        if x == y:
            continue
        if x is None or y is None:
            return n + 1, 1
        col = next((k for k in range(min(len(x), len(y))) if x[k] != y[k]), min(len(x), len(y)))
        return n + 1, col + 1
    return None


def _first_diff(a: list[str], b: list[str]) -> str:
    """The excerpt that shows where two bodies part company.

    The window is around the first differing CHARACTER, not a fixed width:
    two refresh-policy bodies share a long prefix, so a head-truncated
    excerpt would show two identical-looking strings.
    """
    for i in range(max(len(a), len(b))):
        av = a[i] if i < len(a) else "<missing line>"
        bv = b[i] if i < len(b) else "<missing line>"
        if av == bv:
            continue
        col = next((j for j, (x, y) in enumerate(zip(av, bv)) if x != y),
                   min(len(av), len(bv)))
        lo = max(0, col - 40)
        hi = col + 60
        marker = "..." if lo else ""
        return (f"      first difference at body line {i + 1}, column {col + 1}:\n"
                f"        sourceExpression: {marker}{av[lo:hi]!r}\n"
                f"        partition source: {marker}{bv[lo:hi]!r}")
    return "      (bodies equal -- divergence is in trailing line count only)"


def _periods(value: Optional[str]) -> int:
    """The periods value as an integer; -1 when it is missing or not one."""
    if value is None or not re.fullmatch(r"-?\d+", value.strip()):
        return -1
    return int(value.strip())


def structural_problems(layout: TableLayout, markers: list[str]) -> list[tuple[str, str]]:
    """``(kind, message)`` for each structural problem of an existing policy."""
    pol = layout.policy
    if pol is None:
        return []
    out: list[tuple[str, str]] = []
    ms = layout.m_partitions()
    if ms and ms[0].line < pol.line:
        out.append(("placement",
                    f"refreshPolicy (line {pol.line + 1}) comes AFTER the partition "
                    f"(line {ms[0].line + 1}); it must precede it"))
    if layout.early_annotations:
        out.append(("placement",
                    f"refreshPolicy (line {pol.line + 1}) comes after a table-level "
                    f"annotation/changedProperty (line {layout.early_annotations[0] + 1}) "
                    f"-- TMDL rejects the model"))
    ptype = pol.scalars.get("policyType", "")
    if ptype != "basic":
        out.append(("scalar", f"policyType '{ptype}' not in ('basic',)"))
    for key in ("rollingWindowGranularity", "incrementalGranularity"):
        val = pol.scalars.get(key, "")
        if val not in GRANULARITIES:
            out.append(("scalar", f"{key} '{val}' not in {GRANULARITIES}"))
    for key in ("rollingWindowPeriods", "incrementalPeriods"):
        n = _periods(pol.scalars.get(key))
        if n < 1:
            out.append(("scalar", f"{key} must be a positive integer (got {n})"))
    if pol.unknown:
        out.append(("scalar", "unrecognized refreshPolicy propert(ies): "
                              f"{', '.join(sorted(pol.unknown))}"))
    expression = pol.expression.lines(layout.lines) if pol.expression else []
    if not expression:
        out.append(("expression", "refreshPolicy has no sourceExpression"))
    elif not ms:
        out.append(("expression", "refreshPolicy present but the table has no M partition"))
    else:
        part = ms[0]
        source = part.source.lines(layout.lines) if part.source else []
        if expression != source:
            out.append(("identity",
                        "refreshPolicy.sourceExpression is NOT byte-identical to the "
                        f"partition '{part.name}' source (Power BI requires it; refreshes "
                        "will fail or silently reprocess the wrong slice).\n"
                        + _first_diff(expression, source)))
        if not is_windowed("\n".join(expression), markers):
            out.append(("window",
                        "refreshPolicy.sourceExpression does not reference RangeStart/RangeEnd "
                        "-- the window cannot fold to the source, so every refresh "
                        "reprocesses everything"))
    return out


# ---------------------------------------------------------------------------
# Eligibility of a fact without a policy
# ---------------------------------------------------------------------------


@dataclass
class LoaderCall:
    """A parsed loader call inside a partition source."""

    args: list[str]
    start: int  # char offset of the function name in the source text
    end: int  # char offset one past the closing parenthesis


def find_loader_call(text: str, fn: str) -> Optional[LoaderCall]:
    """Locate and parse the loader call in a partition source.

    Paren-balanced: the argument list itself may hold nested parentheses, so
    a ``[^)]*\\`` pattern cannot do this.
    """
    pat = re.compile(r'(?:(?<![\w."])' + re.escape(fn) + r'|#"' + re.escape(fn) + r'")\s*\(')
    m = pat.search(text)
    if not m:
        return None
    args, buf, depth, i = [], [], 1, m.end()
    in_str = False
    while i < len(text) and depth:
        ch = text[i]
        if in_str:
            buf.append(ch)
            if ch == '"':
                if text[i + 1:i + 2] == '"':
                    buf.append('"')
                    i += 1
                else:
                    in_str = False
        elif ch == '"':
            in_str = True
            buf.append(ch)
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            if depth:
                buf.append(ch)
        elif ch == "," and depth == 1:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    if depth:
        return None
    args.append("".join(buf).strip())
    return LoaderCall(args, m.start(), i)


def _unquote(v: str) -> str:
    v = v.strip()
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


@dataclass
class Eligibility:
    verdict: str  # eligible | ineligible | undecidable
    reason: str
    windowed: bool = False
    view: Optional[str] = None
    date_column: Optional[str] = None
    floor: Optional[str] = None
    #: whether the fixer can write a policy for this table
    repairable: bool = False


def eligibility(layout: TableLayout, cfg: dict) -> Eligibility:
    markers = list(cfg.get("window_markers") or ["RangeEnd"])
    loader = cfg.get("loader_function")
    if not layout.partitions:
        return Eligibility("ineligible", "no partition")
    ms = layout.m_partitions()
    if not ms:
        return Eligibility("ineligible", "no M partition")
    if len(ms) > 1:
        return Eligibility("ineligible", "more than one M partition")
    part = ms[0]
    if part.mode and part.mode.lower() != "import":
        return Eligibility("ineligible", f"mode {part.mode}")
    src = layout.text_of(part.source)
    if "Table.FromRows" in src:
        return Eligibility("ineligible", "entered data")
    if is_windowed(src, markers):
        return Eligibility("eligible", WINDOWED_ORPHAN_REASON, windowed=True, repairable=True)
    call = find_loader_call(src, loader) if loader else None
    if call is None or len(call.args) < 4:
        return Eligibility("undecidable", undecidable_reason(loader))
    view, date_col, no_filter = (_unquote(a) for a in call.args[:3])
    floor = call.args[3].strip()
    if no_filter.strip().lower() == "true":
        return Eligibility("ineligible", f"the loader is told not to filter on view '{view}'")
    if not date_col.strip():
        return Eligibility("ineligible", f"the loader has no date column on view '{view}'")
    reason = (f"event-date fact on view '{view}' windowing on '{date_col}' -- "
              f"should be incrementally refreshed.")
    if date_col in (cfg.get("etl_stamp_columns") or []):
        reason += (f" CAUTION: '{date_col}' is the ETL load stamp, not an event date -- "
                   f"windowing on it freezes rows the ETL never re-touches. Adjudicate "
                   f"before policying (exempt it, or repoint the source to a real "
                   f"event date).")
    template = cfg.get("inline_template")
    return Eligibility("eligible", reason, view=view, date_column=date_col, floor=floor,
                       repairable=bool(template) and "\n" not in str(template))


def render_template(template: str, view: str, date_column: str, floor: str,
                     table: str) -> str:
    """The windowed query that replaces the loader call.

    Only the four known placeholders are substituted, so a template that
    carries M braces of its own survives.
    """
    out = template
    for key, value in (("{view}", view), ("{date_column}", date_column),
                       ("{floor}", floor), ("{table}", table)):
        out = out.replace(key, value)
    return out


def policy_block(window: dict, header: str, body: list[str], fenced: bool) -> list[str]:
    """The ``refreshPolicy`` block lines, ``sourceExpression`` == ``body``."""
    w = {**DEFAULT_WINDOW, **(window or {})}
    out = ["\trefreshPolicy"]
    out += [f"\t\t{k}: {w[k]}" for k in KNOWN_SCALARS]
    out.append(header)
    out += body
    if fenced:
        out.append(FENCE)
    return out
