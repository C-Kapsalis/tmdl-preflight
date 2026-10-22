"""D004: the dangling-table findings and the repairs the fixer makes.

The wording of a finding, the note the model carries, the rebuilt
applied-filters measure and the newline style of a repaired file are all
part of the contract, so they are quoted exactly.
"""

from __future__ import annotations

from conftest import run_check, run_cli, violations

TAG = "2b3c4d5e-0000-4000-8000-{:012d}"


def _model(tmp_path, measures: str = "", y_rows: str = "", newline: str = "\n"):
    """A model with two tables, a measures table and a y-Selector table."""
    d = tmp_path / "Shop.SemanticModel" / "definition"
    (d / "tables").mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    (d / "tables" / "Sales.tmdl").write_text(
        f"table Sales\n\tlineageTag: {TAG.format(1)}\n\n"
        f"\tcolumn Revenue\n\t\tdataType: double\n\t\tlineageTag: {TAG.format(2)}\n"
        f"\t\tsourceColumn: Revenue\n\n"
        f"\tpartition Sales = m\n\t\tmode: import\n"
        f"\t\tsource = #table({{\"Revenue\"}}, {{{{1}}}})\n",
        encoding="utf-8",
    )
    (d / "tables" / "Orders.tmdl").write_text(
        f"table Orders\n\tlineageTag: {TAG.format(3)}\n\n"
        f"\tcolumn Count\n\t\tdataType: int64\n\t\tlineageTag: {TAG.format(4)}\n"
        f"\t\tsourceColumn: Count\n\n"
        f"\tpartition Orders = m\n\t\tmode: import\n"
        f"\t\tsource = #table({{\"Count\"}}, {{{{1}}}})\n",
        encoding="utf-8",
    )
    (d / "tables" / "Shop Measures.tmdl").write_text(
        f"table 'Shop Measures'\n\tlineageTag: {TAG.format(5)}\n\n"
        f"{measures}"
        f"\tpartition 'Shop Measures' = m\n\t\tmode: import\n"
        f"\t\tsource = #table({{\"x\"}}, {{{{1}}}})\n",
        encoding="utf-8",
    )
    rows = y_rows or (
        '				    ( "Revenue", NAMEOF ( \'Sales\'[Revenue] ), 0 ),\n'
        '				    ( "Orders", NAMEOF ( \'Orders\'[Count] ), 1 )\n'
    )
    (d / "tables" / "y-Selector 1.tmdl").write_text(
        f"table 'y-Selector 1'\n\tlineageTag: {TAG.format(6)}\n\n"
        f"\tpartition 'y-Selector 1' = calculated\n\t\tmode: import\n\t\tsource =\n"
        f"\t\t\t\t{{\n{rows}\t\t\t\t}}\n",
        encoding="utf-8",
    )
    if newline != "\n":
        for f in (d / "tables").glob("*.tmdl"):
            f.write_bytes(f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    return d.parent


def _measure(name: str, expression: str, tag: int) -> str:
    return (
        f"\tmeasure {name} = {expression}\n"
        f"\t\tlineageTag: {TAG.format(tag)}\n\n"
    )


class TestDanglingFindings:
    def test_one_finding_per_object_with_the_missing_tables_sorted(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "Total", "SUM(Alpha[x]) + SUM(Beta[y])", 10))
        code, payload = run_check(model, "D004")
        found = violations(payload, "D004")
        assert code == 1 and len(found) == 1
        assert found[0]["message"].startswith(
            "measure Shop Measures[Total] -> missing 'Alpha', 'Beta'"
        )
        assert found[0]["object"] == "Shop Measures[Total]"

    def test_the_model_note_counts_objects_and_references(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "Total", "SUM(Alpha[x]) + SUM(Beta[y])", 10))
        _code, payload = run_check(model, "D004")
        assert any(
            "DANGLING TABLE REFS (1 object(s), 2 ref(s)):" in n for n in payload["notes"]
        )
        assert any(
            "1 model(s) with dangling DAX table references." in n for n in payload["notes"]
        )

    def test_a_calculated_column_is_named_as_a_column(self, tmp_path):
        model = _model(tmp_path)
        f = model / "definition" / "tables" / "Sales.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "\tcolumn Revenue",
                "\tcolumn Margin = SUM(Ghost[x])\n\t\tlineageTag: " + TAG.format(11)
                + "\n\n\tcolumn Revenue",
            ),
            encoding="utf-8",
        )
        found = violations(run_check(model, "D004")[1], "D004")
        assert len(found) == 1
        assert found[0]["message"].startswith(
            "column Sales[Margin] -> missing 'Ghost'"
        )


class TestAppliedFiltersRebuild:
    def test_the_summary_measure_is_rebuilt_from_the_y_axis(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "'i-Applied Filters'", "IF(ISFILTERED('Gone'[x]), \"x\", \"\")", 10))
        code, payload = run_check(model, "D004")
        assert code == 1
        assert violations(payload, "D004")[0]["message"].startswith(
            "measure Shop Measures[i-Applied Filters] -> missing 'Gone'"
        )

        fix_code, _out, _err = run_cli("fix", str(model), "--select", "D004", "--json")
        assert fix_code == 0
        again = run_check(model, "D004")
        assert again[0] == 0 and violations(again[1], "D004") == []
        body = (model / "definition" / "tables" / "Shop Measures.tmdl").read_text(
            encoding="utf-8")
        assert "ISFILTERED('Sales'[Revenue])" in body
        assert "ISFILTERED('Orders'[Count])" in body
        assert "Gone" not in body

    def test_only_that_measure_changed(self, tmp_path):
        model = _model(tmp_path, measures=_measure(
            "'i-Applied Filters'", "IF(ISFILTERED('Gone'[x]), \"x\", \"\")", 10))
        before = {p: p.read_bytes() for p in (model / "definition" / "tables").glob("*.tmdl")}
        run_cli("fix", str(model), "--select", "D004", "--json")
        after = {p: p.read_bytes() for p in (model / "definition" / "tables").glob("*.tmdl")}
        changed = sorted(p.name for p in before if before[p] != after.get(p))
        assert changed == ["Shop Measures.tmdl"]


class TestFixSummary:
    def test_site_groups_and_the_not_auto_fixable_line(self, tmp_path):
        model = _model(tmp_path, measures=(
            _measure("Total", "SUM(Alpha[x])", 10)
            + "\tmeasure 'Kept' =\n"
            "\t\tISFILTERED('Alpha') || ISINSCOPE('Alpha'[x]) ||\n"
            "\t\tTRUE()\n"
            f"\t\tlineageTag: {TAG.format(12)}\n\n"
        ))
        code, out, _err = run_cli("fix", str(model), "--select", "D004")
        assert code == 1
        assert "repaired 1 site-group(s)" in out
        assert out.count("NOT auto-fixable") == 1
        assert "Shop Measures[Total] -> Alpha" in out

    def test_a_crlf_file_keeps_its_line_endings(self, tmp_path):
        model = _model(tmp_path, newline="\r\n", measures=(
            _measure("Total", "SUM(Alpha[x])", 10)
            + "\tmeasure 'Kept' =\n"
            "\t\tISFILTERED('Alpha') || ISINSCOPE('Alpha'[x]) ||\n"
            "\t\tTRUE()\n"
            f"\t\tlineageTag: {TAG.format(12)}\n\n"
        ))
        f = model / "definition" / "tables" / "Shop Measures.tmdl"
        before = f.read_bytes()
        assert before.count(b"\r\n") == before.count(b"\n")
        run_cli("fix", str(model), "--select", "D004")
        after = f.read_bytes()
        assert after.count(b"\n") == before.count(b"\n") - 1
        assert after.count(b"\r\n") == after.count(b"\n")
        assert b"\n" not in after.replace(b"\r\n", b"")
