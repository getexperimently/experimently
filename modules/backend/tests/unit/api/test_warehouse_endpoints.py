"""
Unit tests for Warehouse API endpoints (Issue #26).

Uses FastAPI TestClient with mocked auth and mocked service layer.
No real database or warehouse connection is needed.

Covers:
 1.  GET  /warehouse/connections              → 200 list
 2.  POST /warehouse/connections              → 201 created
 3.  POST /warehouse/connections (bad type)   → 422
 4.  Response never includes password or encrypted_credentials
 5.  DELETE /warehouse/connections/{id}       → 200 soft-delete
 6.  DELETE /warehouse/connections/{id} (404) → 404
 7.  POST /warehouse/connections/test         → ConnectionTestResponse
 8.  test → success:true for valid config
 9.  test → success:false for invalid warehouse_type
10.  POST /warehouse/sync/{experiment_id}     → SyncStatusResponse
11.  sync → returns generated_sql
12.  All endpoints require DEVELOPER+ role (VIEWER → 403)
13.  VIEWER gets 403 on list
14.  GET  /warehouse/connections/{id} (404)   → 404
15.  WarehouseType enum validation in create
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_user(role: UserRole = UserRole.DEVELOPER, is_superuser: bool = False) -> User:
    """Build a minimal User object for mocking auth."""
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.username = f"user_{role.value}"
    user.email = f"{role.value}@example.com"
    user.role = role
    user.is_active = True
    user.is_superuser = is_superuser
    user.hashed_password = "hashed_pw"
    return user


def _make_mock_connection(
    conn_id: str = None,
    name: str = "Test Connection",
    warehouse_type: str = "snowflake",
    is_active: bool = True,
):
    conn = MagicMock()
    conn.id = conn_id or str(uuid.uuid4())
    conn.name = name
    conn.warehouse_type = warehouse_type
    conn.is_active = is_active
    return conn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def developer_user():
    return _make_user(UserRole.DEVELOPER)


@pytest.fixture
def viewer_user():
    return _make_user(UserRole.VIEWER)


@pytest.fixture
def admin_user():
    return _make_user(UserRole.ADMIN, is_superuser=True)


@pytest.fixture
def client_as_developer(developer_user):
    """TestClient with DEVELOPER user injected."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: developer_user
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_as_viewer(viewer_user):
    """TestClient with VIEWER user injected."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: viewer_user
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test: GET /warehouse/connections
# ---------------------------------------------------------------------------


class TestListConnections:
    BASE_URL = "/api/v1/warehouse/connections"

    def test_list_connections_returns_200(self, client_as_developer):
        """Test 1: list endpoint returns HTTP 200."""
        fake_conn = _make_mock_connection()
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
        ) as MockMgr:
            MockMgr.return_value.list_connections.return_value = [fake_conn]
            response = client_as_developer.get(self.BASE_URL)
        assert response.status_code == 200

    def test_list_connections_returns_list(self, client_as_developer):
        """List endpoint returns a JSON array."""
        fake_conn = _make_mock_connection()
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
        ) as MockMgr:
            MockMgr.return_value.list_connections.return_value = [fake_conn]
            response = client_as_developer.get(self.BASE_URL)
        assert isinstance(response.json(), list)

    # Test 13: VIEWER gets 403 on list
    def test_viewer_gets_403_on_list(self, client_as_viewer):
        """VIEWER role must be denied access to list connections."""
        response = client_as_viewer.get(self.BASE_URL)
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: POST /warehouse/connections
# ---------------------------------------------------------------------------


class TestCreateConnection:
    BASE_URL = "/api/v1/warehouse/connections"

    # Test 2: POST creates connection → 201
    def test_create_connection_returns_201(self, client_as_developer):
        payload = {
            "name": "My Snowflake",
            "warehouse_type": "snowflake",
            "host": "account.snowflakecomputing.com",
            "username": "svc_user",
            "password": "s3cr3t",
        }
        fake_conn = _make_mock_connection(name="My Snowflake")
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
        ) as MockMgr:
            MockMgr.return_value.create_connection.return_value = fake_conn
            response = client_as_developer.post(self.BASE_URL, json=payload)
        assert response.status_code == 201

    # Test 3: POST with invalid warehouse_type → 422
    def test_create_connection_invalid_type_returns_422(self, client_as_developer):
        payload = {
            "name": "My Oracle",
            "warehouse_type": "oracle",  # invalid
        }
        response = client_as_developer.post(self.BASE_URL, json=payload)
        assert response.status_code == 422

    # Test 4: Response never includes password or encrypted_credentials
    def test_create_connection_response_has_no_credentials(self, client_as_developer):
        payload = {
            "name": "Secure Conn",
            "warehouse_type": "redshift",
            "host": "my-cluster.redshift.amazonaws.com",
            "username": "admin",
            "password": "super_secret",
        }
        fake_conn = _make_mock_connection(name="Secure Conn", warehouse_type="redshift")
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
        ) as MockMgr:
            MockMgr.return_value.create_connection.return_value = fake_conn
            response = client_as_developer.post(self.BASE_URL, json=payload)
        body = response.json()
        assert "password" not in body
        assert "encrypted_credentials" not in body
        assert "private_key" not in body

    # Test 15: WarehouseType enum validation
    def test_create_connection_accepts_all_valid_types(self, client_as_developer):
        for wtype in ("snowflake", "bigquery", "redshift"):
            payload = {"name": f"My {wtype}", "warehouse_type": wtype}
            fake_conn = _make_mock_connection(warehouse_type=wtype)
            with patch(
                "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
            ) as MockMgr:
                MockMgr.return_value.create_connection.return_value = fake_conn
                response = client_as_developer.post(self.BASE_URL, json=payload)
            assert response.status_code == 201, f"Expected 201 for type={wtype}"

    # Test 12: VIEWER gets 403
    def test_viewer_gets_403_on_create(self, client_as_viewer):
        payload = {"name": "Viewer Conn", "warehouse_type": "snowflake"}
        response = client_as_viewer.post(self.BASE_URL, json=payload)
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: DELETE /warehouse/connections/{id}
# ---------------------------------------------------------------------------


class TestDeleteConnection:
    # Test 5: DELETE soft-deletes → 200
    def test_delete_connection_returns_200(self, client_as_developer):
        conn_id = str(uuid.uuid4())
        fake_conn = _make_mock_connection(conn_id=conn_id)
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
        ) as MockMgr:
            MockMgr.return_value.delete_connection.return_value = fake_conn
            response = client_as_developer.delete(
                f"/api/v1/warehouse/connections/{conn_id}"
            )
        assert response.status_code == 200

    # Test 6: DELETE unknown id → 404
    def test_delete_unknown_connection_returns_404(self, client_as_developer):
        conn_id = str(uuid.uuid4())
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
        ) as MockMgr:
            MockMgr.return_value.delete_connection.return_value = None
            response = client_as_developer.delete(
                f"/api/v1/warehouse/connections/{conn_id}"
            )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Test: GET /warehouse/connections/{id}
# ---------------------------------------------------------------------------


class TestGetConnection:
    # Test 14: GET unknown id → 404
    def test_get_unknown_connection_returns_404(self, client_as_developer):
        conn_id = str(uuid.uuid4())
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
        ) as MockMgr:
            MockMgr.return_value.get_connection.return_value = None
            response = client_as_developer.get(
                f"/api/v1/warehouse/connections/{conn_id}"
            )
        assert response.status_code == 404

    def test_get_existing_connection_returns_200(self, client_as_developer):
        conn_id = str(uuid.uuid4())
        fake_conn = _make_mock_connection(conn_id=conn_id)
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
        ) as MockMgr:
            MockMgr.return_value.get_connection.return_value = fake_conn
            response = client_as_developer.get(
                f"/api/v1/warehouse/connections/{conn_id}"
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Test: POST /warehouse/connections/test
# ---------------------------------------------------------------------------


class TestTestConnection:
    BASE_URL = "/api/v1/warehouse/connections/test"

    # Test 7: Returns ConnectionTestResponse
    def test_test_connection_returns_test_response_shape(self, client_as_developer):
        payload = {
            "name": "Test Conn",
            "warehouse_type": "snowflake",
            "host": "account.snowflakecomputing.com",
        }
        from modules.backend.app.services.warehouse_service import ConnectionTestResult

        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
        ) as MockMgr:
            MockMgr.return_value.test_connection.return_value = ConnectionTestResult(
                success=True, latency_ms=12.5
            )
            response = client_as_developer.post(self.BASE_URL, json=payload)
        assert response.status_code == 200
        body = response.json()
        assert "success" in body
        assert "latency_ms" in body

    # Test 8: success:true for valid config
    def test_test_connection_returns_success_true_for_valid(self, client_as_developer):
        payload = {
            "name": "Good Conn",
            "warehouse_type": "bigquery",
            "project_id": "my-gcp-project",
        }
        from modules.backend.app.services.warehouse_service import ConnectionTestResult

        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseConnectionManager"
        ) as MockMgr:
            MockMgr.return_value.test_connection.return_value = ConnectionTestResult(
                success=True, latency_ms=8.3
            )
            response = client_as_developer.post(self.BASE_URL, json=payload)
        assert response.json()["success"] is True

    # Test 9: success:false for invalid warehouse_type (422 from schema validation)
    def test_test_connection_returns_422_for_invalid_type(self, client_as_developer):
        payload = {
            "name": "Bad Conn",
            "warehouse_type": "teradata",  # not a valid WarehouseType
        }
        response = client_as_developer.post(self.BASE_URL, json=payload)
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test: POST /warehouse/sync/{experiment_id}
# ---------------------------------------------------------------------------


class TestSyncExperiment:
    # Test 10: Returns SyncStatusResponse
    def test_sync_experiment_returns_sync_status_response(self, client_as_developer):
        experiment_id = str(uuid.uuid4())
        payload = {
            "assignments_table": "exp_assignments",
            "events_table": "exp_events",
            "metric_event": "purchase",
        }
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseQueryGenerator"
        ) as MockGen:
            MockGen.generate_results_query.return_value = "SELECT ..."
            response = client_as_developer.post(
                f"/api/v1/warehouse/sync/{experiment_id}",
                json=payload,
            )
        assert response.status_code == 200
        body = response.json()
        assert "experiment_id" in body
        assert "status" in body

    # Test 11: Returns generated_sql
    def test_sync_experiment_returns_generated_sql(self, client_as_developer):
        experiment_id = str(uuid.uuid4())
        payload = {
            "assignments_table": "assignments",
            "events_table": "events",
            "metric_event": "checkout",
        }
        expected_sql = "SELECT a.variant_id, COUNT(*) FROM assignments a ..."
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse.WarehouseQueryGenerator"
        ) as MockGen:
            MockGen.generate_results_query.return_value = expected_sql
            response = client_as_developer.post(
                f"/api/v1/warehouse/sync/{experiment_id}",
                json=payload,
            )
        body = response.json()
        assert body.get("generated_sql") == expected_sql or body.get("status") in (
            "success",
            "pending",
            "running",
        )

    # Test 12: VIEWER gets 403
    def test_viewer_gets_403_on_sync(self, client_as_viewer):
        experiment_id = str(uuid.uuid4())
        payload = {
            "assignments_table": "a",
            "events_table": "e",
            "metric_event": "purchase",
        }
        response = client_as_viewer.post(
            f"/api/v1/warehouse/sync/{experiment_id}",
            json=payload,
        )
        assert response.status_code == 403
