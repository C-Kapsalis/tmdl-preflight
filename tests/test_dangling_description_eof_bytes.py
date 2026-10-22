"""PA2: the bytes the M013 repair leaves at the end of a file.

When a dangling run is the last content of the file, the run and the line
break after it go, and a blank line directly before the run becomes the
file's last line break. A file that had a final newline keeps one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, run_fix


def _model(tmp_path: Path, body: bytes) -> Path:
    definition = tmp_path / "Shop.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    (definition / "model.tmdl").write_text(
        "model Model\n\tculture: en-US\n\nref table Roasts\n", encoding="utf-8")
    (definition / "tables" / "Roasts.tmdl").write_text(
        "table Roasts\n\tlineageTag: 0f6b7c2d-1e3a-4b5c-8d9e-0a1b2c3d4e5f\n",
        encoding="utf-8")
    (definition / "expressions.tmdl").write_bytes(body)
    return definition


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
def test_the_end_of_file_bytes(ending: bytes, tmp_path):
    """PA2: the exact bytes, with LF and with CRLF."""
    d = _model(tmp_path,
               b"expression A = 1" + ending + ending + b"/// x" + ending)
    code, payload = run_check(d, "M013")
    assert code == 1, payload
    run_fix(d, "M013")
    assert (d / "expressions.tmdl").read_bytes() == b"expression A = 1" + ending


def test_a_run_without_a_blank_line_before_it_keeps_the_final_newline(tmp_path):
    """PA2: `a\\n/// x\\n` becomes `a\\n`."""
    d = _model(tmp_path, b"expression A = 1\n/// x\n")
    code, payload = run_check(d, "M013")
    assert code == 1, payload
    run_fix(d, "M013")
    assert (d / "expressions.tmdl").read_bytes() == b"expression A = 1\n"


def test_a_second_repair_writes_nothing(tmp_path):
    """PA2: the repair converges."""
    d = _model(tmp_path, b"expression A = 1\n\n/// x\n")
    run_fix(d, "M013")
    before = (d / "expressions.tmdl").read_bytes()
    run_fix(d, "M013")
    assert (d / "expressions.tmdl").read_bytes() == before


def test_a_mid_file_run_keeps_the_blank_line_before_it(tmp_path):
    """PA2: only the END of the file changes the blank line before the run.

    A run in the middle of the file goes with the blank line AFTER it; the
    blank line before it stays.
    """
    d = _model(tmp_path, b"expression A = 1\n\n/// x\n\nexpression B = 2\n")
    code, payload = run_check(d, "M013")
    assert code == 1, payload
    run_fix(d, "M013")
    assert (d / "expressions.tmdl").read_bytes() == \
        b"expression A = 1\nexpression B = 2\n"
