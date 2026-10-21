"""Console reports for the rules whose reference scripts print their own.

A few rules come from scripts that wrote a report of their own instead of
a list of findings: the lineage repair, the misordered-property repair, the
dangling-description sweep, the comment-spacing cleanup and the TMDL file
validation. Their output is part of the contract, so it is rendered here,
in the same layout, and printed before the tool's own summary.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .rules.base import Context, Rule, Severity, Violation
from .recognizers import attach_descriptions

RULE = "=" * 80

#: The kinds a lineage tag can belong to, as the reference named them.
_LINEAGE_KINDS = ("table", "column", "partition", "relationship")
_DECL_RE = re.compile(r"^\s*(table|column|partition|relationship)\b")


def _rule_context(lines: list[str], line_no: int) -> str:
    """The declaration that owns the tag on ``line_no`` (1-based): the kind
    and the declaration line, looked up within 20 lines above. ``unknown``
    when there is none."""
    for idx in range(line_no - 2, max(-1, line_no - 21), -1):
        m = _DECL_RE.match(lines[idx])
        if m:
            return f"{m.group(1)}:{lines[idx].strip()}"
    return "unknown"


# ---------------------------------------------------------------------------
# M003: duplicate lineage tags
# ---------------------------------------------------------------------------


def lineage_report(ctx: Context, rule: Rule, dry_run: bool) -> list[str]:
    """The lineage repair's own report, in the reference's layout."""
    models = list(ctx.models)
    out: list[str] = []
    if len(models) > 1:
        out.append(RULE)
        out.append("SCANNING ALL MODELS FOR DUPLICATE LINEAGE TAGS")
        out.append(RULE)
        out.append("")
        out.append(f"Found {len(models)} model(s)")
        out.append("")
    plan = rule.last_plan or rule.plan(ctx)
    total_fixes = 0
    for model, plan_for_model in plan:
        if len(models) > 1:
            out.append("")
            out.append(RULE)
            out.append(f"Checking: {model.definition_path.parent.name}")
            out.append(RULE)
            out.append("")
        block, fixed = _lineage_model_block(model, plan_for_model, dry_run)
        out.extend(block)
        total_fixes += fixed
    if len(models) > 1:
        out.append("")
        out.append(RULE)
        out.append("SUMMARY")
        out.append(RULE)
        out.append(f"Total models checked: {len(models)}")
        out.append(f"Total fixes applied: {total_fixes}")
        out.append("")
    return out


def _lineage_model_block(model, plan_for_model: dict, dry_run: bool) -> tuple[list[str], int]:
    out = [RULE, "FIX DUPLICATE LINEAGE TAGS", RULE,
           f"Model: {model.definition_path}",
           f"Mode: {'DRY RUN' if dry_run else 'LIVE'}", ""]
    if not plan_for_model:
        out.append("✅ No duplicate lineage tags found!")
        out.append("")
        return out, 0
    out.append(f"❌ Found {len(plan_for_model)} duplicate lineage tag(s)")
    out.append("")
    lines_cache: dict[Path, list[str]] = {}
    fixed = 0
    for tag, entries in plan_for_model.items():
        out.append(f"Duplicate tag: {tag}")
        out.append(f"  Found in {len(entries)} locations:")
        by_file: dict[Path, list] = {}
        for occ, _new_tag in entries:
            by_file.setdefault(occ.file, []).append(occ)
        for file, occs in by_file.items():
            out.append(f"    {file.name}:")
            for occ in occs:
                out.append(f"      Line {occ.line}: "
                           f"{_lineage_context(lines_cache, file, occ.line)}")
        for index, (occ, new_tag) in enumerate(entries[1:], start=2):
            out.append(f"  → Fixing occurrence {index}: {occ.file.name}")
            out.append(f"    Old tag: {tag}")
            out.append(f"    New tag: {new_tag}")
            fixed += 1
        out.append("")
    if dry_run:
        out.append(f"DRY RUN: Would fix {len(plan_for_model)} duplicate lineage tag(s)")
    else:
        out.append(f"✅ Fixed {fixed} duplicate lineage tag occurrence(s)")
        out.append(f"   Affected {len(plan_for_model)} unique lineage tags")
    out.append("")
    return out, fixed


def _lineage_context(cache: dict[Path, list[str]], file: Path, line_no: int) -> str:
    if file not in cache:
        try:
            cache[file] = file.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError):
            cache[file] = []
    return _rule_context(cache[file], line_no)


# ---------------------------------------------------------------------------
# M011: simple property after a child block
# ---------------------------------------------------------------------------


def misordered_report(ctx: Context, violations: list[Violation], dry_run: bool) -> list[str]:
    """The misordered-property repair's own report, in the reference's layout."""
    verb = "would fix" if dry_run else "fixed"
    by_file: dict[str, list[Violation]] = {}
    for v in violations:
        by_file.setdefault(_relative(ctx, v.file), []).append(v)
    out: list[str] = []
    total = 0
    for path in sorted(by_file):
        found = by_file[path]
        out.append(f"{verb} {path} ({len(found)}):")
        for v in found:
            token, owner = _split_owner(v)
            out.append(f"    [{token}] in {owner}")
        total += len(found)
    out.append("")
    out.append(f"{'Would fix' if dry_run else 'Fixed'} {total} issue(s) across "
               f"{len(by_file)} file(s).")
    return out


def _split_owner(v: Violation) -> tuple[str, str]:
    """The property token and the object name a M011 finding names."""
    m = re.match(r"property '([^']+)' comes after a nested section", v.message)
    token = m.group(1) if m else "property"
    return token, v.obj or ""


# ---------------------------------------------------------------------------
# M013: dangling /// descriptions
# ---------------------------------------------------------------------------


def dangling_report(ctx: Context, violations: list[Violation],
                    fixed: bool) -> list[str]:
    """The dangling-description sweep's own report, in the reference's layout."""
    out: list[str] = []
    by_file: dict[str, list[Violation]] = {}
    for v in violations:
        by_file.setdefault(_relative(ctx, v.file), []).append(v)
    for path in sorted(by_file):
        found = by_file[path]
        out.append(f"DANGLING /// ({len(found)}): {path}")
        for v in found:
            out.append(f"    line {v.line}: {v.obj or ''}")
        if fixed:
            out.append(f"    -> removed {len(found)} dangling run(s)")
    out.append("")
    if fixed:
        out.append(f"Fixed {len(by_file)} file(s); {len(by_file)} had dangling descriptions.")
    else:
        out.append(f"{len(by_file)} file(s) with dangling `///` descriptions.")
    return out


# ---------------------------------------------------------------------------
# M013: the comment-spacing cleanup (attach mode)
# ---------------------------------------------------------------------------


def attach_report(ctx: Context, rule: Rule, dry_run: bool, verbose: bool) -> list[str]:
    """The comment-spacing cleanup's own report, in the reference's layout.

    A dry run counts the occurrences (a description line followed by at
    least one blank line); a live run counts the blank lines it removed.
    """
    model = ctx.models[0] if ctx.models else None
    table_files = sorted((model.definition_path / "tables").glob("*.tmdl")) if model else []
    out = [RULE, "CLEANUP TMDL COMMENT SPACING", RULE, ""]
    if dry_run:
        out.append("🔍 DRY RUN MODE - No changes will be written")
        out.append("")
    if dry_run:
        found = _attach_occurrences(table_files)
    else:
        found = [(name, blanks) for name, _occurrences, blanks in rule.last_attach]
    for name, count in found:
        if dry_run and not verbose:
            continue
        out.append(f"  ✓ {name}: Removed {count} blank line(s)")
    out.append("")
    out.append(f"Scanned {len(table_files)} tables")
    if not found:
        out.append("✓ No issues found - all tables are clean")
        return out
    total = sum(count for _name, count in found)
    out.append(f"Fixed {len(found)} tables")
    out.append(f"  - {total} blank lines removed")
    out.append("")
    out.append("Files fixed:")
    for name, count in found:
        out.append(f"  - {name}: {count} blank lines")
    if dry_run:
        out.append("")
        out.append("⚠️  Run without --dry-run to apply fixes")
    return out


def _attach_occurrences(table_files: list[Path]) -> list[tuple[str, int]]:
    """The table files that carry a description followed by a blank line,
    with the number of such occurrences."""
    out = []
    for f in table_files:
        try:
            lines = f.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        _new, occurrences, _blanks = attach_descriptions(lines)
        if occurrences:
            out.append((f.name, occurrences))
    return out


# ---------------------------------------------------------------------------
# M017: space indentation
# ---------------------------------------------------------------------------


def validation_report(ctx: Context, violations: list[Violation]) -> list[str]:
    """The TMDL file validation's own report, in the reference's layout."""
    model = ctx.models[0] if ctx.models else None
    folder = model.definition_path.parent.name if model else ""
    table_files = sorted((model.definition_path / "tables").glob("*.tmdl")) if model else []
    out = [RULE, f"VALIDATING TMDL FILES: {folder}", RULE, ""]
    out.append(f"Found {len(table_files)} TMDL files to validate")
    out.append("")
    by_file: dict[Path, list[Violation]] = {}
    for v in violations:
        if v.file is None:
            continue
        by_file.setdefault(v.file, []).append(v)
    errors = 0
    notes = 0
    for file in table_files:
        found = by_file.get(file, [])
        errors += sum(1 for v in found if v.severity != Severity.INFO)
        notes += sum(1 for v in found if v.severity == Severity.INFO)
        if not found:
            continue
        out.append(f"❌ {file.name}:")
        for v in found[:5]:
            out.append(f"   - {v.message}")
        if len(found) > 5:
            out.append(f"   ... and {len(found) - 5} more errors")
        out.append("")
    out.append(RULE)
    out.append("VALIDATION SUMMARY")
    out.append(RULE)
    if errors == 0:
        out.append(f"✅ All {len(table_files)} files passed validation")
        if notes:
            out.append(f"⚠️  {notes} warnings found (not critical)")
    else:
        failing = [f for f in table_files if by_file.get(f)]
        out.append(f"❌ Found {errors} errors in {len(failing)} files:")
        for file in failing[:10]:
            out.append(f"   - {file.name}")
        if len(failing) > 10:
            out.append(f"   ... and {len(failing) - 10} more")
        out.append("")
        out.append("These errors will cause Power BI Desktop to fail opening the file.")
        out.append("Please fix the errors before opening in Power BI.")
    out.extend(_model_summary(model, len(table_files), len(failing) if errors else 0))
    return out


def _model_summary(model, total_files: int, invalid_files: int) -> list[str]:
    """The model's own counts, as the reference's validation summary printed
    them."""
    if model is None:
        return []
    measures = sum(len(t.measure_list) for t in model.table_list)
    tables = len(model.table_list)
    tags = len(model.lineage_tags)
    seen: dict[str, int] = {}
    for occ in model.lineage_tags:
        seen[occ.tag] = seen.get(occ.tag, 0) + 1
    duplicates = sum(1 for n in seen.values() if n > 1)
    valid = max(total_files - invalid_files, 0)
    rate = round((valid / max(total_files, 1)) * 100, 1)
    return [
        "",
        "📊 Model Validation Summary:",
        f"   📁 Total files: {total_files}",
        f"   ✅ Valid files: {valid}",
        f"   ❌ Invalid files: {invalid_files}",
        f"   📊 Total measures: {measures}",
        f"   📋 Total tables: {tables}",
        f"   🏷️  Total lineageTags: {tags}",
        f"   🔄 Duplicate lineageTags: {duplicates}",
        f"   📈 Success rate: {rate}%",
    ]


def _relative(ctx: Context, file: Optional[Path]) -> str:
    """A file's path relative to the scan root."""
    if file is None:
        return ""
    rel = ctx.scan_relative(file)
    if rel:
        return rel
    return file.name


def refused_report(refused: list[str]) -> list[str]:
    """The lines a refused repair prints on standard error.

    A refused repair reads ``ERROR <path>: <reason>``; the path is the
    file's path relative to the scan root."""
    out = []
    for entry in refused:
        parts = entry.split(": ", 2)
        if len(parts) == 3:
            _rule, path, reason = parts
            out.append(f"ERROR {path}: {reason}")
        else:
            out.append(f"ERROR {entry}")
    return out
