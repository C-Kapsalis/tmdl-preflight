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
TARGET_NOTE = ("Model parameter values must match the target contract; contract values "
               "never mask a stale model target.")


@dataclass
class SourceSettings:
    connector_tokens: list[str] = field(default_factory=lambda: ["GoogleBigQuery"])
    default_loaders: list[str] = field(default_factory=lambda: ["source_filter_dates"])
    loader_family_prefixes: list[str] = field(default_factory=lambda: ["_source_filter_rowsLimit"])
    project_parameter: str = "v-BQ_project"
    ir_marker: Optional[str] = None
    name_transform_functions: list[str] = field(
        default_factory=lambda: ["PrefixColumns", "TransformColumnNames"])


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
            out[col.replace('""', '"')] = re.sub(r"\s+", " ", typ)
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

_IR_TABLE_RE = re.compile(r'&\s*"([A-Za-z0-9_]+)"\s*&\s*"`\s*where', re.IGNORECASE)
_IR_DATE_RE = re.compile(r"cast\(\s*([A-Za-z_][\w.]*)\s+as\s+date\s*\)", re.IGNORECASE)
_NAV_RE = re.compile(r'\{\s*\[\s*Name\s*=\s*"((?:[^"]|"")+)"\s*,\s*Kind\s*=\s*"Table"\s*\]\s*\}')


def parse_inline_window(text: str, marker: Optional[str] = None) -> Optional[tuple[str, Optional[str]]]:
    """``(view, date column)`` of an inlined incremental-refresh query."""
    if "RangeStart" not in text or (marker and marker not in text):
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
    for pat in names:
        rx = re.compile(r'(?:#"(?:' + pat + r')"|(?<![\w"#.-])(?:' + pat + r'))\s*\(\s*' + lit
                        + r'(?:\s*,\s*' + lit + r')?')
        m = rx.search(text)
        if m:
            date = m.group(2).replace('""', '"') if m.group(2) else None
            return m.group(1).replace('""', '"'), date or None
    return None


def _speaks_warehouse(text: str, loaders: Iterable[str], s: SourceSettings) -> bool:
    code = code_only(text)
    if any(t in code for t in s.connector_tokens) or s.project_parameter in code:
        return True
    return any(_references(code, n) for n in loaders)


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


def parse_table(path: Path, readers: Optional[Iterable[str]] = None,
                transformers: Iterable[str] = (), settings: Optional[SourceSettings] = None,
                classes: Optional[ClassSettings] = None) -> dict:
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
        if line.startswith("\t\t") and current is not None and not line.startswith("\t\t\t"):
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
    table: dict[str, Any] = {"name": name, "classification": classify(name, classes),
                             "column_count": len(columns)}
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
        code = code_only(all_m)
        if any(f in code for f in s.name_transform_functions) or any(
                _references(code, n) for n in transformers):
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
            out.append({"name": line[len("relationship "):].strip(), "fromTable": None,
                        "fromColumn": None, "toTable": None, "toColumn": None, "isActive": True,
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
    out: dict[str, Any] = {"project": model_project, "dataset": model_dataset,
                           "billing_project": model_billing, "model_project": model_project,
                           "model_dataset": model_dataset, "model_billing_project": model_billing}
    if entry:
        out["client_id"] = entry.get("client_id")
        out["registry_project"] = entry.get("project") or default_project
        out["registry_dataset"] = entry.get("dataset")
        if entry.get("project"):
            out["project"] = entry["project"]
            out["billing_project"] = entry.get("billing_project") or entry["project"]
        if entry.get("dataset"):
            out["dataset"] = entry["dataset"]
    out["warehouse"] = ("internal" if out["project"] is None or out["project"] == default_project
                        else "external")
    out["note"] = TARGET_NOTE
    return out


def check_warehouse_target(model_rel: str, target: dict, entry: Optional[dict],
                           reads_warehouse: bool, default_project: Optional[str] = None,
                           dataset_template: Optional[str] = None,
                           key_pattern: Optional[str] = None) -> None:
    if not reads_warehouse:
        return
    if not target.get("project") or not target.get("dataset"):
        raise WarehouseTargetError(
            f"{model_rel}: could not resolve the project/dataset parameters for a model "
            f"that reads the warehouse, refusing to guess")
    if entry:
        key = entry.get("client_id")
        expected = entry.get("project") or default_project
        declared = target.get("model_project")
        if declared != expected:
            raise WarehouseTargetError(
                f"{model_rel}: the model declares project {declared or '<missing>'} but the "
                f"target contract for {key} expects {expected}; warehouse targets must match")
        if entry.get("dataset") and target.get("model_dataset") != entry["dataset"]:
            raise WarehouseTargetError(
                f"{model_rel}: the model declares dataset {target.get('model_dataset') or '<missing>'} "
                f"but the target contract for {key} expects {entry['dataset']}; dataset targets "
                f"must match")
        if dataset_template and key and not entry.get("dataset") and (
                key_pattern is None or re.fullmatch(key_pattern, key)):
            want = dataset_template.format(key=key.replace("-", "_"))
            if target.get("dataset") != want:
                raise WarehouseTargetError(
                    f"{model_rel}: dataset {target.get('dataset')} is not {want}: this model reads "
                    f"another tenant's dataset; declare the dataset in the targets file if "
                    f"intentional")


def load_targets(path: Optional[Path]) -> dict[str, dict]:
    """The targets file (YAML or JSON) as {key: entry}; missing or unreadable
    means no contract."""
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
    out = {}
    for key, entry in data.items():
        if isinstance(entry, dict):
            e = dict(entry)
            e.setdefault("client_id", key)
            out[str(key)] = e
    return out


def entry_for_model(entry: dict, model_rel: str) -> dict:
    """The contract for one model of an entry (secondary rows override)."""
    base = {k: copy.deepcopy(v) for k, v in entry.items() if k != "secondary_models"}
    norm = model_rel.replace("\\", "/").strip("/")
    for sec in entry.get("secondary_models") or []:
        if str(sec.get("path", "")).replace("\\", "/").strip("/") == norm:
            for key in ("project", "billing_project", "dataset"):
                if key in sec:
                    if sec[key] is None:
                        base.pop(key, None)
                    else:
                        base[key] = sec[key]
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
    tables = [parse_table(p, readers, transformers, s)
              for p in sorted((definition / "tables").glob("*.tmdl"))]
    default_project = target_opts.get("default_project")
    target = read_warehouse_target(
        expr_path, entry, default_project,
        target_opts.get("project_parameter", s.project_parameter),
        target_opts.get("dataset_parameter", "v-db"),
        target_opts.get("billing_parameter", "v-BQ_billing_project"))
    reads = any("bq_source" in t or t.get("unresolved_source") for t in tables)
    check_warehouse_target(source_path, target, entry, reads, default_project,
                           target_opts.get("dataset_template"), target_opts.get("key_pattern"))
    shared = set(opts.get("shared_tables") or [])
    domains_cfg = opts.get("domains") or []
    domains: dict[str, list[str]] = {}
    for t in tables:
        if t["classification"] not in DATA_CLASSES:
            continue
        if t["name"] in shared:
            dom = opts.get("shared_domain_label", "Core / Shared")
        else:
            low = t["name"].lower()
            dom = next((d["name"] for d in domains_cfg
                        if any(sub.lower() in low for sub in d.get("substrings", []))),
                       opts.get("fallback_domain", "Other"))
        t["domain"] = dom
        domains.setdefault(dom, []).append(t["name"])
        if "bq_source" in t and target.get("project") and target.get("dataset"):
            t["fqtn_default"] = f"{target['project']}.{target['dataset']}.{t['bq_source']['table']}"
    by_class: dict[str, int] = {}
    for t in tables:
        by_class[t["classification"]] = by_class.get(t["classification"], 0) + 1
    rels = parse_relationships(definition / "relationships.tmdl")
    name = model_dir.name[: -len(".SemanticModel")] if model_dir.name.endswith(".SemanticModel") else model_dir.name
    return {
        "model": name,
        "source_model_path": source_path,
        "generated_by": GENERATED_BY,
        target_opts.get("block_key", "warehouse"): target,
        "counts": {"tables": len(tables), "relationships": len(rels), "by_classification": by_class},
        "domains": {d: sorted(v) for d, v in sorted(domains.items())},
        "tables": tables,
        "relationships": rels,
    }


def render(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
