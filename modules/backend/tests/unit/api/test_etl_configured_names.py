"""The ETL routes act only on the Glue names the deployment configured (#565).

``GET /etl/jobs/{run_id}/status`` accepts ``GLUE_ETL_JOB_NAME`` or
``GLUE_METRICS_JOB_NAME``; the crawler routes accept ``GLUE_CRAWLER_NAME``
(the default when the name is omitted); ``POST /etl/partitions/add`` accepts
only ``GLUE_DATABASE`` with ``GLUE_EVENTS_TABLE``. Any other name answers 404
with a fixed detail that does not repeat it, and no Glue call is made. With
nothing configured every name answers 404, not 500.

The Glue client is a recording fake set on a real ``ETLService``, so "no Glue
call" is an assertion on the record, and ``boto3.client`` is replaced with one
that fails the test, so no real client can be created either.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import boto3
import pytest
from botocore.stub import Stubber
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole
from modules.backend.app.api.v1.endpoints.etl import get_etl_service
from modules.backend.app.services import etl_service as etl_service_module
from modules.backend.app.services.etl_service import ETLService

pytestmark = [pytest.mark.regression]

ETL_JOB = "cfg-events-etl-b565"
METRICS_JOB = "cfg-metrics-etl-b565"
CRAWLER = "cfg-crawler-b565"
DATABASE = "cfg_db_b565"
TABLE = "cfg_raw_events_b565"
PLANTED = "PLANTED-zq565"


class RecordingGlue:
    """Stands in for the boto3 Glue client and records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def _record(self, name: str, kwargs: dict) -> None:
        self.calls.append((name, kwargs))

    def get_job_run(self, **kwargs):
        self._record("get_job_run", kwargs)
        return {"JobRun": {"JobRunState": "RUNNING"}}

    def start_job_run(self, **kwargs):
        self._record("start_job_run", kwargs)
        return {"JobRunId": "jr_b565"}

    def get_crawler(self, **kwargs):
        self._record("get_crawler", kwargs)
        return {"Crawler": {"State": "READY"}}

    def start_crawler(self, **kwargs):
        self._record("start_crawler", kwargs)
        return {}

    def get_table(self, **kwargs):
        self._record("get_table", kwargs)
        return {"Table": {"StorageDescriptor": {"Location": "s3://b565/raw/"}}}

    def batch_create_partition(self, **kwargs):
        self._record("batch_create_partition", kwargs)
        return {}

    def __getattr__(self, name: str):
        # Any other attribute (``exceptions`` included) counts as a call.
        self.calls.append((name, {}))
        raise AssertionError(f"unexpected Glue attribute {name!r}")


def _user(role: UserRole) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.username = role.value
    user.email = f"{role.value}@example.com"
    user.is_active = True
    user.is_superuser = False
    user.role = role
    return user


def _configure(monkeypatch, **values: str) -> None:
    names = {
        "GLUE_ETL_JOB_NAME": ETL_JOB,
        "GLUE_METRICS_JOB_NAME": METRICS_JOB,
        "GLUE_CRAWLER_NAME": CRAWLER,
        "GLUE_DATABASE": DATABASE,
        "GLUE_EVENTS_TABLE": TABLE,
    }
    names.update(values)
    for key, value in names.items():
        monkeypatch.setattr(etl_service_module.modules_settings, key, value)


@pytest.fixture
def glue(monkeypatch):
    """A recording fake Glue client; creating a real one fails the test."""

    def no_real_client(*args, **kwargs):
        raise AssertionError("a real boto3 client was created")

    monkeypatch.setattr(etl_service_module.boto3, "client", no_real_client)
    return RecordingGlue()


@pytest.fixture
def call(glue):
    """``call(role, method, path, json=None)`` -> response, against ``glue``."""
    service = ETLService()
    service._glue_client = glue

    def run(role, method, path, json=None):
        app.dependency_overrides[deps.get_current_active_user] = lambda: _user(role)
        app.dependency_overrides[get_etl_service] = lambda: service
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.request(method, path, json=json)

    yield run
    app.dependency_overrides.clear()


# (role, method, path, detail) for each route given a name nobody configured.
UNKNOWN_NAME_CASES = [
    pytest.param(
        UserRole.VIEWER,
        "GET",
        f"/api/v1/etl/jobs/jr_1/status?job_name={PLANTED}",
        "Unknown ETL job",
        id="job-status",
    ),
    pytest.param(
        UserRole.VIEWER,
        "GET",
        f"/api/v1/etl/jobs/jr_1/status?job_name={ETL_JOB}-{PLANTED}",
        "Unknown ETL job",
        id="job-status-configured-prefix",
    ),
    pytest.param(
        UserRole.VIEWER,
        "GET",
        f"/api/v1/etl/crawler/status?crawler_name={PLANTED}",
        "Unknown crawler",
        id="crawler-status",
    ),
    pytest.param(
        UserRole.ADMIN,
        "POST",
        f"/api/v1/etl/crawler/run?crawler_name={PLANTED}",
        "Unknown crawler",
        id="crawler-run",
    ),
    pytest.param(
        UserRole.ADMIN,
        "POST",
        f"/api/v1/etl/partitions/add?database={PLANTED}&table={TABLE}&date=2026-10-01",
        "Unknown Glue table",
        id="partitions-database",
    ),
    pytest.param(
        UserRole.ADMIN,
        "POST",
        f"/api/v1/etl/partitions/add?database={DATABASE}&table={PLANTED}"
        "&date=2026-10-01",
        "Unknown Glue table",
        id="partitions-table",
    ),
]


@pytest.mark.parametrize("role,method,path,detail", UNKNOWN_NAME_CASES)
def test_an_unknown_name_is_404_and_glue_is_not_called(
    monkeypatch, call, glue, role, method, path, detail
):
    _configure(monkeypatch)
    response = call(role, method, path)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": detail}
    assert PLANTED not in response.text
    assert glue.calls == []


@pytest.mark.parametrize(
    "role,method,path,operation,kwargs",
    [
        pytest.param(
            UserRole.VIEWER,
            "GET",
            f"/api/v1/etl/jobs/jr_1/status?job_name={ETL_JOB}",
            "get_job_run",
            {"JobName": ETL_JOB, "RunId": "jr_1"},
            id="job-status-etl",
        ),
        pytest.param(
            UserRole.VIEWER,
            "GET",
            f"/api/v1/etl/jobs/jr_1/status?job_name={METRICS_JOB}",
            "get_job_run",
            {"JobName": METRICS_JOB, "RunId": "jr_1"},
            id="job-status-metrics",
        ),
        pytest.param(
            UserRole.VIEWER,
            "GET",
            "/api/v1/etl/crawler/status",
            "get_crawler",
            {"Name": CRAWLER},
            id="crawler-status-default",
        ),
        pytest.param(
            UserRole.VIEWER,
            "GET",
            f"/api/v1/etl/crawler/status?crawler_name={CRAWLER}",
            "get_crawler",
            {"Name": CRAWLER},
            id="crawler-status-named",
        ),
        pytest.param(
            UserRole.ADMIN,
            "POST",
            f"/api/v1/etl/crawler/run?crawler_name={CRAWLER}",
            "start_crawler",
            {"Name": CRAWLER},
            id="crawler-run",
        ),
        pytest.param(
            UserRole.ADMIN,
            "POST",
            f"/api/v1/etl/partitions/add?database={DATABASE}&table={TABLE}"
            "&date=2026-10-01",
            "get_table",
            {"DatabaseName": DATABASE, "Name": TABLE},
            id="partitions",
        ),
    ],
)
def test_a_configured_name_reaches_glue(
    monkeypatch, call, glue, role, method, path, operation, kwargs
):
    _configure(monkeypatch)
    response = call(role, method, path)
    assert response.status_code < 300, response.text
    assert glue.calls[0] == (operation, kwargs)


@pytest.mark.parametrize(
    "role,method,path,json,detail",
    [
        pytest.param(
            UserRole.VIEWER,
            "GET",
            f"/api/v1/etl/jobs/jr_1/status?job_name={PLANTED}",
            None,
            "Unknown ETL job",
            id="job-status",
        ),
        pytest.param(
            UserRole.VIEWER,
            "GET",
            "/api/v1/etl/jobs/jr_1/status?job_name=",
            None,
            "Unknown ETL job",
            id="job-status-empty-name",
        ),
        pytest.param(
            UserRole.VIEWER,
            "GET",
            "/api/v1/etl/crawler/status",
            None,
            "Unknown crawler",
            id="crawler-status-default",
        ),
        pytest.param(
            UserRole.VIEWER,
            "GET",
            f"/api/v1/etl/crawler/status?crawler_name={PLANTED}",
            None,
            "Unknown crawler",
            id="crawler-status-named",
        ),
        pytest.param(
            UserRole.ADMIN,
            "POST",
            "/api/v1/etl/crawler/run",
            None,
            "Unknown crawler",
            id="crawler-run",
        ),
        pytest.param(
            UserRole.ADMIN,
            "POST",
            f"/api/v1/etl/partitions/add?database={PLANTED}&table={PLANTED}"
            "&date=2026-10-01",
            None,
            "Unknown Glue table",
            id="partitions",
        ),
        pytest.param(
            UserRole.DEVELOPER,
            "POST",
            "/api/v1/etl/jobs/run",
            {"job_type": "events_to_parquet", "date": "2026-10-01"},
            "Unknown ETL job",
            id="job-run",
        ),
    ],
)
def test_nothing_configured_is_404_not_500(
    monkeypatch, call, glue, role, method, path, json, detail
):
    _configure(
        monkeypatch,
        GLUE_ETL_JOB_NAME="",
        GLUE_METRICS_JOB_NAME="",
        GLUE_CRAWLER_NAME="",
        GLUE_DATABASE="",
        GLUE_EVENTS_TABLE="",
    )
    response = call(role, method, path, json=json)
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": detail}
    assert PLANTED not in response.text
    assert glue.calls == []


def test_a_missing_run_of_a_configured_job_does_not_repeat_the_run_id(monkeypatch):
    """Glue's not-found for a configured job answers a fixed 404 too."""
    _configure(monkeypatch)
    client = boto3.client(
        "glue",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    stub = Stubber(client)
    stub.add_client_error(
        "get_job_run",
        service_error_code="EntityNotFoundException",
        expected_params={"JobName": ETL_JOB, "RunId": PLANTED},
    )
    stub.activate()
    service = ETLService()
    service._glue_client = client
    app.dependency_overrides[deps.get_current_active_user] = lambda: _user(
        UserRole.VIEWER
    )
    app.dependency_overrides[get_etl_service] = lambda: service
    try:
        with TestClient(app, raise_server_exceptions=False) as http:
            response = http.get(f"/api/v1/etl/jobs/{PLANTED}/status?job_name={ETL_JOB}")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Job run not found"}
    stub.assert_no_pending_responses()
