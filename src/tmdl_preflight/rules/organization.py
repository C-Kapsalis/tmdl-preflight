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

#: The guidance the strict profile prints for each subcategory.
_GUIDANCE = {
    "measure_helper": "the helper table",
    "visual_helper": "the helper table or a visual (w-) table",
    "diagnostic_helper": "a helper or diagnostic table",
    "slicer_helper": "the slicer table or a visual (w-) table",
    "intermediary_helper": "a '<Domain> Measures' table next to the measures it feeds",
    "test_measure": "a helper or diagnostic table",
}

#: The guidance of the strict report, one block per subcategory.
_STRICT_BLOCK = {
    "measure_helper":
        "'-helper *' / '_*' measures must live in 'Helper Measures' with a "
        "displayFolder named after the analysis category they support (e.g. "
        "'Helpers Time Intelligence', 'Helpers SEO Debugging'). They are a "
        "specific kind of helper - do not scatter them across domain <X> "
        "Measures tables.",
    "visual_helper":
        "'-Visual *' / 'w-*' measures live in 'Helper Measures' or in a "
        "`w-*` table (e.g. 'w-Titles', 'w-Colors', 'w-Visuals Filters').",
    "diagnostic_helper":
        "'i-*' measures live in 'Helper Measures' or a table containing "
        "'Diagnostic' in its name (e.g. 'Diagnostic Measures').",
    "slicer_helper":
        "'f-*' measures live in 'f-Filters' (slicer-level filters) or in a "
        "`w-*` table (non-slicer-level visual filters, e.g. 'w-Visuals "
        "Filters').",
    "intermediary_helper":
        "Other '-*' and '<letter>-*' helpers live next to the user-facing "
        "measures they support, in a `<Domain> Measure(s)` table (e.g. 'GA "
        "Measures', 'Time Intelligence Measures', 'Dynamic Measure'), OR in a "
        "`w-*` table when they back a visual element (e.g. 'w-Titles' for "
        "cluster-name title helpers).",
    "test_measure":
        "Test measures (any name containing whole-word 'test', "
        "case-insensitive) belong in 'Helper Measures' or 'Diagnostic "
        "Measures'. If it's not a real test, rename to drop 'test'.",
}

#: The four buckets the lenient profile counts, with the table each helper
#: belongs in.
_LENIENT_BUCKETS = (
    ("slicer_helper", "f- measures outside f-Filters / w-*",
     "f- measures in wrong table",
     "'f-Filters' or any 'w-*' table"),
    ("measure_helper", "-helper * outside 'Helper Measures'",
     "-helper * measures in wrong table",
     "'Helper Measures' (with displayFolder named by analysis category)"),
    ("visual_helper", "-Visual * / w-* outside Helper Measures / w-*",
     "-Visual * / w-* measures in wrong table",
     "'Helper Measures' or any 'w-*' table"),
    ("diagnostic_helper", "i- measures outside Helper / Diagnostic",
     "i- measures in wrong table",
     "'Helper Measures' or 'Diagnostic Measures'"),
)

#: The table each kind of helper belongs in, in the wording of a finding.
_LENIENT_EXPECTED = {sub: expected for sub, _c, _l, expected in _LENIENT_BUCKETS}

#: The width the count labels line up in.
_LENIENT_LABEL_WIDTH = max(len(count) for _s, count, _l, _e in _LENIENT_BUCKETS)


class HelperMeasurePlacementRule(Rule):
    id = "O002"
    name = "helper-measure-placement"
    severity = Severity.WARNING
    opt_in = True
    option_defaults = {
        "helper_table": "Helper Measures",
        "slicer_table": "f-Filters",
        "visual_table_prefix": "w-",
        "field_parameter_prefixes": ["x-Selector", "y-Selector",
                                     "x-Plot Specific", "y-Plot Specific"],
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
        "dimension (_) tables and exempts the axis field-parameter tables; "
        "profile 'lenient' (infos) judges only slicer, '-helper', visual and "
        "diagnostic helpers and prints a per-model summary. Opt-in; the "
        "symptom is a confusing field list."
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
            strict: dict[str, list[tuple[str, str]]] = {}
            lenient_buckets: dict[str, list[tuple[str, str]]] = {}
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
                        lenient_buckets.setdefault(sub, []).append((host, m.name))
                        out.append(self.violation(
                            f"{host}[{m.name}] [{sub}] (expected: "
                            f"{_LENIENT_EXPECTED[sub]})",
                            file=m.file, line=m.line, obj=m.full_name,
                            severity=Severity.INFO,
                        ))
                        continue
                    if host.startswith(o["user_only_table_prefix"]) or host.startswith(o["dimension_prefix"]):
                        reason = "user-only" if host.startswith(o["user_only_table_prefix"]) else "dimension"
                        out.append(self.violation(
                            f"{host}[{m.name}] [{sub}] is a helper in a {reason} table; move it "
                            f"to {_GUIDANCE.get(sub, 'a helper table')}.",
                            file=m.file, line=m.line, obj=m.full_name,
                            grouped=True,
                        ))
                        strict.setdefault(sub, []).append((host, m.name))
                        continue
                    if any(host.startswith(p) for p in o["field_parameter_prefixes"]):
                        continue
                    if not self._allowed(sub, host):
                        out.append(self.violation(
                            f"{host}[{m.name}] [{sub}] is in the wrong table; move it to "
                            f"{_GUIDANCE.get(sub, 'a helper table')}.",
                            file=m.file, line=m.line, obj=m.full_name,
                            grouped=True,
                        ))
                        strict.setdefault(sub, []).append((host, m.name))
            if lenient:
                ctx.notes.append(self._lenient_report(ctx, model, lenient_buckets))
            else:
                block = self._strict_report(strict)
                if block:
                    ctx.notes.append(block)
        return out

    def _strict_report(self, grouped: dict[str, list[tuple[str, str]]]) -> str:
        """The strict report: one block per subcategory, in sorted order."""
        if not grouped:
            return ""
        total = sum(len(v) for v in grouped.values())
        lines = [f"Found {total} helper measure(s) in wrong table(s), "
                 f"grouped by subcategory:"]
        for sub in sorted(grouped):
            items = grouped[sub]
            lines.append("")
            lines.append(f"  [{sub}] - {len(items)} violation(s)")
            lines.append(f"    Rule: {_STRICT_BLOCK.get(sub, '(no per-subcategory guidance)')}")
            for table, name in items:
                lines.append(f"      - {table}[{name}]")
        return "\n".join(lines)

    def _lenient_report(self, ctx: Context, model,
                        buckets: dict[str, list[tuple[str, str]]]) -> str:
        """The lenient report: the four counts and the lists under them."""
        key = ctx.model_key(model)
        lines = [f"Measure Organization ({key}):"]
        for sub, count_label, _list_label, _expected in _LENIENT_BUCKETS:
            items = buckets.get(sub) or []
            lines.append(f"{count_label + ':':<{_LENIENT_LABEL_WIDTH + 1}} {len(items)}")
        for sub, _count_label, list_label, expected in _LENIENT_BUCKETS:
            items = buckets.get(sub) or []
            if not items:
                continue
            lines.append("")
            lines.append(f"{list_label} ({len(items)}):")
            for table, name in items:
                lines.append(f"  - {table}[{name}]  (expected: {expected})")
        if not any(buckets.get(sub) for sub, _c, _l, _e in _LENIENT_BUCKETS):
            lines.append("")
            lines.append("All helper-family measures live in expected tables.")
        return "\n".join(lines)


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
        "internal_name_tokens": ["ga4traf", "ga4users", "ga4convs", "related"],
        "diagnostic_tokens": ["countrows", "count ", "diagnostic", "debug", "helper"],
    }
    description = (
        "Fact tables should hold data. A user-facing measure on a fact (one a "
        "field parameter surfaces, or a visible measure whose name is not a "
        "diagnostic, test, helper or lowercase name) is a warning; any other "
        "measure on a fact is listed as info with the reason it was not "
        "counted. A name that carries one of the internal_name_tokens is "
        "advisory too; the token itself is not a tag. Facts follow the shared "
        "table-role law. Opt-in."
    )

    def _tags(self, m, diag: list[str]) -> list[str]:
        """The advisory tags of a measure, in the reference's order."""
        low = m.name.lower()
        tags = []
        if m.is_hidden:
            tags.append("hidden")
        if low.startswith("test"):
            tags.append("test")
        if m.name.startswith("-"):
            tags.append("helper")
        if any(d in low for d in diag):
            tags.append("diagnostic")
        if m.name[:1].islower():
            tags.append("lowercase")
        return tags

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        diag = [t.lower() for t in self.options["diagnostic_tokens"]]
        internal = [t.lower() for t in self.options["internal_name_tokens"]]
        for model in ctx.models:
            surfaced = surfaced_measures(model, self.options["surfacing_tables"] or None)
            warnings: list[tuple[str, str, bool]] = []
            advisories: list[tuple[str, str, str]] = []
            for name in fact_tables(model):
                t = model.tables[name]
                for m in t.measure_list:
                    low = m.name.lower()
                    tags = self._tags(m, diag)
                    is_internal = any(tok in low for tok in internal)
                    if m.name in surfaced or not (tags or is_internal):
                        why = "a field parameter surfaces it" if m.name in surfaced else "it is visible"
                        out.append(self.violation(
                            f"user-facing measure {t.name}[{m.name}] is homed on a fact "
                            f"table ({why}); move it into a measures table.",
                            file=m.file, line=m.line, obj=m.full_name,
                        ))
                        warnings.append((t.name, m.name, m.name in surfaced))
                        continue
                    group = ", ".join(tags)
                    advisories.append((t.name, m.name, group))
                    out.append(self.violation(
                        f"{t.name}[{m.name}]"
                        + (f" [{group}]" if group else "")
                        + " sits on a fact table (advisory).",
                        file=m.file, line=m.line, obj=m.full_name, severity=Severity.INFO,
                    ))
            ctx.notes.extend(self._report(ctx, model, warnings, advisories))
        return out

    def _report(self, ctx: Context, model, warnings: list, advisories: list) -> list[str]:
        """The per-model block the text report shows beside the findings."""
        out: list[str] = []
        if warnings:
            out.append(f"Found {len(warnings)} USER-FACING measures in fact tables")
            for table, name, surfaced in warnings:
                out.append(f"   Table: {table}")
                out.append(f"      - {name}" + (" (IN x-Selector!)" if surfaced else ""))
            out.append("")
        if advisories:
            out.append(
                f"ADVISORY: Found {len(advisories)} hidden/diagnostic measures "
                f"in fact tables")
            for table, name, group in advisories:
                out.append(f"   • {table}[{name}]"
                           + (f" [{group}]" if group else ""))
            out.append("   Recommended actions:")
            out.append("   - Move diagnostic measures to 'Diagnostic Measures' table")
            out.append("   - Delete test measures (leftover from development)")
            out.append("   - Priority: P2 (cleanup when convenient, not urgent)")
            out.append("")
        if not warnings and not advisories:
            out.append("No measures in fact tables")
            out.append("")
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


def dead_fact_tables(model) -> list[tuple[str, int]]:
    """``(table, sensor references)`` of every fact no measure reads.

    A fact whose only mentions are filter-context sensors is dead: sensing
    makes it look owned, so it is never dropped and keeps loading.
    """
    exprs = [m.expression for m in model.all_measures() if m.expression]
    out = []
    for name in fact_tables(model):
        data, sensor = table_reads(name, exprs)
        if data == 0:
            out.append((name, sensor))
    return out


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
        current: dict[str, list[str]] = {}
        for model in ctx.models:
            current[ctx.model_key(model)] = sorted(
                name for name, _s in dead_fact_tables(model))
        # every floor entry that is not dead now: the table came back, or the
        # model was not scanned, or it does not exist any more
        stale: list[str] = []
        if floors is not None:
            for key, value in floors.items():
                entry = value if isinstance(value, list) else []
                found, alive = entry_for(current, key)
                for name in entry:
                    if not found or name not in (alive or []):
                        stale.append(f"{key}: {name}")
        if stale:
            ctx.notes.append(
                "[dead-fact-table floor] entries no longer dead — tighten the "
                "floor (tmdl-preflight dead-facts --capture):\n  "
                + "\n  ".join(sorted(stale)))
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
            growth = [name for name, _s in dead if name not in accepted]
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
            if growth and floors is not None:
                ctx.notes.append(
                    f"{len(growth)} NEW dead fact table(s) beyond the committed "
                    f"floor — no measure reads them; either finish the drop or "
                    f"accept them into {self.options['baseline']} with a reason:\n  "
                    + "\n  ".join(f"{key}: {name}" for name in sorted(growth)))
        return out


class DimensionPrefixFloorRule(Rule):
    id = "N020"
    name = "dimension-prefix-floor"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {"enabled": False, "min_dimension_tables": 20, "dimension_prefix": "_"}
    description = (
        "Opt-in and disabled by default (select it and set enabled = true): "
        "count the table files "
        "whose name starts with the dimension prefix and fail when there are "
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
            folder = model.definition_path / "tables"
            names = sorted(p.stem for p in folder.glob("*.tmdl")
                           if p.stem.startswith(prefix))
            n = len(names)
            if n < floor:
                out.append(self.violation(
                    f"Expected at least {floor} dimension tables starting with "
                    f"'{prefix}', found {n}",
                    file=folder, obj=ctx.model_key(model)))
            else:
                out.append(self.violation(
                    "\n".join([f"✅ Found {n} dimension tables starting with '{prefix}'",
                               "Sample dimension tables:"]
                              + [f"  - {name}" for name in names[:10]]),
                    file=folder, obj=ctx.model_key(model), severity=Severity.INFO))
        return out
