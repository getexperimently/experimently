"""
MySQL / MariaDB analytics warehouse connector (EP-048).

Provides a thread-safe, retry-enabled connector for executing read-only
SQL queries against a MySQL or MariaDB database.  Uses ``PyMySQL``
(pure Python, no native client library required) with ``DictCursor`` so
all rows are returned as dicts rather than tuples.

Parameterised queries use ``%s`` placeholders (PyMySQL standard), which
prevents SQL injection at the driver level.

Credentials are never logged or stored beyond the lifetime of the object.

Classes:
    MySQLConnector           — primary connector with context-manager support
    MySQLConnectionError     — raised when a connection cannot be established
    MySQLQueryError          — raised when a query is rejected or fails
    MySQLAuthError           — raised on authentication / authorisation failure
    MySQLTimeoutError        — raised when a query or connection times out
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import — mocked in unit tests
# ---------------------------------------------------------------------------

try:
    import pymysql  # type: ignore[import]
    from pymysql.cursors import DictCursor  # type: ignore[import]
except ImportError:  # pragma: no cover — package present in production env
    pymysql = None  # type: ignore[assignment]
    DictCursor = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: SQL keywords that indicate a mutating / destructive statement.
DANGEROUS_KEYWORDS = {
    "drop",
    "delete",
    "insert",
    "update",
    "truncate",
    "alter",
    "create",
    "grant",
    "revoke",
    "merge",
}

#: Default number of connection retry attempts.
DEFAULT_MAX_RETRIES = 3

#: Initial backoff interval in seconds (doubles each retry).
INITIAL_BACKOFF_SECONDS = 1.0


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class MySQLConnectionError(Exception):
    """Raised when the connector cannot reach the MySQL server."""


class MySQLQueryError(Exception):
    """Raised when a query is rejected (unsafe SQL) or fails during execution."""


class MySQLAuthError(MySQLConnectionError):
    """Raised when authentication / authorisation with MySQL fails."""


class MySQLTimeoutError(MySQLConnectionError):
    """Raised when a query or connection attempt times out."""


# ---------------------------------------------------------------------------
# MySQLConnector
# ---------------------------------------------------------------------------


class MySQLConnector:
    """
    MySQL / MariaDB analytics warehouse connector.

    Wraps ``PyMySQL`` to provide:
    - Parameterised (injection-safe) query execution via ``%s`` placeholders
    - SQL validation that rejects DML / DDL
    - Retry with exponential backoff
    - DictCursor so rows are always returned as dicts
    - Context-manager support for automatic cleanup

    Args:
        host:     MySQL server hostname (default: settings.MYSQL_HOST).
        port:     MySQL server port (default: settings.MYSQL_PORT, 3306).
        database: Database name (default: settings.MYSQL_DATABASE).
        user:     MySQL username (default: settings.MYSQL_USER).
        password: MySQL password (default: settings.MYSQL_PASSWORD).
        charset:  Connection charset (default: ``utf8mb4``).
        timeout:  Connect / read timeout in seconds
                  (default: settings.MYSQL_TIMEOUT_SECONDS).

    Example::

        with MySQLConnector(host="db.example.com", database="analytics") as conn:
            rows = conn.execute_query(
                "SELECT user_id FROM assignments WHERE experiment_id = %s",
                ("exp-001",),
            )
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        charset: str = "utf8mb4",
        timeout: Optional[int] = None,
    ) -> None:
        self.host = host if host is not None else settings.MYSQL_HOST
        self.port = port if port is not None else settings.MYSQL_PORT
        self.database = database if database is not None else settings.MYSQL_DATABASE
        self.user = user if user is not None else settings.MYSQL_USER
        self.password = password if password is not None else settings.MYSQL_PASSWORD
        self.charset = charset
        self.timeout = timeout if timeout is not None else settings.MYSQL_TIMEOUT_SECONDS

        # Live connection — None until connect() is called.
        self._connection: Optional[Any] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "MySQLConnector":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
        return None  # Do not suppress exceptions

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, max_retries: int = DEFAULT_MAX_RETRIES) -> bool:
        """
        Establish a connection to the MySQL server.

        Idempotent: if a live connection already exists, this is a no-op.
        Retries up to *max_retries* times with exponential backoff.

        Args:
            max_retries: Maximum number of connection attempts (default 3).

        Returns:
            True on success.

        Raises:
            MySQLConnectionError: After all retry attempts are exhausted.
            MySQLAuthError:       If the error message indicates an auth failure.
            MySQLTimeoutError:    If the error message indicates a timeout.
        """
        if self._connection is not None:
            return True  # Already connected

        last_error: Optional[Exception] = None
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(
                    "Connecting to MySQL (attempt %d/%d): host=%s port=%d",
                    attempt,
                    max_retries,
                    self.host,
                    self.port,
                )
                self._connection = pymysql.connect(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    user=self.user,
                    password=self.password,
                    charset=self.charset,
                    connect_timeout=self.timeout,
                    read_timeout=self.timeout,
                    cursorclass=DictCursor,
                )
                logger.info("Connected to MySQL: host=%s", self.host)
                return True
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "MySQL connection attempt %d failed: %s", attempt, exc
                )
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2  # exponential backoff

        # Classify the error type
        err_lower = str(last_error).lower() if last_error else ""

        if any(kw in err_lower for kw in ("timeout", "timed out", "connection timed out")):
            raise MySQLTimeoutError(
                f"MySQL connection timed out after {max_retries} attempts: "
                f"{last_error}"
            ) from last_error

        if any(
            kw in err_lower
            for kw in (
                "access denied", "authentication", "password", "1045",
                "auth", "forbidden", "unauthorized",
            )
        ):
            raise MySQLAuthError(
                f"MySQL authentication failed after {max_retries} attempts: "
                f"{last_error}"
            ) from last_error

        raise MySQLConnectionError(
            f"Could not connect to MySQL after {max_retries} attempts: "
            f"{last_error}"
        ) from last_error

    def close(self) -> None:
        """
        Close the underlying MySQL connection.

        Safe to call even if the connector is not connected (no-op).
        After calling close(), ``_connection`` is set to ``None`` so the
        connector can be reconnected if needed.
        """
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception as exc:  # pragma: no cover
                logger.warning("Error closing MySQL connection: %s", exc)
            finally:
                self._connection = None

    # ------------------------------------------------------------------
    # SQL validation
    # ------------------------------------------------------------------

    @staticmethod
    def _is_safe_sql(sql: str) -> bool:
        """
        Return *True* only for read-only SQL statements.

        Rejects empty strings and any SQL that contains DML / DDL keywords
        when tokenised.  Token matching is case-insensitive and operates on
        whitespace-split tokens to avoid false positives inside string literals
        for common cases.
        """
        if not sql or not sql.strip():
            return False
        tokens = set(re.split(r"\s+", sql.strip().lower()))
        return not bool(tokens & DANGEROUS_KEYWORDS)

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    def execute_query(
        self,
        sql: str,
        params: Optional[Tuple[Any, ...]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a read-only SQL query against MySQL and return rows as dicts.

        PyMySQL uses ``%s`` as the placeholder character for parameterised
        queries.  Parameters are **never** interpolated into the SQL string
        by user code — the driver handles binding, preventing SQL injection.

        Args:
            sql:    A SELECT-style SQL statement with optional ``%s``
                    placeholders.  DML / DDL is rejected.
            params: Optional tuple of positional values corresponding to the
                    ``%s`` placeholders in *sql*.

        Returns:
            List of dicts mapping column names to values
            (DictCursor is always used).

        Raises:
            MySQLQueryError:      If the SQL is unsafe or execution fails.
            MySQLConnectionError: If the connector is not yet connected.
        """
        # Guard: reject mutating SQL before any network traffic.
        if not self._is_safe_sql(sql):
            raise MySQLQueryError(
                f"SQL statement not allowed (contains DML/DDL keywords): {sql!r}"
            )

        if self._connection is None:
            raise MySQLConnectionError(
                "MySQLConnector is not connected. Call connect() first."
            )

        cursor = None
        try:
            cursor = self._connection.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            rows = cursor.fetchall()
            # DictCursor already returns dicts; ensure we always return list
            return list(rows) if rows else []
        except MySQLQueryError:
            raise
        except Exception as exc:
            logger.exception("MySQL query failed: %s", exc)
            raise MySQLQueryError(f"Query execution failed: {exc}") from exc
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:  # pragma: no cover
                    pass

    # ------------------------------------------------------------------
    # High-level analytics helpers
    # ------------------------------------------------------------------

    def get_experiment_metrics(self, experiment_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Fetch per-variant conversion metrics for a given experiment.

        Uses ``%s`` parameterised query to safely bind experiment_id.

        Args:
            experiment_id: The experiment identifier to filter on.

        Returns:
            Dict keyed by ``variant_id`` with fields:
            ``{"mean": float, "count": int, "conversions": int}``.
            Returns ``{}`` when no rows match.

        Raises:
            MySQLConnectionError: If the connector is not connected.
            MySQLQueryError:      On query execution failure.
        """
        sql = (
            "SELECT variant_id, "
            "COUNT(DISTINCT user_id) AS sample_size, "
            "SUM(CASE WHEN converted = 1 THEN 1 ELSE 0 END) AS conversions "
            "FROM experiment_assignments "
            "WHERE experiment_id = %s "
            "GROUP BY variant_id"
        )
        rows = self.execute_query(sql, params=(experiment_id,))

        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            variant_id = row.get("variant_id")
            if not variant_id:
                continue
            sample_size = int(row.get("sample_size") or 0)
            conversions = int(row.get("conversions") or 0)
            mean = conversions / max(sample_size, 1)
            result[variant_id] = {
                "mean": mean,
                "count": sample_size,
                "conversions": conversions,
            }
        return result

    def get_feature_flag_metrics(self, flag_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Fetch per-group error-rate metrics for a feature flag.

        Args:
            flag_id: The feature flag identifier to filter on.

        Returns:
            Dict keyed by ``group_key`` with fields:
            ``{"error_rate": float, "requests": int, "errors": int}``.
            Returns ``{}`` when no rows match.

        Raises:
            MySQLConnectionError: If the connector is not connected.
            MySQLQueryError:      On query execution failure.
        """
        sql = (
            "SELECT group_key, "
            "SUM(request_count) AS requests, "
            "SUM(error_count) AS errors "
            "FROM feature_flag_events "
            "WHERE flag_id = %s "
            "GROUP BY group_key"
        )
        rows = self.execute_query(sql, params=(flag_id,))

        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            group_key = row.get("group_key")
            if not group_key:
                continue
            requests = int(row.get("requests") or 0)
            errors = int(row.get("errors") or 0)
            error_rate = errors / max(requests, 1)
            result[group_key] = {
                "error_rate": error_rate,
                "requests": requests,
                "errors": errors,
            }
        return result

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        """
        Test whether the MySQL server is reachable.

        Opens a temporary connection, executes ``SELECT 1`` as a lightweight
        liveness check, then closes the connection.

        Returns:
            ``True`` if the connection and query succeeded; ``False`` otherwise.
        """
        tmp_conn = None
        try:
            tmp_conn = pymysql.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                charset=self.charset,
                connect_timeout=self.timeout,
                cursorclass=DictCursor,
            )
            with tmp_conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchall()
            return True
        except Exception as exc:
            logger.warning("MySQL connection test failed: %s", exc)
            return False
        finally:
            if tmp_conn is not None:
                try:
                    tmp_conn.close()
                except Exception:  # pragma: no cover
                    pass
