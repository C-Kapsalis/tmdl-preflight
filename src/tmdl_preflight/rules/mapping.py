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
    axis_group_ids,
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
    severity = Severity.WARNING
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
        "per-category filter measures silently return nothing. This is a P1 "
        "check: it is a warning, and --strict makes it fail the run. enabled "
        "= false skips the rule."
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
                    f"P1 WARNING: {name} table not found",
                    file=model.definition_path / "tables", obj=name,
                ))
                continue
            have = [c.name for c in table.column_list]
            present = [c for c in required if c in have]
            missing = [c for c in required if c not in have]
            if missing:
                out.append(self.violation(
                    f"Z-Map Table Structure: table found: {name}; total columns: "
                    f"{len(have)}; required columns present: {len(present)}/"
                    f"{len(required)}; present required columns: {present}; missing "
                    f"required columns: {missing}. These columns are critical for "
                    f"dimension-measure grouping",
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
        "numbered x-axis tables use, and how many relationships touch the "
        "mapping table (0 means it is used through DAX filtering only)."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        name = self.options["mapping_table"]
        prefix = name.split(" ")[0]
        for model in ctx.models:
            table = model.get_table(name)
            if table is not None:
                groups = sorted(set(axis_group_ids(model, self.options["axis_globs"])))
                out.append(self.violation(
                    f"Unique x-Selector categories found: {len(groups)}\n"
                    + "".join(f"  - {g}\n" for g in groups)
                    + "z-Map table provides category mapping infrastructure",
                    file=table.file, obj=name,
                ))
            rel_file = model.definition_path / "relationships.tmdl"
            if not rel_file.is_file():
                continue
            try:
                content = rel_file.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeDecodeError):
                continue
            blocks = re.split(r"(?m)^relationship\b", content)
            count = sum(1 for b in blocks if prefix in b)
            note = (f"{prefix} has relationships defined" if count else
                    f"No relationships found involving {prefix}. Note: {prefix} may "
                    f"use calculated relationships or direct filtering")
            out.append(self.violation(
                f"Relationships involving {prefix}: {count}\n{note}",
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
        "unpaired-chains (the chains gate different literals), "
        "undeclared-gate-measure (a live IF([f-X] > 0 names no declared f- "
        "measure), coverage-gap (a category with a resolvable f- measure has "
        "no gate), ungated-without-measure, inert-literal (a literal matches "
        "no registered category) and over-broad-literal (a literal matches "
        "several categories). The first, second and fifth are P0 checks and "
        "fail the run; the third, fourth and sixth are P1 checks and are "
        "warnings (P0 = error, P1 = warning, --strict = full run). Coverage is "
        "substring based, as CONTAINSSTRING is. Categories come from the "
        "encoded mapping table; without one the last four checks are skipped. "
        "The baseline file (option baseline) accepts known findings per model "
        "and only shrinks: an entry that no longer applies is reported as "
        "stale."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        base = _load_gate_baseline(self.options.get("baseline"))
        for model in ctx.models:
            out.extend(self._check_model(ctx, model, base))
        return out

    def _check_model(self, ctx: Context, model: SemanticModel, base: dict) -> list[Violation]:
        out: list[Violation] = []
        table_name = self.options["orchestrator_table"]
        measure_name = self.options["orchestrator_measure"]
        and_chain = self.options["and_chain"]
        or_chain = self.options["or_chain"]
        orch = model.get_table(table_name)
        model_id = ctx.model_key(model)
        if model_id.endswith(".SemanticModel"):
            model_id = model_id[: -len(".SemanticModel")]
        if orch is None:
            self.skip(ctx, f"model has no {table_name}.tmdl", model_id)
            return out
        try:
            text = orch.file.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError):
            return out
        file = orch.file
        baseline = str(self.options.get("baseline") or "the baseline file")
        hint = (f"\nRepair: pbip-forge f-filters --model {model_id}"
                "\n        (append-only: existing/client-specific gates are never touched)")

        def add(check: str, msg: str, severity: Severity, obj: Optional[str] = None):
            out.append(self.violation(f"{check}: {msg}", file=file,
                                      obj=f"{model_id}:{obj or check}",
                                      severity=severity))

        declared = declared_gate_measures(text)

        def accepted(key: str) -> list[str]:
            entry = (base.get(key) or {}).get(model_id) or []
            return [str(x) for x in entry]

        # (1) both chains gate the same literals
        and_body = chain_body(text, and_chain, rf"VAR\s+{re.escape(or_chain)}|RETURN")
        or_body = chain_body(text, or_chain, r"VAR\s+|RETURN")
        if and_body is None or or_body is None:
            self.skip(ctx, f"{measure_name} is absent or non-canonical "
                           f"(no {and_chain}/{or_chain})", model_id)
            return out
        and_lits, or_lits = gate_literals(and_body), gate_literals(or_body)
        only_and = sorted(set(and_lits) - set(or_lits))
        only_or = sorted(set(or_lits) - set(and_lits))
        if only_and or only_or:
            add("unpaired-chains",
                f"{model_id}: f-All's AND/OR chains gate different category sets — "
                f"the model filters inconsistently depending on how many categories "
                f"are in scope.\n"
                f"  only in {and_chain} (AND): {only_and or '—'}\n"
                f"  only in {or_chain}   (OR): {only_or or '—'}" + hint,
                Severity.ERROR, "chains")

        # (2) live IF([f-X] > 0 lines name declared measures
        dangling = sorted({name for _line, name in gate_measure_calls(text)
                           if name not in declared})
        if dangling:
            add("undeclared-gate-measure",
                f"{model_id}: f-All gates reference {len(dangling)} f- measure(s) that "
                f"are not declared in {table_name}.tmdl — f-All will fail to evaluate "
                f"for the entire model: {dangling}",
                Severity.ERROR, "gates")

        # (3) to (6) need the registered categories
        mapping = load_mapping(model, prefix=self.options["mapping_prefix"])
        cats = sorted(mapping.categories()) if mapping else []
        if not cats:
            self.skip(ctx, "no decodable z-Map to derive registered categories from",
                     model_id)
            return out

        def gated(cat: str) -> bool:
            return any(lit in cat for lit in and_lits)

        gaps = [c for c in cats if not gated(c) and resolve_gate_measure(c, declared)]
        no_measure = [c for c in cats if not gated(c) and not resolve_gate_measure(c, declared)]
        inert = [lit for lit in and_lits if not any(lit in c for c in cats)]
        broad = {lit: sorted(c for c in cats if lit in c) for lit in and_lits}
        broad = {lit: cs for lit, cs in broad.items() if len(cs) > 1}
        fleet = {str(x) for x in base.get("fleet_inert_literals") or []}

        # (3) a category that owns a filter measure must be gated
        allowed = accepted("coverage_gaps")
        new_gaps = sorted(set(gaps) - set(allowed))
        if new_gaps:
            add("coverage-gap",
                f"{model_id}: {len(new_gaps)} analysis categor(ies) are registered in "
                f"the z-Map and own an f- measure, but f-All does not gate them — "
                f"those categories are silently excluded from filtering: {new_gaps}\n"
                f"  (declared pre-existing gaps for this model: {sorted(allowed) or 'none'})"
                + hint,
                Severity.WARNING, "coverage-gap")
        stale = sorted(set(allowed) - set(gaps))
        if stale:
            add("coverage-gap",
                f"{model_id}: the baseline lists {len(stale)} categor(ies) under "
                f"coverage_gaps that are now gated — the ratchet must tighten. Remove "
                f"them from {baseline}: {stale}",
                Severity.WARNING, "coverage-gap")

        # (4) a category with no filter measure to gate on is a declared gap
        allowed = accepted("ungated_without_measure")
        new_gaps = sorted(set(no_measure) - set(allowed))
        if new_gaps:
            add("ungated-without-measure",
                f"{model_id}: {len(new_gaps)} analysis categor(ies) are registered in "
                f"the z-Map, gated by no f-All line, and own no f- measure the gate "
                f"could reference -- they render ungated and nothing else reports it: "
                f"{new_gaps}\n"
                f"  Either add `f-<Category>` (or the underscored variant) + run "
                f"pbip-forge f-filters, or retire the z-Map rows, or declare the gap "
                f"under ungated_without_measure in {baseline}." + hint,
                Severity.WARNING, "ungated-without-measure")
        stale = sorted(set(allowed) - set(no_measure))
        if stale:
            add("ungated-without-measure",
                f"{model_id}: the baseline lists {len(stale)} categor(ies) under "
                f"ungated_without_measure that are now gated or gone -- the ratchet "
                f"must tighten. Remove them from {baseline}: {stale}",
                Severity.WARNING, "ungated-without-measure")

        # (5) a literal that matches no category never fires
        allowed = accepted("inert_literals")
        new_inert = sorted(set(inert) - set(allowed) - fleet)
        if new_inert:
            add("inert-literal",
                f"{model_id}: {len(new_inert)} f-All gate literal(s) match no "
                f"registered z-Map category, so the gate never fires and the intended "
                f"category renders ungated: {new_inert}\n"
                f"  registered categories: {cats}\n"
                f"  Fix the literal to the z-Map spelling (substring match), or retire "
                f"the line.",
                Severity.ERROR, "inert-literal")
        stale = sorted(set(allowed) - set(inert))
        if stale:
            add("inert-literal",
                f"{model_id}: the baseline lists {len(stale)} literal(s) under "
                f"inert_literals that now match a category -- remove them from "
                f"{baseline}: {stale}",
                Severity.ERROR, "inert-literal")

        # (6) a literal that spans two categories gates the wrong one
        allowed = accepted("over_broad_literals")
        new_broad = sorted(set(broad) - set(allowed))
        if new_broad:
            detail = "; ".join(f"{lit!r} -> {broad[lit]}" for lit in new_broad)
            add("over-broad-literal",
                f"{model_id}: {len(new_broad)} f-All gate literal(s) span more than one "
                f"registered z-Map category, so every category but one is gated on the "
                f"WRONG fact and nothing errors: {detail}\n"
                f"  Split into one exact literal per category, each resolving to its "
                f"own f- measure, or declare the overlap intentional under "
                f"over_broad_literals in {baseline} with a reason.",
                Severity.WARNING, "over-broad-literal")
        stale = sorted(set(allowed) - set(broad))
        if stale:
            add("over-broad-literal",
                f"{model_id}: the baseline lists {len(stale)} literal(s) under "
                f"over_broad_literals that are no longer over-broad -- the ratchet "
                f"must tighten. Remove them from {baseline}: {stale}",
                Severity.WARNING, "over-broad-literal")
        return out


# ---------------------------------------------------------------------------
# f- measure shapes
# ---------------------------------------------------------------------------

_F_REF = r"\[f-[^\]]*\]"

#: The kinds a filter measure can have, and what each one means.
F_KINDS = (
    ("STANDARD", "0/1 filter flag — ISEMPTY/ISINSCOPE/ISFILTERED check on a fact table"),
    ("AGGREGATOR", "rolls up two or more f-measures via + or * into a parent integration filter"),
    ("SWITCH-ROUTER", "SWITCH(TRUE(), ...) dispatching across integrations by analysis category"),
    ("DISPLAY-STRING", "returns a label string for visual titles/headers (lives in w-* tables)"),
    ("EXEMPTED", "named carve-out; legitimate exception to the f-measure pattern rules"),
    ("UNCLASSIFIED", "doesn't fit any bucket — review for bugs, or extend the taxonomy"),
)


def classify_f_measure(expression: str, table: str, display_prefix: str = "w-") -> str:
    expr = expression or ""
    upper = expr.upper()
    if any(k in upper for k in ("ISEMPTY", "ISINSCOPE", "ISFILTERED")):
        return "STANDARD"
    if len(re.findall(_F_REF, expr)) >= 2 and re.search(_F_REF + r"\s*[-+*]\s*\[f-", expr):
        return "AGGREGATOR"
    if "SWITCH(TRUE()" in re.sub(r"\s+", "", expr).upper():
        return "SWITCH-ROUTER"
    if table.startswith(display_prefix) or "CONCATENATEX" in upper:
        return "DISPLAY-STRING"
    return "UNCLASSIFIED"


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
        "the visual filter keeps every row or none. This is a P1 check: it is "
        "a warning, and --strict makes it fail the run. The rule also reports "
        "the inventory of the filter measures (how many there are, how they "
        "are classified, where they live) as info findings."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        prefix = self.options["prefix"]
        exempt = set(self.options["exempt"])
        for model in ctx.models:
            counts = {kind: 0 for kind, _description in F_KINDS}
            elsewhere: list[tuple[str, str]] = []
            in_filters = visible = hidden = 0
            for m in model.all_measures():
                if not m.name.startswith(prefix):
                    continue
                if m.name in exempt:
                    kind = "EXEMPTED"
                else:
                    kind = classify_f_measure(m.expression, m.table,
                                              self.options["display_table_prefix"])
                counts[kind] = counts.get(kind, 0) + 1
                if "f-Filter" in m.table:
                    in_filters += 1
                else:
                    elsewhere.append((m.name, m.table))
                if m.is_hidden:
                    hidden += 1
                else:
                    visible += 1
                if kind == "UNCLASSIFIED":
                    out.append(self.violation(
                        f"{m.table}[{m.name}] fits no known filter-measure shape "
                        f"(existence check, aggregate of f- measures, SWITCH(TRUE()) "
                        f"router or display string); add the existence check, or list "
                        f"it under exempt.",
                        file=m.file, line=m.line, obj=m.full_name,
                    ))
            out.extend(self._inventory(ctx, model, counts, in_filters, elsewhere,
                                       visible, hidden))
        return out

    def _inventory(self, ctx: Context, model: SemanticModel, counts: dict,
                   in_filters: int, elsewhere: list[tuple[str, str]],
                   visible: int, hidden: int) -> list[Violation]:
        """The filter-measure inventory, as info findings."""
        total = sum(counts.values())
        key = ctx.model_key(model)
        out = [self.violation(
            f"F-Measure Pattern Classification: Total f-measures: {total}",
            obj=key, severity=Severity.INFO)]
        for kind, description in F_KINDS:
            out.append(self.violation(
                f"{kind:14s}: {counts.get(kind, 0):4d}  {description}",
                obj=key, severity=Severity.INFO))
        if total:
            coverage = (f"F-Measure Coverage Analytics: Total f- measures: {total}; "
                        f"In f-Filters table: {in_filters} "
                        f"({in_filters / total * 100:.1f}%); "
                        f"In other tables: {len(elsewhere)}; "
                        f"Visible: {visible} ({visible / total * 100:.1f}%); "
                        f"Hidden: {hidden}")
        else:
            coverage = (f"F-Measure Coverage Analytics: Total f- measures: 0; "
                        f"In f-Filters table: 0; In other tables: 0; "
                        f"Visible: 0; Hidden: 0")
        out.append(self.violation(coverage, obj=key, severity=Severity.INFO))
        for name, table in elsewhere[:5]:
            out.append(self.violation(f"{name} (in {table})", obj=key,
                                      severity=Severity.INFO))
        if elsewhere:
            out.append(self.violation("Recommendation: Move to f-Filters table for "
                                      "consistency", obj=key, severity=Severity.INFO))
        return out
