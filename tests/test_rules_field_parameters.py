"""Rule F001: stray structural commas in calculated-table sources."""

from __future__ import annotations

from tmdl_preflight.rules.base import Context
from tmdl_preflight.rules.field_parameters import FieldParameterCommaRunsRule


def _inject_orphan_comma(definition):
    """Simulate dropping the 'Orders #' row but leaving its comma behind."""
    f = definition / "tables" / "Metric Selector.tmdl"
    text = f.read_text(encoding="utf-8")
    text = text.replace(
        '\t\t\t\t    ( "Orders #", NAMEOF ( [Orders #] ), 1 ),',
        "\t\t\t\t    ,",
    )
    f.write_text(text, encoding="utf-8")
    return f


class TestFieldParameterCommaRuns:
    def test_clean_passes(self, project):
        assert FieldParameterCommaRunsRule().check(Context(project)) == []

    def test_orphan_comma_detected(self, project, definition):
        _inject_orphan_comma(definition)
        violations = FieldParameterCommaRunsRule().check(Context(project))
        assert len(violations) == 1
        assert "stray comma run" in violations[0].message
        assert violations[0].fixable

    def test_fix_collapses_run_and_keeps_live_rows(self, project, definition):
        f = _inject_orphan_comma(definition)
        ctx = Context(project)
        rule = FieldParameterCommaRunsRule()
        assert rule.check(ctx)

        applied = rule.fix(ctx)
        assert applied and "orphan comma" in applied[0]

        ctx.reload()
        assert rule.check(ctx) == []
        text = f.read_text(encoding="utf-8")
        # surviving rows are intact
        assert 'NAMEOF ( [Revenue] ), 0 ),' in text
        assert 'NAMEOF ( [Units Sold] ), 3 )' in text
        # rest of the file untouched
        assert "extendedProperty ParameterMetadata" in text

    def test_fix_is_idempotent(self, project, definition):
        _inject_orphan_comma(definition)
        ctx = Context(project)
        rule = FieldParameterCommaRunsRule()
        rule.fix(ctx)
        ctx.reload()
        assert rule.fix(ctx) == []  # nothing left to do

    def test_commented_rows_do_not_trigger(self, project, definition):
        f = definition / "tables" / "Metric Selector.tmdl"
        text = f.read_text(encoding="utf-8")
        text = text.replace(
            '\t\t\t\t    ( "Orders #", NAMEOF ( [Orders #] ), 1 ),',
            '\t\t\t\t    -- ( "Orders #", NAMEOF ( [Orders #] ), 1 ),\n'
            '\t\t\t\t    ( "Orders #", NAMEOF ( [Orders #] ), 1 ),',
        )
        f.write_text(text, encoding="utf-8")
        assert FieldParameterCommaRunsRule().check(Context(project)) == []
