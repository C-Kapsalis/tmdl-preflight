"""Model organisation: where measures live and which tables carry data.
IDs O0xx (plus S003 format-inference-naming).

The placement rules encode one team's naming conventions, so they are
opt-in: they run only when selected by id or name. Every name decision goes
through the shared classifier in ``measure_classes`` and every fact decision
through ``roles``.
"""

from __future__ import annotations

import re
from typing import Optional

from ..dax import strip_comments
from ..measure_classes import DEFAULTS as CLASS_DEFAULTS
from ..measure_classes import classify_measure_name
from ..ratchet import RatchetFileError, entry_for, load_floors
from ..roles import fact_tables, field_parameter_tables, is_field_parameter_table, surfaced_measures
from .base import Context, Rule, Severity, Violation


def _class_options(rule: Rule) -> dict:
    opts = {k: rule.options[k] for k in CLASS_DEFAULTS if k in rule.options}
    return opts


# ---------------------------------------------------------------------------
# O001: helpers in user-only (#) tables
# ---------------------------------------------------------------------------


class UserOnlyTablePurityRule(Rule):
    id = "O001"
    name = "user-only-table-purity"
    severity = Severity.WARNING
    opt_in = True
    option_defaults = {"user_only_table_prefix": "#", "user_facing_letters": ["z"]}
    description = (
        "Tables whose name starts with the user-only prefix (default '#') are "
        "meant to hold only measures report authors drag onto visuals. A "
        "helper measure there (by name: '-helper ...', 'i-...', '_...', a "
        "'test' measure) pollutes the field list. Opt-in; nothing fails in "
        "Power BI."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        prefix = self.options["user_only_table_prefix"]
        for model in ctx.models:
            for t in model.table_list:
                if not t.name.startswith(prefix):
                    continue
                for m in t.measure_list:
                    c = classify_measure_name(m.name, _class_options(self))
                    if c.is_helper:
                        out.append(self.violation(
                            f"helper measure {t.name}[{m.name}] [{c.subcategory}] sits in "
                            f"a user-only table; move it to the table for its kind, or "
                            f"rename it if it is really meant for report authors.",
                            file=m.file, line=m.line, obj=m.full_name,
                        ))
        return out


# ---------------------------------------------------------------------------
# O002: helpers in the table their kind belongs to
# ---------------------------------------------------------------------------

_GUIDANCE = {
    "measure_helper": "the helper table",
    "visual_helper": "the helper table or a visual (w-) table",
    "diagnostic_helper": "a helper or diagnostic table",
    "slicer_helper": "the slicer table or a visual (w-) table",
    "intermediary_helper": "a '<Domain> Measures' table next to the measures it feeds",
    "test_measure": "a helper or diagnostic table",
}


class HelperMeasurePlacementRule(Rule):
    id = "O002"
    name = "helper-measure-placement"
    severity = Severity.WARNING
    opt_in = True
    option_defaults = {
        "helper_table": "Helper Measures",
        "slicer_table": "f-Filters",
        "visual_table_prefix": "w-",
        "field_parameter_prefixes": [],
        "user_facing_letters": ["z"],
        "user_only_table_prefix": "#",
        "dimension_prefix": "_",
        "profile": "strict",
        "helper_marker": "Helper",
        "diagnostic_marker": "Diagnostic",
    }
    description = (
        "Each helper measure belongs in a table for its kind: measure helpers "
        "in the helper table, visual helpers there or in a w- table, "
        "diagnostics in a helper or diagnostic table, slicer helpers in the "
        "slicer table, intermediary helpers in a measures table. Profile "
        "'strict' (warnings) also bans helpers from user-only (#) and "
        "dimension (_) tables and exempts field-parameter tables; profile "
        "'lenient' (infos) judges only slicer, '-helper', visual and "
        "diagnostic helpers. Opt-in; the symptom is a confusing field list."
    )

    def _allowed(self, sub: str, host: str) -> bool:
        o = self.options
        helper, visual = o["helper_table"], o["visual_table_prefix"]
        h_mark, d_mark = o["helper_marker"], o["diagnostic_marker"]
        if sub == "measure_helper":
            return host == helper
        if sub == "visual_helper":
            return host == helper or host.startswith(visual)
        if sub in ("diagnostic_helper", "test_measure"):
            return h_mark in host or d_mark in host
        if sub == "slicer_helper":
            return host == o["slicer_table"] or host.startswith(visual)
        if sub == "intermediary_helper":
            return "Measure" in host or host.startswith(visual)
        return True

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        o = self.options
        lenient = o.get("profile") == "lenient"
        for model in ctx.models:
            for t in model.table_list:
                host = t.name
                for m in t.measure_list:
                    c = classify_measure_name(m.name, _class_options(self))
                    if not c.is_helper:
                        continue
                    sub = c.subcategory or "unknown_helper"
                    if lenient:
                        judged = sub in ("slicer_helper", "visual_helper", "diagnostic_helper") or (
                            sub == "measure_helper" and m.name.startswith(CLASS_DEFAULTS["strict_helper_prefix"])
                        )
                        if not judged or self._allowed(sub, host):
                            continue
                        out.append(self.violation(
                            f"{host}[{m.name}] [{sub}] (expected: {_GUIDANCE[sub]})",
                            file=m.file, line=m.line, obj=m.full_name, severity=Severity.INFO,
                        ))
                        continue
                    if host.startswith(o["user_only_table_prefix"]) or host.startswith(o["dimension_prefix"]):
                        reason = "user-only" if host.startswith(o["user_only_table_prefix"]) else "dimension"
                        out.append(self.violation(
                            f"{host}[{m.name}] [{sub}] is a helper in a {reason} table; move it "
                            f"to {_GUIDANCE.get(sub, 'a helper table')}.",
                            file=m.file, line=m.line, obj=m.full_name,
                        ))
                        continue
                    if any(host.startswith(p) for p in o["field_parameter_prefixes"]):
                        continue
                    if not self._allowed(sub, host):
                        out.append(self.violation(
                            f"{host}[{m.name}] [{sub}] is in the wrong table; move it to "
                            f"{_GUIDANCE.get(sub, 'a helper table')}.",
                            file=m.file, line=m.line, obj=m.full_name,
                        ))
        return out


# ---------------------------------------------------------------------------
# O003: user-facing measures parked in helper or dimension tables
# ---------------------------------------------------------------------------


class UserFacingInHelperTablesRule(Rule):
    id = "O003"
    name = "user-facing-in-helper-tables"
    severity = Severity.WARNING
    opt_in = True
    option_defaults = {
        "helper_table_prefixes": ["f-", "w-", "i-"],
        "dimension_prefix": "_",
        "user_facing_letters": ["z"],
    }
    description = (
        "A user-facing measure (by name) should not live in a dimension (_) "
        "table or a helper table (f-, w-, i- by default): report authors do "
        "not find it there, and it often gets hidden with the scaffolding "
        "around it. z- tables, user-only tables, measure containers, facts "
        "and field-parameter tables may host anything. Opt-in."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        prefixes = [self.options["dimension_prefix"], *self.options["helper_table_prefixes"]]
        for model in ctx.models:
            for t in model.table_list:
                if not any(t.name.startswith(p) for p in prefixes) or is_field_parameter_table(t):
                    continue
                for m in t.measure_list:
                    if classify_measure_name(m.name, _class_options(self)).is_user_facing:
                        out.append(self.violation(
                            f"user-facing measure {t.name}[{m.name}] sits in a helper or "
                            f"dimension table; move it to a user-only or '<Domain> "
                            f"Measures' table.",
                            file=m.file, line=m.line, obj=m.full_name,
                        ))
        return out


# ---------------------------------------------------------------------------
# O004: user-facing measures homed on fact tables
# ---------------------------------------------------------------------------


class MeasuresInFactTablesRule(Rule):
    id = "O004"
    name = "measures-in-fact-tables"
    severity = Severity.WARNING
    opt_in = True
    option_defaults = {
        "surfacing_tables": [],
        "internal_name_tokens": [],
        "diagnostic_tokens": ["countrows", "count ", "diagnostic", "debug", "helper"],
    }
    description = (
        "Fact tables should hold data. A user-facing measure on a fact (one a "
        "field parameter surfaces, or a visible measure whose name is not a "
        "diagnostic, test, helper or lowercase name) is a warning; any other "
        "measure on a fact is listed as info with the reason it was not "
        "counted. Facts follow the shared table-role law. Opt-in."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        diag = [t.lower() for t in self.options["diagnostic_tokens"]]
        internal = [t.lower() for t in self.options["internal_name_tokens"]]
        for model in ctx.models:
            surfaced = surfaced_measures(model, self.options["surfacing_tables"] or None)
            for name in fact_tables(model):
                t = model.tables[name]
                for m in t.measure_list:
                    low = m.name.lower()
                    tags = []
                    if m.is_hidden:
                        tags.append("hidden")
                    if low.startswith("test"):
                        tags.append("test")
                    if m.name.startswith("-") or "helper" in low:
                        tags.append("helper")
                    if any(d in low for d in diag if d != "helper"):
                        tags.append("diagnostic")
                    if m.name[:1].islower():
                        tags.append("lowercase")
                    if any(tok in low for tok in internal):
                        tags.append("internal")
                    if m.name in surfaced or not tags:
                        why = "a field parameter surfaces it" if m.name in surfaced else "it is visible"
                        out.append(self.violation(
                            f"user-facing measure {t.name}[{m.name}] is homed on a fact "
                            f"table ({why}); move it into a measures table.",
                            file=m.file, line=m.line, obj=m.full_name,
                        ))
                    else:
                        out.append(self.violation(
                            f"{t.name}[{m.name}] [{', '.join(tags)}] sits on a fact table "
                            f"(advisory).",
                            file=m.file, line=m.line, obj=m.full_name, severity=Severity.INFO,
                        ))
        return out


# ---------------------------------------------------------------------------
# O005, O006, S003: advisory listings
# ---------------------------------------------------------------------------


class MeasuresInDimensionTablesRule(Rule):
    id = "O005"
    name = "measures-in-dimension-tables"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"dimension_prefix": "_", "system_prefix": "__"}
    description = (
        "Dimension tables (name starts with '_' but not '__') carry "
        "attributes; measures on them are hard to find and move with the "
        "dimension when it is re-sourced. Advisory, opt-in."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        dim, system = self.options["dimension_prefix"], self.options["system_prefix"]
        for model in ctx.models:
            for t in model.table_list:
                if t.name.startswith(dim) and not t.name.startswith(system) and t.measure_list:
                    names = ", ".join(m.name for m in t.measure_list)
                    out.append(self.violation(
                        f"dimension table {t.name} holds measures ({names}); move them to "
                        f"a measures table.",
                        file=t.file, line=t.line, obj=t.name,
                    ))
        return out


class EmptyMeasureTablesRule(Rule):
    id = "O006"
    name = "empty-measure-tables"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"measure_container_token": "Measures"}
    description = (
        "A table named as a measures container (its name contains 'Measures') "
        "that holds no measures is usually a leftover after a move. Advisory, "
        "opt-in."
    )

    def check(self, ctx: Context) -> list[Violation]:
        token = self.options["measure_container_token"]
        return [
            self.violation(
                f"table {t.name} is named as a measures table but holds no measures; "
                f"delete it or move the intended measures into it.",
                file=t.file, line=t.line, obj=t.name,
            )
            for model in ctx.models for t in model.table_list
            if token in t.name and not t.measure_list
        ]


class FormatInferenceNamingRule(Rule):
    id = "S003"
    name = "format-inference-naming"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {
        "currency_tokens": ["cost", "revenue", "value", "cpc", "cpm", "cpa", "price", "spend"],
        "percent_tokens": ["%", "rate", "ctr", "cvr", "ratio", "roas"],
        "count_tokens": ["#", "count", "total"],
    }
    description = (
        "When a calculation group picks formats from the measure name "
        "(currency for 'cost', percent for 'rate'), a visible measure in a "
        "measures table whose name carries no type indicator falls back to "
        "default formatting. Advisory, opt-in."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        tokens = [t.lower() for key in ("currency_tokens", "percent_tokens", "count_tokens")
                  for t in self.options[key]]
        for model in ctx.models:
            for t in model.table_list:
                if "Measures" not in t.name:
                    continue
                for m in t.measure_list:
                    if m.is_hidden or m.name.startswith("-"):
                        continue
                    if not any(tok in m.name.lower() for tok in tokens):
                        out.append(self.violation(
                            f"{t.name}[{m.name}] has no type indicator (currency, percent "
                            f"or count) in its name; rename it or give it a format string.",
                            file=m.file, line=m.line, obj=m.full_name,
                        ))
        return out


# ---------------------------------------------------------------------------
# O007: dead fact tables (ratcheted)
# ---------------------------------------------------------------------------

# Functions that only sense filter context; a table named inside them is
# observed, not read.
_SENSOR_RE = re.compile(
    r"\b(?:HAS(?:ONEVALUE|ONEFILTER)|IS(?:CROSSFILTERED|FILTERED|INSCOPE|EMPTY))\s*\(",
    re.IGNORECASE,
)
_PLAIN_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _observed_regions(code: str):
    """Argument spans of every sensor call (parentheses balanced)."""
    found = []
    for m in _SENSOR_RE.finditer(code):
        level = 1
        for pos in range(m.end(), len(code)):
            level += {"(": 1, ")": -1}.get(code[pos], 0)
            if level == 0:
                found.append((m.end(), pos))
                break
        else:
            found.append((m.end(), len(code)))
    return found


def table_reads(name: str, expressions: list[str]) -> tuple[int, int]:
    """``(data, sensor)`` reference counts of a table across expressions."""
    if _PLAIN_IDENT_RE.match(name):
        ref = re.compile(r"'" + re.escape(name) + r"'|\b" + re.escape(name) + r"\b")
    else:
        ref = re.compile(r"'" + re.escape(name.replace("'", "''")) + r"'")
    data = sensor = 0
    for expr in expressions:
        if name not in expr:
            continue
        code = strip_comments(expr)
        spans = _observed_regions(code)
        for m in ref.finditer(code):
            if any(a <= m.start() < b for a, b in spans):
                sensor += 1
            else:
                data += 1
    return data, sensor


class DeadFactTablesRule(Rule):
    id = "O007"
    name = "dead-fact-tables"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {"baseline": None}
    description = (
        "A fact table no measure reads (its only mentions are filter sensors "
        "such as ISFILTERED, or comments) is residue of an incomplete "
        "removal; sensing makes it look owned, so it is never dropped and "
        "keeps loading. Ratcheted: tables recorded in the 'baseline' file "
        "(a JSON object of model key to table list) pass, new ones fail, and "
        "recorded tables that are alive again print a tighten hint. A "
        "configured baseline file that does not exist is an error. Opt-in."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        floors: Optional[dict] = None
        if self.options.get("baseline"):
            try:
                floors = load_floors(self.options["baseline"])
            except RatchetFileError as exc:
                return [self.violation(
                    f"{exc}; record the accepted dead tables (or an empty object) "
                    f"before relying on this gate.",
                )]
        for model in ctx.models:
            exprs = [m.expression for m in model.all_measures() if m.expression]
            key = ctx.model_key(model)
            accepted: set[str] = set()
            if floors is not None:
                _found, value = entry_for(floors, key)
                accepted = set(value or [])
            dead = []
            for name in fact_tables(model):
                data, sensor = table_reads(name, exprs)
                if data == 0:
                    dead.append((name, sensor))
            dead_names = {n for n, _ in dead}
            for name, sensor in dead:
                if name in accepted:
                    continue
                t = model.tables[name]
                out.append(self.violation(
                    f"fact table {name} is dead: no measure reads it ({sensor} sensor "
                    f"reference(s) only). Finish removing it, or record it in the "
                    f"baseline with a reason.",
                    file=t.file, line=t.line, obj=name,
                ))
            alive = sorted(accepted - dead_names)
            if alive:
                ctx.notes.append(
                    "[dead-fact-table floor] entries no longer dead — tighten the floor: "
                    + ", ".join(f"{key}: {name}" for name in alive))
        return out


class DimensionPrefixFloorRule(Rule):
    id = "N020"
    name = "dimension-prefix-floor"
    severity = Severity.WARNING
    opt_in = True
    option_defaults = {"enabled": False, "min_dimension_tables": 20, "dimension_prefix": "_"}
    description = (
        "Opt-in and disabled by default (select it and set enabled = true): "
        "count the tables "
        "whose name starts with the dimension prefix and warn when there are "
        "fewer than min_dimension_tables. Useful for a template whose "
        "convention is a fixed set of dimensions; a copy that lost some "
        "fails here before anything is published."
    )

    def disabled_by_policy(self) -> bool:
        return not self.options.get("enabled")

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        floor = int(self.options["min_dimension_tables"])
        prefix = self.options["dimension_prefix"]
        for model in ctx.models:
            n = sum(1 for t in model.table_list if t.name.startswith(prefix))
            if n < floor:
                out.append(self.violation(
                    f"the model has {n} dimension table(s) (names starting with '{prefix}'), "
                    f"fewer than the {floor} the convention expects.",
                    file=model.definition_path / "tables", obj=ctx.model_key(model)))
        return out
