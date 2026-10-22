"""D001 delimiter messages: the reference wording, the character position and
the order the findings come in.

The checker's own strings are the contract here, so they are quoted exactly.
"""

from __future__ import annotations

from tmdl_preflight.dax import check_balanced_delimiters, strip_strings


class TestReferenceWording:
    def test_unmatched_opening_parenthesis(self):
        assert check_balanced_delimiters("SUM([Cost]") == [
            "Unmatched opening parenthesis '(' at position 3"
        ]

    def test_unmatched_closing_parenthesis(self):
        assert check_balanced_delimiters("SUM([Cost]))") == [
            "Unmatched closing parenthesis ')' at position 11"
        ]

    def test_unmatched_opening_bracket(self):
        assert check_balanced_delimiters("SUM([Cost)") == [
            "Unmatched opening bracket '[' at position 4"
        ]

    def test_unmatched_brace(self):
        assert check_balanced_delimiters("{ (1, 2) ") == [
            "Unmatched opening brace '{' at position 0"
        ]

    def test_unmatched_double_quote(self):
        assert check_balanced_delimiters('CALCULATE(SUM([Cost]), "Q1') == [
            "Unmatched opening parenthesis '(' at position 9",
            "Unmatched opening double quote at position 23",
        ]

    def test_unmatched_single_quote(self):
        assert check_balanced_delimiters("COUNTROWS('Bike Shops") == [
            "Unmatched opening parenthesis '(' at position 9",
            "Unmatched opening single quote at position 10",
        ]


class TestOneOpeningPerKind:
    def test_two_open_parentheses_report_the_earliest(self):
        assert check_balanced_delimiters("((SUM([Cost])") == [
            "Unmatched opening parenthesis '(' at position 0"
        ]

    def test_closers_come_first_in_text_order(self):
        errors = check_balanced_delimiters("SUM([Cost])) )")
        assert errors[0] == "Unmatched closing parenthesis ')' at position 11"
        assert errors[1] == "Unmatched closing parenthesis ')' at position 13"

    def test_kinds_mixed_in_text_order(self):
        errors = check_balanced_delimiters(") ] }")
        assert errors == [
            "Unmatched closing parenthesis ')' at position 0",
            "Unmatched closing bracket ']' at position 2",
            "Unmatched closing brace '}' at position 4",
        ]

    def test_openers_come_in_the_reference_order(self):
        errors = check_balanced_delimiters("{[(")
        assert errors == [
            "Unmatched opening parenthesis '(' at position 2",
            "Unmatched opening bracket '[' at position 1",
            "Unmatched opening brace '{' at position 0",
        ]


class TestStrayClosingBracket:
    def test_closing_bracket_outside_a_name(self):
        assert check_balanced_delimiters("SUM(Cost])") == [
            "Unmatched closing bracket ']' at position 8"
        ]

    def test_two_stray_brackets(self):
        assert check_balanced_delimiters("[a]] b]") == [
            "Unmatched closing bracket ']' at position 3",
            "Unmatched closing bracket ']' at position 6",
        ]

    def test_double_bracket_outside_a_name_is_two_closers(self):
        assert check_balanced_delimiters("a]]") == [
            "Unmatched closing bracket ']' at position 1",
            "Unmatched closing bracket ']' at position 2",
        ]


class TestLegalNamesAreNotCode:
    def test_apostrophe_inside_a_bracketed_name(self):
        assert check_balanced_delimiters("SUM([Customer's Count])") == []

    def test_parenthesis_inside_a_bracketed_name(self):
        assert check_balanced_delimiters("SUM([Cost (USD])") == []


class TestInterleavedDelimiters:
    def test_brace_inside_parenthesis(self):
        assert check_balanced_delimiters("{(})") == [
            "Unmatched closing brace '}' at position 2",
            "Unmatched opening brace '{' at position 0",
        ]


class TestUnterminatedBlockComment:
    def test_delimiters_after_an_unterminated_block_comment(self):
        assert check_balanced_delimiters("/* unterminated ( SUM(") == [
            "Unmatched opening parenthesis '(' at position 16"
        ]


class TestStringBlanking:
    def test_escaped_quote_becomes_two_spaces(self):
        assert strip_strings('"a""b"') == '"    "'

    def test_empty_string_keeps_its_quotes(self):
        assert strip_strings('""') == '""'
