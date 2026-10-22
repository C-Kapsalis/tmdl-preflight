"""The golden outputs of the slice, compared byte for byte.

The reference outputs live outside the repository, so the test reads them
from the folder the reviewer put them in. When that folder is not there the
test is skipped: the repository must not carry the reviewer's material.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli

GOLDEN = Path(
    "/Users/chkapsalis/Documents/swift-pbi-port-workspace/port/review/"
    "preflight-completeness-A/golden-RP")
TREE = "rp_reports"

pytestmark = pytest.mark.skipif(not GOLDEN.is_dir(),
                                reason="the reviewer's golden outputs are not here")


def _model(stand_in):
    return stand_in(TREE) / "Growth.SemanticModel"


def test_the_complexity_json_is_the_golden_one(stand_in):
    code, out, _err = run_cli("report", "complexity", str(_model(stand_in)), "--json")
    assert code == 0
    golden = json.loads((GOLDEN / "out" / "report-complexity.json").read_text(encoding="utf-8"))
    golden.pop("timestamp", None)
    assert json.loads(out) == golden


def test_the_nameof_json_is_the_golden_one(stand_in):
    code, out, _err = run_cli("report", "nameof", str(_model(stand_in)), "--json")
    assert code == 0
    golden = json.loads((GOLDEN / "out" / "report-nameof-families.json").read_text(encoding="utf-8"))
    golden.pop("timestamp", None)
    assert json.loads(out) == golden


def test_the_relationships_json_is_the_golden_one(stand_in):
    code, out, _err = run_cli("report", "relationships", str(_model(stand_in)), "--json")
    assert code == 0
    golden = json.loads((GOLDEN / "out" / "report-relationships.json").read_text(encoding="utf-8"))
    assert json.loads(out) == golden


def test_the_relationships_text_is_the_golden_one(stand_in):
    """The golden shows the two paths as <root>; the tool prints the paths
    it read, and the two lines that say the analysis was saved to a file are
    not printed because no file is written."""
    model = _model(stand_in)
    code, out, _err = run_cli("report", "relationships", str(model))
    assert code == 0
    golden = (GOLDEN / "out" / "report-relationships.txt").read_text(encoding="utf-8")
    golden = golden.replace("💾 Saving analysis to: <root>/relationship_analysis.json\n"
                             "✅ Analysis saved\n", "")
    root = str(model.parent)
    assert out == golden.replace("<root>", root)


def test_the_complexity_text_is_the_golden_one(stand_in):
    """The golden ends with the line that says the analysis was saved to a
    file; the tool writes no file, so it does not print that line. The
    expression statistics follow the closing banner, in the shape the golden
    keeps in its own file."""
    code, out, _err = run_cli("report", "complexity", str(_model(stand_in)))
    assert code == 0
    golden = (GOLDEN / "out" / "report-complexity.txt").read_text(encoding="utf-8")
    golden = golden.replace("💾 Analysis saved to: measure_complexity.json\n\n", "")
    statistics = (GOLDEN / "out" / "report-expression-statistics.txt").read_text(encoding="utf-8")
    assert out == golden + statistics
