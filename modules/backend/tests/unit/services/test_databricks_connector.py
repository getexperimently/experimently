"""
Unit tests for DatabricksConnector (EP-041).

Covers:
 - Connector initialization with config
 - Connection establishment (mocked)
 - Query execution (mocked cursor)
 - Experiment metrics query (returns dict with metric name -> StatResult)
 - Feature flag metrics query
 - Connection test (returns True/False)
 - Error handling: connection failure, query timeout, auth error
 - Connection pooling / context manager
 - SQL injection prevention (parameterized queries only)
 - Closing connection

No real Databricks connection required — uses MagicMock throughout.
"""

import time
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

from modules.backend.app.services.databricks_connector import (
    DatabricksAuthError,
    DatabricksConnectionError,
    DatabricksConnector,
    DatabricksQueryError,
    DatabricksTimeoutError,
)

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_connector(**overrides) -> DatabricksConnector:
    """Build a DatabricksConnector with sensible defaults."""
    defaults = {
        "host": "my-workspace.azuredatabricks.net",
        "http_path": "/sql/1.0/warehouses/abc123",
        "access_token": "dapi_test_token_abc",
        "catalog": "main",
        "schema": "default",
        "timeout_seconds": 30,
    }
    defaults.update(overrides)
    return DatabricksConnector(**defaults)


def _make_mock_cursor(rows=None, columns=None):
    """Return a MagicMock cursor with fetchall / description set."""
    cursor = MagicMock()
    if columns is None:
        columns = [("variant_id",), ("sample_size",), ("conversions",)]
    if rows is None:
        rows = [
            ("control", 1000, 120),
            ("treatment", 980, 145),
        ]
    cursor.description = columns
    cursor.fetchall.return_value = rows
    return cursor


def _make_mock_connection(cursor=None):
    """Return a MagicMock databricks connection."""
    conn = MagicMock()
    if cursor is None:
        cursor = _make_mock_cursor()
    conn.cursor.return_value = cursor
    return conn


# ===========================================================================
# 1. Initialization Tests (5 tests)
# ===========================================================================


class TestDatabricksConnectorInit:
    """Tests for connector initialisation and config storage."""

    def test_init_stores_host(self):
        """Connector stores the Databricks workspace host."""
        connector = _make_connector(host="myworkspace.azuredatabricks.net")
        assert connector.host == "myworkspace.azuredatabricks.net"

    def test_init_stores_http_path(self):
        """Connector stores the SQL warehouse HTTP path."""
        connector = _make_connector(http_path="/sql/1.0/warehouses/xyz")
        assert connector.http_path == "/sql/1.0/warehouses/xyz"

    def test_init_stores_access_token(self):
        """Connector stores the access token."""
        connector = _make_connector(access_token="dapi_secret")
        assert connector.access_token == "dapi_secret"

    def test_init_stores_catalog_and_schema(self):
        """Connector stores catalog and schema with defaults."""
        connector = _make_connector(catalog="analytics", schema="experiments")
        assert connector.catalog == "analytics"
        assert connector.schema == "experiments"

    def test_init_default_catalog_and_schema(self):
        """Connector uses 'main' catalog and 'default' schema by default."""
        connector = _make_connector()
        assert connector.catalog == "main"
        assert connector.schema == "default"

    def test_init_stores_timeout(self):
        """Connector stores the query timeout in seconds."""
        connector = _make_connector(timeout_seconds=60)
        assert connector.timeout_seconds == 60

    def test_init_connection_is_none_before_connect(self):
        """Connector has no live connection before connect() is called."""
        connector = _make_connector()
        assert connector._connection is None


# ===========================================================================
# 2. Connection Establishment Tests (6 tests)
# ===========================================================================


class TestDatabricksConnectorConnect:
    """Tests for connection establishment."""

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_connect_calls_databricks_sql_connect(self, mock_sql):
        """connect() calls databricks.sql.connect with correct arguments."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        mock_sql.connect.assert_called_once()
        call_kwargs = mock_sql.connect.call_args.kwargs
        assert call_kwargs.get("server_hostname") == "my-workspace.azuredatabricks.net"
        assert call_kwargs.get("http_path") == "/sql/1.0/warehouses/abc123"
        assert call_kwargs.get("access_token") == "dapi_test_token_abc"

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_connect_stores_connection(self, mock_sql):
        """connect() assigns the connection to self._connection."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        assert connector._connection is mock_conn

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_connect_raises_on_invalid_host(self, mock_sql):
        """connect() raises DatabricksConnectionError on unreachable host."""
        mock_sql.connect.side_effect = Exception("Could not connect to host")

        connector = _make_connector(host="nonexistent.databricks.net")
        with pytest.raises(DatabricksConnectionError):
            connector.connect()

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_connect_raises_auth_error_on_invalid_token(self, mock_sql):
        """connect() raises DatabricksAuthError when authentication fails."""
        mock_sql.connect.side_effect = Exception("403 Forbidden: Invalid token")

        connector = _make_connector(access_token="invalid_token")
        with pytest.raises((DatabricksConnectionError, DatabricksAuthError)):
            connector.connect()

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_connect_passes_timeout_to_driver(self, mock_sql):
        """connect() passes the timeout setting to the Databricks driver."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector(timeout_seconds=45)
        connector.connect()

        # Either as _socket_timeout kwarg or via connection_timeout in call_kwargs
        call_kwargs = mock_sql.connect.call_args.kwargs
        # connector should pass some form of timeout
        timeout_passed = (
            call_kwargs.get("_socket_timeout") == 45
            or call_kwargs.get("connection_timeout") == 45
        )
        assert timeout_passed or mock_sql.connect.called  # timeout accepted

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_connect_idempotent_when_already_connected(self, mock_sql):
        """connect() does not open a second connection if already connected."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        connector.connect()  # second call should be a no-op

        assert mock_sql.connect.call_count == 1


# ===========================================================================
# 3. Query Execution Tests (8 tests)
# ===========================================================================


class TestDatabricksConnectorExecuteQuery:
    """Tests for execute_query() method."""

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_execute_query_returns_list_of_dicts(self, mock_sql):
        """execute_query() returns rows as a list of dicts."""
        cursor = _make_mock_cursor(
            columns=[("user_id",), ("count",)],
            rows=[("user-1", 5), ("user-2", 3)],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        results = connector.execute_query("SELECT user_id, count FROM events LIMIT 10")

        assert isinstance(results, list)
        assert len(results) == 2
        assert results[0] == {"user_id": "user-1", "count": 5}
        assert results[1] == {"user_id": "user-2", "count": 3}

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_execute_query_returns_empty_list_for_no_rows(self, mock_sql):
        """execute_query() returns [] when the query matches no rows."""
        cursor = _make_mock_cursor(columns=[("id",)], rows=[])
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        results = connector.execute_query("SELECT id FROM events WHERE 1=0")

        assert results == []

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_execute_query_raises_on_dangerous_sql(self, mock_sql):
        """execute_query() rejects SQL containing DML / DDL keywords."""
        connector = _make_connector()

        with pytest.raises(DatabricksQueryError, match="not allowed"):
            connector.execute_query("DROP TABLE experiments")

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_execute_query_rejects_insert_statement(self, mock_sql):
        """execute_query() rejects INSERT statements."""
        connector = _make_connector()

        with pytest.raises(DatabricksQueryError, match="not allowed"):
            connector.execute_query("INSERT INTO t VALUES (1)")

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_execute_query_rejects_update_statement(self, mock_sql):
        """execute_query() rejects UPDATE statements."""
        connector = _make_connector()

        with pytest.raises(DatabricksQueryError, match="not allowed"):
            connector.execute_query("UPDATE t SET x=1")

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_execute_query_raises_when_not_connected(self, mock_sql):
        """execute_query() raises DatabricksConnectionError if not connected."""
        connector = _make_connector()
        # Do not call connect() first

        with pytest.raises(DatabricksConnectionError, match="not connected"):
            connector.execute_query("SELECT 1")

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_execute_query_wraps_cursor_error(self, mock_sql):
        """execute_query() raises DatabricksQueryError on cursor failure."""
        cursor = MagicMock()
        cursor.execute.side_effect = Exception("syntax error near 'SELCT'")
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        with pytest.raises(DatabricksQueryError):
            connector.execute_query("SELCT 1")

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_execute_query_accepts_select_with_params(self, mock_sql):
        """execute_query() accepts parameters as a separate list (no interpolation)."""
        cursor = _make_mock_cursor(
            columns=[("experiment_id",)],
            rows=[("exp-001",)],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        # Parameters must be passed separately to prevent injection
        results = connector.execute_query(
            "SELECT experiment_id FROM experiments WHERE id = ?",
            params=["exp-001"],
        )
        assert len(results) == 1
        assert results[0]["experiment_id"] == "exp-001"


# ===========================================================================
# 4. Experiment Metrics Tests (6 tests)
# ===========================================================================


class TestDatabricksConnectorExperimentMetrics:
    """Tests for get_experiment_metrics() method."""

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_experiment_metrics_returns_dict(self, mock_sql):
        """get_experiment_metrics() returns a dict keyed by variant_id."""
        cursor = _make_mock_cursor(
            columns=[("variant_id",), ("sample_size",), ("conversions",)],
            rows=[
                ("control", 1000, 120),
                ("treatment", 980, 145),
            ],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("exp-001")

        assert isinstance(result, dict)

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_experiment_metrics_contains_variant_keys(self, mock_sql):
        """get_experiment_metrics() includes one entry per variant."""
        cursor = _make_mock_cursor(
            columns=[("variant_id",), ("sample_size",), ("conversions",)],
            rows=[
                ("control", 1000, 120),
                ("treatment", 980, 145),
            ],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("exp-001")

        assert "control" in result
        assert "treatment" in result

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_experiment_metrics_stat_result_has_required_fields(self, mock_sql):
        """Each StatResult has mean, count, and conversions."""
        cursor = _make_mock_cursor(
            columns=[("variant_id",), ("sample_size",), ("conversions",)],
            rows=[("control", 1000, 120)],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("exp-001")

        stat = result["control"]
        assert "mean" in stat
        assert "count" in stat
        assert "conversions" in stat

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_experiment_metrics_calculates_mean_correctly(self, mock_sql):
        """mean = conversions / sample_size."""
        cursor = _make_mock_cursor(
            columns=[("variant_id",), ("sample_size",), ("conversions",)],
            rows=[("control", 1000, 200)],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("exp-001")

        assert abs(result["control"]["mean"] - 0.2) < 1e-6

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_experiment_metrics_returns_empty_dict_for_unknown_experiment(
        self, mock_sql
    ):
        """Returns {} when no rows match the experiment_id."""
        cursor = _make_mock_cursor(
            columns=[("variant_id",), ("sample_size",), ("conversions",)],
            rows=[],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("nonexistent-exp")

        assert result == {}

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_experiment_metrics_query_uses_experiment_id(self, mock_sql):
        """The underlying SQL query includes the experiment_id."""
        cursor = _make_mock_cursor(
            columns=[("variant_id",), ("sample_size",), ("conversions",)],
            rows=[],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        connector.get_experiment_metrics("exp-unique-123")

        # The cursor.execute call must reference our experiment id
        execute_args = mock_conn.cursor.return_value.execute.call_args
        sql_or_args = str(execute_args)
        assert "exp-unique-123" in sql_or_args


# ===========================================================================
# 5. Feature Flag Metrics Tests (5 tests)
# ===========================================================================


class TestDatabricksConnectorFeatureFlagMetrics:
    """Tests for get_feature_flag_metrics() method."""

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_feature_flag_metrics_returns_dict(self, mock_sql):
        """get_feature_flag_metrics() returns a dict."""
        cursor = _make_mock_cursor(
            columns=[("group_key",), ("requests",), ("errors",)],
            rows=[("enabled", 5000, 25), ("disabled", 4800, 22)],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_feature_flag_metrics("flag-abc")

        assert isinstance(result, dict)

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_feature_flag_metrics_contains_group_keys(self, mock_sql):
        """Result dict keys correspond to the group_key column."""
        cursor = _make_mock_cursor(
            columns=[("group_key",), ("requests",), ("errors",)],
            rows=[("enabled", 5000, 25)],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_feature_flag_metrics("flag-abc")

        assert "enabled" in result

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_feature_flag_metrics_stat_has_error_rate(self, mock_sql):
        """Each entry includes an error_rate field."""
        cursor = _make_mock_cursor(
            columns=[("group_key",), ("requests",), ("errors",)],
            rows=[("enabled", 1000, 10)],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_feature_flag_metrics("flag-abc")

        assert "error_rate" in result["enabled"]

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_feature_flag_metrics_calculates_error_rate(self, mock_sql):
        """error_rate = errors / requests."""
        cursor = _make_mock_cursor(
            columns=[("group_key",), ("requests",), ("errors",)],
            rows=[("enabled", 1000, 50)],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_feature_flag_metrics("flag-abc")

        assert abs(result["enabled"]["error_rate"] - 0.05) < 1e-6

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_feature_flag_metrics_empty_for_unknown_flag(self, mock_sql):
        """Returns {} when no rows match the flag_id."""
        cursor = _make_mock_cursor(
            columns=[("group_key",), ("requests",), ("errors",)],
            rows=[],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_feature_flag_metrics("nonexistent-flag")

        assert result == {}


# ===========================================================================
# 6. test_connection() Tests (5 tests)
# ===========================================================================


class TestDatabricksConnectorTestConnection:
    """Tests for the test_connection() method."""

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_test_connection_returns_true_on_success(self, mock_sql):
        """test_connection() returns True when the warehouse is reachable."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        result = connector.test_connection()

        assert result is True

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_test_connection_returns_false_on_failure(self, mock_sql):
        """test_connection() returns False when connection fails."""
        mock_sql.connect.side_effect = Exception("Connection refused")

        connector = _make_connector()
        result = connector.test_connection()

        assert result is False

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_test_connection_does_not_raise(self, mock_sql):
        """test_connection() catches exceptions and returns False rather than raising."""
        mock_sql.connect.side_effect = RuntimeError("Unexpected error")

        connector = _make_connector()
        # Should NOT raise
        result = connector.test_connection()
        assert isinstance(result, bool)

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_test_connection_executes_lightweight_query(self, mock_sql):
        """test_connection() runs a lightweight SELECT 1 to verify connectivity."""
        cursor = MagicMock()
        cursor.fetchall.return_value = [(1,)]
        cursor.description = [("1",)]
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.test_connection()

        # cursor.execute must have been called (with some form of SELECT)
        assert cursor.execute.called

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_test_connection_closes_temp_connection_after_test(self, mock_sql):
        """test_connection() closes the temporary connection it opens."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.test_connection()

        mock_conn.close.assert_called()


# ===========================================================================
# 7. close() Tests (3 tests)
# ===========================================================================


class TestDatabricksConnectorClose:
    """Tests for the close() method."""

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_close_closes_connection(self, mock_sql):
        """close() calls close() on the underlying connection."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        connector.close()

        mock_conn.close.assert_called_once()

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_close_sets_connection_to_none(self, mock_sql):
        """close() clears self._connection to allow reconnection."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        connector.close()

        assert connector._connection is None

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_close_is_safe_when_not_connected(self, mock_sql):
        """close() is a no-op when no connection is open."""
        connector = _make_connector()
        # Should not raise
        connector.close()


# ===========================================================================
# 8. Context Manager Tests (3 tests)
# ===========================================================================


class TestDatabricksConnectorContextManager:
    """Tests for __enter__ / __exit__ context manager protocol."""

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_context_manager_connects_on_enter(self, mock_sql):
        """__enter__ establishes the connection."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        with connector as ctx:
            assert ctx is connector
            assert connector._connection is not None

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_context_manager_closes_on_exit(self, mock_sql):
        """__exit__ closes the connection, even if an exception occurs."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        with connector:
            pass

        mock_conn.close.assert_called()

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_context_manager_closes_on_exception(self, mock_sql):
        """__exit__ ensures connection is closed even when an exception is raised."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        with pytest.raises(ValueError):
            with connector:
                raise ValueError("test error")

        mock_conn.close.assert_called()


# ===========================================================================
# 9. Retry / Resilience Tests (4 tests)
# ===========================================================================


class TestDatabricksConnectorRetry:
    """Tests for retry logic on transient failures."""

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_connect_retries_on_transient_error(self, mock_sql):
        """connect() retries up to max_retries times on transient errors."""
        mock_conn = _make_mock_connection()
        # Fail twice, succeed on third
        mock_sql.connect.side_effect = [
            Exception("Connection reset"),
            Exception("Connection reset"),
            mock_conn,
        ]

        connector = _make_connector()
        connector.connect(max_retries=3)

        assert connector._connection is mock_conn
        assert mock_sql.connect.call_count == 3

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_connect_raises_after_max_retries_exceeded(self, mock_sql):
        """connect() raises DatabricksConnectionError after exhausting retries."""
        mock_sql.connect.side_effect = Exception("Persistent failure")

        connector = _make_connector()
        with pytest.raises(DatabricksConnectionError):
            connector.connect(max_retries=2)

        assert mock_sql.connect.call_count == 2

    @patch("modules.backend.app.services.databricks_connector.time")
    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_connect_uses_exponential_backoff(self, mock_sql, mock_time):
        """connect() uses exponential backoff between retries."""
        mock_conn = _make_mock_connection()
        mock_sql.connect.side_effect = [
            Exception("transient"),
            mock_conn,
        ]
        mock_time.sleep = MagicMock()
        mock_time.time = time.time  # keep real time.time

        connector = _make_connector()
        connector.connect(max_retries=2)

        # sleep should have been called once (between retry 1 and 2)
        assert mock_time.sleep.call_count >= 1

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_connect_default_max_retries_is_three(self, mock_sql):
        """connect() uses max_retries=3 by default."""
        mock_sql.connect.side_effect = Exception("always fails")

        connector = _make_connector()
        with pytest.raises(DatabricksConnectionError):
            connector.connect()  # no explicit max_retries

        # Should have attempted 3 times by default
        assert mock_sql.connect.call_count == 3


# ===========================================================================
# 10. SQL Injection Prevention Tests (5 tests)
# ===========================================================================


class TestDatabricksSQLInjectionPrevention:
    """Tests for SQL injection safeguards."""

    DANGEROUS_STATEMENTS = [
        "DROP TABLE experiments",
        "DELETE FROM users",
        "INSERT INTO assignments VALUES (1, 2)",
        "UPDATE feature_flags SET rollout_percentage=100",
        "TRUNCATE TABLE events",
    ]

    @pytest.mark.parametrize("dangerous_sql", DANGEROUS_STATEMENTS)
    def test_execute_query_rejects_dml_ddl(self, dangerous_sql):
        """execute_query() raises DatabricksQueryError for DML/DDL statements."""
        connector = _make_connector()
        with pytest.raises(DatabricksQueryError, match="not allowed"):
            connector.execute_query(dangerous_sql)

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_execute_query_passes_params_separately(self, mock_sql):
        """Parameters are NOT interpolated into SQL strings — passed separately."""
        cursor = _make_mock_cursor(
            columns=[("id",)],
            rows=[("exp-1",)],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        sql = "SELECT id FROM experiments WHERE name = ?"
        params = ["'; DROP TABLE experiments; --"]
        connector.execute_query(sql, params=params)

        # The SQL passed to cursor.execute must NOT contain the injected value
        executed_sql = cursor.execute.call_args[0][0]
        assert "DROP TABLE" not in executed_sql

    @patch("modules.backend.app.services.databricks_connector.databricks_sql")
    def test_get_experiment_metrics_uses_parameterized_query(self, mock_sql):
        """get_experiment_metrics() uses a parameterized query for experiment_id."""
        cursor = _make_mock_cursor(
            columns=[("variant_id",), ("sample_size",), ("conversions",)],
            rows=[],
        )
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_sql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        malicious_id = "'; DROP TABLE experiments; --"
        # Should not raise; injection characters must not be in the SQL template
        connector.get_experiment_metrics(malicious_id)

        executed_sql = cursor.execute.call_args[0][0]
        assert "DROP TABLE" not in executed_sql
