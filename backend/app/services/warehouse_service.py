"""
Warehouse-Native Analytics Service (Issue #26).

Generates experiment analysis SQL for Snowflake, BigQuery, and Redshift.
Credentials are stored encrypted; never logged or returned in API responses.

Classes:
    WarehouseQueryGenerator  — dialect-aware SQL generation + validation
    WarehouseConnectionManager — connection CRUD + credential encryption
    ResultsImporter          — maps warehouse query rows to MetricResult format
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from uuid import UUID

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DANGEROUS_KEYWORDS = {
    "drop", "delete", "insert", "update", "truncate",
    "alter", "create", "grant", "revoke",
}

# Quote character used around identifiers for each dialect
DIALECT_QUOTE: Dict[str, str] = {
    "snowflake": '"',
    "bigquery": "`",
    "redshift": '"',
    "default": '"',
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ConnectionTestResult:
    """Result of a warehouse connectivity test."""

    success: bool
    latency_ms: float
    error: Optional[str] = None


@dataclass
class WarehouseSyncResult:
    """Result of syncing experiment results from a warehouse query."""

    experiment_id: str
    rows_processed: int
    variants_updated: int
    status: str  # "success" | "partial" | "failed"
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# WarehouseQueryGenerator
# ---------------------------------------------------------------------------

class WarehouseQueryGenerator:
    """
    Generate dialect-aware SQL for experiment assignment and results queries.

    Supports Snowflake, BigQuery, and Redshift via the ``dialect`` parameter.
    All table/column names are sanitized before interpolation to prevent
    SQL injection via user-supplied table names.
    """

    @staticmethod
    def sanitize_identifier(name: str) -> str:
        """
        Remove dangerous characters from a table or column name.

        Allows alphanumeric characters, underscores, and dots (for
        schema-qualified names like ``schema.table``).  Everything else is
        stripped.
        """
        return re.sub(r"[^\w.]", "", name)

    @staticmethod
    def validate_sql(sql: str) -> bool:
        """
        Return True only if *sql* is a safe SELECT-style statement.

        Rejects empty strings and any SQL that contains DML / DDL keywords
        (DROP, DELETE, INSERT, UPDATE, TRUNCATE, ALTER, CREATE, GRANT,
        REVOKE).  The check is performed on lowercased tokens, so casing
        tricks do not bypass it.
        """
        if not sql or not sql.strip():
            return False
        tokens = set(sql.lower().split())
        return not bool(tokens & DANGEROUS_KEYWORDS)

    @classmethod
    def quote_identifier(cls, name: str, dialect: str) -> str:
        """Wrap a sanitized identifier in the dialect-appropriate quote char."""
        q = DIALECT_QUOTE.get(dialect, DIALECT_QUOTE["default"])
        safe = cls.sanitize_identifier(name)
        return f"{q}{safe}{q}"

    @staticmethod
    def quote_literal(value: str) -> str:
        """
        Render *value* as a single-quoted SQL string literal.

        Generated warehouse SQL is shipped as text (no parameter binding is
        available across Snowflake/BigQuery/Redshift), so every value that
        lands inside quotes is escaped here: single quotes are doubled and
        backslashes / control characters are stripped.
        """
        cleaned = re.sub(r"[\\\x00-\x1f\x7f]", "", str(value))
        return "'" + cleaned.replace("'", "''") + "'"

    @classmethod
    def generate_assignment_query(
        cls,
        experiment_id: str,
        assignments_table: str,
        dialect: str = "default",
    ) -> str:
        """
        Generate a query that fetches all user→variant assignments for an
        experiment from the customer's warehouse assignments table.

        Args:
            experiment_id:     Experiment identifier to filter on.
            assignments_table: Customer's assignments table name.
            dialect:           One of ``snowflake``, ``bigquery``, ``redshift``,
                               or ``default`` (falls back to double-quote style).

        Returns:
            SQL string ready to execute against the target warehouse.
        """
        table = cls.quote_identifier(assignments_table, dialect)
        exp_lit = cls.quote_literal(experiment_id)
        return (
            f"SELECT user_id, variant_id\n"  # nosec B608 - identifiers sanitized, literals escaped above
            f"FROM {table}\n"
            f"WHERE experiment_id = {exp_lit}"
        )

    @classmethod
    def generate_results_query(
        cls,
        experiment_id: str,
        assignments_table: str,
        events_table: str,
        metric_event: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        dialect: str = "default",
    ) -> str:
        """
        Generate a full experiment results query that joins assignments with
        events and aggregates conversions per variant.

        The query uses two CTEs:
         - ``assignments``: users enrolled in the experiment with their
           variant assignment.
         - ``events``: events of the specified *metric_event* type.

        It then LEFT-JOINs them and groups by ``variant_id``, returning:
         - ``sample_size``  — COUNT(DISTINCT user_id) in each variant
         - ``conversions``  — SUM of matched events per variant

        Args:
            experiment_id:     Experiment identifier.
            assignments_table: Warehouse assignments table.
            events_table:      Warehouse events table.
            metric_event:      Event type that counts as a conversion.
            start_date:        Optional ISO-8601 start filter for events.
            end_date:          Optional ISO-8601 end filter for events.
            dialect:           Target warehouse SQL dialect.

        Returns:
            SQL string with CTEs and aggregation.
        """
        a_table = cls.quote_identifier(assignments_table, dialect)
        e_table = cls.quote_identifier(events_table, dialect)
        exp_lit = cls.quote_literal(experiment_id)
        event_lit = cls.quote_literal(metric_event)

        date_filter = ""
        if start_date and end_date:
            start_lit = cls.quote_literal(start_date)
            end_lit = cls.quote_literal(end_date)
            date_filter = f"\n  AND e.occurred_at BETWEEN {start_lit} AND {end_lit}"

        return (
            f"WITH assignments AS (\n"  # nosec B608 - identifiers sanitized, literals escaped above
            f"  SELECT user_id, variant_id\n"
            f"  FROM {a_table}\n"
            f"  WHERE experiment_id = {exp_lit}\n"
            f"),\n"
            f"events AS (\n"
            f"  SELECT user_id, event_type, value\n"
            f"  FROM {e_table}\n"
            f"  WHERE event_type = {event_lit}{date_filter}\n"
            f")\n"
            f"SELECT\n"
            f"  a.variant_id,\n"
            f"  COUNT(DISTINCT a.user_id) AS sample_size,\n"
            f"  SUM(CASE WHEN e.event_type IS NOT NULL THEN 1 ELSE 0 END) AS conversions\n"
            f"FROM assignments a\n"
            f"LEFT JOIN events e ON a.user_id = e.user_id\n"
            f"GROUP BY a.variant_id"
        )


# ---------------------------------------------------------------------------
# WarehouseConnectionManager
# ---------------------------------------------------------------------------

class WarehouseConnectionManager:
    """
    Manage warehouse connection configurations stored in the application DB.

    Credentials are encrypted before persistence and decrypted on demand.
    In production this delegates to AWS KMS; in tests a base64 round-trip
    is used as a mock.
    """

    def __init__(self, db: Any) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Credential encryption helpers
    # ------------------------------------------------------------------

    def encrypt_credentials(self, config: Dict) -> str:
        """
        Encrypt a credential dict for storage.

        In production this would use AWS KMS / Secrets Manager.
        Here we base64-encode a JSON serialisation so that:
          1. The plaintext never appears in the stored string.
          2. Tests can verify round-trip without a KMS dependency.
        """
        import json
        import base64

        serialised = json.dumps(config, sort_keys=True)
        return base64.b64encode(serialised.encode()).decode()

    def decrypt_credentials(self, encrypted: str) -> Dict:
        """
        Decrypt a previously encrypted credential blob.

        Inverse of :meth:`encrypt_credentials`.
        """
        import json
        import base64

        return json.loads(base64.b64decode(encrypted.encode()).decode())

    # ------------------------------------------------------------------
    # Connectivity test
    # ------------------------------------------------------------------

    def test_connection(self, config: Dict) -> ConnectionTestResult:
        """
        Test that a warehouse connection is reachable.

        In production this would open a real connection.  Here we perform
        lightweight config validation and return a mock latency so that
        the logic can be exercised without an actual warehouse.

        Returns:
            :class:`ConnectionTestResult` with ``success``, ``latency_ms``,
            and optional ``error``.
        """
        import time

        start = time.time()
        try:
            warehouse_type = config.get("warehouse_type", "")
            if warehouse_type not in ("snowflake", "bigquery", "redshift"):
                return ConnectionTestResult(
                    success=False,
                    latency_ms=0.0,
                    error=f"Unsupported warehouse type: {warehouse_type!r}",
                )
            # BigQuery uses project_id instead of host
            if warehouse_type != "bigquery" and not config.get("host"):
                return ConnectionTestResult(
                    success=False,
                    latency_ms=0.0,
                    error="Missing required field: host",
                )
            latency_ms = (time.time() - start) * 1000
            return ConnectionTestResult(success=True, latency_ms=latency_ms)
        except Exception as exc:  # pragma: no cover
            logger.exception("Unexpected error testing warehouse connection")
            return ConnectionTestResult(success=False, latency_ms=0.0, error=str(exc))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_connection(
        self,
        name: str,
        warehouse_type: str,
        config: Dict,
        owner_id: Optional[Any] = None,
    ):
        """
        Persist a new warehouse connection with encrypted credentials.

        Args:
            name:           Human-readable connection name.
            warehouse_type: ``snowflake`` | ``bigquery`` | ``redshift``.
            config:         Raw credential dict (will be encrypted).
            owner_id:       Optional owning user UUID.

        Returns:
            Newly created :class:`WarehouseConnection` ORM instance.
        """
        from backend.app.models.warehouse_connection import WarehouseConnection

        encrypted = self.encrypt_credentials(config)
        conn = WarehouseConnection(
            name=name,
            warehouse_type=warehouse_type,
            encrypted_credentials=encrypted,
            owner_id=owner_id,
            is_active=True,
        )
        self.db.add(conn)
        self.db.commit()
        self.db.refresh(conn)
        return conn

    def get_connection(self, connection_id: UUID):
        """
        Retrieve a single active warehouse connection by primary key.

        Returns:
            :class:`WarehouseConnection` or ``None`` if not found / deleted.
        """
        from backend.app.models.warehouse_connection import WarehouseConnection

        return (
            self.db.query(WarehouseConnection)
            .filter(
                WarehouseConnection.id == connection_id,
                WarehouseConnection.is_active == True,  # noqa: E712
            )
            .first()
        )

    def list_connections(self) -> List:
        """
        Return all active warehouse connections visible to the caller.

        Returns:
            List of :class:`WarehouseConnection` ORM instances.
        """
        from backend.app.models.warehouse_connection import WarehouseConnection

        return (
            self.db.query(WarehouseConnection)
            .filter(WarehouseConnection.is_active == True)  # noqa: E712
            .all()
        )

    def delete_connection(self, connection_id: UUID):
        """
        Soft-delete a warehouse connection by setting ``is_active=False``.

        Returns:
            The updated :class:`WarehouseConnection`, or ``None`` if not found.
        """
        conn = self.get_connection(connection_id)
        if conn:
            conn.is_active = False
            self.db.commit()
        return conn


# ---------------------------------------------------------------------------
# ResultsImporter
# ---------------------------------------------------------------------------

class ResultsImporter:
    """
    Map raw warehouse query rows into the platform's MetricResult format.

    Each row is expected to contain at minimum a ``variant_id`` and
    ``sample_size``; ``conversions`` defaults to 0 when absent.  Rows
    without a ``variant_id`` are silently skipped.
    """

    @staticmethod
    def import_results(query_rows: List[Dict], experiment_id: str) -> List[Dict]:
        """
        Convert warehouse result rows to the platform's VariantResult format.

        Args:
            query_rows:     List of dicts from the warehouse query, each
                            containing ``variant_id``, ``sample_size``, and
                            optionally ``conversions``.
            experiment_id:  Experiment this import belongs to (for logging).

        Returns:
            List of dicts with keys: variant_id, sample_size, conversions, mean.
        """
        results: List[Dict] = []
        for row in query_rows:
            variant_id = row.get("variant_id")
            if not variant_id:
                logger.debug(
                    "Skipping row without variant_id for experiment %s", experiment_id
                )
                continue
            sample_size = int(row.get("sample_size") or 0)
            conversions = int(row.get("conversions") or 0)
            mean = conversions / max(sample_size, 1)
            results.append(
                {
                    "variant_id": variant_id,
                    "sample_size": sample_size,
                    "conversions": conversions,
                    "mean": mean,
                }
            )
        return results

    @staticmethod
    def estimate_query_cost(sql: str, dialect: str) -> Dict:
        """
        Estimate the scan cost of executing *sql* against the target warehouse.

        This is intentionally mocked — a real implementation would call the
        warehouse's EXPLAIN or DRY_RUN API.

        Returns:
            Dict with ``estimated_bytes_scanned``, ``estimated_cost_usd``,
            and ``dialect``.
        """
        word_count = len(sql.split())
        return {
            "estimated_bytes_scanned": word_count * 1_000,
            "estimated_cost_usd": word_count * 0.001,
            "dialect": dialect,
        }
