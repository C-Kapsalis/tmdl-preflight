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


# ---------------------------------------------------------------------------
# 1.1.0: lexer edge cases, references, variables, table constructors
# ---------------------------------------------------------------------------

from tmdl_preflight.dax import (  # noqa: E402
    BRACKET,
    IDENT,
    classify,
    extract_references,
    find_outer_scope_duplicate_vars,
    insert_missing_row_separators,
    remove_trailing_row_commas,
    scan_table_constructors,
    string_literals,
)


class TestLexerEdgeCases:
    def test_doubled_quote_inside_table_name(self):
        text = "'Bob''s Sales'[x]"
        tags = classify(text)
        # the whole quoted name, escape included, is one identifier region
        assert tags[: len("'Bob''s Sales'")] == IDENT * len("'Bob''s Sales'")
        refs = extract_references(text)
        assert [(r.kind, r.table, r.member) for r in refs] == [("column", "Bob's Sales", "x")]

    def test_doubled_bracket_escape(self):
        text = "[Margin ]] %] + 1"
        tags = classify(text)
        assert tags[: len("[Margin ]] %]")] == BRACKET * len("[Margin ]] %]")
        assert extract_references(text)[0].member == "Margin ] %"

    def test_comment_marker_inside_brackets_is_not_a_comment(self):
        text = "[a -- b] + [c // d]"
        assert check_balanced_delimiters(text) == []
        assert [r.member for r in extract_references(text)] == ["a -- b", "c // d"]

    def test_comment_marker_inside_quoted_table_name(self):
        text = "COUNTROWS('x -- y')"
        refs = extract_references(text)
        assert [(r.kind, r.table) for r in refs] == [("table", "x -- y")]


class TestExtractReferences:
    def test_forms(self):
        text = "CALCULATE([Revenue], 'Sales'[qty] > 0, Products[cat] = \"a\", ALL('Stores'))"
        refs = [(r.kind, r.table, r.member) for r in extract_references(text)]
        assert refs == [
            ("bare", None, "Revenue"),
            ("column", "Sales", "qty"),
            ("column", "Products", "cat"),
            ("table", "Stores", None),
        ]

    def test_strings_and_comments_are_ignored(self):
        text = "\"'Fake'[x]\" -- 'Gone'[y]\n/* [z] */ [Real]"
        assert [r.member for r in extract_references(text)] == ["Real"]

    def test_keyword_before_bracket_is_not_a_table(self):
        refs = extract_references("VAR x = 1 RETURN [Revenue]")
        assert refs[0].kind == "bare" and refs[0].prev_word == "RETURN"

    def test_line_numbers(self):
        refs = extract_references("1 +\n  [A] +\n  'T'[b]")
        assert [r.line for r in refs] == [2, 3]

    def test_string_literals(self):
        assert string_literals('ADDCOLUMNS(T, "New Col", 1, "Say ""hi""", 2)') == {
            "New Col", 'Say "hi"'
        }


class TestDuplicateVars:
    def test_outer_scope_duplicate(self):
        text = "VAR a = 1\nVAR b = 2\nVAR a = 3\nRETURN a + b"
        assert find_outer_scope_duplicate_vars(text) == [("a", 3)]

    def test_nested_scopes_are_legal(self):
        text = (
            "IF(x, VAR t = 1 RETURN t, VAR t = 2 RETURN t)"
        )
        assert find_outer_scope_duplicate_vars(text) == []

    def test_case_insensitive_and_comments_ignored(self):
        text = "VAR Total = 1\n-- VAR total = 2\nvar TOTAL = 3\nRETURN Total"
        assert find_outer_scope_duplicate_vars(text) == [("TOTAL", 3)]


class TestTableConstructors:
    def test_clean_rows(self):
        text = '{\n  ( "A", NAMEOF([A]), 0 ),\n  ( "B", NAMEOF([B]), 1 )\n}'
        assert scan_table_constructors(text) == []

    def test_missing_separator_across_lines(self):
        text = '{\n  ( "A", NAMEOF([A]), 0 )\n  ( "B", NAMEOF([B]), 1 )\n}'
        issues = scan_table_constructors(text)
        assert [(i.kind, i.line) for i in issues] == [("missing_separator", 2)]
        fixed, n = insert_missing_row_separators(text)
        assert n == 1 and scan_table_constructors(fixed) == []
        assert fixed.replace(",", "") == text.replace(",", "")

    def test_missing_separator_two_rows_on_one_line(self):
        text = '{ ("A", 0) ("B", 1), ("C", 2) }'
        issues = scan_table_constructors(text)
        assert [i.kind for i in issues] == ["missing_separator"]
        assert insert_missing_row_separators(text)[0] == '{ ("A", 0), ("B", 1), ("C", 2) }'

    def test_tuple_split_across_lines(self):
        text = '{\n  (\n    "A",\n    NAMEOF([A]),\n    0\n  ),\n  ( "B", NAMEOF([B]), 1 )\n}'
        assert scan_table_constructors(text) == []

    def test_trailing_comma(self):
        text = '{\n  ( "A", 0 ),\n  ( "B", 1 ), -- last row\n}'
        issues = scan_table_constructors(text)
        assert [(i.kind, i.line) for i in issues] == [("trailing_comma", 3)]
        fixed, n = remove_trailing_row_commas(text)
        assert n == 1 and fixed == '{\n  ( "A", 0 ),\n  ( "B", 1 ) -- last row\n}'

    def test_ragged_rows(self):
        text = '{ ("A", NAMEOF([A]), 0), ("B", NAMEOF([B])), ("C", NAMEOF([C]), 2) }'
        issues = scan_table_constructors(text)
        assert [i.kind for i in issues] == ["ragged"]
        assert issues[0].widths == (3, 2, 3)

    def test_commas_in_nested_calls_and_strings_do_not_count(self):
        text = '{ ("a,b", FORMAT(1, "0,0"), 0), ("c", FORMAT(2, "0"), 1) }'
        assert scan_table_constructors(text) == []

    def test_scalar_constructor(self):
        assert scan_table_constructors("{1, 2, 3}") == []
        assert [i.kind for i in scan_table_constructors("{1, 2, }")] == ["trailing_comma"]

    def test_comma_inside_comment_is_ignored(self):
        text = '{\n  ( "A", 0 )\n  -- ( "B", 1 ),\n}'
        assert scan_table_constructors(text) == []
