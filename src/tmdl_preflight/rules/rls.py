"""Row-level security in the model files (roles/ and the user-mapping
table). IDs L001-L006. Assignments of users to roles, and everything else
that lives in the Power BI Service, are out of reach of a file check."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..model import SemanticModel, Table
from .base import Context, Rule, Severity, Violation

_PERM_RE = re.compile(r"^\s*tablePermission\s+(?P<table>'(?:[^']|'')+'|[^\s=]+)\s*(?P<eq>=)?(?P<rest>.*)$")
_ROLE_RE = re.compile(r"^role\s+(?P<name>'(?:[^']|'')+'|.+?)\s*$")
_USERNAME_RE = re.compile(r"\bUSERNAME\s*\(", re.IGNORECASE)
_IN_VALUES_RE = re.compile(r"\bIN\s+VALUES\s*\(", re.IGNORECASE)
_CALCTABLE_RE = re.compile(r"\bCALCULATETABLE\s*\(", re.IGNORECASE)
_UPN_RE = re.compile(r"\bUSERPRINCIPALNAME\s*\(", re.IGNORECASE)


def _unquote(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == name[-1] == "'":
        return name[1:-1].replace("''", "'")
    return name


@dataclass
class TablePermission:
    table: str
    line: int  # 1-based
    filter: Optional[str]  # None: no '=' at all


@dataclass
class RoleFile:
    path: Path
    name: str
    read: bool
    permissions: list[TablePermission] = field(default_factory=list)


def read_role(path: Path) -> RoleFile:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    name = "?"
    for ln in lines:
        m = _ROLE_RE.match(ln)
        if m:
            name = _unquote(m.group("name"))
            break
    role = RoleFile(path, name, any(ln.strip() == "modelPermission: read" for ln in lines))
    for idx, ln in enumerate(lines):
        m = _PERM_RE.match(ln)
        if not m:
            continue
        flt: Optional[str] = None
        if m.group("eq"):
            rest = m.group("rest").lstrip()
            if rest.startswith("```"):
                body = rest[3:] + "\n" + "\n".join(lines[idx + 1:])
                end = body.find("```")
                flt = body[:end].strip() if end >= 0 else ""
            else:
                flt = rest.strip()
        role.permissions.append(TablePermission(_unquote(m.group("table")), idx + 1, flt))
    return role


def role_files(model: SemanticModel) -> list[RoleFile]:
    folder = model.definition_path / "roles"
    if not folder.is_dir():
        return []
    return [read_role(p) for p in sorted(folder.glob("*.tmdl"))]


def mapping_tables(model: SemanticModel) -> list[Table]:
    """Tables that map users to data: a column named UserPrincipalName."""
    out = []
    for t in model.table_list:
        try:
            text = t.file.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        if any(ln.strip() == "column UserPrincipalName" for ln in text.splitlines()):
            out.append(t)
    return out


class RoleGrammarRule(Rule):
    id = "L001"
    name = "rls-role-grammar"
    severity = Severity.ERROR
    description = (
        "Every role needs 'modelPermission: read', and every tablePermission "
        "needs a filter expression ('tablePermission T = <DAX>'). A bare "
        "tablePermission is not a valid row filter; delete the line to grant "
        "the role full access to the table instead."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for role in role_files(model):
                if not role.read:
                    out.append(self.violation(
                        f"role {role.name} has no 'modelPermission: read'; add it.",
                        file=role.path, obj=role.name))
                for p in role.permissions:
                    if p.filter is None:
                        out.append(self.violation(
                            f"role {role.name}: tablePermission {p.table} has no filter "
                            f"expression; write '= <DAX filter>' or delete the line.",
                            file=role.path, line=p.line, obj=f"{role.name}:{p.table}"))
        return out


class UsernameFunctionRule(Rule):
    id = "L002"
    name = "rls-username-function"
    severity = Severity.ERROR
    description = (
        "Row filters must identify the user with USERPRINCIPALNAME(). "
        "USERNAME() returns DOMAIN\\user in Desktop and the UPN in the "
        "Service, so a filter written against one silently matches nothing "
        "in the other."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for role in role_files(model):
                for p in role.permissions:
                    if p.filter and _USERNAME_RE.search(p.filter):
                        out.append(self.violation(
                            f"role {role.name}: the filter on {p.table} calls USERNAME(); use "
                            f"USERPRINCIPALNAME().",
                            file=role.path, line=p.line, obj=f"{role.name}:{p.table}"))
        return out


class InValuesBypassRule(Rule):
    id = "L003"
    name = "rls-in-values-bypass"
    severity = Severity.ERROR
    description = (
        "A row filter of the form '[col] IN VALUES(Mapping[col])' reads the "
        "mapping table without restricting it to the signed-in user, so "
        "every user sees every mapped value. Restrict it: CALCULATETABLE("
        "VALUES(Mapping[col]), Mapping[UserPrincipalName] = "
        "USERPRINCIPALNAME())."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for role in role_files(model):
                for p in role.permissions:
                    f = p.filter or ""
                    if not _IN_VALUES_RE.search(f):
                        continue
                    if _CALCTABLE_RE.search(f) and _UPN_RE.search(f):
                        continue
                    out.append(self.violation(
                        f"role {role.name}: the filter on {p.table} uses IN VALUES(...) without "
                        f"CALCULATETABLE(..., [UserPrincipalName] = USERPRINCIPALNAME()), so it "
                        f"does not restrict rows to the signed-in user.",
                        file=role.path, line=p.line, obj=f"{role.name}:{p.table}"))
        return out


class MappingTableHiddenRule(Rule):
    id = "L004"
    name = "rls-mapping-table-hidden"
    severity = Severity.ERROR
    description = (
        "The user-mapping table (a table with a UserPrincipalName column) "
        "lists who may see what; left visible, report users can browse "
        "every user's e-mail and assignment. Hide the table."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            for t in mapping_tables(model):
                if not t.is_hidden:
                    out.append(self.violation(
                        f"user-mapping table {t.name} is visible; add isHidden to the table.",
                        file=t.file, line=t.line, obj=t.name))
        return out


class MappingTableNoRelationshipRule(Rule):
    id = "L005"
    name = "rls-mapping-table-no-relationship"
    severity = Severity.ERROR
    description = (
        "The user-mapping table should be read only by the role filter "
        "(CALCULATETABLE ... USERPRINCIPALNAME()). A relationship to it "
        "makes report filters flow into the mapping and back, and RLS on a "
        "related table can block or widen access unexpectedly. Delete the "
        "relationship."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            names = {t.name for t in mapping_tables(model)}
            if not names:
                continue
            for r in model.relationships:
                hit = names & {r.from_table, r.to_table}
                for name in sorted(hit):
                    out.append(self.violation(
                        f"a relationship ({r.from_table}.{r.from_column} -> {r.to_table}."
                        f"{r.to_column}) touches the user-mapping table {name}; delete it and "
                        f"read the mapping only in the role filter.",
                        file=model.definition_path / "relationships.tmdl", obj=name))
        return out


class RlsInventoryRule(Rule):
    id = "L006"
    name = "rls-inventory"
    severity = Severity.INFO
    opt_in = True
    description = (
        "Inventory (never fails): the roles, their model permission and "
        "table filters, the user-mapping tables, and the resulting posture "
        "(no RLS, static, dynamic via a mapping table, or incomplete)."
    )

    def check(self, ctx: Context) -> list[Violation]:
        out: list[Violation] = []
        for model in ctx.models:
            roles = role_files(model)
            maps = [t.name for t in mapping_tables(model)]
            where = model.definition_path / "roles"
            if not roles:
                out.append(self.violation("roles/ absent: the model defines no roles.",
                                          file=model.definition_path, obj="roles"))
            for role in roles:
                perms = ", ".join(f"{p.table}{' (no filter)' if p.filter is None else ''}"
                                  for p in role.permissions) or "none (full access)"
                out.append(self.violation(
                    f"role {role.name}: modelPermission {'read' if role.read else 'MISSING'}; "
                    f"table permissions: {perms}",
                    file=role.path, obj=role.name))
            if maps:
                out.append(self.violation(f"user-mapping tables: {', '.join(maps)}",
                                          file=where, obj="mapping"))
            if not roles and not maps:
                posture = "no RLS"
            elif roles and not maps:
                posture = "static (roles without a user-mapping table)"
            elif roles:
                posture = f"dynamic via mapping table {', '.join(maps)}"
            else:
                posture = "incomplete (a user-mapping table but no roles)"
            out.append(self.violation(f"RLS posture: {posture}", file=where, obj="posture"))
        return out
