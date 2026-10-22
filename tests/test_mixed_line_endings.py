"""A file that mixes its line endings is never rewritten.

A fleet committed from Windows, then touched by a tool that writes LF, ends
up with a file that mixes CRLF and LF. Such a file cannot be split on one
style and joined on another: the lines that use the other style fold into
one, and an edit computed on that deletes the model.

The tool must leave such a file exactly as it is and say why. The
violation stays on the report: the defect is still there.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _mixed(path: Path, body: str = "table 'Roast Measures'\n") -> Path:
    """A file whose first lines end with CRLF and whose rest end with LF."""
    lines = body.split("\n")
    head = "\r\n".join(lines[:2]) + "\r\n"
    tail = "\n".join(lines[2:])
    path.write_bytes((head + tail).encode("utf-8"))
    return path


def test_a_mixed_file_is_not_rewritten(tmp_path):
    """The edit is refused; the file keeps every byte."""
    from tmdl_preflight.edits import EditRefused, read_text_file, verified_write
    path = _mixed(tmp_path / "Mixed.tmdl",
                  "table 'Roast Measures'\n"
                  "\t/// An orphaned note nobody attached.\n"
                  "\n"
                  "\tmeasure 'Revenue' = 1\n")
    before = path.read_bytes()
    original = read_text_file(path)

    with pytest.raises(EditRefused):
        verified_write(original, original.text.replace("orphaned", "attached"))

    assert path.read_bytes() == before, "the mixed file was rewritten"


def test_a_mixed_file_is_reported(tmp_path):
    """The defect is still on the report; only the fix is refused."""
    from tmdl_preflight.edits import mixed_line_endings
    path = _mixed(tmp_path / "Mixed.tmdl",
                  "table 'Roast Measures'\n"
                  "\tmeasure 'Revenue' = 1\n"
                  "\tmeasure 'Cost' = 2\n")
    assert mixed_line_endings(path) is True


def test_a_normal_file_is_not_mixed(tmp_path):
    """A file with one style is not mixed."""
    from tmdl_preflight.edits import mixed_line_endings
    lf = tmp_path / "Lf.tmdl"
    lf.write_bytes(b"a\nb\nc\n")
    assert mixed_line_endings(lf) is False
    crlf = tmp_path / "Crlf.tmdl"
    crlf.write_bytes(b"a\r\nb\r\nc\r\n")
    assert mixed_line_endings(crlf) is False


def test_a_file_with_a_lone_cr_is_read_line_by_line(tmp_path):
    """PA-3: a lone CR is a line ending like any other."""
    from tmdl_preflight.edits import read_text_file
    path = tmp_path / "Cr.tmdl"
    path.write_bytes(b"a\rb\rc")
    tf = read_text_file(path)
    assert tf.lines() == ["a", "b", "c"], tf.lines()


def test_a_file_with_a_lone_cr_keeps_it(tmp_path):
    """PA-3: a fixer on such a file keeps the lone CR."""
    from tmdl_preflight.edits import read_text_file, verified_write
    path = tmp_path / "Cr.tmdl"
    path.write_bytes(b"a\rb\rc")
    original = read_text_file(path)
    verified_write(original, "a\rb\rc\rd")
    assert path.read_bytes() == b"a\rb\rc\rd", path.read_bytes()


def test_a_file_with_a_lone_cr_is_not_mixed(tmp_path):
    """PA-3: a lone-CR file has ONE style; it may be written."""
    from tmdl_preflight.edits import mixed_line_endings
    path = tmp_path / "Cr.tmdl"
    path.write_bytes(b"a\rb\rc")
    assert mixed_line_endings(path) is False


def test_a_fix_that_adds_a_line_keeps_the_file_s_style(tmp_path):
    """PA-2: the added line takes the file's own style."""
    from tmdl_preflight.edits import read_text_file, verified_write
    for ending in (b"\n", b"\r\n", b"\r"):
        path = tmp_path / f"F{len(ending)}.tmdl"
        path.write_bytes(b"a" + ending + b"b" + ending)
        before = path.read_bytes()
        original = read_text_file(path)
        assert original.newline == ending.decode(), (ending, original.newline)
        verified_write(original, "a" + ending.decode() + "b" + ending.decode()
                       + "c" + ending.decode())
        after = path.read_bytes()
        assert after == b"a" + ending + b"b" + ending + b"c" + ending, after
