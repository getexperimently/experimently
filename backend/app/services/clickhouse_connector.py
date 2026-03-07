"""
ClickHouse analytics warehouse connector (EP-048).

Provides a thread-safe, retry-enabled connector for executing read-only
SQL queries against a ClickHouse database.  Uses ``clickhouse-connect``
(HTTP-based, pure Python, version 0.7.x) so no native libraries are
required and mocking in unit tests is straightforward.

Credentials are never logged or stored beyond the lifetime of the object;
only passed at construction time and forwarded to the client.

Classes:
    ClickHouseConnector           — primary connector with context-manager support
    ClickHouseConnectionError     — raised when a connection cannot be established
    ClickHouseQueryError          — raised when a query is rejected or fails
    ClickHouseAuthError           — raised on authentication / authorisation failure
    ClickHouseTimeoutError        — raised when a query or connection times out
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import — mocked in unit tests
# ---------------------------------------------------------------------------

try:
    import clickhouse_connect  # type: ignore[import]
except ImportError:  # pragma: no cover — package present in production env
    clickhouse_connect = None  # type: ignore[assignment]

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


class ClickHouseConnectionError(Exception):
    """Raised when the connector cannot reach the ClickHouse server."""


class ClickHouseQueryError(Exception):
    """Raised when a query is rejected (unsafe SQL) or fails during execution."""


class ClickHouseAuthError(ClickHouseConnectionError):
    """Raised when authentication / authorisation with ClickHouse fails."""


class ClickHouseTimeoutError(ClickHouseConnectionError):
    """Raised when a query or connection attempt times out."""


# ---------------------------------------------------------------------------
# ClickHouseConnector
# ---------------------------------------------------------------------------


class ClickHouseConnector:
    """
    ClickHouse analytics warehouse connector.

    Wraps ``clickhouse-connect`` (HTTP protocol) to provide:
    - Parameterised (injection-safe) query execution
    - SQL validation that rejects DML / DDL
    - Retry with exponential backoff
    - Context-manager support for automatic cleanup

    Args:
        host:       ClickHouse server hostname (default: settings.CLICKHOUSE_HOST).
        port:       ClickHouse HTTP port (default: settings.CLICKHOUSE_PORT, 8123).
        database:   Database / schema name (default: settings.CLICKHOUSE_DATABASE).
        user:       Username (default: settings.CLICKHOUSE_USER).
        password:   Password (default: settings.CLICKHOUSE_PASSWORD).
        secure:     Use HTTPS (default: settings.CLICKHOUSE_SECURE).
        timeout:    Query timeout in seconds (default: settings.CLICKHOUSE_TIMEOUT_SECONDS).

    Example::

        with ClickHouseConnector(host="ch.example.com", user="default") as conn:
            rows = conn.execute_query("SELECT user_id FROM assignments LIMIT 10")
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        secure: Optional[bool] = None,
        timeout: Optional[int] = None,
    ) -> None:
        self.host = host if host is not None else settings.CLICKHOUSE_HOST
        self.port = port if port is not None else settings.CLICKHOUSE_PORT
        self.database = database if database is not None else settings.CLICKHOUSE_DATABASE
        self.user = user if user is not None else settings.CLICKHOUSE_USER
        self.password = password if password is not None else settings.CLICKHOUSE_PASSWORD
        self.secure = secure if secure is not None else settings.CLICKHOUSE_SECURE
        self.timeout = timeout if timeout is not None else settings.CLICKHOUSE_TIMEOUT_SECONDS

        # Live client — None until connect() is called.
        self._client: Optional[Any] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "ClickHouseConnector":
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
        Establish a connection to the ClickHouse server.

        Idempotent: if a live client already exists, this is a no-op.
        Retries up to *max_retries* times with exponential backoff.

        Args:
            max_retries: Maximum number of connection attempts (default 3).

        Returns:
            True on success.

        Raises:
            ClickHouseConnectionError: After all retry attempts are exhausted.
            ClickHouseAuthError:       If the error message indicates an auth failure.
            ClickHouseTimeoutError:    If the error message indicates a timeout.
        """
        if self._client is not None:
            return True  # Already connected

        last_error: Optional[Exception] = None
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(
                    "Connecting to ClickHouse (attempt %d/%d): host=%s port=%d",
                    attempt,
                    max_retries,
                    self.host,
                    self.port,
                )
                self._client = clickhouse_connect.get_client(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    username=self.user,
                    password=self.password,
                    secure=self.secure,
                    connect_timeout=self.timeout,
                    send_receive_timeout=self.timeout,
                )
                logger.info("Connected to ClickHouse: host=%s", self.host)
                return True
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "ClickHouse connection attempt %d failed: %s", attempt, exc
                )
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2  # exponential backoff

        # Classify the error type
        err_lower = str(last_error).lower() if last_error else ""

        if any(kw in err_lower for kw in ("timeout", "timed out")):
            raise ClickHouseTimeoutError(
                f"ClickHouse connection timed out after {max_retries} attempts: "
                f"{last_error}"
            ) from last_error

        if any(
            kw in err_lower
            for kw in ("401", "403", "forbidden", "auth", "unauthorized", "wrong password", "password")
        ):
            raise ClickHouseAuthError(
                f"ClickHouse authentication failed after {max_retries} attempts: "
                f"{last_error}"
            ) from last_error

        raise ClickHouseConnectionError(
            f"Could not connect to ClickHouse after {max_retries} attempts: "
            f"{last_error}"
        ) from last_error

    def close(self) -> None:
        """
        Close the underlying ClickHouse client.

        Safe to call even if not connected (no-op).
        After calling close(), ``_client`` is set to ``None`` so the
        connector can be reconnected if needed.
        """
        if self._client is not None:
            try:
                self._client.close()
            except Exception as exc:  # pragma: no cover
                logger.warning("Error closing ClickHouse connection: %s", exc)
            finally:
                self._client = None

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
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a read-only SQL query against ClickHouse and return rows as dicts.

        ClickHouse-connect uses named ``{param:Type}`` placeholders for
        parameterised queries, preventing SQL injection.

        Args:
            sql:    A SELECT-style SQL statement.  DML / DDL is rejected.
            params: Optional dict of named parameters matching ``{name:Type}``
                    placeholders in the SQL.

        Returns:
            List of dicts mapping column names to values.

        Raises:
            ClickHouseQueryError:      If the SQL is unsafe or execution fails.
            ClickHouseConnectionError: If the connector is not yet connected.
        """
        # Guard: reject mutating SQL before any network traffic.
        if not self._is_safe_sql(sql):
            raise ClickHouseQueryError(
                f"SQL statement not allowed (contains DML/DDL keywords): {sql!r}"
            )

        if self._client is None:
            raise ClickHouseConnectionError(
                "ClickHouseConnector is not connected. Call connect() first."
            )

        try:
            result = self._client.query(sql, parameters=params or {})
            columns = result.column_names
            rows = result.result_rows
            return [dict(zip(columns, row)) for row in rows]
        except ClickHouseQueryError:
            raise
        except Exception as exc:
            err_lower = str(exc).lower()
            if any(kw in err_lower for kw in ("timeout", "timed out")):
                raise ClickHouseTimeoutError(f"Query timed out: {exc}") from exc
            logger.exception("ClickHouse query failed: %s", exc)
            raise ClickHouseQueryError(f"Query execution failed: {exc}") from exc

    # ------------------------------------------------------------------
    # High-level analytics helpers
    # ------------------------------------------------------------------

    def get_experiment_metrics(self, experiment_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Fetch per-variant conversion metrics for a given experiment.

        Uses ClickHouse-native parameterised syntax ``{param:Type}`` to
        safely bind the experiment_id value.

        Args:
            experiment_id: The experiment identifier to filter on.

        Returns:
            Dict keyed by ``variant_name`` with fields:
            ``{"mean": float, "count": int, "conversions": int}``.
            Returns ``{}`` when no rows match.

        Raises:
            ClickHouseConnectionError: If the connector is not connected.
            ClickHouseQueryError:      On query execution failure.
        """
        sql = (
            "SELECT "
            "    variant_name, "
            "    count() AS count, "
            "    avg(metric_value) AS mean, "
            "    countIf(converted = 1) AS conversions "
            "FROM experiment_events "
            "WHERE experiment_id = {experiment_id:String} "
            "GROUP BY variant_name"
        )
        rows = self.execute_query(sql, params={"experiment_id": experiment_id})

        result: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            variant_name = row.get("variant_name")
            if not variant_name:
                continue
            count = int(row.get("count") or 0)
            conversions = int(row.get("conversions") or 0)
            mean = float(row.get("mean") or 0.0)
            result[variant_name] = {
                "mean": mean,
                "count": count,
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
            ClickHouseConnectionError: If the connector is not connected.
            ClickHouseQueryError:      On query execution failure.
        """
        sql = (
            "SELECT "
            "    group_key, "
            "    sum(request_count) AS requests, "
            "    sum(error_count) AS errors "
            "FROM feature_flag_events "
            "WHERE flag_id = {flag_id:String} "
            "GROUP BY group_key"
        )
        rows = self.execute_query(sql, params={"flag_id": flag_id})

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
        Test whether the ClickHouse server is reachable.

        Opens a temporary client, executes ``SELECT 1`` as a lightweight
        liveness check, then closes the client.

        Returns:
            ``True`` if the connection and query succeeded; ``False`` otherwise.
        """
        tmp_client = None
        try:
            tmp_client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.user,
                password=self.password,
                secure=self.secure,
                connect_timeout=self.timeout,
                send_receive_timeout=self.timeout,
            )
            tmp_client.query("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("ClickHouse connection test failed: %s", exc)
            return False
        finally:
            if tmp_client is not None:
                try:
                    tmp_client.close()
                except Exception:  # pragma: no cover
                    pass
