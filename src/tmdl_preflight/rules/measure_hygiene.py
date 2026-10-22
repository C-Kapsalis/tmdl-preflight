"""Measure visibility, folders, descriptions and filter coverage, plus the
required calculation-group tables. IDs C012 and O008-O015 (all opt-in: they
encode one team's naming conventions)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..categories import (
    MAPPING_TABLE,
    NUMBERED_X_AXIS_GLOBS,
    NON_ATTRIBUTING_GROUPS,
    FactTracer,
    axis_rows,
    category_map,
    load_mapping,
)
from ..edits import EditRefused, read_text_file, verified_write
from ..measure_classes import classify_measure_name, helper_subcategory, is_helper_name
from ..model import Measure, SemanticModel
from ..recognizers import _expression_end
from .base import Context, Rule, Severity, Violation


def _user_facing(m: Measure) -> bool:
    return not is_helper_name(m.name)


class RequiredCalcGroupsRule(Rule):
    id = "C012"
    name = "required-calc-groups"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {
        "format_selector": True,
        "time_intelligence_selector": True,
        "format_table": "z-Selector Format",
        "time_intelligence_table": "z-Selector Time Intelligence Function",
        "names": [],
    }
    description = (
        "The calculation-group tables the report's selectors rely on must "
        "exist (exact names): by default the format selector (z-Selector "
        "Format) and the time-intelligence selector (z-Selector Time "
        "Intelligence Function), each switchable, plus any names listed. "
        "Without them every visual that applies the selector loses its "
        "format or its time logic. All switches off skips the rule. Opt-in: "
        "the rule encodes one team's template, so it runs only when it is "
        "named."
    )

    def _required(self) -> list[str]:
        out = []
        if self.options.get("format_selector"):
            out.append(self.options["format_table"])
        if self.options.get("time_intelligence_selector"):
            out.append(self.options["time_intelligence_table"])
        out += [n for n in self.options.get("names") or [] if n not in out]
        return out

    def disabled_by_policy(self) -> bool:
        return not self._required()

    def skip_reason(self) -> str:
        return "Calculation group validation disabled in policy"

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            required = self._required()
            present = [name for name in required if model.get_table(name) is not None]
            missing = [name for name in required if name not in present]
            for name in missing:
                out.append(self.violation(
                    f"required calculation-group table '{name}' is missing; copy it from "
                    f"the template.", file=model.definition_path / "tables", obj=name))
            ctx.notes.extend(self._report(ctx, model, required, present, missing))
        return out

    def _report(self, ctx: Context, model, required: list[str],
                present: list[str], missing: list[str]) -> list[str]:
        """The summary of the required calculation groups, and the inventory."""
        lines = [
            f"Calculation Group Infrastructure ({ctx.model_key(model)}):",
            f"Required calculation groups: {len(required)}",
            f"Present: {len(present)}",
            f"Missing: {len(missing)}",
        ]
        if present:
            lines.append("Present calculation groups:")
            lines.extend(f"  - {name}" for name in present)
        if missing:
            lines.append("Missing required calculation groups:")
            lines.extend(f"  - {name}" for name in missing)
            lines.append("These are critical for dynamic formatting and time intelligence")
        lines.extend(self._inventory(model))
        return lines

    def _inventory(self, model) -> list[str]:
        """The z-Selector tables of the model: their columns and measures."""
        tables = [t for t in model.table_list if t.name.startswith("z-Selector")]
        lines = [f"Total z-Selector tables: {len(tables)}"]
        for t in tables:
            lines.append(f"{t.name}:")
            lines.append(f"  - Columns: {len(t.column_list)}")
            lines.append(f"  - Measures: {len(t.measure_list)}")
            if t.column_list:
                lines.append("  - Items (columns):")
                lines.extend(f"    - {c.name}" for c in
                             sorted(t.column_list, key=lambda c: c.name))
            if t.name == self.options["format_table"]:
                used = [m.name for m in t.measure_list
                        if "SELECTEDMEASURENAME" in (m.expression or "").upper()]
                lines.append(f"  - Measures using SELECTEDMEASURENAME(): {len(used)}")
                if used:
                    lines.append("  - Measures with format inference:")
                    lines.extend(f"    - {name}" for name in used)
                else:
                    lines.append("  No SELECTEDMEASURENAME() patterns found")
        if not tables:
            lines.append("No z-Selector calculation groups found")
        return lines


class IntermediaryHelperFolderRule(Rule):
    id = "O008"
    name = "intermediary-helper-folder"
    severity = Severity.WARNING
    opt_in = True
    description = (
        "Intermediary helper measures ('-Name') are building blocks other "
        "measures reuse; each needs a display folder so they stay grouped "
        "instead of cluttering the measure list. Opt-in: the rule encodes "
        "one team's template, so it runs only when it is named."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for m in model.all_measures():
                c = classify_measure_name(m.name)
                if c.subcategory == "intermediary_helper" and not (m.display_folder or "").strip():
                    out.append(self.violation(
                        f"intermediary helper {m.full_name} has no displayFolder; give it one.",
                        file=m.file, line=m.line, obj=m.full_name))
        return out


ALWAYS_VISIBLE = [
    "f-All", "f-Slicer", "f-Matrix Title", "i-On-Plot Title", "i-On-Plot Subtitle",
    "i-HTML x/y Plot Specific", "i-HTML x/y Selector-2", "i-Applied Filters",
    "i-Selected Timeframe", "i-Selected Analysis Category", "i-Diagnostic Measures",
    "i-Tooltip", "i-Enhanced Timeframe", "i-Enhanced Timeframe HTML",
    "i-Selected Timeframe HTML",
]


class HelperMeasuresHiddenRule(Rule):
    id = "O009"
    name = "helper-measures-hidden"
    severity = Severity.WARNING
    opt_in = True
    fixable = True
    option_defaults = {"always_visible": list(ALWAYS_VISIBLE)}
    description = (
        "Helper measures (names classified as helpers) are plumbing and must "
        "be hidden, except the ones on the always_visible list that report "
        "pages bind directly. Auto-fix adds isHidden to the measure's "
        "property section. Opt-in: the rule encodes one team's template, so "
        "it runs only when it is named."
    )

    def _offenders(self, ctx: Context, model=None):
        keep = set(self.options.get("always_visible") or [])
        for md in ([model] if model is not None else ctx.models):
            for m in md.all_measures():
                if is_helper_name(m.name) and not m.is_hidden and m.name not in keep:
                    yield m

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            offenders = list(self._offenders(ctx, model))
            for m in offenders:
                out.append(self.violation(
                    f"helper measure {m.full_name} ({helper_subcategory(m.name)}) is visible; "
                    f"hide it (the auto-fix adds isHidden).",
                    file=m.file, line=m.line, obj=m.full_name))
            ctx.notes.extend(self._report(ctx, model, offenders))
        return out

    def _report(self, ctx: Context, model, offenders: list[Measure]) -> list[str]:
        """The visibility summary of the model's helper measures."""
        keep = set(self.options.get("always_visible") or [])
        helpers = [m for m in model.all_measures()
                   if is_helper_name(m.name) and m.name not in keep]
        total = len(helpers)
        hidden = total - len(offenders)
        share = (100.0 * hidden / total) if total else 100.0
        lines = [
            f"Helper Measure Visibility ({ctx.model_key(model)}):",
            f"Total helper-named measures: {total}",
            f"Hidden: {hidden} ({share:.1f}%)",
            f"Visible (need to hide): {len(offenders)}",
        ]
        if offenders:
            lines.append("Helpers currently visible to users (set isHidden=true):")
            ordered = sorted(offenders,
                             key=lambda m: (helper_subcategory(m.name) or "",
                                            m.table, m.name))
            lines.extend(f"  - [{helper_subcategory(m.name)}] {m.full_name}"
                         for m in ordered)
            lines.append("Fix: in TMDL, add `isHidden` (no value) under the measure")
            lines.append("declaration; or set isHidden = true in the JSON if editing")
            lines.append("via the .pbip definition file directly.")
        else:
            lines.append("All helper-named measures are properly hidden.")
        return lines

    def fix(self, ctx: Context) -> list[str]:
        applied: list[str] = []
        by_file: dict[Path, list[Measure]] = {}
        for m in self._offenders(ctx):
            by_file.setdefault(m.file, []).append(m)
        for path, measures in by_file.items():
            tf = read_text_file(path)
            lines = tf.lines()
            inserts = []
            for m in measures:
                decl = m.line - 1
                if decl >= len(lines) or not lines[decl].lstrip().startswith("measure"):
                    continue
                indent = lines[decl][: len(lines[decl]) - len(lines[decl].lstrip())]
                inserts.append((_expression_end(lines, decl) + 1, indent + "\t" + "isHidden", m))
            for at, text, _m in sorted(inserts, key=lambda x: x[0], reverse=True):
                lines.insert(at, text)

            def verify(old: str, new: str, n=len(inserts)) -> None:
                if len(new.split(tf.newline)) - len(old.split(tf.newline)) != n:
                    raise EditRefused("unexpected line count")

            try:
                verified_write(tf, tf.join(lines), verify)
            except EditRefused:
                continue
            applied.extend(f"{path.name}: hid {m.full_name}" for _a, _t, m in inserts)
        return applied


class UnusedHelperMeasuresRule(Rule):
    id = "O010"
    name = "unused-helper-measures"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"frequent_threshold": 5}
    description = (
        "Inventory (never fails): helper measures no expression in the model "
        "and no report file next to it references, and the most used "
        "helpers. Check the other models built from the same template before "
        "deleting one. Opt-in: the rule encodes one team's template, so it "
        "runs only when it is named."
    )

    #: the report files that can name a measure
    REPORT_SUFFIXES = (".json", ".pbir", ".bim")

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            helpers = sorted({m.name for m in model.all_measures() if is_helper_name(m.name)},
                             key=len, reverse=True)
            if not helpers:
                continue
            tmdl_files = sorted(model.definition_path.rglob("*.tmdl"))
            tmdl = "\n".join(p.read_text(encoding="utf-8-sig", errors="replace")
                             for p in tmdl_files)
            report_text = ""
            json_files = 0
            for rep in model.definition_path.parent.parent.glob("*.Report"):
                for p in rep.rglob("*"):
                    if not p.is_file():
                        continue
                    if p.suffix.lower() not in self.REPORT_SUFFIXES:
                        continue
                    json_files += 1
                    report_text += "\n" + p.read_text(encoding="utf-8", errors="replace")
            tmdl_counts: dict[str, int] = {}
            json_counts: dict[str, int] = {}
            for name in helpers:  # longer names first so they claim their matches
                pat = re.escape(f"[{name}]")
                tmdl_counts[name] = len(re.findall(pat, tmdl))
                tmdl = re.sub(pat, " ", tmdl)
                bare = len(re.findall(re.escape(name), report_text))
                report_text = report_text.replace(name, " ")
                json_counts[name] = bare
            counts = {n: tmdl_counts[n] + json_counts[n] for n in helpers}
            unused = sorted(n for n, c in counts.items() if c == 0)
            frequent = sorted((n for n, c in counts.items()
                               if c >= self.options["frequent_threshold"]),
                              key=lambda n: (-counts[n], n))
            if unused:
                out.append(self.violation(
                    f"unused in this model ({len(unused)}): {', '.join(unused)}",
                    file=model.definition_path, obj="unused"))
            if frequent:
                out.append(self.violation(
                    f"frequently used helpers ({len(frequent)}): {', '.join(frequent)}",
                    file=model.definition_path, obj="frequent"))
            ctx.notes.extend(self._report(ctx, model, helpers, tmdl_counts,
                                          json_counts, counts, unused, frequent,
                                          len(tmdl_files), json_files))
        return out

    def _report(self, ctx: Context, model, helpers: list[str],
                tmdl_counts: dict[str, int], json_counts: dict[str, int],
                counts: dict[str, int], unused: list[str], frequent: list[str],
                tmdl_files: int, json_files: int) -> list[str]:
        """The inventory of the helper measures and who uses them."""
        home = {m.name: m.table for m in model.all_measures()
                if m.name in set(helpers)}
        used = [n for n in helpers if counts[n] > 0]
        share = (100.0 * len(used) / len(helpers)) if helpers else 0.0
        lines = [
            f"Helper Measure Dependencies ({ctx.model_key(model)}):",
            f"Scanned {tmdl_files} TMDL + {json_files} JSON/PBIR files in the "
            f"active model + adjacent .Report dirs",
            f"Total helper measures: {len(helpers)}",
            f"Used in active model:  {len(used)} ({share:.1f}%)",
            f"Unused in active model:{len(unused)}",
        ]
        if frequent:
            lines.append("Most frequently referenced (>=5 refs):")
            for name in frequent:
                lines.append(f"  - {home.get(name, '')}[{name}]: {counts[name]} "
                             f"({tmdl_counts[name]} TMDL + {json_counts[name]} JSON)")
        if unused:
            lines.append(f"Unused in active model ({len(unused)}) — candidates for "
                         f"deletion FROM THIS MODEL (rerun with other models to "
                         f"confirm they're unused there too before deleting from "
                         f"the template):")
            for name in sorted(unused):
                lines.append(f"  - {home.get(name, '')}[{name}]")
        else:
            lines.append("Every helper in the active model is referenced somewhere.")
        return lines


class UserFacingMeasureVisibleRule(Rule):
    id = "O011"
    name = "user-facing-measure-visible"
    severity = Severity.ERROR
    opt_in = True
    description = (
        "A measure whose name says it is for report authors (not a helper "
        "name) must not be hidden: hidden, it disappears from the field list "
        "and from Q&A. Either unhide it or rename it with a helper prefix; "
        "decide per measure. Opt-in: the rule encodes one team's template, "
        "so it runs only when it is named."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            facing = [m for m in model.all_measures() if _user_facing(m)]
            noise = [m for m in facing if classify_measure_name(m.name).is_noise]
            hidden = [m for m in facing
                      if not classify_measure_name(m.name).is_noise and m.is_hidden]
            for m in hidden:
                out.append(self.violation(
                    f"user-facing measure {m.full_name} is hidden; unhide it or give it a "
                    f"helper name.", file=m.file, line=m.line, obj=m.full_name))
            ctx.notes.extend(self._report(ctx, model, facing, noise, hidden))
        return out

    def _report(self, ctx: Context, model, facing: list[Measure],
                noise: list[Measure], hidden: list[Measure]) -> list[str]:
        """The visibility summary of the model's user-facing measures."""
        total = len(facing) - len(noise)
        visible = total - len(hidden)
        share = (100.0 * visible / total) if total else 100.0
        lines = [
            f"User-Facing Measure Visibility ({ctx.model_key(model)}):",
            f"Total user-facing-named measures: {total} "
            f"(+{len(noise)} scaffolding names filtered)",
            f"Visible: {visible} ({share:.1f}%)",
            f"Hidden (need to unhide OR rename to helper): {len(hidden)}",
        ]
        if hidden:
            lines.append("User-facing-named measures currently hidden:")
            ordered = sorted(hidden, key=lambda m: (m.table, m.name))
            lines.extend(f"  - {m.full_name}" for m in ordered)
            lines.append("JUDGMENT CALL FOR THE BI DEVELOPER — NOT AUTO-FIXABLE.")
            lines.append("Each entry is per-measure: only the BI dev knows whether the")
            lines.append("measure is (a) genuinely user-facing and was hidden by mistake,")
            lines.append("or (b) actually a helper that should be renamed with a helper")
            lines.append("prefix. There is no safe heuristic that can pick between those")
            lines.append("two outcomes — DO NOT script a bulk unhide or bulk rename.")
            lines.append("")
            lines.append("Per-measure fix:")
            lines.append("  - If genuinely user-facing: remove `isHidden` from the")
            lines.append("    measure declaration in TMDL.")
            lines.append("  - If actually a helper: rename it with a helper prefix")
            lines.append("    (-, _, i-, f-, w-, x-, y-, ...).")
            lines.append("    NB: '#', '^', and 'z-' are NOT helper prefixes — those")
            lines.append("    are user-facing conventions.")
        else:
            lines.append("All user-facing-named measures are visible.")
        return lines


class UserFacingDisplayFolderRule(Rule):
    id = "O012"
    name = "user-facing-display-folder"
    severity = Severity.INFO
    opt_in = True
    description = (
        "Advisory: user-facing measures without a display folder, with the "
        "folder coverage of the model. Opt-in: the rule encodes one team's "
        "template, so it runs only when it is named."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            facing = [m for m in model.all_measures() if _user_facing(m)]
            # a folder counts when the property is there and not empty as
            # written; a whitespace-only value is a folder
            missing = [m for m in facing if not (m.display_folder or "")]
            with_folder = len(facing) - len(missing)
            share = (100.0 * with_folder / len(facing)) if facing else 0.0
            ctx.notes.extend([
                f"Display Folder Organization ({ctx.model_key(model)}):",
                f"User-facing measures: {len(facing)}",
                f"With folders:    {with_folder} ({share:.1f}%)",
                f"Without folders: {len(missing)}",
            ])
            if missing:
                ctx.notes.append("User-facing measures without display folder:")
                ctx.notes.extend(f"  - {m.full_name}" for m in missing)
            if missing:
                out.append(self.violation(
                    f"{len(missing)} of {len(facing)} user-facing measures have no display folder "
                    f"({share:.0f}% covered): {', '.join(m.full_name for m in missing)}",
                    file=model.definition_path, obj="display-folders"))
        return out


class UserFacingMeasureDescriptionRule(Rule):
    id = "O013"
    name = "user-facing-measure-description"
    severity = Severity.INFO
    opt_in = True
    option_defaults = {"enabled": True, "min_length": 10}
    description = (
        "Advisory: user-facing measures (by name, hidden or not) whose /// "
        "description is missing or shorter than min_length characters "
        "(default 10). enabled = false skips the rule. Opt-in: the rule "
        "encodes one team's template, so it runs only when it is named."
    )

    def disabled_by_policy(self) -> bool:
        return self.options.get("enabled") is False

    def skip_reason(self) -> str:
        return "Description validation disabled"

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        floor = int(self.options["min_length"])
        for model in ctx.models:
            facing = [m for m in model.all_measures() if _user_facing(m)]
            missing = [m for m in facing if len((m.description or "").strip()) < floor]
            with_desc = len(facing) - len(missing)
            share = (100.0 * with_desc / len(facing)) if facing else 100.0
            ctx.notes.extend([
                f"User-Facing Measure Descriptions ({ctx.model_key(model)}):",
                f"Total user-facing measures: {len(facing)}",
                f"With descriptions:    {with_desc} ({share:.1f}%)",
                f"Without descriptions: {len(missing)}",
            ])
            if missing:
                ctx.notes.append("Measures needing descriptions:")
                ctx.notes.extend(f"  - {m.full_name}" for m in missing)
                out.append(self.violation(
                    f"{len(missing)} of {len(facing)} user-facing measures lack a description of "
                    f"at least {floor} characters: {', '.join(m.full_name for m in missing)}",
                    file=model.definition_path, obj="descriptions"))
        return out


class TableDescriptionCoverageRule(Rule):
    id = "O014"
    name = "table-description-coverage"
    severity = Severity.INFO
    opt_in = True
    description = (
        "Advisory: how many tables carry a /// description. Opt-in: the rule "
        "encodes one team's template, so it runs only when it is named."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            tables = model.table_list
            described = sum(1 for t in tables if (t.description or "").strip())
            share = (100.0 * described / len(tables)) if tables else 0.0
            ctx.notes.extend([
                f"Table Documentation Coverage ({ctx.model_key(model)}):",
                f"Total tables: {len(tables)}",
                f"With descriptions: {described} ({share:.1f}%)",
                f"Without descriptions: {len(tables) - described}",
            ])
            out.append(self.violation(
                f"{described} of {len(tables)} tables have a description ({share:.0f}%)",
                file=model.definition_path, obj="table-descriptions"))
        return out


_SENSORS = ("ISFILTERED", "ISINSCOPE", "ISEMPTY", "ISCROSSFILTERED", "HASONEVALUE", "HASONEFILTER")


def _strip_dax_comments(text: str) -> str:
    out, i, n = [], 0, len(text)
    quote: Optional[str] = None
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if text.startswith(("--", "//"), i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _sensor_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for m in re.finditer(r"\b(" + "|".join(_SENSORS) + r")\s*\(", text, re.IGNORECASE):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        spans.append((m.end(), i))
    return spans


def reads_data(expression: str, fact: str) -> bool:
    """True when ``fact`` is read outside a sensor function (ISEMPTY, ...)."""
    text = _strip_dax_comments(expression or "")
    spans = _sensor_spans(text)
    pats = [re.escape("'" + fact.replace("'", "''") + "'")]
    if re.fullmatch(r"[A-Za-z_]\w*", fact):
        pats.append(r"(?<![\w'\[])" + re.escape(fact) + r"(?![\w'])")
    for pat in pats:
        for m in re.finditer(pat, text):
            if not any(a <= m.start() < b for a, b in spans):
                return True
    return False


class FactTableFilterCoverageRule(Rule):
    id = "O015"
    name = "fact-table-filter-coverage"
    severity = Severity.ERROR
    opt_in = True
    option_defaults = {"filter_prefix": "f-", "mapping_table": MAPPING_TABLE,
                       "axis_globs": list(NUMBERED_X_AXIS_GLOBS)}
    description = (
        "Every fact table a user-facing measure reads (directly or through "
        "other measures) must also be read by some visual-filter measure "
        "(f- prefix); otherwise visual-level filters never narrow that "
        "fact's rows. Facts reached only through the analysis-category "
        "mechanism (an axis measure whose group maps to a category) are "
        "exempt. pbip-forge can write the missing filter measure. Opt-in: "
        "the rule encodes one team's template, so it runs only when it is "
        "named."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        prefix = self.options["filter_prefix"]
        for model in ctx.models:
            tracer = FactTracer(model)
            consumers: dict[str, list[str]] = {}
            covered: set[str] = set()
            for m in model.all_measures():
                facts = tracer.trace(m.name)
                if m.name.startswith(prefix):
                    covered |= facts
                elif _user_facing(m):
                    for f in facts:
                        consumers.setdefault(f, []).append(m.name)
            uncovered = sorted(set(consumers) - covered)
            exempt: list[str] = []
            if uncovered:
                for f in uncovered:
                    if self._exempt(model, f, consumers[f], tracer):
                        exempt.append(f)
                uncovered = [f for f in uncovered if f not in exempt]
            unused = sorted(set(tracer.facts) - set(consumers))
            ctx.notes.extend(self._report(model, tracer, consumers, covered,
                                          uncovered, exempt, unused))
            for f in uncovered:
                names = ", ".join(sorted(set(consumers[f])))
                table = model.get_table(f)
                model_key = model.definition_path.parent.name
                out.append(self.violation(
                    f"fact table {f} is read by user-facing measures ({names}) but by no {prefix} "
                    f"filter measure, so visual filters never narrow its rows. Add a filter "
                    f"measure (pbip-forge f-filters --model {model_key} writes "
                    f"int(not ISEMPTY('{f}'))).",
                    file=table.file if table else model.definition_path, obj=f))
        return out

    def _report(self, model: SemanticModel, tracer: FactTracer,
                consumers: dict[str, list[str]], covered: set[str],
                uncovered: list[str], exempt: list[str],
                unused: list[str]) -> list[str]:
        """The informational report beside the findings.

        The counts say how much of the model's fact surface is covered, and
        the lists say which fact is which. An exempt fact and an unused
        fact never fail: they are reported so that a reader can see why
        nothing was said about them.
        """
        facts = sorted(tracer.facts)
        consumed = sorted(consumers)
        key = model.definition_path.parent.name
        out = [
            "",
            f"Fact-Table Completeness ({key}):",
            f"Fact tables identified:                {len(facts)}",
            f"Consumed by user-facing measures:      {len(consumed)}",
            f"Reachable via some f-measure:          "
            f"{len([f for f in facts if f in covered])}",
            f"Uncovered (consumed, no f-measure):    {len(uncovered)}",
            f"Unused (no user-facing consumer):      {len(unused)}",
        ]
        if uncovered:
            out.append(
                "Fact tables consumed by user-facing measures, no f-coverage:")
            for f in uncovered:
                names = consumers.get(f) or []
                out.append(f"  - {f}  ({len(names)} user-facing consumer(s))")
                for name in names:
                    home = tracer.by_name[name]
                    out.append(f"      e.g. {home.table}[{name}]")
        if exempt:
            out.append(
                "Gated via the z-Map-driven f-Analysis Category mechanism "
                "(no per-fact f-measure needed, not gating):")
            for f in exempt:
                out.append(f"  - {f}")
        if unused:
            out.append("Fact tables with no user-facing consumer (not gating):")
            for f in unused:
                out.append(f"  - {f}")
        return out

    def _exempt(self, model: SemanticModel, fact: str, consumers: list[str],
                tracer: FactTracer) -> bool:
        """Is the fact gated through the analysis-category mechanism?

        The forge's gap-fill planner decides this the same way: an x-row
        measure with a mapped group that reads the fact DIRECTLY (a data
        read, not only inside a sensor) means the fact is already gated, so
        no f- measure is owed. The x-row measure must be user-facing; a
        helper on an x row is the model's own business.
        """
        mapping = load_mapping(model, name=self.options["mapping_table"])
        if mapping is None:
            return False
        cmap = category_map(mapping.rows, NON_ATTRIBUTING_GROUPS)
        for row in axis_rows(model, self.options["axis_globs"]):
            if not cmap.get(row.group or ""):
                continue
            m = tracer.by_name.get(row.target)
            if m is None or not _user_facing(m):
                continue
            if reads_data(m.expression, fact):
                return True
        return False
