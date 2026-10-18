"""
NAMEOF Resolver

Tests for NAMEOF() reference validation. The resolver must:
1. Find NAMEOF references in DAX expressions
2. Validate they point to existing objects
3. Report broken references clearly

Ported: the registry model is replaced by the stand-in
`tests/fixtures/test_dax_parsable_bikeshop` (`__Calendar` with `Date` and `Year`,
measures using NAMEOF, a field parameter `x-Selector 1`). The kernel resolver is
replaced by the tool's NAMEOF API `tmdl_preflight.nameof.NameofResolver`
(extraction records carry table_name, object_name, full_reference,
source_measure, source_table, is_measure_ref, line_context; spec
E-nameof-resolution), model-level validation by rule D002
(`check --select D002`), and statistics / text report by
`tmdl-preflight report nameof` (spec E-report-nameof).
The template count floor (test_find_all_nameof_references) belongs to
E-template-count-floor; the registry plumbing test
(test_client_id_for_resolves_secondary_models) is not ported.
"""

from __future__ import annotations

import json

import pytest

from conftest import run_check, run_cli, violations
from tmdl_preflight.parser import parse_model

FIXTURE = "test_dax_parsable_bikeshop"


@pytest.fixture
def model_dir(stand_in):
    root = stand_in(FIXTURE)
    (root / "variants.json").unlink()
    return root / "BikeShop.SemanticModel"


@pytest.fixture
def model(model_dir):
    return parse_model(model_dir / "definition")


def _api():
    # imported lazily so the file collects before the API ships
    from tmdl_preflight import nameof
    return nameof


def NameofResolver(model):  # noqa: N802 - mirrors the API class name
    return _api().NameofResolver(model)


def NameofReference(**fields):  # noqa: N802
    return _api().NameofReference(**fields)


def _severity(b) -> str:
    return str(getattr(b.severity, "value", b.severity)).upper()


def test_nameof_resolver_initialization(model):
    """The resolver can be created and keeps the model it was given."""
    resolver = NameofResolver(model)

    assert resolver is not None
    assert resolver.model is model


def test_nameof_reference_structure(model):
    """NameofReference records have the documented structure."""
    resolver = NameofResolver(model)

    refs = resolver.find_all_nameof_references()
    assert len(refs) > 0

    ref = refs[0]
    assert hasattr(ref, 'table_name')
    assert hasattr(ref, 'object_name')
    assert hasattr(ref, 'full_reference')
    assert hasattr(ref, 'source_measure')
    assert hasattr(ref, 'source_table')
    assert hasattr(ref, 'is_measure_ref')
    assert hasattr(ref, 'line_context')


def test_validate_references_no_broken(model, model_dir):
    """The model has no broken NAMEOF references (ERROR severity; warnings allowed)."""
    resolver = NameofResolver(model)
    refs = resolver.find_all_nameof_references()
    broken = resolver.validate_references(refs)
    error_count = len([b for b in broken if _severity(b) == "ERROR"])
    assert error_count == 0, f"Found {error_count} broken NAMEOF references"

    code, payload = run_check(model_dir, "D002")
    assert [v for v in violations(payload, "D002") if v["severity"] == "error"] == []


def test_nameof_column_reference_pattern(model):
    """NAMEOF('Table'[Column])"""
    resolver = NameofResolver(model)

    test_expr = "NAMEOF('__Calendar'[Date])"
    refs = resolver.find_nameof_in_expression(test_expr, "TestMeasure", "TestTable")

    assert len(refs) == 1
    ref = refs[0]
    assert ref.table_name == "__Calendar"
    assert ref.object_name == "Date"
    assert ref.is_measure_ref == False  # noqa: E712


def test_nameof_measure_reference_pattern(model):
    """NAMEOF([Measure])"""
    resolver = NameofResolver(model)

    test_expr = "NAMEOF([TestMeasure])"
    refs = resolver.find_nameof_in_expression(test_expr, "TestMeasure", "TestTable")

    assert len(refs) == 1
    ref = refs[0]
    assert ref.table_name is None
    assert ref.object_name == "TestMeasure"
    assert ref.is_measure_ref == True  # noqa: E712


def test_nameof_without_quotes(model):
    """NAMEOF(Table[Column]) without quotes"""
    resolver = NameofResolver(model)

    test_expr = "NAMEOF(__Calendar[Date])"
    refs = resolver.find_nameof_in_expression(test_expr, "TestMeasure", "TestTable")

    assert len(refs) == 1
    ref = refs[0]
    assert ref.table_name == "__Calendar"
    assert ref.object_name == "Date"


def test_multiple_nameof_in_expression(model):
    """Multiple NAMEOF calls in one expression"""
    resolver = NameofResolver(model)

    test_expr = """
    VAR Col1 = NAMEOF('__Calendar'[Date])
    VAR Col2 = NAMEOF('__Calendar'[Year])
    VAR Measure = NAMEOF([TotalSales])
    RETURN Col1 & Col2 & Measure
    """

    refs = resolver.find_nameof_in_expression(test_expr, "TestMeasure", "TestTable")

    assert len(refs) == 3
    column_refs = [r for r in refs if not r.is_measure_ref]
    measure_refs = [r for r in refs if r.is_measure_ref]

    assert len(column_refs) == 2
    assert len(measure_refs) == 1


def test_validate_valid_column_reference(model):
    """A valid column reference validates"""
    resolver = NameofResolver(model)

    test_ref = NameofReference(
        table_name="__Calendar",
        object_name="Date",
        full_reference="__Calendar[Date]",
        source_measure="TestMeasure",
        source_table="TestTable",
        is_measure_ref=False,
        line_context="VAR Col = NAMEOF('__Calendar'[Date])"
    )

    broken = resolver.validate_references([test_ref])

    assert len(broken) == 0, "Known column should validate successfully"


def test_validate_invalid_table_reference(model):
    """Reference to a non-existent table"""
    resolver = NameofResolver(model)

    test_ref = NameofReference(
        table_name="NonExistentTable",
        object_name="SomeColumn",
        full_reference="NonExistentTable[SomeColumn]",
        source_measure="TestMeasure",
        source_table="TestTable",
        is_measure_ref=False,
        line_context="NAMEOF(NonExistentTable[SomeColumn])"
    )

    broken = resolver.validate_references([test_ref])

    assert len(broken) == 1
    assert isinstance(broken[0], _api().BrokenReference)
    assert _severity(broken[0]) == "ERROR"
    assert "not found" in broken[0].reason.lower()


def test_validate_invalid_column_reference(model):
    """Reference to a non-existent column in a valid table"""
    resolver = NameofResolver(model)

    test_ref = NameofReference(
        table_name="__Calendar",
        object_name="NonExistentColumn",
        full_reference="__Calendar[NonExistentColumn]",
        source_measure="TestMeasure",
        source_table="TestTable",
        is_measure_ref=False,
        line_context="NAMEOF(__Calendar[NonExistentColumn])"
    )

    broken = resolver.validate_references([test_ref])

    assert len(broken) == 1
    assert _severity(broken[0]) == "ERROR"
    assert "not found" in broken[0].reason.lower()


def test_get_reference_statistics(model, model_dir):
    """Statistics from `report nameof --json`."""
    refs = NameofResolver(model).find_all_nameof_references()
    code, out, err = run_cli("report", "nameof", model_dir, "--json")
    assert code == 0, err
    stats = json.loads(out)["statistics"]

    assert "total_references" in stats
    assert "measure_references" in stats
    assert "column_references" in stats
    assert "unique_tables" in stats
    assert "unique_objects" in stats

    assert stats["total_references"] == len(refs)
    assert stats["measure_references"] + stats["column_references"] == stats["total_references"]
    assert stats["unique_tables"] > 0
    assert stats["unique_objects"] > 0


def _report_text(model_dir):
    code, out, err = run_cli("report", "nameof", model_dir)
    assert code == 0, err
    return out


def test_generate_report(model, model_dir):
    """Text report from `report nameof`."""
    resolver = NameofResolver(model)
    refs = resolver.find_all_nameof_references()
    broken = resolver.validate_references(refs)

    report = _report_text(model_dir)

    assert isinstance(report, str)
    assert len(report) > 0
    assert "NAMEOF REFERENCE VALIDATION REPORT" in report
    assert "Total References:" in report

    if len(broken) == 0:
        assert "All references are valid" in report
    else:
        assert "Found" in report and "issues" in report


def test_generate_report_broken_branch(model_dir):
    """Spec E-report-nameof case 2, second branch: a broken stand-in copy."""
    shop = model_dir / "definition" / "tables" / "Shop Measures.tmdl"
    text = shop.read_text(encoding="utf-8")
    shop.write_text(text.replace(
        "\tpartition 'Shop Measures' = m\n",
        "\tmeasure 'Gone Field Name' = NAMEOF('Shops'[Units])\n\n\tpartition 'Shop Measures' = m\n"),
        encoding="utf-8")
    report = _report_text(model_dir)
    assert "Found" in report and "issues" in report


def test_nameof_case_insensitivity(model):
    """The NAMEOF function name is case-insensitive"""
    resolver = NameofResolver(model)

    test_cases = [
        "NAMEOF(__Calendar[Date])",
        "nameof(__Calendar[Date])",
        "NameOf(__Calendar[Date])",
        "NAMEOF (__Calendar[Date])",  # with space
    ]

    for expr in test_cases:
        refs = resolver.find_nameof_in_expression(expr, "Test", "Test")
        assert len(refs) >= 1, f"Should find NAMEOF in: {expr}"
