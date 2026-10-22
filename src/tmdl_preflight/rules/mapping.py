"""Analysis-category plumbing: the encoded mapping table, the f-All gate
chains and the f- filter measures. IDs A001-A005 (all opt-in: they encode
the axis/category convention of one family of report models)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ..categories import (
    MAPPING_PREFIX,
    MAPPING_TABLE,
    NUMBERED_X_AXIS_GLOBS,
    NON_ATTRIBUTING_GROUPS,
    FactTracer,
    MappingDecodeError,
    axis_rows,
    category_backing,
    chain_body,
    declared_gate_measures,
    find_mapping_table,
    gate_literals,
    gate_measure_calls,
    load_mapping,
    read_mapping,
    resolve_gate_measure,
)
from ..edits import EditRefused, verified_write
from ..model import SemanticModel
from .base import Context, Rule, Severity, Violation


def _has_column(model: SemanticModel, table: str, column: str) -> bool:
    """Does the table hold a column with exactly this name?"""
    t = model.get_table(table)
    return t is not None and any(c.name == column for c in t.column_list)


class MappingTableRequiredColumnsRule(Rule):
    id = "A001"
    name = "mapping-table-required-columns"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {
        "mapping_table": MAPPING_TABLE,
        "required_columns": ["category_x_id", "Analysis Category", "Analysis Subcategory"],
        "enabled": True,
    }
    description = (
        "The category-mapping table (which analysis category each axis group "
        "belongs to) must exist and declare its key columns (exact, "
        "case-sensitive names). Without them the category slicer and the "
        "per-category filter measures silently return nothing. enabled = "
        "false skips the rule."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("enabled") is False

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        name = self.options["mapping_table"]
        required = list(self.options["required_columns"])
        for model in ctx.models:
            table = model.get_table(name)
            if table is None:
                out.append(self.violation(
                    f"mapping table '{name}' not found; category filtering has no "
                    f"category-to-group map. Restore the table from the template.",
                    file=model.definition_path / "tables", obj=name,
                ))
                continue
            have = [c.name for c in table.column_list]
            missing = [c for c in required if c not in have]
            if missing:
                out.append(self.violation(
                    f"mapping table '{name}' ({len(have)} columns) lacks required "
                    f"column(s) {', '.join(missing)}; present: "
                    f"{', '.join(c for c in required if c in have) or 'none'}. Restore "
                    f"the column(s) in the source and the table definition.",
                    file=table.file, line=table.line, obj=name,
                ))
        return out


class MappingTableInfoReportsRule(Rule):
    id = "A002"
    name = "mapping-table-info-reports"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"mapping_table": MAPPING_TABLE, "axis_globs": list(NUMBERED_X_AXIS_GLOBS)}
    description = (
        "Inventory for reviewers (never fails): the distinct group ids the "
        "axis field-parameter tables use, and how many relationships touch "
        "the mapping table (0 means it is used through DAX filtering only)."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        name = self.options["mapping_table"]
        for model in ctx.models:
            table = model.get_table(name)
            if table is None:
                continue
            groups = sorted({r.group for r in axis_rows(model, self.options["axis_globs"]) if r.group})
            out.append(self.violation(
                f"axis group ids ({len(groups)}): {', '.join(groups) or 'none'}",
                file=table.file, obj=name,
            ))
            rel_file = model.definition_path / "relationships.tmdl"
            if not rel_file.is_file():
                continue
            prefix = name.split(" ")[0]
            blocks = re.split(r"(?m)^relationship\b", rel_file.read_text(encoding="utf-8-sig"))[1:]
            count = sum(1 for b in blocks if prefix in b)
            note = "" if count else "; the table is used through DAX filtering only"
            out.append(self.violation(
                f"{count} relationship(s) mention '{prefix}'{note}",
                file=rel_file, obj=name,
            ))
        return out


class MappingCategoryRequiredKeysRule(Rule):
    id = "A003"
    name = "mapping-category-required-keys"
    severity = Severity.ERROR
    opt_in = True
    fixable = True
    option_defaults = {
        "mapping_table": MAPPING_TABLE,
        "account_key_column": "account_x_id",
        "required_keys": ["Account_y", "Service_y"],
        "non_attributing_group_ids": list(NON_ATTRIBUTING_GROUPS),
        "axis_globs": list(NUMBERED_X_AXIS_GLOBS),
        "declared_removals": [],
    }
    description = (
        "Every analysis category whose data can be filtered by account must "
        "list the account groups (required_keys) in the mapping table; "
        "otherwise consumers that build per-category filter lists fail with "
        "'filter dimension not found' for multi-account tenants. A category "
        "is exempt only when its measures are traced to fact tables and none "
        "of them has the account key column (those get a warning instead: "
        "the account filter would return unfiltered data). The key column is "
        "matched by its exact name. A mapping table whose payload cannot be "
        "read is an error, not a pass. declared_removals lists [category, key] "
        "pairs removed on purpose. Auto-fix appends the missing rows to the "
        "encoded table; existing rows are untouched."
    )

    def _removed(self) -> set[tuple[str, str]]:
        out = set()
        for pair in self.options.get("declared_removals") or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                out.add((str(pair[0]), str(pair[1])))
        return out

    def _read(self, model: SemanticModel):
        """``(mapping, error)``: the error is the message of the finding
        when the table's payload cannot be read."""
        table = model.get_table(self.options["mapping_table"])
        if table is None:
            return None, None
        try:
            return read_mapping(table), None
        except MappingDecodeError as exc:
            if exc.no_payload:
                return None, f"No binary data found in {table.file}"
            return None, f"mapping payload does not decode: {exc}"

    def _analyse(self, model: SemanticModel):
        """``(mapping, error, missing {category: [keys]}, warnings)``."""
        mapping, error = self._read(model)
        if mapping is None:
            return None, error, {}, []
        key_col = self.options["account_key_column"]
        tracer = FactTracer(model)
        backing = category_backing(model, mapping, self.options["axis_globs"],
                                   self.options["non_attributing_group_ids"], tracer)
        has_key = {f: _has_column(model, f, key_col) for f in tracer.facts}
        removed = self._removed()
        keys = list(self.options["required_keys"])
        missing: dict[str, list[str]] = {}
        warnings: list[tuple[str, str]] = []
        for cat in mapping.categories():
            facts = backing.get(cat)
            groups = mapping.groups_of(cat)
            if facts and not any(has_key.get(f) for f in facts):
                warnings.append((cat, (
                    f"[{cat}] account-UNSUPPORTED — backing fact table(s) lack "
                    f"'{key_col}': {sorted(facts)}. Not adding account dims; backfill "
                    f"'{key_col}' to enable account filtering.")))
                continue
            if facts:
                lacking = sorted(f for f in facts if not has_key.get(f))
                if lacking:
                    warnings.append((cat, (
                        f"[{cat}] account-filterable, but these backing fact tables "
                        f"still lack '{key_col}' (account filter will be partial until "
                        f"backfilled): {lacking}.")))
            gaps = [k for k in keys if k not in groups and (cat, k) not in removed]
            if gaps:
                missing[cat] = gaps
        return mapping, None, missing, warnings

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        keys = list(self.options["required_keys"])
        both = " and ".join(keys[:2])
        for model in ctx.models:
            mapping, error, missing, warnings = self._analyse(model)
            if error is not None:
                out.append(self.violation(
                    error, file=model.get_table(self.options["mapping_table"]).file))
                continue
            for cat in sorted(missing):
                out.append(self.violation(
                    f"[{cat}] missing {missing[cat]} Each must assign both {both}.",
                    file=mapping.table.file, obj=f"{mapping.table.name}[{cat}]",
                ))
            for cat, text in warnings:
                out.append(self.violation(text, file=mapping.table.file,
                                          obj=f"{mapping.table.name}[{cat}]",
                                          severity=Severity.WARNING, fixable=False))
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            mapping, error, missing, _w = self._analyse(model)
            if mapping is None or not missing:
                continue
            width = mapping.width
            added = []
            for cat in mapping.categories():
                for key in missing.get(cat, []):
                    added.append([cat, "", key] if width >= 3 else [cat, key])
            if not added:
                continue
            new_rows = mapping.rows + added
            new_text = mapping.with_rows(new_rows)

            def verify(old: str, new: str, mapping=mapping, new_rows=new_rows) -> None:
                from ..categories import _BLOB_RE, decode_rows

                if old[: mapping.blob_start] != new[: mapping.blob_start]:
                    raise EditRefused("text before the payload changed")
                m = list(_BLOB_RE.finditer(new))
                if not m or decode_rows(m[0].group("blob")) != new_rows:
                    raise EditRefused("payload does not round-trip")

            try:
                verified_write(mapping.file, new_text, verify)
            except EditRefused:
                continue
            applied.extend(f"   wrote [{r[0]}] += {r[-1]}" for r in added)
        return applied


# ---------------------------------------------------------------------------
# f-All gate coverage
# ---------------------------------------------------------------------------

_BASELINE_KEYS = ("coverage_gaps", "ungated_without_measure", "inert_literals",
                  "fleet_inert_literals", "over_broad_literals")


def _load_gate_baseline(path: Optional[str]) -> dict:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class CategoryGateCoverageRule(Rule):
    id = "A004"
    name = "category-gate-coverage"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {
        "baseline": None,
        "mapping_prefix": MAPPING_PREFIX,
        "orchestrator_table": "f-Filters",
        "orchestrator_measure": "f-All",
        "and_chain": "temp_basic",
        "or_chain": "temp_alt",
    }
    description = (
        "The f-All orchestrator measure gates every analysis category with "
        "IF(CONTAINSSTRING(all_cats, \"<Category>\"), IF([f-<Category>] > 0, ...)) "
        "in an AND chain and an OR chain. Six checks, named in each message: "
        "unpaired-chains (the chains gate different literals, error), "
        "undeclared-gate-measure (a live IF([f-X] > 0 names no declared f- "
        "measure, error), coverage-gap (a category with a resolvable f- "
        "measure has no gate, warning), ungated-without-measure (warning), "
        "inert-literal (a literal matches no registered category, error) and "
        "over-broad-literal (a literal matches several categories, warning). "
        "Coverage is substring based, as CONTAINSSTRING is. Categories come "
        "from the encoded mapping table; without one the last four checks are "
        "skipped. The baseline file (option baseline) accepts known findings "
        "per model and only shrinks: an entry that no longer applies is "
        "reported as stale."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        base = _load_gate_baseline(self.options.get("baseline"))
        for model in ctx.models:
            out.extend(self._check_model(ctx, model, base))
        return out

    def _check_model(self, ctx: Context, model: SemanticModel, base: dict) -> list[Violation]:
        out: list[Violation] = []
        orch = model.get_table(self.options["orchestrator_table"])
        if orch is None:
            return out
        try:
            text = orch.file.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError):
            return out
        model_id = ctx.model_key(model)
        if model_id.endswith(".SemanticModel"):
            model_id = model_id[: -len(".SemanticModel")]
        file = orch.file

        def add(check: str, msg: str, severity: Severity, obj: str, line: Optional[int] = None):
            out.append(self.violation(f"{check}: {msg}", file=file, line=line,
                                      obj=f"{model_id}:{obj}", severity=severity))

        declared = declared_gate_measures(text)
        # (2) live IF([f-X] > 0 lines name declared measures
        reported: set[str] = set()
        for line, name in gate_measure_calls(text):
            if name not in declared and name not in reported:
                reported.add(name)
                add("undeclared-gate-measure",
                    f"IF([{name}] > 0 calls a measure '{self.options['orchestrator_table']}' "
                    f"does not declare, so {self.options['orchestrator_measure']} fails "
                    f"wherever it is evaluated. Restore the measure or drop the gate.",
                    Severity.ERROR, name, line)

        measure = orch.find_measure(self.options["orchestrator_measure"])
        if measure is None:
            return out
        expr = measure.expression or ""
        and_body = chain_body(expr, self.options["and_chain"], [f"VAR {self.options['or_chain']}", "RETURN"])
        or_body = chain_body(expr, self.options["or_chain"], ["VAR ", "RETURN"])
        if and_body is None or or_body is None:
            return out
        and_lits, or_lits = gate_literals(and_body), gate_literals(or_body)
        # (1) both chains gate the same literals
        only_and = [x for x in and_lits if x not in or_lits]
        only_or = [x for x in or_lits if x not in and_lits]
        if only_and or only_or:
            add("unpaired-chains",
                f"the {self.options['and_chain']} and {self.options['or_chain']} chains of "
                f"{self.options['orchestrator_measure']} gate different categories (only in "
                f"{self.options['and_chain']}: {', '.join(only_and) or 'none'}; only in "
                f"{self.options['or_chain']}: {', '.join(only_or) or 'none'}). Add the "
                f"missing gate to the other chain.",
                Severity.ERROR, "chains", measure.line)

        mapping = load_mapping(model, prefix=self.options["mapping_prefix"])
        if mapping is None:
            return out
        cats = mapping.categories()

        def gated(cat: str) -> bool:
            return any(lit in cat for lit in and_lits)

        gaps = [c for c in cats if not gated(c) and resolve_gate_measure(c, declared)]
        no_measure = [c for c in cats if not gated(c) and not resolve_gate_measure(c, declared)]
        inert = [lit for lit in and_lits if not any(lit in c for c in cats)]
        broad = {lit: [c for c in cats if lit in c] for lit in and_lits}
        broad = {lit: cs for lit, cs in broad.items() if len(cs) > 1}

        def accepted(key: str) -> list[str]:
            entry = (base.get(key) or {}).get(model_id) or []
            return [str(x) for x in entry]

        fleet = {str(x) for x in base.get("fleet_inert_literals") or []}
        sev_w = Severity.WARNING

        def ratchet(check: str, key: str, found: list[str], severity: Severity, text):
            allowed = accepted(key)
            for item in found:
                if item not in allowed:
                    add(check, text(item), severity, item, measure.line)
            for item in allowed:
                if item not in found:
                    add(check, f"stale baseline entry '{item}' in {key} for {model_id}: it no "
                        f"longer applies; remove it from the baseline (baselines only shrink).",
                        severity, item)

        ratchet("coverage-gap", "coverage_gaps", gaps, sev_w, lambda c: (
            f"category '{c}' has the gate measure [{resolve_gate_measure(c, declared)}] but no "
            f"gate in {self.options['and_chain']}, so its rows are never filtered. Add the gate "
            f"to both chains (pbip-forge can append it)."))
        ratchet("ungated-without-measure", "ungated_without_measure", no_measure, sev_w, lambda c: (
            f"category '{c}' has neither a gate nor an f- measure to gate on; write the "
            f"measure and gate it, or retire the category's mapping rows."))
        inert_new = [x for x in inert if x not in fleet]
        ratchet("inert-literal", "inert_literals", inert_new, Severity.ERROR, lambda x: (
            f"gate literal \"{x}\" matches no registered category, so the gate never fires; "
            f"fix the literal or remove the gate."))
        ratchet("over-broad-literal", "over_broad_literals", sorted(broad), sev_w, lambda x: (
            f"gate literal \"{x}\" matches {len(broad[x])} categories "
            f"({', '.join(broad[x])}), so one gate filters several categories on the same "
            f"measure; use the full category name."))
        return out


# ---------------------------------------------------------------------------
# f- measure shapes
# ---------------------------------------------------------------------------

_F_REF = r"\[f-[^\]]*\]"


def classify_f_measure(expression: str, table: str, display_prefix: str = "w-") -> str:
    expr = expression or ""
    upper = expr.upper()
    if any(k in upper for k in ("ISEMPTY", "ISINSCOPE", "ISFILTERED")):
        return "standard"
    if len(re.findall(_F_REF, expr)) >= 2 and re.search(_F_REF + r"\s*[-+*]\s*\[f-", expr):
        return "aggregator"
    if "SWITCH(TRUE()" in re.sub(r"\s+", "", expr).upper():
        return "switch-router"
    if table.startswith(display_prefix) or "CONCATENATEX" in upper:
        return "display-string"
    return "unclassified"


class FMeasurePatternRule(Rule):
    id = "A005"
    name = "f-measure-pattern"
    severity = Severity.WARNING
    opt_in = True
    option_defaults = {"prefix": "f-", "exempt": ["f-Analysis Category"], "display_table_prefix": "w-"}
    description = (
        "Every f- (visual-filter) measure must have a known shape: an "
        "existence check (ISEMPTY, ISINSCOPE or ISFILTERED), an aggregate of "
        "two or more f- measures joined by + - or *, a SWITCH(TRUE(), ...) "
        "router, or a display string (hosted in a w- table, or built with "
        "CONCATENATEX). Anything else usually lacks the existence check, so "
        "the visual filter keeps every row or none."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        prefix = self.options["prefix"]
        exempt = set(self.options["exempt"])
        for model in ctx.models:
            for m in model.all_measures():
                if not m.name.startswith(prefix) or m.name in exempt:
                    continue
                if classify_f_measure(m.expression, m.table, self.options["display_table_prefix"]) != "unclassified":
                    continue
                out.append(self.violation(
                    f"{m.table}[{m.name}] fits no known filter-measure shape (existence "
                    f"check, aggregate of f- measures, SWITCH(TRUE()) router or display "
                    f"string); add the existence check, or list it under exempt.",
                    file=m.file, line=m.line, obj=m.full_name,
                ))
        return out
