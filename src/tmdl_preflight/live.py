"""Opt-in checks against a published dataset (``tmdl-preflight live``).

Everything else in tmdl-preflight reads files. These checks ask the Power BI
service about the dataset that was built from the local model: do its tables
hold rows (a row-limit parameter left at ``LIMIT 1`` imports one row per
table), do measures evaluate, did the last refresh succeed, is the data
fresh, does a best-practice pass over the published metadata find anything.

Three clients share one interface:

* ``RestClient`` talks to the Power BI REST API with a bearer token
  (service principal from ``PBI_TENANT_ID``/``PBI_CLIENT_ID``/
  ``PBI_CLIENT_SECRET``, or an interactive sign-in when the optional
  ``msal`` package is installed);
* ``RecordingClient`` wraps it and writes every response to a folder;
* ``ReplayClient`` answers from such a folder and never touches the network.
  Queries are matched on their whitespace-normalised text.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

API = "https://api.powerbi.com/v1.0/myorg"
SCOPE = "https://analysis.windows.net/powerbi/api/.default"


class LiveError(RuntimeError):
    """A live request failed (or a replay has no recording for it)."""


class LiveUsageError(RuntimeError):
    """The live command cannot run (missing ids or credentials)."""


def normalise_query(query: str) -> str:
    q = re.sub(r"\s+", " ", query).strip()
    q = re.sub(r"\(\s+", "(", q)
    return re.sub(r"\s+\)", ")", q)


def rows_of(body: dict) -> list[dict]:
    out: list[dict] = []
    for result in body.get("results") or []:
        for table in result.get("tables") or []:
            out.extend(table.get("rows") or [])
    return out


def scalar(row: Optional[dict], name: str) -> Any:
    if not row:
        return None
    return row.get(f"[{name}]", row.get(name))


def count(row: Optional[dict], name: str) -> int:
    value = scalar(row, name)
    try:
        return int(value) if value else 0
    except (TypeError, ValueError):
        return 0


@dataclass
class QueryResult:
    rows: list[dict]
    elapsed_ms: float
    timestamp: str
    error: Optional[str] = None

    @property
    def first(self) -> Optional[dict]:
        return self.rows[0] if self.rows else None


def quote_table(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------


class _Client:
    def execute(self, query: str) -> QueryResult:  # pragma: no cover - interface
        raise NotImplementedError

    def refreshes(self, top: int = 10) -> list[dict]:  # pragma: no cover
        raise NotImplementedError

    def datasources(self) -> list[dict]:  # pragma: no cover
        raise NotImplementedError

    def dataset(self) -> dict:  # pragma: no cover
        raise NotImplementedError

    def now(self) -> _dt.datetime:
        return _dt.datetime.now(_dt.timezone.utc)

    def health_check(self) -> dict:
        try:
            self.dataset()
            result = self.execute("EVALUATE { 1 }")
            if result.error:
                raise LiveError(result.error)
            return {"status": "healthy"}
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            return {"status": "unhealthy", "error": str(exc)}


class ReplayClient(_Client):
    """Answers from recorded responses in ``folder``."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._queries: dict[str, dict] = {}
        for entry in self._load("queries.json", []):
            self._queries[normalise_query(entry.get("query", ""))] = entry.get("response") or {}

    def _load(self, name: str, default: Any) -> Any:
        path = self.folder / name
        if not path.is_file():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def execute(self, query: str) -> QueryResult:
        start = time.perf_counter()
        key = normalise_query(query)
        stamp = self.now().isoformat()
        if key not in self._queries:
            return QueryResult([], 0.0, stamp, f"no recorded response for query: {key}")
        body = self._queries[key]
        ms = (time.perf_counter() - start) * 1000
        if "error" in body:
            return QueryResult([], ms, stamp, str(body["error"]))
        return QueryResult(rows_of(body), ms, stamp)

    def refreshes(self, top: int = 10) -> list[dict]:
        data = self._load("refreshes.json", [])
        return list(data)[:top] if isinstance(data, list) else []

    def datasources(self) -> list[dict]:
        data = self._load("datasources.json", [])
        return data if isinstance(data, list) else []

    def dataset(self) -> dict:
        return self._load("dataset.json", {})

    def now(self) -> _dt.datetime:
        clock = self._load("clock.json", {})
        if clock.get("now"):
            return _parse_time(clock["now"])
        return super().now()


class RestClient(_Client):
    """Power BI REST client (group-scoped dataset)."""

    def __init__(self, workspace: str, dataset: str, token: Callable[[], str],
                 cache_ttl: float = 300.0):
        self.workspace, self.dataset_id, self._token = workspace, dataset, token
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, Any]] = {}

    def _url(self, tail: str) -> str:
        return f"{API}/groups/{self.workspace}/datasets/{self.dataset_id}{tail}"

    def _request(self, method: str, url: str, body: Optional[dict] = None) -> Any:
        import urllib.error
        import urllib.request

        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - fixed https host
            raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}

    def _cached(self, key: str, fn: Callable[[], Any]) -> Any:
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.cache_ttl:
            return hit[1]
        value = fn()
        self._cache[key] = (time.monotonic(), value)
        return value

    def execute(self, query: str) -> QueryResult:
        import urllib.error

        stamp = self.now().isoformat()
        start = time.perf_counter()
        last = None
        for attempt in range(3):
            try:
                body = self._request("POST", self._url("/executeQueries"),
                                     {"queries": [{"query": query}],
                                      "serializerSettings": {"includeNulls": True}})
                return QueryResult(rows_of(body), (time.perf_counter() - start) * 1000, stamp)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                return QueryResult([], (time.perf_counter() - start) * 1000, stamp,
                                   f"HTTP {exc.code}: {detail}")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = exc
                time.sleep(min(2 ** (attempt + 1), 10))
        return QueryResult([], (time.perf_counter() - start) * 1000, stamp, f"request failed: {last}")

    def refreshes(self, top: int = 10) -> list[dict]:
        try:
            return self._cached(f"refreshes:{top}", lambda: self._request(
                "GET", self._url(f"/refreshes?$top={top}")).get("value", []))
        except Exception:  # noqa: BLE001 - the history is best effort
            return []

    def datasources(self) -> list[dict]:
        try:
            return self._cached("datasources", lambda: self._request(
                "GET", self._url("/datasources")).get("value", []))
        except Exception:  # noqa: BLE001
            return []

    def dataset(self) -> dict:
        def load() -> dict:
            data = self._request("GET", self._url(""))
            try:
                group = self._request("GET", f"{API}/groups?$filter=id eq '{self.workspace}'")
                ws = (group.get("value") or [{}])[0]
            except Exception:  # noqa: BLE001
                ws = {}
            keys = ("id", "name", "configuredBy", "isRefreshable", "targetStorageMode")
            out = {k: data.get(k) for k in keys}
            out.update({"workspaceId": self.workspace, "workspaceName": ws.get("name")})
            return out
        return self._cached("dataset", load)


class RecordingClient(_Client):
    """Passes calls to ``inner`` and records every answer under ``folder``."""

    def __init__(self, inner: _Client, folder: Path):
        self.inner, self.folder = inner, Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._queries: list[dict] = []

    def _write(self, name: str, data: Any) -> None:
        (self.folder / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def execute(self, query: str) -> QueryResult:
        result = self.inner.execute(query)
        response = ({"error": result.error} if result.error
                    else {"results": [{"tables": [{"rows": result.rows}]}]})
        self._queries.append({"query": normalise_query(query), "response": response})
        self._write("queries.json", self._queries)
        return result

    def refreshes(self, top: int = 10) -> list[dict]:
        data = self.inner.refreshes(top)
        self._write("refreshes.json", data)
        return data

    def datasources(self) -> list[dict]:
        data = self.inner.datasources()
        self._write("datasources.json", data)
        return data

    def dataset(self) -> dict:
        data = self.inner.dataset()
        self._write("dataset.json", data)
        return data

    def now(self) -> _dt.datetime:
        now = self.inner.now()
        self._write("clock.json", {"now": now.isoformat().replace("+00:00", "Z")})
        return now


def token_provider(interactive: bool = True) -> Callable[[], str]:
    """Bearer tokens: service principal from the environment, else an
    interactive sign-in (needs the optional ``msal`` package). Tokens are
    kept in memory only and renewed when less than 5 minutes remain."""
    tenant, client, secret = (os.environ.get(k) for k in
                              ("PBI_TENANT_ID", "PBI_CLIENT_ID", "PBI_CLIENT_SECRET"))
    state: dict[str, Any] = {"token": None, "expires": 0.0}
    if tenant and client and secret:
        def fetch() -> tuple[str, float]:
            import urllib.parse
            import urllib.request

            body = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": client,
                                           "client_secret": secret, "scope": SCOPE}).encode()
            url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
            last = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(url, data=body, timeout=60) as resp:  # noqa: S310
                        data = json.loads(resp.read().decode("utf-8"))
                    return data["access_token"], time.time() + float(data.get("expires_in", 3600))
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    time.sleep(min(2 * 2 ** attempt, 10))
            raise LiveError(f"could not obtain a token: {last}")
    elif interactive:
        try:
            import msal  # type: ignore[import-not-found]
        except ImportError:
            raise LiveUsageError(
                "no credentials: set PBI_TENANT_ID, PBI_CLIENT_ID and PBI_CLIENT_SECRET for a "
                "service principal, or install msal for an interactive sign-in") from None
        app = msal.PublicClientApplication("04b07795-8ddb-461a-bbee-02f9e1bf7b46",
                                           authority="https://login.microsoftonline.com/organizations")

        def fetch() -> tuple[str, float]:
            result = app.acquire_token_interactive(scopes=[SCOPE])
            if "access_token" not in result:
                raise LiveError(f"sign-in failed: {result.get('error_description')}")
            return result["access_token"], time.time() + float(result.get("expires_in", 3600))
    else:
        raise LiveUsageError(
            "no credentials: set PBI_TENANT_ID, PBI_CLIENT_ID and PBI_CLIENT_SECRET "
            "(--non-interactive allows no sign-in prompt)")

    def token() -> str:
        if state["token"] is None or state["expires"] - time.time() < 300:
            state["token"], state["expires"] = fetch()
        return state["token"]

    return token


# ---------------------------------------------------------------------------
# Local model facts the checks need
# ---------------------------------------------------------------------------


@dataclass
class LocalModel:
    path: Path
    tables_with_columns: list[str]
    tables: list[str]
    measures: list[tuple[str, str]]
    parameters: Optional[dict[str, str]]  # None: no expressions.tmdl


def read_local_model(model_dir: Path) -> LocalModel:
    tables_dir = Path(model_dir) / "definition" / "tables"
    with_cols, names, measures = [], [], []
    for f in sorted(tables_dir.glob("*.tmdl")) if tables_dir.is_dir() else []:
        text = f.read_text(encoding="utf-8-sig")
        names.append(f.stem)
        if re.search(r"(?m)^\tcolumn ", text):
            with_cols.append(f.stem)
        for m in re.finditer(r"(?m)^\tmeasure\s+('(?:[^']|'')+'|[^\s=]+)", text):
            name = m.group(1)
            if name.startswith("'"):
                name = name[1:-1].replace("''", "'")
            measures.append((f.stem, name))
    expr = Path(model_dir) / "definition" / "expressions.tmdl"
    params = None
    if expr.is_file():
        params = {}
        for line in expr.read_text(encoding="utf-8-sig").splitlines():
            m = re.match(r"^expression\s+(v-[^\s=]+)\s*=\s*(.*?)(?:\s+meta\b.*)?$", line)
            if m:
                params[m.group(1)] = m.group(2).strip()
    return LocalModel(Path(model_dir), sorted(with_cols), sorted(names),
                      sorted(measures), params)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    "calendar_table": "__Calendar",
    "date_column": "Date",
    "dimension_prefix": "_",
    "probe_tables": None,
    "dimension_probe_tables": ["_Accounts", "_Campaigns", "_Conversions", "_Devices", "_Countries"],
    "filter_probe_tables": None,
    "uniform_limits": [100, 1000, 10000],
    "sample_tables": 10,
    "sample_pass_rate": 0.6,
    "dimension_pass_rate": 0.7,
    "sample_measures": 20,
    "measure_pass_rate": 0.2,
    "parameter_table_measures": False,
    "parameter_table_prefixes": ["x-Selector", "x-Plot Specific"],
    "suite_measures": 50,
    "suite_pass_rate": 0.8,
    "freshness_max_hours": 24,
    "parameter_prefix": "v-",
    "row_limit_parameter": "v-rows_limit",
    "from_date_parameter": "v-fromdate",
    "bpa": {"user_facing_prefix": "!", "max_duration_ms": 30000},
}


@dataclass
class CheckResult:
    id: str
    outcome: str  # pass | warn | fail | skip | error
    message: str
    details: dict = field(default_factory=dict)


class LiveContext:
    def __init__(self, client: _Client, model: LocalModel, options: Optional[dict] = None):
        self.client, self.model = client, model
        self.cfg = {**DEFAULTS, **(options or {})}
        cal = self.cfg["calendar_table"]
        if self.cfg["probe_tables"] is None:
            self.cfg["probe_tables"] = [cal, "_Accounts", "_Campaigns", "_Conversions", "_Devices"]
        if self.cfg["filter_probe_tables"] is None:
            self.cfg["filter_probe_tables"] = ["_Accounts", "_Campaigns", "_Conversions", cal, "Ads"]

    def table_count(self, table: str, label: str = "Count") -> tuple[Optional[int], Optional[str]]:
        r = self.client.execute(f'EVALUATE ROW("{label}", COUNTROWS({quote_table(table)}))')
        if r.error:
            return None, r.error
        return count(r.first, label), None


def _rate(passed: int, probed: int) -> float:
    return passed / probed if probed else 0.0


def check_uniform_row_limit(c: LiveContext) -> CheckResult:
    counts = {t: c.table_count(t)[0] for t in c.cfg["probe_tables"]}
    known = [v for v in counts.values() if v is not None]
    details = {"counts": counts}
    if not known:
        return CheckResult("live-uniform-row-limit", "warn",
                           "could not retrieve any row counts", details)
    if set(known) == {1}:
        return CheckResult("live-uniform-row-limit", "fail",
                           "every table has exactly one row; a LIMIT 1 parameter is set", details)
    if len(set(known)) == 1 and known[0] in c.cfg["uniform_limits"]:
        return CheckResult("live-uniform-row-limit", "warn",
                           f"uniform limit {known[0]}; acceptable for testing, not production",
                           details)
    details.update({"min": min(known), "max": max(known)})
    return CheckResult("live-uniform-row-limit", "pass",
                       f"row counts vary ({min(known)} to {max(known)})", details)


def _calendar_query(c: LiveContext, order: str) -> str:
    cal, col = quote_table(c.cfg["calendar_table"]), c.cfg["date_column"]
    parts = {"RowCount": f'"RowCount", COUNTROWS({cal})',
             "MinDate": f'"MinDate", MIN({cal}[{col}])',
             "MaxDate": f'"MaxDate", MAX({cal}[{col}])'}
    keys = ["RowCount", "MinDate", "MaxDate"] if order == "count-first" else ["MinDate", "MaxDate", "RowCount"]
    return "EVALUATE ROW( " + ", ".join(parts[k] for k in keys) + " )"


def check_calendar_rows(c: LiveContext) -> CheckResult:
    r = c.client.execute(_calendar_query(c, "count-first"))
    cid = "live-calendar-rows"
    if r.error:
        return CheckResult(cid, "error", f"calendar query failed: {r.error}")
    n = count(r.first, "RowCount")
    details = {"row_count": n, "min_date": scalar(r.first, "MinDate"),
               "max_date": scalar(r.first, "MaxDate")}
    if n == 1:
        return CheckResult(cid, "fail", "the calendar holds one row; a row limit or filter is "
                                        "applied", details)
    if n < 100:
        return CheckResult(cid, "warn", f"the calendar holds only {n} rows", details)
    if n < 365:
        return CheckResult(cid, "pass", f"{n} calendar rows: less than one year", details)
    return CheckResult(cid, "pass", f"{n} calendar rows", details)


def check_dimension_multirow(c: LiveContext) -> CheckResult:
    tables = list(c.cfg["dimension_probe_tables"])
    counts = {t: c.table_count(t)[0] for t in tables}
    single = [t for t, v in counts.items() if v == 1]
    details = {"counts": counts, "single_row_tables": single}
    cid = "live-dimension-multirow"
    if not any(v is not None and v > 1 for v in counts.values()):
        return CheckResult(cid, "fail", "no dimension table holds more than one row", details)
    if len(single) > len(tables) // 2:
        return CheckResult(cid, "warn", f"{len(single)} of {len(tables)} dimension tables hold "
                                        f"one row: {', '.join(single)}", details)
    return CheckResult(cid, "pass", "dimension tables hold several rows", details)


def check_calendar_scan(c: LiveContext) -> CheckResult:
    cid, cal = "live-calendar-scan", c.cfg["calendar_table"]
    r = c.client.execute(f'EVALUATE ROW("RowCount", COUNTROWS({quote_table(cal)}))')
    if r.error:
        return CheckResult(cid, "error", f"calendar count failed: {r.error}")
    raw = scalar(r.first, "RowCount")
    if raw is None:
        return CheckResult(cid, "error", "the calendar count came back BLANK")
    n = int(raw)
    top = c.client.execute(f"EVALUATE TOPN(50, {quote_table(cal)})")
    rows = top.rows if not top.error else []
    date_key = next((k for k in (rows[0] if rows else {}) if "date" in k.lower()), None)
    samples = [row.get(date_key) for row in rows[:5]] if date_key else []
    details = {"row_count": n, "returned_rows": len(rows), "sample_values": samples}
    if top.error:
        details["topn_error"] = top.error
    if n == 1:
        return CheckResult(cid, "fail", "the calendar should hold 365+ rows but holds one; "
                                        "row-level security, a filter or a row limit is "
                                        "restricting data", details)
    if n < 100:
        return CheckResult(cid, "pass", f"warning: the calendar holds only {n} rows", details)
    return CheckResult(cid, "pass", f"{n} calendar rows", details)


def _date_param(value: Optional[str]) -> Optional[str]:
    m = re.search(r"#date\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", value or "")
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def check_calendar_vs_parameters(c: LiveContext) -> CheckResult:
    cid, params = "live-calendar-vs-parameters", c.model.parameters
    if params is None:
        return CheckResult(cid, "skip", "no expressions.tmdl: the model declares no parameters")
    r = c.client.execute(_calendar_query(c, "dates-first"))
    if r.error:
        return CheckResult(cid, "error", f"calendar query failed: {r.error}")
    n = count(r.first, "RowCount")
    details = {
        "v-fromdate": _date_param(params.get(c.cfg["from_date_parameter"])),
        "v-isRolling": params.get("v-isRolling", "0"),
        "v-daysAgo": params.get("v-daysAgo", "90"),
        "min_date": scalar(r.first, "MinDate"), "max_date": scalar(r.first, "MaxDate"),
        "row_count": n,
    }
    if n == 1:
        return CheckResult(cid, "warn", "the calendar holds one row: cannot validate the range; "
                                        "a row limit is applied", details)
    return CheckResult(cid, "pass", f"calendar {details['min_date']} to {details['max_date']} "
                                    f"({n} rows)", details)


def check_parameter_audit(c: LiveContext) -> CheckResult:
    cid, params = "live-parameter-audit", c.model.parameters
    if params is None:
        return CheckResult(cid, "skip", "no expressions.tmdl: the model declares no parameters")
    time_params = sorted(n for n in params if any(k in n for k in
                                                  ("date", "Rolling", "rows_limit", "daysAgo")))
    issues, recs = [], []
    limit = params.get(c.cfg["row_limit_parameter"], "")
    if re.search(r"\bLIMIT\s+1\b", limit):
        issues.append({"severity": "CRITICAL", "parameter": c.cfg["row_limit_parameter"],
                       "issue": "only one row per table is imported"})
        recs.append(f"set {c.cfg['row_limit_parameter']} to a blank string and refresh")
    elif "LIMIT" in limit:
        issues.append({"severity": "WARNING", "parameter": c.cfg["row_limit_parameter"],
                       "issue": f"a row limit is set ({limit})"})
    start = _date_param(params.get(c.cfg["from_date_parameter"]))
    today = c.client.now().date()
    if start and _dt.date.fromisoformat(start) > today:
        ahead = (_dt.date.fromisoformat(start) - today).days
        issues.append({"severity": "CRITICAL", "parameter": c.cfg["from_date_parameter"],
                       "issue": f"the start date is {ahead} days in the future"})
        recs.append(f"set {c.cfg['from_date_parameter']} to a date in the past")
    cal = c.cfg["calendar_table"]
    r = c.client.execute(f'EVALUATE ROW( "CalendarRows", COUNTROWS({quote_table(cal)}), '
                         f'"AccountsRows", COUNTROWS({quote_table("_Accounts")}) )')
    sample, notes = {}, []
    if r.error:
        notes.append(f"live sample failed: {r.error}")
    else:
        sample = {cal: count(r.first, "CalendarRows"), "_Accounts": count(r.first, "AccountsRows")}
        if sample[cal] == 1 and sample["_Accounts"] == 1:
            notes.append("both sampled tables hold one row: a row limit is applied")
        elif sample[cal] < 100:
            notes.append("the calendar holds fewer than 100 rows")
    details = {"time_parameters": time_params, "parameters": params, "issues": issues,
               "live_sample": sample, "notes": notes, "recommendations": recs}
    return CheckResult(cid, "pass", f"{len(issues)} parameter issue(s)", details)


def _row_probe(c: LiveContext, table: str) -> tuple[bool, str]:
    n, err = c.table_count(table, "RowCount")
    if err:
        return False, err
    return (n or 0) > 0, f"{n} rows"


def check_table_sample(c: LiveContext) -> CheckResult:
    tables = c.model.tables_with_columns[: c.cfg["sample_tables"]]
    results = {t: _row_probe(c, t) for t in tables}
    passed = sum(1 for ok, _ in results.values() if ok)
    details = {"tables": tables, "probed": len(tables), "passed": passed,
               "empty_tables": [t for t, (ok, _) in results.items() if not ok]}
    ok = _rate(passed, len(tables)) >= c.cfg["sample_pass_rate"]
    return CheckResult("live-table-sample", "pass" if ok else "fail",
                       f"{passed} of {len(tables)} sampled tables hold rows", details)


def check_dimension_rows(c: LiveContext) -> CheckResult:
    prefix = c.cfg["dimension_prefix"]
    tables = [t for t in c.model.tables_with_columns if t.startswith(prefix)]
    if not tables:
        return CheckResult("live-dimension-rows", "fail", "no dimension tables found")
    results = {t: _row_probe(c, t) for t in tables}
    passed = sum(1 for ok, _ in results.values() if ok)
    details = {"tables": tables, "probed": len(tables), "passed": passed,
               "empty_tables": [t for t, (ok, _) in results.items() if not ok]}
    ok = _rate(passed, len(tables)) >= c.cfg["dimension_pass_rate"]
    return CheckResult("live-dimension-rows", "pass" if ok else "fail",
                       f"{passed} of {len(tables)} dimension tables hold rows", details)


def _measure_probe(c: LiveContext, measure: str) -> tuple[bool, str]:
    ref = "[" + measure.replace("]", "]]") + "]"
    r = c.client.execute(f'EVALUATE ROW( "Value", {ref}, "IsBlank", ISBLANK({ref}) )')
    if r.error:
        return False, r.error
    if not r.rows:
        return False, "empty result"
    blank = scalar(r.first, "IsBlank")
    return (blank is False), "value" if blank is False else "BLANK"


def _measure_sample(c: LiveContext, cid: str, measures: list[str], none_message: str) -> CheckResult:
    if not measures:
        return CheckResult(cid, "fail", none_message, {"probed": 0, "passed": 0})
    results = {m: _measure_probe(c, m) for m in measures}
    passed = sum(1 for ok, _ in results.values() if ok)
    rate = _rate(passed, len(measures))
    details: dict = {"probed": len(measures), "passed": passed,
                     "blank_or_failed": [m for m, (ok, _) in results.items() if not ok]}
    if rate < 0.5:
        details["note"] = "fewer than half of the sampled measures return a value"
    ok = rate >= c.cfg["measure_pass_rate"]
    return CheckResult(cid, "pass" if ok else "fail",
                       f"{passed} of {len(measures)} sampled measures return a value", details)


def check_measure_sample(c: LiveContext) -> CheckResult:
    measures = [m for _t, m in c.model.measures][: c.cfg["sample_measures"]]
    return _measure_sample(c, "live-measure-sample", measures, "the model declares no measures")


def check_parameter_table_measures(c: LiveContext) -> CheckResult:
    cid = "live-parameter-table-measures"
    if not c.cfg["parameter_table_measures"]:
        return CheckResult(cid, "skip", "disabled (live.parameter_table_measures = false): "
                                        "field-parameter tables normally own no measures")
    prefixes = tuple(c.cfg["parameter_table_prefixes"])
    per_table: dict[str, list[str]] = {}
    for t, m in c.model.measures:
        if t.startswith(prefixes):
            per_table.setdefault(t, []).append(m)
    measures = [m for ms in per_table.values() for m in ms[:5]]
    return _measure_sample(c, cid, measures, "no parameter measure tables with measures found")


def _refresh_probe(c: LiveContext) -> tuple[str, str, dict]:
    hist = c.client.refreshes(1)
    if not hist:
        return "warn", "no refresh history found", {}
    latest = hist[0]
    status = latest.get("status") or "Unknown"
    details = {"status": status, "endTime": latest.get("endTime"), "requestId": latest.get("requestId")}
    if status == "Completed":
        return "pass", f"last refresh Completed at {latest.get('endTime')}", details
    return "warn", f"last refresh status: {status}", details


def check_refresh_status(c: LiveContext) -> CheckResult:
    outcome, msg, details = _refresh_probe(c)
    return CheckResult("live-refresh-status", outcome, msg, details)


def _parse_time(text: str) -> _dt.datetime:
    value = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)


def _freshness_probe(c: LiveContext) -> tuple[str, str, dict]:
    hist = c.client.refreshes(10)
    if not hist:
        return "warn", "no refresh history found", {}
    done = next((h for h in hist if h.get("status") == "Completed"), None)
    if done is None:
        return "warn", "no successful refresh found", {}
    try:
        age = (c.client.now() - _parse_time(str(done.get("endTime")))).total_seconds() / 3600
    except (TypeError, ValueError) as exc:
        return "warn", f"cannot read the refresh end time: {exc}", {}
    details = {"age_hours": round(age, 3), "endTime": done.get("endTime")}
    if age <= c.cfg["freshness_max_hours"]:
        return "pass", f"data is {age:.1f} hours old", details
    return "warn", f"data is {age:.0f} hours old (limit {c.cfg['freshness_max_hours']})", details


def check_freshness(c: LiveContext) -> CheckResult:
    outcome, msg, details = _freshness_probe(c)
    return CheckResult("live-freshness", outcome, msg, details)


def check_smoke(c: LiveContext) -> CheckResult:
    start = time.perf_counter()
    items: list[tuple[str, bool, str]] = []
    prefix = c.cfg["dimension_prefix"]
    for t in [t for t in c.model.tables_with_columns if t.startswith(prefix)]:
        ok, why = _row_probe(c, t)
        items.append((f"rows: {t}", ok, why))
    for _t, m in c.model.measures[: c.cfg["suite_measures"]]:
        ok, why = _measure_probe(c, m)
        items.append((f"measure: {m}", ok, why))
    outcome, msg, _d = _refresh_probe(c)
    items.append(("refresh status", outcome == "pass", msg))
    outcome, msg, _d = _freshness_probe(c)
    items.append(("freshness", outcome == "pass", msg))
    passed = sum(1 for _n, ok, _w in items if ok)
    details = {"passed": passed, "total": len(items),
               "failed_items": [f"{n}: {w}" for n, ok, w in items if not ok],
               "elapsed_ms": round((time.perf_counter() - start) * 1000, 3)}
    ok = _rate(passed, len(items)) >= c.cfg["suite_pass_rate"]
    return CheckResult("live-smoke", "pass" if ok else "fail",
                       f"{passed} of {len(items)} smoke items passed", details)


def check_identity(c: LiveContext) -> CheckResult:
    r = c.client.execute('EVALUATE ROW( "UserPrincipalName", USERPRINCIPALNAME(), '
                         '"UserName", USERNAME(), "UserObjectId", USEROBJECTID() )')
    if r.error:
        return CheckResult("live-identity", "error", f"identity query failed: {r.error}")
    ds = c.client.dataset()
    details = {"user_principal_name": scalar(r.first, "UserPrincipalName"),
               "user_name": scalar(r.first, "UserName"),
               "user_object_id": scalar(r.first, "UserObjectId"),
               "dataset_name": ds.get("name"), "is_refreshable": ds.get("isRefreshable"),
               "storage_mode": ds.get("targetStorageMode"),
               "note": "role membership cannot be read without admin rights"}
    return CheckResult("live-identity", "pass",
                       f"querying as {details['user_principal_name']}", details)


def check_filter_compare(c: LiveContext) -> CheckResult:
    rows, flagged = [], []
    for t in c.cfg["filter_probe_tables"]:
        n, err = c.table_count(t, "RowCount")
        if err:
            return CheckResult("live-filter-compare", "error", f"COUNTROWS({t}) failed: {err}")
        entry: dict[str, Any] = {"table": t, "countrows": n}
        top = c.client.execute(f"EVALUATE TOPN(10, {quote_table(t)})")
        entry["topn_rows"] = None if top.error else len(top.rows)
        if top.error:
            entry["topn_error"] = top.error
        tot = c.client.execute(f'EVALUATE ROW( "TotalRows", CALCULATE(COUNTROWS({quote_table(t)}), '
                               f'ALL({quote_table(t)})) )')
        entry["countrows_all"] = None if tot.error else count(tot.first, "TotalRows")
        if tot.error:
            entry["all_error"] = tot.error
        if entry["countrows_all"] is not None and entry["countrows_all"] != n:
            entry["note"] = "filter context or RLS detected"
            flagged.append(t)
        rows.append(entry)
    return CheckResult("live-filter-compare", "pass",
                       f"{len(flagged)} table(s) count differently with ALL()",
                       {"tables": rows, "flagged": flagged})


def check_metadata(c: LiveContext) -> CheckResult:
    refreshes = [{k: r.get(k) for k in ("status", "endTime", "requestId")} for r in c.client.refreshes(5)]
    details = {"dataset": c.client.dataset(), "refreshes": refreshes,
               "datasources": c.client.datasources()}
    return CheckResult("live-metadata", "pass", "dataset metadata collected", details)


def check_filter_diagnostic(c: LiveContext) -> CheckResult:
    findings: list[dict] = []
    who = c.client.execute('EVALUATE ROW("User", USERPRINCIPALNAME())')
    if who.error:
        findings.append({"level": "ERROR", "item": "identity", "message": who.error})
    else:
        findings.append({"level": "INFO", "item": "identity",
                         "message": f"querying as {scalar(who.first, 'User')}"})
    cal = c.cfg["calendar_table"]
    r = c.client.execute(f'EVALUATE ROW("Count", COUNTROWS({quote_table(cal)}))')
    raw = None if r.error else scalar(r.first, "Count")
    if r.error or raw is None:
        findings.append({"level": "ERROR", "item": "calendar",
                         "message": r.error or "the calendar count came back BLANK"})
    else:
        n = int(raw)
        level = "CRITICAL" if n == 1 else ("WARNING" if n < 100 else "OK")
        findings.append({"level": level, "item": "calendar", "message": f"{n} calendar rows"})
    dims = [t for t in c.cfg["filter_probe_tables"] if t.startswith(c.cfg["dimension_prefix"])
            and t != cal]
    if dims:
        d = quote_table(dims[0])
        cmp_ = c.client.execute(f'EVALUATE ROW( "Normal", COUNTROWS({d}), '
                                f'"WithALL", CALCULATE(COUNTROWS({d}), ALL({d})) )')
        if cmp_.error:
            findings.append({"level": "ERROR", "item": dims[0], "message": cmp_.error})
        else:
            a, b = count(cmp_.first, "Normal"), count(cmp_.first, "WithALL")
            findings.append({"level": "WARNING" if a != b else "OK", "item": dims[0],
                             "message": f"{a} rows, {b} with ALL()"})
    hist = c.client.refreshes(1)
    if not hist:
        findings.append({"level": "INFO", "item": "refresh", "message": "no refresh history"})
    else:
        status = hist[0].get("status") or "Unknown"
        findings.append({"level": "OK" if status == "Completed" else "WARNING", "item": "refresh",
                         "message": f"last refresh {status}"})
    recs = []
    if any(f["level"] in ("CRITICAL", "WARNING", "ERROR") for f in findings):
        recs = ["check the RLS roles and the account the query runs as",
                "check the service principal's access to the workspace",
                "check calculation groups and model-level filters"]
    critical = any(f["level"] == "CRITICAL" for f in findings)
    return CheckResult("live-filter-diagnostic", "fail" if critical else "pass",
                       f"{len(findings)} diagnostic finding(s)",
                       {"findings": findings, "recommendations": recs})


# ---------------------------------------------------------------------------
# Best-practice analysis over the published metadata
# ---------------------------------------------------------------------------

BPA_RULES = [
    {"id": "DAX_DIVISION_USAGE", "name": "Use DIVIDE instead of /", "category": "DAX Expressions",
     "severity": 3, "fix": "Use DIVIDE(numerator, denominator) so a zero denominator returns BLANK."},
    {"id": "PERF_CALCULATED_COLUMNS", "name": "Calculated columns", "category": "Performance",
     "severity": 2, "fix": "Move the column logic to Power Query or into a measure."},
    {"id": "NAME_MEASURE_DESCRIPTIONS", "name": "User-facing measures have descriptions",
     "category": "Naming Conventions", "severity": 2, "fix": "Add a description."},
    {"id": "DAX_FULLY_QUALIFIED_COLUMNS", "name": "Fully qualified column references",
     "category": "DAX Expressions", "severity": 2, "fix": "Write Table[Column]."},
    {"id": "META_HIDDEN_FOREIGN_KEYS", "name": "Hide foreign keys", "category": "Metadata",
     "severity": 2, "fix": "Hide key columns used only by relationships."},
]


@dataclass
class BPAViolation:
    rule_id: str
    rule_name: str
    category: str
    severity: int
    object_name: str
    object_type: str
    message: str
    fix_suggestion: str
    timestamp: str


@dataclass
class BPAReport:
    violations: list[BPAViolation]
    total_objects_analyzed: int
    analysis_duration_ms: float
    timestamp: _dt.datetime

    def _count(self, test) -> int:
        return sum(1 for v in self.violations if test(v.severity))

    @property
    def critical_count(self) -> int:
        return self._count(lambda s: s >= 4)

    @property
    def error_count(self) -> int:
        return self._count(lambda s: s == 3)

    @property
    def warning_count(self) -> int:
        return self._count(lambda s: s == 2)

    @property
    def info_count(self) -> int:
        return self._count(lambda s: s <= 1)

    def get_violations_by_severity(self, minimum: int) -> list[BPAViolation]:
        return [v for v in self.violations if v.severity >= minimum]

    def export_report_json(self) -> str:
        return json.dumps({
            "summary": {"total_violations": len(self.violations),
                        "critical_count": self.critical_count, "error_count": self.error_count,
                        "warning_count": self.warning_count, "info_count": self.info_count,
                        "total_objects_analyzed": self.total_objects_analyzed,
                        "analysis_duration_ms": self.analysis_duration_ms,
                        "timestamp": self.timestamp.isoformat()},
            "violations": [asdict(v) for v in self.violations],
        }, indent=2)


class LiveBPA:
    def __init__(self, client: _Client, options: Optional[dict] = None):
        self.client = client
        self.options = {**DEFAULTS["bpa"], **(options or {})}
        self.rules = [dict(r) for r in BPA_RULES]

    def _rule(self, rid: str) -> dict:
        return next(r for r in self.rules if r["id"] == rid)

    def _violation(self, rid: str, obj: str, otype: str, message: str) -> BPAViolation:
        r = self._rule(rid) if rid != "BPA_ANALYSIS_FAILED" else {
            "id": rid, "name": "Analysis failed", "category": "System", "severity": 5,
            "fix": "Check the connection and permissions."}
        return BPAViolation(rid, r["name"], r["category"], r["severity"], obj, otype, message,
                            r["fix"], _dt.datetime.now(_dt.timezone.utc).isoformat())

    def analyze_model(self) -> BPAReport:
        start = time.perf_counter()
        out: list[BPAViolation] = []
        objects = 0
        try:
            m = self.client.execute('EVALUATE ADDCOLUMNS( INFO.MEASURES(), "HasDivision", '
                                    'SEARCH("/", [Expression], 1, 0) > 0, "HasDIVIDE", '
                                    'SEARCH("DIVIDE", [Expression], 1, 0) > 0 )')
            for row in [] if m.error else m.rows:
                expr = str(scalar(row, "Expression") or "")
                if "/" in expr and "divide" not in expr.lower():
                    name = str(scalar(row, "Name"))
                    out.append(self._violation("DAX_DIVISION_USAGE", name, "Measure",
                                               f"{name} divides with '/'; use DIVIDE"))
            cols = self.client.execute("EVALUATE FILTER( INFO.COLUMNS(), [Type] = 2 )")
            for row in [] if cols.error else cols.rows:
                table = scalar(row, "TableName") or scalar(row, "TableID")
                obj = f"{table}[{scalar(row, 'Name')}]"
                out.append(self._violation("PERF_CALCULATED_COLUMNS", obj, "Column",
                                           f"{obj} is a calculated column"))
            desc = self.client.execute('EVALUATE FILTER( INFO.MEASURES(), ISBLANK([Description]) '
                                       '|| [Description] = "" )')
            prefix = self.options["user_facing_prefix"]
            for row in [] if desc.error else desc.rows:
                name = str(scalar(row, "Name"))
                if name.startswith(prefix):
                    out.append(self._violation("NAME_MEASURE_DESCRIPTIONS", name, "Measure",
                                               f"user-facing measure {name} has no description"))
            mc = self.client.execute('EVALUATE ROW("MeasureCount", COUNTROWS(INFO.MEASURES()))')
            cc = self.client.execute('EVALUATE ROW("ColumnCount", COUNTROWS(INFO.COLUMNS()))')
            objects = (0 if mc.error else count(mc.first, "MeasureCount")) + \
                      (0 if cc.error else count(cc.first, "ColumnCount"))
        except Exception as exc:  # noqa: BLE001 - one system finding instead of a crash
            out.append(self._violation("BPA_ANALYSIS_FAILED", "model", "Model", str(exc)))
        ms = max((time.perf_counter() - start) * 1000, 0.001)
        return BPAReport(out, objects, ms, _dt.datetime.now(_dt.timezone.utc))


def check_bpa(c: LiveContext) -> CheckResult:
    report = LiveBPA(c.client, c.cfg.get("bpa")).analyze_model()
    cats: dict[str, int] = {}
    for v in report.violations:
        cats[v.category] = cats.get(v.category, 0) + 1
    details = {"by_category": cats, "objects": report.total_objects_analyzed,
               "duration_ms": report.analysis_duration_ms,
               "violations": [asdict(v) for v in report.violations]}
    if report.critical_count:
        return CheckResult("live-bpa", "fail", f"{report.critical_count} critical finding(s)", details)
    if report.total_objects_analyzed == 0:
        return CheckResult("live-bpa", "fail", "no objects could be analysed", details)
    if report.analysis_duration_ms >= (c.cfg.get("bpa") or {}).get("max_duration_ms", 30000):
        return CheckResult("live-bpa", "fail", "the analysis took too long", details)
    return CheckResult("live-bpa", "pass", f"{len(report.violations)} finding(s), none critical",
                       details)


CHECKS: dict[str, Callable[[LiveContext], CheckResult]] = {
    "live-refresh-status": check_refresh_status,
    "live-freshness": check_freshness,
    "live-table-sample": check_table_sample,
    "live-dimension-rows": check_dimension_rows,
    "live-measure-sample": check_measure_sample,
    "live-parameter-table-measures": check_parameter_table_measures,
    "live-uniform-row-limit": check_uniform_row_limit,
    "live-calendar-rows": check_calendar_rows,
    "live-dimension-multirow": check_dimension_multirow,
    "live-calendar-scan": check_calendar_scan,
    "live-calendar-vs-parameters": check_calendar_vs_parameters,
    "live-parameter-audit": check_parameter_audit,
    "live-identity": check_identity,
    "live-filter-compare": check_filter_compare,
    "live-metadata": check_metadata,
    "live-filter-diagnostic": check_filter_diagnostic,
    "live-smoke": check_smoke,
    "live-bpa": check_bpa,
}


def coupled(dataset: dict, model_dir: Path, expect_name: Optional[str] = None) -> bool:
    stem = Path(model_dir).name
    stem = stem[: -len(".SemanticModel")] if stem.endswith(".SemanticModel") else stem
    name = str(dataset.get("name") or "")
    if name and (stem.lower() in name.lower() or name.lower() in stem.lower()):
        return True
    return bool(expect_name) and expect_name.lower() in str(dataset.get("workspaceName") or "").lower()


def run_checks(ctx: LiveContext, ids: list[str]) -> list[CheckResult]:
    out = []
    for cid in ids:
        try:
            out.append(CHECKS[cid](ctx))
        except Exception as exc:  # noqa: BLE001 - an unexpected failure is an outcome
            out.append(CheckResult(cid, "error", f"{type(exc).__name__}: {exc}"))
    return out


def exit_code(results: list[CheckResult], strict: bool = False) -> int:
    if any(r.outcome in ("fail", "error") for r in results):
        return 1
    if strict and any(r.outcome == "warn" for r in results):
        return 1
    return 0
