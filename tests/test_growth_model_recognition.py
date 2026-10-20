"""Partition sources are extracted in both TMDL styles (spec A-partition-source-styles).

A discovery step that required the fenced form (```` source = ``` ````) silently
reported "0 dimensions" for any model written with a bare `source =`. Never
trust a zero from a hand-rolled pattern: these tests assert that a
known-present case returns non-zero, not merely that nothing raised.

Only the partition-source cases are covered here; the tool's parser
(`tmdl_preflight.parser.parse_table_file` -> `Table.partitions[0].source`)
does the extraction.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from tmdl_preflight.parser import parse_table_file

FENCED = """
	partition 'y-Selector Main Plot-abc' = calculated
		mode: import
		source = ```
				{
				("Year", NAMEOF('__Calendar'[Calendar Year]), 0, "Date_y", "Query Related")
				}
				```
"""

UNFENCED = """
	partition 'y-Selector Main Plot-abc' = calculated
		mode: import
		source =
				{
				-- Date_y
				("Year", NAMEOF('__Calendar'[Calendar Year]), 0, "Date_y", "Query Related"),

				("Quarter", NAMEOF('__Calendar'[Quarter Text]), 1, "Date_y", "Query Related")
				}
"""


def _extract_partition_source(tmp_path: Path, content: str) -> Optional[str]:
    path = tmp_path / "y-Selector Main Plot.tmdl"
    if not content.lstrip().startswith("table"):
        content = "table 'y-Selector Main Plot'\n\tlineageTag: 6f1d2a7e-0b8c-4e7a-9f3d-2c5b8a1e4d70\n" + content
    path.write_text(content, encoding="utf-8")
    table, _errors = parse_table_file(path)
    if table is None or not table.partitions:
        return None
    return table.partitions[0].source


@pytest.mark.parametrize("content,style", [(FENCED, "fenced"), (UNFENCED, "unfenced")],
                         ids=["fenced", "unfenced"])
def test_partition_source_is_extracted_in_both_tmdl_styles(tmp_path, content: str, style: str) -> None:
    got = _extract_partition_source(tmp_path, content)
    assert got is not None, f"{style} partition source not extracted"
    assert "NAMEOF(" in got, f"{style} extraction dropped the tuple body"


def test_unfenced_extraction_keeps_every_row(tmp_path) -> None:
    """The unfenced branch must capture the WHOLE block, blank lines included."""
    got = _extract_partition_source(tmp_path, UNFENCED)
    assert got.count("NAMEOF(") == 2, f"expected 2 rows, captured {got.count('NAMEOF(')}"


def test_absent_source_still_returns_none(tmp_path) -> None:
    """The fix must not turn a genuinely missing partition into a false positive."""
    assert _extract_partition_source(
        tmp_path, "table 'x'\n\tlineageTag: abc\n"
    ) is None
