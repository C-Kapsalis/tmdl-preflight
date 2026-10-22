"""Command-line interface.

Usage:
    tmdl-preflight check    <path> [--select IDs] [--ignore IDs] [--strict]
                            [--format text|json|github|sarif|markdown] [--json]
                            [--config FILE] [--profile NAME] [--no-config]
                            [--baseline FILE]
    tmdl-preflight fix      <path> (same options as check)
    tmdl-preflight baseline <path> [--output FILE] [--update] [--accept-new]
                             [--config FILE] [--profile NAME] [--no-config]
    tmdl-preflight dead-facts <path> [--capture FILE] [--json]
    tmdl-preflight stats    <path> [--json]
    tmdl-preflight rules    [--json]

Exit codes: 0 clean, 1 violations remain (errors; warnings too with
--strict), 2 usage, path, configuration or baseline errors.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .baseline import (
    BASELINE_FILENAME,
    BaselineError,
    apply_baseline,
    count_identities,
    load_baseline,
    update_counts,
    write_baseline,
)
from .config import Config, ConfigError, load_config
from .engine import PreflightReport, apply_policy, check, fix
from .output import FORMATS, render
from .rules import default_ruleset, full_ruleset
from .rules.base import Context, RuleSet, Violation
from .stats import collect_stats, render_stats


class UsageError(Exception):
    """A problem with the invocation itself (exit code 2)."""


def _parse_id_list(raw: Optional[str]) -> Optional[set[str]]:
    if raw is None:
        return None
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _harden_output_streams() -> None:
    """Never let a violation message crash the run.

    Real models carry object names outside the console's code page (Greek,
    accented, emoji). On such consoles ``print`` would raise
    ``UnicodeEncodeError``; replacing unencodable characters keeps the
    report flowing.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (ValueError, OSError):  # pragma: no cover - exotic streams
                pass


def _print_rules(as_json: bool) -> None:
    ruleset = full_ruleset()
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "id": r.id,
                        "name": r.name,
                        "severity": r.severity.value,
                        "fixable": r.fixable,
                        "description": r.description,
                        "baselinable": r.baselinable,
                        "safe": r.safe if r.fixable else None,
                        "opt_in": r.opt_in,
                        "options": r.option_defaults,
                    }
                    for r in ruleset.rules
                ],
                indent=2,
            )
        )
        return
    for r in ruleset.rules:
        fixable = "auto-fixable" if r.fixable else "check-only"
        opt = "  (opt-in)" if r.opt_in else ""
        print(f"{r.id}  {r.name:30s} {r.severity.value:8s} {fixable}{opt}")
        print(f"      {r.description}")
        print()


def _add_config_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", metavar="FILE",
                   help="read configuration from FILE instead of searching "
                        "for .tmdl-preflight.toml/.json or pyproject.toml")
    p.add_argument("--profile", metavar="NAME",
                   help="merge the [profiles.NAME] table of the configuration")
    p.add_argument("--no-config", action="store_true",
                   help="ignore any configuration file")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tmdl-preflight",
        description="Preflight checks and auto-fixes for Power BI semantic "
        "models in TMDL format (PBIP folders).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--rules", action="store_true", help="list the rule catalog and exit"
    )
    sub = parser.add_subparsers(dest="command")

    path_help = ("a PBIP project root, *.SemanticModel, definition folder, "
                 "or *.Report folder")
    for name, help_text in (
        ("check", "report violations; never modifies files"),
        ("fix", "apply auto-fixes, then re-check (imposition pattern)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("path", help=path_help)
        p.add_argument("--select", help="comma-separated rule ids/names to run "
                                        "(default: all)")
        p.add_argument("--ignore", help="comma-separated rule ids/names to skip")
        p.add_argument("--format", choices=FORMATS, default=None,
                       help="output format (default: text)")
        p.add_argument("--json", action="store_true",
                       help="machine-readable output (same as --format json)")
        p.add_argument("--strict", action="store_true",
                       help="exit nonzero on warnings as well as errors")
        p.add_argument("--baseline", metavar="FILE",
                       help="only fail on violations not recorded in this "
                            "baseline file")
        p.add_argument("--capture-floor", metavar="FILE",
                       help="write the ratchet floor of the selected rules to "
                            "FILE and print what was captured")
        if name == "fix":
            p.add_argument("--dry-run", action="store_true",
                           help="report what fix would change; write nothing")
            p.add_argument("--verbose", action="store_true",
                           help="list every file a dry run would change")
            p.add_argument("--clear-cache", action="store_true",
                           help="after lineage tags change, delete the model's "
                                ".pbi/cache.abf so Desktop does not reuse old tags")
            p.add_argument("--keep-cache", action="store_true",
                           help="after lineage tags change, keep the model's "
                                ".pbi/cache.abf even on a single-model run")
            p.add_argument("--check", action="store_true",
                           help="write nothing; exit with the number of objects the "
                                "selected fixers would act on (capped at 255)")
            p.add_argument("--only", choices=("missing", "invalid"),
                           help="refresh-policy fixers: only add missing policies, or "
                                "only realign invalid ones")
            p.add_argument("--no-prune", action="store_true",
                           help="refresh-policy fixer: keep the backlog entries of the "
                                "tables it repaired")
        _add_config_options(p)

    p_base = sub.add_parser(
        "baseline", help="record today's violations so check --baseline fails only on new ones"
    )
    p_base.add_argument("path", help=path_help)
    p_base.add_argument("--output", metavar="FILE",
                        help=f"baseline file to write (default: <path>/{BASELINE_FILENAME})")
    p_base.add_argument("--update", action="store_true",
                        help="shrink an existing baseline to what still fails; "
                             "never adds entries")
    p_base.add_argument("--accept-new", action="store_true",
                         help="with --update, also add today's new violations")
    p_base.add_argument("--capture-floors", metavar="RULE",
                         help="record the floor file of a ratcheted rule (O007, "
                              "R008 or R016) from today's findings and write it out")
    p_base.add_argument("--select", help=argparse.SUPPRESS)
    p_base.add_argument("--ignore", help=argparse.SUPPRESS)
    _add_config_options(p_base)


    p_stats = sub.add_parser("stats", help="print an inventory of the project (counts only)")
    p_stats.add_argument("path", help=path_help)
    p_stats.add_argument("--json", action="store_true", help="machine-readable output")
    p_stats.add_argument("--measures", action="store_true",
                         help="add the measure-organisation summary (classes, "
                              "field-parameter surfacing, top tables)")
    p_stats.add_argument("--field-parameter-tables", metavar="NAMES",
                         help="comma-separated table names or globs whose NAMEOF rows "
                              "count as surfaced (default: detected field parameters)")

    p_dead = sub.add_parser(
        "dead-facts",
        help="report the fact tables no measure reads, and record them as a floor")
    p_dead.add_argument("path", help=path_help)
    p_dead.add_argument("--capture", metavar="FILE",
                        help="write the current dead fact tables to FILE as the "
                             "floor (a JSON object of model key to table list)")
    p_dead.add_argument("--json", action="store_true", help="machine-readable output")
    _add_config_options(p_dead)

    p_refs = sub.add_parser("comment-refs",
                            help="count ticket references (#123) in model comments")
    p_refs.add_argument("path", help=path_help)
    p_refs.add_argument("--list", nargs="?", const="", metavar="PREFIX",
                        help="list every reference (optionally only models whose key "
                             "starts with PREFIX)")
    p_refs.add_argument("--json", action="store_true", help="machine-readable output")
    p_refs.add_argument("--floors", metavar="FILE", help="the ratchet file to compare with")
    p_refs.add_argument("--tighten", action="store_true",
                        help="lower the floors in FILE to today's counts (never raises)")
    _add_config_options(p_refs)

    p_report = sub.add_parser("report", help="read-only reports (complexity, nameof, relationships)")
    p_report.add_argument("kind", choices=("complexity", "nameof", "relationships"),
                          help="which report")
    p_report.add_argument("path", help=path_help)
    p_report.add_argument("--json", action="store_true", help="machine-readable output")
    p_report.add_argument("--top", type=int, default=10, help="complexity: longest N measures")
    p_report.add_argument("--group-prefix", action="append", metavar="PREFIX",
                          help="nameof: the table-name prefix of the x family "
                               "(default: x-Selector and x-Plot Specific)")

    p_fmt = sub.add_parser("format-resolve",
                           help="resolve the format a measure name gets from a format "
                                "calculation group")
    p_fmt.add_argument("path", help=path_help)
    p_fmt.add_argument("--name", required=True, help="the measure name (SELECTEDMEASURENAME)")
    p_fmt.add_argument("--table", default="z-Selector Format",
                       help="the calculation-group table (default: z-Selector Format)")
    p_fmt.add_argument("--axis", help="a field-parameter table in scope (default: every axis "
                                      "the group branches on, plus none)")
    p_fmt.add_argument("--label", help="the label the field parameter shows (default: the name)")
    p_fmt.add_argument("--compare", metavar="NAME2", help="resolve a second name on the same axes")
    p_fmt.add_argument("--json", action="store_true", help="machine-readable output")

    p_grain = sub.add_parser("grain", help="derive which dimensions can filter a cost fact and "
                                            "its backend facts; check a grain guard against it")
    p_grain.add_argument("path", help=path_help)
    p_grain.add_argument("--cost-fact", default="Campaigns",
                         help="the fact the cost side reads (default: Campaigns)")
    p_grain.add_argument("--backend-fact", action="append", default=None, metavar="TABLE",
                         help="a fact of the population side (repeatable; default: _Users and "
                              "Transactions; naming one replaces the default list)")
    p_grain.add_argument("--permit", action="append", default=[], metavar="TABLE",
                         help="treat this dimension as conformed (repeatable)")
    p_grain.add_argument("--axis-prefix", action="append", default=None, metavar="PREFIX",
                         help="field-parameter tables whose NAMEOF rows expose columns "
                              "(default: y-Selector and y-Plot Specific)")
    p_grain.add_argument("--check", action="store_true", help="check the guard; exit 1 on a gap")
    p_grain.add_argument("--guard-table", help="with --check: the table holding the guard")
    p_grain.add_argument("--guard-measure", default="-helper Cost Grain Valid",
                         help="with --check: the guard measure (default: '-helper Cost Grain "
                              "Valid'; a name starting with '-' needs the --guard-measure=... form)")
    p_grain.add_argument("--emit-config", action="store_true",
                         help="print the blocked/permitted lists as grain-guard-coverage config")
    p_grain.add_argument("--json", action="store_true", help="machine-readable output")

    p_info = sub.add_parser("info", help="derived model facts (analysis categories)")
    p_info.add_argument("path", help=path_help)
    p_info.add_argument("--categories", action="store_true", required=True,
                        help="group ids -> categories from the encoded mapping table, and "
                             "fact table -> categories through the metric-axis measures")
    p_info.add_argument("--mapping-table", default=None,
                        help="the mapping table (default: the first table named z-Map*)")
    p_info.add_argument("--json", action="store_true", help="machine-readable output")

    p_fp = sub.add_parser("fieldparam", help="edit field-parameter rows")
    fp_sub = p_fp.add_subparsers(dest="fp_command", required=True)
    p_retag = fp_sub.add_parser("retag", help="move named rows from one category to another "
                                              "(all or nothing across the files)")
    p_retag.add_argument("files", nargs="+", help="field-parameter table files (.tmdl)")
    p_retag.add_argument("--names", required=True, action="append",
                         help="row display name; comma-separated, or repeat the "
                              "option for a name that holds a comma")
    p_retag.add_argument("--from", dest="old", required=True, help="the current category")
    p_retag.add_argument("--to", dest="new", required=True, help="the new category")
    p_retag.add_argument("--position", type=int, default=4,
                         help="1-based row position of the category (default 4)")

    p_man = sub.add_parser("manifest", help="write a JSON manifest of a model (tables, roles, "
                                             "sources, relationships)")
    p_man.add_argument("model", help="a *.SemanticModel folder, or an entry key of the targets file")
    p_man.add_argument("--out", help="output file (default: <model>/generated/<name>-manifest.json)")
    p_man.add_argument("--check", action="store_true",
                       help="write nothing; exit 1 when the file is missing or stale")
    p_man.add_argument("--targets", help="the target contract file (YAML or JSON)")
    _add_config_options(p_man)

    p_sc = sub.add_parser("schema-check", help="compare a manifest with a warehouse schema "
                                               "snapshot, or prove view columns from SQL files")
    p_sc.add_argument("--manifest", help="a manifest written by 'manifest'")
    p_sc.add_argument("--schema", help="schema snapshot: {table: [{name, type}, ...]}")
    p_sc.add_argument("--out", help="output file (default: <manifest stem>.schema.json)")
    p_sc.add_argument("--ignore-columns", help="JSON {columns: [...], exceptions: [[table, col]]}")
    p_sc.add_argument("--strict", action="store_true",
                      help="exit 1 on missing columns, needs-review, unreachable tables or a "
                           "coverage gap")
    p_sc.add_argument("--project", help="the warehouse project to check against "
                                        "(default: the manifest's own target)")
    p_sc.add_argument("--dataset", help="the warehouse dataset to check against "
                                        "(default: the manifest's own target)")
    p_sc.add_argument("--sql-dir", help="SQL project root (view-column exposure mode)")
    p_sc.add_argument("--entries", help="with --sql-dir: JSON file of {client, table, view, "
                                        "columns} entries")
    p_sc.add_argument("--holdbacks", help="with --sql-dir: holdbacks file path")
    p_sc.add_argument("--write-holdbacks", action="store_true",
                      help="with --sql-dir: write the holdbacks file")
    p_sc.add_argument("--clear-ready", action="store_true",
                      help="with --sql-dir: remove the entries of the clients whose every entry "
                           "is READY")
    p_sc.add_argument("--owner-folder-pattern",
                      help="with --sql-dir: regex whose first group turns an owner id into the "
                           "SQL folder segment that holds its views")

    p_refs2 = sub.add_parser("refs", help="count the places that name an object (model and "
                                          "report), before a rename or delete")
    p_refs2.add_argument("name", help="the object name, exact and case-sensitive")
    p_refs2.add_argument("paths", nargs="*", default=["."], help="folders to scan (default: .)")
    p_refs2.add_argument("--files", action="store_true", help="list the matching files")
    p_refs2.add_argument("--include-nonlive", "--include-history", action="store_true",
                         help="with --files: list the non-live files too")
    p_refs2.add_argument("--history", action="append", metavar="GLOB",
                         help="glob of archived paths (repeatable)")
    p_refs2.add_argument("--loose", action="store_true",
                         help="count NAME] and NAME\" (closing delimiter only; over-counts)")
    p_refs2.add_argument("--targets", help="the target contract file: the live set is the "
                                           "registered model paths")

    p_live = sub.add_parser("live", help="opt-in checks against the published dataset "
                                         "(Power BI REST; --replay answers from recordings)")
    p_live.add_argument("model", help="the local *.SemanticModel folder")
    p_live.add_argument("--workspace", help="workspace (group) id "
                                            "(default: FABRIC_WORKSPACE_ID)")
    p_live.add_argument("--dataset", help="dataset id (default: FABRIC_MODEL_ID)")
    p_live.add_argument("--checks", help="comma-separated live check ids (default: all)")
    p_live.add_argument("--json", action="store_true", help="machine-readable output")
    p_live.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    p_live.add_argument("--record", metavar="DIR", help="write every response to DIR")
    p_live.add_argument("--replay", metavar="DIR", help="answer from responses recorded in DIR "
                                                         "(no network)")
    p_live.add_argument("--no-coupling-check", action="store_true",
                        help="run even when the dataset name does not match the local model")
    p_live.add_argument("--expect-name", help="accept the dataset when this text is part of "
                                              "the workspace name")
    p_live.add_argument("--non-interactive", action="store_true",
                        help="never open a sign-in prompt (service principal only)")
    p_live.add_argument("--cache-ttl", type=float, default=300.0,
                        help="seconds to cache dataset metadata (default 300)")
    _add_config_options(p_live)

    p_rules = sub.add_parser("rules", help="list the rule catalog")
    p_rules.add_argument("--json", action="store_true", help="machine-readable output")
    p_rules.add_argument("--format", choices=("text", "json", "markdown"), default=None,
                         help="catalog format (markdown: a generated docs page)")
    p_rules.add_argument("--out", metavar="FILE", help="write the catalog to FILE")
    p_rules.add_argument("--check", action="store_true",
                         help="with --out: fail if FILE is missing or stale; write nothing")
    return parser


def _context(raw_path: str, exclude: Optional[list[str]] = None,
             exclude_configured: bool = False) -> Context:
    root = Path(raw_path)
    if not root.exists():
        raise UsageError(
            f"cannot find the path {root}. Check the spelling, then pass a "
            f"PBIP project root, a *.SemanticModel folder, a definition "
            f"folder, or a *.Report folder."
        )
    ctx = Context(root, exclude=exclude,
                  exclude_configured=exclude_configured)
    if ctx.is_empty() and ctx.excluded_files:
        return ctx  # everything was excluded on purpose: a clean, empty run
    if ctx.is_empty():
        raise UsageError(
            f"no semantic model or report found under {root}. Expected a "
            f"*.SemanticModel folder with a definition/ subfolder, or a "
            f"*.Report folder; check that the project was saved in PBIP format "
            f"(File > Save as > Power BI project files in Power BI Desktop)."
        )
    return ctx


def _load_config(args, ruleset: RuleSet) -> Config:
    if getattr(args, "no_config", False):
        if args.config or args.profile:
            raise UsageError("--no-config cannot be combined with --config or --profile")
        return Config()
    try:
        return load_config(
            ruleset,
            start=Path(args.path),
            explicit=Path(args.config) if args.config else None,
            profile=args.profile,
        )
    except ConfigError as exc:
        raise UsageError(f"configuration error: {exc}") from exc


def _validate_ids(full: RuleSet, select: Optional[set[str]], ignore: Optional[set[str]]) -> None:
    valid_keys = {r.id.lower() for r in full.rules} | {r.name.lower() for r in full.rules}
    for flag_name, requested in (("--select", select), ("--ignore", ignore)):
        unknown = sorted((requested or set()) - valid_keys)
        if unknown:
            raise UsageError(
                f"{flag_name} names rules that do not exist: {', '.join(unknown)}. "
                f"Run 'tmdl-preflight rules' to list the valid rule ids and names."
            )


#: The rule options that name a file. A relative path in one of them is
#: resolved against the folder of the configuration file that set it, so a
#: run from anywhere finds the same file.
_PATH_OPTIONS = ("floors", "baseline")


def _resolve_option_paths(options: dict, cfg: Config) -> dict:
    """Resolve the relative file paths of a rule's options."""
    if not cfg.source:
        return options
    out = dict(options)
    for name in _PATH_OPTIONS:
        value = out.get(name)
        if not isinstance(value, str) or not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = Path(cfg.source).parent / path
        out[name] = str(path)
    return out


def _effective_ruleset(full: RuleSet, cfg: Config, args) -> RuleSet:
    cli_select = _parse_id_list(args.select)
    cli_ignore = _parse_id_list(args.ignore)
    _validate_ids(full, cli_select, cli_ignore)
    select = cli_select if cli_select is not None else (
        {s.lower() for s in cfg.select} if cfg.select is not None else None
    )
    ignore = (cli_ignore or set()) | {s.lower() for s in cfg.ignore}
    for rule in full.rules:
        if rule.id in cfg.rule_options:
            rule.configure(_resolve_option_paths(cfg.rule_options[rule.id], cfg))
    ruleset = full.select(select, ignore or None)
    if not ruleset.rules:
        raise UsageError(
            "this --select/--ignore combination leaves no rules to run. Loosen "
            "the selection, or run 'tmdl-preflight rules' to list the "
            "available rules."
        )
    return ruleset


def _run(args, mode: str) -> tuple[PreflightReport, RuleSet, Config, Context]:
    full = full_ruleset()
    if not Path(args.path).exists():
        _context(args.path)  # raises the path error before any config error
    cfg = _load_config(args, full)
    ctx = _context(args.path, cfg.exclude, cfg.exclude_configured)
    ctx.options = dict(cfg.sections)
    if cfg.source is not None:
        ctx.options["_config_path"] = str(cfg.source)
    if getattr(args, "only", None):
        ctx.options["_fix_only"] = args.only
    # a fix run that writes nothing: the rules may say what they would do
    ctx.options["_dry_run"] = bool(getattr(args, "dry_run", False))
    if getattr(args, "no_prune", False):
        ctx.options["_no_prune"] = True
    ruleset = _effective_ruleset(full, cfg, args)
    explicit = _parse_id_list(getattr(args, "select", None)) or set()
    if explicit & {"b003", "bookmark-options-schema"}:
        from .rules.report import bookmark_files

        if not bookmark_files(ctx):
            raise UsageError(
                f"error: no bookmark files under {ctx.root} — the glob is "
                "broken, not the repo")
    if mode == "fix" and not getattr(args, "dry_run", False) and not getattr(args, "check", False):
        report = fix(ctx, ruleset, explicit=_parse_id_list(args.select))
    else:
        report = check(ctx, ruleset)
        if mode == "fix":  # dry run: say what would be repaired
            explicit = {e.lower() for e in (_parse_id_list(getattr(args, "select", None)) or set())}
            counts: dict[str, int] = {}
            for rule in ruleset.rules:
                if not _runs_fixer(rule, explicit):
                    continue
                n = len(rule.pending_fix_objects(ctx, report.violations))
                if n:
                    counts[rule.id] = n
                report.notes.extend(rule.dry_run_report(ctx))
            report.would_fix = [
                f"{rid}: {n} violation(s)" for rid, n in sorted(counts.items())
            ]
            dirty = {v.rule_id for v in report.violations}
            for rule in ruleset.rules:
                if not rule.fixable:
                    continue
                if not _runs_fixer(rule, explicit):
                    # the real run skips an unsafe fixer nobody named, and
                    # names it when it had findings to repair; so does this
                    # (a `fix --check` neither lists nor counts it)
                    if getattr(args, "dry_run", False) \
                            and (rule.id in dirty or rule.pending_repairs(ctx)) \
                            and dirty & rule.repaired_rule_ids():
                        report.skipped_fixers.append(rule.id)
                    continue
                report.fix_notes.extend(rule.dry_run_notes(ctx))
    apply_policy(report, cfg, ctx=ctx)
    ran = {r.id for r in ruleset.rules}
    report.unused_exemptions = [e for e in report.unused_exemptions if e.rule in ran]
    report.console = _console_report(args, report, ruleset, ctx)
    return report, ruleset, cfg, ctx


def _console_report(args, report: PreflightReport, ruleset: RuleSet,
                    ctx: Context) -> list[str]:
    """The rules that came from scripts with a report of their own print it
    when they are the one rule the run selected."""
    from . import console

    selected = _parse_id_list(getattr(args, "select", None)) or set()
    if not selected:
        return []
    dry_run = bool(getattr(args, "dry_run", False))
    checking = args.command != "fix"
    lines: list[str] = []
    for rule in ruleset.rules:
        if rule.id.lower() not in selected and rule.name.lower() not in selected:
            continue
        if rule.id == "M003":
            lines.extend(console.lineage_report(ctx, rule, dry_run, checking))
        elif rule.id == "M011":
            lines.extend(console.misordered_report(
                ctx, _found(report, "M011"), dry_run, checking))
        elif rule.id == "M013":
            if rule.options.get("fix_mode") == "attach":
                lines.extend(console.attach_report(
                    ctx, rule, dry_run, bool(getattr(args, "verbose", False)),
                    checking))
            else:
                lines.extend(console.dangling_report(
                    ctx, _found(report, "M013"), not dry_run and not checking))
        elif rule.id == "M017":
            lines.extend(console.validation_report(ctx, report.violations))
    return lines


def _found(report: PreflightReport, rule_id: str) -> list[Violation]:
    """The findings of one rule: the ones the first pass found when a fixer
    ran, the ones still on the report otherwise."""
    found = [v for v in report.found if v.rule_id == rule_id]
    return found or [v for v in report.violations if v.rule_id == rule_id]


def _capture_floor(args, ruleset: RuleSet, ctx: Context) -> int:
    """Write the ratchet floor of the selected rules to a file."""
    from .ratchet import RatchetFileError, load_floors

    target = Path(args.capture_floor)
    floors: dict[str, list[str]] = {}
    if target.is_file():
        try:
            existing = load_floors(target, missing_ok=True)
        except RatchetFileError as exc:
            raise UsageError(str(exc)) from exc
        for key, value in existing.items():
            floors[key] = list(value) if isinstance(value, list) else []
    captured = False
    indent = 2
    for rule in ruleset.rules:
        captured_now = rule.capture_floor(ctx)
        if captured_now is None:
            continue
        captured = True
        indent = rule.floor_indent()
        for key, names in captured_now.items():
            floors[key] = sorted(names)
        print(rule.floor_captured_message(captured_now))
    if not captured:
        raise UsageError(
            "none of the selected rules records a floor; pick a rule that "
            "gates a backlog (for example fact-conformed-dimension-join or "
            "dead-anchor-calendar)"
        )
    ordered = {key: floors[key] for key in sorted(floors)}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(ordered, indent=indent) + "\n", encoding="utf-8",
                      newline="\n")
    print(f"tmdl-preflight: floor written to {target}")
    return 0


def _runs_fixer(rule, explicit: set[str]) -> bool:
    """Would a fix with this selection run the rule's fixer?

    An unsafe fixer (one that changes what a model stores) runs only when
    its rule is named, so a blanket fix -- and a blanket ``fix --check`` --
    leaves it alone.
    """
    if not rule.fixable:
        return False
    if rule.safe:
        return True
    if {rule.id.lower(), rule.name.lower()} & explicit:
        return True
    return rule.unsafe_fix_enabled()


def _cmd_check(args) -> int:
    if args.json and args.format not in (None, "json"):
        raise UsageError(f"--json conflicts with --format {args.format}")
    report, ruleset, cfg, ctx = _run(args, args.command)
    fmt = "json" if args.json else (args.format or "text")
    if getattr(args, "capture_floor", None):
        return _capture_floor(args, ruleset, ctx)
    if args.command == "fix" and getattr(args, "check", False):
        explicit = {e.lower() for e in (_parse_id_list(getattr(args, "select", None)) or set())}
        pending: set[tuple[str, str]] = set()
        listed: set[str] = set()
        for rule in ruleset.rules:
            named = bool({rule.id.lower(), rule.name.lower()} & explicit)
            if not (_runs_fixer(rule, explicit) or named):
                # an unsafe fixer is not part of a blanket fix, so a blanket
                # `fix --check` neither lists nor counts it
                continue
            listed.add(rule.id)
            if not rule.fixable:
                # the rule has no fixer of its own; the fixer that repairs
                # its findings counts the objects itself
                continue
            for obj in rule.pending_fix_objects(ctx, report.violations):
                pending.add((rule.id, obj))
        report.violations = [v for v in report.violations if v.rule_id in listed]
        print(render(fmt, report, Path(args.path), ruleset))
        return min(len(pending), 255)
    if args.baseline:
        try:
            known = load_baseline(Path(args.baseline))
        except BaselineError as exc:
            raise UsageError(str(exc)) from exc
        report.violations, report.baseline = apply_baseline(
            report.violations, known, ruleset, {r.id for r in ruleset.rules}
        )
    if args.command == "fix" and not getattr(args, "dry_run", False):
        _after_fix_cache(args, report, ctx)
    if fmt == "text":
        for line in report.console:
            print(line)
        _refused_lines(report)
    print(render(fmt, report, Path(args.path), ruleset))
    return report.exit_code(strict=args.strict or cfg.strict)


def _refused_lines(report: PreflightReport) -> None:
    """A repair the tool could not prove is reported on standard error, the
    way the reference reported it."""
    from . import console

    for line in console.refused_report(report.refused_fixes):
        print(line, file=sys.stderr)


def _found(report: PreflightReport, rule_id: str) -> list[Violation]:
    """The findings of one rule: the ones the first pass found when a fixer
    ran, the ones still on the report otherwise."""
    found = [v for v in report.found if v.rule_id == rule_id]
    return found or [v for v in report.violations if v.rule_id == rule_id]


def _after_fix_cache(args, report: PreflightReport, ctx: Context) -> None:
    """Desktop keeps a model cache (.pbi/cache.abf) that remembers lineage
    tags. After tags change, delete it — on a single-model run by default,
    because that cache is what makes Desktop reuse the old tags. A
    whole-repository run never deletes a cache; it says that it exists.
    """
    if not any(rid in ("M003", "M004") for rid in report.fixed_rule_ids):
        return
    single = len(ctx.definition_dirs) == 1
    for d in ctx.definition_dirs:
        cache = d.parent / ".pbi" / "cache.abf"
        if not cache.is_file():
            continue
        forced = getattr(args, "clear_cache", False)
        keep = getattr(args, "keep_cache", False)
        if forced or (single and not keep):
            cache.unlink()
            print(f"🗑️  Deleted cache file: {cache}")
            print()
            report.fixes_applied.append(
                f"cache: deleted {cache.parent.parent.name}/.pbi/cache.abf")
        else:
            print(
                f"tmdl-preflight: lineage tags changed; Power BI Desktop may still hold "
                f"the old ones in {cache}. Re-run with --clear-cache to delete it.",
                file=sys.stderr,
            )


def _cmd_capture_floors(args) -> int:
    """Record the floor file of a ratcheted rule from today's findings."""
    from .ratchet import CAPTURED_RULES, capture_floors, write_floors

    wanted = args.capture_floors.strip()
    full = full_ruleset()
    names = {r.id.lower(): r.id for r in full.rules}
    names.update({r.name.lower(): r.id for r in full.rules})
    rule_id = names.get(wanted.lower(), wanted.upper())
    if rule_id not in CAPTURED_RULES:
        raise UsageError(
            f"--capture-floors names a rule whose floor file cannot be captured: "
            f"{args.capture_floors!r}. The rules that can: {', '.join(CAPTURED_RULES)}."
        )
    cfg = _load_config(args, full)
    ctx = _context(args.path, cfg.exclude, cfg.exclude_configured)
    options = cfg.rule_options.get(rule_id, {})
    root = Path(args.path)
    target = Path(args.output) if args.output else (
        (root if root.is_dir() else root.parent) / f"{rule_id.lower()}_floors.json"
    )
    existing: dict = {}
    if rule_id == "R008" and target.exists():
        from .ratchet import load_floors

        existing = load_floors(target, missing_ok=True)
    floors, entries, message = capture_floors(rule_id, ctx, options, existing)
    indent = 1 if rule_id == "R008" else 2
    write_floors(target, floors, indent=indent)
    print(f"{message} -> {target}")
    return 0


def _cmd_baseline(args) -> int:
    if args.capture_floors:
        return _cmd_capture_floors(args)
    if args.select or args.ignore:
        raise UsageError(
            "a baseline must be recorded from a full run; drop --select/--ignore "
            "(a partial run would record, or later forget, only some violations)"
        )
    if args.accept_new and not args.update:
        raise UsageError("--accept-new only makes sense together with --update")
    report, ruleset, _cfg, _ctx = _run(args, "check")
    if any(v.rule_id == "M002" for v in report.violations + report.exempted + report.excluded):
        raise UsageError(
            "refusing to write a baseline while files fail to parse (M002): "
            "a baseline recorded from a partly-read model would hide real "
            "violations later. Fix the M002 findings first."
        )
    root = Path(args.path)
    target = Path(args.output) if args.output else (
        (root if root.is_dir() else root.parent) / BASELINE_FILENAME
    )
    current = count_identities(report.violations, ruleset)
    skipped = [v for v in report.violations if v.rule_id not in
               {r.id for r in ruleset.rules if r.baselinable}]
    if args.update:
        try:
            old = load_baseline(target)
        except BaselineError as exc:
            raise UsageError(str(exc)) from exc
        new = update_counts(old, current, accept_new=args.accept_new)
        removed = sum((old - new).values())
        added = sum((new - old).values())
        write_baseline(target, new, __version__)
        print(
            f"tmdl-preflight: baseline {target}: {sum(new.values())} violation(s) "
            f"recorded, {removed} removed" + (f", {added} added" if args.accept_new else "")
        )
    else:
        if target.exists():
            raise UsageError(
                f"{target} already exists. Use 'baseline --update' to drop fixed "
                f"entries (it never adds new ones unless --accept-new is given), "
                f"or delete the file to record a fresh baseline."
            )
        write_baseline(target, current, __version__)
        print(f"tmdl-preflight: baseline {target}: {sum(current.values())} violation(s) recorded")
    if skipped:
        ids = ", ".join(sorted({v.rule_id for v in skipped}))
        print(
            f"tmdl-preflight: {len(skipped)} violation(s) of rules that can never "
            f"be baselined were not recorded ({ids}); they will still fail every check"
        )
    return 0


def _cmd_rules_markdown(args) -> int:
    from .catalog import REGENERATE, render_markdown_catalog

    if getattr(args, "format", None) not in (None, "markdown"):
        print("tmdl-preflight: --out/--check only apply to --format markdown", file=sys.stderr)
        return 2
    if args.check and not args.out:
        print("tmdl-preflight: --check needs --out FILE", file=sys.stderr)
        return 2
    payload = render_markdown_catalog(full_ruleset())
    if not args.out:
        sys.stdout.write(payload)
        return 0
    target = Path(args.out)
    if args.check:
        problem = None
        if not target.is_file():
            problem = f"MISSING: {target} was never generated."
        elif target.read_bytes() != payload.encode("utf-8"):
            problem = f"DRIFT: {target} is stale."
        if problem:
            print("catalog check FAILED:", file=sys.stderr)
            print(f"  {problem}", file=sys.stderr)
            print(f"  regenerate with: {REGENERATE.format(out=target.as_posix())}", file=sys.stderr)
            return 1
        print("OK: catalog up to date.")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload.encode("utf-8"))
    print(f"Wrote {target}")
    return 0


def _cmd_report(args) -> int:
    from . import nameof, reports

    ctx = _context(args.path)
    models = ctx.models
    if not models:
        raise UsageError("report needs a semantic model; no *.SemanticModel found")
    if args.kind == "complexity":
        data = reports.complexity(models, top=args.top)
        text = reports.render_complexity
        if args.json:
            print(json.dumps({
                "total_measures": data["total_measures"],
                "statistics": data["statistics"],
                "top_10_complex": data["top_10_complex"],
                "all_measures": data["all_measures"],
            }, indent=2))
            return 0
    elif args.kind == "nameof":
        data = nameof.build_report(models[0], args.group_prefix)
        for extra in models[1:]:
            other = nameof.build_report(extra, args.group_prefix)
            data["broken"] += other["broken"]
            for k, v in other["statistics"].items():
                data["statistics"][k] += v
        text = nameof.render_report
        if args.json:
            def _tables(name):
                return {table: {k: v for k, v in row.items() if k != "samples"}
                        for table, row in data["families"].get(name, {}).items()}

            x, y = _tables("x"), _tables("y")
            print(json.dumps({
                "x_selector": x,
                "y_selector": y,
                "summary": {
                    "x_selector_refs": sum(r["nameof_refs"] for r in x.values()),
                    "x_selector_broken": sum(r["broken_refs"] for r in x.values()),
                    "y_selector_refs": sum(r["nameof_refs"] for r in y.values()),
                    "y_selector_broken": sum(r["broken_refs"] for r in y.values()),
                    "total_refs": sum(r["nameof_refs"] for r in x.values())
                    + sum(r["nameof_refs"] for r in y.values()),
                    "total_broken": sum(r["broken_refs"] for r in x.values())
                    + sum(r["broken_refs"] for r in y.values()),
                },
            }, indent=2))
            return 0
    else:
        data = reports.relationships(models[0])
        data["relationships_file"] = str(models[0].definition_path / "relationships.tmdl")
        data["tables_folder"] = str(models[0].definition_path / "tables")
        text = reports.render_relationships
        if args.json:
            print(json.dumps({k: v for k, v in data.items()
                              if k not in ("relationships_file", "tables_folder")},
                             indent=2, ensure_ascii=False))
            return 0
    print(json.dumps(data, indent=2) if args.json else text(data))
    return 0


def _cmd_format_resolve(args) -> int:
    from .format_resolver import branched_axes, decimals, resolve

    ctx = _context(args.path)
    rows = []
    for model in ctx.models:
        table = model.get_table(args.table)
        if table is None:
            continue
        text = table.file.read_text(encoding="utf-8-sig")
        axes = [args.axis] if args.axis else [None, *branched_axes(text)]
        for axis in axes:
            fmt, unresolved = resolve(table.file, args.name, axis=axis, label=args.label)
            row = {"model": ctx.model_key(model), "axis": axis, "format": fmt,
                   "decimals": decimals(fmt), "unresolved": unresolved}
            if args.compare:
                other, _u = resolve(table.file, args.compare, axis=axis)
                row["compare_format"] = other
                row["compare_decimals"] = decimals(other)
                row["decimals_differ"] = decimals(other) != decimals(fmt)
            rows.append(row)
    if args.json:
        print(json.dumps({"name": args.name, "compare": args.compare, "results": rows}, indent=2))
        return 0
    for row in rows:
        where = row["axis"] or "SELECTEDMEASURENAME"
        line = f"  {row['model']:<46} axis={where:<24} {row['format']!r}"
        if args.compare:
            line += f"  ->  {row['compare_format']!r}"
            if row["decimals_differ"]:
                line += "   ⚠ CHANGES"
        print(line)
        if row["unresolved"]:
            print(f"       unresolved: {row['unresolved'][:2]!r}")
    return 0


def _cmd_grain(args) -> int:
    from .rules.grain import DEFAULT_BACKEND_FACTS, DEFAULT_COST_FACT, grain_gaps, grain_verdicts

    ctx = _context(args.path)
    if not ctx.models:
        raise UsageError("grain needs a semantic model")
    model = ctx.models[0]
    cost_fact = args.cost_fact or DEFAULT_COST_FACT
    backend_facts = list(args.backend_fact or DEFAULT_BACKEND_FACTS)
    rows = grain_verdicts(model, cost_fact, backend_facts, args.permit, args.axis_prefix)
    payload: dict = {"dimensions": rows}
    code = 0
    error = None
    gaps: list[str] = []
    if args.check:
        if not args.guard_table:
            error = "--check needs --guard-table"
        else:
            error, gaps = grain_gaps(model, rows, args.guard_table, args.guard_measure)
        payload.update({"error": error, "gaps": gaps})
        code = 1 if (error or gaps) else 0
    if args.emit_config:
        payload["config"] = {
            "blocked_tables": [r["dimension"] for r in rows
                               if r["verdict"] != "CONFORMED" and not r["dimension"].startswith("z-")],
            "permitted_tables": [r["dimension"] for r in rows if r["verdict"] == "CONFORMED"],
        }
    if args.json:
        print(json.dumps(payload, indent=2))
        return code
    print(f"{'dimension table':36} {'->cost':6} {'->backend':30} {'verdict':14} y-Selector cols")
    for r in rows:
        print(f"{r['dimension']:36} {'Y' if r['reaches_cost'] else '-':6} "
              f"{','.join(sorted(r['backend_reached'])) or '-':30} {r['verdict']:14} "
              f"{len(r['exposed_columns'])}")
    if args.check:
        print()
        if error:
            print(error, file=sys.stderr)
        elif gaps:
            print(f"{len(gaps)} coverage gap(s) — absence from the deny-list reads as permission:")
            for g in gaps:
                print("  ", g)
        else:
            print("guard covers every axis-exposed column of every non-conformed dimension table")
    if args.emit_config:
        print(json.dumps(payload["config"], indent=2))
    return code


def _cmd_info(args) -> int:
    from .categories import category_map, fact_table_categories, load_mapping

    ctx = _context(args.path)
    if not ctx.models:
        raise UsageError("info --categories needs a semantic model")
    result: dict = {}
    for model in ctx.models:
        mapping = load_mapping(model, name=args.mapping_table)
        groups = category_map(mapping.rows) if mapping else {}
        facts = fact_table_categories(model, mapping)
        result[ctx.model_key(model)] = {
            "groups": {g: sorted(c) for g, c in sorted(groups.items())},
            "fact_tables": {f: sorted(c) for f, c in sorted(facts.items())},
        }
    payload = next(iter(result.values())) if len(result) == 1 else {"models": result}
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    for key, data in result.items():
        print(f"{key}:")
        for g, cats in data["groups"].items():
            print(f"  group {g}: {', '.join(cats)}")
        for f, cats in data["fact_tables"].items():
            print(f"  fact {f}: {', '.join(cats) or '-'}")
    return 0


def _cmd_fieldparam(args) -> int:
    from .edits import EditRefused
    from .rules.fp_axes import RetagIncomplete, retag_rows

    given = [x for x in (args.names or [])]
    if len(given) == 1:
        names = _parse_list(given[0]) or []
    else:
        names = [x.strip() for x in given if x.strip()]
    if not names:
        raise UsageError("--names needs at least one display name")
    for f in args.files:
        if not Path(f).is_file():
            raise UsageError(f"cannot find the file {f}")
    try:
        done = retag_rows([Path(f) for f in args.files], names, args.old, args.new, args.position)
    except RetagIncomplete as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except EditRefused as exc:
        print(f"tmdl-preflight: {exc}", file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError) as exc:
        print(f"tmdl-preflight: cannot read the file: {exc}", file=sys.stderr)
        return 2
    for name in done:
        print(f"retagged \"{name}\": {args.old} -> {args.new}")
    return 0


def _warn(message: str) -> None:
    """A warning on standard error; the run goes on."""
    print(f"WARNING: {message}", file=sys.stderr)


def _cmd_manifest(args) -> int:
    from .manifest import WarehouseTargetError, build_manifest, find_entry, load_targets, render

    cfg_sections: dict = {}
    if not getattr(args, "no_config", False):
        try:
            cfg = load_config(full_ruleset(), start=Path(args.model) if Path(args.model).exists()
                              else Path.cwd(),
                              explicit=Path(args.config) if args.config else None,
                              profile=args.profile)
        except ConfigError as exc:
            raise UsageError(f"configuration error: {exc}") from exc
        cfg_sections = cfg.sections
    opts = dict(cfg_sections.get("manifest") or {})
    target_opts = dict(opts.get("target") or {})
    targets_path = args.targets or target_opts.get("targets_file")
    targets = load_targets(Path(targets_path), _warn) if targets_path else {}
    targets_name = Path(targets_path).name if targets_path else "the targets file"
    root = Path.cwd()
    model_arg = args.model
    from_registry = False
    if not Path(model_arg).exists() and model_arg in targets:
        from_registry = True
        rel = targets[model_arg].get("model_path")
        if not rel:
            raise UsageError(f"registry entry '{model_arg}' declares no model_path")
        candidate = Path(rel)
        if not candidate.exists() and targets_path:
            candidate = Path(targets_path).parent / rel
        model_arg = str(candidate)
    model_dir = Path(model_arg)
    if not (model_dir / "definition").is_dir():
        if from_registry:
            raise UsageError(f"model path '{model_arg}' has no definition/ directory under {root}")
        raise UsageError(f"MODEL '{model_arg}' is neither a registry client_id nor a "
                         f"<path>/definition model directory under {root}")
    rel = Path(model_arg).as_posix()
    entry = None
    if targets:
        entry = next((find_entry(targets, cand) for cand in
                      (rel, f"{model_dir.parent.name}/{model_dir.name}")
                      if find_entry(targets, cand)), None)
        if entry is None:
            print(f"WARNING: '{rel}' is not in {targets_name} — no client_id; warehouse "
                  f"derived from the model's v-BQ_project only.", file=sys.stderr)
    target_opts["targets_name"] = targets_name
    opts["target"] = target_opts
    try:
        doc = build_manifest(model_dir, rel, entry, opts)
    except WarehouseTargetError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    text = render(doc)
    out = Path(args.out) if args.out else (
        model_dir / opts.get("output_dir_name", "generated")
        / f"{doc['model'].lower()}{opts.get('output_suffix', '-manifest.json')}")
    regen = f"tmdl-preflight manifest {model_arg}" + (f" --out {args.out}" if args.out else "")
    if args.check:
        if not out.is_file():
            print(f"MISSING: {out} was never generated. Run: {regen}", file=sys.stderr)
            return 1
        existing = out.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n")
        if existing != text:
            print(f"DRIFT: {out} is stale. Run: {regen}", file=sys.stderr)
            return 1
        print(f"OK: {out} is up to date.")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(text.encode("utf-8"))
    block = doc.get(target_opts.get("block_key", "bigquery")) or {}
    counts = doc["counts"]
    print(f"Wrote {out}")
    print(f"  model: {doc['model']} ({rel}) -> {block.get('project')}.{block.get('dataset')} "
          f"[{block.get('warehouse')}]")
    print(f"  {counts['tables']} tables, {counts['relationships']} relationships")
    print(f"  by classification: {counts['by_classification']}")
    print(f"  domains: {', '.join(doc['domains'])}")
    return 0


def _cmd_schema_check(args) -> int:
    if args.sql_dir:
        from .sqlviews import (clear_ready, git_head, holdbacks_yaml, judge, load_entries,
                               load_registry, previous_since)

        root = Path(args.sql_dir)
        if not root.is_dir():
            raise UsageError(f"--sql-dir {root} is not a folder")
        if not args.entries:
            raise UsageError("--sql-dir needs --entries FILE")
        try:
            entries = load_entries(Path(args.entries))
            registry = load_registry(Path(args.entries))
        except ValueError as exc:
            raise UsageError(f"cannot read the entries file: {exc}") from exc
        hb = Path(args.holdbacks) if args.holdbacks else (
            Path(args.entries).parent / "deploy_holdbacks.yml")
        if not entries:
            print("outstanding-enrichment registry is empty — nothing to hold.")
            if args.write_holdbacks:
                hb.write_text(holdbacks_yaml([], previous_since(hb)), encoding="utf-8",
                              newline="\n")
                print(f"  holdbacks written: {hb} (0 client(s)) — commit it with the registry")
            return 0
        print(f"SQL state: {root} @ {git_head(root)}")
        verdicts = [judge(e, root, args.owner_folder_pattern) for e in entries]
        for v in verdicts:
            tag = "READY" if v.ready else "HELD "
            print(f"{'✓' if v.ready else '✗'} {tag} {v.owner} · {v.table} · {v.view}")
            print(f"         {v.reason}")
        held = {v.owner for v in verdicts if not v.ready}
        ready = {v.owner for v in verdicts if v.ready} - held
        print()
        print(f"READY to /deploy: {sorted(ready) or '—'}")
        print(f"HELD (view enrichment pending): {sorted(held) or '—'}")
        if args.clear_ready:
            removed = clear_ready(Path(args.entries), registry, ready)
            if removed:
                print(f"\n--clear-ready: removed {removed} READY entr(ies) from {args.entries}")
                print("  ⚠ REMEMBER TO COMMIT the updated registry (it is a committed receipt).")
            else:
                print("\n--clear-ready: nothing to clear (no fully-READY client).")
        if args.write_holdbacks:
            hb.write_text(holdbacks_yaml(entries, previous_since(hb)), encoding="utf-8",
                          newline="\n")
            clients = {str(e.get("client", "")) for e in entries}
            print(f"  holdbacks written: {hb} ({len(clients)} client(s)) — commit it with the "
                  f"registry")
        return 3 if held else 0
    from .reconcile import coverage_gap, failing, load_ignore_columns, reconcile

    if not args.manifest or not args.schema:
        raise UsageError("schema-check needs --manifest and --schema (or --sql-dir and --entries)")
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8-sig"))
        snapshot = json.loads(Path(args.schema).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"cannot read the manifest or the schema snapshot: {exc}") from exc
    for label, doc in (("manifest", manifest), ("schema snapshot", snapshot)):
        if not isinstance(doc, dict):
            raise UsageError(
                f"the {label} is a {type(doc).__name__}, not an object; it "
                f"cannot be read")
    ignore, exceptions = load_ignore_columns(Path(args.ignore_columns) if args.ignore_columns else None)
    doc = reconcile(manifest, snapshot, ignore, exceptions, Path(args.schema).name,
                    args.project, args.dataset)
    mpath = Path(args.manifest)
    if args.out:
        out = Path(args.out)
    elif mpath.name.endswith(".bq.json"):
        out = mpath
    else:
        out = mpath.with_name(mpath.stem + ".bq.json")
    out.write_bytes((json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    block = doc["bq_schema_check"]
    project, dataset = block["project"], block["dataset"]
    print(f"Auth: {block['auth']} [{block['warehouse']} warehouse]")
    print(f"Checked {block['tables_checked']} tables against {project}.{dataset} -> {out}")
    print(f"  FAILING       (PBI column missing in BigQuery): {block['tables_failing']} table(s)")
    print(f"  needs review  (programmatic renames — adjudicate via the M, e.g. /model-bq-drift): "
          f"{block['tables_needs_review']} table(s)")
    print(f"  informational (BQ column not imported in PBI):  {block['tables_informational']} table(s)")
    print(f"  type mismatch (suspicious PBI<->BQ type pairs, informational -- each entry notes "
          f"whether an M Changed Type confirms it): {block['tables_type_mismatch']} table(s)")
    if block["ignored_bookkeeping_columns"]:
        print("  ignored bookkeeping columns (TRASH_COLUMNS):    "
              + ", ".join(block["ignored_bookkeeping_columns"]))
    if block["tables_unreachable"]:
        print(f"  {block['tables_unreachable']} table(s) unreachable — check SA access to "
              f"{project}.{dataset} or pass an accessible --project/--dataset.", file=sys.stderr)
    if block["unresolved_sources"]:
        print("  UNRESOLVED partition sources (extractor gap, fails --strict): "
              + ", ".join(block["unresolved_sources"]), file=sys.stderr)
    if not block["tables_checked"]:
        if coverage_gap(doc):
            print("  COVERAGE: warehouse-backed tables exist but none was checked — refusing to "
                  "call that a pass.", file=sys.stderr)
        else:
            print("  note: this model reads no BigQuery — nothing to check (pass).")
    if block["skipped_no_source"]:
        print("  skipped (no BQ source — DAX/static tables): "
              + ", ".join(block["skipped_no_source"]))
    if (block["tables_failing"] or block["tables_needs_review"] or block["tables_unreachable"]
            or block["unresolved_sources"]):
        print()
        print("  READ-ONLY ROUTING: this sweep never changes BigQuery objects.")
        print("  Inspect the complete M query before classifying any apparent missing column:")
        print("    - deliberate PBI/model change -> open a PBI issue and use the dependency graph "
              "for cleanup")
        print("    - unexpected production table/view regression -> open an issue with the "
              "warehouse owners")
    return 1 if args.strict and failing(doc) else 0


def _cmd_refs(args) -> int:
    from .manifest import load_targets
    from .refs import census, live_roots, render

    targets = load_targets(Path(args.targets), _warn) if args.targets else {}
    live = live_roots(targets) if targets else None
    counts = census(args.name, [Path(p) for p in args.paths], args.history, args.loose, live)
    print(render(args.name, counts, args.loose, args.files, args.include_nonlive))
    return 0


def _cmd_live(args) -> int:
    from . import live

    model_dir = Path(args.model)
    if not (model_dir / "definition").is_dir():
        raise UsageError(f"{model_dir} has no definition/ folder; pass the local *.SemanticModel")
    workspace = args.workspace or os.environ.get("FABRIC_WORKSPACE_ID")
    dataset_id = args.dataset or os.environ.get("FABRIC_MODEL_ID")
    if not workspace or not dataset_id:
        raise UsageError("missing --workspace and --dataset "
                         "(or FABRIC_WORKSPACE_ID and FABRIC_MODEL_ID)")
    options: dict = {}
    if not args.no_config:
        try:
            cfg = load_config(full_ruleset(), start=model_dir,
                              explicit=Path(args.config) if args.config else None,
                              profile=args.profile)
        except ConfigError as exc:
            raise UsageError(f"configuration error: {exc}") from exc
        options = dict(cfg.sections.get("live") or {})
    ids = _parse_list(args.checks) or list(live.CHECKS)
    unknown = [c for c in ids if c not in live.CHECKS]
    if unknown:
        raise UsageError(f"unknown live check(s): {', '.join(unknown)}; known: "
                         f"{', '.join(live.CHECKS)}")
    if args.replay:
        client = live.ReplayClient(Path(args.replay))
    else:
        try:
            token = live.token_provider(interactive=not args.non_interactive)
        except live.LiveUsageError as exc:
            raise UsageError(str(exc)) from exc
        client = live.RestClient(workspace, dataset_id, token, args.cache_ttl)
    if args.record:
        client = live.RecordingClient(client, Path(args.record))
    dataset = client.dataset()
    if not args.no_coupling_check and not live.coupled(dataset, model_dir, args.expect_name):
        print(f"tmdl-preflight: the live dataset '{dataset.get('name')}' (workspace "
              f"'{dataset.get('workspaceName')}') does not look like the local model "
              f"{model_dir.name}; pass --expect-name or --no-coupling-check if it is the same "
              f"model.", file=sys.stderr)
        return 1
    ctx = live.LiveContext(client, live.read_local_model(model_dir), options)
    results = live.run_checks(ctx, ids)
    if args.json:
        print(json.dumps({"dataset": dataset,
                          "checks": [{"id": r.id, "outcome": r.outcome, "message": r.message,
                                      "details": r.details} for r in results]},
                         indent=2, default=str))
    else:
        print(f"dataset: {dataset.get('name')} (workspace {dataset.get('workspaceName')})")
        for r in results:
            for line in r.report:
                print(line)
            print(f"{r.outcome:5s}  {r.id}: {r.message}")
    return live.exit_code(results, args.strict)


def _cmd_stats(args) -> int:
    ctx = _context(args.path)
    stats = collect_stats(ctx)
    if args.measures:
        from .stats import measure_summary, render_measure_summary

        patterns = _parse_list(args.field_parameter_tables)
        summary = measure_summary(ctx, patterns)
        if args.json:
            stats["measures"] = summary
        else:
            print(render_stats(stats))
            print()
            print(render_measure_summary(summary))
            return 0
    print(json.dumps(stats, indent=2) if args.json else render_stats(stats))
    return 0


def _parse_list(raw: Optional[str]) -> Optional[list[str]]:
    if not raw:
        return None
    return [x.strip() for x in raw.split(",") if x.strip()]


def _cmd_dead_facts(args) -> int:
    from .ratchet import write_floors
    from .rules.organization import dead_fact_tables

    ctx = _context(args.path)
    current: dict[str, list[str]] = {}
    for model in ctx.models:
        dead = sorted(name for name, _s in dead_fact_tables(model))
        if dead:
            current[ctx.model_key(model)] = dead
    if args.capture:
        target = Path(args.capture)
        write_floors(target, current)
        entries = sum(len(v) for v in current.values())
        print(f"[dead-fact-table floor] captured {entries} entries across "
              f"{len(current)} models -> {target}")
        return 0
    if args.json:
        print(json.dumps(current, indent=2))
        return 0
    for key in sorted(current):
        for name in current[key]:
            print(f"{key}: {name}")
    return 0


def _cmd_comment_refs(args) -> int:
    from .ratchet import RatchetFileError, load_floors, matching_key, write_floors
    from .rules.comments import CLASSES, root_ticket_refs

    cfg = _load_config(args, full_ruleset())
    ctx = _context(args.path, cfg.exclude, cfg.exclude_configured)
    root = Path(args.path)
    refs = root_ticket_refs(root, ctx)
    counts: dict[str, dict[str, int]] = {}
    for ref in refs:
        counts.setdefault(ref.model, {c: 0 for c in CLASSES})
        counts[ref.model][ref.cls] += 1

    if args.list is not None:
        return _comment_refs_list(args, root, refs)

    floors: dict = {}
    if args.floors:
        try:
            floors = load_floors(args.floors, missing_ok=True)
        except RatchetFileError as exc:
            raise UsageError(str(exc)) from exc

    if args.tighten:
        if not args.floors:
            raise UsageError("--tighten needs --floors FILE")
        if not Path(args.floors).exists():
            print("no floors file yet — seeding from the current scan")
            write_floors(args.floors, {k: dict(v) for k, v in sorted(counts.items())})
            return 0
        lowered = []
        new: dict[str, dict[str, int]] = {}
        done: set[str] = set()
        for key in sorted(set(floors) | set(counts)):
            floor_key = matching_key(floors, key) if key in counts else key
            if floor_key in done:
                continue
            done.add(floor_key)
            entry = floors.get(floor_key) or {}
            model = _model_for_key(floors, counts, key)
            cur = counts.get(model, {c: 0 for c in CLASSES}) if model else {c: 0 for c in CLASSES}
            row = {}
            for cls in CLASSES:
                old = int(entry.get(cls, 0))
                now = int(cur.get(cls, 0))
                if now < old:
                    lowered.append(f"{floor_key} {cls}: {old} -> {now}")
                row[cls] = min(old, now)
            if any(row.values()):
                new[floor_key] = row
        write_floors(args.floors, new)
        print("\n".join(lowered) if lowered else "nothing to tighten")
        return 0

    if args.json:
        print(json.dumps({"counts": counts}, indent=2))
        return 0

    return _comment_refs_gate(args, floors_path=args.floors, counts=counts, floors=floors, refs=refs)


def _model_for_key(floors, counts, key):
    """The scanned model a floors key names, or None when it names none."""
    from .ratchet import matching_key

    if key in counts:
        return key
    for model in counts:
        if matching_key(floors, model) == key:
            return model
    return None


def _comment_refs_list(args, root: Path, refs) -> int:
    """One line per reference, then the total."""
    prefix = args.list or ""
    shown = [r for r in refs if r.model.startswith(prefix)]
    for ref in shown:
        rel = ref.file.relative_to(root).as_posix()
        print(f"{rel}:{ref.line}  [{ref.cls}]  {ref.text[:140]}")
    print()
    print(f"{len(shown)} reference(s) in {len({r.model for r in shown})} model(s)")
    return 0


def _comment_refs_gate(args, floors_path, counts, floors, refs) -> int:
    """The gate: the counts against the committed floor."""
    from .ratchet import ambiguous_keys, matching_key
    from .rules.comments import CLASSES

    rises = []
    below = []
    claimed = set()
    for key in sorted(counts):
        floor_key = matching_key(floors, key)
        entry = floors.get(floor_key) or {} if floor_key else {}
        claimed.add(floor_key)
        cur = counts[key]
        for cls in CLASSES:
            floor = int(entry.get(cls, 0))
            if cur.get(cls, 0) > floor:
                rises.append(f"{key} [{cls}]: {floor} -> {cur[cls]}")
            elif cur.get(cls, 0) < floor:
                below.append(f"{key} [{cls}]: {floor} -> {cur.get(cls, 0)}")
        for candidate in ambiguous_keys(floors, key):
            print(f"   note: the floor key '{candidate}' could name '{key}' but "
                  f"several keys say so; none of them was used.")
    for key in sorted(set(floors) - claimed):
        entry = floors[key] or {}
        for cls in CLASSES:
            floor = int(entry.get(cls, 0))
            if floor:
                below.append(f"{key} [{cls}]: {floor} -> 0")
    below.sort()
    if rises:
        print(f"❌ issue/PR references in TMDL comments ROSE above the committed floor "
              f"in {len(rises)} model/class(es):")
        for line in rises:
            print(f"   {line}")
        print()
        print("   Offending lines (new refs are among these; comments carry the mechanism, "
              "the commit carries the issue):")
        risen = {line.split(" [")[0] for line in rises}
        shown = 0
        for ref in refs:
            if ref.model in risen and shown < 40:
                rel = ref.file.relative_to(Path(args.path)).as_posix()
                print(f"   {rel}:{ref.line}  [{ref.cls}]  {ref.text[:120]}")
                shown += 1
        print()
        print(f"   Fix the comment, or (human edit, justified in the PR) raise "
              f"{floors_path}.")
        return 1
    total = sum(sum(v.values()) for v in counts.values())
    print(f"✅ comment issue-ref ratchet: {total} reference(s) across {len(counts)} "
          f"model(s), none above floor")
    if below:
        print("   below floor — tighten with --tighten:")
        for line in below:
            print(f"   {line}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    _harden_output_streams()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.rules or args.command == "rules":
        fmt = getattr(args, "format", None)
        if fmt == "markdown" or getattr(args, "out", None) or getattr(args, "check", False):
            return _cmd_rules_markdown(args)
        _print_rules(getattr(args, "json", False) or fmt == "json")
        return 0

    handlers = {"check": _cmd_check, "fix": _cmd_check, "baseline": _cmd_baseline,
                "stats": _cmd_stats, "comment-refs": _cmd_comment_refs,
                "dead-facts": _cmd_dead_facts,
                "report": _cmd_report, "format-resolve": _cmd_format_resolve,
                "grain": _cmd_grain, "info": _cmd_info, "fieldparam": _cmd_fieldparam,
                "manifest": _cmd_manifest, "schema-check": _cmd_schema_check, "refs": _cmd_refs, "live": _cmd_live}
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args)
    except UsageError as exc:
        print(f"tmdl-preflight: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
