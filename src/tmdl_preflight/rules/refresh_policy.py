"""Incremental-refresh rules: policy structure (P001) and coverage of
eligible facts (P002). Both read the project's ``refresh_policy`` section."""

from __future__ import annotations

from typing import Optional

from ..edits import EditRefused, TextFile, read_text_file, verified_write
from ..model import SemanticModel
from ..refresh import (
    Eligibility,
    TableLayout,
    eligibility,
    policy_block,
    read_layout,
    structural_problems,
)
from ..roles import FACT_CANDIDATE, name_role
from .base import Context, Rule, Severity, Violation


def _settings(ctx: Context) -> dict:
    cfg = dict(ctx.options.get("refresh_policy") or {})
    cfg.setdefault("window_markers", ["RangeEnd"])
    return cfg


def _model_id(ctx: Context, model: SemanticModel) -> str:
    key = ctx.model_key(model)
    return key[: -len(".SemanticModel")] if key.endswith(".SemanticModel") else key


def _layouts(model: SemanticModel):
    for table in model.table_list:
        try:
            tf = read_text_file(table.file)
        except (OSError, UnicodeDecodeError):
            continue
        yield table, tf, read_layout(tf.lines())


def _fix_only(ctx: Context) -> Optional[str]:
    return ctx.options.get("_fix_only")


class RefreshPolicyRepairRule(Rule):
    id = "P001"
    name = "refresh-policy-repair"
    severity = Severity.ERROR
    fixable = True
    safe = False
    description = (
        "Structure of an existing refreshPolicy: declared before the table's "
        "partition and before table-level annotations; policyType basic; "
        "granularities day, month, quarter or year; periods whole numbers of "
        "at least 1; no unknown properties; a sourceExpression identical, "
        "line for line, to the M partition's source (Power BI requires them "
        "to match, otherwise refreshes fail or reload the wrong slice); and "
        "a windowed source (RangeStart plus a configured window marker, "
        "default RangeEnd). The fixer (unsafe: it runs only when this rule is "
        "selected) repairs both refresh-policy rules: it copies the partition "
        "source into a drifted sourceExpression (fix --only invalid), and adds "
        "the missing policy of an eligible fact P002 reports (fix --only "
        "missing): metadata only for an already windowed source, a rewrite "
        "from refresh_policy.inline_template for a loader call (a full "
        "refresh is then required). Other problems need a human."
    )

    def pending_repairs(self, ctx: Context) -> bool:
        if _fix_only(ctx) not in (None, "missing"):
            return False
        cover = RefreshPolicyCoverageRule()
        return any(cover._missing(ctx, m) for m in ctx.models)

    def _problems(self, ctx: Context):
        cfg = _settings(ctx)
        for model in ctx.models:
            for table, tf, layout in _layouts(model):
                probs = structural_problems(layout, list(cfg["window_markers"]))
                if probs:
                    yield model, table, tf, layout, probs

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for _m, table, _tf, layout, probs in self._problems(ctx):
            for kind, msg in probs:
                v = self.violation(f"{table.name}: {msg}", file=table.file,
                                   line=layout.policy.line + 1, obj=table.name)
                out.append(v)
        return out

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        if _fix_only(ctx) in (None, "invalid"):
            applied.extend(self._realign(ctx))
            ctx.reload()
        if _fix_only(ctx) in (None, "missing"):
            applied.extend(RefreshPolicyCoverageRule().add_missing(ctx))
        return applied

    def _realign(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for _m, table, tf, layout, probs in list(self._problems(ctx)):
            if not any(kind == "identity" for kind, _ in probs):
                continue
            pol, part = layout.policy, layout.m_partitions()[0]
            lines = list(layout.lines)
            src = part.source
            header = "\t\tsourceExpression =" + (" ```" if src.fenced else "")
            new_block = [header] + src.lines(lines) + ([lines[src.end]] if src.fenced else [])
            exp = pol.expression
            lines[exp.header:exp.last] = new_block

            def verify(old: str, new: str, name=table.name) -> None:
                after = read_layout(new.split(tf.newline))
                if any(k == "identity" for k, _ in structural_problems(after, ["RangeStart"])):
                    raise EditRefused(f"{name}: sourceExpression still differs")

            try:
                verified_write(tf, tf.join(lines), verify)
            except EditRefused:
                continue
            applied.append(f"{table.file.name}: sourceExpression of {table.name} realigned with "
                           f"partition {part.name} (refresh the table to apply)")
        return applied


class RefreshPolicyCoverageRule(Rule):
    id = "P002"
    name = "refresh-policy-coverage"
    severity = Severity.WARNING
    opt_in = True
    description = (
        "Every fact table eligible for incremental refresh carries a "
        "refreshPolicy, or is declared in the project's per-model backlog "
        "(refresh_policy.backlog); without one it reloads in full on every "
        "scheduled refresh. Eligible: one import M partition whose source is "
        "already windowed, or that calls the configured date-filter loader "
        "(refresh_policy.loader_function) with a date column and filtering "
        "on. Hand-written sources are listed as info. Backlog entries that "
        "are no longer eligible are stale and reported. The repair belongs "
        "to P001's fixer (fix --select refresh-policy-repair --only missing)."
    )

    def _analyse(self, ctx: Context, model: SemanticModel):
        cfg = _settings(ctx)
        exempt = cfg.get("exempt") or {}
        backlog = set((cfg.get("backlog") or {}).get(_model_id(ctx, model), []))
        verdicts: list[tuple] = []
        for table, tf, layout in _layouts(model):
            if name_role(table.name) != FACT_CANDIDATE or layout.policy is not None:
                continue
            if table.name in exempt:
                continue
            verdicts.append((table, tf, layout, eligibility(layout, cfg)))
        eligible = {t.name for t, _tf, _l, e in verdicts if e.verdict == "eligible"}
        return cfg, backlog, verdicts, eligible

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            _cfg, backlog, verdicts, eligible = self._analyse(ctx, model)
            for table, _tf, layout, e in verdicts:
                line = layout.partitions[0].line + 1 if layout.partitions else None
                if e.verdict == "undecidable":
                    v = self.violation(f"{table.name}: {e.reason}; eligibility for incremental "
                                       f"refresh cannot be decided.", file=table.file, line=line,
                                       obj=table.name, severity=Severity.INFO)
                    v.fixable = False
                    out.append(v)
                elif e.verdict == "eligible" and table.name not in backlog:
                    v = self.violation(
                        f"{table.name} is eligible for incremental refresh ({e.reason}) but has "
                        f"no refreshPolicy, so it reloads in full on every refresh. Add the "
                        f"policy (fix --select refresh-policy-repair --only missing), or "
                        f"declare it in refresh_policy.backlog.",
                        file=table.file, line=line, obj=table.name)
                    v.fixable = True  # repaired by P001's fixer
                    out.append(v)
            for entry in sorted(backlog - eligible):
                v = self.violation(
                    f"stale backlog entry {entry}: it is not an eligible fact without a policy "
                    f"any more; remove it from refresh_policy.backlog.",
                    file=model.definition_path / "tables", obj=entry)
                v.fixable = False
                out.append(v)
        return out

    def _missing(self, ctx: Context, model: SemanticModel) -> list[tuple]:
        cfg, backlog, verdicts, _el = self._analyse(ctx, model)
        return [(cfg, t, tf, layout, e) for t, tf, layout, e in verdicts
                if e.verdict == "eligible" and t.name not in backlog
                and (e.windowed or cfg.get("inline_template"))]

    def add_missing(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        for model in ctx.models:
            for cfg, table, tf, layout, e in self._missing(ctx, model):
                done = self._insert(cfg, table, tf, layout, e)
                if done:
                    applied.append(done)
        return applied

    def _insert(self, cfg: dict, table, tf: TextFile, layout: TableLayout,
                e: Eligibility) -> Optional[str]:
        part = layout.m_partitions()[0]
        if part.source is None:
            return None
        lines = list(layout.lines)
        src = part.source
        note = ""
        if not e.windowed:
            template = cfg.get("inline_template")
            if not template:
                return None
            rendered = str(template).format(view=e.view, date_column=e.date_column,
                                            floor=e.floor, table=table.name)
            body = ["\t\t\t\t" + ln if ln.strip() else "" for ln in rendered.split("\n")]
            closing = lines[src.end] if src.fenced else None
            lines[src.start:src.end] = body
            src_lines, header = body, "\t\tsourceExpression =" + (" ```" if src.fenced else "")
            note = " (source rewritten: a full refresh of the table is required)"
        else:
            src_lines = src.lines(lines)
            header = "\t\tsourceExpression =" + (" ```" if src.fenced else "")
            closing = lines[src.end] if src.fenced else None
        block = policy_block(cfg.get("window") or {}, header, src_lines, closing)
        at = part.line
        top = at
        while top > 0 and not lines[top - 1].strip():
            top -= 1
        lines[top:at] = [""] + block + [""] if top > 0 else block + [""]

        def verify(old: str, new: str) -> None:
            after = read_layout(new.split(tf.newline))
            if after.policy is None or any(
                k in ("identity", "placement") for k, _ in structural_problems(after, ["RangeStart"])
            ):
                raise EditRefused("inserted policy does not validate")

        try:
            verified_write(tf, tf.join(lines), verify)
        except EditRefused:
            return None
        return f"{table.file.name}: refreshPolicy added to {table.name}{note}"
