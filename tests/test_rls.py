"""Row-level security validation (local files only).

What is NOT tested, by design: user-to-role assignment, the additive-roles trap,
workspace contributors bypassing RLS and service-side "Test as role" output all
live in the Power BI Service, not in the model files.

Rules (new, selected by name):
  rls-role-grammar, rls-username-function, rls-in-values-bypass,
  rls-mapping-table-hidden, rls-mapping-table-no-relationship (errors),
  rls-inventory (info report: inventory + posture, always exit 0).
When the model has no roles/ (or no mapping table for the relationship
check) the tests assert the rule reports nothing and then skip. Stand-ins: ``tests/fixtures/rls_standins/<id>``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import run_check, violations

pytestmark = [pytest.mark.p0]

FIX = "rls_standins"
ALL = [
    "rls_calculatetable_no_upn", "rls_dynamic", "rls_full_access", "rls_in_values_bare",
    "rls_mapping_only", "rls_mapping_related", "rls_mapping_unhidden",
    "rls_no_filter", "rls_no_model_permission", "rls_none", "rls_static", "rls_upn",
    "rls_username", "rls_username_lower",
]
NO_ROLES = {"rls_none", "rls_mapping_only"}
NO_MAPPING = {"rls_full_access", "rls_in_values_bare", "rls_no_filter",
              "rls_no_model_permission", "rls_none", "rls_static", "rls_upn",
              "rls_username", "rls_username_lower"}


def _model(stand_in, sid) -> Path:
    return stand_in(FIX) / sid / "Model.SemanticModel"


def _cases(fails, skips):
    return [(s, "skip" if s in skips else "fail" if s in fails else "pass") for s in ALL]


def _assert_verdict(model, rule, verdict, *expect_in_message):
    code, payload = run_check(model, rule)
    found = violations(payload)
    if verdict == "fail":
        assert found and code == 1
        msgs = " ".join(v["message"] for v in found)
        for text in expect_in_message:
            assert text in msgs
        assert all(v["severity"] == "error" for v in found)
        return found
    assert found == [], "\n  " + "\n  ".join(v["message"] for v in found)
    if verdict == "skip":
        pytest.skip(f"{rule}: precondition absent in this model ")
    return found


@pytest.mark.parametrize("sid, verdict", _cases({"rls_no_filter", "rls_no_model_permission"}, NO_ROLES))
def test_role_grammar(stand_in, sid, verdict):
    msg = {"rls_no_filter": ("_Stores",), "rls_no_model_permission": ("modelPermission",)}
    _assert_verdict(_model(stand_in, sid), "rls-role-grammar", verdict, *msg.get(sid, ()))


@pytest.mark.parametrize("sid, verdict", _cases({"rls_username", "rls_username_lower"}, NO_ROLES))
def test_no_username_function(stand_in, sid, verdict):
    _assert_verdict(_model(stand_in, sid), "rls-username-function", verdict, "USERPRINCIPALNAME")


@pytest.mark.parametrize("sid, verdict", _cases({"rls_in_values_bare", "rls_calculatetable_no_upn"}, NO_ROLES))
def test_in_values_must_be_wrapped_in_calculatetable_with_upn_filter(stand_in, sid, verdict):
    _assert_verdict(_model(stand_in, sid), "rls-in-values-bypass", verdict, "CALCULATETABLE")


POSTURE = {
    "rls_none": "no RLS",
    "rls_static": "static",
    "rls_dynamic": "dynamic",
    "rls_mapping_only": "incomplete",
}


@pytest.mark.parametrize("sid", ALL)
def test_rls_inventory(stand_in, sid):
    code, payload = run_check(_model(stand_in, sid), "rls-inventory")
    found = violations(payload)
    assert code == 0
    assert all(v["severity"] == "info" for v in found)
    msgs = " ".join(v["message"] for v in found)
    if sid in NO_ROLES:
        assert "absent" in msgs or "no RLS" in msgs
    else:
        assert "modelPermission" in msgs
    if sid == "rls_no_model_permission":
        assert "MISSING" in msgs
    if sid == "rls_no_filter":
        assert "(no filter)" in msgs
    if sid not in NO_MAPPING:
        assert "User Access" in msgs


@pytest.mark.parametrize("sid", ALL)
def test_rls_posture_summary(stand_in, sid):
    code, payload = run_check(_model(stand_in, sid), "rls-inventory")
    assert code == 0
    msgs = " ".join(v["message"] for v in violations(payload))
    if sid in POSTURE:
        assert POSTURE[sid] in msgs


@pytest.mark.parametrize("sid, verdict", _cases({"rls_mapping_unhidden"}, set()))
def test_mapping_table_is_hidden(stand_in, sid, verdict):
    _assert_verdict(_model(stand_in, sid), "rls-mapping-table-hidden", verdict, "User Access")


@pytest.mark.parametrize("sid, verdict", _cases({"rls_mapping_related"}, NO_MAPPING))
def test_mapping_table_has_no_relationship(stand_in, sid, verdict):
    _assert_verdict(_model(stand_in, sid), "rls-mapping-table-no-relationship", verdict, "User Access")
