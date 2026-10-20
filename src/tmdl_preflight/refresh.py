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
    start: int  # first body line
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


def structural_problems(layout: TableLayout, markers: list[str]) -> list[tuple[str, str]]:
    """``(kind, message)`` for each structural problem of an existing policy."""
    pol = layout.policy
    if pol is None:
        return []
    out: list[tuple[str, str]] = []
    ms = layout.m_partitions()
    if ms and ms[0].line < pol.line:
        out.append(("placement", f"refreshPolicy is declared after partition {ms[0].name}; "
                                 f"TMDL expects the policy before the partition. Move the block up."))
    if layout.early_annotations:
        out.append(("placement", "a table-level annotation or changedProperty comes before "
                                 "refreshPolicy; move the policy above it."))
    ptype = pol.scalars.get("policyType")
    if ptype != "basic":
        out.append(("scalar", f"policyType is {ptype or 'missing'}; only basic is supported."))
    for key in ("rollingWindowGranularity", "incrementalGranularity"):
        val = pol.scalars.get(key)
        if val not in GRANULARITIES:
            out.append(("scalar", f"{key} is {val or 'missing'}; use one of "
                                  f"{', '.join(GRANULARITIES)}."))
    for key in ("rollingWindowPeriods", "incrementalPeriods"):
        val = pol.scalars.get(key)
        if val is None or not re.fullmatch(r"\d+", val) or int(val) < 1:
            out.append(("scalar", f"{key} is {val or 'missing'}; it must be a whole number of "
                                  f"at least 1."))
    if pol.unknown:
        out.append(("scalar", f"unknown refreshPolicy properties: {', '.join(pol.unknown)}."))
    if pol.expression is None:
        out.append(("expression", "refreshPolicy has no sourceExpression."))
    if not ms:
        out.append(("expression", "the table has no M partition for the policy to apply to."))
    if pol.expression is not None and ms and ms[0].source is not None:
        diff = first_difference(pol.expression.lines(layout.lines), ms[0].source.lines(layout.lines))
        if diff:
            out.append(("identity", (
                f"sourceExpression differs from the source of partition {ms[0].name} (first "
                f"difference at body line {diff[0]}, column {diff[1]}); Power BI requires them "
                f"to be identical. The repair copies the partition source.")))
    src = layout.text_of(ms[0].source) if ms else layout.text_of(pol.expression)
    if not is_windowed(src, markers):
        out.append(("window", f"the source is not windowed (it needs RangeStart and one of "
                              f"{', '.join(markers)}); the policy filters nothing."))
    return out


# ---------------------------------------------------------------------------
# Eligibility of a fact without a policy
# ---------------------------------------------------------------------------


def _call_args(text: str, fn: str) -> Optional[list[str]]:
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
    return args


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


def eligibility(layout: TableLayout, cfg: dict) -> Eligibility:
    markers = list(cfg.get("window_markers") or ["RangeEnd"])
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
        return Eligibility("eligible", "windowed source without a policy (lost in a merge?)",
                           windowed=True)
    fn = cfg.get("loader_function")
    args = _call_args(src, fn) if fn else None
    if not args or len(args) < 4:
        return Eligibility("undecidable", "hand-written M source")
    view, date_col, no_filter, floor = (_unquote(a) for a in args[:4])
    if no_filter.strip().lower() == "true":
        return Eligibility("ineligible", "the loader is told not to filter")
    if not date_col.strip():
        return Eligibility("ineligible", "no date column")
    reason = "date-filtered loader call"
    if date_col in (cfg.get("etl_stamp_columns") or []):
        reason += f" (caution: {date_col} is a load-stamp column, not a business date)"
    return Eligibility("eligible", reason, view=view, date_column=date_col, floor=floor)


def policy_block(window: dict, header: str, body: list[str], closing: Optional[str]) -> list[str]:
    w = {**DEFAULT_WINDOW, **(window or {})}
    out = ["\trefreshPolicy"]
    out += [f"\t\t{k}: {w[k]}" for k in KNOWN_SCALARS]
    out.append(header)
    out += body
    if closing is not None:
        out.append(closing)
    return out
