"""The live command's transport, credentials and local discovery: the
missing-credential message (PB170), the query body, the retry waits and the
token life (PB171), the local table and measure discovery (PB172).

Replay mode and stubs only: no network, no real data.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request

import pytest

from conftest import FIXTURES, run_cli

LIVE = FIXTURES / "live"
MODEL = LIVE / "models" / "coffee" / "Coffee.SemanticModel"
INDENTED = LIVE / "models" / "coffee-indented" / "Coffee.SemanticModel"
CREDENTIAL_VARS = ("PBI_TENANT_ID", "PBI_CLIENT_ID", "PBI_CLIENT_SECRET")
FABRIC_VARS = ("FABRIC_TENANT_ID", "FABRIC_CLIENT_ID", "FABRIC_CLIENT_SECRET",
               "FABRIC_WORKSPACE_ID", "FABRIC_MODEL_ID")


@pytest.fixture
def no_credentials(monkeypatch):
    for var in CREDENTIAL_VARS + FABRIC_VARS:
        monkeypatch.delenv(var, raising=False)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# PB170: the missing credentials are named
# ---------------------------------------------------------------------------

def test_missing_credentials_name_the_missing_variable(no_credentials, monkeypatch):
    monkeypatch.setenv("PBI_TENANT_ID", "tenant")
    monkeypatch.setenv("PBI_CLIENT_ID", "client")
    code, _out, err = run_cli("live", MODEL, "--workspace", "ws", "--dataset", "ds",
                              "--non-interactive")
    assert code == 2
    assert "Missing required environment variables: PBI_CLIENT_SECRET." in err


def test_missing_credentials_name_every_missing_variable(no_credentials, monkeypatch):
    monkeypatch.setenv("PBI_TENANT_ID", "tenant")
    code, _out, err = run_cli("live", MODEL, "--workspace", "ws", "--dataset", "ds",
                              "--non-interactive")
    assert code == 2
    assert "Missing required environment variables: PBI_CLIENT_ID, PBI_CLIENT_SECRET." in err


def test_the_fabric_names_are_accepted_as_fallbacks(no_credentials, monkeypatch):
    from tmdl_preflight import live

    monkeypatch.setenv("FABRIC_TENANT_ID", "tenant")
    monkeypatch.setenv("FABRIC_CLIENT_ID", "client")
    monkeypatch.setenv("FABRIC_CLIENT_SECRET", "secret")
    assert live.missing_credentials() == "Missing required environment variables: ."
    provider = live.token_provider(interactive=False)
    assert callable(provider)


def test_the_ids_fall_back_to_the_fabric_names(no_credentials, monkeypatch):
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "ws-from-env")
    monkeypatch.setenv("FABRIC_MODEL_ID", "ds-from-env")
    code, out, err = run_cli("live", MODEL, "--replay", LIVE / "refresh-completed",
                             "--checks", "live-refresh-status", "--json")
    assert code == 0, err
    assert json.loads(out)["checks"][0]["outcome"] == "pass"


def test_the_ids_are_still_required(no_credentials):
    code, _out, err = run_cli("live", MODEL, "--replay", LIVE / "refresh-completed")
    assert code == 2
    assert "--workspace" in err


# ---------------------------------------------------------------------------
# PB171: the transport
# ---------------------------------------------------------------------------

def test_execute_queries_sends_only_the_query(monkeypatch):
    from tmdl_preflight import live

    seen = {}

    class Client(live.RestClient):
        def _request(self, method, url, body=None):
            seen["method"], seen["url"], seen["body"] = method, url, body
            return {"results": [{"tables": [{"rows": [{"[Value]": 1}]}]}]}

    client = Client("ws", "ds", lambda: "token")
    result = client.execute("EVALUATE { 1 }")
    assert result.rows == [{"[Value]": 1}]
    assert seen["method"] == "POST"
    assert seen["body"] == {"queries": [{"query": "EVALUATE { 1 }"}]}


def test_a_failing_query_waits_twice(monkeypatch):
    from tmdl_preflight import live

    waits: list[float] = []
    monkeypatch.setattr(live.time, "sleep", lambda seconds: waits.append(seconds))

    class Client(live.RestClient):
        def _request(self, method, url, body=None):
            raise urllib.error.URLError("no route to host")

    client = Client("ws", "ds", lambda: "token")
    result = client.execute("EVALUATE { 1 }")
    assert result.error
    assert waits == [2, 2]


def test_a_token_without_expires_in_lasts_3599_seconds(no_credentials, monkeypatch):
    from tmdl_preflight import live

    monkeypatch.setenv("PBI_TENANT_ID", "tenant")
    monkeypatch.setenv("PBI_CLIENT_ID", "client")
    monkeypatch.setenv("PBI_CLIENT_SECRET", "secret")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: _Response(json.dumps({"access_token": "tok"}).encode()))
    provider = live.token_provider(interactive=False)
    assert provider() == "tok"
    assert 3590 < provider.remaining_seconds() <= 3599


def test_a_failed_sign_in_names_the_error(no_credentials, monkeypatch):
    from tmdl_preflight import live

    monkeypatch.setenv("PBI_TENANT_ID", "tenant")
    monkeypatch.setenv("PBI_CLIENT_ID", "client")
    monkeypatch.setenv("PBI_CLIENT_SECRET", "secret")
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *a, **k: _Response(json.dumps({"error_description": "bad secret"}).encode()))
    provider = live.token_provider(interactive=False)
    with pytest.raises(live.LiveError) as excinfo:
        provider()
    assert "Authentication failed: bad secret" in str(excinfo.value)


# ---------------------------------------------------------------------------
# PB172: the local discovery
# ---------------------------------------------------------------------------

def test_an_indented_column_is_a_column():
    from tmdl_preflight import live

    local = live.read_local_model(INDENTED)
    assert local.tables_with_columns == ["_Roasts"]
    assert local.measures == [("Coffee Measures", "!Roasts Sold")]
