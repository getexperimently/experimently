"""A whole analysis through the real BigQuery connector, on recorded answers.

The connector, its client, the destination and address checks and the
deadlines all run; only the network is the recorded-response Google fake from
the connector's own tests.  Nothing leaves the machine.
"""

from __future__ import annotations

import pytest

from modules.backend.tests.integration.warehouse import recording_estimator
from modules.backend.tests.integration.warehouse.conftest import (
    WA,
    bigquery_client_factory,
    ts,
)
from modules.backend.tests.integration.warehouse.test_connections_api import (
    bigquery_body,
)
from modules.backend.tests.unit.warehouse.google_fake import GoogleFake, Script

pytestmark = [pytest.mark.integration, pytest.mark.modules]

DIAGNOSTICS = {
    "kind": "bigquery#getQueryResultsResponse",
    "jobReference": {"projectId": "acme-analytics", "jobId": "JOBID", "location": "US"},
    "jobComplete": True,
    "totalRows": "1",
    "schema": {
        "fields": [
            {"name": name, "type": "INTEGER", "mode": "NULLABLE"}
            for name in (
                "exposure_rows",
                "null_key_rows",
                "units",
                "multi_variant_units",
                "variant_values",
            )
        ]
    },
    "rows": [{"f": [{"v": "2100"}, {"v": "3"}, {"v": "2004"}, {"v": "4"}, {"v": "2"}]}],
}


def test_a_proportion_run_through_the_bigquery_connector(wh, service_account_pem):
    fake = GoogleFake(
        Script(
            {
                "token": ["token_ok"],
                "table": ["table_get"],
                "dry_run": ["dry_run_select"],
                "insert": ["insert_running"],
                "results": [(200, DIAGNOSTICS), "query_results_metric"],
                "job": ["job_done"],
            }
        )
    )
    wh.google_factory = bigquery_client_factory(fake)
    admin = wh.as_("ADMIN")
    connection = admin.post(
        f"{WA}/connections", json=bigquery_body(service_account_pem)
    )
    assert connection.status_code == 201, connection.text
    connection_id = connection.json()["id"]
    columns = {
        "unit_id": "user_id",
        "experiment_key": "experiment",
        "variant": "variant",
        "exposed_at": "exposed_at",
    }
    assignment = wh.assignment_source(
        admin, connection_id, table="acme-data.events.exposures", columns=columns
    )
    metric = wh.metric_source(
        admin,
        connection_id,
        table="acme-data.events.exposures",
        columns={"unit_id": "user_id", "event_at": "exposed_at"},
    )
    for source in (assignment, metric):
        validated = wh.validate(admin, source["id"])
        assert validated["source"]["validated_at"] is not None
    experiment = wh.experiment(end=ts(10))
    response = wh.start_run(
        admin,
        experiment,
        {
            "connection_id": connection_id,
            "assignment_source_id": assignment["id"],
            "metric_source_id": metric["id"],
        },
    )
    assert response.status_code == 202, response.text
    run = wh.wait_for_run(admin, response.json()["run_id"])
    assert run["status"] == "succeeded", run

    counts = [
        (v["variant_name"], v["n"], v["n_converted"])
        for v in recording_estimator.CALLS[-1]["variants"]
    ]
    assert counts == [("control", 1000, 100), ("treatment", 1000, 110)]
    assert run["results"]["diagnostics"]["multi_variant_units"] == 4
    assert [m["statement"] for m in run["job_metadata"]] == ["diagnostics", "metric"]
    assert all(m["total_bytes_billed"] == 10485760 for m in run["job_metadata"])
    assert all(m["job_id"].startswith("experimently_") for m in run["job_metadata"])
    # BigQuery statements, in BigQuery's dialect.
    assert all(s["dialect"] == "bigquery" for s in run["statements"])
    assert "`acme-data`.`events`.`exposures`" in run["statements"][1]["sql"]
    assert {r.host for r in fake.requests} == {
        "oauth2.googleapis.com",
        "bigquery.googleapis.com",
    }
