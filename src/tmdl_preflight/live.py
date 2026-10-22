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
NO_ROWS = "no rows returned"

CREDENTIAL_NAMES = (("PBI_TENANT_ID", "FABRIC_TENANT_ID"),
                    ("PBI_CLIENT_ID", "FABRIC_CLIENT_ID"),
                    ("PBI_CLIENT_SECRET", "FABRIC_CLIENT_SECRET"))


def missing_credentials() -> str:
    """The names of the credentials that are not set, as one sentence."""
    missing = [pbi for pbi, fabric in CREDENTIAL_NAMES
               if not (os.environ.get(pbi) or os.environ.get(fabric))]
    return f"Missing required environment variables: {', '.join(missing)}."


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

    def today(self) -> _dt.date:
        """The local date (a replay answers with its own clock)."""
        return _dt.date.today()

    def token_remaining_seconds(self) -> float:
        return 0.0

    def health_check(self) -> dict:
        """Sign in, read the dataset and run a query; each step is reported."""
        start = time.perf_counter()
        checks: dict[str, dict] = {}
        status, error = "healthy", None
        try:
            auth_start = time.perf_counter()
            checks["authentication"] = {
                "status": "ok", "time_ms": (time.perf_counter() - auth_start) * 1000,
                "token_remaining_seconds": self.token_remaining_seconds()}
            ds_start = time.perf_counter()
            props = self.dataset()
            checks["dataset_access"] = {
                "status": "ok", "time_ms": (time.perf_counter() - ds_start) * 1000,
                "dataset_name": props.get("name")}
            q_start = time.perf_counter()
            result = self.execute("EVALUATE { 1 }")
            if result.error:
                raise LiveError(result.error)
            checks["query_execution"] = {
                "status": "ok", "time_ms": (time.perf_counter() - q_start) * 1000,
                "rows_returned": len(result.rows)}
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            status, error = "unhealthy", str(exc)
        out = {"status": status, "checks": checks,
               "total_time_ms": (time.perf_counter() - start) * 1000}
        if error is not None:
            out["error"] = error
        return out


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

    def today(self) -> _dt.date:
        return self.now().date()


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
                                     {"queries": [{"query": query}]})
                return QueryResult(rows_of(body), (time.perf_counter() - start) * 1000, stamp)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:500]
                return QueryResult([], (time.perf_counter() - start) * 1000, stamp,
                                   f"HTTP {exc.code}: {detail}")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = exc
                if attempt < 2:
                    time.sleep(2)
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

    def token_remaining_seconds(self) -> float:
        remaining = getattr(self._token, "remaining_seconds", None)
        return float(remaining()) if callable(remaining) else 0.0


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

    def today(self) -> _dt.date:
        return self.inner.today()


def token_provider(interactive: bool = True) -> Callable[[], str]:
    """Bearer tokens: service principal from the environment, else an
    interactive sign-in (needs the optional ``msal`` package). Tokens are
    kept in memory only and renewed when less than 5 minutes remain.

    The returned callable carries ``remaining_seconds()``: the life left on
    the token it last fetched."""
    tenant, client, secret = (os.environ.get(pbi) or os.environ.get(fabric)
                              for pbi, fabric in CREDENTIAL_NAMES)
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
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    if attempt < 2:
                        time.sleep(2)
                    continue
                if "access_token" not in data:
                    raise LiveError(f"Authentication failed: "
                                    f"{data.get('error_description', 'Unknown error')}")
                return data["access_token"], time.time() + float(data.get("expires_in", 3599))
            raise LiveError(f"could not obtain a token: {last}")
    elif interactive:
        try:
            import msal  # type: ignore[import-not-found]
        except ImportError:
            raise LiveUsageError(
                f"{missing_credentials()}. no credentials: set PBI_TENANT_ID, PBI_CLIENT_ID and "
                "PBI_CLIENT_SECRET for a service principal, or install msal for an interactive "
                "sign-in") from None
        app = msal.PublicClientApplication("04b07795-8ddb-461a-bbee-02f9e1bf7b46",
                                           authority="https://login.microsoftonline.com/organizations")

        def fetch() -> tuple[str, float]:
            result = app.acquire_token_interactive(scopes=[SCOPE])
            if "access_token" not in result:
                raise LiveError(f"Authentication failed: "
                                f"{result.get('error_description', 'Unknown error')}")
            return result["access_token"], time.time() + float(result.get("expires_in", 3599))
    else:
        raise LiveUsageError(
            f"{missing_credentials()}. no credentials: set PBI_TENANT_ID, PBI_CLIENT_ID and "
            "PBI_CLIENT_SECRET (--non-interactive allows no sign-in prompt)")

    def token() -> str:
        if state["token"] is None or state["expires"] - time.time() < 300:
            state["token"], state["expires"] = fetch()
        return state["token"]

    def remaining_seconds() -> float:
        return max(0.0, state["expires"] - time.time())

    token.remaining_seconds = remaining_seconds  # type: ignore[attr-defined]
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


COLUMN_PATTERN = re.compile(r"^\s*column\s+['\"]?([^'\";\s\[=]+)['\"]?", re.MULTILINE)
MEASURE_PATTERN = re.compile(r"^\s*measure\s+(?:'((?:[^']|'')+)'|([^'\"\n=]+?))\s*=", re.MULTILINE)
EXPRESSION_PATTERN = re.compile(r"expression (v-[^\s=]+)\s*=\s*([^\n]+?)(?:\s+meta|\n)")


def read_local_model(model_dir: Path) -> LocalModel:
    tables_dir = Path(model_dir) / "definition" / "tables"
    with_cols, names, measures = [], [], []
    for f in sorted(tables_dir.glob("*.tmdl")) if tables_dir.is_dir() else []:
        text = f.read_text(encoding="utf-8-sig")
        names.append(f.stem)
        if COLUMN_PATTERN.search(text):
            with_cols.append(f.stem)
        for m in MEASURE_PATTERN.finditer(text):
            quoted, plain = m.group(1), m.group(2)
            name = quoted.replace("''", "'") if quoted is not None else plain.strip()
            measures.append((f.stem, name))
    expr = Path(model_dir) / "definition" / "expressions.tmdl"
    params = None
    if expr.is_file():
        params = {m.group(1): m.group(2).strip()
                  for m in EXPRESSION_PATTERN.finditer(expr.read_text(encoding="utf-8-sig"))}
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
    report: list[str] = field(default_factory=list)


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
        if not r.rows:
            return None, NO_ROWS
        return count(r.first, label), None


def _rate(passed: int, probed: int) -> float:
    return passed / probed if probed else 0.0


def _probe(icon: str, name: str, message: str, ms: float) -> str:
    return f"{icon} {name}: {message} ({ms:.2f}ms)"


def check_uniform_row_limit(c: LiveContext) -> CheckResult:
    cid = "live-uniform-row-limit"
    counts: dict[str, Optional[int]] = {}
    report = ["", "=== Row Count Pattern Detection ===", ""]
    for t in c.cfg["probe_tables"]:
        n, err = c.table_count(t)
        counts[t] = n
        report.append(f"  {t}: ERROR - {err[:50]}" if err else f"  {t}: {n:,} rows")
    known = [v for v in counts.values() if v is not None]
    details: dict = {"counts": counts}
    if not known:
        return CheckResult(cid, "warn", "Could not retrieve any row counts", details, report)
    details["min"], details["max"] = min(known), max(known)
    report += ["", "📊 Analysis:", f"  Unique row counts: {sorted(set(known))}"]
    if set(known) == {1}:
        return CheckResult(cid, "fail",
                           f"🔴 CRITICAL: All {len(known)} tables have exactly 1 row. This "
                           "indicates v-rows_limit='LIMIT 1' is set. Change parameter to ' ' "
                           "(blank) for full data.", details, report)
    if len(set(known)) == 1 and known[0] in c.cfg["uniform_limits"]:
        limit = known[0]
        return CheckResult(cid, "warn",
                           f"⚠️  WARNING: All tables have exactly {limit} rows. This suggests "
                           f"v-rows_limit='LIMIT {limit}' is set. This is acceptable for testing "
                           "but not production.", details, report)
    report.append(f"  ✅ Row counts vary ({details['min']} to {details['max']}) - "
                  "no uniform limit detected")
    return CheckResult(cid, "pass",
                       f"row counts vary ({details['min']} to {details['max']})", details, report)


def _calendar_query(c: LiveContext, order: str) -> str:
    cal, col = quote_table(c.cfg["calendar_table"]), c.cfg["date_column"]
    parts = {"RowCount": f'"RowCount", COUNTROWS({cal})',
             "MinDate": f'"MinDate", MIN({cal}[{col}])',
             "MaxDate": f'"MaxDate", MAX({cal}[{col}])'}
    keys = ["RowCount", "MinDate", "MaxDate"] if order == "count-first" else ["MinDate", "MaxDate", "RowCount"]
    return "EVALUATE ROW( " + ", ".join(parts[k] for k in keys) + " )"


def check_calendar_rows(c: LiveContext) -> CheckResult:
    cid = "live-calendar-rows"
    r = c.client.execute(_calendar_query(c, "count-first"))
    if r.error:
        return CheckResult(cid, "error", f"calendar query failed: {r.error}")
    if not r.rows:
        return CheckResult(cid, "error", "the calendar query returned no rows")
    n = count(r.first, "RowCount")
    details = {"row_count": n, "min_date": scalar(r.first, "MinDate"),
               "max_date": scalar(r.first, "MaxDate")}
    report = ["", "=== Calendar Table Validation ===", "",
              f"  Row count: {n:,}",
              f"  Min date: {details['min_date']}",
              f"  Max date: {details['max_date']}"]
    if n == 1:
        return CheckResult(cid, "fail",
                           "🔴 CRITICAL: Calendar has only 1 row (expected 365+). This indicates "
                           "v-rows_limit='LIMIT 1' is set. Change to ' ' (blank) for full data.",
                           details, report)
    if n < 100:
        return CheckResult(cid, "warn",
                           f"⚠️  WARNING: Calendar has only {n} rows (expected 365+). Check "
                           "v-rows_limit and v-fromdate parameters.", details, report)
    if n < 365:
        report.append(f"  ⚠️  Calendar has {n} rows (less than 1 year)")
        report.append("     This may indicate date filtering or limited data range")
    else:
        report.append("  ✅ Calendar has realistic row count")
    return CheckResult(cid, "pass", f"{n} calendar rows", details, report)


def check_dimension_multirow(c: LiveContext) -> CheckResult:
    cid = "live-dimension-multirow"
    tables = list(c.cfg["dimension_probe_tables"])
    counts: dict[str, Optional[int]] = {}
    report = ["", "=== Dimension Table Validation ===", ""]
    for t in tables:
        n, err = c.table_count(t)
        counts[t] = n
        if err:
            report.append(f"  ❌ {t}: ERROR - {err[:50]}")
        else:
            report.append(f"  {'✅' if n > 1 else '🔴'} {t}: {n:,} rows")
    details: dict = {"counts": counts}
    if not any(v is not None and v > 1 for v in counts.values()):
        return CheckResult(cid, "fail",
                           "🔴 CRITICAL: All dimension tables have ≤1 row. This indicates "
                           f"v-rows_limit='LIMIT 1' or empty source data. Results: {counts}",
                           details, report)
    single = [t for t, v in counts.items() if v == 1]
    details["single_row_tables"] = single
    if len(single) > len(tables) // 2:
        return CheckResult(cid, "warn",
                           f"⚠️  WARNING: {len(single)}/{len(tables)} dimension tables have only "
                           f"1 row. Check v-rows_limit parameter. Single-row tables: {single}",
                           details, report)
    report += ["", "  ✅ Dimension tables have realistic row counts"]
    return CheckResult(cid, "pass", "dimension tables hold several rows", details, report)


def _sample_value(row: dict) -> Any:
    for key, value in row.items():
        if "date" in key.lower() and value not in (None, ""):
            return value
    if row:
        return next(iter(row.values()))
    return "N/A"


def check_calendar_scan(c: LiveContext) -> CheckResult:
    cid, cal = "live-calendar-scan", c.cfg["calendar_table"]
    quoted = quote_table(cal)
    r = c.client.execute(f'EVALUATE ROW("RowCount", COUNTROWS({quoted}))')
    if r.error:
        return CheckResult(cid, "error", f"calendar count failed: {r.error}")
    raw = scalar(r.first, "RowCount")
    report = ["", "=== Large Table Full Scan Test ===", "",
              f"Testing {cal} table (should have 365+ rows)...",
              f"COUNTROWS({quoted}): {raw}"]
    if raw is None or int(raw) == 0:
        return CheckResult(cid, "error", "the calendar count came back BLANK or 0", {}, report)
    n = int(raw)
    top = c.client.execute(f"EVALUATE TOPN(50, {quoted})")
    if top.error:
        report.append(f"❌ Error querying {cal}: {top.error[:100]}")
        return CheckResult(cid, "error", f"calendar sample failed: {top.error}",
                           {"topn_error": top.error}, report)
    rows = top.rows
    report.append(f"TOPN(50, {quoted}): {len(rows)} rows returned")
    samples = []
    if rows:
        report.append("")
        report.append(f"Sample dates from {cal}:")
        for i, row in enumerate(rows[:5], 1):
            value = _sample_value(row)
            samples.append(value)
            report.append(f"  Row {i}: {value}")
    report += ["", "=" * 80, "ASSESSMENT", "=" * 80]
    details = {"row_count": n, "returned_rows": len(rows), "sample_values": samples}
    if n == 1:
        report += [f"🔴 CRITICAL: {cal} has only 1 row!",
                   "   This is HIGHLY SUSPICIOUS for a calendar table.",
                   "   Likely causes:",
                   "   1. Row-Level Security (RLS) is filtering to 1 row",
                   "   2. Global filter context is applied",
                   "   3. Service principal has restricted data access",
                   "",
                   "   ACTION REQUIRED:",
                   "   - Check RLS roles in Fabric workspace",
                   "   - Verify service principal permissions",
                   "   - Review any filter context in model"]
        return CheckResult(cid, "fail",
                           f"{cal} should have 365+ rows but has only 1. This indicates RLS or "
                           "filter context is limiting data access.", details, report)
    if n < 100:
        report += [f"⚠️  WARNING: {cal} has only {n} rows",
                   "   This seems low for a calendar table.",
                   "   May indicate limited date range or filter applied."]
        return CheckResult(cid, "pass", f"{n} calendar rows", details, report)
    report += [f"✅ {cal} has {n} rows (healthy)",
               "   No obvious filter context limiting data."]
    return CheckResult(cid, "pass", f"{n} calendar rows", details, report)


def _date_param(value: Optional[str]) -> Optional[str]:
    m = re.search(r"#date\((\d+),\s*(\d+),\s*(\d+)\)", value or "")
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def check_calendar_vs_parameters(c: LiveContext) -> CheckResult:
    cid, params = "live-calendar-vs-parameters", c.model.parameters
    if params is None:
        return CheckResult(cid, "skip",
                           f"expressions.tmdl not found under {c.model.path / 'definition'}")
    r = c.client.execute(_calendar_query(c, "dates-first"))
    if r.error:
        return CheckResult(cid, "error", f"calendar query failed: {r.error}")
    if not r.rows:
        return CheckResult(cid, "error", "the calendar query returned no rows")
    n = count(r.first, "RowCount")
    from_date = _date_param(params.get(c.cfg["from_date_parameter"]))
    is_rolling = params.get("v-isRolling", "0").strip()
    days_ago = params.get("v-daysAgo", "90").strip()
    details = {
        "v-fromdate": from_date,
        "v-isRolling": is_rolling,
        "v-daysAgo": days_ago,
        "min_date": scalar(r.first, "MinDate"), "max_date": scalar(r.first, "MaxDate"),
        "row_count": n,
    }
    report = ["", "=== Date Range Validation ===", "",
              "  Parameter Configuration:",
              f"    v-fromdate: {from_date}",
              f"    v-isRolling: {is_rolling}",
              f"    v-daysAgo: {days_ago}",
              "",
              "  Actual Data:",
              f"    Min date: {details['min_date']}",
              f"    Max date: {details['max_date']}",
              f"    Row count: {n:,}"]
    if n == 1:
        return CheckResult(cid, "warn",
                           "Only 1 row in calendar - cannot validate date range "
                           "(LIMIT 1 applied)", details, report)
    report += ["", "  ✅ Date range retrieved (validation informational)"]
    return CheckResult(cid, "pass",
                       f"calendar {details['min_date']} to {details['max_date']} ({n} rows)",
                       details, report)


def check_parameter_audit(c: LiveContext) -> CheckResult:
    cid, params = "live-parameter-audit", c.model.parameters
    if params is None:
        return CheckResult(cid, "skip",
                           f"expressions.tmdl not found under {c.model.path / 'definition'}")
    time_params = sorted(n for n in params if any(k in n for k in
                                                  ("date", "Rolling", "rows_limit", "daysAgo")))
    issues: list[dict] = []
    limit_name = c.cfg["row_limit_parameter"]
    limit = params.get(limit_name, "")
    if re.search(r"LIMIT 1(?!\d)", limit):
        issues.append({"severity": "CRITICAL", "parameter": limit_name, "value": limit,
                       "message": "LIMIT 1 applied - only 1 row per table imported",
                       "recommendation": "Change to ' ' (blank) for production"})
    elif "LIMIT" in limit:
        issues.append({"severity": "WARNING", "parameter": limit_name, "value": limit,
                       "message": "Row limit applied - data incomplete",
                       "recommendation": "Review limit value for environment"})
    date_name = c.cfg["from_date_parameter"]
    from_date = _date_param(params.get(date_name))
    today = c.client.today()
    if from_date and _dt.date.fromisoformat(from_date) > today:
        ahead = (_dt.date.fromisoformat(from_date) - today).days
        issues.append({"severity": "CRITICAL", "parameter": date_name,
                       "value": params.get(date_name, ""),
                       "message": f"Future date ({ahead} days ahead) - no historical data",
                       "recommendation": "Change to past date (e.g., 2023-01-01)"})
    cal = c.cfg["calendar_table"]
    r = c.client.execute(f'EVALUATE ROW( "CalendarRows", COUNTROWS({quote_table(cal)}), '
                         f'"AccountsRows", COUNTROWS({quote_table("_Accounts")}) )')
    sample: dict[str, int] = {}
    report = ["", "=" * 80, "CONNECTION PARAMETER AUDIT REPORT", "=" * 80, "",
              "1. PARAMETER CONFIGURATION", "-" * 80, "", "  Time/Data Filters:"]
    report += [f"    {name}: {params[name]}" for name in time_params]
    report += ["", "2. RISK ASSESSMENT", "-" * 80]
    if issues:
        report += ["", "  Issues Found:"]
        for issue in issues:
            icon = "🔴" if issue["severity"] == "CRITICAL" else "⚠️ "
            report += ["", f"    {icon} {issue['severity']}: {issue['parameter']}",
                       f"       Value: {issue['value']}",
                       f"       Issue: {issue['message']}",
                       f"       Recommendation: {issue['recommendation']}"]
    else:
        report += ["", "  ✅ No critical issues detected"]
    report += ["", "3. LIVE DATA VALIDATION", "-" * 80]
    if r.error:
        report += ["", f"  ❌ Error validating live data: {r.error[:100]}"]
    else:
        calendar_rows = count(r.first, "CalendarRows")
        accounts_rows = count(r.first, "AccountsRows")
        sample = {cal: calendar_rows, "_Accounts": accounts_rows}
        report += ["", "  Sample Row Counts:",
                   f"    {cal}: {calendar_rows:,} rows",
                   f"    _Accounts: {accounts_rows:,} rows"]
        if calendar_rows == 1 and accounts_rows == 1:
            report += ["", "  🔴 Pattern: All tables have 1 row (confirms LIMIT 1 parameter)"]
        elif calendar_rows < 100:
            report += ["", "  ⚠️  Calendar has limited rows - check date filtering"]
    report += ["", "4. RECOMMENDATIONS", "-" * 80]
    if issues:
        report += ["", "  Immediate Actions Required:"]
        report += [f"    {i}. {issue['recommendation']}"
                   for i, issue in enumerate(issues, 1) if issue["severity"] == "CRITICAL"]
    report += ["", "=" * 80, f"Report generated: {_dt.datetime.now()}", "=" * 80, "",
               "✅ Audit report generated successfully"]
    details = {"time_parameters": time_params, "parameters": params, "issues": issues,
               "live_sample": sample,
               "recommendations": [i["recommendation"] for i in issues
                                   if i["severity"] == "CRITICAL"]}
    return CheckResult(cid, "pass", f"{len(issues)} parameter issue(s)", details, report)


def _table_probe(c: LiveContext, table: str) -> tuple[bool, str, float]:
    r = c.client.execute(f'EVALUATE ROW("RowCount", COUNTROWS({quote_table(table)}))')
    if r.error:
        return False, f"Error checking table: {r.error}", r.elapsed_ms
    if not r.rows:
        return False, f"Error checking table: {NO_ROWS}", r.elapsed_ms
    n = count(r.first, "RowCount")
    if n > 0:
        return True, f"Table '{table}' has {n:,} rows", r.elapsed_ms
    return False, f"Table '{table}' is empty (0 rows)", r.elapsed_ms


def check_table_sample(c: LiveContext) -> CheckResult:
    cid = "live-table-sample"
    tables = c.model.tables_with_columns[: c.cfg["sample_tables"]]
    report: list[str] = []
    passed = 0
    empty: list[str] = []
    for t in tables:
        ok, message, ms = _table_probe(c, t)
        if ok:
            passed += 1
        else:
            empty.append(t)
        name = "Table '%s' has data" % t
        report.append("  " + _probe("✅ PASS" if ok else "❌ FAIL", name, message, ms))
    rate = _rate(passed, len(tables))
    details = {"tables": tables, "probed": len(tables), "passed": passed,
               "empty_tables": empty}
    if rate >= c.cfg["sample_pass_rate"]:
        return CheckResult(cid, "pass",
                           f"{passed} of {len(tables)} sampled tables hold rows", details, report)
    return CheckResult(cid, "fail",
                       f"Only {passed}/{len(tables)} tables have data ({rate:.1%}). Expected at "
                       f"least {c.cfg['sample_pass_rate']:.0%}.", details, report)


def check_dimension_rows(c: LiveContext) -> CheckResult:
    cid = "live-dimension-rows"
    prefix = c.cfg["dimension_prefix"]
    tables = [t for t in c.model.tables_with_columns if t.startswith(prefix)]
    if not tables:
        return CheckResult(cid, "fail", f"No dimension tables found starting with '{prefix}'")
    report: list[str] = []
    passed = 0
    failed: list[str] = []
    for t in tables:
        ok, message, ms = _table_probe(c, t)
        if ok:
            passed += 1
        else:
            failed.append(t)
            name = "Table '%s' has data" % t
            report.append("  " + _probe("❌ FAIL", name, message, ms))
    if failed:
        report += ["", f"⚠️  Warning: {len(failed)} dimension tables are empty: {failed}"]
    details = {"tables": tables, "probed": len(tables), "passed": passed,
               "empty_tables": failed}
    rate = _rate(passed, len(tables))
    if rate >= c.cfg["dimension_pass_rate"]:
        return CheckResult(cid, "pass",
                           f"{passed} of {len(tables)} dimension tables hold rows", details, report)
    return CheckResult(cid, "fail",
                       f"Only {passed}/{len(tables)} dimension tables have data ({rate:.1%}). "
                       f"Failed tables: {failed}", details, report)


def _measure_probe(c: LiveContext, measure: str) -> tuple[bool, str, float, Any]:
    ref = "[" + measure.replace("]", "]]") + "]"
    r = c.client.execute(f'EVALUATE ROW( "Value", {ref}, "IsBlank", ISBLANK({ref}) )')
    if r.error:
        return False, f"Error checking measure: {r.error}", r.elapsed_ms, None
    if not r.rows:
        return False, f"Error checking measure: {NO_ROWS}", r.elapsed_ms, None
    value = scalar(r.first, "Value")
    raw = r.first.get("[IsBlank]", r.first.get("IsBlank"))
    blank = True if raw is None else bool(raw)
    if blank:
        return False, f"Measure '{ref}' returned BLANK", r.elapsed_ms, value
    return True, f"Measure '{ref}' returned value: {value}", r.elapsed_ms, value


def _measure_sample(c: LiveContext, cid: str, items: list[tuple[str, str]],
                    noun: str = "measures") -> CheckResult:
    report: list[str] = []
    values: dict[str, Any] = {}
    passed = 0
    for table, m in items:
        ok, message, ms, value = _measure_probe(c, m)
        values[m] = value
        if ok:
            passed += 1
        else:
            probe = _probe("❌ FAIL", f"Measure '[{m}]' not blank", message, ms)
            report.append(f"  ❌ [{table}].[{m}]: {probe}" if table else f"  {probe}")
    rate = _rate(passed, len(items))
    details: dict = {"probed": len(items), "passed": passed, "values": values,
                     "blank_or_failed": [m for _t, m in items if values[m] is None]}
    if rate < 0.5:
        details["note"] = "fewer than half of the sampled measures return a value"
        report += ["", f"⚠️  Warning: Only {rate:.1%} of measures returned non-blank values"]
    if rate >= c.cfg["measure_pass_rate"]:
        return CheckResult(cid, "pass",
                           f"{passed} of {len(items)} sampled measures return a value",
                           details, report)
    return CheckResult(cid, "fail",
                       f"Only {passed}/{len(items)} {noun} returned non-blank ({rate:.1%}). "
                       f"Expected at least {c.cfg['measure_pass_rate']:.0%}.", details, report)


def check_measure_sample(c: LiveContext) -> CheckResult:
    items = [("", m) for _t, m in c.model.measures][: c.cfg["sample_measures"]]
    return _measure_sample(c, "live-measure-sample", items)


def check_parameter_table_measures(c: LiveContext) -> CheckResult:
    cid = "live-parameter-table-measures"
    if not c.cfg["parameter_table_measures"]:
        return CheckResult(cid, "skip",
                           "Report tables are parameter tables, not measure tables. "
                           "Skipping for now.")
    prefixes = tuple(c.cfg["parameter_table_prefixes"])
    per_table: dict[str, list[str]] = {}
    for t, m in c.model.measures:
        if t.startswith(prefixes):
            per_table.setdefault(t, []).append(m)
    if not per_table:
        return CheckResult(cid, "fail", "No x-Selector measure tables found")
    items = [(t, m) for t, ms in per_table.items() for m in ms[:5]]
    return _measure_sample(c, cid, items, noun="Report measures")


def _refresh_probe(c: LiveContext) -> tuple[str, str, dict, float]:
    start = time.perf_counter()
    hist = c.client.refreshes(1)
    ms = (time.perf_counter() - start) * 1000
    if not hist:
        return "warn", "No refresh history found", {"refresh_count": 0}, ms
    latest = hist[0]
    status = latest.get("status", "Unknown")
    details = {"status": status, "end_time": latest.get("endTime"),
               "request_id": latest.get("requestId")}
    if status == "Completed":
        return ("pass", f"Latest refresh completed successfully at {latest.get('endTime')}",
                details, ms)
    return "warn", f"Latest refresh status: {status}", details, ms


def check_refresh_status(c: LiveContext) -> CheckResult:
    cid = "live-refresh-status"
    outcome, msg, details, ms = _refresh_probe(c)
    report = ["  " + _probe("✅ PASS" if outcome == "pass" else "❌ FAIL",
                            "Latest refresh status", msg, ms)]
    if outcome != "pass":
        report += ["", f"⚠️  WARNING: {msg}", f"    Details: {details}"]
    message = msg if outcome == "pass" else f"Refresh status check failed (non-blocking): {msg}"
    return CheckResult(cid, outcome, message, details, report)


def _parse_time(text: str) -> _dt.datetime:
    value = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)


def _freshness_probe(c: LiveContext) -> tuple[str, str, dict, float]:
    start = time.perf_counter()
    max_hours = c.cfg["freshness_max_hours"]
    hist = c.client.refreshes(10)
    ms = (time.perf_counter() - start) * 1000
    if not hist:
        return "warn", "No refresh history found", {"refresh_count": 0}, ms
    done = next((h for h in hist if h.get("status") == "Completed"), None)
    if done is None:
        return "warn", "No successful refresh found in history", {"completed_refresh_count": 0}, ms
    raw = done.get("endTime")
    try:
        age = (c.client.now() - _parse_time(str(raw))).total_seconds() / 3600
    except (TypeError, ValueError) as exc:
        return ("warn", f"Error checking data freshness: {exc}", {"error": str(exc)}, ms)
    fresh = age <= max_hours
    details = {"end_time": raw, "age_hours": age, "max_hours": max_hours, "is_fresh": fresh}
    if fresh:
        return "pass", f"Data refreshed {age:.1f} hours ago (within {max_hours}h threshold)", \
            details, ms
    return "warn", f"Data is {age:.1f} hours old (exceeds {max_hours}h threshold)", details, ms


def check_freshness(c: LiveContext) -> CheckResult:
    cid = "live-freshness"
    outcome, msg, details, ms = _freshness_probe(c)
    name = f"Data freshness (max {c.cfg['freshness_max_hours']}h)"
    report = ["  " + _probe("✅ PASS" if outcome == "pass" else "❌ FAIL", name, msg, ms)]
    if outcome != "pass":
        report += ["", f"⚠️  WARNING: {msg}", f"    Details: {details}"]
    message = msg if outcome == "pass" else f"Data freshness check failed (non-blocking): {msg}"
    return CheckResult(cid, outcome, message, details, report)


def check_smoke(c: LiveContext) -> CheckResult:
    cid = "live-smoke"
    items: list[tuple[str, bool, str, float]] = []
    prefix = c.cfg["dimension_prefix"]
    for t in [t for t in c.model.tables_with_columns if t.startswith(prefix)]:
        ok, why, ms = _table_probe(c, t)
        items.append((f"Table '{t}' has data", ok, why, ms))
    for _t, m in c.model.measures[: c.cfg["suite_measures"]]:
        ok, why, ms, _value = _measure_probe(c, m)
        items.append((f"Measure '[{m}]' not blank", ok, why, ms))
    outcome, msg, _details, ms = _refresh_probe(c)
    items.append(("Latest refresh status", outcome == "pass", msg, ms))
    outcome, msg, _details, ms = _freshness_probe(c)
    items.append((f"Data freshness (max {c.cfg['freshness_max_hours']}h)",
                   outcome == "pass", msg, ms))
    passed = sum(1 for _n, ok, _w, _ms in items if ok)
    failed = len(items) - passed
    rate = _rate(passed, len(items))
    total_ms = sum(ms for _n, _ok, _w, ms in items)
    report = ["", "=" * 80, "COMPREHENSIVE SMOKE TEST SUITE", "=" * 80, "",
              "-" * 80, "SUMMARY", "-" * 80,
              f"Total tests: {len(items)}",
              f"Passed: {passed} ({rate:.1%})",
              f"Failed: {failed}"]
    if failed:
        report += ["", "Failed tests:"]
        report += ["  ❌ " + _probe("❌ FAIL", name, why, ms)
                   for name, ok, why, ms in items if not ok]
    report += ["", f"Total execution time: {total_ms:.2f}ms ({total_ms / 1000:.2f}s)",
               "=" * 80, ""]
    details = {"passed": passed, "total": len(items),
               "failed_items": [f"{name}: {why}" for name, ok, why, _ms in items if not ok],
               "elapsed_ms": total_ms}
    if rate >= c.cfg["suite_pass_rate"]:
        return CheckResult(cid, "pass",
                           f"{passed} of {len(items)} smoke items passed", details, report)
    return CheckResult(cid, "fail",
                       f"Smoke test suite failed. Pass rate: {rate:.1%} (expected >= "
                       f"{c.cfg['suite_pass_rate']:.0%}). {failed} tests failed.", details, report)


DATASET_PROPERTIES = (("id", "id"), ("name", "name"), ("configuredBy", "configured_by"),
                      ("isRefreshable", "is_refreshable"),
                      ("targetStorageMode", "target_storage_mode"),
                      ("workspaceId", "workspace_id"), ("workspaceName", "workspace_name"))


def _dataset_properties(client: _Client) -> dict:
    data = client.dataset()
    return {label: data.get(key) for key, label in DATASET_PROPERTIES}


def check_identity(c: LiveContext) -> CheckResult:
    cid = "live-identity"
    r = c.client.execute('EVALUATE ROW( "UserPrincipalName", USERPRINCIPALNAME(), '
                         '"UserName", USERNAME(), "UserObjectId", USEROBJECTID() )')
    if r.error:
        return CheckResult(cid, "error", f"identity query failed: {r.error}")
    props = _dataset_properties(c.client)
    details = {"user_principal_name": scalar(r.first, "UserPrincipalName"),
               "user_name": scalar(r.first, "UserName"),
               "user_object_id": scalar(r.first, "UserObjectId"),
               "dataset_name": props["name"], "is_refreshable": props["is_refreshable"],
               "storage_mode": props["target_storage_mode"],
               "note": "role membership cannot be read without admin rights"}
    report = ["", "=== RLS Detection Test ===", "",
              f"Query executed in {r.elapsed_ms:.2f}ms",
              f"Row count: {len(r.rows)}",
              "", "User Identity:"]
    for row in r.rows:
        report += [f"  {key}: {value}" for key, value in row.items()]
    report += ["", f"Dataset: {props['name']}",
               f"Is Refreshable: {props['is_refreshable']}",
               f"Target Storage Mode: {props['target_storage_mode']}",
               "", "✅ User identity retrieved",
               "⚠️  Cannot directly query RLS roles (requires admin). "
               "Check manually in Fabric workspace."]
    return CheckResult(cid, "pass",
                       f"querying as {details['user_principal_name']}", details, report)


def check_filter_compare(c: LiveContext) -> CheckResult:
    cid = "live-filter-compare"
    rows: list[dict[str, Any]] = []
    flagged: list[str] = []
    report: list[str] = []
    for t in c.cfg["filter_probe_tables"]:
        n, err = c.table_count(t, "RowCount")
        report += ["", f"--- Testing table: {t} ---"]
        if err:
            return CheckResult(cid, "error", f"COUNTROWS({t}) failed: {err}", {}, report)
        report.append(f"COUNTROWS({quote_table(t)}): {n}")
        entry: dict[str, Any] = {"table": t, "countrows": n}
        top = c.client.execute(f"EVALUATE TOPN(10, {quote_table(t)})")
        if top.error:
            report.append(f"❌ Error querying {t}: {top.error[:100]}")
            entry["topn_actual"] = "ERROR"
            entry["countrows_all"] = "ERROR"
            entry["error"] = top.error[:100]
            rows.append(entry)
            continue
        entry["topn_actual"] = len(top.rows)
        report.append(f"EVALUATE TOPN(10, {quote_table(t)}): {len(top.rows)} rows returned")
        tot = c.client.execute(f'EVALUATE ROW( "TotalRows", CALCULATE(COUNTROWS({quote_table(t)}), '
                               f'ALL({quote_table(t)})) )')
        if tot.error:
            report.append(f"❌ Error querying {t}: {tot.error[:100]}")
            entry["countrows_all"] = "ERROR"
            entry["error"] = tot.error[:100]
            rows.append(entry)
            continue
        all_count = count(tot.first, "TotalRows")
        entry["countrows_all"] = all_count
        report.append(f"COUNTROWS with ALL({quote_table(t)}): {all_count}")
        if top.rows:
            report += ["", f"Sample data from {t} (first row):"]
            report += [f"  {key}: {value}" for key, value in list(top.rows[0].items())[:5]]
        if all_count != n:
            entry["discrepancy"] = True
            flagged.append(t)
        rows.append(entry)
    report += ["", "=" * 80, "SUMMARY", "=" * 80,
               f"{'Table':<30} {'COUNTROWS':<15} {'TOPN Actual':<15} {'ALL()':<15} "
               f"{'Filter?':<10}", "-" * 80]
    for entry in rows:
        indicator = "⚠️ YES" if entry.get("discrepancy") else "✅ NO"
        report.append(f"{entry['table']:<30} {str(entry['countrows']):<15} "
                      f"{str(entry['topn_actual']):<15} {str(entry['countrows_all']):<15} "
                      f"{indicator:<10}")
    if flagged:
        report += ["", "⚠️  WARNING: Filter context or RLS detected!",
                   f"   {len(flagged)} tables show different counts with/without ALL()",
                   "   This suggests Row-Level Security or implicit filters are active."]
    else:
        report += ["", "✅ No filter context detected",
                   "   COUNTROWS and COUNTROWS with ALL() return same values"]
    return CheckResult(cid, "pass",
                       f"{len(flagged)} table(s) count differently with ALL()",
                       {"tables": rows, "flagged": flagged}, report)


def check_metadata(c: LiveContext) -> CheckResult:
    cid = "live-metadata"
    props = _dataset_properties(c.client)
    refreshes = c.client.refreshes(5)
    datasources = c.client.datasources()
    report = ["", "=== Connection Metadata Investigation ===", "", "Dataset Properties:"]
    report += [f"  {key}: {value}" for key, value in props.items()]
    report += ["", "Refresh History (last 5):"]
    for i, refresh in enumerate(refreshes, 1):
        report.append(f"  {i}. Status: {refresh.get('status', 'Unknown')}, "
                      f"End: {refresh.get('endTime', 'Unknown')}, "
                      f"ID: {refresh.get('requestId', 'Unknown')}")
    report += ["", "Datasources:"]
    for i, source in enumerate(datasources, 1):
        report.append(f"  {i}. Connection: {source}")
    report += ["", "✅ Metadata investigation complete"]
    details = {"dataset": c.client.dataset(),
               "refreshes": [{k: r.get(k) for k in ("status", "endTime", "requestId")}
                             for r in refreshes],
               "datasources": datasources}
    return CheckResult(cid, "pass", "dataset metadata collected", details, report)


def check_filter_diagnostic(c: LiveContext) -> CheckResult:
    cid = "live-filter-diagnostic"
    findings: list[dict[str, Any]] = []
    report = ["", "=" * 80, "COMPREHENSIVE FILTER CONTEXT DIAGNOSTIC REPORT", "=" * 80, "",
              "1. User Identity Check..."]
    who = c.client.execute('EVALUATE ROW("User", USERPRINCIPALNAME())')
    if who.error:
        value = f"ERROR: {who.error[:50]}"
        findings.append({"name": "User Identity", "value": value, "level": "ERROR"})
        report.append(f"   ❌ Error: {who.error[:50]}")
    else:
        user = scalar(who.first, "User")
        findings.append({"name": "User Identity", "value": user, "level": "INFO"})
        report.append(f"   ✅ User: {user}")
    report += ["", "2. Calendar Table Row Count..."]
    cal = c.cfg["calendar_table"]
    r = c.client.execute(f'EVALUATE ROW("Count", COUNTROWS({quote_table(cal)}))')
    raw = None if r.error else scalar(r.first, "Count")
    if r.error:
        value = f"ERROR: {r.error[:50]}"
        findings.append({"name": "Calendar Rows", "value": value, "level": "ERROR"})
        report.append(f"   ❌ Error: {r.error[:50]}")
    elif raw is None or int(raw) == 0:
        value = "ERROR: count is BLANK or 0"
        findings.append({"name": "Calendar Rows", "value": value, "level": "ERROR"})
        report.append("   ❌ Error: count is BLANK or 0")
    else:
        n = int(raw)
        if n == 1:
            level = "CRITICAL"
            report.append(f"   🔴 CRITICAL: Only {n} row (expected 365+)")
        elif n < 100:
            level = "WARNING"
            report.append(f"   ⚠️  WARNING: Only {n} rows (expected 365+)")
        else:
            level = "OK"
            report.append(f"   ✅ OK: {n} rows")
        findings.append({"name": "Calendar Rows", "value": n, "level": level})
    report += ["", "3. Filter Context Check (COUNTROWS vs ALL)..."]
    dims = [t for t in c.cfg["filter_probe_tables"] if t.startswith(c.cfg["dimension_prefix"])
            and t != cal]
    if dims:
        table = dims[0]
        d = quote_table(table)
        cmp_ = c.client.execute(f'EVALUATE ROW( "Normal", COUNTROWS({d}), '
                                f'"WithALL", CALCULATE(COUNTROWS({d}), ALL({d})) )')
        if cmp_.error:
            value = f"ERROR: {cmp_.error[:50]}"
            findings.append({"name": "Filter Context", "value": value, "level": "ERROR"})
            report.append(f"   ❌ Error: {cmp_.error[:50]}")
        else:
            a, b = count(cmp_.first, "Normal"), count(cmp_.first, "WithALL")
            if a != b:
                value = f"DETECTED: {a} vs {b}"
                findings.append({"name": "Filter Context", "value": value, "level": "WARNING"})
                report.append(f"   ⚠️  WARNING: Filter detected ({a} vs {b})")
            else:
                value = "None detected"
                findings.append({"name": "Filter Context", "value": value, "level": "OK"})
                report.append(f"   ✅ OK: No filter context ({a} rows)")
    report += ["", "4. Dataset Refresh Status..."]
    hist = c.client.refreshes(1)
    if not hist:
        findings.append({"name": "Refresh Status", "value": "No history", "level": "INFO"})
        report.append("   ⚠️  No refresh history found")
    else:
        status = hist[0].get("status")
        level = "OK" if status == "Completed" else "WARNING"
        findings.append({"name": "Refresh Status", "value": status, "level": level})
        if status == "Completed":
            report.append("    ✅ Last refresh: Completed")
        else:
            report.append(f"   ⚠️  Last refresh: {status}")
    report += ["", "=" * 80, "DIAGNOSTIC SUMMARY", "=" * 80]
    groups = (("CRITICAL", "🔴 CRITICAL ISSUES:"), ("WARNING", "⚠️  WARNINGS:"),
              ("ERROR", "❌ ERRORS:"))
    counted = {level: [f for f in findings if f["level"] == level] for level, _ in groups}
    for level, title in groups:
        if counted[level]:
            report += ["", title]
            report += [f"   - {f['name']}: {f['value']}" for f in counted[level]]
    if not any(counted[level] for level, _ in groups):
        report += ["", "✅ All diagnostics passed - no filter context or RLS detected"]
    report += ["", "=" * 80, "RECOMMENDATIONS", "=" * 80]
    critical = counted["CRITICAL"]
    warnings = counted["WARNING"]
    if critical or warnings:
        report += ["", "1. Check Row-Level Security (RLS) settings in Fabric workspace:",
                   "   - Navigate to the dataset in Fabric",
                   "   - Check Security > Row-Level Security",
                   "   - Verify service principal is not assigned restrictive roles",
                   "", "2. Verify service principal permissions:",
                   "   - Ensure service principal has 'Read' access to workspace",
                   "   - Check if any workspace-level filters are applied",
                   "", "3. Review model for implicit filters:",
                   "   - Check calculation groups",
                   "   - Review any model-level filter expressions"]
    else:
        report += ["", "✅ No action required - data access appears unrestricted"]
    report += ["", "=" * 80]
    recs = []
    if critical or warnings:
        recs = ["check the RLS roles and the account the query runs as",
                "check the service principal's access to the workspace",
                "check calculation groups and model-level filters"]
    if critical:
        names = ", ".join(f["name"] for f in critical)
        return CheckResult(cid, "fail",
                           f"Critical issues detected: {names}. Row-Level Security or filter "
                           "context is likely limiting data access.",
                           {"findings": findings, "recommendations": recs}, report)
    return CheckResult(cid, "pass", f"{len(findings)} diagnostic finding(s)",
                       {"findings": findings, "recommendations": recs}, report)


# ---------------------------------------------------------------------------
# Best-practice analysis over the published metadata
# ---------------------------------------------------------------------------

BPA_RULES = [
    {"id": "DAX_DIVISION_USAGE", "name": "Avoid division operator (use DIVIDE function)",
     "category": "DAX Expressions", "severity": 3, "scope": "Measure",
     "description": "Measures should use DIVIDE() instead of / for better error handling",
     "fix": "Replace / with DIVIDE(numerator, denominator) for better error handling"},
    {"id": "DAX_FULLY_QUALIFIED_COLUMNS", "name": "Column references should be fully qualified",
     "category": "DAX Expressions", "severity": 2, "scope": "Measure",
     "description": "Use Table[Column] instead of [Column] for clarity",
     "fix": "Qualify every column reference with its table"},
    {"id": "PERF_CALCULATED_COLUMNS", "name": "Avoid calculated columns where possible",
     "category": "Performance", "severity": 2, "scope": "Column",
     "description": "Calculated columns can impact refresh performance",
     "fix": "Consider moving logic to M (Power Query) or creating a measure instead"},
    {"id": "META_HIDDEN_FOREIGN_KEYS", "name": "Hide foreign key columns from report view",
     "category": "Metadata", "severity": 2, "scope": "Column",
     "description": "Foreign keys should be hidden from end users",
     "fix": "Hide the key column used only by a relationship"},
    {"id": "NAME_MEASURE_DESCRIPTIONS", "name": "User-facing measures should have descriptions",
     "category": "Naming Conventions", "severity": 2, "scope": "Measure",
     "description": "Measures visible to users should include descriptions",
     "fix": "Add a description explaining what this measure calculates"},
]

BPA_ANALYSIS_FAILED = {
    "id": "BPA_ANALYSIS_FAILED", "name": "BPA Analysis Failed", "category": "System",
    "severity": 5, "scope": "Model",
    "description": "The analysis could not read the model's metadata",
    "fix": "Check model connectivity and permissions",
}


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

    def _violation(self, rid: str, obj: str, otype: str, message: str,
                   fix: Optional[str] = None) -> BPAViolation:
        r = self._rule(rid) if rid != "BPA_ANALYSIS_FAILED" else BPA_ANALYSIS_FAILED
        return BPAViolation(rid, r["name"], r["category"], r["severity"], obj, otype, message,
                            fix if fix is not None else r["fix"],
                            _dt.datetime.now().isoformat())

    def analyze_model(self) -> BPAReport:
        start = _dt.datetime.now()
        clock = time.perf_counter()
        out: list[BPAViolation] = []
        objects = 0
        try:
            m = self.client.execute('EVALUATE ADDCOLUMNS( INFO.MEASURES(), "HasDivision", '
                                    'SEARCH("/", [Expression], 1, 0) > 0, "HasDIVIDE", '
                                    'SEARCH("DIVIDE", [Expression], 1, 0) > 0 )')
            for row in [] if m.error else m.rows:
                expr = str(scalar(row, "Expression") or "")
                if "/" in expr and "divide" not in expr.lower():
                    name = str(row.get("[Name]", "Unknown"))
                    out.append(self._violation(
                        "DAX_DIVISION_USAGE", name, "Measure",
                        f"Measure '{name}' uses / operator instead of DIVIDE() function"))
            cols = self.client.execute("EVALUATE FILTER( INFO.COLUMNS(), [Type] = 2 )")
            for row in [] if cols.error else cols.rows:
                table = str(row.get("[TableName]", "Unknown"))
                column = str(row.get("[Name]", "Unknown"))
                out.append(self._violation(
                    "PERF_CALCULATED_COLUMNS", f"{table}[{column}]", "CalculatedColumn",
                    f"Calculated column '{column}' in table '{table}' may impact performance"))
            desc = self.client.execute('EVALUATE FILTER( INFO.MEASURES(), ISBLANK([Description]) '
                                       '|| [Description] = "" )')
            prefix = self.options["user_facing_prefix"]
            for row in [] if desc.error else desc.rows:
                name = str(row.get("[Name]", "Unknown"))
                table = str(row.get("[TableName]", "Unknown"))
                if name.startswith(prefix):
                    out.append(self._violation(
                        "NAME_MEASURE_DESCRIPTIONS", name, "Measure",
                        f"User-facing measure '{name}' in table '{table}' lacks description"))
            mc = self.client.execute('EVALUATE ROW("MeasureCount", COUNTROWS(INFO.MEASURES()))')
            cc = self.client.execute('EVALUATE ROW("ColumnCount", COUNTROWS(INFO.COLUMNS()))')
            if mc.error or cc.error:
                objects = 0
            else:
                objects = count(mc.first, "MeasureCount") + count(cc.first, "ColumnCount")
        except Exception as exc:  # noqa: BLE001 - one system finding instead of a crash
            out.append(self._violation("BPA_ANALYSIS_FAILED", "ModelAnalysis", "System",
                                       f"BPA analysis encountered an error: {exc}"))
        ms = max((time.perf_counter() - clock) * 1000, 0.001)
        return BPAReport(out, objects, ms, start)


def _severity_icon(severity: int) -> str:
    if severity >= 4:
        return "🔴"
    if severity == 3:
        return "🟠"
    if severity == 2:
        return "🟡"
    return "ℹ️"


def _bpa_report_lines(report: BPAReport, model: str) -> list[str]:
    lines = ["", "🔍 Running Fabric BPA analysis...",
             "", "=" * 80, "FABRIC BPA ANALYSIS REPORT", "=" * 80,
             f"Analysis completed: {report.timestamp}",
             f"Duration: {report.analysis_duration_ms:.2f}ms",
             f"Objects analyzed: {report.total_objects_analyzed}",
             "", "VIOLATION SUMMARY:",
             f"  🔴 Critical (4-5): {report.critical_count}",
             f"  🟠 Errors (3):     {report.error_count}",
             f"  🟡 Warnings (2):   {report.warning_count}",
             f"  ℹ️  Info (1):       {report.info_count}",
             f"  📊 Total:          {len(report.violations)}",
             ""]
    by_category: dict[str, list[BPAViolation]] = {}
    for v in report.violations:
        by_category.setdefault(v.category, []).append(v)
    if by_category:
        lines.append("VIOLATIONS BY CATEGORY:")
        for category in sorted(by_category):
            violations = by_category[category]
            lines += ["", f"{category}: {len(violations)} violations"]
            lines += [f"  {_severity_icon(v.severity)} {v.rule_name}: {v.object_name}"
                      for v in violations]
    else:
        lines.append("✅ No violations found!")
    lines += ["", "=" * 80]
    if by_category:
        lines += ["", f"📋 BPA Results Summary ({len(report.violations)} total violations):"]
        for category in sorted(by_category):
            violations = by_category[category]
            critical = sum(1 for v in violations if v.severity >= 4)
            errors = sum(1 for v in violations if v.severity == 3)
            warnings = sum(1 for v in violations if v.severity == 2)
            lines.append(f"  {category}: {len(violations)} violations ({critical} critical, "
                         f"{errors} errors, {warnings} warnings)")
    else:
        lines += ["", "✅ BPA Analysis: No violations found!"]
    lines += ["", "=" * 80, "FABRIC BPA AUDIT REPORT", "=" * 80,
              f"Generated: {_dt.datetime.now()}",
              f"Model: {model}",
              "", "1. ANALYSIS SUMMARY",
              f"   Duration: {report.analysis_duration_ms:.2f}ms",
              f"   Objects analyzed: {report.total_objects_analyzed}",
              f"   Rules evaluated: {len(BPA_RULES)}",
              "", "2. VIOLATION SUMMARY",
              f"   🔴 Critical (4-5): {report.critical_count}",
              f"   🟠 Errors (3):     {report.error_count}",
              f"   🟡 Warnings (2):   {report.warning_count}",
              f"   ℹ️  Info (1):       {report.info_count}",
              f"   📊 Total:          {len(report.violations)}",
              ""]
    if report.violations:
        lines.append("3. RULES TRIGGERED")
        counts: dict[str, int] = {}
        for v in report.violations:
            counts[v.rule_id] = counts.get(v.rule_id, 0) + 1
        for rule_id, count_ in sorted(counts.items(), key=lambda item: item[1], reverse=True):
            sample = next(v for v in report.violations if v.rule_id == rule_id)
            lines += [f"   {rule_id}: {count_} violations",
                      f"      Rule: {sample.rule_name}",
                      f"      Category: {sample.category}",
                      f"      Severity: {sample.severity}",
                      ""]
    lines.append("4. RECOMMENDATIONS")
    if report.critical_count:
        lines += ["   🚫 IMMEDIATE ACTION REQUIRED:",
                  "      Fix critical violations before deployment"]
    else:
        lines.append("   ✅ No critical violations - deployment ready")
    if report.error_count:
        lines.append(f"   🟠 Address {report.error_count} error-level violations")
    if report.warning_count:
        lines.append(f"   🟡 Consider fixing {report.warning_count} warning-level violations")
    lines += ["", "=" * 80]
    return lines


def check_bpa(c: LiveContext) -> CheckResult:
    cid = "live-bpa"
    health = c.client.health_check()
    if health.get("status") != "healthy":
        return CheckResult(cid, "fail", f"health check unhealthy: {health.get('error')}",
                           {"health": health})
    report = LiveBPA(c.client, c.cfg.get("bpa")).analyze_model()
    lines = _bpa_report_lines(report, str(c.client.dataset().get("workspaceName") or ""))
    cats: dict[str, int] = {}
    for v in report.violations:
        cats[v.category] = cats.get(v.category, 0) + 1
    details = {"by_category": cats, "objects": report.total_objects_analyzed,
               "duration_ms": report.analysis_duration_ms, "health": health,
               "violations": [asdict(v) for v in report.violations]}
    failures = [v for v in report.violations if v.rule_id == "BPA_ANALYSIS_FAILED"]
    if failures:
        failure = failures[0]
        return CheckResult(cid, "fail",
                           f"🚫 BPA analysis failed: {failure.message}\n"
                           f"Fix suggestion: {failure.fix_suggestion}\n\n"
                           "This indicates a problem with model connectivity or permissions.",
                           details, lines)
    critical = report.get_violations_by_severity(4)
    if critical:
        listed = "\n".join(f"  🔴 {v.rule_name}: {v.object_name} ({v.message})"
                           for v in critical)
        return CheckResult(cid, "fail",
                           f"🚫 {len(critical)} critical BPA violations found:\n{listed}\n\n"
                           "These violations must be fixed before deployment. "
                           "See BPA report for details and fix suggestions.", details, lines)
    if report.total_objects_analyzed == 0:
        return CheckResult(cid, "fail", "no objects could be analysed", details, lines)
    if report.analysis_duration_ms >= (c.cfg.get("bpa") or {}).get("max_duration_ms", 30000):
        return CheckResult(cid, "fail", "the analysis took too long", details, lines)
    return CheckResult(cid, "pass", f"{len(report.violations)} finding(s), none critical",
                       details, lines)


CHECKS: dict[str, Callable[[LiveContext], CheckResult]] = {
    "live-uniform-row-limit": check_uniform_row_limit,
    "live-calendar-rows": check_calendar_rows,
    "live-dimension-multirow": check_dimension_multirow,
    "live-calendar-vs-parameters": check_calendar_vs_parameters,
    "live-parameter-audit": check_parameter_audit,
    "live-table-sample": check_table_sample,
    "live-dimension-rows": check_dimension_rows,
    "live-measure-sample": check_measure_sample,
    "live-parameter-table-measures": check_parameter_table_measures,
    "live-refresh-status": check_refresh_status,
    "live-freshness": check_freshness,
    "live-smoke": check_smoke,
    "live-identity": check_identity,
    "live-filter-compare": check_filter_compare,
    "live-calendar-scan": check_calendar_scan,
    "live-metadata": check_metadata,
    "live-filter-diagnostic": check_filter_diagnostic,
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
