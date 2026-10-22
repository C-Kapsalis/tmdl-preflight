"""A malformed input is a configuration error, never a Python traceback.

A CI job hands the tool an artifact: a manifest, a schema snapshot, a
field-parameter table. The artifact may be hand-edited, truncated or written
by another version of the tool. Whatever it is, the command must refuse it
the way it refuses any other configuration problem: exit 2, a message on
standard error, and never a Python traceback.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import run_cli


def _run(*args):
    return run_cli(*[str(a) for a in args])


def test_schema_check_refuses_a_manifest_that_is_not_an_object(tmp_path):
    """A list in place of the manifest is a configuration error."""
    manifest = tmp_path / "m.json"
    manifest.write_text("[1, 2]", encoding="utf-8")
    schema = tmp_path / "s.json"
    schema.write_text("{}", encoding="utf-8")

    code, out, err = _run("schema-check", "--manifest", manifest, "--schema",
                          schema)
    assert code == 2, out
    assert "Traceback" not in out and "Traceback" not in err
    assert "manifest" in err, err


def test_schema_check_refuses_a_schema_that_is_not_an_object(tmp_path):
    """A list in place of the schema snapshot is a configuration error."""
    manifest = tmp_path / "m.json"
    manifest.write_text("{}", encoding="utf-8")
    schema = tmp_path / "s.json"
    schema.write_text("[1, 2]", encoding="utf-8")

    code, out, err = _run("schema-check", "--manifest", manifest, "--schema",
                          schema)
    assert code == 2, out
    assert "Traceback" not in out and "Traceback" not in err
    assert "schema snapshot" in err, err


def test_fieldparam_retag_refuses_a_file_it_cannot_read(tmp_path):
    """A file that is not UTF-8 is a configuration error."""
    bad = tmp_path / "Bad.tmdl"
    bad.write_bytes(b"\xff\xfe junk")

    code, out, err = _run("fieldparam", "retag", "--names", "X", "--from",
                          "a", "--to", "b", bad)
    assert code == 2, out
    assert "Traceback" not in out and "Traceback" not in err
    assert err.strip(), "the refusal must say something on stderr"
