"""
Test Enhanced DAX Parser - Phase 2.3A

Tests for context-aware comment handling that fixes the top 5 parser failure patterns:
1. Line comments (--) at end of lines
2. Line comments (--) inside strings
3. Double-slash comments (//)
4. Block comments (/* */)
5. Mixed comment styles

These tests validate that the parser correctly handles comments while preserving
string contents and delimiter balancing.
"""

from tmdl_preflight.dax import check_balanced_delimiters, strip_comments
from tmdl_preflight.dax import strip_strings as strip_string_literals


class TestCommentStripping:
    """Test comment stripping functionality"""

    def test_strip_line_comment_simple(self):
        """Line comments should be stripped"""
        dax = 'VAR x = 1 -- This is a comment\nRETURN x'
        result = strip_comments(dax)
        assert '--' not in result or 'comment' not in result.lower()
        assert 'VAR x = 1' in result
        assert 'RETURN x' in result

    def test_strip_line_comment_inline(self):
        """Inline line comments should be stripped"""
        dax = 'SUM([Cost]),--[Old]'
        result = strip_comments(dax)
        assert 'SUM([Cost]),' in result
        assert '[Old]' not in result or '--' not in result

    def test_preserve_comment_in_string(self):
        """Comments inside strings should be preserved"""
        dax = 'VAR x = "Revenue -- YoY"\nRETURN x'
        result = strip_comments(dax)
        assert '"Revenue -- YoY"' in result
        assert 'Revenue -- YoY' in result

    def test_strip_double_slash_comment(self):
        """Double-slash comments should be stripped"""
        dax = 'VAR x = 1 // This is a comment\nRETURN x'
        result = strip_comments(dax)
        assert 'VAR x = 1' in result
        assert 'RETURN x' in result
        assert '//' not in result or 'comment' not in result.lower()

    def test_strip_block_comment(self):
        """Block comments should be stripped"""
        dax = '/* This is a block comment */\nVAR x = 1\nRETURN x'
        result = strip_comments(dax)
        assert 'VAR x = 1' in result
        assert 'RETURN x' in result
        assert '/*' not in result
        assert 'block comment' not in result.lower()


class TestStringLiteralStripping:
    """Test string-literal stripping (used by reference extraction
    to avoid matching column/measure refs typed inside DAX string literals)."""

    def test_blank_simple_string(self):
        """String contents replaced with spaces; surrounding quotes preserved"""
        dax = 'IF([Service] = "google_ads", 1, 0)'
        result = strip_string_literals(dax)
        # 10 inner spaces between the preserved quote chars
        assert result == 'IF([Service] = "          ", 1, 0)'

    def test_quotes_preserved(self):
        """The double-quote chars themselves stay in place; only content blanked"""
        result = strip_string_literals('a "bcd" e')
        assert result.startswith('a "') and result.endswith('" e')
        # Quote count is preserved (string-boundary tracking still valid)
        assert result.count('"') == 2

    def test_position_preserved(self):
        """Output is the same length as input — refs after a string don't shift"""
        dax = 'SUM(Tab[col]) + "abc" + [Measure]'
        result = strip_string_literals(dax)
        assert len(result) == len(dax)

    def test_brackets_inside_string_are_blanked(self):
        """Refs typed inside a string literal must not survive the pass"""
        dax = '"this is fake [TableX][colY]"'
        result = strip_string_literals(dax)
        assert '[TableX]' not in result
        assert '[colY]' not in result

    def test_escaped_double_quote(self):
        """DAX uses "" as an escaped double quote — should NOT close the string"""
        # "He said ""hi""" — represents: He said "hi"
        dax = '"a ""b"" c"'
        result = strip_string_literals(dax)
        # No ref-eligible characters survive
        assert '[' not in result
        assert ']' not in result
        # Length preserved
        assert len(result) == len(dax)

    def test_unrelated_outside_strings_untouched(self):
        """Content outside strings is not modified"""
        dax = 'SUM(Sales[Amount]) + [Profit]'
        result = strip_string_literals(dax)
        assert result == dax

    def test_empty_string(self):
        result = strip_string_literals('""')
        assert result == '""'

    def test_no_strings(self):
        result = strip_string_literals('CALCULATE(SUM(Sales[Amount]))')
        assert result == 'CALCULATE(SUM(Sales[Amount]))'

    def test_strip_multiline_block_comment(self):
        """Multiline block comments should be stripped"""
        dax = '''/*
        Multi-line
        block comment
        */
        VAR x = 1
        RETURN x'''
        result = strip_comments(dax)
        assert 'VAR x = 1' in result
        assert 'RETURN x' in result
        assert 'Multi-line' not in result


class TestEnhancedParser:
    """Test enhanced parser with comment handling"""

    def test_comments_in_strings_ignored(self):
        """Comments inside strings should be ignored"""
        dax = 'VAR x = "Revenue -- YoY"\nRETURN x'
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_line_comment_at_end(self):
        """Line comments at end of lines should be handled"""
        dax = 'CALCULATE(\n    SUM([Cost]),--[Old]\n    [Date] > 100\n)'
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_line_comment_at_start(self):
        """Line comments at start of lines should be handled"""
        dax = '-- This is a comment\nSUM([Cost])'
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_double_slash_comment(self):
        """Double-slash comments should be handled"""
        dax = '// Comment\nSUM([Cost])'
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_block_comment(self):
        """Block comments should be handled"""
        dax = '/* Comment */\nSUM([Cost])'
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_mixed_comment_styles(self):
        """Mixed comment styles should be handled"""
        dax = '''
        /* Block comment */
        -- Line comment
        VAR x = 1 // Inline comment
        VAR y = "Text -- with dashes" -- Another comment
        RETURN x + y
        '''
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_commented_out_unmatched_delimiter(self):
        """Unmatched delimiters in comments should be ignored"""
        dax = 'VAR x = 1 -- Missing paren (\nRETURN x'
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_real_world_example_1(self):
        """Real failure case: inline comment with closing paren"""
        dax = 'CALCULATE(\n    DISTINCTCOUNT([id]),--[old_id]),\n    [Date] > 100\n)'
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_real_world_example_2(self):
        """Real failure case: comment at start of measure"""
        dax = "-- this measure's results cannot be broken down by crawl-related dims\n\nSWITCH(\n    TRUE(),\n    [x] <> \"good\", BLANK(),\n    [Cost] + [Extra]\n)"
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_real_world_example_3(self):
        """Real failure case: block comment with decorative borders"""
        dax = '''/*──────────────────────────────────────────────
        1.  One row per ID, with its own
            average-across-dates (only CPC ≥ 0.01)
        ──────────────────────────────────────────────*/
        VAR _avgPerId =
            CALCULATE([Cost])
        RETURN _avgPerId'''
        errors = check_balanced_delimiters(dax)
        assert errors == []


class TestEdgeCases:
    """Test edge cases and corner scenarios"""

    def test_escaped_quotes_with_comments(self):
        """Escaped quotes with comments should work"""
        dax = "VAR x = 'O''Brien' -- Comment\nRETURN x"
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_multiple_strings_with_dashes(self):
        """Multiple strings with dashes should work"""
        dax = 'VAR x = "A -- B"\nVAR y = "C -- D"\nRETURN x & y'
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_unicode_in_comments(self):
        """Unicode characters in comments should work"""
        dax = '-- Comment with unicode: ≥ ≤ ≠\nSUM([Cost])'
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_nested_block_comments(self):
        """Nested block comments should work"""
        dax = '/* Outer /* Inner */ Still outer */\nSUM([Cost])'
        errors = check_balanced_delimiters(dax)
        assert errors == []

    def test_comment_chars_in_strings_dont_start_comments(self):
        """Comment characters in strings should not start comments"""
        dax = 'VAR url = "https://example.com" -- Real comment\nRETURN url'
        errors = check_balanced_delimiters(dax)
        assert errors == []


class TestBackwardsCompatibility:
    """Ensure existing functionality still works"""

    def test_unmatched_paren_still_detected(self):
        """Unmatched parentheses should still be detected"""
        dax = 'SUM([Cost]'
        errors = check_balanced_delimiters(dax)
        assert len(errors) > 0
        assert 'paren' in errors[0].lower() or '(' in errors[0]

    def test_unmatched_bracket_still_detected(self):
        """Unmatched brackets should still be detected"""
        dax = 'SUM([Cost)'
        errors = check_balanced_delimiters(dax)
        assert len(errors) > 0
        assert 'bracket' in errors[0].lower() or '[' in errors[0]

    def test_unmatched_quote_still_detected(self):
        """Unmatched quotes should still be detected"""
        dax = 'VAR x = "Unclosed string\nRETURN x'
        errors = check_balanced_delimiters(dax)
        assert len(errors) > 0
        assert 'quote' in errors[0].lower()

    def test_valid_expression_still_passes(self):
        """Valid expressions should still pass"""
        dax = 'CALCULATE(\n    SUM([Cost]),\n    [Date] >= TODAY()\n)'
        errors = check_balanced_delimiters(dax)
        assert errors == []
