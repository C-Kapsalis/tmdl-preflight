"""Grain and reach guards. IDs C009-C011 and D012.

Guard measures blank a ratio or count where a dimension cannot filter the
fact behind it; without them the visual repeats its overall total on every
row, a believable wrong number. The guards are hand-kept deny-lists, so
these rules hold them to the model: every axis column of a blocked table is
named, conformed tables are never blocked table-wide, helpers of one family
list the same dimensions, and the guard's OR chain stays short enough for
Analysis Services to evaluate.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..model import SemanticModel, Table
from .base import Context, Rule, Severity, Violation


def fenced_body(table: Table, measure: str) -> Optional[str]:
    """Body of a measure declared in fenced form (``measure 'X' = ```...```)
    in ``table``'s file, or None when it is not declared that way."""
    try:
        lines = table.file.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    quoted = "'" + measure.replace("'", "''") + "'"
    heads = {f"measure {quoted} = ```", f"measure {measure} = ```"}
    for idx, line in enumerate(lines):
        if line.strip() in heads:
            body = []
            for nxt in lines[idx + 1:]:
                if nxt.strip().startswith("```"):
                    return "\n".join(body)
                body.append(nxt)
            return None
    return None


def term_present(body: str, fn: str, arg: str) -> bool:
    """``FN ( arg )`` with free whitespace inside the call."""
    needle = re.compile(rf"{re.escape(fn)}\s*\(\s*{re.escape(arg)}\s*\)")
    return bool(needle.search(body))


_NAMEOF_ANY = re.compile(
    r"NAMEOF\s*\(\s*(?:'(?P<q>(?:[^']|'')+)'|(?P<b>[A-Za-z_][\w ]*?))\s*\[(?P<c>[^\]]+)\]\s*\)"
)


def _axis_lines(model: SemanticModel, prefixes: list[str]):
    for table in model.table_list:
        if any(table.name.startswith(p) for p in prefixes):
            try:
                yield from table.file.read_text(encoding="utf-8-sig").splitlines()
            except (OSError, UnicodeDecodeError):
                continue


def axis_columns(model: SemanticModel, prefixes: list[str], skip_comments: bool,
                 quoted_only: bool = False) -> dict[str, set[str]]:
    """Columns the axis field parameters register, by table, as ``'T'[c]``.
    ``quoted_only`` ignores references whose table is not single-quoted."""
    found: dict[str, set[str]] = {}
    for text in _axis_lines(model, prefixes):
        if skip_comments and text.lstrip().startswith(("--", "//")):
            continue
        for hit in _NAMEOF_ANY.finditer(text):
            if hit.group("q") is None and quoted_only:
                continue
            owner = (hit.group("q") or hit.group("b")).replace("''", "'").strip()
            found.setdefault(owner, set()).add("'%s'[%s]" % (owner, hit.group("c").strip()))
    return found


def _qt(table: str) -> str:
    return "'" + table.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# C010 grain-guard-coverage
# ---------------------------------------------------------------------------


class GrainGuardCoverageRule(Rule):
    id = "C010"
    name = "grain-guard-coverage"
    severity = Severity.ERROR
    option_defaults = {"axis_prefixes": ["y-Selector", "y-Plot Specific"], "models": {}, "below": {}}
    description = (
        "Declared grain guards. 'models' (per model: guard_table, "
        "guard_measure, blocked_tables, permitted_tables, permitted_grains, "
        "guarded_ratios, reach_guard, reach_guard_overrides, guarded_counts, "
        "require_registered_columns): the fenced guard must name ISFILTERED "
        "of every blocked table and ISINSCOPE of every axis column of it; a "
        "permitted table is never blocked table-wide and its columns only "
        "member-conditionally (with SELECTEDVALUE); a permitted grain is "
        "never blocked; guarded ratios use the guard and no numeric floor; "
        "guarded counts use their reach guard. 'below' (model, host_table, "
        "guards {measure: [tables]}): each measure's guard names every axis "
        "column of the tables below its grain. Inert until configured."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        prefixes = list(self.options.get("axis_prefixes") or [])
        for cid, cfg in (self.options.get("models") or {}).items():
            for model in ctx.models:
                if ctx.model_matches(cfg.get("model"), model):
                    out.extend(self._cost(model, cid, cfg, prefixes))
        below = self.options.get("below") or {}
        if below:
            for model in ctx.models:
                if ctx.model_matches(below.get("model"), model):
                    out.extend(self._below(model, below, prefixes))
        return out

    def _cost(self, model, cid, cfg, prefixes) -> list[Violation]:
        out: list[Violation] = []
        host = model.get_table(cfg.get("guard_table", ""))
        guard = cfg.get("guard_measure", "")
        body = fenced_body(host, guard) if host else None

        def v(msg, obj=None, file=None, line=None):
            out.append(self.violation(f"{cid}: {msg}", file=file or (host.file if host else
                                                                       model.definition_path),
                                      line=line, obj=obj))

        if body is None:
            v(f"guard [{guard}] not declared (fenced) in {cfg.get('guard_table')}; every grain "
              f"check of this model fails until it is.", obj=guard)
            return out
        registered = axis_columns(model, prefixes, skip_comments=False)
        for table in cfg.get("blocked_tables") or []:
            if not term_present(body, "ISFILTERED", _qt(table)):
                v(f"(1) guard [{guard}] lacks ISFILTERED({_qt(table)}) for blocked table "
                  f"{table}.", obj=table)
            cols = registered.get(table, set())
            if not cols and cfg.get("require_registered_columns"):
                v(f"(2) no axis field parameter exposes a column of {_qt(table)}; check the "
                  f"parser or the field parameters.", obj=table)
            for col in sorted(cols):
                if not term_present(body, "ISINSCOPE", col):
                    v(f"(2) guard [{guard}] lacks ISINSCOPE({col}): an axis exposes this "
                      f"column of blocked table {table}.", obj=col)
        for table in cfg.get("permitted_tables") or []:
            for col in sorted(registered.get(table, set())):
                blocked = term_present(body, "ISINSCOPE", col) or term_present(body, "ISFILTERED", col)
                if blocked and not term_present(body, "SELECTEDVALUE", col):
                    v(f"(3) {col} of conformed table {table} is blocked without SELECTEDVALUE; "
                      f"a conformed column may only be blocked member-conditionally.", obj=col)
            if term_present(body, "ISFILTERED", _qt(table)):
                v(f"(4) guard [{guard}] blocks conformed table {table} table-wide with "
                  f"ISFILTERED({_qt(table)}); remove it.", obj=table)
        for grain in cfg.get("permitted_grains") or []:
            if term_present(body, "ISINSCOPE", grain) or term_present(body, "ISFILTERED", grain):
                v(f"(4b) guard [{guard}] blocks permitted grain {grain}; it must stay usable.",
                  obj=grain)
        floor = re.compile(r"\]\s?<\s?\d")
        for name in cfg.get("guarded_ratios") or []:
            m = host.measures.get(name) or next(
                (x for t in model.table_list for x in t.measure_list if x.name == name), None)
            if m is None:
                v(f"(5) guarded ratio [{name}] not found.", obj=name)
                continue
            if f"[{guard}]" not in m.expression:
                v(f"(5) ratio [{name}] does not consult the grain guard [{guard}].",
                  obj=name, file=m.file, line=m.line)
            if floor.search(m.expression):
                v(f"(5) ratio [{name}] hides small values with a numeric floor instead of the "
                  f"guard.", obj=name, file=m.file, line=m.line)
        overrides = cfg.get("reach_guard_overrides") or {}
        for name in cfg.get("guarded_counts") or []:
            reach = overrides.get(name, cfg.get("reach_guard"))
            m = next((x for t in model.table_list for x in t.measure_list if x.name == name), None)
            if m is None:
                v(f"(6) guarded count [{name}] not found.", obj=name)
            elif reach and f"[{reach}]" not in m.expression:
                v(f"(6) count [{name}] does not consult its reach guard [{reach}].",
                  obj=name, file=m.file, line=m.line)
        return out

    def _below(self, model, cfg, prefixes) -> list[Violation]:
        host = model.get_table(cfg.get("host_table", ""))
        if host is None:
            return []  # the guard host is absent: the check does not apply here
        try:
            lines = host.file.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError):
            return []
        registered = axis_columns(model, prefixes, skip_comments=True, quoted_only=True)
        out: list[Violation] = []
        for measure, tables in (cfg.get("guards") or {}).items():
            block = _block_until_lineage(lines, measure)
            guarded = set()
            for m in re.finditer(r"ISINSCOPE\s*\(\s*(?:'((?:[^']|'')+)'|([A-Za-z_]\w*))\s*\[([^\]]+)\]\s*\)",
                                 block or ""):
                table = (m.group(1) or m.group(2)).replace("''", "'")
                guarded.add(f"'{table}'[{m.group(3).strip()}]")
            for table in tables:
                cols = registered.get(table, set())
                if not cols:
                    out.append(self.violation(
                        f"[{measure}]: no axis field parameter registers a column of "
                        f"{_qt(table)}; the recogniser is broken, so this is not a pass.",
                        file=host.file, obj=f"{measure}/{table}",
                    ))
                for col in sorted(cols - guarded):
                    out.append(self.violation(
                        f"[{measure}] is below the grain of {table} but its guard lacks "
                        f"ISINSCOPE({col}).", file=host.file, obj=f"{measure}/{col}",
                    ))
        return out


def _block_until_lineage(lines: list[str], measure: str) -> Optional[str]:
    quoted = "'" + measure.replace("'", "''") + "'"
    for idx, line in enumerate(lines):
        s = line.strip()
        if s.startswith(f"measure {quoted} ") or s.startswith(f"measure {quoted}=") or \
                s.startswith(f"measure {measure} "):
            body = [line]
            for nxt in lines[idx + 1:]:
                if nxt.strip().startswith("lineageTag:"):
                    break
                body.append(nxt)
            return "\n".join(body)
    return None


# ---------------------------------------------------------------------------
# D012 dax-or-chain-depth
# ---------------------------------------------------------------------------

_VAR_CUT_RE = re.compile(r"\n(?=[ \t]*VAR[ \t]+\w+[ \t]*=)")


def worst_or_chain(expr: str) -> int:
    return max((chunk.count("||") for chunk in _VAR_CUT_RE.split(expr)), default=0)


class DaxOrChainDepthRule(Rule):
    id = "D012"
    name = "dax-or-chain-depth"
    severity = Severity.ERROR
    option_defaults = {"max_or_chain": 60, "or_chain_measures": []}
    description = (
        "Analysis Services lowers each || to a nested binary OR; a flat chain "
        "of more than max_or_chain (default 60) terms in one VAR deploys and "
        "then fails every query. The body is cut at each 'VAR name =' line "
        "and the worst chunk's || count is compared (raw count, strings and "
        "comments included). or_chain_measures restricts the rule to listed "
        "measures (default: every measure and calculated column)."
    )

    def check(self, ctx: Context) -> list[Violation]:
        limit = int(self.options.get("max_or_chain", 60))
        only = set(self.options.get("or_chain_measures") or [])
        out: list[Violation] = []
        for model in ctx.models:
            for b in model.dax_blocks():
                if b.kind not in ("measure", "calculated_column"):
                    continue
                if only and b.name not in only:
                    continue
                worst = worst_or_chain(b.expression)
                if worst > limit:
                    out.append(self.violation(
                        f"[{b.name}] has {worst} || in one VAR (limit {limit}); Analysis "
                        f"Services fails every query on such a chain. Split the terms across "
                        f"several VARs.", file=b.file, line=b.line, obj=b.label,
                    ))
        return out


# ---------------------------------------------------------------------------
# C011 grain-policy-exception
# ---------------------------------------------------------------------------


class GrainPolicyExceptionRule(Rule):
    id = "C011"
    name = "grain-policy-exception"
    severity = Severity.ERROR
    option_defaults = {"model": None, "helper": None, "guard": None, "policy_column": None,
                       "floor_min": 0.9, "floor_max_exclusive": 1.0}
    description = (
        "A narrow exception helper may forgive a population filter (a policy "
        "slicer) that trips the grain guard, but only if it stays narrow: the "
        "shared guard never mentions it; it declares VAR coverageFloor within "
        "[floor_min, floor_max_exclusive) and uses it after RETURN; it "
        "requires NOT ISINSCOPE(policy column); and it re-checks the guard "
        "with the policy filter removed and requires that re-check = 1. "
        "Reports nothing when the helper is not declared."
    )

    def check(self, ctx: Context) -> list[Violation]:
        o = self.options
        if not o.get("helper") or not o.get("guard"):
            return []
        out: list[Violation] = []
        for model in ctx.models:
            if not ctx.model_matches(o.get("model"), model):
                continue
            helper = next((t for t in model.table_list if o["helper"] in t.measures), None)
            if helper is None:
                continue
            body = fenced_body(helper, o["helper"]) or helper.measures[o["helper"]].expression
            guard_table = next((t for t in model.table_list if o["guard"] in t.measures), None)
            guard_body = (fenced_body(guard_table, o["guard"]) if guard_table else None) or ""

            def v(msg):
                m = helper.measures[o["helper"]]
                out.append(self.violation(msg, file=m.file, line=m.line, obj=m.full_name))

            tail = o["helper"].split(" ", 1)[1] if " " in o["helper"] else o["helper"]
            if tail in guard_body:
                v(f"the shared guard [{o['guard']}] mentions the exception helper "
                  f"[{o['helper']}]; keep the exception outside the guard.")
            after = body[body.rfind("RETURN"):] if "RETURN" in body else ""
            floor = re.search(r"VAR\s+coverageFloor\s*=\s*([0-9.]+)", body)
            if not floor:
                v(f"[{o['helper']}] declares no VAR coverageFloor = <number>.")
            else:
                value = float(floor.group(1))
                if not (float(o["floor_min"]) <= value < float(o["floor_max_exclusive"])):
                    v(f"[{o['helper']}] sets coverageFloor = {value}, outside "
                      f"[{o['floor_min']}, {o['floor_max_exclusive']}).")
                if "coverageFloor" not in after:
                    v(f"[{o['helper']}] declares coverageFloor but does not use it after RETURN.")
            column = o.get("policy_column") or ""
            if not re.search(r"NOT\s+ISINSCOPE\s*\(\s*" + re.escape(column) + r"\s*\)", body):
                v(f"[{o['helper']}] lacks NOT ISINSCOPE( {column} ); the exception must "
                  f"never admit the policy column on an axis.")
            recheck = re.search(
                r"VAR\s+(\w+)\s*=\s*CALCULATE\s*\(\s*\[" + re.escape(o["guard"]) +
                r"\]\s*,\s*REMOVEFILTERS\s*\(\s*" + re.escape(column) + r"\s*\)\s*\)", body)
            if not recheck:
                v(f"[{o['helper']}] has no VAR = CALCULATE( [{o['guard']}], REMOVEFILTERS( "
                  f"{column} ) ) re-check.")
            elif not re.search(re.escape(recheck.group(1)) + r"\s*=\s*1\b", after):
                v(f"[{o['helper']}] computes the re-check {recheck.group(1)} but does not "
                  f"require {recheck.group(1)} = 1 after RETURN; it would forgive more than "
                  f"the policy filter.")
        return out


# ---------------------------------------------------------------------------
# C009 reach-guard-helper-consistency
# ---------------------------------------------------------------------------

_ENGINE_RE = re.compile(
    r"ISFILTERED\s*\(\s*'((?:[^']|'')+)'\s*\)\s*&&\s*NOT\s+CALCULATE\s*\([^\n]*?,\s*REMOVEFILTERS\s*\(\s*\)"
    r"\s*,\s*VALUES\s*\(\s*'((?:[^']|'')+)'\s*\[([^\]]+)\]\s*\)\s*\)"
)
_WHOLE_TABLE_RE = re.compile(r"VALUES\s*\(\s*'(?:[^']|'')+'\s*\)")


class ReachGuardHelperConsistencyRule(Rule):
    id = "C009"
    name = "reach-guard-helper-consistency"
    severity = Severity.ERROR
    option_defaults = {"model": None, "host_table": None, "helpers": [], "min_filter_misses": 0,
                       "reference_helper": None, "canary": [], "exclusions": {},
                       "natural_keys": {}}
    description = (
        "Reach-guard helpers blank a fact's measures when the filter cannot "
        "reach the fact. Each repeats the per-dimension test ISFILTERED('T') "
        "&& NOT CALCULATE(..., REMOVEFILTERS(), VALUES('T'[key])); a "
        "dimension missing from one helper repeats the total on that family. "
        "All configured helpers must exist and list the same (table, key) "
        "pairs as the reference helper, cover every '_' dimension table "
        "(minus documented exclusions), key each table by the to-column of an "
        "active relationship (or its declared natural key), and never use a "
        "whole-table VALUES('T'). Inert until configured."
    )

    def check(self, ctx: Context) -> list[Violation]:
        o = self.options
        if not o.get("host_table") or not o.get("helpers"):
            return []
        out: list[Violation] = []
        for model in ctx.models:
            if ctx.model_matches(o.get("model"), model):
                out.extend(self._one(model))
        return out

    def _one(self, model: SemanticModel) -> list[Violation]:
        o = self.options
        host = model.get_table(o["host_table"])
        out: list[Violation] = []

        def v(msg, obj=None):
            out.append(self.violation(msg, file=host.file if host else model.definition_path, obj=obj))

        if host is None:
            v(f"host table '{o['host_table']}' not found.")
            return out
        pairs: dict[str, set[tuple[str, str]]] = {}
        for name in o["helpers"]:
            body = fenced_body(host, name)
            if body is None:
                v(f"helper [{name}] not found (fenced) in {host.name}.", obj=name)
                continue
            found = set()
            for m in _ENGINE_RE.finditer(body):
                t1, t2 = m.group(1).replace("''", "'"), m.group(2).replace("''", "'")
                if t1 != t2:
                    v(f"helper [{name}] tests ISFILTERED('{t1}') but takes VALUES of '{t2}'.", obj=name)
                found.add((t2, m.group(3).strip()))
            if _WHOLE_TABLE_RE.search(body):
                v(f"helper [{name}] uses a whole-table VALUES('T'); use the slicer key column.",
                  obj=name)
            pairs[name] = found
        misses = [n for n in pairs if n.startswith("-helper Filter Misses")]
        if len(misses) < int(o.get("min_filter_misses") or 0):
            v(f"only {len(misses)} Filter Misses helper(s) parsed; at least "
              f"{o['min_filter_misses']} expected.")
        canary = tuple(o.get("canary") or ())
        if canary:
            for name, found in pairs.items():
                if canary not in found:
                    v(f"helper [{name}] lacks the canary pair {canary[0]}[{canary[1]}]; the "
                      f"recogniser may be broken.", obj=name)
        ref_name = o.get("reference_helper")
        ref = pairs.get(ref_name, set()) if ref_name else set()
        for name, found in pairs.items():
            if name == ref_name or ref_name not in pairs:
                continue
            for t, k in sorted(ref - found):
                v(f"helper [{name}] misses {t}[{k}], which [{ref_name}] lists.", obj=name)
            for t, k in sorted(found - ref):
                v(f"helper [{name}] lists {t}[{k}], which [{ref_name}] does not.", obj=name)
        exclusions = set((o.get("exclusions") or {}).keys())
        dims = {p.stem for p in (model.definition_path / "tables").glob("*.tmdl")
                if p.stem.startswith("_") and not p.stem.startswith("__")} - exclusions
        listed = {t for t, _k in ref}
        for t in sorted(dims - listed):
            v(f"dimension {t} is not listed in the reach-guard helpers.", obj=t)
        for t in sorted(listed - dims):
            v(f"helpers list {t}, which is not a dimension table (or is excluded).", obj=t)
        natural = o.get("natural_keys") or {}
        for t, k in sorted(ref):
            incoming = {r.to_column for r in model.relationships if r.is_active and r.to_table == t}
            if incoming:
                if k not in incoming:
                    v(f"{t}[{k}] is not the to-column of an active relationship into {t} "
                      f"({', '.join(sorted(incoming))}).", obj=f"{t}[{k}]")
            elif natural.get(t) != k:
                v(f"{t} has no incoming active relationship; its helpers must use the declared "
                  f"natural key ({natural.get(t, 'none declared')}), not {k}.", obj=f"{t}[{k}]")
        return out


# ---------------------------------------------------------------------------
# The `grain` command: derive blocked and conformed dimensions from the graph
# ---------------------------------------------------------------------------

#: The fact the cost side reads and the facts the population side reads, when
#: the caller names none.
DEFAULT_COST_FACT = "Campaigns"
DEFAULT_BACKEND_FACTS = ("_Users", "Transactions")

_USEREL_RE = re.compile(
    r"USERELATIONSHIP\s*\(\s*(?:'((?:[^']|'')+)'|([A-Za-z_][\w ]*?))\s*\[[^\]]*\]\s*,"
    r"\s*(?:'((?:[^']|'')+)'|([A-Za-z_][\w ]*?))\s*\[[^\]]*\]\s*\)",
    re.IGNORECASE,
)


def propagation_graph(model: SemanticModel) -> dict[str, set[str]]:
    """Filter steps: one side -> many side of every active relationship, the
    reverse too when it filters both ways, and a step for each
    USERELATIONSHIP that involves a calendar (a table named ``__...``)."""
    steps: dict[str, set[str]] = {}

    def add(a: str, b: str) -> None:
        steps.setdefault(a, set()).add(b)

    for r in model.relationships:
        if r.is_active:
            add(r.to_table, r.from_table)
            if r.cross_filtering.lower() == "bothdirections":
                add(r.from_table, r.to_table)
    by_pair = {frozenset((r.from_table, r.to_table)): r for r in model.relationships}
    texts = []
    for table in model.table_list:
        try:
            texts.append(table.file.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError):
            pass
    for hit in (h for text in texts for h in _USEREL_RE.finditer(text)):
        left = (hit.group(1) or hit.group(2) or "").replace("''", "'").strip()
        right = (hit.group(3) or hit.group(4) or "").replace("''", "'").strip()
        if "__" not in (left[:2], right[:2]):
            continue  # only calendar activations add a step
        known = by_pair.get(frozenset((left, right)))
        if known is None:
            add(left, right)
        else:
            add(known.to_table, known.from_table)
    return steps


def _reach(steps: dict[str, set[str]], start: str) -> set[str]:
    """Tables a filter on ``start`` reaches. The table itself counts as
    reached: a dimension that is also a fact filters that fact."""
    seen, todo = {start}, [start]
    while todo:
        for nxt in steps.get(todo.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen


def grain_verdicts(model: SemanticModel, cost_fact: str, backend_facts: list[str],
                   permit: list[str] = (), axis_prefixes: Optional[list[str]] = None) -> list[dict]:
    steps = propagation_graph(model)
    exposed = axis_columns(model, axis_prefixes or ["y-Selector", "y-Plot Specific"], skip_comments=False)
    dims = sorted({t for r in model.relationships for t in (r.from_table, r.to_table)
                   if t.startswith("_") or t.startswith("z-")})
    rows = []
    for d in dims:
        reached = _reach(steps, d)
        cost = cost_fact in reached
        backend = [b for b in backend_facts if b in reached]
        if d in permit or (cost and len(backend) == len(backend_facts)):
            verdict = "CONFORMED"
        elif cost and backend:
            verdict = "partial"
        elif cost:
            verdict = "cost-only"
        elif backend:
            verdict = "backend-only"
        else:
            verdict = "neither"
        rows.append({"dimension": d, "reaches_cost": cost, "backend_reached": backend,
                     "verdict": verdict, "exposed_columns": sorted(exposed.get(d, set()))})
    return rows


def grain_gaps(model: SemanticModel, rows: list[dict], guard_table: str,
               guard_measure: str) -> tuple[Optional[str], list[str]]:
    """``(error, gaps)`` of a guard against the derived verdicts."""
    host = model.get_table(guard_table)
    body = fenced_body(host, guard_measure) if host else None
    if body is None:
        return (f"guard measure {guard_measure!r} not found in {guard_table}.tmdl "
                f"(fenced form expected)"), []
    gaps = []
    for row in rows:
        d = row["dimension"]
        if row["verdict"] == "CONFORMED":
            continue
        if d.startswith("z-") or not row["exposed_columns"]:
            continue
        if not term_present(body, "ISFILTERED", _qt(d)):
            gaps.append(f"{d}: no table-level ISFILTERED")
        for col in row["exposed_columns"]:
            if not term_present(body, "ISINSCOPE", col):
                gaps.append(f"{d}: axis column {col} has no ISINSCOPE term")
    for row in rows:
        d = row["dimension"]
        if row["verdict"] == "CONFORMED" and term_present(body, "ISFILTERED", _qt(d)):
            gaps.append(f"{d}: conformed table is blocked table-wide — that blanks the headline "
                        f"ratios (column-level ISINSCOPE terms on it are rate-eligibility rulings "
                        f"and stay allowed)")
    return None, gaps
