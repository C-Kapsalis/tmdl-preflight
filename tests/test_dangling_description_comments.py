"""TMDL `///` description comments must not dangle (M013).

Dangling-description gate (spec
A-dangling-description; fixer behaviour B-dangling-description-fixer).

A `///` run must be immediately followed by the declaration it documents,
never by a blank line or end of file. At end of file it is latent; the moment
anything is appended after it (for example the RangeStart/RangeEnd parameters
spliced onto ``expressions.tmdl`` for incremental refresh), the service rejects
the whole dataset:

    TMDL Format Error: Parsing error type - InvalidLineType
    Detailed error - Unexpected line type: Empty!  Document - './expressions'

The earlier check ran the repair script in check mode, failed with "no
auto-repair" unless a repair switch was set, and otherwise ran fix + re-check.
Here ``check`` is the read-only gate and ``fix`` the explicit repair.

Stand-ins (tests/fixtures/b3-a2/dangling_description_comments/): ``dd_bad``
has an orphan `///` run at the END of expressions.tmdl, ``dd_ok`` has its
description attached.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_fix, violations

STAND_INS = "b3-a2/dangling_description_comments"

# (stand-in, model folder, earlier verdict with the repair switch unset)
MODELS = [
    pytest.param("dd_bad", "dd_bad_db/Roastery.SemanticModel", "fail", id="dd_bad_db/Roastery"),
    pytest.param("dd_ok", "dd_ok_db/Roastery.SemanticModel", "pass", id="dd_ok_db/Roastery"),
]


def _definition(stand_in, name, folder) -> Path:
    return stand_in(f"{STAND_INS}/{name}") / folder / "definition"


@pytest.mark.parametrize("name,folder,verdict", MODELS)
def test_no_dangling_description_comments(stand_in, name, folder, verdict):
    definition = _definition(stand_in, name, folder)
    if not (definition / "tables").is_dir() and not (definition / "expressions.tmdl").exists():
        pytest.skip("model has no tables/ or expressions.tmdl")

    before = (definition / "expressions.tmdl").read_bytes()
    code, payload = run_check(definition, "M013")
    found = violations(payload, "M013")

    if verdict == "pass":
        assert code == 0 and found == []
        return

    # STRICTER (project decision): an end-of-file run is an ERROR, so the default
    # profile fails without --strict.
    assert code == 1
    assert len(found) == 1 and found[0]["severity"] == "error"
    # read-only: "no auto-repair" in the earlier check == check never writes
    assert (definition / "expressions.tmdl").read_bytes() == before


def test_dangling_description_repair_is_opt_in(stand_in):
    """Repair branch (switch = 1): fix, then a clean re-check."""
    definition = _definition(stand_in, "dd_bad", "dd_bad_db/Roastery.SemanticModel")
    code, payload = run_fix(definition, "M013")
    assert code == 0, payload
    text = (definition / "expressions.tmdl").read_text(encoding="utf-8")
    assert "US Format" not in text
    # the run goes, and the blank line before it becomes the file's last
    # line break: no trailing empty line
    assert text.endswith('IsParameterQueryRequired=true]\n')
    code, payload = run_check(definition, "M013")
    assert code == 0 and violations(payload, "M013") == []


# --- fixer stand-in cases (B-dangling-description-fixer / A-dangling-description) ---

def _model(tmp_path: Path, expressions: bytes) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text("model Model\n\tculture: en-US\n\nref table Roasts\n",
                                           encoding="utf-8")
    (definition / "tables" / "Roasts.tmdl").write_text(
        "table Roasts\n\tlineageTag: 0f6b7c2d-1e3a-4b5c-8d9e-0a1b2c3d4e5f\n", encoding="utf-8")
    (definition / "expressions.tmdl").write_bytes(expressions)
    return definition


def test_end_of_file_run_between_blank_lines(tmp_path):
    d = _model(tmp_path, b"expression A = 1\n\n\n/// x\n\n")
    code, payload = run_check(d, "M013")
    assert code == 1 and len(violations(payload, "M013")) == 1
    assert violations(payload, "M013")[0]["severity"] == "error"   # STRICTER
    run_fix(d, "M013")
    # the run goes, and the blank line before it becomes the file's last
    # line break: no trailing empty line
    assert (d / "expressions.tmdl").read_bytes() == b"expression A = 1\n\n"


def test_mid_file_run_is_removed_with_its_blank(tmp_path):
    d = _model(tmp_path, b'expression A = 1\n/// Old note\n\nexpression X = 1\n')
    code, payload = run_check(d, "M013")
    assert code == 1 and violations(payload, "M013")[0]["line"] == 2
    run_fix(d, "M013")
    assert (d / "expressions.tmdl").read_bytes() == b"expression A = 1\nexpression X = 1\n"


def test_attached_run_passes(tmp_path):
    d = _model(tmp_path, b"/// note\nexpression X = 1\n")
    code, payload = run_check(d, "M013")
    assert code == 0 and violations(payload, "M013") == []


def test_crlf_file_keeps_crlf(tmp_path):
    d = _model(tmp_path, b"expression A = 1\r\n/// Old note\r\n\r\nexpression X = 1\r\n")
    run_fix(d, "M013")
    assert (d / "expressions.tmdl").read_bytes() == b"expression A = 1\r\nexpression X = 1\r\n"


def test_two_offending_files_fail_check_and_stay_unchanged(tmp_path):
    d = _model(tmp_path, b"expression A = 1\n/// a\n\nexpression B = 2\n")
    t = d / "tables" / "Beans.tmdl"
    t.write_bytes(b"table Beans\n\n\t/// b\n\n\tcolumn origin\n\t\tdataType: string\n")
    before = [p.read_bytes() for p in (d / "expressions.tmdl", t)]
    code, payload = run_check(d, "M013")
    assert code != 0 and len(violations(payload, "M013")) == 2
    assert [p.read_bytes() for p in (d / "expressions.tmdl", t)] == before
