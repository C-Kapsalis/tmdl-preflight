"""Model manifest: a deterministic JSON view of a semantic model for the
pipelines around it (schema checks, lineage, documentation).

Per table it records the role (by name), the columns and measures, and the
warehouse table its partition reads, recovered from the M text in one of
three forms: a call of a loader function (``source_filter_dates("view",
"date")`` or a wrapper the model's expressions derive from it), an inlined
incremental-refresh native query, or the navigator form
``{[Name="view", Kind="Table"]}``. For each sourced column it follows the
Power Query renames and copies back to the warehouse column, and marks
columns created in Power Query as computed.

It also reads the warehouse target the model declares in its parameters and
compares it with an expected target contract (a targets file), refusing to
emit a manifest when they disagree.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

GENERATED_BY = "tmdl-preflight manifest"
TARGET_NOTE = ("Model declarations from expressions.tmdl must match the warehouse target "
               "contract in real_clients_registry.yml; registry bq_project/bq_dataset "
               "values are never allowed to mask a stale model target.")

#: The marker an inlined incremental-refresh query always carries.
DEFAULT_IR_MARKER = "ir_dfilter"

#: Tables every domain shares; their name is matched exactly.
SHARED_DIMENSIONS = (
    "__Calendar",
    "__Comparison Calendar",
    "_Accounts",
    "_Devices",
    "_Countries",
    "_Landing Pages",
)

#: The shipped domain rules: the first rule whose substring appears in the
#: (lowercased) table name wins.
DEFAULT_DOMAINS: list[dict] = [
    {"name": "Facebook", "substrings": ["fb ", "facebook", "_fb "]},
    {"name": "GA4", "substrings": ["ga4"]},
    {"name": "Email", "substrings": ["client-c", "email"]},
    {"name": "App & YouTube",
     "substrings": ["youtube", "google play", "play installs", "adjust"]},
    {"name": "Speed",
     "substrings": ["speed", "lighthouse", "audit score", "page speed"]},
    {"name": "SEO & Search",
     "substrings": ["queries organic", "crawl", "sitemap", "cluster", "organic"]},
    {"name": "Advertising",
     "substrings": ["ads", "campaign", "conversion", "keyword", "queries paid",
                    "google ads", "_ad", "_quer", "device"]},
]


@dataclass
class SourceSettings:
    connector_tokens: list[str] = field(default_factory=lambda: ["GoogleBigQuery"])
    default_loaders: list[str] = field(default_factory=lambda: ["source_filter_dates"])
    loader_family_prefixes: list[str] = field(default_factory=lambda: ["_source_filter_rowsLimit"])
    project_parameter: str = "v-BQ_project"
    ir_marker: Optional[str] = DEFAULT_IR_MARKER
    name_transform_functions: list[str] = field(
        default_factory=lambda: ["PrefixColumns", "TransformColumnNames"])


@dataclass
class DomainSettings:
    """The domain rules a table name is classified with."""

    rules: list[dict] = field(default_factory=lambda: [dict(r) for r in DEFAULT_DOMAINS])
    shared: list[str] = field(default_factory=lambda: list(SHARED_DIMENSIONS))
    shared_label: str = "Core / Shared"
    fallback: str = "Other"


@dataclass
class ClassSettings:
    field_parameter_prefixes: list[str] = field(
        default_factory=lambda: ["x-Selector", "x-Plot Specific", "y-Selector", "y-Plot Specific"])
    selector_prefixes: list[str] = field(default_factory=lambda: ["z-"])
    helper_prefixes: list[str] = field(default_factory=lambda: ["w-"])
    filter_prefixes: list[str] = field(default_factory=lambda: ["f-", "i-"])


DATA_CLASSES = ("fact", "dimension", "calendar")


# ---------------------------------------------------------------------------
# M text helpers
# ---------------------------------------------------------------------------


def drop_comment_lines(text: str) -> str:
    return "\n".join(ln for ln in text.split("\n") if not ln.lstrip().startswith("//"))


def code_only(text: str) -> str:
    """Remove the contents of M string literals; ``#"name"`` stays."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"' and not (i > 0 and text[i - 1] == "#"):
            i += 1
            while i < n:
                if text[i] == '"':
                    if text[i + 1:i + 2] == '"':
                        i += 2
                        continue
                    break
                i += 1
            out.append('""')
            i += 1
            continue
        if ch == '"':  # the quote of #"name": copy the identifier verbatim
            end = text.find('"', i + 1)
            end = n - 1 if end < 0 else end
            out.append(text[i:end + 1])
            i = end + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _string_literals(text: str) -> Iterable[tuple[int, int, str]]:
    """``(start, end, value)`` of each top-level string literal (``#"x"``
    identifiers excluded)."""
    i, n = 0, len(text)
    while i < n:
        if text[i] == '"':
            is_ident = i > 0 and text[i - 1] == "#"
            j, buf = i + 1, []
            while j < n:
                if text[j] == '"':
                    if text[j + 1:j + 2] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(text[j])
                j += 1
            if not is_ident:
                yield i, j + 1, "".join(buf)
            i = j + 1
            continue
        i += 1


def _call_windows(text: str, fn: str) -> Iterable[str]:
    """Argument text of each ``<anything>.fn(`` / ``fn(`` call, up to the
    matching parenthesis (parentheses inside strings do not count)."""
    for m in re.finditer(r"\b" + re.escape(fn) + r"\s*\(", text):
        depth, i, n = 1, m.end(), len(text)
        in_str = False
        while i < n and depth:
            ch = text[i]
            if in_str:
                if ch == '"':
                    if text[i + 1:i + 2] == '"':
                        i += 2
                        continue
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        yield text[m.end():i - 1]


def _top_level_literals_after_first_comma(args: str) -> list[str]:
    depth, i, n, seen_comma = 0, 0, len(args), False
    out = []
    while i < n:
        ch = args[i]
        if ch == '"' and not (i > 0 and args[i - 1] == "#"):
            j, buf = i + 1, []
            while j < n:
                if args[j] == '"':
                    if args[j + 1:j + 2] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    break
                buf.append(args[j])
                j += 1
            if seen_comma and depth == 0:
                out.append("".join(buf))
            i = j + 1
            continue
        if ch == '"':  # #"identifier"
            end = args.find('"', i + 1)
            i = (end + 1) if end >= 0 else n
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            seen_comma = True
        i += 1
    return out


_PAIR_RE = re.compile(r'\{\s*"((?:[^"]|"")*)"\s*,\s*"((?:[^"]|"")*)"\s*\}')
_TYPE_PAIR_RE = re.compile(r'\{\s*"((?:[^"]|"")*)"\s*,\s*(type\s+\w+|[A-Za-z]\w*\.Type)\s*\}')


def parse_renames(m_text: str) -> dict[str, str]:
    """new name -> old name for every RenameColumns pair."""
    out: dict[str, str] = {}
    for args in _call_windows(m_text, "RenameColumns"):
        for old, new in _PAIR_RE.findall(args):
            out[new.replace('""', '"')] = old.replace('""', '"')
    return out


def synthesized_columns(m_text: str) -> set[str]:
    out = set()
    for args in _call_windows(m_text, "AddColumn"):
        lits = _top_level_literals_after_first_comma(args)
        if lits:
            out.add(lits[0])
    return out


def duplicate_edges(m_text: str) -> list[tuple[str, str]]:
    """``(origin, copy)`` for each DuplicateColumn call."""
    out = []
    for args in _call_windows(m_text, "DuplicateColumn"):
        lits = _top_level_literals_after_first_comma(args)
        if len(lits) >= 2:
            out.append((lits[0], lits[1]))
    return out


def type_changes(m_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for args in _call_windows(m_text, "TransformColumnTypes"):
        for col, typ in _TYPE_PAIR_RE.findall(args):
            out[col.replace('""', '"')] = typ
    return out


def normalise(name: str) -> str:
    return re.sub(r"\s+", "_", name.strip().lower())


def resolve_origin(name: str, renames: dict[str, str], synthesized: Iterable[str] = ()) -> Optional[str]:
    """Follow rename/copy edges back to the warehouse column (normalised), or
    None when the column was created in Power Query (or the edges cycle)."""
    synth = set(synthesized)
    cur = name
    for _ in range(16):
        if cur in synth:
            return None
        nxt = renames.get(cur)
        if nxt is None:
            break
        cur = nxt
    else:
        return None
    if cur in synth:
        return None
    return normalise(cur)


# ---------------------------------------------------------------------------
# Loaders derived from the shared expressions
# ---------------------------------------------------------------------------

_EXPR_START_RE = re.compile(r"^expression\s+('(?:[^']|'')+'|[^\s=]+)\s*=")


def _expression_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, list[str]]] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        m = _EXPR_START_RE.match(line)
        if m:
            name = m.group(1)
            if name.startswith("'"):
                name = name[1:-1].replace("''", "'")
            blocks.append((name, [line[m.end():]]))
            continue
        if blocks and not line.lstrip().startswith("//"):
            blocks[-1][1].append(line)
    return [(n, "\n".join(b)) for n, b in blocks]


def _references(code: str, name: str) -> bool:
    if f'#"{name}"' in code:
        return True
    return re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", code) is not None


def derive_loaders(expressions_text: str, settings: Optional[SourceSettings] = None) -> set[str]:
    """Expressions that read the warehouse, directly or through another."""
    s = settings or SourceSettings()
    blocks = [(n, code_only(b)) for n, b in _expression_blocks(expressions_text)]
    readers = {n for n, code in blocks if any(t in code for t in s.connector_tokens)}
    changed = True
    while changed:
        changed = False
        for n, code in blocks:
            if n not in readers and any(_references(code, r) for r in readers):
                readers.add(n)
                changed = True
    return readers | set(s.default_loaders)


def derive_name_transformers(expressions_text: str, settings: Optional[SourceSettings] = None) -> set[str]:
    s = settings or SourceSettings()
    return {n for n, b in _expression_blocks(expressions_text)
            if any(f in code_only(b) for f in s.name_transform_functions)}


# ---------------------------------------------------------------------------
# Source forms
# ---------------------------------------------------------------------------

_IR_TABLE_RE = re.compile(r'&\s*"([A-Za-z0-9_]+)"\s*&\s*"`\s*where\s*"')
_IR_DATE_RE = re.compile(r"cast\((\w+) as date\)")
_NAV_RE = re.compile(r'\{\s*\[\s*Name\s*=\s*"((?:[^"]|"")+)"\s*,\s*Kind\s*=\s*"Table"\s*\]\s*\}')


def parse_inline_window(text: str, marker: Optional[str] = None) -> Optional[tuple[str, Optional[str]]]:
    """``(view, date column)`` of an inlined incremental-refresh query."""
    marker = DEFAULT_IR_MARKER if marker is None else marker
    if marker and marker not in text:
        return None
    if "RangeStart" not in text:
        return None
    m = _IR_TABLE_RE.search(text)
    if not m:
        return None
    d = _IR_DATE_RE.search(text)
    return m.group(1), d.group(1) if d else None


def _loader_call(text: str, loaders: Iterable[str], prefixes: Iterable[str]) -> Optional[tuple[str, Optional[str]]]:
    lit = r'"((?:[^"]|"")*)"'
    names = [re.escape(n) for n in sorted(set(loaders), key=len, reverse=True)]
    names += [re.escape(p) + r"[A-Za-z-]*" for p in prefixes]
    if not names:
        return None
    rx = re.compile(r'(?:#")?(?:' + "|".join(names) + r')(?:")?\s*\(\s*' + lit
                    + r'(?:\s*,\s*' + lit + r')?')
    m = rx.search(text)
    if m:
        date = m.group(2).replace('""', '"') if m.group(2) else None
        return m.group(1).replace('""', '"'), date or None
    return None


def _speaks_warehouse(text: str, loaders: Iterable[str], s: SourceSettings) -> bool:
    if any(t in text for t in s.connector_tokens) or s.project_parameter in text:
        return True
    return any(n in text for n in loaders)


def resolve_source(text: str, loaders: Iterable[str], s: SourceSettings) -> Optional[dict]:
    loaders = list(loaders)
    call = _loader_call(text, loaders, s.loader_family_prefixes)
    if call:
        return {"table": call[0], "date_column": call[1]}
    ir = parse_inline_window(text, s.ir_marker)
    if ir:
        return {"table": ir[0], "date_column": ir[1], "incremental_refresh": True}
    nav = _NAV_RE.search(text)
    if nav:
        return {"table": nav.group(1).replace('""', '"'), "date_column": None, "navigator": True}
    return None


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _unquote(name: str) -> str:
    name = name.strip()
    if len(name) >= 2 and name[0] == name[-1] == "'":
        return name[1:-1]
    return name


def classify(name: str, cls: Optional[ClassSettings] = None) -> str:
    c = cls or ClassSettings()
    if name.startswith("#") or name.endswith(" Measures"):
        return "measure-group"
    if name.startswith(tuple(c.field_parameter_prefixes)):
        return "field-parameter"
    if name.startswith(tuple(c.selector_prefixes)):
        return "selector"
    if name.startswith(tuple(c.helper_prefixes)):
        return "helper"
    if name.startswith(tuple(c.filter_prefixes)):
        return "filter"
    if name.startswith("__"):
        return "calendar"
    if name.startswith("_"):
        return "dimension"
    return "fact"


def assign_domain(name: str, settings: Optional[DomainSettings] = None) -> Optional[str]:
    """The domain a data table belongs to, or None for a non-data table."""
    d = settings or DomainSettings()
    if name in d.shared:
        return d.shared_label
    low = name.lower()
    for rule in d.rules:
        if any(str(sub).lower() in low for sub in rule.get("substrings", [])):
            return str(rule.get("name"))
    return d.fallback


def parse_table(path: Path, readers: Optional[Iterable[str]] = None,
                transformers: Iterable[str] = (), settings: Optional[SourceSettings] = None,
                classes: Optional[ClassSettings] = None,
                domains: Optional[DomainSettings] = None) -> dict:
    s = settings or SourceSettings()
    lines = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n").split("\n")
    first = lines[0] if lines else ""
    name = _unquote(first[len("table "):]) if first.startswith("table ") else Path(path).stem
    columns: list[dict] = []
    measures: list[dict] = []
    partitions: list[list[str]] = []
    doc: list[str] = []
    current: Optional[dict] = None
    in_partition = False
    for line in lines[1:]:
        if line.startswith("\t///"):
            body = line[4:]
            doc.append((body[1:] if body.startswith(" ") else body).strip())
            continue
        if line.startswith("\tcolumn "):
            head = line[len("\tcolumn "):]
            calc = " =" in head
            cname = _unquote(head.split(" =", 1)[0])
            current = {"name": cname, "dataType": None, "isHidden": False, "isKey": False,
                       "calculated": calc, "summarizeBy": None, "sourceColumn": None,
                       "description": " ".join(doc) if doc else None}
            columns.append(current)
            doc, in_partition = [], False
            continue
        if line.startswith("\tmeasure "):
            head = line[len("\tmeasure "):]
            measures.append({"name": _unquote(head.split(" =", 1)[0]),
                             "description": " ".join(doc) if doc else None})
            current, doc, in_partition = None, [], False
            continue
        if line.startswith("\tpartition "):
            partitions.append([line])
            current, doc, in_partition = None, [], True
            continue
        if in_partition:
            partitions[-1].append(line)
            continue
        if line.startswith("\t\t") and current is not None:
            prop = line.strip()
            m = re.match(r"^(dataType|summarizeBy|sourceColumn)\s*:\s*(.*)$", prop)
            if m:
                current[m.group(1)] = m.group(2).strip()
            elif prop in ("isHidden", "isKey"):
                current[prop] = True
            continue
        if line.strip() and not line.startswith("\t\t"):
            doc = []

    loaders = set(readers) if readers is not None else set()
    loaders |= set(s.default_loaders)
    classification = classify(name, classes)
    table: dict[str, Any] = {"name": name, "classification": classification,
                             "column_count": len(columns)}
    if classification in DATA_CLASSES:
        table["domain"] = assign_domain(name, domains)
    texts = [drop_comment_lines("\n".join(p)) for p in partitions]
    resolved, speaks = None, False
    for t in texts:
        src = resolve_source(t, loaders, s)
        if src and resolved is None:
            resolved = src
        if not src and _speaks_warehouse(t, loaders, s):
            speaks = True
    all_m = "\n".join(texts)
    renames = parse_renames(all_m)
    for origin, dup in duplicate_edges(all_m):
        renames.setdefault(dup, origin)
    synth = synthesized_columns(all_m)
    if resolved is not None:
        table["bq_source"] = resolved
        if any(f in all_m for f in s.name_transform_functions) or any(
                n in all_m for n in transformers):
            table["programmatic_renames"] = True
        changes = type_changes(all_m)
        if changes:
            table["m_type_changes"] = changes
    elif speaks:
        table["unresolved_source"] = True
    for col in columns:
        if col["calculated"] or not col.get("sourceColumn"):
            continue
        origin = None if col["name"] in synth else resolve_origin(col["sourceColumn"], renames, synth)
        if origin is None:
            col["computed"] = True
        else:
            col["bqColumn"] = origin
    if columns:
        table["columns"] = columns
    if measures:
        table["measures"] = measures
    return table


def split_endpoint(text: str) -> tuple[str, str]:
    text = text.strip()
    if text.startswith("'"):
        end = text.find("'", 1)
        return text[1:end], text[end + 1:].lstrip(".")
    table, _, column = text.partition(".")
    return table, column


def parse_relationships(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").split("\n"):
        if line.startswith("relationship "):
            out.append({"fromTable": None, "fromColumn": None,
                        "toTable": None, "toColumn": None, "isActive": True,
                        "crossFilteringBehavior": "single", "fromCardinality": "many",
                        "toCardinality": "one"})
            continue
        if not out or not line.startswith("\t") or line.startswith("\t\t"):
            continue
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if key in ("fromColumn", "toColumn"):
            t, c = split_endpoint(value)
            side = key[:-len("Column")]
            out[-1][f"{side}Table"], out[-1][f"{side}Column"] = t, c
        elif key == "isActive":
            out[-1]["isActive"] = value != "false"
        elif key in ("crossFilteringBehavior", "fromCardinality", "toCardinality"):
            out[-1][key] = value
    return out


# ---------------------------------------------------------------------------
# Warehouse target
# ---------------------------------------------------------------------------


class WarehouseTargetError(RuntimeError):
    """The model's declared warehouse target breaks the target contract."""


_PARAM_RE = re.compile(r'^expression\s+(\'(?:[^\']|\'\')+\'|[^\s=]+)\s*=\s*"((?:[^"]|"")*)"', re.MULTILINE)


def _parameters(expressions: Path) -> dict[str, str]:
    try:
        text = Path(expressions).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    out = {}
    for name, value in _PARAM_RE.findall(text):
        out[_unquote(name)] = value.replace('""', '"')
    return out


def read_warehouse_target(expressions: Path, entry: Optional[dict] = None,
                          default_project: Optional[str] = None,
                          project_parameter: str = "v-BQ_project",
                          dataset_parameter: str = "v-db",
                          billing_parameter: str = "v-BQ_billing_project") -> dict:
    params = _parameters(expressions)
    model_project = params.get(project_parameter)
    model_dataset = params.get(dataset_parameter)
    model_billing = params.get(billing_parameter) or model_project
    out: dict[str, Any] = {"model_project": model_project, "model_dataset": model_dataset,
                           "model_billing_project": model_billing, "project": model_project,
                           "dataset": model_dataset, "billing_project": model_billing}
    fields = target_fields(entry)
    if entry:
        out["client_id"] = entry.get("client_id")
        out["registry_project"] = fields.get("project") or default_project
        out["registry_dataset"] = fields.get("dataset")
        if fields.get("project"):
            out["project"] = fields["project"]
            out["billing_project"] = fields.get("billing_project")
        if fields.get("dataset"):
            out["dataset"] = fields["dataset"]
    out["warehouse"] = ("internal" if out["project"] is None or out["project"] == default_project
                        else "external")
    out["note"] = TARGET_NOTE
    return out


def check_warehouse_target(model_rel: str, target: dict, entry: Optional[dict],
                           reads_warehouse: bool, default_project: Optional[str] = None,
                           dataset_template: Optional[str] = None,
                           key_pattern: Optional[str] = None,
                           targets_name: str = "the targets file") -> None:
    if not reads_warehouse:
        return
    if not target.get("project") or not target.get("dataset"):
        raise WarehouseTargetError(
            f"{model_rel}: could not resolve v-BQ_project/v-db from expressions.tmdl for a "
            f"model that reads BigQuery — refusing to guess a target.")
    if entry:
        key = entry.get("client_id")
        fields = target_fields(entry)
        expected = fields.get("project") or default_project
        declared = target.get("model_project")
        if declared != expected:
            raise WarehouseTargetError(
                f"{model_rel}: v-BQ_project is '{declared or '<missing>'}' but {targets_name} "
                f"expects '{expected}' for {key} — the model and registry warehouse targets "
                f"must match. Refusing to query the registry target because that would hide "
                f"what Power BI actually reads.")
        if fields.get("dataset") and target.get("model_dataset") != fields["dataset"]:
            raise WarehouseTargetError(
                f"{model_rel}: v-db is '{target.get('model_dataset') or '<missing>'}' but "
                f"{targets_name} declares bq_dataset '{fields['dataset']}' for {key} — the "
                f"model and registry dataset targets must match.")
        if dataset_template and key and not fields.get("dataset") and (
                key_pattern is None or re.fullmatch(key_pattern, key)):
            want = dataset_template.format(key=key.replace("-", "_"))
            if target.get("dataset") != want:
                raise WarehouseTargetError(
                    f"{model_rel}: v-db is '{target.get('dataset')}' but client {key} implies "
                    f"'{want}' — this model reads another org's dataset. If intentional, "
                    f"declare bq_dataset: in the registry entry.")


def target_fields(entry: Optional[dict]) -> dict:
    """The canonical target fields of a targets entry.

    Both spellings are accepted: the flat one (``project``, ``dataset``,
    ``billing_project``) and the registry one (``bq_project``, ``bq_dataset``,
    ``bq_billing_project``). The billing project is the declared
    ``bq_billing_project`` when the key is there (even when it is null), else
    the project."""
    if not entry:
        return {}
    project = entry["project"] if "project" in entry else entry.get("bq_project")
    dataset = entry["dataset"] if "dataset" in entry else entry.get("bq_dataset")
    if "billing_project" in entry:
        billing = entry["billing_project"]
    elif "bq_billing_project" in entry:
        billing = entry["bq_billing_project"]
    else:
        billing = project
    return {"project": project, "dataset": dataset, "billing_project": billing}


def load_targets(path: Optional[Path]) -> dict[str, dict]:
    """The targets file (YAML or JSON) as {key: entry}; missing or unreadable
    means no contract. Both the flat shape and the registry shape (a
    ``clients:`` mapping) are accepted."""
    if path is None:
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    data: Any = None
    if str(path).endswith(".json"):
        try:
            data = json.loads(text)
        except ValueError:
            return {}
    else:
        try:
            import yaml  # optional dependency
        except ImportError:  # pragma: no cover - environment without PyYAML
            try:
                data = json.loads(text)
            except ValueError:
                return {}
        else:
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError:
                return {}
    if not isinstance(data, dict):
        return {}
    clients = data.get("clients")
    if isinstance(clients, dict):
        data = clients
    out = {}
    for key, entry in data.items():
        if isinstance(entry, dict):
            e = dict(entry)
            e.setdefault("client_id", str(key))
            out[str(key)] = e
    return out


def entry_for_model(entry: dict, model_rel: str) -> dict:
    """The contract for one model of an entry (secondary rows override)."""
    base = {k: copy.deepcopy(v) for k, v in entry.items() if k != "secondary_models"}
    norm = model_rel.replace("\\", "/").strip("/")
    for sec in entry.get("secondary_models") or []:
        if str(sec.get("path", "")).replace("\\", "/").strip("/") == norm:
            for field, alias in (("project", "bq_project"),
                                 ("billing_project", "bq_billing_project"),
                                 ("dataset", "bq_dataset")):
                if field in sec:
                    value = sec[field]
                elif alias in sec:
                    value = sec[alias]
                else:
                    continue
                base.pop(field, None)
                base.pop(alias, None)
                if value is not None:
                    base[field] = value
            base["model_path"] = sec.get("path")
            return base
    return base


def find_entry(targets: dict[str, dict], model_rel: str) -> Optional[dict]:
    norm = model_rel.replace("\\", "/").strip("/")
    for entry in targets.values():
        paths = [entry.get("model_path")] + [s.get("path") for s in entry.get("secondary_models") or []]
        if any(p and str(p).replace("\\", "/").strip("/") == norm for p in paths):
            return entry_for_model(entry, norm)
    return None


# ---------------------------------------------------------------------------
# The manifest document
# ---------------------------------------------------------------------------


def build_manifest(model_dir: Path, source_path: str, entry: Optional[dict] = None,
                   options: Optional[dict] = None) -> dict:
    opts = options or {}
    src_opts = opts.get("sources") or {}
    s = SourceSettings(**{k: v for k, v in src_opts.items() if k in SourceSettings.__dataclass_fields__})
    target_opts = opts.get("target") or {}
    definition = model_dir / "definition"
    expr_path = definition / "expressions.tmdl"
    expr_text = expr_path.read_text(encoding="utf-8-sig") if expr_path.is_file() else ""
    readers = derive_loaders(expr_text, s)
    transformers = derive_name_transformers(expr_text, s)
    domain_settings = DomainSettings(
        rules=[dict(r) for r in (opts.get("domains") or DEFAULT_DOMAINS)],
        shared=list(SHARED_DIMENSIONS) + [str(t) for t in (opts.get("shared_tables") or [])],
        shared_label=opts.get("shared_domain_label", "Core / Shared"),
        fallback=opts.get("fallback_domain", "Other"))
    tables = [parse_table(p, readers, transformers, s, domains=domain_settings)
              for p in sorted((definition / "tables").glob("*.tmdl"))]
    default_project = target_opts.get("default_project")
    target = read_warehouse_target(
        expr_path, entry, default_project,
        target_opts.get("project_parameter", s.project_parameter),
        target_opts.get("dataset_parameter", "v-db"),
        target_opts.get("billing_parameter", "v-BQ_billing_project"))
    reads = any("bq_source" in t or t.get("unresolved_source") for t in tables)
    check_warehouse_target(source_path, target, entry, reads, default_project,
                           target_opts.get("dataset_template"), target_opts.get("key_pattern"),
                           target_opts.get("targets_name", "the targets file"))
    domains: dict[str, list[str]] = {}
    for t in tables:
        dom = t.get("domain")
        if dom is None:
            continue
        domains.setdefault(dom, []).append(t["name"])
    for t in tables:
        src = t.get("bq_source") or {}
        if src.get("table") and target.get("project") and target.get("dataset"):
            src["fqtn_default"] = f"{target['project']}.{target['dataset']}.{src['table']}"
    by_class: dict[str, int] = {}
    for t in tables:
        by_class[t["classification"]] = by_class.get(t["classification"], 0) + 1
    rels = parse_relationships(definition / "relationships.tmdl")
    name = model_dir.name[: -len(".SemanticModel")] if model_dir.name.endswith(".SemanticModel") else model_dir.name
    return {
        "model": name,
        "source_model_path": source_path,
        "generated_by": GENERATED_BY,
        target_opts.get("block_key", "bigquery"): target,
        "counts": {"tables": len(tables), "relationships": len(rels), "by_classification": by_class},
        "domains": {d: sorted(v) for d, v in sorted(domains.items())},
        "tables": tables,
        "relationships": rels,
    }


def render(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
