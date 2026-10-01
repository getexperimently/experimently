"""What the ETL routes answer when the Glue call fails unexpectedly.

Each used to put the client error's text in ``detail``. Now each answers a
fixed sentence with the request ID, and the full error goes to the server log
under that ID. The deliberate 404 and 409 answers are unchanged.

The Glue client is a real botocore client with a ``Stubber``: no network, no
credentials.
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
from modules.backend.app.services.etl_service import ETLService

pytestmark = [pytest.mark.regression]

CANARY = "CANARY glue-says-no zq540"
REQUEST_ID = "etl-fixed-540"


def _service(
    operation: str, code: str = "ConcurrentRunsExceededException"
) -> ETLService:
    client = boto3.client(
        "glue",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    stub = Stubber(client)
    stub.add_client_error(operation, service_error_code=code, service_message=CANARY)
    stub.activate()
    service = ETLService()
    service._glue_client = client
    return service


def _user(role: UserRole) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.username = role.value
    user.email = f"{role.value}@example.com"
    user.is_active = True
    user.is_superuser = False
    user.role = role
    return user


@pytest.fixture
def call():
    """``call(role, service, method, path, json=None)`` -> response."""

    def run(role, service, method, path, json=None):
        app.dependency_overrides[deps.get_current_active_user] = lambda: _user(role)
        app.dependency_overrides[get_etl_service] = lambda: service
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.request(
                method, path, json=json, headers={"X-Request-ID": REQUEST_ID}
            )

    yield run
    app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "role,operation,method,path,body,sentence",
    [
        (
            UserRole.VIEWER,
            "get_job_run",
            "GET",
            "/api/v1/etl/jobs/jr_1/status?job_name=experimently-events-to-parquet",
            None,
            "Could not read the ETL job's status",
        ),
        (
            UserRole.VIEWER,
            "get_crawler",
            "GET",
            "/api/v1/etl/crawler/status?crawler_name=c1",
            None,
            "Could not read the crawler's status",
        ),
        (
            UserRole.DEVELOPER,
            "start_job_run",
            "POST",
            "/api/v1/etl/jobs/run",
            {"job_type": "events_to_parquet", "date": "2026-09-30"},
            "Could not start the ETL job",
        ),
        (
            UserRole.ADMIN,
            "start_crawler",
            "POST",
            "/api/v1/etl/crawler/run?crawler_name=c1",
            None,
            "Could not start the crawler",
        ),
    ],
    ids=["job-status", "crawler-status", "job-run", "crawler-run"],
)
def test_a_glue_failure_answers_the_fixed_message(
    call, role, operation, method, path, body, sentence, caplog
):
    response = call(role, _service(operation), method, path, json=body)
    assert response.status_code == 500, response.text
    assert response.json() == {"detail": f"{sentence} (request ID: {REQUEST_ID})."}
    for marker in ("CANARY", "glue-says-no", "zq540", "ConcurrentRuns"):
        assert marker not in response.text
    assert CANARY in caplog.text  # the full error is in the server log


def test_a_running_crawler_is_still_a_409(call):
    response = call(
        UserRole.ADMIN,
        _service("start_crawler", code="CrawlerRunningException"),
        "POST",
        "/api/v1/etl/crawler/run?crawler_name=c1",
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "Crawler 'c1' is already running."}


def test_an_unknown_crawler_is_still_a_404(call):
    response = call(
        UserRole.VIEWER,
        _service("get_crawler", code="EntityNotFoundException"),
        "GET",
        "/api/v1/etl/crawler/status?crawler_name=c1",
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Crawler 'c1' not found."}
