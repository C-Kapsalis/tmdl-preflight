"""D001 at the rule level: the finding text, the object label, the summary
note, the success-rate boundary and the no-measures guard."""

from __future__ import annotations

from conftest import run_check, violations

TAG = "2b3c4d5e-0000-4000-8000-{:012d}"


def _model(tmp_path, measures):
    """A model with the given measures (name, expression) and one column."""
    d = tmp_path / "Shop.SemanticModel" / "definition"
    (d / "tables").mkdir(parents=True)
    (d / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
    body = "".join(
        f"\tmeasure {name} = {expr}\n\t\tlineageTag: {TAG.format(i + 2)}\n\n"
        for i, (name, expr) in enumerate(measures)
    )
    (d / "tables" / "Sales.tmdl").write_text(
        f"table Sales\n\tlineageTag: {TAG.format(1)}\n\n"
        f"{body}"
        f"\tcolumn Revenue\n\t\tdataType: double\n\t\tlineageTag: {TAG.format(90)}\n"
        f"\t\tsourceColumn: Revenue\n\n"
        f"\tpartition Sales = m\n\t\tmode: import\n"
        f"\t\tsource = #table({{\"Revenue\"}}, {{{{1}}}})\n",
        encoding="utf-8",
    )
    return d.parent


def _no_threshold():
    """The threshold finding off, so a test sees only the expression error."""
    return {"rules": {"D001": {"min_success_rate": 0.0}}}


class TestFindingText:
    def test_message_names_the_kind_and_the_position(self, tmp_path):
        model = _model(tmp_path, [("Fine", "1"), ("Broken", "SUM([Revenue]")])
        found = violations(run_check(model, "D001", config=_no_threshold())[1], "D001")
        assert len(found) == 1
        assert found[0]["message"].startswith(
            "Unmatched opening parenthesis '(' at position 3"
        )
        assert found[0]["object"] == "Sales[Broken]"

    def test_object_label_of_a_calculated_column(self, tmp_path):
        model = _model(tmp_path, [("Fine", "1")])
        f = model / "definition" / "tables" / "Sales.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "\tcolumn Revenue",
                "\tcolumn Margin = SUM([Revenue]\n\t\tlineageTag: " + TAG.format(91) + "\n\n"
                "\tcolumn Revenue",
            ),
            encoding="utf-8",
        )
        found = violations(run_check(model, "D001", config=_no_threshold())[1], "D001")
        assert len(found) == 1
        assert found[0]["object"] == "Sales[Margin]"


class TestSummaryNote:
    def test_clean_model_still_reports_the_summary(self, tmp_path):
        model = _model(tmp_path, [("A", "1"), ("B", "2"), ("C", "3")])
        code, payload = run_check(model, "D001")
        assert code == 0
        assert any("Valid: 3 (100.0%)" in n for n in payload["notes"])
        assert any("Invalid: 0 (0.0%)" in n for n in payload["notes"])
        assert any("Total expressions: 3" in n for n in payload["notes"])

    def test_nine_clean_expressions_out_of_ten_pass_the_threshold(self, tmp_path):
        measures = [(f"M{i}", "1") for i in range(9)]
        measures.append(("Broken", "SUM([Revenue]"))
        model = _model(tmp_path, measures)
        found = violations(run_check(model, "D001")[1], "D001")
        assert not any("parse success rate below threshold" in v["message"] for v in found)


class TestNoMeasuresGuard:
    def test_model_with_tables_and_no_measures_fails(self, tmp_path):
        model = _model(tmp_path, [])
        code, payload = run_check(model, "D001")
        found = violations(payload, "D001")
        assert code == 1
        assert [v["severity"] for v in found] == ["error"]
        assert found[0]["message"] == "Shop.SemanticModel: no measures found (suspicious)"
