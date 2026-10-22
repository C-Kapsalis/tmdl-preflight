"""The opt-in ``live`` command (E-live-connection): credentials and the
local-model / live-dataset coupling guard.

Missing ids or credentials are a usage error before anything is queried, and
a dataset that does not match the local model stops the run.
"""

from __future__ import annotations

import json

import pytest

from conftest import FIXTURES, run_cli

LIVE = FIXTURES / "live"
MODEL = LIVE / "models" / "coffee" / "Coffee.SemanticModel"
CREDENTIAL_VARS = ("PBI_TENANT_ID", "PBI_CLIENT_ID", "PBI_CLIENT_SECRET")


@pytest.mark.parametrize("scenario, expected_exit", [
    # dataset 'Coffee' and local folder Coffee.SemanticModel: same model
    pytest.param("refresh-completed", 0, id="dataset-matches-model"),
    # dataset 'Bakery' (workspace 'Bakery Ovens'): fails before any check runs
    pytest.param("coupling-mismatch", 1, id="dataset-names-another-model"),
])
def test_coupling_guard(scenario, expected_exit):
    code, out, err = run_cli("live", MODEL, "--workspace", "ws-coffee", "--dataset", "ds-coffee",
                             "--replay", LIVE / scenario, "--checks", "live-refresh-status", "--json")
    assert code == expected_exit
    if expected_exit == 0:
        payload = json.loads(out)
        assert payload["dataset"]["name"] == "Coffee"
        assert [c["id"] for c in payload["checks"]] == ["live-refresh-status"]
    else:
        assert "Bakery" in (out + err)
        # opting out of the guard runs the checks
        code, out, _ = run_cli("live", MODEL, "--workspace", "ws-coffee", "--dataset", "ds-coffee",
                               "--replay", LIVE / scenario, "--checks", "live-refresh-status",
                               "--json", "--no-coupling-check")
        assert code == 0
        assert json.loads(out)["checks"][0]["outcome"] == "pass"


def test_live_requires_credentials(monkeypatch):
    """Without replay and without credentials nothing is queried: usage error."""
    # the subcommand exists (so exit 2 below is the credential check, not argparse)
    assert run_cli("live", "--help")[0] == 0
    for var in CREDENTIAL_VARS:
        monkeypatch.delenv(var, raising=False)
    code, out, err = run_cli("live", MODEL, "--workspace", "ws-coffee", "--dataset", "ds-coffee",
                             "--non-interactive")
    assert code == 2
    # missing ids are a usage error too
    code, _, _ = run_cli("live", MODEL, "--replay", LIVE / "refresh-completed")
    assert code == 2


def test_record_then_replay_round_trips(tmp_path):
    """--record writes the folder --replay reads: replaying a recording gives
    the same outcomes."""
    from tmdl_preflight.live import RecordingClient, ReplayClient

    rec = tmp_path / "rec"
    client = RecordingClient(ReplayClient(LIVE / "smoke-healthy"), rec)
    client.dataset()
    client.now()
    client.execute("EVALUATE   ROW(\"RowCount\",\n COUNTROWS('_Beans'))")
    client.refreshes(10)
    client.datasources()
    saved = json.loads((rec / "queries.json").read_text(encoding="utf-8"))
    assert saved[0]["query"] == "EVALUATE ROW(\"RowCount\", COUNTROWS('_Beans'))"
    first = run_cli("live", MODEL, "--workspace", "ws-coffee", "--dataset", "ds-coffee",
                    "--replay", LIVE / "smoke-healthy", "--checks", "live-smoke,live-freshness",
                    "--json", "--record", tmp_path / "rec2")
    second = run_cli("live", MODEL, "--workspace", "ws-coffee", "--dataset", "ds-coffee",
                     "--replay", tmp_path / "rec2", "--checks", "live-smoke,live-freshness", "--json")
    outcomes = [[c["outcome"] for c in json.loads(r[1])["checks"]] for r in (first, second)]
    assert outcomes[0] == outcomes[1] == ["pass", "pass"]


def test_unrecorded_query_is_an_error(tmp_path):
    code, out, _ = run_cli("live", MODEL, "--workspace", "ws-coffee", "--dataset", "ds-coffee",
                           "--replay", LIVE / "refresh-completed", "--checks", "live-calendar-rows",
                           "--json")
    result = json.loads(out)["checks"][0]
    assert code == 1 and result["outcome"] == "error" and "no recorded response" in result["message"]
