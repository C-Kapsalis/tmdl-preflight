"""The manifest's target contract: the targets file it reads, the failures it
refuses to write through, and the lines it prints.

The manifest is the hand-off between the model and the pipelines next to it,
so a target that does not match must fail loudly and write nothing.
"""
from __future__ import annotations

import json

from conftest import run_cli

FIXTURE = "manifest_target"
MODEL = "Warehouse.SemanticModel"
MODEL_REL = "manifest_target/Warehouse.SemanticModel"


def _model(stand_in):
    return stand_in(FIXTURE) / MODEL


def _manifest(model):
    return model / "generated" / "warehouse-manifest.json"


def _targets(tmp_path, text, name="targets.yml"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The targets file (registry shape)
# ---------------------------------------------------------------------------

def test_the_registry_shape_matches_by_primary_path(stand_in, tmp_path):
    model = _model(stand_in)
    targets = _targets(tmp_path,
                       "clients:\n"
                       "  spinout-05:\n"
                       "    client_id: spinout-05\n"
                       f"    model_path: {MODEL_REL}\n"
                       "    bq_project: example-project-2\n"
                       "    bq_billing_project: example-project-2\n"
                       "    bq_dataset: warehouse_db\n")
    code, _out, err = run_cli("manifest", model, "--targets", targets, "--no-config")
    assert code == 0, err
    block = json.loads(_manifest(model).read_text(encoding="utf-8"))["bigquery"]
    assert block["client_id"] == "spinout-05"
    assert block["registry_project"] == "example-project-2"
    assert block["registry_dataset"] == "warehouse_db"
    assert block["billing_project"] == "example-project-2"


def test_the_registry_shape_matches_by_secondary_path(stand_in, tmp_path):
    model = _model(stand_in)
    targets = _targets(tmp_path,
                       "clients:\n"
                       "  spinout-06:\n"
                       "    client_id: spinout-06\n"
                       "    model_path: other/Primary.SemanticModel\n"
                       "    bq_project: example-project-2\n"
                       "    secondary_models:\n"
                       f"      - path: {MODEL_REL}\n"
                       "        bq_dataset: warehouse_db\n")
    code, _out, err = run_cli("manifest", model, "--targets", targets, "--no-config")
    assert code == 0, err
    block = json.loads(_manifest(model).read_text(encoding="utf-8"))["bigquery"]
    assert block["client_id"] == "spinout-06"
    assert block["registry_project"] == "example-project-2"
    assert block["registry_dataset"] == "warehouse_db"


def test_a_secondary_row_overrides_and_a_null_removes_a_target():
    from tmdl_preflight.manifest import entry_for_model, target_fields

    entry = {
        "client_id": "spinout-06",
        "model_path": "other/Primary.SemanticModel",
        "bq_project": "example-project-1",
        "bq_dataset": "other_db",
        "secondary_models": [
            {"path": "other/Secondary.SemanticModel", "bq_project": "example-project-3",
             "bq_dataset": None},
        ],
    }
    secondary = entry_for_model(entry, "other/Secondary.SemanticModel")
    fields = target_fields(secondary)
    assert fields["project"] == "example-project-3"
    assert fields["dataset"] is None
    # the billing project is the declared one when the key is there, else the project
    assert target_fields({"bq_project": "p", "bq_billing_project": None})["billing_project"] is None
    assert target_fields({"bq_project": "p"})["billing_project"] == "p"


# ---------------------------------------------------------------------------
# The unregistered model
# ---------------------------------------------------------------------------

def test_an_unregistered_model_warns_with_the_agreed_words(stand_in, tmp_path):
    model = _model(stand_in)
    targets = _targets(tmp_path, "clients:\n  other:\n    model_path: x/Y.SemanticModel\n")
    code, out, err = run_cli("manifest", model, "--targets", targets, "--no-config")
    assert code == 0
    assert err == (f"WARNING: '{model.as_posix()}' is not in targets.yml — no client_id; "
                   f"warehouse derived from the model's v-BQ_project only.\n")


# ---------------------------------------------------------------------------
# The target-contract failures
# ---------------------------------------------------------------------------

def test_a_model_without_a_declared_target_refuses_to_guess(stand_in, tmp_path):
    model = _model(stand_in)
    expr = model / "definition" / "expressions.tmdl"
    expr.write_text(expr.read_text(encoding="utf-8").replace(
        'expression v-BQ_project = "example-project-2"', 'expression other = "x"'), "utf-8")
    code, _out, err = run_cli("manifest", model, "--no-config")
    assert code == 1
    assert err == (f"{model.as_posix()}: could not resolve v-BQ_project/v-db from "
                   f"expressions.tmdl for a model that reads BigQuery — refusing to guess "
                   f"a target.\n")
    assert not _manifest(model).exists()


def test_a_project_mismatch_refuses_the_registry_target(stand_in, tmp_path):
    model = _model(stand_in)
    targets = _targets(tmp_path,
                       "clients:\n"
                       "  spinout-05:\n"
                       f"    model_path: {MODEL_REL}\n"
                       "    bq_project: example-project-9\n")
    code, _out, err = run_cli("manifest", model, "--targets", targets, "--no-config")
    assert code == 1
    assert err == (f"{model.as_posix()}: v-BQ_project is 'example-project-2' but targets.yml "
                   f"expects 'example-project-9' for spinout-05 — the model and registry "
                   f"warehouse targets must match. Refusing to query the registry target "
                   f"because that would hide what Power BI actually reads.\n")
    assert not _manifest(model).exists()


def test_a_dataset_mismatch_refuses_the_registry_dataset(stand_in, tmp_path):
    model = _model(stand_in)
    targets = _targets(tmp_path,
                       "clients:\n"
                       "  spinout-05:\n"
                       f"    model_path: {MODEL_REL}\n"
                       "    bq_project: example-project-2\n"
                       "    bq_dataset: other_db\n")
    code, _out, err = run_cli("manifest", model, "--targets", targets, "--no-config")
    assert code == 1
    assert err == (f"{model.as_posix()}: v-db is 'warehouse_db' but targets.yml declares "
                   f"bq_dataset 'other_db' for spinout-05 — the model and registry dataset "
                   f"targets must match.\n")
    assert not _manifest(model).exists()


def test_the_dataset_convention_is_an_optional_setting(stand_in, tmp_path):
    model = _model(stand_in)
    targets = _targets(tmp_path,
                       "clients:\n"
                       "  spinout-05:\n"
                       f"    model_path: {MODEL_REL}\n"
                       "    bq_project: example-project-2\n")
    config = tmp_path / "preflight.json"
    config.write_text(json.dumps({"manifest": {"target": {
        "targets_name": "targets.yml",
        "dataset_template": "{key}_db"}}}), encoding="utf-8")
    code, _out, err = run_cli("manifest", model, "--targets", targets, "--config", config)
    assert code == 1
    assert err == (f"{model.as_posix()}: v-db is 'warehouse_db' but client spinout-05 implies "
                   f"'spinout_05_db' — this model reads another org's dataset. If intentional, "
                   f"declare bq_dataset: in the registry entry.\n")
    # without the setting the convention is not checked
    assert run_cli("manifest", model, "--targets", targets, "--no-config")[0] == 0


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

def test_an_unknown_model_says_what_it_is_not(stand_in, tmp_path):
    code, _out, err = run_cli("manifest", "nope", "--no-config")
    assert code == 2
    assert "MODEL 'nope' is neither a registry client_id nor a <path>/definition model " \
           "directory under " in err


def test_a_registry_entry_without_a_model_path_says_so(stand_in, tmp_path):
    targets = _targets(tmp_path, "clients:\n  spinout-05:\n    bq_project: example-project-2\n")
    code, _out, err = run_cli("manifest", "spinout-05", "--targets", targets, "--no-config")
    assert code == 2
    assert "registry entry 'spinout-05' declares no model_path" in err


def test_a_registry_model_path_without_a_definition_says_so(stand_in, tmp_path):
    targets = _targets(tmp_path, "clients:\n  spinout-05:\n    model_path: gone/M.SemanticModel\n")
    code, _out, err = run_cli("manifest", "spinout-05", "--targets", targets, "--no-config")
    assert code == 2
    assert "model path '" in err and "has no definition/ directory under " in err


# ---------------------------------------------------------------------------
# The console and the check
# ---------------------------------------------------------------------------

def test_manifest_prints_the_summary_the_pipelines_read(stand_in, tmp_path):
    model = _model(stand_in)
    config = tmp_path / "preflight.json"
    config.write_text(json.dumps({"manifest": {"target": {
        "default_project": "example-project-2"}}}), encoding="utf-8")
    code, out, err = run_cli("manifest", model, "--config", config)
    assert code == 0, err
    lines = out.splitlines()
    assert lines[0] == f"Wrote {_manifest(model)}"
    assert lines[1] == (f"  model: Warehouse ({model.as_posix()}) -> "
                        f"example-project-2.warehouse_db [internal]")
    assert lines[2] == "  5 tables, 1 relationships"
    assert lines[3] == "  by classification: {'fact': 3, 'calendar': 1, 'selector': 1}"
    assert lines[4] == "  domains: Advertising, Core / Shared, GA4, Other"


def test_the_check_says_what_to_run_and_ignores_line_endings(stand_in, tmp_path):
    model = _model(stand_in)
    run_cli("manifest", model, "--no-config")
    code, out, err = run_cli("manifest", model, "--check", "--no-config")
    assert code == 0 and out == f"OK: {_manifest(model)} is up to date.\n" and err == ""

    # a copy with Windows line endings is not stale
    _manifest(model).write_bytes(_manifest(model).read_bytes().replace(b"\n", b"\r\n"))
    code, out, err = run_cli("manifest", model, "--check", "--no-config")
    assert code == 0 and "is up to date" in out

    _manifest(model).write_bytes(_manifest(model).read_bytes() + b" ")
    code, _out, err = run_cli("manifest", model, "--check", "--no-config")
    assert code == 1
    assert err == (f"DRIFT: {_manifest(model)} is stale. Run: tmdl-preflight manifest "
                   f"{model}\n")

    _manifest(model).unlink()
    code, _out, err = run_cli("manifest", model, "--check", "--no-config")
    assert code == 1
    assert err == (f"MISSING: {_manifest(model)} was never generated. Run: tmdl-preflight "
                   f"manifest {model}\n")


def test_the_written_manifest_uses_unix_line_endings(stand_in, tmp_path):
    model = _model(stand_in)
    run_cli("manifest", model, "--no-config")
    raw = _manifest(model).read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n")
