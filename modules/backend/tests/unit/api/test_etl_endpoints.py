"""
Unit tests for ETL REST endpoints (P3-A TDD).

All ETLService calls are mocked via dependency_overrides so tests run
without AWS credentials or real Glue/Athena resources.

Coverage:
- POST /api/v1/etl/jobs/run          — 202 for DEVELOPER, 403 for VIEWER
- GET  /api/v1/etl/jobs/{id}/status  — returns job status JSON
- POST /api/v1/etl/query             — 200 with rows for ANALYST
- POST /api/v1/etl/query             — 403 for VIEWER
- POST /api/v1/etl/partitions/add    — 201 for ADMIN, 403 for non-ADMIN
- GET  /api/v1/etl/crawler/status    — returns crawler state
- POST /api/v1/etl/crawler/run       — 202 for ADMIN, 403 for DEVELOPER
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole
from modules.backend.app.schemas.etl import (
    AthenaQueryResult,
    ETLJobResponse,
    ETLJobType,
    GlueCrawlerStatus,
    GlueJobStatus,
    PartitionInfo,
)

# ---------------------------------------------------------------------------
# User factories
# ---------------------------------------------------------------------------


def _make_user(role: UserRole, is_superuser: bool = False) -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = f"{role.value}@example.com"
    user.username = role.value
    user.is_active = True
    user.is_superuser = is_superuser
    user.role = role
    return user


def make_admin():
    return _make_user(UserRole.ADMIN, is_superuser=True)


def make_developer():
    return _make_user(UserRole.DEVELOPER)


def make_analyst():
    return _make_user(UserRole.ANALYST)


def make_viewer():
    return _make_user(UserRole.VIEWER)


# ---------------------------------------------------------------------------
# Mock ETLService responses
# ---------------------------------------------------------------------------


def _mock_job_response(
    job_type: ETLJobType = ETLJobType.EVENTS_TO_PARQUET,
    status: GlueJobStatus = GlueJobStatus.STARTING,
) -> ETLJobResponse:
    return ETLJobResponse(
        job_run_id="jr-test-001",
        job_name="experimentation-events-etl",
        job_type=job_type,
        status=status,
        started_at="2024-01-15T02:00:00Z",
    )


def _mock_athena_result() -> AthenaQueryResult:
    return AthenaQueryResult(
        query_execution_id="qe-test-001",
        status="SUCCEEDED",
        rows=[
            {"event_id": "e1", "event_type": "view"},
            {"event_id": "e2", "event_type": "click"},
        ],
        column_names=["event_id", "event_type"],
        rows_returned=2,
        execution_time_ms=450,
        data_scanned_bytes=1024,
    )


def _mock_partition_list() -> list:
    return [
        PartitionInfo(
            database="experimentation",
            table="raw_events",
            partition_values={
                "year": "2024",
                "month": "01",
                "day": "15",
                "hour": f"{h:02d}",
            },
            location=f"s3://exp-data-bucket/raw/events/year=2024/month=01/day=15/hour={h:02d}/",
        )
        for h in range(24)
    ]


def _mock_crawler_status() -> GlueCrawlerStatus:
    return GlueCrawlerStatus(
        crawler_name="experimentation-crawler",
        state="RUNNING",
        last_run_status="SUCCEEDED",
        last_run_time="2024-01-14T02:00:00Z",
        tables_created=2,
        tables_updated=1,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_etl_service():
    """Return a MagicMock ETLService with sensible defaults."""
    svc = MagicMock()
    svc.run_etl_job.return_value = _mock_job_response()
    svc.get_job_status.return_value = _mock_job_response(status=GlueJobStatus.RUNNING)
    svc.run_athena_query.return_value = _mock_athena_result()
    svc.add_partitions.return_value = _mock_partition_list()
    svc.run_crawler.return_value = _mock_crawler_status()
    svc.get_crawler_status.return_value = _mock_crawler_status()
    return svc


@pytest.fixture
def client_as_admin(mock_etl_service):
    """TestClient with ADMIN user and mocked ETL service."""
    from modules.backend.app.api.v1.endpoints.etl import get_etl_service

    admin = make_admin()
    app.dependency_overrides[deps.get_current_active_user] = lambda: admin
    app.dependency_overrides[get_etl_service] = lambda: mock_etl_service
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_as_developer(mock_etl_service):
    """TestClient with DEVELOPER user and mocked ETL service."""
    from modules.backend.app.api.v1.endpoints.etl import get_etl_service

    developer = make_developer()
    app.dependency_overrides[deps.get_current_active_user] = lambda: developer
    app.dependency_overrides[get_etl_service] = lambda: mock_etl_service
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_as_analyst(mock_etl_service):
    """TestClient with ANALYST user and mocked ETL service."""
    from modules.backend.app.api.v1.endpoints.etl import get_etl_service

    analyst = make_analyst()
    app.dependency_overrides[deps.get_current_active_user] = lambda: analyst
    app.dependency_overrides[get_etl_service] = lambda: mock_etl_service
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_as_viewer(mock_etl_service):
    """TestClient with VIEWER user and mocked ETL service."""
    from modules.backend.app.api.v1.endpoints.etl import get_etl_service

    viewer = make_viewer()
    app.dependency_overrides[deps.get_current_active_user] = lambda: viewer
    app.dependency_overrides[get_etl_service] = lambda: mock_etl_service
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# POST /api/v1/etl/jobs/run
# ---------------------------------------------------------------------------


class TestRunETLJobEndpoint:
    def test_developer_can_trigger_etl_job(self, client_as_developer):
        """DEVELOPER receives 202 when triggering an ETL job."""
        payload = {
            "job_type": "events_to_parquet",
            "date": "2024-01-15",
        }
        resp = client_as_developer.post("/api/v1/etl/jobs/run", json=payload)
        assert resp.status_code == 202
        data = resp.json()
        assert data["job_run_id"] == "jr-test-001"
        assert data["status"] == "STARTING"

    def test_admin_can_trigger_etl_job(self, client_as_admin):
        """ADMIN receives 202 when triggering an ETL job."""
        payload = {
            "job_type": "metrics_aggregation",
            "date": "2024-01-15",
        }
        resp = client_as_admin.post("/api/v1/etl/jobs/run", json=payload)
        assert resp.status_code == 202

    def test_viewer_cannot_trigger_etl_job(self, client_as_viewer):
        """VIEWER receives 403 when triggering an ETL job."""
        payload = {
            "job_type": "events_to_parquet",
            "date": "2024-01-15",
        }
        resp = client_as_viewer.post("/api/v1/etl/jobs/run", json=payload)
        assert resp.status_code == 403

    def test_analyst_cannot_trigger_etl_job(self, client_as_analyst):
        """ANALYST receives 403 when triggering an ETL job."""
        payload = {
            "job_type": "events_to_parquet",
            "date": "2024-01-15",
        }
        resp = client_as_analyst.post("/api/v1/etl/jobs/run", json=payload)
        assert resp.status_code == 403

    def test_invalid_date_returns_422(self, client_as_developer):
        """Invalid date format returns 422 Unprocessable Entity."""
        payload = {
            "job_type": "events_to_parquet",
            "date": "2024/01/15",  # wrong format
        }
        resp = client_as_developer.post("/api/v1/etl/jobs/run", json=payload)
        assert resp.status_code == 422

    def test_response_includes_job_name(self, client_as_developer):
        """Response body contains job_name field."""
        payload = {"job_type": "events_to_parquet", "date": "2024-01-15"}
        resp = client_as_developer.post("/api/v1/etl/jobs/run", json=payload)
        assert "job_name" in resp.json()


# ---------------------------------------------------------------------------
# GET /api/v1/etl/jobs/{run_id}/status
# ---------------------------------------------------------------------------


class TestGetJobStatusEndpoint:
    def test_get_job_status_returns_200(self, client_as_analyst):
        """Any authenticated user can GET job status."""
        resp = client_as_analyst.get(
            "/api/v1/etl/jobs/jr-test-001/status",
            params={"job_name": "experimentation-events-etl"},
        )
        assert resp.status_code == 200

    def test_get_job_status_response_shape(self, client_as_analyst):
        """GET job status response has expected fields."""
        resp = client_as_analyst.get(
            "/api/v1/etl/jobs/jr-test-001/status",
            params={"job_name": "experimentation-events-etl"},
        )
        data = resp.json()
        assert "job_run_id" in data
        assert "status" in data
        assert "job_name" in data

    def test_viewer_can_get_job_status(self, client_as_viewer):
        """VIEWER can read job status (read-only action)."""
        resp = client_as_viewer.get(
            "/api/v1/etl/jobs/jr-test-001/status",
            params={"job_name": "experimentation-events-etl"},
        )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/v1/etl/query
# ---------------------------------------------------------------------------


class TestAthenaQueryEndpoint:
    def test_analyst_can_run_query(self, client_as_analyst):
        """ANALYST receives 200 with query results."""
        payload = {
            "sql": "SELECT COUNT(*) FROM raw_events WHERE year='2024'",
            "database": "experimentation",
        }
        resp = client_as_analyst.post("/api/v1/etl/query", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["query_execution_id"] == "qe-test-001"
        assert data["rows_returned"] == 2

    def test_developer_can_run_query(self, client_as_developer):
        """DEVELOPER receives 200 with query results."""
        payload = {
            "sql": "SELECT event_type, COUNT(*) FROM events GROUP BY event_type",
        }
        resp = client_as_developer.post("/api/v1/etl/query", json=payload)
        assert resp.status_code == 200

    def test_admin_can_run_query(self, client_as_admin):
        """ADMIN receives 200 with query results."""
        payload = {
            "sql": "SELECT * FROM raw_events LIMIT 100",
        }
        resp = client_as_admin.post("/api/v1/etl/query", json=payload)
        assert resp.status_code == 200

    def test_viewer_cannot_run_query(self, client_as_viewer):
        """VIEWER receives 403 when running Athena query."""
        payload = {
            "sql": "SELECT COUNT(*) FROM raw_events",
        }
        resp = client_as_viewer.post("/api/v1/etl/query", json=payload)
        assert resp.status_code == 403

    def test_query_response_includes_column_names(self, client_as_analyst):
        """Query response includes column_names list."""
        payload = {"sql": "SELECT event_id, event_type FROM raw_events LIMIT 5"}
        resp = client_as_analyst.post("/api/v1/etl/query", json=payload)
        data = resp.json()
        assert "column_names" in data
        assert isinstance(data["column_names"], list)

    def test_short_sql_returns_422(self, client_as_analyst):
        """SQL shorter than min_length returns 422."""
        payload = {"sql": "SELECT 1"}  # too short
        resp = client_as_analyst.post("/api/v1/etl/query", json=payload)
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/v1/etl/partitions/add
# ---------------------------------------------------------------------------


class TestAddPartitionsEndpoint:
    def test_admin_can_add_partitions(self, client_as_admin):
        """ADMIN receives 201 with partition list."""
        resp = client_as_admin.post(
            "/api/v1/etl/partitions/add",
            params={
                "database": "experimentation",
                "table": "raw_events",
                "date": "2024-01-15",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 24

    def test_developer_cannot_add_partitions(self, client_as_developer):
        """DEVELOPER receives 403 when adding partitions."""
        resp = client_as_developer.post(
            "/api/v1/etl/partitions/add",
            params={
                "database": "experimentation",
                "table": "raw_events",
                "date": "2024-01-15",
            },
        )
        assert resp.status_code == 403

    def test_analyst_cannot_add_partitions(self, client_as_analyst):
        """ANALYST receives 403 when adding partitions."""
        resp = client_as_analyst.post(
            "/api/v1/etl/partitions/add",
            params={
                "database": "experimentation",
                "table": "raw_events",
                "date": "2024-01-15",
            },
        )
        assert resp.status_code == 403

    def test_viewer_cannot_add_partitions(self, client_as_viewer):
        """VIEWER receives 403 when adding partitions."""
        resp = client_as_viewer.post(
            "/api/v1/etl/partitions/add",
            params={
                "database": "experimentation",
                "table": "raw_events",
                "date": "2024-01-15",
            },
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/v1/etl/crawler/status
# ---------------------------------------------------------------------------


class TestCrawlerStatusEndpoint:
    def test_get_crawler_status_returns_200(self, client_as_analyst):
        """Any authenticated user can GET crawler status."""
        resp = client_as_analyst.get("/api/v1/etl/crawler/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["crawler_name"] == "experimentation-crawler"
        assert "state" in data

    def test_viewer_can_get_crawler_status(self, client_as_viewer):
        """VIEWER can read crawler status."""
        resp = client_as_viewer.get("/api/v1/etl/crawler/status")
        assert resp.status_code == 200

    def test_crawler_status_includes_run_info(self, client_as_admin):
        """Crawler status response includes last_run_status and counts."""
        resp = client_as_admin.get("/api/v1/etl/crawler/status")
        data = resp.json()
        assert "last_run_status" in data
        assert "tables_created" in data
        assert "tables_updated" in data


# ---------------------------------------------------------------------------
# POST /api/v1/etl/crawler/run
# ---------------------------------------------------------------------------


class TestRunCrawlerEndpoint:
    def test_admin_can_run_crawler(self, client_as_admin):
        """ADMIN receives 202 when triggering crawler."""
        resp = client_as_admin.post("/api/v1/etl/crawler/run")
        assert resp.status_code == 202
        data = resp.json()
        assert data["state"] == "RUNNING"

    def test_developer_cannot_run_crawler(self, client_as_developer):
        """DEVELOPER receives 403 when triggering crawler."""
        resp = client_as_developer.post("/api/v1/etl/crawler/run")
        assert resp.status_code == 403

    def test_analyst_cannot_run_crawler(self, client_as_analyst):
        """ANALYST receives 403 when triggering crawler."""
        resp = client_as_analyst.post("/api/v1/etl/crawler/run")
        assert resp.status_code == 403

    def test_viewer_cannot_run_crawler(self, client_as_viewer):
        """VIEWER receives 403 when triggering crawler."""
        resp = client_as_viewer.post("/api/v1/etl/crawler/run")
        assert resp.status_code == 403
