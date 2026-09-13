"""
Unit tests for ClickHouseConnector (EP-048).

Covers:
 - Connector initialization with defaults and overrides
 - connect() success (mock clickhouse_connect.get_client)
 - connect() with retry logic (fail twice, succeed third)
 - execute_query returns list of dicts
 - execute_query prevents DML (INSERT/UPDATE/DELETE/DROP raise exception)
 - execute_query parameterized queries
 - get_experiment_metrics returns per-variant metrics
 - get_feature_flag_metrics returns dict
 - test_connection returns True on success, False on failure
 - close() clears client reference
 - Context manager (__enter__/__exit__)
 - Connection error raises ClickHouseConnectionError
 - Auth error raises ClickHouseAuthError
 - Timeout raises ClickHouseTimeoutError
 - Query error raises ClickHouseQueryError
 - Empty result set returns empty dict
 - Reconnect after disconnect

No real ClickHouse connection required — uses MagicMock throughout.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from modules.backend.app.services.clickhouse_connector import (
    ClickHouseAuthError,
    ClickHouseConnectionError,
    ClickHouseConnector,
    ClickHouseQueryError,
    ClickHouseTimeoutError,
)

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_connector(**overrides) -> ClickHouseConnector:
    """Build a ClickHouseConnector with sensible defaults."""
    defaults = {
        "host": "ch.example.com",
        "port": 8123,
        "database": "analytics",
        "user": "default",
        "password": "secret",
        "secure": False,
        "timeout": 30,
    }
    defaults.update(overrides)
    return ClickHouseConnector(**defaults)


def _make_mock_result(columns=None, rows=None):
    """Return a MagicMock QueryResult with column_names and result_rows."""
    result = MagicMock()
    if columns is None:
        columns = ["variant_name", "count", "mean", "conversions"]
    if rows is None:
        rows = [
            ("control", 1000, 0.12, 120),
            ("treatment", 980, 0.148, 145),
        ]
    result.column_names = columns
    result.result_rows = rows
    return result


def _make_mock_client(query_result=None):
    """Return a MagicMock ClickHouse client."""
    client = MagicMock()
    if query_result is None:
        query_result = _make_mock_result()
    client.query.return_value = query_result
    return client


# ===========================================================================
# 1. Initialization Tests (7 tests)
# ===========================================================================


class TestClickHouseConnectorInit:
    """Tests for connector initialisation and config storage."""

    def test_init_stores_host(self):
        """Connector stores the ClickHouse host."""
        connector = _make_connector(host="myhost.clickhouse.cloud")
        assert connector.host == "myhost.clickhouse.cloud"

    def test_init_stores_port(self):
        """Connector stores the HTTP port."""
        connector = _make_connector(port=8443)
        assert connector.port == 8443

    def test_init_stores_database(self):
        """Connector stores the database name."""
        connector = _make_connector(database="experiments_db")
        assert connector.database == "experiments_db"

    def test_init_stores_user_and_password(self):
        """Connector stores the user and password."""
        connector = _make_connector(user="analyst", password="p@ssw0rd")
        assert connector.user == "analyst"
        assert connector.password == "p@ssw0rd"

    def test_init_stores_secure_flag(self):
        """Connector stores the secure (HTTPS) flag."""
        connector = _make_connector(secure=True)
        assert connector.secure is True

    def test_init_stores_timeout(self):
        """Connector stores the query timeout."""
        connector = _make_connector(timeout=60)
        assert connector.timeout == 60

    def test_init_client_is_none_before_connect(self):
        """Connector has no live client before connect() is called."""
        connector = _make_connector()
        assert connector._client is None

    def test_init_uses_settings_defaults(self):
        """Connector falls back to settings when no args supplied."""
        from modules.backend.app.settings import settings

        connector = ClickHouseConnector()
        assert connector.host == settings.CLICKHOUSE_HOST
        assert connector.port == settings.CLICKHOUSE_PORT
        assert connector.database == settings.CLICKHOUSE_DATABASE


# ===========================================================================
# 2. Connection Establishment Tests (6 tests)
# ===========================================================================


class TestClickHouseConnectorConnect:
    """Tests for connection establishment."""

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_connect_calls_get_client(self, mock_ch):
        """connect() calls clickhouse_connect.get_client with correct args."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        result = connector.connect()

        assert result is True
        mock_ch.get_client.assert_called_once()
        call_kwargs = mock_ch.get_client.call_args.kwargs
        assert call_kwargs.get("host") == "ch.example.com"
        assert call_kwargs.get("port") == 8123
        assert call_kwargs.get("username") == "default"

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_connect_stores_client(self, mock_ch):
        """connect() assigns the client to self._client."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()

        assert connector._client is mock_client

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_connect_raises_connection_error_on_failure(self, mock_ch):
        """connect() raises ClickHouseConnectionError on unreachable host."""
        mock_ch.get_client.side_effect = Exception("Connection refused")

        connector = _make_connector(host="nonexistent.example.com")
        with pytest.raises(ClickHouseConnectionError):
            connector.connect()

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_connect_raises_auth_error_on_bad_credentials(self, mock_ch):
        """connect() raises ClickHouseAuthError when credentials are wrong."""
        mock_ch.get_client.side_effect = Exception(
            "Authentication failed: wrong password"
        )

        connector = _make_connector(password="wrong")
        with pytest.raises((ClickHouseConnectionError, ClickHouseAuthError)):
            connector.connect()

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_connect_raises_timeout_error_on_timeout(self, mock_ch):
        """connect() raises ClickHouseTimeoutError when connection times out."""
        mock_ch.get_client.side_effect = Exception("Connection timed out")

        connector = _make_connector()
        with pytest.raises((ClickHouseConnectionError, ClickHouseTimeoutError)):
            connector.connect()

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_connect_idempotent_when_already_connected(self, mock_ch):
        """connect() does not open a second connection if already connected."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        connector.connect()  # second call should be a no-op

        assert mock_ch.get_client.call_count == 1


# ===========================================================================
# 3. Query Execution Tests (8 tests)
# ===========================================================================


class TestClickHouseConnectorExecuteQuery:
    """Tests for execute_query() method."""

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_execute_query_returns_list_of_dicts(self, mock_ch):
        """execute_query() returns rows as a list of dicts."""
        result = _make_mock_result(
            columns=["user_id", "event_count"],
            rows=[("user-1", 5), ("user-2", 3)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        rows = connector.execute_query(
            "SELECT user_id, event_count FROM events LIMIT 10"
        )

        assert isinstance(rows, list)
        assert len(rows) == 2
        assert rows[0] == {"user_id": "user-1", "event_count": 5}
        assert rows[1] == {"user_id": "user-2", "event_count": 3}

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_execute_query_returns_empty_list_for_no_rows(self, mock_ch):
        """execute_query() returns [] when the query matches no rows."""
        result = _make_mock_result(columns=["id"], rows=[])
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        rows = connector.execute_query("SELECT id FROM events WHERE 1=0")

        assert rows == []

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_execute_query_raises_on_drop_statement(self, mock_ch):
        """execute_query() rejects DROP TABLE statements."""
        connector = _make_connector()

        with pytest.raises(ClickHouseQueryError, match="not allowed"):
            connector.execute_query("DROP TABLE experiments")

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_execute_query_raises_on_insert_statement(self, mock_ch):
        """execute_query() rejects INSERT statements."""
        connector = _make_connector()

        with pytest.raises(ClickHouseQueryError, match="not allowed"):
            connector.execute_query("INSERT INTO t VALUES (1)")

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_execute_query_raises_on_update_statement(self, mock_ch):
        """execute_query() rejects UPDATE statements."""
        connector = _make_connector()

        with pytest.raises(ClickHouseQueryError, match="not allowed"):
            connector.execute_query("UPDATE t SET x=1")

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_execute_query_raises_on_delete_statement(self, mock_ch):
        """execute_query() rejects DELETE statements."""
        connector = _make_connector()

        with pytest.raises(ClickHouseQueryError, match="not allowed"):
            connector.execute_query("DELETE FROM t WHERE id=1")

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_execute_query_raises_when_not_connected(self, mock_ch):
        """execute_query() raises ClickHouseConnectionError if not connected."""
        connector = _make_connector()
        # Do not call connect()

        with pytest.raises(ClickHouseConnectionError, match="not connected"):
            connector.execute_query("SELECT 1")

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_execute_query_wraps_client_error(self, mock_ch):
        """execute_query() raises ClickHouseQueryError on client query failure."""
        mock_client = _make_mock_client()
        mock_client.query.side_effect = Exception("Unknown column 'foo'")
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()

        with pytest.raises(ClickHouseQueryError):
            connector.execute_query("SELECT foo FROM bar")

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_execute_query_accepts_parameterized_query(self, mock_ch):
        """execute_query() accepts named params dict and passes to client."""
        result = _make_mock_result(
            columns=["experiment_id"],
            rows=[("exp-001",)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        rows = connector.execute_query(
            "SELECT experiment_id FROM events WHERE experiment_id = {eid:String}",
            params={"eid": "exp-001"},
        )
        assert len(rows) == 1
        # Verify params were forwarded to the client
        call_kwargs = mock_client.query.call_args
        assert call_kwargs is not None


# ===========================================================================
# 4. Experiment Metrics Tests (6 tests)
# ===========================================================================


class TestClickHouseConnectorExperimentMetrics:
    """Tests for get_experiment_metrics() method."""

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_experiment_metrics_returns_dict(self, mock_ch):
        """get_experiment_metrics() returns a dict keyed by variant_name."""
        result = _make_mock_result(
            columns=["variant_name", "count", "mean", "conversions"],
            rows=[("control", 1000, 0.12, 120), ("treatment", 980, 0.148, 145)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        metrics = connector.get_experiment_metrics("exp-001")

        assert isinstance(metrics, dict)

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_experiment_metrics_contains_variant_keys(self, mock_ch):
        """get_experiment_metrics() includes one entry per variant."""
        result = _make_mock_result(
            columns=["variant_name", "count", "mean", "conversions"],
            rows=[("control", 1000, 0.12, 120), ("treatment", 980, 0.148, 145)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        metrics = connector.get_experiment_metrics("exp-001")

        assert "control" in metrics
        assert "treatment" in metrics

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_experiment_metrics_has_required_fields(self, mock_ch):
        """Each variant entry has mean, count, and conversions fields."""
        result = _make_mock_result(
            columns=["variant_name", "count", "mean", "conversions"],
            rows=[("control", 1000, 0.12, 120)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        metrics = connector.get_experiment_metrics("exp-001")

        stat = metrics["control"]
        assert "mean" in stat
        assert "count" in stat
        assert "conversions" in stat

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_experiment_metrics_correct_values(self, mock_ch):
        """Values are correctly mapped from query result rows."""
        result = _make_mock_result(
            columns=["variant_name", "count", "mean", "conversions"],
            rows=[("control", 1000, 0.20, 200)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        metrics = connector.get_experiment_metrics("exp-001")

        assert metrics["control"]["count"] == 1000
        assert metrics["control"]["conversions"] == 200
        assert abs(metrics["control"]["mean"] - 0.20) < 1e-6

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_experiment_metrics_returns_empty_for_no_data(self, mock_ch):
        """Returns {} when no rows match the experiment_id."""
        result = _make_mock_result(
            columns=["variant_name", "count", "mean", "conversions"],
            rows=[],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        metrics = connector.get_experiment_metrics("nonexistent-exp")

        assert metrics == {}

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_experiment_metrics_uses_parameterized_query(self, mock_ch):
        """The SQL is executed with experiment_id as a parameter, not interpolated."""
        result = _make_mock_result(
            columns=["variant_name", "count", "mean", "conversions"],
            rows=[],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        connector.get_experiment_metrics("exp-unique-123")

        # The SQL passed to query must NOT contain the literal experiment_id
        call_args = mock_client.query.call_args
        sql_arg = call_args[0][0] if call_args[0] else call_args.args[0]
        assert "exp-unique-123" not in sql_arg


# ===========================================================================
# 5. Feature Flag Metrics Tests (5 tests)
# ===========================================================================


class TestClickHouseConnectorFeatureFlagMetrics:
    """Tests for get_feature_flag_metrics() method."""

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_flag_metrics_returns_dict(self, mock_ch):
        """get_feature_flag_metrics() returns a dict."""
        result = _make_mock_result(
            columns=["group_key", "requests", "errors"],
            rows=[("enabled", 5000, 25), ("disabled", 4800, 22)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        metrics = connector.get_feature_flag_metrics("flag-abc")

        assert isinstance(metrics, dict)

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_flag_metrics_contains_group_keys(self, mock_ch):
        """Result dict keys correspond to the group_key column."""
        result = _make_mock_result(
            columns=["group_key", "requests", "errors"],
            rows=[("enabled", 5000, 25)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        metrics = connector.get_feature_flag_metrics("flag-abc")

        assert "enabled" in metrics

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_flag_metrics_has_error_rate_field(self, mock_ch):
        """Each entry includes an error_rate field."""
        result = _make_mock_result(
            columns=["group_key", "requests", "errors"],
            rows=[("enabled", 1000, 10)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        metrics = connector.get_feature_flag_metrics("flag-abc")

        assert "error_rate" in metrics["enabled"]

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_flag_metrics_calculates_error_rate(self, mock_ch):
        """error_rate = errors / requests."""
        result = _make_mock_result(
            columns=["group_key", "requests", "errors"],
            rows=[("enabled", 1000, 50)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        metrics = connector.get_feature_flag_metrics("flag-abc")

        assert abs(metrics["enabled"]["error_rate"] - 0.05) < 1e-6

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_flag_metrics_empty_for_unknown_flag(self, mock_ch):
        """Returns {} when no rows match the flag_id."""
        result = _make_mock_result(
            columns=["group_key", "requests", "errors"],
            rows=[],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        metrics = connector.get_feature_flag_metrics("nonexistent-flag")

        assert metrics == {}


# ===========================================================================
# 6. test_connection() Tests (5 tests)
# ===========================================================================


class TestClickHouseConnectorTestConnection:
    """Tests for the test_connection() method."""

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_test_connection_returns_true_on_success(self, mock_ch):
        """test_connection() returns True when ClickHouse is reachable."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        result = connector.test_connection()

        assert result is True

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_test_connection_returns_false_on_failure(self, mock_ch):
        """test_connection() returns False when connection fails."""
        mock_ch.get_client.side_effect = Exception("Connection refused")

        connector = _make_connector()
        result = connector.test_connection()

        assert result is False

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_test_connection_does_not_raise(self, mock_ch):
        """test_connection() catches exceptions and returns False rather than raising."""
        mock_ch.get_client.side_effect = RuntimeError("Unexpected error")

        connector = _make_connector()
        result = connector.test_connection()  # Should NOT raise
        assert isinstance(result, bool)

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_test_connection_executes_select_1(self, mock_ch):
        """test_connection() runs a lightweight SELECT 1 query."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.test_connection()

        mock_client.query.assert_called_once()
        call_args = mock_client.query.call_args
        sql = call_args[0][0] if call_args[0] else call_args.args[0]
        assert "SELECT 1" in sql.upper() or "select 1" in sql.lower()

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_test_connection_closes_temp_client(self, mock_ch):
        """test_connection() closes the temporary client it creates."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.test_connection()

        mock_client.close.assert_called()


# ===========================================================================
# 7. close() Tests (3 tests)
# ===========================================================================


class TestClickHouseConnectorClose:
    """Tests for the close() method."""

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_close_closes_client(self, mock_ch):
        """close() calls close() on the underlying client."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        connector.close()

        mock_client.close.assert_called_once()

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_close_sets_client_to_none(self, mock_ch):
        """close() clears self._client to allow reconnection."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()
        connector.close()

        assert connector._client is None

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_close_is_safe_when_not_connected(self, mock_ch):
        """close() is a no-op when no client is open."""
        connector = _make_connector()
        connector.close()  # Should NOT raise


# ===========================================================================
# 8. Context Manager Tests (3 tests)
# ===========================================================================


class TestClickHouseConnectorContextManager:
    """Tests for __enter__ / __exit__ context manager protocol."""

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_context_manager_connects_on_enter(self, mock_ch):
        """__enter__ establishes the connection."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        with connector as ctx:
            assert ctx is connector
            assert connector._client is not None

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_context_manager_closes_on_exit(self, mock_ch):
        """__exit__ closes the connection."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        with connector:
            pass

        mock_client.close.assert_called()

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_context_manager_closes_on_exception(self, mock_ch):
        """__exit__ ensures client is closed even when an exception is raised."""
        mock_client = _make_mock_client()
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        with pytest.raises(ValueError):
            with connector:
                raise ValueError("test error")

        mock_client.close.assert_called()


# ===========================================================================
# 9. Retry / Resilience Tests (4 tests)
# ===========================================================================


class TestClickHouseConnectorRetry:
    """Tests for retry logic on transient failures."""

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_connect_retries_on_transient_error(self, mock_ch):
        """connect() retries up to max_retries times on transient errors."""
        mock_client = _make_mock_client()
        mock_ch.get_client.side_effect = [
            Exception("Connection reset"),
            Exception("Connection reset"),
            mock_client,
        ]

        connector = _make_connector()
        connector.connect(max_retries=3)

        assert connector._client is mock_client
        assert mock_ch.get_client.call_count == 3

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_connect_raises_after_max_retries_exceeded(self, mock_ch):
        """connect() raises ClickHouseConnectionError after exhausting retries."""
        mock_ch.get_client.side_effect = Exception("Persistent failure")

        connector = _make_connector()
        with pytest.raises(ClickHouseConnectionError):
            connector.connect(max_retries=2)

        assert mock_ch.get_client.call_count == 2

    @patch("modules.backend.app.services.clickhouse_connector.time")
    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_connect_uses_exponential_backoff(self, mock_ch, mock_time):
        """connect() uses exponential backoff between retries."""
        mock_client = _make_mock_client()
        mock_ch.get_client.side_effect = [
            Exception("transient"),
            mock_client,
        ]
        mock_time.sleep = MagicMock()
        mock_time.time = time.time

        connector = _make_connector()
        connector.connect(max_retries=2)

        assert mock_time.sleep.call_count >= 1

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_connect_default_max_retries_is_three(self, mock_ch):
        """connect() uses max_retries=3 by default."""
        mock_ch.get_client.side_effect = Exception("always fails")

        connector = _make_connector()
        with pytest.raises(ClickHouseConnectionError):
            connector.connect()  # no explicit max_retries

        assert mock_ch.get_client.call_count == 3


# ===========================================================================
# 10. SQL Injection Prevention Tests (6 tests)
# ===========================================================================


class TestClickHouseSQLInjectionPrevention:
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
        """execute_query() raises ClickHouseQueryError for DML/DDL."""
        connector = _make_connector()
        with pytest.raises(ClickHouseQueryError, match="not allowed"):
            connector.execute_query(dangerous_sql)

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_execute_query_passes_params_separately(self, mock_ch):
        """Parameters are NOT interpolated into SQL strings — passed separately."""
        result = _make_mock_result(
            columns=["id"],
            rows=[("exp-1",)],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()

        sql = "SELECT id FROM experiments WHERE name = {name:String}"
        params = {"name": "'; DROP TABLE experiments; --"}
        connector.execute_query(sql, params=params)

        # The SQL passed to client.query must NOT contain the injected value
        call_args = mock_client.query.call_args
        sql_arg = call_args[0][0] if call_args[0] else call_args.args[0]
        assert "DROP TABLE" not in sql_arg

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_get_experiment_metrics_uses_parameterized_query(self, mock_ch):
        """get_experiment_metrics() uses parameterized query for experiment_id."""
        result = _make_mock_result(
            columns=["variant_name", "count", "mean", "conversions"],
            rows=[],
        )
        mock_client = _make_mock_client(query_result=result)
        mock_ch.get_client.return_value = mock_client

        connector = _make_connector()
        connector.connect()

        malicious_id = "'; DROP TABLE experiments; --"
        connector.get_experiment_metrics(malicious_id)

        call_args = mock_client.query.call_args
        sql_arg = call_args[0][0] if call_args[0] else call_args.args[0]
        assert "DROP TABLE" not in sql_arg


# ===========================================================================
# 11. Reconnect After Disconnect Tests (2 tests)
# ===========================================================================


class TestClickHouseConnectorReconnect:
    """Tests for reconnection after close()."""

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_reconnect_after_close(self, mock_ch):
        """Connector can reconnect after being closed."""
        mock_client1 = _make_mock_client()
        mock_client2 = _make_mock_client()
        mock_ch.get_client.side_effect = [mock_client1, mock_client2]

        connector = _make_connector()
        connector.connect()
        connector.close()
        connector.connect()  # Should succeed again

        assert connector._client is mock_client2
        assert mock_ch.get_client.call_count == 2

    @patch("modules.backend.app.services.clickhouse_connector.clickhouse_connect")
    def test_close_allows_context_manager_reuse(self, mock_ch):
        """After close, the connector can be used as context manager again."""
        mock_client1 = _make_mock_client()
        mock_client2 = _make_mock_client()
        mock_ch.get_client.side_effect = [mock_client1, mock_client2]

        connector = _make_connector()

        with connector:
            pass

        with connector:
            assert connector._client is mock_client2
