"""Data model for a parsed TMDL semantic model.

These are deliberately thin dataclasses: tmdl-preflight parses just enough
of a TMDL definition to run its rules. It is *not* a full TMDL
implementation, and it never needs to round-trip a model. Fixers edit the
original files surgically instead of re-serializing these objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional


@dataclass
class Column:
    """A column declared inside a ``table`` block."""

    name: str
    table: str
    file: Path
    line: int
    data_type: Optional[str] = None
    source_column: Optional[str] = None
    format_string: Optional[str] = None
    lineage_tag: Optional[str] = None
    is_hidden: bool = False
    is_key: bool = False
    expression: Optional[str] = None  # set for calculated columns

    @property
    def is_calculated(self) -> bool:
        return self.expression is not None

    @property
    def full_name(self) -> str:
        return f"{self.table}[{self.name}]"


@dataclass
class Measure:
    """A measure declared inside a ``table`` block."""

    name: str
    table: str
    file: Path
    line: int
    expression: str = ""
    format_string: Optional[str] = None
    lineage_tag: Optional[str] = None
    is_hidden: bool = False

    @property
    def full_name(self) -> str:
        return f"{self.table}[{self.name}]"


@dataclass
class Partition:
    """A partition; for ``calculated`` partitions the source is DAX."""

    name: str
    table: str
    file: Path
    line: int
    kind: str = "m"  # "m", "calculated", "entity", ...
    source: Optional[str] = None
    # 1-based inclusive line range of the source block in the file (used by
    # fixers that rewrite the block in place).
    source_start_line: Optional[int] = None
    source_end_line: Optional[int] = None


@dataclass
class Table:
    """A table parsed from one ``tables/*.tmdl`` file."""

    name: str
    file: Path
    line: int = 1
    lineage_tag: Optional[str] = None
    is_hidden: bool = False
    is_field_parameter: bool = False
    columns: dict[str, Column] = field(default_factory=dict)
    measures: dict[str, Measure] = field(default_factory=dict)
    partitions: list[Partition] = field(default_factory=list)
    # (name, expression, line) triples for calculationItem blocks
    calculation_items: list[tuple[str, str, int]] = field(default_factory=list)
    # (owner, expression, line) triples for formatStringDefinition blocks
    format_string_definitions: list[tuple[str, str, int]] = field(default_factory=list)


@dataclass
class Relationship:
    """A relationship parsed from ``relationships.tmdl``."""

    rel_id: str
    file: Path
    line: int
    from_table: str = ""
    from_column: str = ""
    to_table: str = ""
    to_column: str = ""
    from_cardinality: str = "many"
    to_cardinality: str = "one"
    cross_filtering: str = "oneDirection"
    is_active: bool = True

    @property
    def endpoints(self) -> tuple[str, str, str, str]:
        return (self.from_table, self.from_column, self.to_table, self.to_column)


@dataclass
class LineageTagOccurrence:
    """One ``lineageTag:`` line anywhere in the definition folder."""

    tag: str
    file: Path
    line: int
    context: str  # for example "table Sales", "column order_id"


@dataclass
class DaxBlock:
    """Any DAX expression the model carries, wherever it lives."""

    kind: str  # measure | calculated_column | partition_source |
    #            calculation_item | format_string_definition
    table: str
    name: str
    expression: str
    file: Path
    line: int

    @property
    def label(self) -> str:
        return f"{self.table}[{self.name}] ({self.kind})"


@dataclass
class ParseError:
    """A file the parser could not make sense of."""

    file: Path
    message: str
    line: Optional[int] = None


@dataclass
class SemanticModel:
    """A parsed ``definition/`` folder of a ``*.SemanticModel``."""

    definition_path: Path
    tables: dict[str, Table] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)
    lineage_tags: list[LineageTagOccurrence] = field(default_factory=list)
    tmdl_files: list[Path] = field(default_factory=list)
    parse_errors: list[ParseError] = field(default_factory=list)

    def get_table(self, name: str) -> Optional[Table]:
        return self.tables.get(name)

    def get_column(self, table: str, column: str) -> Optional[Column]:
        t = self.tables.get(table)
        return t.columns.get(column) if t else None

    def find_measures(self, name: str) -> list[Measure]:
        """All measures with this name, across every table."""
        return [
            t.measures[name] for t in self.tables.values() if name in t.measures
        ]

    def all_measures(self) -> Iterator[Measure]:
        for t in self.tables.values():
            yield from t.measures.values()

    def dax_blocks(self) -> Iterator[DaxBlock]:
        """Every DAX expression in the model, uniform shape.

        Covers measures, calculated columns, calculated-partition sources
        (calculated tables and field parameters), calculation items, and
        dynamic format-string definitions. M partitions are excluded: their
        source is Power Query, not DAX.
        """
        for t in self.tables.values():
            for m in t.measures.values():
                if m.expression:
                    yield DaxBlock("measure", t.name, m.name, m.expression, m.file, m.line)
            for c in t.columns.values():
                if c.expression:
                    yield DaxBlock(
                        "calculated_column", t.name, c.name, c.expression, c.file, c.line
                    )
            for p in t.partitions:
                if p.kind == "calculated" and p.source:
                    yield DaxBlock(
                        "partition_source", t.name, p.name, p.source, p.file,
                        p.source_start_line or p.line,
                    )
            for name, expr, line in t.calculation_items:
                if expr:
                    yield DaxBlock("calculation_item", t.name, name, expr, t.file, line)
            for owner, expr, line in t.format_string_definitions:
                if expr:
                    yield DaxBlock(
                        "format_string_definition", t.name, owner, expr, t.file, line
                    )
