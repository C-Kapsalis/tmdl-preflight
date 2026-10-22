"""The layout of a field-parameter file: rows that carry a double slash, and
the blank lines a fenced source accumulates.

A row with `//` in it is either a row that was commented out or a label some
editor would truncate; either way it does not belong in the picker. A fenced
source that scripts keep rewriting grows blank lines and a drifted
indentation, so two copies of the same table stop comparing equal.

Rules: F016 fieldparam-double-slash-rows (info, opt-in repair),
F017 fieldparam-blank-lines (info, repair).
Fixtures: `tests/fixtures/fieldparam_double_slash`,
`tests/fixtures/fieldparam_blank_lines`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_fix, violations

pytestmark = [pytest.mark.p0]


def _model(stand_in, name):
    return stand_in(name) / "Model.SemanticModel"


def _table(model, name):
    return model / "definition" / "tables" / name


# ---------------------------------------------------------------------------
# F016
# ---------------------------------------------------------------------------


def test_a_row_that_carries_a_double_slash_is_reported(stand_in):
    model = _model(stand_in, "fieldparam_double_slash")
    code, payload = run_check(model, "F016")
    found = violations(payload, "F016")
    assert code == 0
    assert len(found) == 2
    assert all("'//'" in v["message"] for v in found)


def test_a_fenceless_source_is_not_inspected(stand_in):
    model = _model(stand_in, "fieldparam_double_slash")
    code, payload = run_check(model, "F016")
    assert not [v for v in violations(payload, "F016")
                if Path(v["file"]).name == "x-Selector 2.tmdl"]


def test_a_source_indented_with_three_tabs_is_not_inspected(stand_in):
    model = _model(stand_in, "fieldparam_double_slash")
    code, payload = run_check(model, "F016")
    assert not [v for v in violations(payload, "F016")
                if Path(v["file"]).name == "x-Selector 3.tmdl"]


def test_a_table_outside_the_axis_family_is_not_inspected(stand_in):
    model = _model(stand_in, "fieldparam_double_slash")
    code, payload = run_check(model, "F016")
    assert not [v for v in violations(payload, "F016")
                if Path(v["file"]).name == "Other Table.tmdl"]


def test_the_repair_removes_the_offending_rows(stand_in):
    model = _model(stand_in, "fieldparam_double_slash")
    code, payload = run_fix(model, "F016")
    assert code == 0
    text = _table(model, "x-Selector 1.tmdl").read_text(encoding="utf-8")
    assert '// ("Old KPI", NAMEOF([CPM]), 1, "old_x"),' not in text
    assert '("Web//App", NAMEOF([Margin %]), 3, "web_x"),' not in text
    # the rows that are clean, and the comment that is not a row, stay
    assert '("Revenue", NAMEOF(\'Sales\'[Revenue]), 0, "sales_x"),' in text
    assert "// section: sales" in text
    assert '("Orders", NAMEOF([Update Events]), 2, "sales_x")' in text


def test_the_repair_keeps_a_backup(stand_in):
    model = _model(stand_in, "fieldparam_double_slash")
    run_fix(model, "F016")
    backup = _table(model, "backups") / "x-Selector 1.tmdl.double_slash_backup"
    assert backup.is_file()
    assert '// ("Old KPI", NAMEOF([CPM]), 1, "old_x"),' in backup.read_text(encoding="utf-8")


def test_a_file_without_offending_rows_is_not_rewritten(stand_in):
    model = _model(stand_in, "fieldparam_double_slash")
    before = _table(model, "x-Selector 4.tmdl").read_bytes()
    run_fix(model, "F016")
    assert _table(model, "x-Selector 4.tmdl").read_bytes() == before


def test_the_repair_says_what_it_removed(stand_in):
    model = _model(stand_in, "fieldparam_double_slash")
    code, payload = run_fix(model, "F016")
    fixes = payload["fixes"]
    assert any(f.startswith("F016: Removing: ") for f in fixes), fixes
    assert any(f == "F016: ✓ x-Selector 1.tmdl: Removed 2/4 entries" for f in fixes), fixes
    blocks = payload["blocks"]
    assert any("Files modified: 1" in b and "Entries removed: 2" in b for b in blocks), blocks
    assert any(b.startswith("✓ Removed 2 entries") for b in blocks), blocks


# ---------------------------------------------------------------------------
# F017
# ---------------------------------------------------------------------------


def test_a_source_that_is_not_canonical_is_reported(stand_in):
    model = _model(stand_in, "fieldparam_blank_lines")
    code, payload = run_check(model, "F017")
    found = violations(payload, "F017")
    assert code == 0
    assert len(found) == 3
    assert all(v["severity"] == "info" for v in found)


def test_a_canonical_source_passes(stand_in):
    model = _model(stand_in, "fieldparam_blank_lines")
    code, payload = run_check(model, "F017")
    assert not [v for v in violations(payload, "F017")
                if Path(v["file"]).name == "x-Selector 3.tmdl"]


def test_a_bare_source_is_not_inspected(stand_in):
    model = _model(stand_in, "fieldparam_blank_lines")
    code, payload = run_check(model, "F017")
    assert not [v for v in violations(payload, "F017")
                if Path(v["file"]).name == "x-Selector 4.tmdl"]


def test_a_partition_that_is_not_calculated_is_not_inspected(stand_in):
    model = _model(stand_in, "fieldparam_blank_lines")
    code, payload = run_check(model, "F017")
    assert not [v for v in violations(payload, "F017")
                if Path(v["file"]).name == "Other Table.tmdl"]


def test_the_repair_leaves_one_blank_line_between_row_groups(stand_in):
    model = _model(stand_in, "fieldparam_blank_lines")
    code, payload = run_fix(model, "F017")
    assert code == 0
    text = _table(model, "x-Selector 1.tmdl").read_text(encoding="utf-8")
    body = text.split("source = ```", 1)[1]
    assert body.count("\n\n") == 1, repr(body)


def test_the_repair_takes_the_blank_lines_before_the_brace_away(stand_in):
    model = _model(stand_in, "fieldparam_blank_lines")
    run_fix(model, "F017")
    text = _table(model, "x-Plot Specific 1.tmdl").read_text(encoding="utf-8")
    body = text.split("source = ```", 1)[1]
    assert body.count("\n\n") == 0, repr(body)


def test_the_repair_reindents_the_braces_and_leaves_the_rows_alone(stand_in):
    model = _model(stand_in, "fieldparam_blank_lines")
    run_fix(model, "F017")
    text = _table(model, "x-Selector 2.tmdl").read_text(encoding="utf-8")
    assert "\t\t\t\t{\n" in text
    assert "\t\t\t\t}\n" in text
    assert '\t\t("Revenue", NAMEOF(\'Sales\'[Revenue]), 0, "sales_x"),\n' in text


def test_the_repair_says_what_it_changed(stand_in):
    model = _model(stand_in, "fieldparam_blank_lines")
    code, payload = run_fix(model, "F017")
    fixes = payload["fixes"]
    assert any(f.startswith("F017: ✓ x-Selector 1.tmdl: removed ") for f in fixes), fixes
    code, payload = run_check(model, "F017")
    assert violations(payload, "F017") == []
