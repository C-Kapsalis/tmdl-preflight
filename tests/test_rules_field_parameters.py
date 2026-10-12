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


# ---------------------------------------------------------------------------
# F002-F004
# ---------------------------------------------------------------------------

from tmdl_preflight.engine import check as run_check  # noqa: E402
from tmdl_preflight.engine import fix as run_fix  # noqa: E402
from tmdl_preflight.rules import default_ruleset  # noqa: E402
from tmdl_preflight.rules.base import Severity  # noqa: E402
from tmdl_preflight.rules.field_parameters import (  # noqa: E402
    MissingRowSeparatorRule,
    RaggedRowWidthRule,
    TrailingRowCommaRule,
)


def _selector(definition):
    return definition / "tables" / "Metric Selector.tmdl"


class TestMissingRowSeparator:
    def test_clean_passes(self, project):
        assert MissingRowSeparatorRule().check(Context(project)) == []

    def test_detected_and_fixed(self, project, definition, replace_in):
        replace_in(
            _selector(definition),
            '( "Orders #", NAMEOF ( [Orders #] ), 1 ),',
            '( "Orders #", NAMEOF ( [Orders #] ), 1 )',
        )
        rule = MissingRowSeparatorRule()
        violations = rule.check(Context(project))
        assert len(violations) == 1 and violations[0].line == 45
        assert rule.fix(Context(project))
        assert rule.check(Context(project)) == []
        assert rule.fix(Context(project)) == []
        assert '( "Orders #", NAMEOF ( [Orders #] ), 1 ),' in _selector(definition).read_text(
            encoding="utf-8"
        )

    def test_two_rows_on_one_line(self, project, definition, replace_in):
        replace_in(
            _selector(definition),
            '( "Orders #", NAMEOF ( [Orders #] ), 1 ),\n\t\t\t\t    ',
            '( "Orders #", NAMEOF ( [Orders #] ), 1 ) ',
        )
        assert len(MissingRowSeparatorRule().check(Context(project))) == 1
        report = run_fix(Context(project), default_ruleset())
        assert report.violations == []


class TestTrailingRowComma:
    def test_clean_passes(self, project):
        assert TrailingRowCommaRule().check(Context(project)) == []

    def test_detected_and_fixed(self, project, definition, replace_in):
        replace_in(
            _selector(definition),
            '( "Units Sold", NAMEOF ( [Units Sold] ), 3 )\n',
            '( "Units Sold", NAMEOF ( [Units Sold] ), 3 ),\n',
        )
        rule = TrailingRowCommaRule()
        assert len(rule.check(Context(project))) == 1
        assert rule.fix(Context(project))
        assert rule.check(Context(project)) == []
        assert rule.fix(Context(project)) == []

    def test_comma_run_before_brace_needs_both_fixers(self, project, definition, replace_in):
        replace_in(
            _selector(definition),
            '( "Units Sold", NAMEOF ( [Units Sold] ), 3 )\n',
            '( "Units Sold", NAMEOF ( [Units Sold] ), 3 ),\n\t\t\t\t    ,\n',
        )
        first = run_check(Context(project), default_ruleset())
        assert {"F001", "F003"} <= {v.rule_id for v in first.violations}
        report = run_fix(Context(project), default_ruleset())
        assert report.violations == []


class TestRaggedRows:
    def test_clean_passes(self, project):
        assert RaggedRowWidthRule().check(Context(project)) == []

    def test_detected_check_only(self, project, definition, replace_in):
        replace_in(
            _selector(definition),
            '( "Orders #", NAMEOF ( [Orders #] ), 1 ),',
            '( "Orders #", NAMEOF ( [Orders #] ) ),',
        )
        violations = RaggedRowWidthRule().check(Context(project))
        assert len(violations) == 1
        assert violations[0].severity == Severity.WARNING and not violations[0].fixable
        assert "1 row(s) with 2, 3 row(s) with 3" in violations[0].message
