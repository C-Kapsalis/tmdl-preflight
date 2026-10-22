"""
P0: DAX Parsable - Delimiter & Basic Syntax Validation

Purpose: Ensure all DAX expressions have balanced delimiters and basic
syntactic validity. This is a BLOCKING test - deployment fails if any
measure has syntax errors.

This test performs BASIC syntax checking only:
- Balanced parentheses ( )
- Balanced brackets [ ]
- Balanced braces { }
- Balanced quotes " and '

This does NOT validate:
- DAX semantics (function names, arguments, etc.)
- Reference validity
- Code quality or style

Implementation: the registry-driven model is replaced by the stand-in
`tests/fixtures/test_dax_parsable_bikeshop` and its variants; the expression
extractor + balance checker by rule D001 (`check --select D001 --json`) and
`tmdl_preflight.dax.check_balanced_delimiters`; the statistics helper by
`report complexity --json` (spec E-report-measure-complexity). The expression
count floor against the template baseline (test_dax_expressions_exist) belongs
to E-template-count-floor and is not covered here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_check, run_cli, violations
from tmdl_preflight.dax import check_balanced_delimiters
from tmdl_preflight.parser import parse_model

FIXTURE = "test_dax_parsable_bikeshop"
MIN_SUCCESS_RATE = 0.90  # config default dax_parsing.min_success_rate


def _materialize(stand_in, variant):
    root = stand_in(FIXTURE)
    if variant:
        for op in json.loads((root / "variants.json").read_text(encoding="utf-8"))[variant]:
            f = root / op["file"]
            if op.get("delete"):
                f.unlink()
            elif "write" in op:
                f.write_text(op["write"], encoding="utf-8")
            else:
                text = f.read_text(encoding="utf-8")
                assert text.count(op["old"]) == 1
                f.write_text(text.replace(op["old"], op["new"]), encoding="utf-8")
    (root / "variants.json").unlink()
    return root / "BikeShop.SemanticModel"


def _all_expressions(model_dir: Path):
    """Measures and calculated columns (what the earlier check extractor saw)."""
    model = parse_model(model_dir / "definition")
    return [b for b in model.dax_blocks() if b.kind in ("measure", "calculated_column")]


def _delimiter_findings(model_dir: Path, word: str):
    errors = []
    for expr in _all_expressions(model_dir):
        found = [e for e in check_balanced_delimiters(expr.expression) if word in e.lower()]
        if found:
            errors.append({"location": expr.label, "errors": found})
    return errors


# ==================== Balanced Parentheses (informational) ====================

@pytest.mark.parametrize("variant", [None, "one_unmatched_paren"])
def test_dax_balanced_parentheses(stand_in, variant):
    """Informational in the earlier check (P1): reports, never fails."""
    model_dir = _materialize(stand_in, variant)
    _delimiter_findings(model_dir, "parenthes")
    code, payload = run_check(model_dir, "D001")
    assert code in (0, 1)


# ==================== Balanced Brackets ====================

def _expression_findings(payload):
    """The D001 findings that name one measure or calculated column.

    The object label is `Table[Object]`; the kind is in the message.
    """
    return [
        v for v in violations(payload, "D001")
        if "in measure expression" in v.get("message", "")
        or "in calculated_column expression" in v.get("message", "")
    ]


def _brackets_gate(model_dir: Path):
    code, payload = run_check(model_dir, "D001")
    bracket_errors = [
        v for v in _expression_findings(payload)
        if "bracket" in v["message"].lower()
    ]
    assert not bracket_errors, (
        f"Found {len(bracket_errors)} expressions with unmatched brackets:\n"
        + "\n".join(f"  {v.get('object')}: {v['message']}" for v in bracket_errors)
    )


@pytest.mark.parametrize("variant,verdict", [
    (None, "pass"),
    ("bracket_broken", "fail"),
])
def test_dax_balanced_brackets(stand_in, variant, verdict):
    model_dir = _materialize(stand_in, variant)
    if verdict == "pass":
        _brackets_gate(model_dir)
    else:
        with pytest.raises(AssertionError):
            _brackets_gate(model_dir)


# ==================== Balanced Quotes (informational) ====================

@pytest.mark.parametrize("variant", [None])
def test_dax_balanced_quotes(stand_in, variant):
    """Informational in the earlier check (P1): reports, never fails."""
    model_dir = _materialize(stand_in, variant)
    _delimiter_findings(model_dir, "quote")


# ==================== Comprehensive Validation ====================

@pytest.mark.parametrize("variant", [None, "one_unmatched_paren"])
def test_dax_comprehensive_syntax_check(stand_in, variant):
    """Clean share of measures + calculated columns must be >= the configured
    `dax_parsing.min_success_rate` (default 0.90).

    STRICTER (project decision): every unbalanced expression is still a D001 error
    whatever the share; the share threshold is kept as a separate assertion."""
    model_dir = _materialize(stand_in, variant)
    total = len(_all_expressions(model_dir))
    code, payload = run_check(model_dir, "D001")
    invalid_objects = {v.get("object") for v in _expression_findings(payload)}
    success_rate = (total - len(invalid_objects)) / total if total else 0.0
    assert success_rate >= MIN_SUCCESS_RATE, (
        f"Success rate {success_rate:.1%} is below threshold {MIN_SUCCESS_RATE:.0%}."
    )
    if variant == "one_unmatched_paren":
        assert len(invalid_objects) == 1
        assert code == 1
    else:
        assert invalid_objects == set()


# ==================== Expression Statistics (informational) ====================

def test_dax_expression_statistics(stand_in):
    """Report statistics about DAX expressions (informational, always passes
    in the earlier check; the keys it printed must exist)."""
    model_dir = _materialize(stand_in, None)
    code, out, err = run_cli("report", "complexity", model_dir)
    assert code == 0, err
    lines = out.splitlines()
    start = lines.index("📊 DAX Expression Statistics:")
    block = lines[start:]
    assert block[1] == "   Total expressions: 11"
    assert block[2] == "   - Measures: 10"
    assert block[3] == "   - Calculated columns: 1"
