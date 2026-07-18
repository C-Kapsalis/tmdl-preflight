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
