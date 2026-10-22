"""`cultures/*.tmdl` must not bind to tables the model no longer has.

An orphan binding is a
`Binding.ConceptualEntity` naming a missing table: generated Q&A metadata, so
it does not break queries, but it is drift and a fingerprint of a table
removed outside the retirement channel (dangling DAX refs are likely too).

Rule (new, selected by name): culture-orphan-bindings (error, fixable).
The stand-in fleet is listed explicitly; ``check`` reports and
``fix --select`` repairs.
"""

from __future__ import annotations

import pytest

from conftest import run_check, run_fix, violations

FLEET = "measure_organization_fleet"
MODELS = ["universal/Performance.SemanticModel", "spinout_02_db/Performance.SemanticModel"]
RULE = "culture-orphan-bindings"


@pytest.mark.parametrize("model_rel", MODELS, ids=lambda p: p.split("/")[0])
def test_no_orphan_culture_bindings(stand_in, model_rel):
    model = stand_in(FLEET) / model_rel
    if not (model / "definition" / "cultures").is_dir():
        pytest.skip("model has no cultures/")

    code, payload = run_check(model, RULE)
    culture = (model / "definition" / "cultures" / "en-US.tmdl").read_bytes()
    if model_rel.startswith("universal"):
        # expected: pass
        assert code == 0
        assert violations(payload) == []
        return

    # check: fail, naming the orphan entity
    assert code == 1
    found = violations(payload)
    assert len(found) == 1
    assert "_Suppliers" in found[0]["message"]
    # check never writes
    assert (model / "definition" / "cultures" / "en-US.tmdl").read_bytes() == culture

    # fix, then the re-check is clean
    fix_code, _ = run_fix(model, RULE)
    assert fix_code == 0
    again, payload = run_check(model, RULE)
    assert again == 0, payload
    text = (model / "definition" / "cultures" / "en-US.tmdl").read_text(encoding="utf-8")
    assert "_Suppliers" not in text
    assert '"ConceptualEntity": "_Ads"' in text
    assert '"ConceptualEntity": "Ads Measures"' in text


def test_model_without_cultures_reports_nothing(stand_in):
    model = stand_in(FLEET) / MODELS[0]
    import shutil
    shutil.rmtree(model / "definition" / "cultures")
    code, payload = run_check(model, RULE)
    assert code == 0
    assert violations(payload) == []
