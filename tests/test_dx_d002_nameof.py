"""D004 and D002: the quoted member, the leaked property lines, the reason
wording and the field-parameter row label.

The reason texts are quoted exactly: they are the contract with the
reference.
"""

from __future__ import annotations

from conftest import run_check, violations

TAG = "2b3c4d5e-0000-4000-8000-{:012d}"


def _model(tmp_path, measures: str = "", rows: str = ""):
    """A model with one table, a measures table and a field parameter."""
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
    body = rows or '				    ( "Amount", NAMEOF ( \'Sales\'[Amount] ), 0 )\n'
    (d / "tables" / "x-Plot Specific 1.tmdl").write_text(
        f"table 'x-Plot Specific 1'\n\tlineageTag: {TAG.format(4)}\n\n"
        f"\tpartition 'x-Plot Specific 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
        f"\t\t\t\t{{\n{body}\t\t\t\t}}\n",
        encoding="utf-8",
    )
    return d.parent


def _measure(name: str, expression: str, tag: int) -> str:
    return f"\tmeasure {name} = {expression}\n\t\tlineageTag: {TAG.format(tag)}\n\n"


class TestQuotedMember:
    def test_a_quoted_member_resolves(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "Label", "NAMEOF(Sales['Amount'])", 10))
        found = violations(run_check(model, "D004")[1], "D004")
        assert found == []


class TestLeakedPropertyLines:
    def test_a_leaked_source_lineage_tag_is_ignored(self, tmp_path):
        model = _model(tmp_path)
        f = model / "definition" / "tables" / "Sales.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "\tcolumn Amount",
                "\tcolumn Margin = SUM(Amount)\n"
                f"\t\tlineageTag: {TAG.format(11)}\n"
                "\t\tsourceLineageTag: 'Old Key'\n\n"
                "\tcolumn Amount",
            ),
            encoding="utf-8",
        )
        found = violations(run_check(model, "D004")[1], "D004")
        assert found == []


class TestReasons:
    def test_a_missing_table(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "Label", "NAMEOF('Nope'[X])", 10))
        found = violations(run_check(model, "D002")[1], "D002")
        assert len(found) == 1
        assert "Table 'Nope' not found" in found[0]["message"]

    def test_a_missing_measure(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "Label", "NAMEOF([Gone])", 10))
        found = violations(run_check(model, "D002")[1], "D002")
        assert len(found) == 1
        assert "Measure 'Gone' not found in any table" in found[0]["message"]

    def test_a_missing_member(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "Label", "NAMEOF('Sales'[Nope])", 10))
        found = violations(run_check(model, "D002")[1], "D002")
        assert len(found) == 1
        assert "Column 'Nope' not found in table 'Sales'" in found[0]["message"]

    def test_a_measure_written_with_a_table(self, tmp_path):
        model = _model(tmp_path, measures=(
            _measure("Revenue", "SUM(Sales[Amount])", 10)
            + _measure("Label", "NAMEOF('Shop Measures'[Revenue])", 12)
        ))
        found = violations(run_check(model, "D002")[1], "D002")
        assert [v["severity"] for v in found] == ["warning"]
        assert ("'Revenue' is a measure, not a column. "
                "Use NAMEOF([Revenue]) instead") in found[0]["message"]

    def test_an_empty_member(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "Label", "NAMEOF([])", 10))
        found = violations(run_check(model, "D002")[1], "D002")
        assert len(found) == 1
        assert "Invalid reference format" in found[0]["message"]


class TestFieldParameterRow:
    def test_the_row_label_is_in_the_object(self, tmp_path):
        model = _model(tmp_path, rows=(
            '				    ( "Bad", NAMEOF(\'Sales\'[Nope]), 2 )\n'
        ))
        found = violations(run_check(model, "D002")[1], "D002")
        assert len(found) == 1
        assert found[0]["object"] == "x-Plot Specific 1['Bad']"
        assert "Column 'Nope' not found in table 'Sales'" in found[0]["message"]
