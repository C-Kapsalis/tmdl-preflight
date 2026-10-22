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
    # 1-based line on which the expression text starts (calculated columns)
    expression_line: Optional[int] = None
    description: Optional[str] = None  # from a /// comment run
    display_folder: Optional[str] = None

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
    # 1-based line on which the expression text starts
    expression_line: Optional[int] = None
    description: Optional[str] = None  # from a /// comment run
    display_folder: Optional[str] = None
    # DAX of a measure-level ``formatStringDefinition`` block, when present
    format_string_definition: Optional[str] = None

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
class RefreshPolicy:
    """Where a table's ``refreshPolicy`` block sits, plus its properties."""

    file: Path
    line: int
    level: int  # indentation level of the ``refreshPolicy`` line
    properties: dict[str, str] = field(default_factory=dict)


@dataclass
class Table:
    """A table parsed from one ``tables/*.tmdl`` file."""

    name: str
    file: Path
    line: int = 1
    lineage_tag: Optional[str] = None
    is_hidden: bool = False
    is_field_parameter: bool = False
    is_calculation_group: bool = False
    description: Optional[str] = None  # from a /// comment run
    # First declaration wins in the name-keyed dicts; the lists keep every
    # declaration, duplicates included, so duplicate-name rules can see them.
    columns: dict[str, Column] = field(default_factory=dict)
    measures: dict[str, Measure] = field(default_factory=dict)
    column_list: list[Column] = field(default_factory=list)
    measure_list: list[Measure] = field(default_factory=list)
    partitions: list[Partition] = field(default_factory=list)
    # (name, expression, line) triples for calculationItem blocks
    calculation_items: list[tuple[str, str, int]] = field(default_factory=list)
    # 1-based expression start line of each calculation item, parallel to
    # ``calculation_items``
    calculation_item_starts: list[int] = field(default_factory=list)
    # (owner, expression, line) triples for formatStringDefinition blocks
    # (owner is the measure or calculation item the block belongs to)
    format_string_definitions: list[tuple[str, str, int]] = field(default_factory=list)
    # 1-based expression start line of each format-string definition,
    # parallel to ``format_string_definitions``
    format_string_definition_starts: list[int] = field(default_factory=list)
    # names of calculation items that carry a formatStringDefinition
    dynamic_format_items: list[str] = field(default_factory=list)
    refresh_policy: Optional[RefreshPolicy] = None

    # case-insensitive indexes, built on first lookup
    _ci_columns: Optional[dict] = field(default=None, repr=False, compare=False)
    _ci_measures: Optional[dict] = field(default=None, repr=False, compare=False)

    def add_column(self, col: Column) -> None:
        self.column_list.append(col)
        self.columns.setdefault(col.name, col)
        self._ci_columns = None

    def add_measure(self, meas: Measure) -> None:
        self.measure_list.append(meas)
        self.measures.setdefault(meas.name, meas)
        self._ci_measures = None

    def find_column(self, name: str) -> Optional[Column]:
        """Case-insensitive column lookup (the engine compares names that way)."""
        if name in self.columns:
            return self.columns[name]
        if self._ci_columns is None:
            self._ci_columns = {}
            for c in self.column_list:
                self._ci_columns.setdefault(c.name.lower(), c)
        return self._ci_columns.get(name.lower())

    def find_measure(self, name: str) -> Optional[Measure]:
        """Case-insensitive measure lookup."""
        if name in self.measures:
            return self.measures[name]
        if self._ci_measures is None:
            self._ci_measures = {}
            for m in self.measure_list:
                self._ci_measures.setdefault(m.name.lower(), m)
        return self._ci_measures.get(name.lower())


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
    # the values exactly as written in the file ("Many" is not "many"); the
    # pairs above are lowercased, because most checks compare case-insensitively
    from_cardinality_raw: str = "many"
    to_cardinality_raw: str = "one"
    cross_filtering: str = "oneDirection"
    is_active: bool = True

    @property
    def endpoints(self) -> tuple[str, str, str, str]:
        return (self.from_table, self.from_column, self.to_table, self.to_column)


@dataclass
class Expression:
    """A shared expression or parameter from ``expressions.tmdl``."""

    name: str
    file: Path
    line: int
    expression: str = ""
    # parsed ``meta [Key = value, ...]`` record (values kept as raw text,
    # string quotes removed)
    meta: dict[str, str] = field(default_factory=dict)
    lineage_tag: Optional[str] = None

    @property
    def is_parameter(self) -> bool:
        return self.meta.get("IsParameterQuery", "").lower() == "true"


@dataclass
class ModelInfo:
    """What ``model.tmdl`` declares about the model as a whole."""

    file: Optional[Path] = None
    name: str = ""
    discourage_implicit_measures: bool = False
    # (table name, 1-based line) for every ``ref table`` line
    ref_tables: list[tuple[str, int]] = field(default_factory=list)


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
    # 1-based line on which the expression text starts (defaults to line)
    start_line: Optional[int] = None

    @property
    def first_line(self) -> int:
        return self.start_line or self.line

    @property
    def label(self) -> str:
        if self.kind == "partition_source":
            return f"{self.table} (partition source)"
        if self.kind == "calculation_item":
            return f"{self.table}[{self.name}] (calculationItem)"
        if self.kind == "format_string_definition":
            return f"{self.table} (formatStringDefinition)"
        return f"{self.table}[{self.name}]"


@dataclass
class ParseError:
    """A file the parser could not make sense of."""

    file: Path
    message: str
    line: Optional[int] = None
    # "error" for anything that stops the file from loading; "warning" for
    # oddities the parser could still read (for example an empty name)
    severity: str = "error"


@dataclass
class SemanticModel:
    """A parsed ``definition/`` folder of a ``*.SemanticModel``."""

    definition_path: Path
    # First declaration wins in ``tables``; ``table_list`` keeps every parsed
    # table file, duplicates included.
    tables: dict[str, Table] = field(default_factory=dict)
    table_list: list[Table] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    # relationships the parser could not resolve to two endpoints; R001
    # reports them instead of the parser dropping them silently
    malformed_relationships: list[Relationship] = field(default_factory=list)
    lineage_tags: list[LineageTagOccurrence] = field(default_factory=list)
    tmdl_files: list[Path] = field(default_factory=list)
    parse_errors: list[ParseError] = field(default_factory=list)
    expressions: list[Expression] = field(default_factory=list)
    info: ModelInfo = field(default_factory=ModelInfo)
    _ci_tables: Optional[dict] = field(default=None, repr=False, compare=False)

    def add_table(self, table: Table) -> None:
        self.table_list.append(table)
        self.tables.setdefault(table.name, table)
        self._ci_tables = None

    def get_table(self, name: str) -> Optional[Table]:
        return self.tables.get(name)

    def find_table(self, name: str) -> Optional[Table]:
        """Case-insensitive table lookup (the engine compares names that way)."""
        if name in self.tables:
            return self.tables[name]
        if self._ci_tables is None:
            self._ci_tables = {}
            for t in self.table_list:
                self._ci_tables.setdefault(t.name.lower(), t)
        return self._ci_tables.get(name.lower())

    def get_column(self, table: str, column: str) -> Optional[Column]:
        t = self.tables.get(table)
        return t.columns.get(column) if t else None

    def find_measures(self, name: str) -> list[Measure]:
        """All measures with this name, across every table."""
        return [
            t.measures[name] for t in self.tables.values() if name in t.measures
        ]

    def find_measures_ci(self, name: str) -> list[Measure]:
        """All measures with this name (case-insensitive), across every table."""
        low = name.lower()
        return [m for m in self.all_measures() if m.name.lower() == low]

    def all_measures(self) -> Iterator[Measure]:
        """Every measure declaration, duplicates included."""
        for t in self.table_list:
            yield from t.measure_list

    def all_columns(self) -> Iterator[Column]:
        """Every column declaration, duplicates included."""
        for t in self.table_list:
            yield from t.column_list

    def dax_blocks(self) -> Iterator[DaxBlock]:
        """Every DAX expression in the model, uniform shape.

        Covers measures, calculated columns, calculated-partition sources
        (calculated tables and field parameters), calculation items, and
        dynamic format-string definitions. M partitions are excluded: their
        source is Power Query, not DAX.
        """
        for t in self.table_list:
            for m in t.measure_list:
                if m.expression:
                    yield DaxBlock(
                        "measure", t.name, m.name, m.expression, m.file, m.line,
                        m.expression_line,
                    )
            for c in t.column_list:
                if c.expression:
                    yield DaxBlock(
                        "calculated_column", t.name, c.name, c.expression, c.file,
                        c.line, c.expression_line,
                    )
            for p in t.partitions:
                if p.kind == "calculated" and p.source:
                    yield DaxBlock(
                        "partition_source", t.name, p.name, p.source, p.file,
                        p.source_start_line or p.line, p.source_start_line,
                    )
            for k, (name, expr, line) in enumerate(t.calculation_items):
                if expr:
                    start = (
                        t.calculation_item_starts[k]
                        if k < len(t.calculation_item_starts) else None
                    )
                    yield DaxBlock(
                        "calculation_item", t.name, name, expr, t.file, line, start
                    )
            for k, (owner, expr, line) in enumerate(t.format_string_definitions):
                if expr:
                    start = (
                        t.format_string_definition_starts[k]
                        if k < len(t.format_string_definition_starts) else None
                    )
                    yield DaxBlock(
                        "format_string_definition", t.name, owner, expr, t.file,
                        line, start,
                    )
