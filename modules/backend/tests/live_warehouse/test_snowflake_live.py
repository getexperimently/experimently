"""The Snowflake connector against a real account (founder-run; never in CI).

Run with ``WAREHOUSE_LIVE_TARGET=snowflake`` and the variables the runbook
lists::

    pytest -m warehouse_live modules/backend/tests/live_warehouse/

Before any statement uses the warehouse, ``SHOW WAREHOUSES`` must show it
under the resource monitor ``WAREHOUSE_LIVE_SF_RESOURCE_MONITOR`` names;
otherwise every check errors and nothing runs on it.  Every statement is
cancelled by Snowflake at the connection's limit (at most 120 s).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Tuple

import pytest
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from modules.backend.app.core.warehouse_identifiers import (
    SNOWFLAKE,
    render_column,
    render_table,
)
from modules.backend.app.services.warehouse_clients import (
    NUMERIC_TYPES,
    TIME_TYPES,
    WarehouseClient,
)
from modules.backend.app.services.warehouse_query_builder import (
    SNOWFLAKE_SQL,
    AnalysisWindow,
    AssignmentMapping,
    BuiltQuery,
    MetricMapping,
    build_metric_query,
)
from modules.backend.app.services.warehouse_sufficient_stats import (
    parse_float,
    parse_metric_rows,
)
from modules.backend.app.warehouse.deadlines import Deadline
from modules.backend.app.warehouse.errors import WarehouseError, WarehouseErrorCode
from modules.backend.app.warehouse.snowflake import (
    SnowflakeAdapter,
    SnowflakeConnection,
    SnowflakeKey,
)
from modules.backend.tests.live_warehouse import harness

pytestmark = pytest.mark.warehouse_live

OFFSET = SNOWFLAKE_SQL.session_offset
#: The fallback serialisation the connector's docstring names, recorded only.
FALLBACK_SERIALISE = (
    "TO_VARCHAR(CAST(0.1 AS DOUBLE) + CAST(0.2 AS DOUBLE), 'S9.9999999999999999EE')"
)
TIMEZONE_PROBE = (
    "SELECT TO_CHAR(CAST(CAST('2026-09-01 00:30:00' AS TIMESTAMP_NTZ) AS TIMESTAMP_TZ),"
    " 'YYYY-MM-DD HH24:MI:SS TZH:TZM') AS v, " + OFFSET + " AS session_offset"
)


@dataclass
class SnowflakeSession:
    config: Any
    adapter: SnowflakeAdapter
    client: WarehouseClient
    recording: Any
    key: SnowflakeKey
    exposures: Tuple[str, str, str]
    events: Tuple[str, str, str]
    columns: Dict[str, Dict[str, str]]

    def deadline(self, seconds: float = 0) -> Deadline:
        return Deadline(seconds or self.config.query_timeout_seconds + 30)


def _key(config) -> SnowflakeKey:
    password = config.key_passphrase.encode() if config.key_passphrase else None
    return SnowflakeKey(load_pem_private_key(config.key_pem, password=password))


def _adapter(config, key, recording, timeout: int) -> SnowflakeAdapter:
    return SnowflakeAdapter(
        SnowflakeConnection(
            account=config.account,
            user=config.user,
            role=config.role,
            warehouse=config.warehouse,
            query_timeout_seconds=timeout,
        ),
        key,
        client_factory=recording,
    )


def _verify_spend_cap(adapter: SnowflakeAdapter, config, recorder) -> None:
    """Refuse to go on unless the warehouse is under the named resource monitor.

    ``SHOW WAREHOUSES`` is a metadata command, so it is not expected to resume
    the warehouse; the evidence records the state it reports.
    """
    name = config.warehouse  # passed the connection's fullmatch check
    _, rows, _ = adapter._execute(f"SHOW WAREHOUSES LIKE '{name}'", Deadline(60))
    match = [r for r in rows if (r.get("name") or "").upper() == name.upper()]
    seen = {
        key: match[0].get(key) if match else None
        for key in ("name", "size", "auto_suspend", "resource_monitor", "state", "type")
    }
    recorder.record(
        "sf_spend_cap",
        declared_resource_monitor=config.resource_monitor,
        warehouse=seen,
    )
    monitor = (seen.get("resource_monitor") or "").strip()
    if not match:
        raise AssertionError(
            f"SHOW WAREHOUSES does not list {name} for role {config.role}; grant the "
            "role USAGE on it (see the runbook)."
        )
    if monitor.upper() != config.resource_monitor.upper():
        raise AssertionError(
            f"warehouse {name} reports resource_monitor={monitor or 'null'}, not "
            f"{config.resource_monitor}. Assign the monitor to the warehouse itself "
            "(ALTER WAREHOUSE ... SET RESOURCE_MONITOR = ...); if it is assigned and "
            "still shows null, grant the role MONITOR on the warehouse. Nothing else "
            "has run."
        )


@pytest.fixture(scope="session")
def sf(live_config, recorder, current_check) -> SnowflakeSession:
    key = _key(live_config)
    recording = harness.recording_factory(recorder, "snowflake", current_check)
    adapter = _adapter(live_config, key, recording, live_config.query_timeout_seconds)
    _verify_spend_cap(adapter, live_config, recorder)
    recorder.record(
        "sf_session",
        host=adapter.connection.host,
        jwt_account=adapter.connection.jwt_account,
        public_key_fingerprint=key.fingerprint,
    )
    client = WarehouseClient(
        "snowflake",
        adapter,
        SNOWFLAKE_SQL,
        TIME_TYPES["snowflake"],
        NUMERIC_TYPES["snowflake"],
    )
    return SnowflakeSession(
        config=live_config,
        adapter=adapter,
        client=client,
        recording=recording,
        key=key,
        exposures=(
            live_config.database,
            live_config.schema,
            harness.EXPOSURES_TABLE.upper(),
        ),
        events=(live_config.database, live_config.schema, harness.EVENTS_TABLE.upper()),
        columns={},
    )


@pytest.fixture(scope="session")
def fixture_arrays():
    return harness.live_fixture()


@pytest.fixture(scope="session")
def reference(fixture_arrays):
    return harness.exact_reference(*fixture_arrays)


@pytest.fixture(scope="session")
def columns(sf, recorder) -> Dict[str, Dict[str, str]]:
    if not sf.columns:
        for name, table, wanted in (
            ("exposures", sf.exposures, harness.EXPOSURE_COLUMNS),
            ("events", sf.events, harness.EVENT_COLUMNS),
        ):
            reported = sf.adapter.table_columns(table, sf.deadline())
            recorder.record("sf_table_columns", **{name: [list(c) for c in reported]})
            sf.columns[name] = harness.resolve_fixture_columns(
                sf.client, reported, wanted
            )
    return sf.columns


def _run(sf, sql: str, tables=frozenset()):
    built = BuiltQuery(kind="preview", dialect="snowflake", sql=sql, tables=tables)
    return sf.adapter.run_query(built, sf.deadline())


def _statement(result) -> Dict[str, Any]:
    return {
        "statement_handle": result.statement_handle,
        "warehouse": result.warehouse,
        "elapsed_ms": result.elapsed_ms,
    }


# -- the checks, in order -------------------------------------------------------------


def test_sf_spend_cap(sf, recorder):
    """The warehouse is under the declared resource monitor (checked by the fixture)."""
    seen = recorder.checks["sf_spend_cap"]["warehouse"]
    assert (
        seen["resource_monitor"] or ""
    ).upper() == sf.config.resource_monitor.upper()


def test_sf_sign_in(sf, recorder):
    """NOT VERIFIED 2 and 8: a key-pair JWT is accepted by the SQL API on this account."""
    check = sf.adapter.check_connection(Deadline(30))
    recorder.record(
        "sf_sign_in",
        host=sf.adapter.connection.host,
        account=sf.config.account,
        role=check.role,
        warehouse=check.warehouse,
        session_offset=check.session_offset,
    )
    assert (check.role or "").upper() == sf.config.role.upper()
    assert (check.warehouse or "").upper() == sf.config.warehouse.upper()


def test_sf_timezone(sf, recorder):
    """A TIMESTAMP_NTZ is read as UTC in our sessions, whatever the account default."""
    result = _run(sf, TIMEZONE_PROBE)
    text = result.rows[0]["v"]
    account_default: Dict[str, Any] = {}
    try:
        _, rows, _ = sf.adapter._execute(
            "SHOW PARAMETERS LIKE 'TIMEZONE' IN ACCOUNT", sf.deadline()
        )
        account_default = {
            "value": rows[0].get("value") if rows else None,
            "level": rows[0].get("level") if rows else None,
        }
    except WarehouseError as exc:  # recorded, not required
        account_default = {
            "unavailable": exc.code.value,
            "vendor_code": exc.vendor_code,
        }
    recorder.record(
        "sf_timezone",
        probe=TIMEZONE_PROBE,
        text=text,
        session_offset=result.rows[0].get("session_offset"),
        account_timezone=account_default,
        **_statement(result),
    )
    assert text == "2026-09-01 00:30:00 +00:00", text


def test_sf_wire_probe(sf, recorder):
    """NOT VERIFIED 3: CAST(CAST(0.1 + 0.2 AS DECFLOAT) AS VARCHAR) reads back exactly."""
    sql = harness.wire_probe_sql(SNOWFLAKE_SQL)
    result = _run(sf, sql)
    text = result.rows[0]["v"]
    fallback: Dict[str, Any] = {}
    try:
        other = _run(
            sf, f"SELECT {FALLBACK_SERIALISE} AS v, {OFFSET} AS session_offset"
        )
        fallback = {"text": other.rows[0]["v"], "handle": other.statement_handle}
        try:
            fallback["parses_to_probe"] = (
                parse_float(other.rows[0]["v"], "v")[0] == harness.WIRE_PROBE_VALUE
            )
        except Exception as exc:  # the product's parser refused it
            fallback["parses_to_probe"] = False
            fallback["parse_error"] = type(exc).__name__
    except WarehouseError as exc:
        fallback = {"refused": exc.code.value, "vendor_code": exc.vendor_code}
    recorder.record(
        "sf_wire_probe", sql=sql, text=text, fallback=fallback, **_statement(result)
    )
    value, _ = parse_float(text, "v")  # the product's parser
    assert value == harness.WIRE_PROBE_VALUE, text
    assert float(text) == 0.30000000000000004


def test_sf_table_columns(columns, recorder):
    recorder.record("sf_table_columns", resolved=columns)
    assert set(columns["exposures"]) == set(harness.EXPOSURE_COLUMNS)
    assert set(columns["events"]) == set(harness.EVENT_COLUMNS)


def test_sf_load_fidelity(sf, columns, fixture_arrays, recorder):
    """The loaded amounts are exactly the fixture's binary64 values (a few spot rows)."""
    control, treatment = fixture_arrays
    wanted = {
        "control-0": float(control[0]),
        "control-1": float(control[1]),
        "treatment-0": float(treatment[0]),
        f"treatment-{len(treatment) - 1}": float(treatment[-1]),
    }
    e = columns["events"]
    unit = render_column(SNOWFLAKE, e["user_id"], "user_id")
    amount = render_column(SNOWFLAKE, e["amount"], "amount")
    ids = ", ".join(f"'{u}'" for u in wanted)  # fixed ids of [a-z0-9-]
    sql = (
        f"SELECT CAST({unit} AS VARCHAR) AS unit_id, "
        f"{SNOWFLAKE_SQL.serialise(amount)} AS amount, {OFFSET} AS session_offset "
        f"FROM {render_table(SNOWFLAKE, sf.events)} WHERE {unit} IN ({ids})"
    )
    result = _run(sf, sql, frozenset({sf.events}))
    seen = {row["unit_id"]: row["amount"] for row in result.rows}
    recorder.record("sf_load_fidelity", rows=seen, **_statement(result))
    assert set(seen) == set(wanted)
    for unit_id, expected in wanted.items():
        assert parse_float(seen[unit_id], "amount")[0] == expected, unit_id


def test_sf_mean_parity(sf, columns, reference, recorder):
    """F-MEAN-1 through DECFLOAT and the JSON wire, within rel 1e-12."""
    a, e = columns["exposures"], columns["events"]
    built = build_metric_query(
        SNOWFLAKE_SQL,
        AssignmentMapping(
            sf.exposures,
            a["user_id"],
            a["experiment_key"],
            a["variant"],
            a["exposed_at"],
        ),
        MetricMapping(sf.events, e["user_id"], e["event_at"], "mean", e["amount"]),
        harness.EXPERIMENT_KEY,
        AnalysisWindow(harness.WINDOW_START, harness.WINDOW_END),
    )
    result = sf.adapter.run_query(built, sf.deadline())
    stats = parse_metric_rows(list(result.rows), expect_session_offset=True)
    errors = harness.mean_parity_errors(stats, reference)
    worst = max(errors.values())
    recorder.record(
        "sf_mean_parity",
        tolerance=harness.F_MEAN_1_TOLERANCE,
        worst_relative_error=worst,
        relative_errors=errors,
        k_text=stats.k_text,
        variants=[
            {
                "variant": v.variant,
                "n": v.n,
                "sum_d": v.sum_d_text,
                "sum_d2": v.sum_d2_text,
            }
            for v in stats.variants
        ],
        session_offset=stats.session_offset,
        sql_sha256=built.sha256,
        **_statement(result),
    )
    assert worst <= harness.F_MEAN_1_TOLERANCE, errors


def test_sf_runner_parity(sf, columns, fixture_arrays, recorder):
    """The run executor over the real warehouse equals it over the DuckDB oracle."""
    plan = harness.run_plan(sf.client, sf.exposures, sf.events, columns)
    real = harness.execute_plan(
        plan, Deadline(3 * sf.config.query_timeout_seconds + 60)
    )
    oracle_client, o_exposures, o_events, o_columns = harness.duckdb_oracle(
        *fixture_arrays
    )
    oracle = harness.execute_plan(
        harness.run_plan(oracle_client, o_exposures, o_events, o_columns), Deadline(600)
    )
    problems = harness.compare_results(real["results"], oracle["results"])
    recorder.record(
        "sf_runner_parity",
        results=real["results"],
        job_metadata=real["job_metadata"],
        differences=problems,
    )
    assert not problems, problems


def test_sf_multi_statement_refused(sf, recorder):
    """Two statements in one request are refused (multi_statement_count = 1)."""
    with pytest.raises(WarehouseError) as refused:
        sf.adapter._execute("SELECT 1; SELECT 2", sf.deadline())
    recorder.record(
        "sf_multi_statement_refused",
        refused=refused.value.code.value,
        vendor_code=refused.value.vendor_code,
    )
    assert refused.value.code is WarehouseErrorCode.NOT_A_SELECT


def test_sf_create_refused(sf, recorder):
    """NOT VERIFIED 11: the role cannot create a table in the fixture's schema."""
    table = render_table(
        SNOWFLAKE, (sf.config.database, sf.config.schema, harness.PROBE_TABLE.upper())
    )
    sql = f"CREATE TABLE {table} (x INT)"
    refused = None
    try:
        sf.adapter._execute(sql, sf.deadline(), sf.config.database)
    except WarehouseError as exc:
        refused = exc
    recorder.record(
        "sf_create_refused",
        sql=sql,
        refused=refused.code.value if refused else None,
        vendor_code=refused.vendor_code if refused else None,
        created=refused is None,
    )
    assert refused is not None, (
        f"role {sf.config.role} CREATED {table}; drop it and revoke what allowed it"
    )
    assert refused.code is WarehouseErrorCode.PERMISSION_DENIED, (
        refused.code,
        refused.vendor_code,
    )


def test_sf_time_limit(sf, recorder):
    """Snowflake cancels a statement at the connection's limit, and history shows it ended."""
    short = _adapter(sf.config, sf.key, sf.recording, harness.SF_TAMPER_TIMEOUT_SECONDS)
    before = len(recorder.exchanges)
    started = time.monotonic()
    with pytest.raises(WarehouseError) as stopped:
        short._execute(harness.SF_LONG_RUNNING_SQL, Deadline(90))
    waited = time.monotonic() - started
    handles = [
        x["body"]["statementHandle"]
        for x in recorder.exchanges[before:]
        if isinstance(x.get("body"), dict)
        and x["request"].get("method") == "POST"
        and x["request"].get("path") == "/api/v2/statements"
        and isinstance(x["body"].get("statementHandle"), str)
    ]
    history: Dict[str, Any] = {}
    handle = handles[0] if handles else None
    if handle is not None:
        database = render_column(SNOWFLAKE, sf.config.database, "database")
        sql = (
            "SELECT EXECUTION_STATUS AS execution_status, ERROR_CODE AS error_code, "
            f"TOTAL_ELAPSED_TIME AS total_elapsed_time, {OFFSET} AS session_offset "
            f"FROM TABLE({database}.INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER("
            "RESULT_LIMIT => 1000)) "
            f"WHERE QUERY_ID = '{handle}'"  # a UUID the adapter already checked
        )
        for _ in range(6):
            _, rows, _ = sf.adapter._execute(sql, sf.deadline(), sf.config.database)
            if rows and (rows[0].get("execution_status") or "").upper() not in (
                "RUNNING",
                "QUEUED",
                "RESUMING_WAREHOUSE",
            ):
                history = dict(rows[0])
                break
            history = dict(rows[0]) if rows else {"found": False}
            time.sleep(5)
    recorder.record(
        "sf_time_limit",
        timeout_seconds=harness.SF_TAMPER_TIMEOUT_SECONDS,
        sql=harness.SF_LONG_RUNNING_SQL,
        stopped=stopped.value.code.value,
        vendor_code=stopped.value.vendor_code,
        seconds_waited=round(waited, 1),
        statement_handle=handle,
        query_history=history,
    )
    assert stopped.value.code is WarehouseErrorCode.TIME_LIMIT
    # 000630 is Snowflake's own "reached its time limit": the server stopped it,
    # not our client-side deadline.
    assert stopped.value.vendor_code == "000630", stopped.value.vendor_code
    assert handle is not None, "no statement handle was recorded"
    status = (history.get("execution_status") or "").upper()
    assert status and status not in ("RUNNING", "QUEUED", "RESUMING_WAREHOUSE"), history
