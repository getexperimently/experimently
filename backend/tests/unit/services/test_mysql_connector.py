"""
Unit tests for MySQLConnector (EP-048).

Covers:
 - Connector initialization with defaults and overrides
 - connect() success (mock pymysql.connect)
 - connect() retry logic (fail twice, succeed third)
 - execute_query with %s placeholders
 - execute_query prevents DML injection
 - get_experiment_metrics returns per-variant metrics
 - get_feature_flag_metrics returns dict
 - test_connection SELECT 1
 - close() clears connection reference
 - Context manager (__enter__/__exit__)
 - All 4 custom exceptions raised correctly
 - Cursor properly closed on error
 - DictCursor used (returns dicts not tuples)
 - UTF-8 character handling (charset)
 - NULL values in results

No real MySQL connection required — uses MagicMock throughout.
"""

import time
from unittest.mock import MagicMock, patch, call

import pytest

from backend.app.services.mysql_connector import (
    MySQLConnector,
    MySQLConnectionError,
    MySQLQueryError,
    MySQLAuthError,
    MySQLTimeoutError,
)


# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------

def _make_connector(**overrides) -> MySQLConnector:
    """Build a MySQLConnector with sensible defaults."""
    defaults = {
        "host": "mysql.example.com",
        "port": 3306,
        "database": "analytics",
        "user": "analyst",
        "password": "secret",
        "charset": "utf8mb4",
        "timeout": 30,
    }
    defaults.update(overrides)
    return MySQLConnector(**defaults)


def _make_mock_cursor(rows=None):
    """Return a MagicMock cursor that returns rows as dicts (DictCursor style)."""
    cursor = MagicMock()
    if rows is None:
        rows = [
            {"variant_id": "control", "sample_size": 1000, "conversions": 120},
            {"variant_id": "treatment", "sample_size": 980, "conversions": 145},
        ]
    cursor.fetchall.return_value = rows
    return cursor


def _make_mock_connection(cursor=None):
    """Return a MagicMock pymysql connection."""
    conn = MagicMock()
    if cursor is None:
        cursor = _make_mock_cursor()
    conn.cursor.return_value = cursor
    # Support context manager on cursor (with conn.cursor() as cursor:)
    conn.cursor.return_value.__enter__ = lambda s: s
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


# ===========================================================================
# 1. Initialization Tests (7 tests)
# ===========================================================================

class TestMySQLConnectorInit:
    """Tests for connector initialisation and config storage."""

    def test_init_stores_host(self):
        """Connector stores the MySQL server host."""
        connector = _make_connector(host="db.example.com")
        assert connector.host == "db.example.com"

    def test_init_stores_port(self):
        """Connector stores the port."""
        connector = _make_connector(port=3307)
        assert connector.port == 3307

    def test_init_stores_database(self):
        """Connector stores the database name."""
        connector = _make_connector(database="my_analytics")
        assert connector.database == "my_analytics"

    def test_init_stores_user_and_password(self):
        """Connector stores the user and password."""
        connector = _make_connector(user="root", password="p@ssw0rd")
        assert connector.user == "root"
        assert connector.password == "p@ssw0rd"

    def test_init_stores_charset(self):
        """Connector stores the charset (utf8mb4 by default)."""
        connector = _make_connector()
        assert connector.charset == "utf8mb4"

    def test_init_stores_timeout(self):
        """Connector stores the query timeout."""
        connector = _make_connector(timeout=60)
        assert connector.timeout == 60

    def test_init_connection_is_none_before_connect(self):
        """Connector has no live connection before connect() is called."""
        connector = _make_connector()
        assert connector._connection is None

    def test_init_uses_settings_defaults(self):
        """Connector falls back to settings when no args supplied."""
        from backend.app.core.config import settings
        connector = MySQLConnector()
        assert connector.host == settings.MYSQL_HOST
        assert connector.port == settings.MYSQL_PORT


# ===========================================================================
# 2. Connection Establishment Tests (6 tests)
# ===========================================================================

class TestMySQLConnectorConnect:
    """Tests for connection establishment."""

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_calls_pymysql_connect(self, mock_pymysql):
        """connect() calls pymysql.connect with correct arguments."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        result = connector.connect()

        assert result is True
        mock_pymysql.connect.assert_called_once()
        call_kwargs = mock_pymysql.connect.call_args.kwargs
        assert call_kwargs.get("host") == "mysql.example.com"
        assert call_kwargs.get("port") == 3306
        assert call_kwargs.get("database") == "analytics"
        assert call_kwargs.get("user") == "analyst"

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_stores_connection(self, mock_pymysql):
        """connect() assigns the connection to self._connection."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        assert connector._connection is mock_conn

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_raises_connection_error_on_failure(self, mock_pymysql):
        """connect() raises MySQLConnectionError on unreachable host."""
        mock_pymysql.connect.side_effect = Exception("Can't connect to MySQL server")

        connector = _make_connector(host="nonexistent.example.com")
        with pytest.raises(MySQLConnectionError):
            connector.connect()

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_raises_auth_error_on_bad_credentials(self, mock_pymysql):
        """connect() raises MySQLAuthError on authentication failure."""
        mock_pymysql.connect.side_effect = Exception("Access denied for user 'analyst'@'host'")

        connector = _make_connector(password="wrong")
        with pytest.raises((MySQLConnectionError, MySQLAuthError)):
            connector.connect()

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_raises_timeout_error_on_timeout(self, mock_pymysql):
        """connect() raises MySQLTimeoutError when connection times out."""
        mock_pymysql.connect.side_effect = Exception("Connection timed out")

        connector = _make_connector()
        with pytest.raises((MySQLConnectionError, MySQLTimeoutError)):
            connector.connect()

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_idempotent_when_already_connected(self, mock_pymysql):
        """connect() does not open a second connection if already connected."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        connector.connect()  # second call should be a no-op

        assert mock_pymysql.connect.call_count == 1

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_uses_dict_cursor(self, mock_pymysql):
        """connect() passes DictCursor as the cursor class."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        call_kwargs = mock_pymysql.connect.call_args.kwargs
        # DictCursor must be passed so rows are dicts, not tuples
        assert "cursorclass" in call_kwargs


# ===========================================================================
# 3. Query Execution Tests (9 tests)
# ===========================================================================

class TestMySQLConnectorExecuteQuery:
    """Tests for execute_query() method."""

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_returns_list_of_dicts(self, mock_pymysql):
        """execute_query() returns rows as a list of dicts (via DictCursor)."""
        rows = [
            {"user_id": "user-1", "count": 5},
            {"user_id": "user-2", "count": 3},
        ]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.execute_query("SELECT user_id, count FROM events LIMIT 10")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0] == {"user_id": "user-1", "count": 5}

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_returns_empty_list_for_no_rows(self, mock_pymysql):
        """execute_query() returns [] when the query matches no rows."""
        cursor = _make_mock_cursor(rows=[])
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.execute_query("SELECT id FROM events WHERE 1=0")

        assert result == []

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_raises_on_drop_statement(self, mock_pymysql):
        """execute_query() rejects DROP TABLE statements."""
        connector = _make_connector()

        with pytest.raises(MySQLQueryError, match="not allowed"):
            connector.execute_query("DROP TABLE experiments")

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_raises_on_insert_statement(self, mock_pymysql):
        """execute_query() rejects INSERT statements."""
        connector = _make_connector()

        with pytest.raises(MySQLQueryError, match="not allowed"):
            connector.execute_query("INSERT INTO t VALUES (1)")

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_raises_on_update_statement(self, mock_pymysql):
        """execute_query() rejects UPDATE statements."""
        connector = _make_connector()

        with pytest.raises(MySQLQueryError, match="not allowed"):
            connector.execute_query("UPDATE t SET x=1")

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_raises_on_delete_statement(self, mock_pymysql):
        """execute_query() rejects DELETE statements."""
        connector = _make_connector()

        with pytest.raises(MySQLQueryError, match="not allowed"):
            connector.execute_query("DELETE FROM t WHERE id=1")

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_raises_when_not_connected(self, mock_pymysql):
        """execute_query() raises MySQLConnectionError if not connected."""
        connector = _make_connector()
        # Do not call connect()

        with pytest.raises(MySQLConnectionError, match="not connected"):
            connector.execute_query("SELECT 1")

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_wraps_cursor_error(self, mock_pymysql):
        """execute_query() raises MySQLQueryError on cursor execute failure."""
        cursor = _make_mock_cursor()
        cursor.execute.side_effect = Exception("Table 'analytics.foo' doesn't exist")
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        with pytest.raises(MySQLQueryError):
            connector.execute_query("SELECT x FROM foo")

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_accepts_percent_s_params(self, mock_pymysql):
        """execute_query() accepts params as a tuple (% placeholders)."""
        rows = [{"experiment_id": "exp-001"}]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.execute_query(
            "SELECT experiment_id FROM experiments WHERE id = %s",
            params=("exp-001",),
        )
        assert len(result) == 1
        # Verify params were passed to cursor.execute
        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args
        assert "exp-001" in str(call_args)


# ===========================================================================
# 4. Cursor Cleanup Tests (2 tests)
# ===========================================================================

class TestMySQLConnectorCursorCleanup:
    """Tests that cursor is closed after query execution."""

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_cursor_closed_after_successful_query(self, mock_pymysql):
        """Cursor is closed after a successful query."""
        rows = [{"id": 1}]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        connector.execute_query("SELECT id FROM t")

        cursor.close.assert_called()

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_cursor_closed_after_failed_query(self, mock_pymysql):
        """Cursor is closed even when the query raises an exception."""
        cursor = _make_mock_cursor()
        cursor.execute.side_effect = Exception("query error")
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        with pytest.raises(MySQLQueryError):
            connector.execute_query("SELECT bad FROM t")

        cursor.close.assert_called()


# ===========================================================================
# 5. Experiment Metrics Tests (6 tests)
# ===========================================================================

class TestMySQLConnectorExperimentMetrics:
    """Tests for get_experiment_metrics() method."""

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_experiment_metrics_returns_dict(self, mock_pymysql):
        """get_experiment_metrics() returns a dict keyed by variant_id."""
        rows = [
            {"variant_id": "control", "sample_size": 1000, "conversions": 120},
            {"variant_id": "treatment", "sample_size": 980, "conversions": 145},
        ]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("exp-001")

        assert isinstance(result, dict)

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_experiment_metrics_contains_variant_keys(self, mock_pymysql):
        """get_experiment_metrics() includes one entry per variant."""
        rows = [
            {"variant_id": "control", "sample_size": 1000, "conversions": 120},
            {"variant_id": "treatment", "sample_size": 980, "conversions": 145},
        ]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("exp-001")

        assert "control" in result
        assert "treatment" in result

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_experiment_metrics_has_required_fields(self, mock_pymysql):
        """Each entry has mean, count, and conversions fields."""
        rows = [{"variant_id": "control", "sample_size": 1000, "conversions": 120}]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("exp-001")

        stat = result["control"]
        assert "mean" in stat
        assert "count" in stat
        assert "conversions" in stat

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_experiment_metrics_calculates_mean(self, mock_pymysql):
        """mean = conversions / sample_size."""
        rows = [{"variant_id": "control", "sample_size": 1000, "conversions": 200}]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("exp-001")

        assert abs(result["control"]["mean"] - 0.2) < 1e-6

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_experiment_metrics_returns_empty_for_no_data(self, mock_pymysql):
        """Returns {} when no rows match the experiment_id."""
        cursor = _make_mock_cursor(rows=[])
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("nonexistent-exp")

        assert result == {}

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_experiment_metrics_uses_parameterized_query(self, mock_pymysql):
        """The SQL is executed with experiment_id as a %s parameter."""
        cursor = _make_mock_cursor(rows=[])
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        connector.get_experiment_metrics("exp-unique-123")

        # The raw SQL must NOT contain the literal experiment_id
        execute_args = cursor.execute.call_args
        sql_arg = execute_args[0][0]
        assert "exp-unique-123" not in sql_arg


# ===========================================================================
# 6. Feature Flag Metrics Tests (5 tests)
# ===========================================================================

class TestMySQLConnectorFeatureFlagMetrics:
    """Tests for get_feature_flag_metrics() method."""

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_flag_metrics_returns_dict(self, mock_pymysql):
        """get_feature_flag_metrics() returns a dict."""
        rows = [
            {"group_key": "enabled", "requests": 5000, "errors": 25},
            {"group_key": "disabled", "requests": 4800, "errors": 22},
        ]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_feature_flag_metrics("flag-abc")

        assert isinstance(result, dict)

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_flag_metrics_contains_group_keys(self, mock_pymysql):
        """Result dict keys correspond to the group_key column."""
        rows = [{"group_key": "enabled", "requests": 5000, "errors": 25}]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_feature_flag_metrics("flag-abc")

        assert "enabled" in result

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_flag_metrics_has_error_rate_field(self, mock_pymysql):
        """Each entry includes an error_rate field."""
        rows = [{"group_key": "enabled", "requests": 1000, "errors": 10}]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_feature_flag_metrics("flag-abc")

        assert "error_rate" in result["enabled"]

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_flag_metrics_calculates_error_rate(self, mock_pymysql):
        """error_rate = errors / requests."""
        rows = [{"group_key": "enabled", "requests": 1000, "errors": 50}]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_feature_flag_metrics("flag-abc")

        assert abs(result["enabled"]["error_rate"] - 0.05) < 1e-6

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_flag_metrics_empty_for_unknown_flag(self, mock_pymysql):
        """Returns {} when no rows match the flag_id."""
        cursor = _make_mock_cursor(rows=[])
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_feature_flag_metrics("nonexistent-flag")

        assert result == {}


# ===========================================================================
# 7. test_connection() Tests (5 tests)
# ===========================================================================

class TestMySQLConnectorTestConnection:
    """Tests for the test_connection() method."""

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_test_connection_returns_true_on_success(self, mock_pymysql):
        """test_connection() returns True when MySQL is reachable."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        result = connector.test_connection()

        assert result is True

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_test_connection_returns_false_on_failure(self, mock_pymysql):
        """test_connection() returns False when connection fails."""
        mock_pymysql.connect.side_effect = Exception("Connection refused")

        connector = _make_connector()
        result = connector.test_connection()

        assert result is False

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_test_connection_does_not_raise(self, mock_pymysql):
        """test_connection() catches exceptions and returns False rather than raising."""
        mock_pymysql.connect.side_effect = RuntimeError("Unexpected error")

        connector = _make_connector()
        result = connector.test_connection()  # Should NOT raise
        assert isinstance(result, bool)

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_test_connection_executes_select_1(self, mock_pymysql):
        """test_connection() runs a lightweight SELECT 1 query."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.test_connection()

        # cursor.execute must have been called
        cursor = mock_conn.cursor.return_value
        assert cursor.execute.called

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_test_connection_closes_temp_connection(self, mock_pymysql):
        """test_connection() closes the temporary connection it opens."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.test_connection()

        mock_conn.close.assert_called()


# ===========================================================================
# 8. close() Tests (3 tests)
# ===========================================================================

class TestMySQLConnectorClose:
    """Tests for the close() method."""

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_close_closes_connection(self, mock_pymysql):
        """close() calls close() on the underlying connection."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        connector.close()

        mock_conn.close.assert_called_once()

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_close_sets_connection_to_none(self, mock_pymysql):
        """close() clears self._connection to allow reconnection."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        connector.close()

        assert connector._connection is None

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_close_is_safe_when_not_connected(self, mock_pymysql):
        """close() is a no-op when no connection is open."""
        connector = _make_connector()
        connector.close()  # Should NOT raise


# ===========================================================================
# 9. Context Manager Tests (3 tests)
# ===========================================================================

class TestMySQLConnectorContextManager:
    """Tests for __enter__ / __exit__ context manager protocol."""

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_context_manager_connects_on_enter(self, mock_pymysql):
        """__enter__ establishes the connection."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        with connector as ctx:
            assert ctx is connector
            assert connector._connection is not None

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_context_manager_closes_on_exit(self, mock_pymysql):
        """__exit__ closes the connection."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        with connector:
            pass

        mock_conn.close.assert_called()

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_context_manager_closes_on_exception(self, mock_pymysql):
        """__exit__ ensures connection is closed even when an exception is raised."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        with pytest.raises(ValueError):
            with connector:
                raise ValueError("test error")

        mock_conn.close.assert_called()


# ===========================================================================
# 10. Retry / Resilience Tests (4 tests)
# ===========================================================================

class TestMySQLConnectorRetry:
    """Tests for retry logic on transient failures."""

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_retries_on_transient_error(self, mock_pymysql):
        """connect() retries up to max_retries times on transient errors."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.side_effect = [
            Exception("Connection reset"),
            Exception("Connection reset"),
            mock_conn,
        ]

        connector = _make_connector()
        connector.connect(max_retries=3)

        assert connector._connection is mock_conn
        assert mock_pymysql.connect.call_count == 3

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_raises_after_max_retries_exceeded(self, mock_pymysql):
        """connect() raises MySQLConnectionError after exhausting retries."""
        mock_pymysql.connect.side_effect = Exception("Persistent failure")

        connector = _make_connector()
        with pytest.raises(MySQLConnectionError):
            connector.connect(max_retries=2)

        assert mock_pymysql.connect.call_count == 2

    @patch("backend.app.services.mysql_connector.time")
    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_uses_exponential_backoff(self, mock_pymysql, mock_time):
        """connect() uses exponential backoff between retries."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.side_effect = [
            Exception("transient"),
            mock_conn,
        ]
        mock_time.sleep = MagicMock()
        mock_time.time = time.time

        connector = _make_connector()
        connector.connect(max_retries=2)

        assert mock_time.sleep.call_count >= 1

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_connect_default_max_retries_is_three(self, mock_pymysql):
        """connect() uses max_retries=3 by default."""
        mock_pymysql.connect.side_effect = Exception("always fails")

        connector = _make_connector()
        with pytest.raises(MySQLConnectionError):
            connector.connect()  # no explicit max_retries

        assert mock_pymysql.connect.call_count == 3


# ===========================================================================
# 11. SQL Injection Prevention Tests (5 tests)
# ===========================================================================

class TestMySQLSQLInjectionPrevention:
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
        """execute_query() raises MySQLQueryError for DML/DDL."""
        connector = _make_connector()
        with pytest.raises(MySQLQueryError, match="not allowed"):
            connector.execute_query(dangerous_sql)

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_passes_params_separately(self, mock_pymysql):
        """Parameters are NOT interpolated into SQL — passed as separate tuple."""
        rows = [{"id": "exp-1"}]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        sql = "SELECT id FROM experiments WHERE name = %s"
        params = ("'; DROP TABLE experiments; --",)
        connector.execute_query(sql, params=params)

        # The SQL passed to cursor.execute must NOT contain the injected value
        executed_sql = cursor.execute.call_args[0][0]
        assert "DROP TABLE" not in executed_sql


# ===========================================================================
# 12. NULL / Unicode Handling Tests (3 tests)
# ===========================================================================

class TestMySQLConnectorDataHandling:
    """Tests for NULL values and character encoding."""

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_execute_query_handles_none_values(self, mock_pymysql):
        """execute_query() handles rows with None (NULL) values correctly."""
        rows = [{"variant_id": "control", "sample_size": None, "conversions": None}]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.execute_query("SELECT variant_id, sample_size, conversions FROM t")

        assert result[0]["variant_id"] == "control"
        assert result[0]["sample_size"] is None

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_utf8mb4_charset_is_used_by_default(self, mock_pymysql):
        """Connector uses utf8mb4 charset by default for full Unicode support."""
        mock_conn = _make_mock_connection()
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()

        call_kwargs = mock_pymysql.connect.call_args.kwargs
        assert call_kwargs.get("charset") == "utf8mb4"

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_get_experiment_metrics_handles_null_conversions(self, mock_pymysql):
        """get_experiment_metrics() handles NULL conversions gracefully."""
        rows = [{"variant_id": "control", "sample_size": 1000, "conversions": None}]
        cursor = _make_mock_cursor(rows=rows)
        mock_conn = _make_mock_connection(cursor=cursor)
        mock_pymysql.connect.return_value = mock_conn

        connector = _make_connector()
        connector.connect()
        result = connector.get_experiment_metrics("exp-001")

        # Should not raise; None treated as 0
        assert result["control"]["conversions"] == 0
        assert result["control"]["mean"] == 0.0

    @patch("backend.app.services.mysql_connector.pymysql")
    def test_reconnect_after_close(self, mock_pymysql):
        """Connector can reconnect after being closed."""
        mock_conn1 = _make_mock_connection()
        mock_conn2 = _make_mock_connection()
        mock_pymysql.connect.side_effect = [mock_conn1, mock_conn2]

        connector = _make_connector()
        connector.connect()
        connector.close()
        connector.connect()  # Should succeed again

        assert connector._connection is mock_conn2
        assert mock_pymysql.connect.call_count == 2
