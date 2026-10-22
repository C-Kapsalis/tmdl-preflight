"""The applied-filters summary measure: the dimensions it lists and its DAX.

``i-Applied Filters`` is a generated measure. It names every dimension the
y-axis field-parameter tables expose and says which values of it the reader
has filtered. Its body is generated from those rows, so a table that leaves
the model takes the measure with it: the generator rebuilds the body from
the rows that are still there.
"""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase

from .fieldparams import nameof_parts, source_rows
from .model import SemanticModel

#: The y-axis of the field parameters: the tables whose rows are the
#: dimensions a reader can filter on.
Y_AXIS_GLOBS = ("y-Selector*", "y-Plot Specific*")

#: The measure the generator owns.
SUMMARY_MEASURE = "i-Applied Filters"


@dataclass
class Dimension:
    """One dimension the summary measure lists."""

    table: str
    column: str
    label: str


def is_y_axis(name: str) -> bool:
    """Is this table one of the y-axis field-parameter tables?"""
    return any(fnmatchcase(name, glob) for glob in Y_AXIS_GLOBS)


def _label(field: str) -> str:
    value = field.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value.replace('""', '"')


def dimensions(model: SemanticModel) -> list[Dimension]:
    """The dimensions the y-axis tables expose, in table and row order.

    A dimension two rows name is listed once.
    """
    out: list[Dimension] = []
    seen: set[tuple[str, str]] = set()
    for table in model.table_list:
        if not is_y_axis(table.name):
            continue
        for partition in table.partitions:
            if partition.kind != "calculated" or not partition.source:
                continue
            for row in source_rows(partition.source):
                qualifier, member = nameof_parts(row.fields[1])
                if not qualifier or not member:
                    continue
                key = (qualifier.lower(), member.lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append(Dimension(qualifier, member, _label(row.fields[0])))
    return out


def _quote(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _block(dim: Dimension) -> str:
    """The DAX of one dimension: what the reader filtered it to.

    The selected values are listed; a dimension whose column has more than
    five values and whose selection excludes a few of them lists the
    excluded ones instead ("Select all, untick a few").
    """
    col = f"'{dim.table}'[{dim.column}]"
    item = f'IF(ISBLANK({col}), "(Blank)", {col} & "")'
    return (
        "IF(\n"
        f"    ISFILTERED({col}),\n"
        f"    VAR ___f = FILTERS({col})\n"
        f"    VAR ___x = EXCEPT(ALL({col}), ___f)\n"
        "    VAR ___nX = COUNTROWS(___x)\n"
        f"    VAR ___inv = COUNTROWS(ALL({col})) > 5 && ___nX >= 1 && ___nX <= 3\n"
        f"    VAR ___t = TOPN(10, ___f, {col})\n"
        f'    VAR ___d = CONCATENATEX(___t, {item}, ", ")\n'
        f'    VAR ___dx = CONCATENATEX(___x, {item}, ", ", {col}, ASC)\n'
        f"    RETURN {_quote(dim.label)} & IF(___inv, \" is not \", \" = \")"
        " & IF(___inv, ___dx, ___d) & UNICHAR(13) & UNICHAR(10)\n"
        ")"
    )


def generate_measure(dims: list[Dimension]) -> str:
    """The body of the summary measure: one block per dimension."""
    return " &\n".join(_block(d) for d in dims)
