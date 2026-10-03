"""What the ETL routes answer when the Glue call fails unexpectedly.

Each used to put the client error's text in ``detail``. Now each answers a
fixed sentence with the request ID, and the full error goes to the server log
under that ID. The deliberate 404 and 409 answers are unchanged.

The routes accept only the configured job and crawler names (#565), so these
requests name the configured ones.

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
from modules.backend.app.services import etl_service as etl_service_module
from modules.backend.app.services.etl_service import ETLService

pytestmark = [pytest.mark.regression]

CANARY = "CANARY glue-says-no zq540"
REQUEST_ID = "etl-fixed-540"
JOB = "experimentation-events-etl"
CRAWLER = "experimentation-crawler"
DATABASE = "experimentation"
TABLE = "raw_events"
PARTITIONS = f"/api/v1/etl/partitions/add?database={DATABASE}&table={TABLE}"


@pytest.fixture(autouse=True)
def _configured_names(monkeypatch):
    monkeypatch.setattr(etl_service_module.modules_settings, "GLUE_ETL_JOB_NAME", JOB)
    monkeypatch.setattr(
        etl_service_module.modules_settings, "GLUE_CRAWLER_NAME", CRAWLER
    )
    monkeypatch.setattr(etl_service_module.modules_settings, "GLUE_DATABASE", DATABASE)
    monkeypatch.setattr(etl_service_module.modules_settings, "GLUE_EVENTS_TABLE", TABLE)


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
            f"/api/v1/etl/jobs/jr_1/status?job_name={JOB}",
            None,
            "Could not read the ETL job's status",
        ),
        (
            UserRole.VIEWER,
            "get_crawler",
            "GET",
            f"/api/v1/etl/crawler/status?crawler_name={CRAWLER}",
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
            f"/api/v1/etl/crawler/run?crawler_name={CRAWLER}",
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
        f"/api/v1/etl/crawler/run?crawler_name={CRAWLER}",
    )
    assert response.status_code == 409
    assert response.json() == {"detail": f"Crawler '{CRAWLER}' is already running."}


def test_an_unknown_crawler_is_still_a_404(call):
    response = call(
        UserRole.VIEWER,
        _service("get_crawler", code="EntityNotFoundException"),
        "GET",
        f"/api/v1/etl/crawler/status?crawler_name={CRAWLER}",
    )
    assert response.status_code == 404
    assert response.json() == {"detail": f"Crawler '{CRAWLER}' not found."}


# --- POST /etl/partitions/add (#656) ------------------------------------------
#
# The route answered 201 whatever Glue said: a failed table read, a refused
# BatchCreatePartition and the per-partition refusals in a successful reply
# were all reported as success.

TABLE_REPLY = {
    "Table": {"Name": TABLE, "StorageDescriptor": {"Location": "s3://lake/raw/"}}
}


def _partition_errors(count: int, code: str) -> list[dict]:
    return [
        {
            "PartitionValues": ["2026", "10", "01", f"{hour:02d}"],
            "ErrorDetail": {"ErrorCode": code, "ErrorMessage": CANARY},
        }
        for hour in range(count)
    ]


def _partitions_service(*steps) -> tuple[ETLService, Stubber]:
    """A stubbed client answering ``steps`` in order: ``(operation, reply)``
    for a reply, ``(operation, code)`` for an error with the canary message."""
    client = boto3.client(
        "glue",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    stub = Stubber(client)
    for operation, answer in steps:
        if isinstance(answer, str):
            stub.add_client_error(
                operation, service_error_code=answer, service_message=CANARY
            )
        else:
            stub.add_response(operation, answer)
    stub.activate()
    service = ETLService()
    service._glue_client = client
    return service, stub


@pytest.mark.parametrize(
    "steps,sentence",
    [
        pytest.param(
            [("get_table", "AccessDeniedException")],
            "Could not read the Glue table",
            id="get-table-refused",
        ),
        pytest.param(
            [("get_table", {"Table": {"Name": TABLE}})],
            "Could not read the Glue table",
            id="no-location",
        ),
        pytest.param(
            [
                ("get_table", TABLE_REPLY),
                ("batch_create_partition", "AccessDeniedException"),
            ],
            "Could not register the partitions",
            id="batch-refused",
        ),
        pytest.param(
            [
                ("get_table", TABLE_REPLY),
                (
                    "batch_create_partition",
                    {"Errors": _partition_errors(24, "AccessDeniedException")},
                ),
            ],
            "Could not register the partitions",
            id="every-partition-refused",
        ),
        pytest.param(
            [
                ("get_table", TABLE_REPLY),
                (
                    "batch_create_partition",
                    {
                        "Errors": _partition_errors(23, "AlreadyExistsException")
                        + [
                            {
                                "PartitionValues": ["2026", "10", "01", "23"],
                                "ErrorDetail": {
                                    "ErrorCode": "ResourceNumberLimitExceededException",
                                    "ErrorMessage": CANARY,
                                },
                            }
                        ]
                    },
                ),
            ],
            "Could not register the partitions",
            id="one-partition-refused",
        ),
    ],
)
def test_a_refused_catalog_write_is_not_201(call, steps, sentence, caplog):
    service, stub = _partitions_service(*steps)
    response = call(UserRole.ADMIN, service, "POST", f"{PARTITIONS}&date=2026-10-01")
    assert response.status_code == 500, response.text
    assert response.json() == {"detail": f"{sentence} (request ID: {REQUEST_ID})."}
    for marker in ("CANARY", "glue-says-no", "zq540", "s3://"):
        assert marker not in response.text
    # The cause is in the server log: the refused call's error code, or the
    # missing location.
    _, answer = steps[-1]
    if isinstance(answer, str):
        cause = answer
    elif "Errors" in answer:
        cause = answer["Errors"][-1]["ErrorDetail"]["ErrorCode"]
    else:
        cause = "no storage location"
    assert cause in caplog.text
    stub.assert_no_pending_responses()


def test_a_table_missing_from_the_catalog_is_a_404(call, caplog):
    service, stub = _partitions_service(("get_table", "EntityNotFoundException"))
    response = call(UserRole.ADMIN, service, "POST", f"{PARTITIONS}&date=2026-10-01")
    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Glue table not found. Run the crawler first."}
    stub.assert_no_pending_responses()


def test_every_partition_already_registered_is_still_201(call):
    """A re-run: Glue lists every hour as already existing, and that is success."""
    service, stub = _partitions_service(
        ("get_table", TABLE_REPLY),
        (
            "batch_create_partition",
            {"Errors": _partition_errors(24, "AlreadyExistsException")},
        ),
    )
    response = call(UserRole.ADMIN, service, "POST", f"{PARTITIONS}&date=2026-10-01")
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body) == 24
    assert body[0]["location"] == "s3://lake/raw/year=2026/month=10/day=01/hour=00/"
    stub.assert_no_pending_responses()


@pytest.mark.parametrize(
    "date", ["2026-10", "2026-13-45", "20261001", "2026-1-01", "2026-W40-1"]
)
def test_a_date_that_is_not_yyyy_mm_dd_is_a_422(call, date):
    service, stub = _partitions_service()  # nothing queued: any Glue call fails
    response = call(UserRole.ADMIN, service, "POST", f"{PARTITIONS}&date={date}")
    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": "date must be a calendar date in YYYY-MM-DD format"
    }
