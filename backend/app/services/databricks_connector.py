"""
Databricks SQL connector for warehouse-native analytics (EP-041).

Provides a thread-safe, retry-enabled connector for executing read-only
SQL queries against a Databricks SQL warehouse.  Credentials are never
logged or stored; only passed at construction time and forwarded to the
Databricks driver.

Classes:
    DatabricksConnector           — primary connector with context-manager support
    DatabricksConnectionError     — raised when a connection cannot be established
    DatabricksQueryError          — raised when a query is rejected or fails
    DatabricksAuthError           — raised on authentication / authorisation failure
    DatabricksTimeoutError        — raised when a query or connection times out
"""

import logging
import re
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import — mocked in unit tests
# ---------------------------------------------------------------------------

try:
    from databricks import sql as databricks_sql  # type: ignore[import]
except ImportError:  # pragma: no cover — package present in production env
    databricks_sql = None  # type: ignore[assignment]

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


class DatabricksConnectionError(Exception):
    """Raised when the connector cannot reach the Databricks SQL warehouse."""


class DatabricksQueryError(Exception):
    """Raised when a query is rejected (unsafe SQL) or fails during execution."""


class DatabricksAuthError(DatabricksConnectionError):
    """Raised when authentication / authorisation with Databricks fails."""


class DatabricksTimeoutError(DatabricksConnectionError):
    """Raised when a query or connection attempt times out."""


# ---------------------------------------------------------------------------
# DatabricksConnector
# ---------------------------------------------------------------------------


class DatabricksConnector:
    """
    Databricks SQL connector for warehouse-native experiment analytics.

    Wraps ``databricks-sql-connector`` to provide:
    - Parameterised (injection-safe) query execution
    - SQL validation that rejects DML / DDL
    - Retry with exponential backoff
    - Context-manager support for automatic cleanup

    Args:
        host:            Databricks workspace hostname
                         (e.g. ``myworkspace.azuredatabricks.net``).
        http_path:       HTTP path for the SQL warehouse
                         (e.g. ``/sql/1.0/warehouses/abc123``).
        access_token:    Personal access token (PAT) or service-principal token.
        catalog:         Unity Catalog catalog name (default: ``main``).
        schema:          Schema inside the catalog (default: ``default``).
        timeout_seconds: Socket / query timeout in seconds (default: ``30``).

    Example::

        with DatabricksConnector(host=..., http_path=..., access_token=...) as conn:
            rows = conn.execute_query("SELECT user_id FROM assignments LIMIT 10")
    """

    def __init__(
        self,
        host: str,
        http_path: str,
        access_token: str,
        catalog: str = "main",
        schema: str = "default",
        timeout_seconds: int = 30,
    ) -> None:
        self.host = host
        self.http_path = http_path
        self.access_token = access_token
        self.catalog = catalog
        self.schema = schema
        self.timeout_seconds = timeout_seconds

        # Live connection — None until connect() is called.
        self._connection: Optional[Any] = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "DatabricksConnector":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
        return None  # Do not suppress exceptions

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self, max_retries: int = DEFAULT_MAX_RETRIES) -> None:
        """
        Establish a connection to the Databricks SQL warehouse.

        Idempotent: if a live connection already exists, this is a no-op.
        Retries up to *max_retries* times with exponential backoff.

        Args:
            max_retries: Maximum number of connection attempts (default 3).

        Raises:
            DatabricksConnectionError: After all retry attempts are exhausted.
            DatabricksAuthError:       If the error message indicates an auth failure.
        """
        if self._connection is not None:
            return  # Already connected

        last_error: Optional[Exception] = None
        backoff = INITIAL_BACKOFF_SECONDS

        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(
                    "Connecting to Databricks (attempt %d/%d): host=%s",
                    attempt,
                    max_retries,
                    self.host,
                )
                self._connection = databricks_sql.connect(
                    server_hostname=self.host,
                    http_path=self.http_path,
                    access_token=self.access_token,
                    _socket_timeout=self.timeout_seconds,
                )
                logger.info("Connected to Databricks: host=%s", self.host)
                return
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Databricks connection attempt %d failed: %s", attempt, exc
                )
                if attempt < max_retries:
                    time.sleep(backoff)
                    backoff *= 2  # exponential backoff

        # Determine whether this looks like an auth failure
        if last_error and any(
            kw in str(last_error).lower()
            for kw in ("403", "forbidden", "token", "auth", "unauthorized")
        ):
            raise DatabricksAuthError(
                f"Databricks authentication failed after {max_retries} attempts: "
                f"{last_error}"
            ) from last_error

        raise DatabricksConnectionError(
            f"Could not connect to Databricks after {max_retries} attempts: "
            f"{last_error}"
        ) from last_error

    def close(self) -> None:
        """
        Close the underlying Databricks connection.

        Safe to call even if the connector is not connected (no-op).
        After calling close(), ``_connection`` is set to ``None`` so the
        connector can be reconnected if needed.
        """
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception as exc:  # pragma: no cover
                logger.warning("Error closing Databricks connection: %s", exc)
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
        params: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a read-only SQL query against Databricks and return rows as dicts.

        Args:
            sql:    A SELECT-style SQL statement.  DML / DDL is rejected.
            params: Optional list of positional parameters (``?`` placeholders)
                    to be passed to the cursor, preventing string interpolation
                    (SQL injection prevention).

        Returns:
            List of dicts mapping column names to values.

        Raises:
            DatabricksQueryError:    If the SQL is unsafe or execution fails.
            DatabricksConnectionError: If the connector is not yet connected.
        """
        # Guard: reject mutating SQL before any network traffic.
        if not self._is_safe_sql(sql):
            raise DatabricksQueryError(
                f"SQL statement not allowed (contains DML/DDL keywords): {sql!r}"
            )

        if self._connection is None:
            raise DatabricksConnectionError(
                "DatabricksConnector is not connected. Call connect() first."
            )

        try:
            cursor = self._connection.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            columns = [desc[0] for desc in (cursor.description or [])]
            rows = cursor.fetchall()
            return [dict(zip(columns, row)) for row in rows]
        except DatabricksQueryError:
            raise
        except Exception as exc:
            logger.exception("Databricks query failed: %s", exc)
            raise DatabricksQueryError(f"Query execution failed: {exc}") from exc

    # ------------------------------------------------------------------
    # High-level analytics helpers
    # ------------------------------------------------------------------

    def get_experiment_metrics(self, experiment_id: str) -> Dict[str, Dict[str, Any]]:
        """
        Fetch per-variant conversion metrics for a given experiment.

        Executes a parameterised query against the configured catalog/schema to
        retrieve variant-level ``sample_size`` and ``conversions`` counts, then
        computes ``mean = conversions / sample_size`` for each variant.

        Args:
            experiment_id: The experiment identifier to filter on.

        Returns:
            Dict keyed by ``variant_id`` with fields:
            ``{"mean": float, "count": int, "conversions": int}``.
            Returns ``{}`` when no rows match.

        Raises:
            DatabricksConnectionError: If the connector is not connected.
            DatabricksQueryError:      On query execution failure.
        """
        sql = (
            "SELECT variant_id, "
            "COUNT(DISTINCT user_id) AS sample_size, "
            "SUM(CASE WHEN converted THEN 1 ELSE 0 END) AS conversions "
            f"FROM {self.catalog}.{self.schema}.experiment_assignments "
            "WHERE experiment_id = ?"
        )
        rows = self.execute_query(sql, params=[experiment_id])

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
            DatabricksConnectionError: If the connector is not connected.
            DatabricksQueryError:      On query execution failure.
        """
        sql = (
            "SELECT group_key, "
            "SUM(request_count) AS requests, "
            "SUM(error_count) AS errors "
            f"FROM {self.catalog}.{self.schema}.feature_flag_events "
            "WHERE flag_id = ? "
            "GROUP BY group_key"
        )
        rows = self.execute_query(sql, params=[flag_id])

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
        Test whether the Databricks SQL warehouse is reachable.

        Opens a temporary connection, executes ``SELECT 1`` as a lightweight
        liveness check, then closes the connection.

        Returns:
            ``True`` if the connection and query succeeded; ``False`` otherwise.
        """
        try:
            conn = databricks_sql.connect(
                server_hostname=self.host,
                http_path=self.http_path,
                access_token=self.access_token,
                _socket_timeout=self.timeout_seconds,
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()
            conn.close()
            return True
        except Exception as exc:
            logger.warning("Databricks connection test failed: %s", exc)
            return False
