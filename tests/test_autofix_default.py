"""Verification is read-only unless repair is requested explicitly.

Ported from the suite's own autofix-default pins (spec A-check-is-read-only):
``check`` never writes, ``fix`` is the explicit write verb, and no environment
variable or default flag turns a read-only command into a writer.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from conftest import run_check, run_cli, run_fix, violations
from tmdl_preflight.cli import build_parser
from tmdl_preflight.rules import ALL_RULES

KNOWN_FIXABLE = {"M003", "M004", "M006", "M011", "M013", "F001", "F002", "F003", "B001", "B003"}


def _snapshot(root: Path) -> dict[str, str]:
    """Hash of every file under ``root`` (tracked or not), by relative path."""
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def _plant_fixable_findings(definition: Path) -> None:
    """One M013 (dangling description at end of file) and one M003 (duplicate tag)."""
    stores = definition / "tables" / "Stores.tmdl"
    stores.write_text(stores.read_text(encoding="utf-8") + "\n/// orphan description\n", encoding="utf-8")
    products = (definition / "tables" / "Products.tmdl").read_text(encoding="utf-8")
    tag = next(ln.split(":", 1)[1].strip() for ln in products.splitlines() if "lineageTag:" in ln)
    text = stores.read_text(encoding="utf-8")
    old = next(ln.split(":", 1)[1].strip() for ln in text.splitlines() if "lineageTag:" in ln)
    stores.write_text(text.replace(old, tag, 1), encoding="utf-8")


@pytest.mark.p0
def test_deliberate_violation_is_byte_identical_by_default_and_repairs_opt_in(tmp_path):
    """Acceptance pin: the same gate is read-only by default and repairs only on ``fix``."""
    model = tmp_path / "Broken.SemanticModel"
    definition = model / "definition"
    definition.mkdir(parents=True)
    expressions = definition / "expressions.tmdl"
    with expressions.open("w", encoding="utf-8", newline="") as fh:
        fh.write('expression v-example = "ok"\n\n/// orphan description\n\n')
    before = expressions.read_bytes()

    # check: the dangling description is reported (error, end-of-file run) and nothing is written
    code, payload = run_check(model, "M013")
    assert code == 1
    found = violations(payload, "M013")
    assert len(found) == 1 and found[0]["severity"] == "error"
    assert expressions.read_bytes() == before

    # fix: the explicit write verb repairs and re-checks from disk
    code, payload = run_fix(model, "M013")
    after = expressions.read_bytes()
    assert after != before
    assert b"orphan description" not in after
    assert after.decode("utf-8").rstrip("\n") == 'expression v-example = "ok"'
    assert violations(payload, "M013") == []
    code, payload = run_check(model, "M013")
    assert code == 0 and violations(payload, "M013") == []


@pytest.mark.p0
def test_every_python_autofix_callsite_defaults_off(project, definition, monkeypatch):
    """Every registered fixer is reachable only through the explicit write verb.

    The original counted the suite's own repair-switch call sites (at least 11, all
    defaulting off). Here: every fixable rule is known, no option of the read-only
    ``check`` command enables writing, and no environment variable turns ``check``
    into a writer.
    """
    fixable = {cls.id for cls in ALL_RULES if getattr(cls, "fixable", False)}
    assert KNOWN_FIXABLE <= fixable

    parser = build_parser()
    sub = next(a for a in parser._actions if a.dest == "command")
    check_parser = sub.choices["check"]
    for action in check_parser._actions:
        if "fix" in (action.dest or "").lower() or "repair" in (action.dest or "").lower():
            assert not action.default, f"check option {action.dest} must default to off"

    _plant_fixable_findings(definition)
    for var in ("PBI_AUTOFIX", "TMDL_PREFLIGHT_FIX", "TMDL_PREFLIGHT_AUTOFIX"):
        monkeypatch.setenv(var, "1")
    before = _snapshot(project)
    code, payload = run_check(project)
    assert code == 1
    assert {"M003", "M013"} <= {v["rule"] for v in violations(payload)}
    assert _snapshot(project) == before


@pytest.mark.p0
def test_verify_default_is_pure_and_apply_fixes_is_explicit(project, definition):
    """Read-only commands leave the tree byte-identical; ``fix`` is the opt-in writer."""
    code, out, _ = run_cli("--help")
    assert code == 0
    assert "check" in out and "fix" in out

    _plant_fixable_findings(definition)
    scratch = project / "notes-untracked.txt"
    scratch.write_text("scratch file left in the tree\n", encoding="utf-8")
    before = _snapshot(project)

    for fmt in ("text", "json", "github", "sarif", "markdown"):
        code, _out, _err = run_cli("check", project, "--format", fmt, "--no-config")
        assert code == 1
        assert _snapshot(project) == before, f"check --format {fmt} changed the tree"
    for argv in (("rules",), ("rules", "--json"), ("stats", project), ("stats", project, "--json")):
        run_cli(*argv)
        assert _snapshot(project) == before, f"{argv[0]} changed the tree"

    code, payload = run_fix(project, "M003", "M013")
    assert _snapshot(project) != before
    assert violations(payload, "M003") == [] and violations(payload, "M013") == []
    assert scratch.read_text(encoding="utf-8") == "scratch file left in the tree\n"
