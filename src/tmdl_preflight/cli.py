"""Command-line interface.

Usage:
    tmdl-preflight check <path> [--select IDs] [--ignore IDs] [--json] [--strict]
    tmdl-preflight fix   <path> [--select IDs] [--ignore IDs] [--json] [--strict]
    tmdl-preflight rules [--json]

Exit codes: 0 clean, 1 violations remain (errors; warnings too with
--strict), 2 usage or path errors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from . import __version__
from .engine import PreflightReport, check, fix
from .rules import default_ruleset
from .rules.base import Context, Severity

_SEVERITY_TAG = {
    Severity.ERROR: "error",
    Severity.WARNING: "warning",
    Severity.INFO: "info",
}


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


def _print_report(report: PreflightReport, root: Path) -> None:
    for applied in report.fixes_applied:
        print(f"fixed  {applied}")
    if report.fixes_applied:
        print()
    for v in sorted(
        report.violations, key=lambda v: (str(v.file or ""), v.line or 0, v.rule_id)
    ):
        loc = v.location()
        try:
            loc = str(Path(loc.split(":")[0]).relative_to(root)) + (
                f":{v.line}" if v.line else ""
            )
        except ValueError:
            pass
        prefix = f"{loc}  " if loc else ""
        obj = f" [{v.obj}]" if v.obj else ""
        fixable = " (auto-fixable)" if v.fixable else ""
        print(f"{prefix}{v.rule_id} {_SEVERITY_TAG[v.severity]}: {v.message}{obj}{fixable}")
    e, w, i = len(report.errors), len(report.warnings), len(report.infos)
    print()
    print(
        f"tmdl-preflight: {e} error(s), {w} warning(s), {i} info(s)"
        + (f", {len(report.fixes_applied)} fix(es) applied" if report.fixes_applied else "")
    )


def _print_rules(as_json: bool) -> None:
    ruleset = default_ruleset()
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
                    }
                    for r in ruleset.rules
                ],
                indent=2,
            )
        )
        return
    for r in ruleset.rules:
        fixable = "auto-fixable" if r.fixable else "check-only"
        print(f"{r.id}  {r.name:28s} {r.severity.value:8s} {fixable}")
        print(f"      {r.description}")
        print()


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

    for name, help_text in (
        ("check", "report violations; never modifies files"),
        ("fix", "apply auto-fixes, then re-check (imposition pattern)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("path", help="a PBIP project root, *.SemanticModel, "
                                    "definition folder, or *.Report folder")
        p.add_argument("--select", help="comma-separated rule ids/names to run "
                                        "(default: all)")
        p.add_argument("--ignore", help="comma-separated rule ids/names to skip")
        p.add_argument("--json", action="store_true", help="machine-readable output")
        p.add_argument("--strict", action="store_true",
                       help="exit nonzero on warnings as well as errors")

    p_rules = sub.add_parser("rules", help="list the rule catalog")
    p_rules.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    _harden_output_streams()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.rules or args.command == "rules":
        _print_rules(getattr(args, "json", False))
        return 0

    if args.command not in ("check", "fix"):
        parser.print_help()
        return 2

    root = Path(args.path)
    if not root.exists():
        print(
            f"tmdl-preflight: cannot find the path {root}. Check the "
            f"spelling, then pass a PBIP project root, a *.SemanticModel "
            f"folder, a definition folder, or a *.Report folder.",
            file=sys.stderr,
        )
        return 2

    ctx = Context(root)
    if ctx.is_empty():
        print(
            f"tmdl-preflight: no semantic model or report found under "
            f"{root}. Expected a *.SemanticModel folder with a definition/ "
            f"subfolder, or a *.Report folder; check that the project was "
            f"saved in PBIP format (File > Save as > Power BI project files "
            f"in Power BI Desktop).",
            file=sys.stderr,
        )
        return 2

    full_ruleset = default_ruleset()
    valid_keys = {r.id.lower() for r in full_ruleset.rules} | {
        r.name.lower() for r in full_ruleset.rules
    }
    for flag_name, raw in (("--select", args.select), ("--ignore", args.ignore)):
        requested = _parse_id_list(raw) or set()
        unknown = sorted(requested - valid_keys)
        if unknown:
            print(
                f"tmdl-preflight: {flag_name} names rules that do not exist: "
                f"{', '.join(unknown)}. Run 'tmdl-preflight rules' to list "
                f"the valid rule ids and names.",
                file=sys.stderr,
            )
            return 2

    ruleset = full_ruleset.select(_parse_id_list(args.select), _parse_id_list(args.ignore))
    if not ruleset.rules:
        print(
            "tmdl-preflight: this --select/--ignore combination leaves no "
            "rules to run. Loosen the selection, or run 'tmdl-preflight "
            "rules' to list the available rules.",
            file=sys.stderr,
        )
        return 2

    report = fix(ctx, ruleset) if args.command == "fix" else check(ctx, ruleset)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_report(report, root)
    return report.exit_code(strict=args.strict)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
