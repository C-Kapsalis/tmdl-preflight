"""Rule S001: format-string presence (advisory)."""

from __future__ import annotations

from tmdl_preflight.rules.base import Context, Severity
from tmdl_preflight.rules.style import FormatStringPresenceRule


class TestFormatStringPresence:
    def test_clean_passes(self, project):
        assert FormatStringPresenceRule().check(Context(project)) == []

    def test_visible_measure_without_format_flagged(self, project, definition):
        f = definition / "tables" / "Sales Measures.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "\tmeasure 'Units Sold' = SUM(Sales[quantity])\n\t\tformatString: #,0\n",
                "\tmeasure 'Units Sold' = SUM(Sales[quantity])\n",
            ),
            encoding="utf-8",
        )
        violations = FormatStringPresenceRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].severity == Severity.INFO
        assert "Units Sold" in (violations[0].obj or "")

    def test_hidden_measure_exempt(self, project):
        # 'countrows sales' on the Sales table is hidden and has no
        # formatString, yet the clean check passes.
        assert FormatStringPresenceRule().check(Context(project)) == []

    def test_dynamic_format_model_exempt(self, project, definition):
        # a model with formatStringDefinition blocks applies formats via
        # calculation groups; static formatString absence is fine there.
        f = definition / "tables" / "Sales Measures.tmdl"
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "\tmeasure 'Units Sold' = SUM(Sales[quantity])\n\t\tformatString: #,0\n",
                "\tmeasure 'Units Sold' = SUM(Sales[quantity])\n",
            ),
            encoding="utf-8",
        )
        (definition / "tables" / "Format Modes.tmdl").write_text(
            "table 'Format Modes'\n"
            "\tlineageTag: 55555555-5555-4555-8555-555555555555\n"
            "\n"
            "\tcalculationGroup\n"
            "\n"
            "\t\tcalculationItem Default = SELECTEDMEASURE()\n"
            "\n"
            "\t\t\tformatStringDefinition = \"#,0\"\n",
            encoding="utf-8",
        )
        assert FormatStringPresenceRule().check(Context(project)) == []


# ---------------------------------------------------------------------------
# S001 measure-level formatStringDefinition, S002
# ---------------------------------------------------------------------------

from tmdl_preflight.rules.style import MeasureDescriptionRule  # noqa: E402


def _measures(definition):
    return definition / "tables" / "Sales Measures.tmdl"


def test_measure_format_string_definition_exempts_only_that_measure(
    project, definition, replace_in
):
    f = _measures(definition)
    replace_in(f, "\t\tformatString: #,0\n\t\tlineageTag: d5884859", "\t\tlineageTag: d5884859")
    replace_in(f, "\t\tformatString: #,0\n\t\tlineageTag: b3662637", "\t\tlineageTag: b3662637")
    replace_in(
        f,
        "\t\tlineageTag: d5884859-48d9-4a1b-a03c-374859607182\n",
        "\t\tlineageTag: d5884859-48d9-4a1b-a03c-374859607182\n\n"
        '\t\tformatStringDefinition = "#,0"\n',
    )
    violations = FormatStringPresenceRule().check(Context(project))
    # Units Sold has a dynamic format; Orders # still has none
    assert [v.obj for v in violations] == ["Sales Measures[Orders #]"]


class TestMeasureDescriptions:
    def test_clean_passes(self, project):
        assert MeasureDescriptionRule().check(Context(project)) == []

    def test_missing_description(self, project, definition, replace_in):
        replace_in(_measures(definition), "\t/// Number of distinct orders placed.\n", "")
        violations = MeasureDescriptionRule().check(Context(project))
        assert [v.obj for v in violations] == ["Sales Measures[Orders #]"]
        assert violations[0].severity == Severity.INFO

    def test_placeholder_and_short_descriptions(self, project, definition, replace_in):
        f = _measures(definition)
        replace_in(f, "/// Number of distinct orders placed.", "/// TODO: describe")
        replace_in(f, "/// Total number of units sold across all order lines.", "/// Units")
        violations = MeasureDescriptionRule().check(Context(project))
        assert {v.obj for v in violations} == {
            "Sales Measures[Orders #]", "Sales Measures[Units Sold]"
        }

    def test_options(self, project, definition, replace_in):
        replace_in(_measures(definition), "/// Total number of units sold across all order lines.", "/// Units")
        rule = MeasureDescriptionRule()
        rule.configure({"min_length": 3, "placeholder_words": ["placeholder"]})
        assert rule.check(Context(project)) == []

    def test_hidden_measures_exempt(self, project):
        # 'countrows sales' is hidden and has no description
        assert MeasureDescriptionRule().check(Context(project)) == []
