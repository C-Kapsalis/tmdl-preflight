"""The Q&A culture files that bind to tables the model no longer has.

An orphan binding is generated metadata, so it does not break a query, but
it is drift and a fingerprint of a table that left the model outside the
retirement channel.

Stand-in: ``tests/fixtures/culture_orphans`` -- a model with one live
table; the en-US culture file binds to it and to a table that is gone
(three nodes), the fr-FR file carries a binding on its own top level,
which binds to nothing.
"""
from __future__ import annotations

from conftest import run_check, run_cli, violations

STANDIN = "culture_orphans"
RULE = "culture-orphan-bindings"


def _model(stand_in):
    return stand_in(STANDIN) / "Model.SemanticModel"


def test_the_check_names_the_orphan_entities(stand_in):
    code, payload = run_check(_model(stand_in), RULE)
    assert code == 1
    found = violations(payload)
    assert len(found) == 1
    assert found[0]["message"].split("\n") == [
        "ORPHAN BINDINGS (1): Model.SemanticModel/definition/cultures/en-US.tmdl",
        "    entity -> '_Old Stores'",
    ]


def test_the_check_says_how_many_files_are_affected(stand_in):
    code, payload = run_check(_model(stand_in), RULE)
    assert "1 file(s) with orphan culture bindings." in payload["notes"]


def test_a_binding_on_the_top_level_of_the_document_binds_to_nothing(stand_in):
    """Only a member value or an array item is a node that binds."""
    code, payload = run_check(_model(stand_in), RULE)
    assert all("fr-FR" not in v["message"] for v in violations(payload))


def test_the_repair_drops_every_binding_node(stand_in):
    model = _model(stand_in)
    code, out, err = run_cli("fix", str(model), "--select", RULE)
    assert "-> dropped 3 binding node(s)" in out, out
    assert "Fixed 1 file(s); 3 binding node(s) removed." in out, out
    code, payload = run_check(model, RULE)
    assert violations(payload) == []


def test_a_repaired_file_keeps_its_line_endings(stand_in):
    model = _model(stand_in)
    culture = model / "definition" / "cultures" / "en-US.tmdl"
    culture.write_bytes(culture.read_bytes().replace(b"\n", b"\r\n"))
    code, out, err = run_cli("fix", str(model), "--select", RULE)
    raw = culture.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
