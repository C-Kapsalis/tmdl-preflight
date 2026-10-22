"""The opt-in rules say so, and the catalog lists how to enable them.

* PA41: the rules that encode one team's conventions are marked opt-in,
  their descriptions say so, and the catalog names the `select` line that
  turns the whole reference set on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli
from tmdl_preflight.rules import full_ruleset

#: the rules the reference suite always ran
REFERENCE_SET = [f"O{n:03d}" for n in range(1, 16)] + ["C012", "S003", "N020"]


def test_every_reference_rule_is_opt_in():
    """PA41: the reference set runs only when it is named."""
    rules = {r.id: r for r in full_ruleset().rules}
    for rid in REFERENCE_SET:
        assert rules[rid].opt_in is True, rid


def test_every_reference_rule_says_it_is_opt_in():
    """PA41: the description says so."""
    rules = {r.id: r for r in full_ruleset().rules}
    for rid in REFERENCE_SET:
        assert "opt-in" in rules[rid].description.lower(), rid


def test_the_catalog_lists_the_select_line():
    """PA41: the catalog names the line that enables the reference set."""
    code, out, err = run_cli("rules", "--format", "markdown")
    assert code == 0, err
    assert "select" in out, out
    for rid in REFERENCE_SET:
        assert rid in out, rid


def test_the_json_marks_them():
    """PA41: the JSON says which rules are opt-in."""
    code, out, err = run_cli("rules", "--json")
    assert code == 0, err
    rules = {r["id"]: r for r in json.loads(out)}
    for rid in REFERENCE_SET:
        assert rules[rid]["opt_in"] is True, rid
