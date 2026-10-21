"""Declared project contracts. IDs C0xx.

Some objects and shapes are deliberate and fragile: a required calculation
group, a text key someone might "align" to int64, a relationship that must
stay inactive, a field-parameter row that must stay in its ordinal gap. None
of these errors in Power BI when broken; the visuals just go wrong. A team
declares them in the configuration and these rules hold the model to them.

Contracts live in the top-level ``contracts`` section of the configuration
(``objects``, ``relationships``, ``fieldparam`` lists) or, for the
relationship rule, in its own ``axes`` and ``reach_guards`` options. Every
entry may name a ``model`` (the ``*.SemanticModel`` folder relative to the
scanned root); without one it applies to every model. With no contracts the
rules report nothing.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from ..model import SemanticModel, Table
from ..parser import parse_endpoint
from .base import Context, Rule, Severity, Violation


def _entries(ctx: Context, section: str, extra: Iterable[dict] = ()) -> list[dict]:
    items = list((ctx.options.get("contracts") or {}).get(section) or [])
    items.extend(extra)
    return [e for e in items if isinstance(e, dict)]


def _models_for(ctx: Context, entry: dict) -> list[SemanticModel]:
    return [m for m in ctx.models if ctx.model_matches(entry.get("model"), m)]


def _model_file(model: SemanticModel):
    return model.definition_path / "model.tmdl"


# ---------------------------------------------------------------------------
# C001 required-model-objects
# ---------------------------------------------------------------------------


class RequiredModelObjectsRule(Rule):
    id = "C001"
    name = "required-model-objects"
    severity = Severity.ERROR
    option_defaults = {"tables": [], "measures": []}
    description = (
        "Infrastructure every report assumes (a format calculation group, a "
        "time-intelligence selector, a helper table) must exist. Configure "
        "'tables' (exact names) and 'measures' (rules: a measure whose name "
        "contains all of 'contains', in a table whose name starts with "
        "'table_prefix'; 'advisory' makes a miss a warning). A missing table "
        "is an error. With no configuration the rule reports nothing."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            names = {t.name for t in model.table_list}
            for wanted in self.options.get("tables") or []:
                if wanted not in names:
                    out.append(self.violation(
                        f"required table '{wanted}' is missing from the model; restore it "
                        f"from version control or the template.",
                        file=_model_file(model), obj=wanted,
                    ))
            for rule in self.options.get("measures") or []:
                prefix = rule.get("table_prefix", "")
                tokens = list(rule.get("contains") or [])
                hit = any(
                    all(tok in m.name for tok in tokens)
                    for t in model.table_list if t.name.startswith(prefix)
                    for m in t.measure_list
                )
                if not hit:
                    out.append(self.violation(
                        f"no measure whose name contains {' and '.join(repr(t) for t in tokens)} "
                        f"exists in a table starting with '{prefix}'"
                        + (" (advisory)" if rule.get("advisory") else "") + ".",
                        file=_model_file(model), obj=f"{prefix}*[{'*'.join(tokens)}]",
                        severity=Severity.WARNING if rule.get("advisory") else None,
                    ))
        return out


# ---------------------------------------------------------------------------
# C002 model-contract-objects
# ---------------------------------------------------------------------------


class ModelContractObjectsRule(Rule):
    id = "C002"
    name = "model-contract-objects"
    severity = Severity.ERROR
    option_defaults = {"objects": []}
    description = (
        "Declared object contracts (contracts.objects): a table, column, "
        "calculated column or measure must exist; a column must keep its "
        "dataType; a calculated column's or measure's DAX must contain every "
        "listed token. Kinds: table_exists, column_exists, column_datatype, "
        "calculated_column_exists, calculated_column_contains, "
        "measures_exist, measure_contains."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for entry in _entries(ctx, "objects", self.options.get("objects") or []):
            for model in _models_for(ctx, entry):
                out.extend(self._one(model, entry))
        return out

    def _one(self, model: SemanticModel, e: dict) -> list[Violation]:
        kind = e.get("kind")
        tname = e.get("table", "")
        table = model.get_table(tname)
        where = _model_file(model)
        if table is None:
            return [self.violation(
                f"contract {kind}: table '{tname}' does not exist.", file=where, obj=tname,
            )]
        if kind == "table_exists":
            return []
        if kind in ("column_exists", "column_datatype", "calculated_column_exists",
                    "calculated_column_contains"):
            col = table.columns.get(e.get("column", ""))
            cname = e.get("column", "")
            if col is None:
                return [self.violation(
                    f"contract {kind}: column {tname}[{cname}] does not exist.",
                    file=table.file, obj=f"{tname}[{cname}]",
                )]
            if kind == "column_datatype" and col.data_type != e.get("dataType"):
                return [self.violation(
                    f"contract: column {tname}[{cname}] must have dataType "
                    f"{e.get('dataType')}, found {col.data_type}.",
                    file=col.file, line=col.line, obj=col.full_name,
                )]
            if kind.startswith("calculated") and not col.is_calculated:
                return [self.violation(
                    f"contract: {tname}[{cname}] must be a calculated column.",
                    file=col.file, line=col.line, obj=col.full_name,
                )]
            if kind == "calculated_column_contains":
                return self._tokens(col.expression or "", e, col.file, col.line, col.full_name)
            return []
        if kind == "measures_exist":
            out = []
            for name in e.get("measures") or []:
                if table.measures.get(name) is None:
                    out.append(self.violation(
                        f"contract: measure {tname}[{name}] does not exist.",
                        file=table.file, obj=f"{tname}[{name}]",
                    ))
            return out
        if kind == "measure_contains":
            m = table.measures.get(e.get("measure", ""))
            if m is None:
                return [self.violation(
                    f"contract: measure {tname}[{e.get('measure')}] does not exist.",
                    file=table.file, obj=f"{tname}[{e.get('measure')}]",
                )]
            return self._tokens(m.expression, e, m.file, m.line, m.full_name)
        return [self.violation(f"unknown contract kind {kind!r}.", file=where)]

    def _tokens(self, text: str, e: dict, file, line, obj) -> list[Violation]:
        missing = [t for t in e.get("tokens") or [] if t not in text]
        if not missing:
            return []
        return [self.violation(
            f"contract: the DAX of {obj} no longer contains {', '.join(repr(t) for t in missing)}.",
            file=file, line=line, obj=obj,
        )]


# ---------------------------------------------------------------------------
# C003 model-contract-relationships
# ---------------------------------------------------------------------------


def _endpoint(text: str) -> tuple[str, str]:
    t, c = parse_endpoint(text)
    return t, c


class ModelContractRelationshipsRule(Rule):
    id = "C003"
    name = "model-contract-relationships"
    severity = Severity.ERROR
    option_defaults = {"axes": [], "reach_guards": []}
    description = (
        "Declared relationship contracts. 'axes': every edge touching a "
        "dimension is one of the sanctioned (table, column, active) edges, "
        "none comes from a forbidden table, and none is reversed. "
        "'reach_guards': guarded tables have no active edge to a fact, "
        "control tables do, the graph has at least min_active_edges active "
        "edges, and the guard measure names every guarded table. "
        "contracts.relationships: 'table_edges' pins how many active edges "
        "leave a table and which one; 'edge_to' pins the edges into an "
        "endpoint and their state."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for axis in self.options.get("axes") or []:
            for model in _models_for(ctx, axis):
                if not (model.definition_path / "relationships.tmdl").is_file():
                    ctx.notes.append(
                        f"C003: {ctx.model_key(model)}: the axis contract for "
                        f"'{axis.get('dimension')}' was skipped: the model has no "
                        f"relationships file."
                    )
                    continue
                out.extend(self._axis(model, axis))
        for guard in self.options.get("reach_guards") or []:
            for model in _models_for(ctx, guard):
                out.extend(self._guard(model, guard))
        for entry in _entries(ctx, "relationships"):
            for model in _models_for(ctx, entry):
                out.extend(self._pin(model, entry))
        return out

    def _where(self, model):
        return model.definition_path / "relationships.tmdl"

    def _axis(self, model: SemanticModel, axis: dict) -> list[Violation]:
        dim = axis.get("dimension", "")
        banned = set(axis.get("forbidden") or [])
        expected = {(s["table"], s["column"]): bool(s.get("active", True))
                    for s in axis.get("sanctioned") or []}
        problems: list[tuple[str, object]] = []
        present: set[tuple[str, str]] = set()
        for rel in model.relationships:
            touches_to, touches_from = rel.to_table == dim, rel.from_table == dim
            if not (touches_to or touches_from):
                continue
            label = f"{rel.from_table}[{rel.from_column}] -> {rel.to_table}[{rel.to_column}]"
            if touches_from:
                problems.append((f"axis {dim}: reversed edge {label} is never sanctioned.", rel))
                continue
            edge = (rel.from_table, rel.from_column)
            if rel.from_table in banned:
                problems.append((
                    f"axis {dim}: edge {label} comes from forbidden table "
                    f"'{rel.from_table}'; remove it.", rel))
                continue
            present.add(edge)
            if edge not in expected:
                problems.append((
                    f"axis {dim}: edge {label} is not in the contract; add it there or "
                    f"remove it.", rel))
            elif expected[edge] is not rel.is_active:
                want = "active" if expected[edge] else "inactive"
                problems.append((f"axis {dim}: edge {label} must be {want}.", rel))
        for table, column in sorted(set(expected) - present):
            problems.append((f"axis {dim}: contracted edge {table}[{column}] -> {dim} is "
                             f"missing.", None))
        out = []
        for message, rel in problems:
            if rel is None:
                out.append(self.violation(message, file=self._where(model), obj=dim))
            else:
                out.append(self.violation(message, file=rel.file, line=rel.line,
                                          obj=f"relationship {rel.rel_id[:8]}"))
        return out

    def _guard(self, model: SemanticModel, g: dict) -> list[Violation]:
        out = []
        fact = g.get("fact", "")
        pairs = {frozenset((r.from_table, r.to_table)) for r in model.relationships if r.is_active}
        where = self._where(model)
        n = g.get("min_active_edges")
        if n is not None:
            active = len(pairs)
            if active < int(n):
                out.append(self.violation(
                    f"reach guard: only {active} active relationship(s) parsed; expected at "
                    f"least {n}. The check would pass vacuously.", file=where,
                ))
        if not any(fact in p for p in pairs):
            out.append(self.violation(
                f"reach guard: no active relationship touches '{fact}'.", file=where, obj=fact,
            ))
        for t in g.get("guarded") or []:
            if frozenset((t, fact)) in pairs:
                out.append(self.violation(
                    f"reach guard: guarded table '{t}' now has an active edge to '{fact}'; "
                    f"update the guard measure and the contract together.",
                    file=where, obj=t,
                ))
        for t in g.get("controls") or []:
            if frozenset((t, fact)) not in pairs:
                out.append(self.violation(
                    f"reach guard: control table '{t}' no longer has an active edge to '{fact}'.",
                    file=where, obj=t,
                ))
        gm = g.get("guard_measure")
        if gm:
            table = model.get_table(gm.get("table", ""))
            m = table.measures.get(gm.get("measure", "")) if table else None
            if m is None:
                out.append(self.violation(
                    f"reach guard: guard measure {gm.get('table')}[{gm.get('measure')}] does not exist.",
                    file=where,
                ))
            else:
                for t in g.get("guarded") or []:
                    if f"'{t}'[" not in m.expression:
                        out.append(self.violation(
                            f"reach guard: {m.full_name} does not name guarded table '{t}'.",
                            file=m.file, line=m.line, obj=m.full_name,
                        ))
        return out

    def _pin(self, model: SemanticModel, e: dict) -> list[Violation]:
        kind = e.get("kind")
        where = self._where(model)
        if kind == "table_edges":
            src = e.get("from_table", "")
            rels = [r for r in model.relationships if r.from_table == src]
            active = [r for r in rels if r.is_active]
            out = []
            want = int(e.get("active", 1))
            if len(active) != want:
                out.append(self.violation(
                    f"contract: '{src}' must have exactly {want} active relationship(s), "
                    f"found {len(active)}.", file=where, obj=src,
                ))
            edge = e.get("active_edge")
            if edge and len(active) == 1:
                r = active[0]
                if (r.from_table, r.from_column) != _endpoint(edge[0]) or (
                        r.to_table, r.to_column) != _endpoint(edge[1]):
                    out.append(self.violation(
                        f"contract: the active relationship of '{src}' must be "
                        f"{edge[0]} -> {edge[1]}.", file=r.file, line=r.line, obj=src,
                    ))
            return out
        if kind == "edge_to":
            target = _endpoint(e.get("to", ""))
            src = e.get("from_table")
            rels = [r for r in model.relationships
                    if (r.to_table, r.to_column) == target and (src is None or r.from_table == src)]
            out = []
            want = int(e.get("count", 1))
            if len(rels) != want:
                out.append(self.violation(
                    f"contract: expected {want} relationship(s) to {e.get('to')}, found {len(rels)}.",
                    file=where, obj=e.get("to"),
                ))
            if "active" in e:
                for r in rels:
                    if r.is_active != bool(e["active"]):
                        state = "active" if e["active"] else "inactive"
                        out.append(self.violation(
                            f"contract: the relationship {r.from_table}[{r.from_column}] -> "
                            f"{e.get('to')} must be {state}.",
                            file=r.file, line=r.line, obj=e.get("to"),
                        ))
            return out
        return [self.violation(f"unknown relationship contract kind {kind!r}.", file=where)]


# ---------------------------------------------------------------------------
# C004 fieldparam-registration-contract
# ---------------------------------------------------------------------------

_ORDINAL_RE = re.compile(r",\s*(\d{3,5})\s*,")
_LABEL_RE = re.compile(r'\(\s*"([^"]*)"')


def _table_lines(table: Table) -> list[str]:
    try:
        return table.file.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def _live(lines: list[str]) -> list[tuple[int, str]]:
    return [(i + 1, ln) for i, ln in enumerate(lines) if not ln.strip().startswith("--")]


def _ordinal(line: str) -> Optional[int]:
    found = _ORDINAL_RE.findall(line)
    return int(found[-1]) if found else None


class FieldParamRegistrationContractRule(Rule):
    id = "C004"
    name = "fieldparam-registration-contract"
    severity = Severity.ERROR
    option_defaults = {"fieldparam": []}
    description = (
        "Declared field-parameter registrations (contracts.fieldparam): rows "
        "of group G are the live lines naming \"G\"; their labels must "
        "include the expected ones (group_labels), their ordinals must stay "
        "inside the group's free gap (group_ordinal_range, column_registered) "
        "and be unique (group_unique_ordinals), and a table must be "
        "referenced by exactly N rows (group_table_rows). A field that is in "
        "the model but in no field parameter is silently unreachable."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for e in _entries(ctx, "fieldparam", self.options.get("fieldparam") or []):
            for model in _models_for(ctx, e):
                out.extend(self._one(model, e))
        return out

    def _one(self, model: SemanticModel, e: dict) -> list[Violation]:
        kind = e.get("kind")
        tname = e.get("table", "")
        table = model.get_table(tname)
        if table is None:
            return [self.violation(
                f"contract {kind}: field-parameter table '{tname}' does not exist.",
                file=_model_file(model), obj=tname,
            )]
        lines = _live(_table_lines(table))
        group = e.get("group")
        rows = [(n, ln) for n, ln in lines if group and f'"{group}"' in ln]
        obj = f"{tname}/{group}" if group else tname
        lo, hi = (e.get("range") or [None, None])[:2]

        def v(msg, line=None):
            return self.violation(msg, file=table.file, line=line, obj=obj)

        if kind == "group_labels":
            labels = set()
            for _n, ln in rows:
                m = _LABEL_RE.search(ln)
                if m:
                    labels.add(m.group(1))
            missing = [lbl for lbl in e.get("labels") or [] if lbl not in labels]
            return [v(f"contract: '{lbl}' is not registered in group {group} of {tname}.")
                    for lbl in missing]
        if kind == "group_ordinal_range":
            marker = e.get("marker", "")
            out = []
            for n, ln in rows:
                if marker in ln:
                    o = _ordinal(ln)
                    if o is not None and not (lo <= o <= hi):
                        out.append(v(f"contract: ordinal {o} in group {group} is outside its "
                                     f"free range {lo}-{hi}.", n))
            return out
        if kind == "group_table_rows":
            ref = e.get("references", "")
            count = sum(1 for _n, ln in rows if ref in ln)
            want = int(e.get("count", 0))
            if count != want:
                return [v(f"contract: expected {want} row(s) of group {group} referencing "
                          f"{ref}, found {count}.")]
            return []
        if kind == "group_unique_ordinals":
            seen: dict[int, int] = {}
            out = []
            for n, ln in rows:
                o = _ordinal(ln)
                if o is None:
                    continue
                if o in seen:
                    out.append(v(f"contract: ordinal {o} is used twice in group {group} "
                                 f"(lines {seen[o]} and {n}).", n))
                else:
                    seen[o] = n
            return out
        if kind == "column_registered":
            col = e.get("column", "")
            groups = e.get("groups") or []
            hits = [(n, ln) for n, ln in lines if col in ln]
            if not hits:
                return [v(f"contract: column '{col}' is not registered in {tname}.")]
            if not any(f'"{g}"' in ln for _n, ln in hits for g in groups):
                return [v(f"contract: column '{col}' is registered, but in none of the "
                          f"groups {', '.join(groups)}.")]
            out = []
            for n, ln in hits:
                for o in (int(x) for x in _ORDINAL_RE.findall(ln)):
                    if lo is not None and not (lo <= o <= hi):
                        out.append(v(f"contract: column '{col}' has ordinal {o}, outside the "
                                     f"free range {lo}-{hi}.", n))
            return out
        return [v(f"unknown field-parameter contract kind {kind!r}.")]
