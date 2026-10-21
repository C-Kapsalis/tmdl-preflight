"""PA10: M018 reports one finding per duplicated name.

A name used three times yields ONE finding that says it appears three
times and lists every line — not two findings that each say "twice".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations


def _model(tmp_path: Path, model_tmdl: str) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(model_tmdl, encoding="utf-8")
    (definition / "tables" / "Sales.tmdl").write_text(
        "table Sales\n\tlineageTag: 00000000-0000-4000-8000-000000000001\n",
        encoding="utf-8")
    return definition


def test_a_name_used_three_times_is_one_finding(tmp_path):
    """PA10: one finding, naming every line."""
    d = _model(tmp_path,
               "model Model\n"
               "\tculture: en-US\n"
               "\tannotation PBI_QueryOrder = []\n"
               "\tannotation PBI_QueryOrder = []\n"
               "\tannotation PBI_QueryOrder = []\n")
    code, payload = run_check(d, "M018")
    found = violations(payload, "M018")
    assert code == 1, payload
    assert len(found) == 1, found
    message = found[0]["message"]
    assert "appears 3 times" in message, message
    assert "line 3, line 4, line 5" in message, message


def test_a_name_used_twice_is_one_finding(tmp_path):
    """PA10: the two-line form."""
    d = _model(tmp_path,
               "model Model\n"
               "\tannotation PBI_QueryOrder = []\n"
               "\tannotation PBI_QueryOrder = []\n")
    code, payload = run_check(d, "M018")
    found = violations(payload, "M018")
    assert len(found) == 1, found
    assert "appears 2 times" in found[0]["message"], found[0]["message"]


def test_a_query_group_duplicate_names_its_group(tmp_path):
    """PA10: the query-group form."""
    d = _model(tmp_path,
               "model Model\n"
               "\tqueryGroup Staging\n"
               "\t\tannotation note = a\n"
               "\t\tannotation note = b\n")
    code, payload = run_check(d, "M018")
    found = violations(payload, "M018")
    assert len(found) == 1, found
    message = found[0]["message"]
    assert "QueryGroup 'Staging'" in message, message
    assert "duplicate annotation 'note'" in message, message
