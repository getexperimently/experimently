"""The BigQuery connector against a real project (founder-run; never in CI).

Run with ``WAREHOUSE_LIVE_TARGET=bigquery`` and the variables the runbook
lists::

    pytest -m warehouse_live modules/backend/tests/live_warehouse/

Every statement is dry-run first; each is capped at the connection's
``maximumBytesBilled`` and the session at a byte budget (``harness``).  The
key is the service account's JSON key, read from the file
``WAREHOUSE_LIVE_BQ_KEY_FILE`` names and checked by the product's own parser.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Tuple

import pytest

from modules.backend.app.core.warehouse_identifiers import (
    BIGQUERY,
    render_column,
    render_table,
)
from modules.backend.app.services.warehouse_clients import (
    NUMERIC_TYPES,
    TIME_TYPES,
    WarehouseClient,
)
from modules.backend.app.services.warehouse_query_builder import (
    BIGQUERY_SQL,
    AnalysisWindow,
    AssignmentMapping,
    BuiltQuery,
    MetricMapping,
    build_diagnostics_query,
    build_metric_query,
)
from modules.backend.app.services.warehouse_sufficient_stats import (
    parse_float,
    parse_metric_rows,
)
from modules.backend.app.warehouse.bigquery import (
    AccessTokenCache,
    BigQueryConnection,
    parse_service_account_json,
)
from modules.backend.app.warehouse.deadlines import Deadline
from modules.backend.app.warehouse.errors import WarehouseError, WarehouseErrorCode
from modules.backend.tests.live_warehouse import harness

pytestmark = pytest.mark.warehouse_live

QUERY_TIMEOUT_SECONDS = 60


@dataclass
class BigQuerySession:
    config: Any
    adapter: Any
    client: WarehouseClient
    recording: Any
    exposures: Tuple[str, str, str]
    events: Tuple[str, str, str]
    columns: Dict[str, Dict[str, str]]

    def deadline(self, seconds: float = QUERY_TIMEOUT_SECONDS + 30) -> Deadline:
        return Deadline(seconds)


def _adapter(config, key, recording, budget, max_bytes, location=None):
    return harness.capped_bigquery_adapter(
        BigQueryConnection(
            billing_project=config.project,
            location=location or config.location,
            max_bytes_per_query=max_bytes,
            query_timeout_seconds=QUERY_TIMEOUT_SECONDS,
        ),
        key,
        client_factory=recording,
        token_cache=AccessTokenCache(),
        budget=budget,
    )


@pytest.fixture(scope="session")
def bq(live_config, recorder, current_check) -> BigQuerySession:
    key = parse_service_account_json(live_config.key_json)  # the product's parser
    recording = harness.recording_factory(recorder, "bigquery", current_check)
    budget = harness.ByteBudget()
    adapter = _adapter(
        live_config, key, recording, budget, live_config.max_bytes_per_query
    )
    client = WarehouseClient(
        "bigquery",
        adapter,
        BIGQUERY_SQL,
        TIME_TYPES["bigquery"],
        NUMERIC_TYPES["bigquery"],
    )
    session = BigQuerySession(
        config=live_config,
        adapter=adapter,
        client=client,
        recording=recording,
        exposures=(live_config.project, live_config.dataset, harness.EXPOSURES_TABLE),
        events=(live_config.project, live_config.dataset, harness.EVENTS_TABLE),
        columns={},
    )
    recorder.record(
        "bq_session",
        service_account=key.client_email,
        key_id_sha256=hashlib.sha256(key.private_key_id.encode()).hexdigest()[:16],
    )
    yield session
    recorder.record(
        "bq_session",
        dry_run_bytes_charged=budget.spent,
        session_budget_bytes=budget.limit,
    )


@pytest.fixture(scope="session")
def fixture_arrays():
    control, treatment = harness.live_fixture()
    return control, treatment


@pytest.fixture(scope="session")
def reference(fixture_arrays):
    return harness.exact_reference(*fixture_arrays)


@pytest.fixture(scope="session")
def columns(bq, recorder) -> Dict[str, Dict[str, str]]:
    if not bq.columns:
        for name, table, wanted in (
            ("exposures", bq.exposures, harness.EXPOSURE_COLUMNS),
            ("events", bq.events, harness.EVENT_COLUMNS),
        ):
            reported = bq.adapter.table_columns(table, bq.deadline())
            recorder.record("bq_table_columns", **{name: [list(c) for c in reported]})
            bq.columns[name] = harness.resolve_fixture_columns(
                bq.client, reported, wanted
            )
    return bq.columns


def _run(bq, sql: str, tables=frozenset()):
    built = BuiltQuery(kind="preview", dialect="bigquery", sql=sql, tables=tables)
    return bq.adapter.run_query(built, bq.deadline())


def _job(result) -> Dict[str, Any]:
    return {
        "job_id": result.job_id,
        "location": result.location,
        "total_bytes_processed": result.total_bytes_processed,
        "total_bytes_billed": result.total_bytes_billed,
        "elapsed_ms": result.elapsed_ms,
    }


def _mean_query(bq, columns) -> BuiltQuery:
    a, e = columns["exposures"], columns["events"]
    return build_metric_query(
        BIGQUERY_SQL,
        AssignmentMapping(
            bq.exposures,
            a["user_id"],
            a["experiment_key"],
            a["variant"],
            a["exposed_at"],
        ),
        MetricMapping(bq.events, e["user_id"], e["event_at"], "mean", e["amount"]),
        harness.EXPERIMENT_KEY,
        AnalysisWindow(harness.WINDOW_START, harness.WINDOW_END),
    )


# -- the checks, in order -------------------------------------------------------------


def test_bq_sign_in(bq, recorder):
    """NOT VERIFIED 1: the sandbox's service-account key signs in and may dry-run."""
    dry = bq.adapter.check_connection(bq.deadline(30))
    recorder.record(
        "bq_sign_in",
        signed_in=True,
        connection_test_statement_type=dry.statement_type,
        connection_test_bytes=dry.total_bytes_processed,
    )
    assert dry.statement_type == "SELECT"


def test_bq_wire_probe(bq, recorder):
    """NOT VERIFIED 7: FORMAT('%.17g', 0.1 + 0.2) reads back as exactly 0.30000000000000004."""
    result = _run(bq, harness.wire_probe_sql(BIGQUERY_SQL))
    text = result.rows[0]["v"]
    value, kept = parse_float(text, "v")  # the product's parser
    recorder.record(
        "bq_wire_probe",
        sql=harness.wire_probe_sql(BIGQUERY_SQL),
        text=text,
        **_job(result),
    )
    assert value == harness.WIRE_PROBE_VALUE, text
    assert float(text) == 0.30000000000000004


def test_bq_table_columns(columns, recorder):
    recorder.record("bq_table_columns", resolved=columns)
    assert set(columns["exposures"]) == set(harness.EXPOSURE_COLUMNS)
    assert set(columns["events"]) == set(harness.EVENT_COLUMNS)


def test_bq_load_fidelity(bq, columns, fixture_arrays, recorder):
    """The loaded amounts are exactly the fixture's binary64 values (a few spot rows)."""
    control, treatment = fixture_arrays
    wanted = {
        "control-0": float(control[0]),
        "control-1": float(control[1]),
        "treatment-0": float(treatment[0]),
        f"treatment-{len(treatment) - 1}": float(treatment[-1]),
    }
    e = columns["events"]
    unit = render_column(BIGQUERY, e["user_id"], "user_id")
    amount = render_column(BIGQUERY, e["amount"], "amount")
    ids = ", ".join(f"'{u}'" for u in wanted)  # fixed ids of [a-z0-9-]
    sql = (
        f"SELECT CAST({unit} AS STRING) AS unit_id, "
        f"{BIGQUERY_SQL.serialise(amount)} AS amount "
        f"FROM {render_table(BIGQUERY, bq.events)} WHERE {unit} IN ({ids})"
    )
    result = _run(bq, sql, frozenset({bq.events}))
    seen = {row["unit_id"]: row["amount"] for row in result.rows}
    recorder.record("bq_load_fidelity", rows=seen, **_job(result))
    assert set(seen) == set(wanted)
    for unit_id, expected in wanted.items():
        assert parse_float(seen[unit_id], "amount")[0] == expected, unit_id


def test_bq_dry_run_statement_type(bq, columns, recorder):
    """NOT VERIFIED 4: the dry run's statementType for our generated statements."""
    a = columns["exposures"]
    diagnostics = build_diagnostics_query(
        BIGQUERY_SQL,
        AssignmentMapping(
            bq.exposures,
            a["user_id"],
            a["experiment_key"],
            a["variant"],
            a["exposed_at"],
        ),
        harness.EXPERIMENT_KEY,
        AnalysisWindow(harness.WINDOW_START, harness.WINDOW_END),
    )
    found = {}
    with bq.recording(bq.deadline()) as client:
        for kind, built in (
            ("metric", _mean_query(bq, columns)),
            ("diagnostics", diagnostics),
        ):
            dry = bq.adapter.dry_run(client, built.sql)
            found[kind] = {
                "statement_type": dry.statement_type,
                "total_bytes_processed": dry.total_bytes_processed,
                "sql_sha256": built.sha256,
            }
    recorder.record("bq_dry_run_statement_type", **found)
    assert {v["statement_type"] for v in found.values()} == {"SELECT"}


def test_bq_mean_parity(bq, columns, reference, recorder):
    """F-MEAN-1 through the real wire, within rel 1e-12 of the exact reference."""
    built = _mean_query(bq, columns)
    result = bq.adapter.run_query(built, bq.deadline())
    stats = parse_metric_rows(list(result.rows))
    errors = harness.mean_parity_errors(stats, reference)
    worst = max(errors.values())
    recorder.record(
        "bq_mean_parity",
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
        sql_sha256=built.sha256,
        **_job(result),
    )
    assert worst <= harness.F_MEAN_1_TOLERANCE, errors


def test_bq_runner_parity(bq, columns, fixture_arrays, recorder):
    """The run executor over the real warehouse equals it over the DuckDB oracle."""
    plan = harness.run_plan(bq.client, bq.exposures, bq.events, columns)
    real = harness.execute_plan(plan, Deadline(3 * QUERY_TIMEOUT_SECONDS + 60))
    oracle_client, o_exposures, o_events, o_columns = harness.duckdb_oracle(
        *fixture_arrays
    )
    oracle = harness.execute_plan(
        harness.run_plan(oracle_client, o_exposures, o_events, o_columns), Deadline(600)
    )
    problems = harness.compare_results(real["results"], oracle["results"])
    recorder.record(
        "bq_runner_parity",
        results=real["results"],
        job_metadata=real["job_metadata"],
        differences=problems,
    )
    assert not problems, problems


def test_bq_create_refused(bq, recorder):
    """NOT VERIFIED 11: the service account cannot create a table.

    Dry-run first, then the statement itself, sent past the adapter's own
    SELECT-only check so that any refusal is BigQuery's.
    """
    table = render_table(
        BIGQUERY, (bq.config.project, bq.config.dataset, harness.PROBE_TABLE)
    )
    sql = f"CREATE TABLE {table} (x INT64)"
    outcome: Dict[str, Any] = {"sql": sql}
    deadline = bq.deadline()
    with bq.recording(deadline) as client:
        try:
            dry = bq.adapter.dry_run(client, sql)
            outcome["dry_run"] = {
                "accepted": True,
                "statement_type": dry.statement_type,
            }
        except WarehouseError as exc:
            outcome["dry_run"] = {
                "refused": exc.code.value,
                "vendor_code": exc.vendor_code,
            }
        job_id = bq.adapter._new_job_id()
        refused = None
        try:
            bq.adapter._insert(client, sql, job_id, deadline)
            bq.adapter._wait(client, job_id, deadline)
        except WarehouseError as exc:
            refused = exc
    outcome["job_id"] = job_id
    outcome["statement"] = (
        {
            "refused": refused.code.value,
            "vendor_code": refused.vendor_code,
            "http_status": refused.http_status,
        }
        if refused
        else {"created": True}
    )
    recorder.record("bq_create_refused", **outcome)
    assert refused is not None, (
        f"the service account CREATED {table}; drop it and remove the role that allowed it"
    )
    assert refused.code is WarehouseErrorCode.PERMISSION_DENIED, outcome


def test_bq_dry_run_refuses_over_cap(bq, live_config, recorder):
    """A query over the cap is refused on its dry-run estimate; nothing runs."""
    key = parse_service_account_json(live_config.key_json)
    small = _adapter(
        live_config,
        key,
        bq.recording,
        harness.ByteBudget(),
        harness.BQ_TAMPER_MAX_BYTES,
        location="US",
    )
    before = len(recorder.exchanges)
    with pytest.raises(WarehouseError) as refused:
        _run_with(small, harness.BQ_LARGE_PUBLIC_SQL, Deadline(90))
    sent = recorder.exchanges[before:]
    inserts = [
        x["request"]
        for x in sent
        if x["request"].get("method") == "POST"
        and x["request"]["path"].endswith("/jobs")
    ]
    recorder.record(
        "bq_dry_run_refuses_over_cap",
        cap_bytes=harness.BQ_TAMPER_MAX_BYTES,
        estimate_bytes=[d.total_bytes_processed for d in small.dry_runs],
        refused=refused.value.code.value,
        job_inserts=inserts,
    )
    assert refused.value.code is WarehouseErrorCode.BYTES_LIMIT
    assert inserts and all(r.get("dry_run") is True for r in inserts), inserts


def _run_with(adapter, sql: str, deadline: Deadline):
    built = BuiltQuery(kind="preview", dialect="bigquery", sql=sql, tables=frozenset())
    return adapter.run_query(built, deadline)


def test_bq_bytes_billed_cap_enforced(bq, live_config, recorder):
    """BigQuery itself refuses a job over ``maximumBytesBilled`` (sent past our dry-run check)."""
    key = parse_service_account_json(live_config.key_json)
    small = _adapter(
        live_config,
        key,
        bq.recording,
        harness.ByteBudget(),
        harness.BQ_TAMPER_MAX_BYTES,
        location="US",
    )
    deadline = Deadline(120)
    outcome: Dict[str, Any] = {"cap_bytes": harness.BQ_TAMPER_MAX_BYTES}
    refused = None
    with bq.recording(deadline) as client:
        dry = small.dry_run(client, harness.BQ_LARGE_PUBLIC_SQL)  # dry-run first
        outcome["estimate_bytes"] = dry.total_bytes_processed
        assert dry.total_bytes_processed > harness.BQ_TAMPER_MAX_BYTES, (
            "the probe table no longer exceeds the cap; pick a larger one"
        )
        job_id = small._new_job_id()
        try:
            small._insert(client, harness.BQ_LARGE_PUBLIC_SQL, job_id, deadline)
            small._wait(client, job_id, deadline)
        except WarehouseError as exc:
            refused = exc
    outcome["job_id"] = job_id
    outcome["refused"] = (
        {"code": refused.code.value, "vendor_code": refused.vendor_code}
        if refused
        else None
    )
    recorder.record("bq_bytes_billed_cap_enforced", **outcome)
    assert refused is not None, "BigQuery ran a job over maximumBytesBilled"
    assert refused.code is WarehouseErrorCode.BYTES_LIMIT, outcome
    assert refused.vendor_code == "bytesBilledLimitExceeded", outcome
