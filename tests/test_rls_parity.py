"""Row-level security: the wording of the findings and the inventory.

The message a rule prints is part of the contract: a team reads the
message, not the rule id.

Stand-ins (tests/fixtures/rls_standins):
- ``rls_no_model_permission``: a role without ``modelPermission: read``.
- ``rls_no_filter``: a role with a bare ``tablePermission``.
- ``rls_username``: a filter that calls ``USERNAME()``.
- ``rls_in_values_bare``: a filter that reads a mapping table with
  ``IN VALUES(...)`` and nothing else.
- ``rls_mapping_unhidden``: a user-mapping table that is not hidden.
- ``rls_mapping_related``: a user-mapping table that is a relationship
  endpoint; ``rls_mapping_related_twice`` has two such relationships.
- ``rls_bare_then_filter``: a bare permission followed by one with a
  filter.
- ``rls_two_roles``: two roles and a user-mapping table.
"""
from __future__ import annotations

from conftest import run_check, violations

FIX = "rls_standins"


def _model(stand_in, sid):
    return stand_in(FIX) / sid / "Model.SemanticModel"


def _messages(payload, rule=None):
    return [v["message"] for v in violations(payload, rule)]


def test_a_role_without_the_model_permission_says_which_file(stand_in):
    code, payload = run_check(_model(stand_in, "rls_no_model_permission"),
                              "rls-role-grammar")
    assert _messages(payload) == ["Store Managers.tmdl: missing `modelPermission: read`"]


def test_a_bare_table_permission_says_what_to_write(stand_in):
    code, payload = run_check(_model(stand_in, "rls_no_filter"), "rls-role-grammar")
    assert _messages(payload) == [
        "Store Managers.tmdl: `tablePermission _Stores` has no `= <DAX>` (every "
        "tablePermission line needs a filter expression; if the role should grant full "
        "access on this table, omit the line entirely — see FullAccess pattern)"]


def test_the_model_permission_may_be_written_without_a_space(stand_in):
    model = _model(stand_in, "rls_static")
    role = model / "definition" / "roles" / "Store Managers.tmdl"
    role.write_text(role.read_text(encoding="utf-8").replace(
        "modelPermission: read", "modelPermission:read"), encoding="utf-8")
    code, payload = run_check(model, "rls-role-grammar")
    assert violations(payload) == []


def test_the_username_finding_names_the_file_and_the_table(stand_in):
    code, payload = run_check(_model(stand_in, "rls_username"), "rls-username-function")
    assert _messages(payload) == [
        "Self.tmdl: `_Stores` filter uses USERNAME() — replace with USERPRINCIPALNAME()"]


def test_the_in_values_finding_names_the_fix(stand_in):
    code, payload = run_check(_model(stand_in, "rls_in_values_bare"),
                              "rls-in-values-bypass")
    assert _messages(payload) == [
        "Regional.tmdl: `_Stores` filter uses `IN VALUES(...)` without wrapping in "
        "`CALCULATETABLE(VALUES(MappingTable[col]), MappingTable[UserPrincipalName] = "
        "USERPRINCIPALNAME())` — this is the silent-bypass trap (every user sees every "
        "row, no error raised)"]


def test_the_mapping_table_finding_names_the_file(stand_in):
    code, payload = run_check(_model(stand_in, "rls_mapping_unhidden"),
                              "rls-mapping-table-hidden")
    assert _messages(payload) == [
        "User Access.tmdl: mapping table `User Access` (has UserPrincipalName column) "
        "is not `isHidden`"]


def test_the_relationship_finding_names_the_mapping_table(stand_in):
    code, payload = run_check(_model(stand_in, "rls_mapping_related"),
                              "rls-mapping-table-no-relationship")
    assert _messages(payload) == [
        "mapping table `User Access` is referenced in relationships.tmdl as a from/to "
        "endpoint (must be standalone — the CALCULATETABLE pattern handles the user "
        "lookup at query time)"]


def test_two_relationships_to_the_mapping_table_are_one_finding(stand_in):
    code, payload = run_check(_model(stand_in, "rls_mapping_related_twice"),
                              "rls-mapping-table-no-relationship")
    assert len(violations(payload)) == 1


def test_a_permission_after_a_bare_one_is_still_examined(stand_in):
    """The bare line is reported, and the filter that follows it too."""
    model = _model(stand_in, "rls_bare_then_filter")
    code, payload = run_check(model, "rls-role-grammar", "rls-username-function")
    assert _messages(payload, "L001") == [
        "Regional.tmdl: `tablePermission _Stores` has no `= <DAX>` (every tablePermission "
        "line needs a filter expression; if the role should grant full access on this "
        "table, omit the line entirely — see FullAccess pattern)"]
    assert _messages(payload, "L002") == [
        "Regional.tmdl: `Sales` filter uses USERNAME() — replace with USERPRINCIPALNAME()"]


def test_the_inventory_says_what_the_roles_may_read(stand_in):
    code, payload = run_check(_model(stand_in, "rls_two_roles"), "rls-inventory")
    assert code == 0
    inventory = _messages(payload)[0]
    assert inventory.split("\n") == [
        "RLS inventory for Model.SemanticModel:",
        "  roles/ directory:    present",
        "  role files:          2",
        "    - Full Access.tmdl: role `Full Access`, modelPermission: read, tables: "
        "(no tablePermission lines — full-access pattern)",
        "    - Regional.tmdl: role `Regional`, modelPermission: read, tables: _Stores",
        "  mapping tables:      1 ['User Access']",
    ]


def test_the_posture_says_which_pattern_the_model_uses(stand_in):
    code, payload = run_check(_model(stand_in, "rls_two_roles"), "rls-inventory")
    posture = _messages(payload)[1]
    assert posture.split("\n") == [
        "RLS posture for Model.SemanticModel: dynamic via mapping table",
        "  Service-side concerns NOT validated here:",
        "    - User-to-role assignment lives on the Power BI Service Security page",
        "    - Roles are additive (union, not intersection) — verify no user is in",
        "      both a restricted and a full-access role",
        "    - Workspace contributors bypass RLS — test with a Viewer account",
    ]


def test_a_model_without_roles_says_so(stand_in):
    code, payload = run_check(_model(stand_in, "rls_none"), "rls-inventory")
    inventory = _messages(payload)[0]
    assert "  roles/ directory:    absent (no RLS in use)" in inventory
    assert "  role files:          0" in inventory
    assert "RLS posture for Model.SemanticModel: no RLS" in _messages(payload)[1]
