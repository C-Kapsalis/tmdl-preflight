"""The NAMEOF report, the duplicate-variable message, the D010 severity and
the cross-fact key message.

The texts are quoted exactly: they are the contract with the reference.
"""

from __future__ import annotations

import json

from conftest import run_check, run_cli, violations

TAG = "2b3c4d5e-0000-4000-8000-{:012d}"


def _model(tmp_path, measures: str = ""):
    """A model with one table, a measures table and no field parameter."""
    d = tmp_path / "Shop.SemanticModel" / "definition"
    (d / "tables").mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    (d / "tables" / "Sales.tmdl").write_text(
        f"table Sales\n\tlineageTag: {TAG.format(1)}\n\n"
        f"\tcolumn Amount\n\t\tdataType: double\n\t\tlineageTag: {TAG.format(2)}\n"
        f"\t\tsourceColumn: Amount\n\n"
        f"\tpartition Sales = m\n\t\tmode: import\n"
        f"\t\tsource = #table({{\"Amount\"}}, {{{{1}}}})\n",
        encoding="utf-8",
    )
    (d / "tables" / "Shop Measures.tmdl").write_text(
        f"table 'Shop Measures'\n\tlineageTag: {TAG.format(3)}\n\n"
        f"{measures}"
        f"\tpartition 'Shop Measures' = m\n\t\tmode: import\n"
        f"\t\tsource = #table({{\"x\"}}, {{{{1}}}})\n",
        encoding="utf-8",
    )
    return d.parent


def _measure(name: str, expression: str, tag: int) -> str:
    return f"\tmeasure {name} = {expression}\n\t\tlineageTag: {TAG.format(tag)}\n\n"


EXPECTED_REPORT = """\
================================================================================
NAMEOF REFERENCE VALIDATION REPORT
================================================================================

Total References: 2
  Measure References: 0
  Column References: 2
  Unique Tables: 2
  Unique Objects: 2

❌ Found 2 issues:
   Errors: 1
   Warnings: 1

ERRORS:
--------------------------------------------------------------------------------
[ERROR] Broken reference in Shop Measures[Broken]:
  Reference: Sales[Nope]
  Reason: Column 'Nope' not found in table 'Sales'
  Context: NAMEOF('Sales'[Nope])...

WARNINGS:
--------------------------------------------------------------------------------
[WARNING] Broken reference in Shop Measures[Warn]:
  Reference: Shop Measures[Revenue]
  Reason: 'Revenue' is a measure, not a column. Use NAMEOF([Revenue]) instead
  Context: NAMEOF('Shop Measures'[Revenue])...

================================================================================"""


class TestNameofReport:
    def test_the_text_report_layout(self, tmp_path):
        model = _model(tmp_path, measures=(
            _measure("Revenue", "SUM(Sales[Amount])", 10)
            + _measure("Broken", "NAMEOF('Sales'[Nope])", 11)
            + _measure("Warn", "NAMEOF('Shop Measures'[Revenue])", 12)
        ))
        code, out, _err = run_cli("report", "nameof", model)
        assert code == 0
        assert out.strip() == EXPECTED_REPORT

    def test_a_clean_model_says_so(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "Fine", "NAMEOF('Sales'[Amount])", 10))
        code, out, _err = run_cli("report", "nameof", model)
        assert code == 0
        assert "✅ All references are valid!" in out
        assert "Found" not in out


class TestDuplicateVariable:
    def test_the_message_names_the_declaration_line(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "Twice", "VAR Total = 1 VAR TOTAL = 2 RETURN Total", 10))
        found = violations(run_check(model, "D005")[1], "D005")
        assert len(found) == 1
        assert found[0]["message"].startswith(
            "VAR 'total' declared twice in the same scope (measure at line 4)"
        )


class TestCalcDaxBlocks:
    def test_the_rule_fails_when_it_is_enabled(self, tmp_path):
        model = _model(tmp_path, measures=_measure("Fine", "1", 10))
        code, payload = run_check(
            model, "calc-dax-blocks-present",
            config={"rules": {"calc-dax-blocks-present": {"enabled": True}}},
        )
        assert code == 1
        found = violations(payload, "D010")
        assert [v["severity"] for v in found] == ["error"]

    def test_the_counts_go_to_the_notes(self, tmp_path):
        model = _model(tmp_path, measures=_measure("Fine", "1", 10))
        _code, payload = run_check(
            model, "calc-dax-blocks-present",
            config={"rules": {"calc-dax-blocks-present": {"enabled": True}}},
        )
        assert any("[OK] Extracted 0 non-measure DAX blocks:" in n for n in payload["notes"])
        assert any("   - calculation_item: 0" in n for n in payload["notes"])


class TestCrossFactKey:
    CONFIG = {"rules": {"cross-fact-multirow-key-join": {"multi_row_keys": ["page_id"]}}}

    def _model(self, tmp_path, body: str):
        model = _model(tmp_path)
        f = model / "definition" / "tables" / "Shop Measures.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "\tpartition 'Shop Measures' = m",
                body + "\tpartition 'Shop Measures' = m",
            ),
            encoding="utf-8",
        )
        return model

    def test_the_message_names_the_two_sides(self, tmp_path):
        model = self._model(tmp_path, (
            "\tmeasure 'Joined' =\n"
            "\t\t'Left'[page_id] IN VALUES('Right'[page_id])\n"
            f"\t\tlineageTag: {TAG.format(10)}\n\n"
        ))
        found = violations(run_check(model, "X001", config=self.CONFIG)[1], "X001")
        assert len(found) == 1
        assert found[0]["message"].startswith(
            "Shop Measures.tmdl:5: 'Left'[page_id] compared against VALUES('Right'[page_id])"
        )
        assert "the two key spaces do not overlap" in found[0]["message"]
        assert ("CALCULATETABLE(VALUES(<dimension>[<business key>]), <fact>), "
                "then use EXCEPT/INTERSECT over those sets") in found[0]["message"]

    def test_a_commented_comparison_is_not_reported(self, tmp_path):
        model = self._model(tmp_path, (
            "\tmeasure 'Joined' =\n"
            "\t\t-- 'Left'[page_id] IN VALUES('Right'[page_id])\n"
            f"\t\tlineageTag: {TAG.format(10)}\n\n"
        ))
        found = violations(run_check(model, "X001", config=self.CONFIG)[1], "X001")
        assert found == []
