"""Declared DAX contracts. IDs C005-C008.

Each rule here pins one deliberate DAX shape a team relies on and that
nothing else would catch: which tables a scoping helper may name, ratios that
must wrap a window guard, flag predicates that must match their column type,
and a filter that must stay on one arm of a blended measure. All of them are
inert until configured, and scoped by an optional ``model`` option (the
``*.SemanticModel`` folder relative to the scanned root).
"""

from __future__ import annotations

import re
from fnmatch import fnmatchcase
from typing import Optional

from ..model import Measure, SemanticModel
from .base import Context, Rule, Severity, Violation


def _live_lines(expr: str) -> list[str]:
    return [ln for ln in expr.split("\n")
            if not ln.strip().startswith(("--", "//", "///"))]


def _names_table(expr: str, table: str) -> bool:
    body = "\n".join(_live_lines(expr))
    return f"'{table}'" in body or f"{table}[" in body


def _measure(model: SemanticModel, table: str, name: str) -> Optional[Measure]:
    t = model.get_table(table)
    return t.measures.get(name) if t else None


def _ws(text: str) -> str:
    """Regex for literal text with flexible whitespace around punctuation."""
    out = []
    for ch in text:
        if ch.isspace():
            out.append(r"\s*")
        elif ch in "()[]{},=":
            out.append(r"\s*" + re.escape(ch) + r"\s*")
        else:
            out.append(re.escape(ch))
    return "".join(out)


# ---------------------------------------------------------------------------
# C005 measure-reference-contract
# ---------------------------------------------------------------------------


class MeasureReferenceContractRule(Rule):
    id = "C005"
    name = "measure-reference-contract"
    severity = Severity.ERROR
    option_defaults = {"contracts": []}
    description = (
        "Declared scoping contracts between measures: must_not_reference (a "
        "helper never names the listed tables), must_reference (a companion "
        "helper exists and names them all), co_reference (consumers that "
        "blank on one helper's literal also consult its partner) and "
        "must_not_divide (ratios divide a masked base, never the raw "
        "measure). A table is 'named' by 'Table' or Table[ outside comment "
        "lines. A contract applies only to models that hold its anchor. A "
        "contract that names a template model or a minimum universe is "
        "checked against the models that declare its anchor: fewer than the "
        "minimum, or the template missing, means discovery is broken."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for c in self.options.get("contracts") or []:
            models = [m for m in ctx.models if ctx.model_matches(c.get("model"), m)]
            out.extend(self._universe(ctx, c, models))
            for model in models:
                out.extend(self._one(model, c))
        return out

    def _universe(self, ctx: Context, c: dict, models: list[SemanticModel]) -> list[Violation]:
        """A contract that names a template model and a minimum universe needs
        that many models to declare its anchor, the template among them."""
        template = c.get("template")
        floor = c.get("min_universe")
        if not template and floor is None:
            return []
        anchor = c.get("anchor") or c.get("measure")
        if not anchor:
            return []
        universe = [m for m in models if m.find_measures(anchor)]
        template_found = any(ctx.model_matches(template, m) for m in universe)
        if len(universe) >= int(floor or 0) and (not template or template_found):
            return []
        return [self.violation(
            f"universe check: found {len(universe)} model(s) declaring [{anchor}]"
            + ("" if template_found else " and not the template")
            + "; discovery is broken, so the contract would pass vacuously.",
            file=models[0].definition_path if models else None,
            obj=anchor,
        )]

    def _one(self, model: SemanticModel, c: dict) -> list[Violation]:
        kind = c.get("kind")
        table, name = c.get("table", ""), c.get("measure", "")
        if kind == "must_not_reference":
            m = _measure(model, table, name)
            if m is None:
                return []
            bad = [t for t in c.get("tables") or [] if _names_table(m.expression, t)]
            if not bad:
                return []
            return [self.violation(
                f"{table}[{name}] must not reference {', '.join(bad)}: it would blank "
                f"every consumer on those rows.",
                file=m.file, line=m.line, obj=m.full_name,
            )]
        if kind == "must_reference":
            anchor = c.get("anchor")
            if anchor and not model.find_measures(anchor):
                return []
            m = _measure(model, table, name)
            if m is None:
                if not anchor:
                    return []
                t = model.get_table(table)
                return [self.violation(
                    f"{table}[{name}] must reference {', '.join(c.get('tables') or [])}, but "
                    f"the measure does not exist.",
                    file=t.file if t else model.definition_path, obj=f"{table}[{name}]",
                )]
            missing = [t for t in c.get("tables") or [] if not _names_table(m.expression, t)]
            if not missing:
                return []
            return [self.violation(
                f"{table}[{name}] must reference {', '.join(missing)} (comment lines do not "
                f"count).", file=m.file, line=m.line, obj=m.full_name,
            )]
        if kind == "co_reference":
            if not model.find_measures(name):
                return []
            t = model.get_table(table)
            if t is None:
                return []
            literal, partner = c.get("literal", ""), c.get("partner", "")
            pattern = re.compile(r"\[" + re.escape(name) + r"\]\s*=\s*\"" + re.escape(literal) + r"\"")
            follow = re.compile(r"\s*\|\|\s*\[" + re.escape(partner) + r"\]")
            out = []
            for m in t.measure_list:
                body = "\n".join(_live_lines(m.expression))
                bare = sum(1 for hit in pattern.finditer(body) if not follow.match(body, hit.end()))
                if bare:
                    out.append(self.violation(
                        f"{table}[{m.name}] blanks on [{name}] = \"{literal}\" without also "
                        f"consulting [{partner}] ({bare} occurrence(s)).",
                        file=m.file, line=m.line, obj=m.full_name,
                    ))
            return out
        if kind == "must_not_divide":
            t = model.get_table(table)
            if t is None:
                return []
            raw = c.get("raw", c.get("raw_measure", ""))
            glob = c.get("measure_glob", c.get("measures", "*"))
            pattern = re.compile(r"(?<!\^)DIVIDE\s*\(\s*\[" + re.escape(raw) + r"\]", re.IGNORECASE)
            return [
                self.violation(
                    f"{table}[{m.name}] divides the raw [{raw}]; divide the masked base "
                    f"measure instead.", file=m.file, line=m.line, obj=m.full_name,
                )
                for m in t.measure_list
                if fnmatchcase(m.name, glob) and pattern.search("\n".join(_live_lines(m.expression)))
            ]
        return [self.violation(f"unknown contract kind {kind!r}.", file=model.definition_path)]


# ---------------------------------------------------------------------------
# C006 guarded-ratio-wrapper
# ---------------------------------------------------------------------------


class GuardedRatioWrapperRule(Rule):
    id = "C006"
    name = "guarded-ratio-wrapper"
    severity = Severity.ERROR
    option_defaults = {
        "model": None, "host_table": None, "selector_table": None, "numerators": [],
        "guard": None, "boundary": None, "measured_option": None, "enhanced_option": None,
        "count_measure": None, "min_measures": 0, "canary_counts": [], "canary_ratios": [],
    }
    description = (
        "When an attribution selector re-allocates counts only from a "
        "boundary date, a cost-per-count ratio over an earlier window divides "
        "all cost by the post-boundary count: plausible and wrong. Every such "
        "ratio (DIVIDE([numerator], [count]) where the count measure reads "
        "the selector) must start with IF([guard], BLANK(), ...); the guard "
        "must be inert on the measured option and use the boundary; the "
        "boundary must be derived, never a hard-coded DATE(). A recogniser "
        "self-test guards against passing vacuously. Inert until configured."
    )

    def check(self, ctx: Context) -> list[Violation]:
        o = self.options
        if not o.get("host_table") or not o.get("guard"):
            return []
        out: list[Violation] = []
        for model in ctx.models:
            if ctx.model_matches(o.get("model"), model):
                out.extend(self._one(model))
        return out

    def _one(self, model: SemanticModel) -> list[Violation]:
        o = self.options
        table = model.get_table(o["host_table"])
        if table is None:
            return [self.violation(f"host table '{o['host_table']}' not found; the guarded-ratio "
                                   f"recogniser has nothing to read.", file=model.definition_path)]
        bodies = {m.name: "\n".join(_live_lines(m.expression)).strip() for m in table.measure_list}
        selector = o.get("selector_table") or ""
        counts = {n for n, b in bodies.items() if n.rstrip().endswith("#") and selector in b}
        nums = "|".join(re.escape(n) for n in o.get("numerators") or [])
        ratio_re = re.compile(r"DIVIDE\s*\(\s*\[\s*(?:" + nums + r")\s*\]\s*,\s*\[\s*([^\]]+?)\s*\]",
                              re.IGNORECASE)
        ratios = {n for n, b in bodies.items()
                  if nums and any(x.strip() in counts for x in ratio_re.findall(b))}
        out: list[Violation] = []

        def v(msg: str, name: Optional[str] = None) -> None:
            m = table.measures.get(name) if name else None
            out.append(self.violation(msg, file=table.file, line=m.line if m else None,
                                      obj=m.full_name if m else table.name))

        floor = int(o.get("min_measures") or 0)
        if len(bodies) <= floor:
            v(f"recogniser self-test: only {len(bodies)} measure(s) parsed from {table.name} "
              f"(more than {floor} expected).")
        for name in o.get("canary_counts") or []:
            if name not in counts:
                v(f"recogniser self-test: canary count measure [{name}] was not recognised.")
        for name in o.get("canary_ratios") or []:
            if name not in ratios:
                v(f"recogniser self-test: canary ratio [{name}] was not recognised.")
        guard, boundary = o["guard"], o.get("boundary")
        wrapper = re.compile(r"^IF\s*\(\s*\[" + re.escape(guard) + r"\]\s*,\s*BLANK\s*\(\s*\)\s*,",
                             re.IGNORECASE)
        for name in sorted(ratios):
            if not wrapper.match(bodies[name]):
                v(f"[{name}] divides by a re-allocated count but is not wrapped in "
                  f"IF ( [{guard}], BLANK (), ... ); it shows a wrong ratio outside the window.",
                  name)
        gbody = bodies.get(guard)
        if gbody is None:
            v(f"guard measure [{guard}] does not exist.")
        else:
            measured = re.compile(r"_basis\s*=\s*\"" + re.escape(o.get("measured_option") or "")
                                  + r"\"\s*,\s*FALSE\s*\(\s*\)", re.IGNORECASE)
            if selector not in gbody:
                v(f"guard [{guard}] does not read the selector {selector}.", guard)
            if not measured.search(gbody):
                v(f"guard [{guard}] is not inert on the measured option "
                  f"\"{o.get('measured_option')}\".", guard)
            if boundary and f"[{boundary}]" not in gbody:
                v(f"guard [{guard}] does not use the boundary [{boundary}].", guard)
        if boundary:
            bbody = bodies.get(boundary)
            if bbody is None:
                v(f"boundary measure [{boundary}] does not exist.")
            else:
                if re.search(r"\bDATE\s*\(", bbody, re.IGNORECASE):
                    v(f"boundary [{boundary}] is hard-coded with DATE(); derive it from the data.",
                      boundary)
                if f"\"{o.get('enhanced_option')}\"" not in bbody:
                    v(f"boundary [{boundary}] does not name the option \"{o.get('enhanced_option')}\".",
                      boundary)
                if o.get("count_measure") and f"[{o['count_measure']}]" not in bbody:
                    v(f"boundary [{boundary}] does not use [{o['count_measure']}].", boundary)
        for helper in (guard, boundary):
            if helper and helper in ratios:
                v(f"[{helper}] is itself a cost ratio; guards must not be guarded ratios.", helper)
        return out


# ---------------------------------------------------------------------------
# C007 typed-flag-predicates
# ---------------------------------------------------------------------------

_BOOL_LITERALS = {"TRUE", "FALSE", "TRUE()", "FALSE()"}


class TypedFlagPredicatesRule(Rule):
    id = "C007"
    name = "typed-flag-predicates"
    severity = Severity.ERROR
    option_defaults = {
        "model": None, "table": None, "prefix": None, "measures_files": [],
        "min_predicates": 0, "canaries": [],
    }
    description = (
        "Flag columns that share a prefix can be counts (int64) or booleans. "
        "'= 1' on a count drops every row with two or more events; '> 0' on a "
        "boolean is coerced silently. Count flags must be compared with > 0 "
        "or = 0 and never to a boolean; boolean flags never to a number. A "
        "recogniser self-test (minimum predicates, canaries, both flag types "
        "parsed) guards against passing vacuously. Inert until configured."
    )

    def check(self, ctx: Context) -> list[Violation]:
        o = self.options
        if not o.get("table") or not o.get("prefix"):
            return []
        out: list[Violation] = []
        for model in ctx.models:
            if ctx.model_matches(o.get("model"), model):
                out.extend(self._one(model))
        return out

    def _one(self, model: SemanticModel) -> list[Violation]:
        o = self.options
        prefix = o["prefix"]
        table = model.get_table(o["table"])
        flags = {c.name: (c.data_type or "") for c in (table.column_list if table else [])
                 if c.name.startswith(prefix)}
        pattern = re.compile(
            r"(" + re.escape(prefix) + r"[a-z_]+)\s*\]\s*(<>|>=|<=|=|>|<)\s*"
            r"([A-Za-z0-9_]+(?:\s*\(\s*\))?)"
        )
        found: list[tuple] = []
        for tname in o.get("measures_files") or []:
            t = model.get_table(tname)
            if t is None:
                continue
            try:
                lines = t.file.read_text(encoding="utf-8-sig").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for n, ln in enumerate(lines, start=1):
                if ln.strip().startswith(("///", "--", "//")):
                    continue
                for m in pattern.finditer(ln):
                    literal = re.sub(r"\s+", "", m.group(3))
                    found.append((m.group(1), m.group(2), literal, t.file, n))
        out: list[Violation] = []
        where = table.file if table else model.definition_path

        def self_test(msg):
            out.append(self.violation(f"recogniser self-test: {msg}", file=where))

        if len(found) < int(o.get("min_predicates") or 0):
            self_test(f"only {len(found)} flag predicate(s) found, fewer than {o.get('min_predicates')}.")
        seen = {(c, op, lit.upper()) for c, op, lit, _f, _n in found}
        seen |= {(c, op, lit.rstrip("()").upper()) for c, op, lit, _f, _n in found}
        for canary in o.get("canaries") or []:
            col, op, lit = canary
            if (col, op, str(lit).upper()) not in seen:
                self_test(f"canary predicate {col} {op} {lit} was not found.")
        ints = {c for c, t in flags.items() if t.lower() == "int64"}
        bools = {c for c, t in flags.items() if t.lower() == "boolean"}
        if not flags or not ints or not bools:
            self_test(f"flag columns not parsed (int64: {len(ints)}, boolean: {len(bools)}).")
        for col, op, lit, f, n in found:
            if col in ints and (
                (op in ("=", "<>") and lit.isdigit() and int(lit) >= 1) or lit.upper() in _BOOL_LITERALS
            ):
                out.append(self.violation(
                    f"{col} is a count (int64) compared with {op} {lit}; rows with more than one "
                    f"event drop out. Use > 0 or = 0.", file=f, line=n, obj=col,
                ))
            elif col in bools and lit.isdigit():
                out.append(self.violation(
                    f"{col} is a boolean compared with {op} {lit}; use = TRUE or = FALSE.",
                    file=f, line=n, obj=col,
                ))
        return out


# ---------------------------------------------------------------------------
# C008 measure-arm-scoped-filter
# ---------------------------------------------------------------------------

_ARM_OPENERS = [
    (re.compile(r'^"search_term"\s*,'), "search_term"),
    (re.compile(r'^"keyword"\s*,'), "keyword"),
    (re.compile(r'^"ad"\s*,'), "ad"),
    (re.compile(r'^"campaign"\s*,'), "campaign"),
    (re.compile(r"^VAR\s+searchterms\s*=", re.IGNORECASE), "search_term"),
    (re.compile(r"^VAR\s+keyword\s*=", re.IGNORECASE), "keyword"),
    (re.compile(r"^VAR\s+adslevel\s*=", re.IGNORECASE), "ad"),
    (re.compile(r"^VAR\s+campaign\s*=", re.IGNORECASE), "campaign"),
]
_ARM_CLOSERS = re.compile(r"^(?:VAR\s+\w+\s*=|RETURN\b|BLANK\s*\(\s*\)\s*$)", re.IGNORECASE)


class MeasureArmScopedFilterRule(Rule):
    id = "C008"
    name = "measure-arm-scoped-filter"
    severity = Severity.ERROR
    option_defaults = {
        "template": None, "measure": None, "host_table": None, "column": None,
        "target_arm": "search_term", "literals": [], "forbidden_literal": None,
    }
    description = (
        "A measure that blends grains in arms (search term, keyword, ad, "
        "campaign) may need a filter on one arm only: KEEPFILTERS(NOT "
        "column IN {literals}) must sit on the target arm, the column must "
        "not be mentioned in any other arm, the literal set must be exactly "
        "the configured one, and a forbidden literal must never appear. The "
        "universe is the template plus every model declaring the measure; "
        "fewer than two models means discovery is broken. Inert until "
        "configured."
    )

    def check(self, ctx: Context) -> list[Violation]:
        o = self.options
        if not o.get("measure") or not o.get("host_table") or not o.get("column"):
            return []
        out: list[Violation] = []
        universe = []
        template_found = False
        for model in ctx.models:
            m = _measure(model, o["host_table"], o["measure"])
            is_template = ctx.model_matches(o.get("template"), model) if o.get("template") else False
            if m is not None:
                universe.append((model, m))
                template_found |= is_template
        if len(universe) < 2 or (o.get("template") and not template_found):
            out.append(self.violation(
                f"universe check: found {len(universe)} model(s) declaring "
                f"{o['host_table']}[{o['measure']}]" + ("" if template_found else " and not the template")
                + "; discovery is broken, so the arm checks would pass vacuously.",
            ))
        for model, m in universe:
            out.extend(self._one(m))
        return out

    def _one(self, m: Measure) -> list[Violation]:
        o = self.options
        target = o.get("target_arm") or "search_term"
        column = o["column"]
        guard_re = re.compile(
            r"KEEPFILTERS\s*\(\s*NOT\s+" + _ws(column) + r"\s+IN\s*\{(?P<lits>[^}]*)\}\s*\)",
            re.IGNORECASE,
        )
        col_re = re.compile(_ws(column), re.IGNORECASE)
        arm: Optional[str] = None
        guards: list[tuple[Optional[str], str]] = []
        stray: list[str] = []
        lines = m.expression.split("\n")
        for ln in lines:
            s = ln.strip()
            if s.startswith(("///",)):
                continue
            for opener, name in _ARM_OPENERS:
                if opener.match(s):
                    arm = name
                    break
            else:
                if _ARM_CLOSERS.match(s):
                    arm = None
            for g in guard_re.finditer(ln):
                guards.append((arm, g.group("lits")))
            if col_re.search(ln) and arm != target:
                stray.append(arm or "outside any arm")
        out: list[Violation] = []

        def v(msg: str) -> None:
            out.append(self.violation(msg, file=m.file, line=m.line, obj=m.full_name))

        if not guards:
            v(f"{m.full_name} has no KEEPFILTERS(NOT {column} IN {{...}}) guard; the "
              f"{target} arm must carry it.")
        elif not any(a == target for a, _l in guards):
            v(f"{m.full_name}: the guard is missing from the {target} arm.")
        for where in sorted(set(stray)):
            v(f"{m.full_name}: {column} is used in the '{where}' arm; it belongs on the "
              f"{target} arm only.")
        wanted = {x.lower() for x in o.get("literals") or []}
        for _arm, lits in guards:
            got = {x.strip().strip('"').strip().lower() for x in lits.split(",") if x.strip()}
            if wanted and got != wanted:
                v(f"{m.full_name}: the guard's literal set {sorted(got)} differs from "
                  f"{sorted(wanted)}.")
        forbidden = o.get("forbidden_literal")
        if forbidden and forbidden.lower() in m.expression.lower():
            v(f"{m.full_name} mentions the forbidden literal \"{forbidden}\".")
        return out
