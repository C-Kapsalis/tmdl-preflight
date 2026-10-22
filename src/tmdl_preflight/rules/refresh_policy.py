"""Incremental-refresh rules: policy structure (P001) and coverage of
eligible facts (P002). Both read the project's ``refresh_policy`` section."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..backlog import prune_backlog
from ..edits import EditRefused, TextFile, read_text_file, verified_write
from ..model import SemanticModel
from ..refresh import (
    DEFAULT_WINDOW,
    FENCE,
    MULTILINE_TEMPLATE_REASON,
    NO_TEMPLATE_REASON,
    UNFILTERED_REASON,
    WINDOWED_ORPHAN_REASON,
    Eligibility,
    TableLayout,
    eligibility,
    find_loader_call,
    policy_block,
    read_layout,
    render_template,
    structural_problems,
    undecidable_reason,
)
from ..roles import FACT_CANDIDATE, name_role
from .base import Context, Rule, Severity, Violation

#: the configuration section that holds the backlog
BACKLOG_SECTION = "refresh_policy"


def _file_names(model: SemanticModel) -> set[str]:
    return {t.file.name for t in model.table_list}


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


def _exempt_tables(cfg: dict) -> set[str]:
    """The tables the configuration exempts from the coverage rule.

    The exempt list is either a table-to-reason map or a list of
    ``{table, reason}`` tables; both name the same tables.
    """
    exempt = cfg.get("exempt") or {}
    if isinstance(exempt, dict):
        return set(exempt)
    out: set[str] = set()
    for entry in exempt:
        if isinstance(entry, dict) and entry.get("table"):
            out.add(entry["table"])
    return out


@dataclass
class Repair:
    """One table the fixer acted on -- or could not act on."""

    kind: str  # "missing" | "invalid"
    table: str
    file_name: str
    note: str = ""
    reason: str = ""
    metadata_only: bool = False
    data_changed: bool = False
    ok: bool = True


def _window_note(window: dict) -> str:
    """The archive/incremental tail every added policy carries."""
    w = {**DEFAULT_WINDOW, **(window or {})}
    return (f"archive {w['rollingWindowPeriods']}x{w['rollingWindowGranularity']}, "
            f"incremental {w['incrementalPeriods']}x{w['incrementalGranularity']}")


def render_repair_report(repairs: list[Repair]) -> str:
    """The repair report the fixer prints after its edits.

    Only the sections that have something to say are printed.
    """
    done = [r for r in repairs if r.ok]
    failed = [r for r in repairs if not r.ok]
    out: list[str] = []
    if done:
        out.append("")
        out.append(f"REPAIRED {len(done)} table(s):")
        for r in sorted(done, key=lambda r: r.file_name):
            out.append(f"  [{r.kind}] {r.table}: {r.note}")
    if failed:
        out.append("")
        out.append(f"FAILED {len(failed)} table(s) -- repair NOT applied:")
        for r in sorted(failed, key=lambda r: r.file_name):
            out.append(f"  [{r.kind}] {r.table}: {r.reason}")
    metadata = sorted({r.table for r in done if r.metadata_only})
    if metadata:
        out.append("")
        out.append(f"Metadata-only ({len(metadata)} table(s)) -- block reinstated over an "
                   f"already-windowed source, NO refresh owed:")
        for t in metadata:
            out.append(f"  - {t}")
    refresh = sorted({r.table for r in done if r.data_changed})
    if refresh:
        out.append("")
        out.append("=" * 74)
        out.append("(!)  MANUAL XMLA FULL REFRESH REQUIRED -- the partition M source changed")
        out.append("=" * 74)
        out.append("Models refreshed incrementally reload only the last few periods. The "
                   "archive beyond")
        out.append("that window stays STALE OR BLANK for these tables until someone triggers an")
        out.append("XMLA `type=Full` refresh with `applyRefreshPolicy=false`.")
        out.append("Every query still succeeds meanwhile -- that is what makes it expensive.")
        out.append("")
        out.append(f"Tables needing a full refresh ({len(refresh)}):")
        for t in refresh:
            out.append(f"  - {t}")
        out.append("=" * 74)
    return "\n".join(out)


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
                # only the drifted sourceExpression can be repaired mechanically
                v.fixable = kind == "identity"
                out.append(v)
        return out

    def pending_fix_objects(self, ctx: Context, violations: list[Violation]) -> set[str]:
        """The tables the fixer would act on (``fix --check`` counts them)."""
        objs = {v.obj or v.path or "" for v in violations
                if v.rule_id == self.id and v.fixable and v.severity is not Severity.INFO}
        cover = RefreshPolicyCoverageRule()
        for model in ctx.models:
            for _cfg, table, _tf, _layout, _e in cover._missing(ctx, model):
                objs.add(table.name)
        return objs

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        repairs: list[Repair] = []
        if _fix_only(ctx) in (None, "invalid"):
            repairs += self._realign(ctx)
            ctx.reload()
        if _fix_only(ctx) in (None, "missing"):
            repairs += self._add_missing(ctx)
        for r in repairs:
            if r.ok:
                applied.append(f"[{r.kind}] {r.table}: {r.note}")
            else:
                applied.append(f"[{r.kind}] {r.table}: repair NOT applied: {r.reason}")
        report = render_repair_report(repairs)
        if report:
            ctx.fix_notes.append(report)
        self._prune(ctx, repairs)
        return applied

    def _prune(self, ctx: Context, repairs: list[Repair]) -> None:
        """Drop the repaired tables from the configuration's backlog."""
        if ctx.options.get("_no_prune"):
            return
        path = ctx.options.get("_config_path")
        if not path:
            return
        for model in ctx.models:
            names = {r.table for r in repairs
                     if r.ok and r.kind == "missing" and r.file_name in _file_names(model)}
            if not names:
                continue
            count = prune_backlog(Path(path), _model_id(ctx, model), names)
            if count:
                ctx.fix_notes.append(
                    f"\nRatchet: pruned {count} entr(ies) from {Path(path).name} `backlog:`.")

    def _realign(self, ctx: Context) -> list[Repair]:
        repairs: list[Repair] = []
        for _m, table, tf, layout, probs in list(self._problems(ctx)):
            if not any(kind == "identity" for kind, _ in probs):
                continue
            pol, part = layout.policy, layout.m_partitions()[0]
            lines = list(layout.lines)
            src = part.source
            header = "\t\tsourceExpression =" + (" ```" if src.fenced else "")
            new_block = [header] + src.lines(lines) + ([FENCE] if src.fenced else [])
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
            repairs.append(Repair("invalid", table.name, table.file.name,
                                   note=f"realigned sourceExpression to partition '{part.name}'"))
        return repairs

    def _add_missing(self, ctx: Context) -> list[Repair]:
        repairs: list[Repair] = []
        cover = RefreshPolicyCoverageRule()
        for model in ctx.models:
            for cfg, table, tf, layout, e in cover._missing(ctx, model):
                repairs.append(self._insert(cfg, table, tf, layout, e))
        return repairs

    def _insert(self, cfg: dict, table, tf: TextFile, layout: TableLayout,
                e: Eligibility) -> Repair:
        part = layout.m_partitions()[0]
        if part.source is None:
            return Repair("missing", table.name, table.file.name, ok=False,
                          reason="the partition has no source to window")
        lines = list(layout.lines)
        src = part.source
        source_text = "\n".join(src.lines(lines))
        loader = cfg.get("loader_function")
        template = cfg.get("inline_template")
        if not e.windowed:
            if not template:
                return Repair("missing", table.name, table.file.name, ok=False,
                              reason=NO_TEMPLATE_REASON)
            call = find_loader_call(source_text, loader) if loader else None
            if call is None or len(call.args) < 4:
                return Repair("missing", table.name, table.file.name, ok=False,
                              reason=undecidable_reason(loader))
            if call.args[2].strip().lower() == "true" or not call.args[1].strip():
                return Repair("missing", table.name, table.file.name, ok=False,
                              reason=UNFILTERED_REASON)
            rendered = render_template(str(template), e.view or "", e.date_column or "",
                                       e.floor or "", table.name)
            if "\n" in rendered:
                return Repair("missing", table.name, table.file.name, ok=False,
                              reason=MULTILINE_TEMPLATE_REASON)
            # only the loader call is replaced; the rest of the source stands
            new_text = source_text[:call.start] + rendered + source_text[call.end:]
            body = new_text.split("\n")
            lines[src.start:src.end] = body
            note = (f"windowed on {e.date_column} (view '{e.view}', floor {e.floor}); "
                    f"{_window_note(cfg.get('window') or {})}")
            data_changed = True
            metadata_only = False
        else:
            body = src.lines(lines)
            note = ("reinstated refreshPolicy over an already-windowed source "
                    f"(metadata-only); {_window_note(cfg.get('window') or {})}")
            data_changed = False
            metadata_only = True
        header = "\t\tsourceExpression =" + (" ```" if src.fenced else "")
        block = policy_block(cfg.get("window") or {}, header, body, src.fenced)
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
            return Repair("missing", table.name, table.file.name, ok=False,
                          reason="the written policy did not validate")
        return Repair("missing", table.name, table.file.name, note=note,
                      metadata_only=metadata_only, data_changed=data_changed)


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
        exempt = _exempt_tables(cfg)
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
            cfg, backlog, verdicts, eligible = self._analyse(ctx, model)
            loader = cfg.get("loader_function") or "the loader"
            new_gaps = [(table, layout, e) for table, _tf, layout, e in verdicts
                        if e.verdict == "eligible" and table.name not in backlog]
            undecidable = sorted(table.name for table, _tf, _layout, e in verdicts
                                 if e.verdict == "undecidable")
            stale = sorted(backlog - eligible)
            for table, layout, e in new_gaps:
                line = layout.partitions[0].line + 1 if layout.partitions else None
                v = self.violation(f"{table.name}: {e.reason}", file=table.file,
                                   line=line, obj=table.name)
                v.fixable = e.repairable
                out.append(v)
            if new_gaps:
                ctx.notes.append(
                    f"{len(new_gaps)} IR-eligible fact table(s) have NO refreshPolicy and are "
                    f"not declared in {BACKLOG_SECTION} `backlog:` -- each reloads IN FULL on "
                    f"every scheduled refresh:")
            if undecidable:
                out.append(self.violation(
                    f"{_model_id(ctx, model)}: {len(undecidable)} fact table(s) need a "
                    f"HAND-WRITTEN refreshPolicy (M source is not a {loader} call): "
                    f"{', '.join(undecidable)}",
                    file=model.definition_path / "tables", obj=_model_id(ctx, model),
                    severity=Severity.INFO))
            if stale:
                ctx.notes.append(
                    f"{len(stale)} {BACKLOG_SECTION} `backlog:` entr(ies) under "
                    f"'{_model_id(ctx, model)}' are no longer eligible-and-missing (fixed, "
                    f"renamed, or removed). Prune them so the ratchet keeps guarding:")
                for entry in stale:
                    v = self.violation(f"    - {entry}",
                                       file=model.definition_path / "tables", obj=entry)
                    v.fixable = False
                    out.append(v)
        return out

    def _missing(self, ctx: Context, model: SemanticModel) -> list[tuple]:
        """The facts a policy can be added to: eligible, without one.

        The backlog is the gate's declared list of known gaps, not a list of
        tables the repair must leave alone: the repair fixes the gaps and
        prunes the entries it fixed.
        """
        cfg, _backlog, verdicts, _el = self._analyse(ctx, model)
        return [(cfg, t, tf, layout, e) for t, tf, layout, e in verdicts
                if e.verdict == "eligible"]
