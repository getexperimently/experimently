"""
Integration tests for EP-048 MySQL API.

Tests the full HTTP request/response cycle for MySQL warehouse endpoints:
  POST   /api/v1/warehouse/mysql/test-connection  — connectivity test
  POST   /api/v1/warehouse/mysql/query            — execute read-only SQL
  GET    /api/v1/warehouse/mysql/metrics/experiments/{id}  — experiment metrics
  GET    /api/v1/warehouse/mysql/metrics/flags/{id}        — feature flag metrics

Error cases:
  - 400 for bad / unsafe SQL
  - 503 when MySQL is unreachable
  - 422 for invalid request payloads
  - 403 for VIEWER role (requires DEVELOPER+)

Uses FastAPI TestClient with mocked auth and mocked MySQLConnector.
No real MySQL connection or database required.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps
from backend.app.main import app
from backend.app.models.user import User, UserRole
from modules.backend.app.services.mysql_connector import (
    MySQLConnectionError,
    MySQLQueryError,
)

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


BASE = "/api/v1/warehouse/mysql"


@pytest.fixture
def developer_user():
    return _make_user(UserRole.DEVELOPER)


@pytest.fixture
def admin_user():
    return _make_user(UserRole.ADMIN, is_superuser=True)


@pytest.fixture
def viewer_user():
    return _make_user(UserRole.VIEWER)


@pytest.fixture
def client_as_developer(developer_user):
    """TestClient authenticated as DEVELOPER."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: developer_user
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_as_admin(admin_user):
    """TestClient authenticated as ADMIN."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: admin_user
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client_as_viewer(viewer_user):
    """TestClient authenticated as VIEWER."""
    app.dependency_overrides[deps.get_current_active_user] = lambda: viewer_user
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    app.dependency_overrides.clear()


# ===========================================================================
# POST /test-connection
# ===========================================================================


class TestMySQLTestConnection:
    """Tests for the POST /mysql/test-connection endpoint."""

    ENDPOINT = f"{BASE}/test-connection"

    VALID_PAYLOAD = {
        "host": "mysql.example.com",
        "port": 3306,
        "database": "analytics",
        "user": "analyst",
        "password": "secret",
    }

    def test_test_connection_returns_200_on_success(self, client_as_developer):
        """Returns HTTP 200 when MySQL is reachable."""
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.test_connection.return_value = True
            response = client_as_developer.post(self.ENDPOINT, json=self.VALID_PAYLOAD)
        assert response.status_code == 200

    def test_test_connection_response_contains_status_connected(
        self, client_as_developer
    ):
        """Response body has status='connected' when connection succeeds."""
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.test_connection.return_value = True
            response = client_as_developer.post(self.ENDPOINT, json=self.VALID_PAYLOAD)
        body = response.json()
        assert body.get("status") == "connected"

    def test_test_connection_returns_503_on_failure(self, client_as_developer):
        """Returns HTTP 503 when MySQL is unreachable."""
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.test_connection.return_value = False
            response = client_as_developer.post(self.ENDPOINT, json=self.VALID_PAYLOAD)
        assert response.status_code == 503

    def test_test_connection_503_when_connector_raises(self, client_as_developer):
        """Returns 503 when MySQLConnector raises a connection error."""
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.test_connection.side_effect = MySQLConnectionError(
                "Host unreachable"
            )
            response = client_as_developer.post(self.ENDPOINT, json=self.VALID_PAYLOAD)
        assert response.status_code == 503

    def test_test_connection_422_for_missing_host(self, client_as_developer):
        """Returns 422 when required host field is missing."""
        payload = {
            "port": 3306,
            "database": "analytics",
            "user": "analyst",
            "password": "secret",
        }
        response = client_as_developer.post(self.ENDPOINT, json=payload)
        assert response.status_code == 422

    def test_test_connection_422_for_missing_database(self, client_as_developer):
        """Returns 422 when required database field is missing."""
        payload = {
            "host": "mysql.example.com",
            "port": 3306,
            "user": "analyst",
            "password": "secret",
        }
        response = client_as_developer.post(self.ENDPOINT, json=payload)
        assert response.status_code == 422

    def test_test_connection_requires_developer_role(self, client_as_viewer):
        """VIEWER role gets 403 Forbidden."""
        response = client_as_viewer.post(self.ENDPOINT, json=self.VALID_PAYLOAD)
        assert response.status_code == 403

    def test_test_connection_works_for_admin_role(self, client_as_admin):
        """ADMIN role can access the test-connection endpoint."""
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.test_connection.return_value = True
            response = client_as_admin.post(self.ENDPOINT, json=self.VALID_PAYLOAD)
        assert response.status_code == 200

    def test_test_connection_with_custom_charset(self, client_as_developer):
        """Returns 200 with custom charset parameter."""
        payload = {**self.VALID_PAYLOAD, "charset": "utf8"}
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.test_connection.return_value = True
            response = client_as_developer.post(self.ENDPOINT, json=payload)
        assert response.status_code == 200


# ===========================================================================
# POST /query
# ===========================================================================


class TestMySQLQuery:
    """Tests for the POST /mysql/query endpoint."""

    ENDPOINT = f"{BASE}/query"

    CONN_PARAMS = {
        "host": "mysql.example.com",
        "port": 3306,
        "database": "analytics",
        "user": "analyst",
        "password": "secret",
    }

    def test_query_returns_200_with_results(self, client_as_developer):
        """Returns 200 and a list of rows on success."""
        payload = {
            **self.CONN_PARAMS,
            "sql": "SELECT user_id, variant_id FROM assignments LIMIT 5",
        }
        fake_rows = [
            {"user_id": "u1", "variant_id": "control"},
            {"user_id": "u2", "variant_id": "treatment"},
        ]
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.execute_query.return_value = fake_rows
            response = client_as_developer.post(self.ENDPOINT, json=payload)
        assert response.status_code == 200

    def test_query_response_contains_rows(self, client_as_developer):
        """Response body contains 'rows' key with data."""
        payload = {**self.CONN_PARAMS, "sql": "SELECT 1 AS num"}
        fake_rows = [{"num": 1}]
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.execute_query.return_value = fake_rows
            response = client_as_developer.post(self.ENDPOINT, json=payload)
        body = response.json()
        assert "rows" in body
        assert len(body["rows"]) == 1

    def test_query_response_contains_row_count(self, client_as_developer):
        """Response body contains 'row_count' reflecting the number of rows."""
        payload = {**self.CONN_PARAMS, "sql": "SELECT 1 AS n"}
        fake_rows = [{"n": 1}, {"n": 2}]
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.execute_query.return_value = fake_rows
            response = client_as_developer.post(self.ENDPOINT, json=payload)
        body = response.json()
        assert body["row_count"] == 2

    def test_query_returns_400_for_dangerous_sql(self, client_as_developer):
        """Returns 400 when SQL contains DML/DDL statements."""
        payload = {**self.CONN_PARAMS, "sql": "DROP TABLE experiments"}
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.execute_query.side_effect = MySQLQueryError(
                "SQL statement not allowed"
            )
            response = client_as_developer.post(self.ENDPOINT, json=payload)
        assert response.status_code == 400

    def test_query_returns_503_on_connection_error(self, client_as_developer):
        """Returns 503 when connector cannot reach MySQL."""
        payload = {**self.CONN_PARAMS, "sql": "SELECT 1"}
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.execute_query.side_effect = MySQLConnectionError(
                "Connection refused"
            )
            response = client_as_developer.post(self.ENDPOINT, json=payload)
        assert response.status_code == 503

    def test_query_returns_422_for_missing_sql(self, client_as_developer):
        """Returns 422 when 'sql' field is absent."""
        payload = {**self.CONN_PARAMS}  # no 'sql' key
        response = client_as_developer.post(self.ENDPOINT, json=payload)
        assert response.status_code == 422

    def test_query_requires_developer_role(self, client_as_viewer):
        """VIEWER role gets 403."""
        payload = {**self.CONN_PARAMS, "sql": "SELECT 1"}
        response = client_as_viewer.post(self.ENDPOINT, json=payload)
        assert response.status_code == 403

    def test_query_returns_empty_rows_list(self, client_as_developer):
        """Returns 200 with rows=[] when query matches nothing."""
        payload = {**self.CONN_PARAMS, "sql": "SELECT id FROM experiments WHERE 1=0"}
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.execute_query.return_value = []
            response = client_as_developer.post(self.ENDPOINT, json=payload)
        assert response.status_code == 200
        assert response.json()["rows"] == []


# ===========================================================================
# GET /metrics/experiments/{experiment_id}
# ===========================================================================


class TestMySQLExperimentMetrics:
    """Tests for GET /mysql/metrics/experiments/{experiment_id}."""

    CONN_PARAMS = {
        "host": "mysql.example.com",
        "port": 3306,
        "database": "analytics",
        "user": "analyst",
        "password": "secret",
    }

    def _endpoint(self, experiment_id: str) -> str:
        return f"{BASE}/metrics/experiments/{experiment_id}"

    def test_get_experiment_metrics_returns_200(self, client_as_developer):
        """Returns 200 with experiment metrics."""
        exp_id = str(uuid.uuid4())
        fake_metrics = {
            "control": {"mean": 0.12, "count": 1000, "conversions": 120},
            "treatment": {"mean": 0.148, "count": 980, "conversions": 145},
        }
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.get_experiment_metrics.return_value = fake_metrics
            response = client_as_developer.get(
                self._endpoint(exp_id), params=self.CONN_PARAMS
            )
        assert response.status_code == 200

    def test_get_experiment_metrics_response_has_metrics_key(self, client_as_developer):
        """Response body includes a 'metrics' key."""
        exp_id = str(uuid.uuid4())
        fake_metrics = {"control": {"mean": 0.12, "count": 1000, "conversions": 120}}
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.get_experiment_metrics.return_value = fake_metrics
            response = client_as_developer.get(
                self._endpoint(exp_id), params=self.CONN_PARAMS
            )
        assert "metrics" in response.json()

    def test_get_experiment_metrics_503_on_connection_error(self, client_as_developer):
        """Returns 503 when connector cannot reach MySQL."""
        exp_id = str(uuid.uuid4())
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.get_experiment_metrics.side_effect = (
                MySQLConnectionError("Connection failed")
            )
            response = client_as_developer.get(
                self._endpoint(exp_id), params=self.CONN_PARAMS
            )
        assert response.status_code == 503

    def test_get_experiment_metrics_400_on_query_error(self, client_as_developer):
        """Returns 400 when the query fails."""
        exp_id = str(uuid.uuid4())
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.get_experiment_metrics.side_effect = MySQLQueryError(
                "Table does not exist"
            )
            response = client_as_developer.get(
                self._endpoint(exp_id), params=self.CONN_PARAMS
            )
        assert response.status_code == 400

    def test_get_experiment_metrics_requires_developer_role(self, client_as_viewer):
        """VIEWER role gets 403."""
        exp_id = str(uuid.uuid4())
        response = client_as_viewer.get(self._endpoint(exp_id), params=self.CONN_PARAMS)
        assert response.status_code == 403

    def test_get_experiment_metrics_returns_empty_for_unknown_id(
        self, client_as_developer
    ):
        """Returns 200 with empty metrics when experiment has no data."""
        exp_id = str(uuid.uuid4())
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.get_experiment_metrics.return_value = {}
            response = client_as_developer.get(
                self._endpoint(exp_id), params=self.CONN_PARAMS
            )
        assert response.status_code == 200
        assert response.json()["metrics"] == {}

    def test_get_experiment_metrics_422_for_missing_host(self, client_as_developer):
        """Returns 422 when required 'host' query param is missing."""
        exp_id = str(uuid.uuid4())
        params = {k: v for k, v in self.CONN_PARAMS.items() if k != "host"}
        response = client_as_developer.get(self._endpoint(exp_id), params=params)
        assert response.status_code == 422


# ===========================================================================
# GET /metrics/flags/{flag_id}
# ===========================================================================


class TestMySQLFeatureFlagMetrics:
    """Tests for GET /mysql/metrics/flags/{flag_id}."""

    CONN_PARAMS = {
        "host": "mysql.example.com",
        "port": 3306,
        "database": "analytics",
        "user": "analyst",
        "password": "secret",
    }

    def _endpoint(self, flag_id: str) -> str:
        return f"{BASE}/metrics/flags/{flag_id}"

    def test_get_flag_metrics_returns_200(self, client_as_developer):
        """Returns 200 with feature flag metrics."""
        flag_id = str(uuid.uuid4())
        fake_metrics = {
            "enabled": {"error_rate": 0.01, "requests": 5000, "errors": 50},
            "disabled": {"error_rate": 0.011, "requests": 4800, "errors": 53},
        }
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.get_feature_flag_metrics.return_value = fake_metrics
            response = client_as_developer.get(
                self._endpoint(flag_id), params=self.CONN_PARAMS
            )
        assert response.status_code == 200

    def test_get_flag_metrics_response_has_metrics_key(self, client_as_developer):
        """Response body includes a 'metrics' key."""
        flag_id = str(uuid.uuid4())
        fake_metrics = {"enabled": {"error_rate": 0.01, "requests": 5000, "errors": 50}}
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.get_feature_flag_metrics.return_value = fake_metrics
            response = client_as_developer.get(
                self._endpoint(flag_id), params=self.CONN_PARAMS
            )
        assert "metrics" in response.json()

    def test_get_flag_metrics_503_on_connection_error(self, client_as_developer):
        """Returns 503 when connector raises connection error."""
        flag_id = str(uuid.uuid4())
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.get_feature_flag_metrics.side_effect = (
                MySQLConnectionError("Timeout")
            )
            response = client_as_developer.get(
                self._endpoint(flag_id), params=self.CONN_PARAMS
            )
        assert response.status_code == 503

    def test_get_flag_metrics_400_on_query_error(self, client_as_developer):
        """Returns 400 when the query fails."""
        flag_id = str(uuid.uuid4())
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.get_feature_flag_metrics.side_effect = (
                MySQLQueryError("Table does not exist")
            )
            response = client_as_developer.get(
                self._endpoint(flag_id), params=self.CONN_PARAMS
            )
        assert response.status_code == 400

    def test_get_flag_metrics_requires_developer_role(self, client_as_viewer):
        """VIEWER role gets 403."""
        flag_id = str(uuid.uuid4())
        response = client_as_viewer.get(
            self._endpoint(flag_id), params=self.CONN_PARAMS
        )
        assert response.status_code == 403

    def test_get_flag_metrics_returns_empty_for_unknown_flag(self, client_as_developer):
        """Returns 200 with empty metrics when flag has no data."""
        flag_id = str(uuid.uuid4())
        with patch(
            "modules.backend.app.api.v1.endpoints.warehouse_mysql.MySQLConnector"
        ) as MockConn:
            MockConn.return_value.__enter__ = lambda s: s
            MockConn.return_value.__exit__ = MagicMock(return_value=False)
            MockConn.return_value.get_feature_flag_metrics.return_value = {}
            response = client_as_developer.get(
                self._endpoint(flag_id), params=self.CONN_PARAMS
            )
        assert response.status_code == 200
        assert response.json()["metrics"] == {}

    def test_get_flag_metrics_422_for_missing_host(self, client_as_developer):
        """Returns 422 when required 'host' query param is missing."""
        flag_id = str(uuid.uuid4())
        params = {k: v for k, v in self.CONN_PARAMS.items() if k != "host"}
        response = client_as_developer.get(self._endpoint(flag_id), params=params)
        assert response.status_code == 422
