"""Unit tests for the DAX text utilities."""

from __future__ import annotations

from tmdl_preflight.dax import (
    check_balanced_delimiters,
    collapse_comma_runs,
    extract_nameof_references,
    find_comma_runs,
    strip_comments,
    strip_strings,
)


class TestStripComments:
    def test_line_comment_dash(self):
        assert strip_comments("SUM([Cost]) -- note").rstrip() == "SUM([Cost])"

    def test_line_comment_slash(self):
        assert strip_comments("SUM([Cost]) // note").rstrip() == "SUM([Cost])"

    def test_block_comment(self):
        out = strip_comments("A /* gone */ B")
        assert "gone" not in out
        assert out.startswith("A ") and out.endswith(" B")

    def test_comment_marker_inside_string_survives(self):
        text = 'VAR x = "Revenue -- YoY" RETURN x'
        assert strip_comments(text) == text

    def test_comment_marker_inside_bracket_identifier_survives(self):
        text = "[--debug measure] + 1"
        assert strip_comments(text) == text

    def test_positions_preserved(self):
        text = "1 -- c\n2"
        assert len(strip_comments(text)) == len(text)


class TestStripStrings:
    def test_contents_blanked(self):
        out = strip_strings('LEFT("bike[x]", 2)')
        assert "bike" not in out
        assert out.count('"') == 2

    def test_escaped_quote(self):
        out = strip_strings('"say ""hi"" now" & [m]')
        assert "[m]" in out


class TestBalancedDelimiters:
    def test_clean(self):
        expr = 'CALCULATE(SUM(Sales[net_amount]), Products[category] = "Bikes")'
        assert check_balanced_delimiters(expr) == []

    def test_unmatched_open_paren(self):
        errors = check_balanced_delimiters("SUM(Sales[net_amount]")
        assert any("parenthesis" in e for e in errors)

    def test_unmatched_close_paren(self):
        errors = check_balanced_delimiters("SUM(Sales[net_amount]))")
        assert any("closing" in e for e in errors)

    def test_unterminated_bracket(self):
        errors = check_balanced_delimiters("SUM(Sales[net_amount")
        assert any("bracket" in e for e in errors)

    def test_unterminated_string(self):
        errors = check_balanced_delimiters('IF([x] > 0, "yes)')
        assert any("string" in e for e in errors)

    def test_braces(self):
        assert check_balanced_delimiters("{ (1, 2), (3, 4) }") == []
        errors = check_balanced_delimiters("{ (1, 2), (3, 4) ")
        assert len(errors) == 1  # the brace; parens inside are balanced

    def test_delimiters_inside_comments_ignored(self):
        assert check_balanced_delimiters("SUM([x]) -- (unclosed ( in comment") == []

    def test_delimiters_inside_strings_ignored(self):
        assert check_balanced_delimiters('[m] & ")()(("') == []

    def test_escaped_quote_in_identifier(self):
        assert check_balanced_delimiters("VAR x = 'It''s Fine'[col] RETURN x") == []


class TestNameofExtraction:
    def test_bare_measure(self):
        refs = extract_nameof_references('( "Revenue", NAMEOF ( [Revenue] ), 0 )')
        assert refs == [(None, "Revenue", 1)]

    def test_quoted_table_column(self):
        refs = extract_nameof_references("NAMEOF('Sales Measures'[Revenue])")
        assert refs == [("Sales Measures", "Revenue", 1)]

    def test_bare_table_column(self):
        refs = extract_nameof_references("NAMEOF(Sales[net_amount])")
        assert refs == [("Sales", "net_amount", 1)]

    def test_commented_row_excluded(self):
        text = '-- ( "Old", NAMEOF ( [Old] ), 9 )\n( "New", NAMEOF ( [New] ), 1 )'
        refs = extract_nameof_references(text)
        assert [(t, m) for t, m, _ in refs] == [(None, "New")]

    def test_line_numbers(self):
        text = '{\n  ( "A", NAMEOF([A]), 0 ),\n  ( "B", NAMEOF([B]), 1 )\n}'
        refs = extract_nameof_references(text)
        assert [(m, ln) for _, m, ln in refs] == [("A", 2), ("B", 3)]


class TestCommaRuns:
    def test_clean(self):
        assert find_comma_runs("{ (1, 2), (3, 4) }") == []

    def test_double_comma(self):
        runs = find_comma_runs("(1),, (2)")
        assert runs == [(1, 1)]

    def test_orphan_comma_across_lines(self):
        text = '{\n  ( "A", 1 ),\n\n  ,\n  ( "B", 2 )\n}'
        runs = find_comma_runs(text)
        assert len(runs) == 1

    def test_commented_comma_exempt(self):
        text = '( "A", 1 ),\n-- ( "B", 2 ),\n( "C", 3 )'
        assert find_comma_runs(text) == []

    def test_collapse_keeps_first_comma(self):
        text = '( "A", 1 ),\n  ,\n( "C", 3 )'
        fixed, removed = collapse_comma_runs(text)
        assert removed == 1
        assert fixed == '( "A", 1 ),\n  \n( "C", 3 )'
        # idempotent
        again, removed2 = collapse_comma_runs(fixed)
        assert removed2 == 0 and again == fixed

    def test_collapse_leaves_comments_alone(self):
        text = '( "A", 1 ),\n-- parked, on purpose,\n( "C", 3 )'
        fixed, removed = collapse_comma_runs(text)
        assert removed == 0 and fixed == text
