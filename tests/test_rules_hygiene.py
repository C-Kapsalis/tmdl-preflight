"""Rules added in 1.2 for file hygiene: M013 attach mode, M016-M019, the
lineage keeper order, fix --dry-run / --clear-cache and unsafe fixers."""

from __future__ import annotations

from pathlib import Path

from conftest import run_check, run_cli, run_fix, violations
from tmdl_preflight.engine import fix
from tmdl_preflight.rules import default_ruleset
from tmdl_preflight.rules.base import Context, Rule, RuleSet, Severity

TAG_A = "0f0f0f0f-0000-4000-8000-00000000000a"


def _model(tmp_path: Path, tables: dict[str, str], model_extra: str = "",
           expressions: str | None = None) -> Path:
    definition = tmp_path / "Cafe.SemanticModel" / "definition"
    (definition / "tables").mkdir(parents=True)
    refs = "".join(f"ref table '{n}'\n" for n in tables)
    (definition / "model.tmdl").write_text(
        f"model Model\n\tculture: en-US\n\n{model_extra}{refs}", encoding="utf-8", newline="\n")
    (definition / "database.tmdl").write_text("database\n\tcompatibilityLevel: 1601\n",
                                              encoding="utf-8", newline="\n")
    for name, body in tables.items():
        (definition / "tables" / f"{name}.tmdl").write_text(body, encoding="utf-8", newline="\n")
    if expressions is not None:
        (definition / "expressions.tmdl").write_text(expressions, encoding="utf-8", newline="\n")
    return definition.parent


BEANS = (
    "table Beans\n\tlineageTag: 0f0f0f0f-0000-4000-8000-000000000001\n\n"
    "\t/// Kilograms sold\n\n\tmeasure Kg = SUM(Beans[kg])\n"
    "\t\tlineageTag: 0f0f0f0f-0000-4000-8000-000000000002\n\n"
    "\tcolumn kg\n\t\tdataType: double\n\t\tlineageTag: 0f0f0f0f-0000-4000-8000-000000000003\n"
    "\t\tsourceColumn: kg\n\n"
    "\tpartition Beans = m\n\t\tmode: import\n\t\tsource = #table({\"kg\"}, {{1}})\n"
)


class TestDescriptionAttachMode:
    def test_attach_keeps_the_description(self, tmp_path):
        model = _model(tmp_path, {"Beans": BEANS})
        code, payload = run_check(model, "M013")
        assert code == 1 and len(violations(payload, "M013")) == 1
        cfg = {"rules": {"M013": {"fix_mode": "attach"}}}
        code, payload = run_fix(model, "M013", config=cfg)
        text = (model / "definition" / "tables" / "Beans.tmdl").read_text(encoding="utf-8")
        assert "\t/// Kilograms sold\n\tmeasure Kg" in text
        assert code == 0 and violations(payload, "M013") == []
        assert payload["fixes"] == ["M013: Beans.tmdl: attached 1 description(s), removed 1 blank line(s)"]
        # idempotent
        code, payload = run_fix(model, "M013", config=cfg)
        assert payload["fixes"] == []

    def test_two_blank_lines_and_crlf(self, tmp_path):
        body = BEANS.replace("\t/// Kilograms sold\n\n", "\t/// Kilograms sold\n\n\n")
        model = _model(tmp_path, {"Beans": body})
        f = model / "definition" / "tables" / "Beans.tmdl"
        f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
        run_fix(model, "M013", config={"rules": {"M013": {"fix_mode": "attach"}}})
        raw = f.read_bytes()
        assert b"\t/// Kilograms sold\r\n\tmeasure Kg" in raw
        assert raw.count(b"\n") == raw.count(b"\r\n")


class TestSpaceIndentation:
    def test_space_indented_declaration(self, tmp_path):
        body = BEANS.replace("\tcolumn kg\n", "    column kg\n")
        model = _model(tmp_path, {"Beans": body})
        code, payload = run_check(model, "space-indentation")
        found = violations(payload, "M017")
        assert code == 1 and len(found) == 1 and found[0]["line"] == 9

    def test_a_fenced_body_is_flagged_too(self, tmp_path):
        """Every line that starts with four spaces is an error, expression
        bodies included."""
        body = BEANS.replace(
            "\tmeasure Kg = SUM(Beans[kg])\n",
            "\tmeasure Kg = ```\n    VAR x = SUM(Beans[kg])\n    RETURN x\n\t\t\t```\n",
        )
        model = _model(tmp_path, {"Beans": body})
        found = violations(run_check(model, "M017")[1], "M017")
        assert len(found) == 2, found
        assert all("Uses spaces instead of tabs" in f["message"] for f in found)
        lenient = run_check(model, "M017",
                            config={"rules": {"M017": {"strict": False}}})[1]
        assert violations(lenient, "M017") == []

    def test_tabs_then_spaces_and_three_spaces_are_clean(self, tmp_path):
        body = BEANS.replace("\t\tdataType: double\n", "\t\t    dataType: double\n").replace(
            "\t\tsourceColumn: kg\n", "   \t\tsourceColumn: kg\n")
        model = _model(tmp_path, {"Beans": body})
        assert violations(run_check(model, "M017")[1]) == []

    def test_a_bare_multiline_body_is_an_info_note(self, tmp_path):
        """The bare quoted multi-line measure note is always computed as a
        non-failing note."""
        body = BEANS.replace("\tmeasure Kg = SUM(Beans[kg])\n",
                             "\tmeasure 'Kg' =\n\t\t\tSUM(Beans[kg])\n")
        model = _model(tmp_path, {"Beans": body})
        found = violations(run_check(model, "M017")[1], "M017")
        assert len(found) == 1 and found[0]["severity"] == "info"
        assert "Multiline DAX should use triple backticks" in found[0]["message"]


class TestModelAnnotationDuplicates:
    def test_model_scope_duplicate(self, tmp_path):
        extra = "annotation Owner = a\n\nannotation Owner = b\n\n"
        model = _model(tmp_path, {"Beans": BEANS}, model_extra=extra)
        found = violations(run_check(model, "model-annotation-duplicates")[1], "M018")
        assert len(found) == 1 and "Owner" in found[0]["message"]

    def test_query_groups_are_separate_scopes(self, tmp_path):
        extra = ("queryGroup Roasting\n\tannotation PBI_QueryGroupOrder = 0\n\n"
                 "queryGroup Cafe\n\tannotation PBI_QueryGroupOrder = 1\n\n"
                 "annotation PBI_QueryGroupOrder = 5\n\n")
        model = _model(tmp_path, {"Beans": BEANS}, model_extra=extra)
        assert violations(run_check(model, "M018")[1]) == []

    def test_duplicate_inside_one_query_group_and_slash_names(self, tmp_path):
        extra = ("queryGroup Roasting\n\tannotation PBI_QueryGroupOrder = 0\n"
                 "\tannotation PBI_QueryGroupOrder = 1\n\n"
                 "annotation Region/Zone = x\nannotation Region/Zone = y\n\n")
        model = _model(tmp_path, {"Beans": BEANS}, model_extra=extra)
        assert len(violations(run_check(model, "M018")[1], "M018")) == 2


class TestUndefinedQueryGroup:
    def _with_group(self, tmp_path, groups, declared=""):
        body = BEANS
        for g in groups:
            body = body.replace("\t\tmode: import\n", f"\t\tmode: import\n\t\tqueryGroup: {g}\n", 1)
        return _model(tmp_path, {"Beans": body}, model_extra=declared)

    def test_declared_group_passes(self, tmp_path):
        model = self._with_group(tmp_path, ["Sales"], "queryGroup Sales\n\n")
        assert violations(run_check(model, "undefined-query-group")[1]) == []

    def test_missing_group_is_declared_by_the_fix(self, tmp_path):
        model = self._with_group(tmp_path, ["'Cafe Ops'"], "queryGroup Sales\n\tannotation PBI_QueryGroupOrder = 0\n\n")
        code, payload = run_check(model, "M019")
        assert code == 1 and "Cafe Ops" in violations(payload, "M019")[0]["message"]
        code, payload = run_fix(model, "M019")
        assert code == 0
        text = (model / "definition" / "model.tmdl").read_text(encoding="utf-8")
        assert "queryGroup 'Cafe Ops'\n\tannotation PBI_QueryGroupOrder = 99\n" in text
        assert text.index("queryGroup Sales") < text.index("queryGroup 'Cafe Ops'")
        assert run_fix(model, "M019")[1]["fixes"] == []

    def test_reference_in_expressions_and_sorted_numbering(self, tmp_path):
        exprs = 'expression Zed = "x"\n\tqueryGroup: Zeta\n\nexpression Al = "y"\n\tqueryGroup: Alpha\n'
        model = _model(tmp_path, {"Beans": BEANS}, expressions=exprs)
        assert len(violations(run_check(model, "M019")[1], "M019")) == 2
        run_fix(model, "M019")
        text = (model / "definition" / "model.tmdl").read_text(encoding="utf-8")
        assert "queryGroup Alpha\n\tannotation PBI_QueryGroupOrder = 99" in text
        assert "queryGroup Zeta\n\tannotation PBI_QueryGroupOrder = 100" in text
        assert text.index("queryGroup Alpha") < text.index("ref table")


class TestLineageKeeper:
    def test_table_keeps_its_tag_over_an_expression(self, tmp_path):
        body = BEANS.replace("0f0f0f0f-0000-4000-8000-000000000003", TAG_A)
        exprs = f'expression ServerName = "srv"\n\tlineageTag: {TAG_A}\n'
        model = _model(tmp_path, {"Beans": body}, expressions=exprs)
        found = violations(run_check(model, "M003")[1], "M003")
        assert len(found) == 1 and found[0]["path"].endswith("expressions.tmdl")
        assert found[0]["object"] == "expression ServerName"
        run_fix(model, "M003")
        assert TAG_A in (model / "definition" / "tables" / "Beans.tmdl").read_text(encoding="utf-8")
        assert TAG_A not in (model / "definition" / "expressions.tmdl").read_text(encoding="utf-8")

    def test_three_copies_in_one_file_keep_the_first(self, tmp_path):
        body = (BEANS.replace("0f0f0f0f-0000-4000-8000-000000000002", TAG_A)
                .replace("0f0f0f0f-0000-4000-8000-000000000003", TAG_A)
                .replace("0f0f0f0f-0000-4000-8000-000000000001", TAG_A))
        model = _model(tmp_path, {"Beans": body})
        assert len(violations(run_check(model, "M003")[1], "M003")) == 2
        run_fix(model, "M003")
        lines = (model / "definition" / "tables" / "Beans.tmdl").read_text(encoding="utf-8").splitlines()
        tags = [ln.split(":", 1)[1].strip() for ln in lines if "lineageTag:" in ln]
        assert tags[0] == TAG_A and len(set(tags)) == 3

    def test_tab_after_colon_is_rewritten(self, tmp_path):
        body = BEANS.replace("lineageTag: 0f0f0f0f-0000-4000-8000-000000000003", f"lineageTag:\t{TAG_A}")
        body = body.replace("0f0f0f0f-0000-4000-8000-000000000002", TAG_A)
        model = _model(tmp_path, {"Beans": body})
        code, payload = run_fix(model, "M003")
        assert code == 0 and len(payload["fixes"]) == 1
        assert "lineageTag:\t" in (model / "definition" / "tables" / "Beans.tmdl").read_text(encoding="utf-8")


class TestFixOptions:
    def _dup(self, tmp_path):
        body = BEANS.replace("0f0f0f0f-0000-4000-8000-000000000003", "0f0f0f0f-0000-4000-8000-000000000002")
        return _model(tmp_path, {"Beans": body})

    def test_dry_run_writes_nothing(self, tmp_path):
        model = self._dup(tmp_path)
        before = {p: p.read_bytes() for p in model.rglob("*") if p.is_file()}
        code, payload = run_fix(model, "M003", args=("--dry-run",))
        assert code == 1 and payload["would_fix"] == ["M003: 1 violation(s)"]
        assert {p: p.read_bytes() for p in model.rglob("*") if p.is_file()} == before

    def test_a_single_model_run_clears_the_cache(self, tmp_path):
        """On a single-model run the cache is what makes Desktop reuse the
        old tags, so it goes by default."""
        model = self._dup(tmp_path)
        cache = model / ".pbi" / "cache.abf"
        cache.parent.mkdir()
        cache.write_bytes(b"cache")
        code, out, err = run_cli("fix", model, "--select", "M003", "--no-config")
        assert not cache.exists(), "the cache was kept"
        assert "Deleted cache file" in out, out

    def test_keep_cache_opts_out(self, tmp_path):
        """`--keep-cache` keeps it."""
        model = self._dup(tmp_path)
        cache = model / ".pbi" / "cache.abf"
        cache.parent.mkdir()
        cache.write_bytes(b"cache")
        code, out, err = run_cli("fix", model, "--select", "M003",
                                 "--keep-cache", "--no-config")
        assert cache.exists(), "the cache was deleted"

    def test_a_multi_model_run_keeps_the_cache(self, tmp_path):
        """A whole-repository run never deletes a cache; it says it exists."""
        model = self._dup(tmp_path)
        cache = model / ".pbi" / "cache.abf"
        cache.parent.mkdir()
        cache.write_bytes(b"cache")
        model2 = self._dup(tmp_path / "second")
        cache2 = model2 / ".pbi" / "cache.abf"
        cache2.parent.mkdir()
        cache2.write_bytes(b"cache")
        code, out, err = run_cli("fix", tmp_path, "--select", "M003",
                                 "--no-config")
        assert cache.exists() and cache2.exists()
        assert "--clear-cache" in err, err

    def test_clear_cache_forces_the_deletion_on_a_multi_model_run(self, tmp_path):
        """`--clear-cache` forces it, whatever the run's scope."""
        model = self._dup(tmp_path)
        cache = model / ".pbi" / "cache.abf"
        cache.parent.mkdir()
        cache.write_bytes(b"cache")
        model2 = self._dup(tmp_path / "second")
        cache2 = model2 / ".pbi" / "cache.abf"
        cache2.parent.mkdir()
        cache2.write_bytes(b"cache")
        code, out, err = run_cli("fix", tmp_path, "--select", "M003",
                                 "--clear-cache", "--no-config")
        assert not cache.exists() and not cache2.exists()
        assert "Deleted cache file" in out, out


class _UnsafeRule(Rule):
    id = "Z999"
    name = "unsafe-demo"
    severity = Severity.ERROR
    fixable = True
    safe = False

    def check(self, ctx):
        flag = ctx.root / "flag.txt"
        return [] if flag.exists() else [self.violation("flag missing", file=ctx.root)]

    def fix(self, ctx):
        (ctx.root / "flag.txt").write_text("x", encoding="utf-8")
        return ["wrote flag"]


def test_unsafe_fixer_only_runs_when_selected(tmp_path):
    model = _model(tmp_path, {"Beans": BEANS})
    blanket = fix(Context(model), RuleSet([_UnsafeRule()]))
    assert blanket.skipped_fixers == ["Z999"] and not (model / "flag.txt").exists()
    chosen = fix(Context(model), RuleSet([_UnsafeRule()]), explicit={"unsafe-demo"})
    assert chosen.fixes_applied == ["Z999: wrote flag"] and chosen.violations == []


def test_new_rules_are_clean_on_the_fixture(clean_project):
    ruleset = default_ruleset().select({"m016", "m017", "m018", "m019"})
    from tmdl_preflight.engine import check
    assert check(Context(clean_project), ruleset).violations == []
