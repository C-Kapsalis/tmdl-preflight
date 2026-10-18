"""Command-line interface.

Usage:
    tmdl-preflight check    <path> [--select IDs] [--ignore IDs] [--strict]
                            [--format text|json|github|sarif|markdown] [--json]
                            [--config FILE] [--profile NAME] [--no-config]
                            [--baseline FILE]
    tmdl-preflight fix      <path> (same options as check)
    tmdl-preflight baseline <path> [--output FILE] [--update] [--accept-new]
                            [--config FILE] [--profile NAME] [--no-config]
    tmdl-preflight stats    <path> [--json]
    tmdl-preflight rules    [--json]

Exit codes: 0 clean, 1 violations remain (errors; warnings too with
--strict), 2 usage, path, configuration or baseline errors.
"""

from __future__ import annotations

import argparse
import json
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
from .rules.base import Context, RuleSet
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
        if name == "fix":
            p.add_argument("--dry-run", action="store_true",
                           help="report what fix would change; write nothing")
            p.add_argument("--clear-cache", action="store_true",
                           help="after lineage tags change, delete the model's "
                                ".pbi/cache.abf so Desktop does not reuse old tags")
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

    p_rules = sub.add_parser("rules", help="list the rule catalog")
    p_rules.add_argument("--json", action="store_true", help="machine-readable output")
    p_rules.add_argument("--format", choices=("text", "json", "markdown"), default=None,
                         help="catalog format (markdown: a generated docs page)")
    p_rules.add_argument("--out", metavar="FILE", help="write the catalog to FILE")
    p_rules.add_argument("--check", action="store_true",
                         help="with --out: fail if FILE is missing or stale; write nothing")
    return parser


def _context(raw_path: str, exclude: Optional[list[str]] = None) -> Context:
    root = Path(raw_path)
    if not root.exists():
        raise UsageError(
            f"cannot find the path {root}. Check the spelling, then pass a "
            f"PBIP project root, a *.SemanticModel folder, a definition "
            f"folder, or a *.Report folder."
        )
    ctx = Context(root, exclude=exclude)
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
            rule.configure(cfg.rule_options[rule.id])
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
    ctx = _context(args.path, cfg.exclude)
    ctx.options = dict(cfg.sections)
    ruleset = _effective_ruleset(full, cfg, args)
    if mode == "fix" and not getattr(args, "dry_run", False):
        report = fix(ctx, ruleset, explicit=_parse_id_list(args.select))
    else:
        report = check(ctx, ruleset)
        if mode == "fix":  # dry run: say what would be repaired
            fixable = {r.id: r for r in ruleset.rules if r.fixable}
            counts: dict[str, int] = {}
            for v in report.violations:
                if v.rule_id in fixable:
                    counts[v.rule_id] = counts.get(v.rule_id, 0) + 1
            report.would_fix = [
                f"{rid}: {n} violation(s)" for rid, n in sorted(counts.items())
            ]
    apply_policy(report, cfg, ctx=ctx)
    ran = {r.id for r in ruleset.rules}
    report.unused_exemptions = [e for e in report.unused_exemptions if e.rule in ran]
    return report, ruleset, cfg, ctx


def _cmd_check(args) -> int:
    if args.json and args.format not in (None, "json"):
        raise UsageError(f"--json conflicts with --format {args.format}")
    report, ruleset, cfg, _ctx = _run(args, args.command)
    if args.baseline:
        try:
            known = load_baseline(Path(args.baseline))
        except BaselineError as exc:
            raise UsageError(str(exc)) from exc
        report.violations, report.baseline = apply_baseline(
            report.violations, known, ruleset, {r.id for r in ruleset.rules}
        )
    if args.command == "fix" and not getattr(args, "dry_run", False):
        _after_fix_cache(args, report, _ctx)
    fmt = "json" if args.json else (args.format or "text")
    print(render(fmt, report, Path(args.path), ruleset))
    return report.exit_code(strict=args.strict or cfg.strict)


def _after_fix_cache(args, report: PreflightReport, ctx: Context) -> None:
    """Desktop keeps a model cache (.pbi/cache.abf) that remembers lineage
    tags. After tags change, delete it on request, or say that it exists."""
    if not any(rid in ("M003", "M004") for rid in report.fixed_rule_ids):
        return
    for d in ctx.definition_dirs:
        cache = d.parent / ".pbi" / "cache.abf"
        if not cache.is_file():
            continue
        if getattr(args, "clear_cache", False):
            cache.unlink()
            report.fixes_applied.append(f"cache: deleted {cache.parent.parent.name}/.pbi/cache.abf")
        else:
            print(
                f"tmdl-preflight: lineage tags changed; Power BI Desktop may still hold "
                f"the old ones in {cache}. Re-run with --clear-cache to delete it.",
                file=sys.stderr,
            )


def _cmd_baseline(args) -> int:
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


def _cmd_comment_refs(args) -> int:
    from .ratchet import RatchetFileError, load_floors, write_floors
    from .rules.comments import CLASSES, count_by_class, model_ticket_refs

    ctx = _context(args.path)
    counts: dict[str, dict[str, int]] = {}
    hits: dict[str, list] = {}
    for model in ctx.models:
        key = ctx.model_key(model)
        refs = model_ticket_refs(model.definition_path, ctx)
        counts[key] = count_by_class(refs)
        hits[key] = refs
    if args.tighten:
        if not args.floors:
            raise UsageError("--tighten needs --floors FILE")
        try:
            floors = load_floors(args.floors, missing_ok=True)
        except RatchetFileError as exc:
            raise UsageError(str(exc)) from exc
        seeded = not Path(args.floors).exists()
        new: dict[str, dict[str, int]] = {}
        for key, entry in floors.items():
            now = counts.get(key)
            if now is None:
                continue  # the model is gone: its entry goes with it
            new[key] = {c: min(int(entry.get(c, 0)), now[c]) for c in CLASSES}
        if seeded:
            new = {k: dict(v) for k, v in counts.items()}
        new = {k: v for k, v in sorted(new.items()) if any(v.values())}
        write_floors(args.floors, new)
        print(f"tmdl-preflight: floors written to {args.floors} ({len(new)} model(s))")
        return 0
    if args.json:
        payload: dict = {"counts": counts}
        if args.list is not None:
            payload["refs"] = [
                {"model": k, "file": str(r.file), "line": r.line, "class": r.cls, "ref": r.ref}
                for k, refs in hits.items() if k.startswith(args.list) for r in refs
            ]
        print(json.dumps(payload, indent=2))
        return 0
    for key in sorted(counts):
        c = counts[key]
        print(f"{key}: description {c['description']}, inline {c['inline']}")
        if args.list is not None and key.startswith(args.list):
            for r in hits[key]:
                print(f"  {r.file.name}:{r.line} [{r.cls}] {r.ref}  {r.text}")
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
                "stats": _cmd_stats, "comment-refs": _cmd_comment_refs}
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
