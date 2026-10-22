"""``report complexity``: the layout a reviewer reads, and the numbers.

The report measures the DAX of a model: how long the expressions are, how
deep they nest, how many VARs they declare, and which measures are the
longest. It is a reading aid, never a gate.

Two things are deliberate: the report never writes a file (the old version
left a JSON file in the working directory), and the length of a measure is
its expression without the indentation the first line carried.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import run_cli

TREE = "rp_reports"


def _model(stand_in) -> Path:
    return stand_in(TREE) / "Growth.SemanticModel"


def test_the_text_report_has_the_reference_layout(stand_in):
    code, out, _err = run_cli("report", "complexity", str(_model(stand_in)))
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "=" * 80
    assert lines[1] == "MEASURE COMPLEXITY ANALYSIS"
    assert lines[2] == "=" * 80
    assert lines[4] == "🔍 Parsing model..."
    assert lines[5] == "✅ Parsed 8 tables"
    assert lines[7] == "📊 Analyzing measures..."
    assert lines[8] == "✅ Analyzed 8 measures"
    assert lines[10] == "=" * 80
    assert lines[11] == "📊 COMPLEXITY ANALYSIS RESULTS"
    assert lines[12] == "=" * 80
    assert lines[14] == "📈 Statistics:"
    assert lines[15] == "   Total measures: 8"
    assert lines[17] == "   Expression Lengths:"
    assert lines[18] == "     Average: 796 characters"
    assert lines[19] == "     Minimum: 1 characters"
    assert lines[20] == "     Maximum: 6,041 characters"
    assert lines[22] == "   Percentiles:"
    assert lines[23] == "     50th (median): 34 characters"
    assert lines[24] == "     75th: 107 characters"
    assert lines[25] == "     90th: 6,041 characters"
    assert lines[26] == "     95th: 6,041 characters"
    assert lines[27] == "     99th: 6,041 characters"
    assert lines[29] == "   Nesting Depth:"
    assert lines[30] == "     Average: 1.6 levels"
    assert lines[31] == "     Maximum: 4 levels"
    assert lines[33] == "   VAR Usage:"
    assert lines[34] == "     Average: 0.2 VARs per measure"
    assert lines[35] == "     Maximum: 2 VARs in a single measure"
    assert lines[37] == "📊 Length Distribution:"
    assert lines[38] == "   Tiny         (     0 -    100 chars):    5 ( 62.5%)"
    assert lines[39] == "   Small        (   100 -    500 chars):    2 ( 25.0%)"
    assert lines[40] == "   Medium       (   500 -  1,000 chars):    0 (  0.0%)"
    assert lines[41] == "   Large        ( 1,000 -  5,000 chars):    0 (  0.0%)"
    assert lines[42] == "   Very Large   ( 5,000 - 10,000 chars):    1 ( 12.5%)"
    assert lines[43] == "   Huge         (10,000 -    inf chars):    0 (  0.0%)"
    assert lines[45] == "🏆 Top 10 Most Complex Measures (by length):"
    assert lines[46] == "-" * 80
    assert lines[47] == " 1. 📝 Sales[Huge]"
    assert lines[48] == "     Length: 6,041 chars | Lines: 1 | VARs: 0 | Depth: 4"
    assert lines[49] == "     CALCULATE: 0 | FILTER: 0 | SUMX: 1"
    assert lines[51] == " 2. 📝 x-Selector 1[Lbl]"
    assert lines[55] == " 3. 📝 Sales[-Helper]"
    assert lines[56] == "     Length: 102 chars | Lines: 3 | VARs: 2 | Depth: 3"
    assert lines[57] == "     CALCULATE: 1 | FILTER: 1 | SUMX: 0"
    assert lines[79] == "=" * 80
    assert lines[80] == "💡 RECOMMENDED THRESHOLDS FOR TESTS"
    assert lines[81] == "=" * 80
    assert lines[83] == "Based on data analysis:"
    assert lines[84] == "   Max length (strict): 6,041 chars (95th percentile)"
    assert lines[85] == "   Max length (relaxed): 6,041 chars (99th percentile)"
    assert lines[86] == "   Max nesting depth: 4 levels (current max)"
    assert lines[87] == "   Max VAR count: 2 (current max)"
    assert lines[89] == "Suggested test thresholds:"
    assert lines[90] == "   - Core measures: <6,041 chars"
    assert lines[91] == "   - Helper measures: <6,041 chars"
    assert lines[92] == "   - Critical violation: >6,041 chars"
    assert lines[93] == "   - Max nesting: 6 levels (allow headroom)"
    assert lines[94] == "   - Max VARs: 7 (allow headroom)"
    assert lines[96] == "=" * 80
    assert lines[97] == "✅ ANALYSIS COMPLETE"
    assert lines[98] == "=" * 80


def test_the_report_writes_no_file(stand_in, tmp_path):
    model = _model(stand_in)
    before = sorted(p.name for p in model.parent.parent.iterdir())
    code, _out, _err = run_cli("report", "complexity", str(model))
    assert code == 0
    assert sorted(p.name for p in model.parent.parent.iterdir()) == before
    assert not list(Path.cwd().glob("measure_complexity.json"))


def test_the_json_report_has_the_reference_layout(stand_in):
    code, out, _err = run_cli("report", "complexity", str(_model(stand_in)), "--json")
    assert code == 0
    data = json.loads(out)
    assert list(data) == ["total_measures", "statistics", "top_10_complex", "all_measures"]
    assert data["total_measures"] == 8
    assert list(data["statistics"]) == [
        "avg_length", "min_length", "max_length", "median_length", "p75_length",
        "p90_length", "p95_length", "p99_length", "avg_nesting_depth",
        "max_nesting_depth", "avg_var_count", "max_var_count",
    ]
    assert data["statistics"]["avg_length"] == 795.75
    assert data["statistics"]["avg_nesting_depth"] == 1.625
    assert data["statistics"]["avg_var_count"] == 0.25
    assert data["statistics"]["median_length"] == 34
    first = data["top_10_complex"][0]
    assert list(first) == [
        "table", "measure", "full_name", "is_helper", "is_core", "length", "lines",
        "var_count", "calculate_count", "filter_count", "sumx_count", "switch_count",
        "max_nesting_depth",
    ]
    assert first["full_name"] == "Sales[Huge]"
    assert first["length"] == 6041
    assert [m["full_name"] for m in data["all_measures"]] == [
        "Sales[Huge]", "x-Selector 1[Lbl]", "Sales[-Helper]", "Sales[^Core]",
        "y-Selector 1[YL]", "Sales[Revenue]", "Sales[Cost/ Conversion]",
        "Report Helpers[Revenue]",
    ]


def test_a_helper_measure_is_measured_without_the_first_line_indentation(stand_in):
    code, out, _err = run_cli("report", "complexity", str(_model(stand_in)), "--json")
    assert code == 0
    data = json.loads(out)
    helper = [m for m in data["all_measures"] if m["measure"] == "-Helper"][0]
    assert helper["length"] == 102
    assert helper["lines"] == 3
    assert helper["is_helper"] is True


def test_the_expression_statistics_block_follows_the_report(stand_in):
    code, out, _err = run_cli("report", "complexity", str(_model(stand_in)))
    assert code == 0
    lines = out.splitlines()
    start = lines.index("📊 DAX Expression Statistics:")
    assert lines[start:] == [
        "📊 DAX Expression Statistics:",
        "   Total expressions: 9",
        "   - Measures: 8",
        "   - Calculated columns: 1",
        "",
        "   Expression Lengths:",
        "   - Average: 709 characters",
        "   - Minimum: 1 characters",
        "   - Maximum: 6,041 characters",
        "   - Total characters: 6,385",
    ]
