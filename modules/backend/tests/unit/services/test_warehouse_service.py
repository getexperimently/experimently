"""
Unit tests for Warehouse-Native Analytics Service (Issue #26).

Covers:
 - WarehouseQueryGenerator: SQL generation for Snowflake, BigQuery, Redshift
 - WarehouseConnectionManager: connection lifecycle and credential handling
 - ResultsImporter: mapping warehouse rows to MetricResult format

No real database or warehouse connection required — uses MagicMock throughout.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from modules.backend.app.services.warehouse_service import (
    ConnectionTestResult,
    ResultsImporter,
    WarehouseConnectionManager,
    WarehouseQueryGenerator,
    WarehouseSyncResult,
)

# ---------------------------------------------------------------------------
# TestWarehouseQueryGenerator (15 tests)
# ---------------------------------------------------------------------------


class TestWarehouseQueryGenerator:
    """Tests for SQL generation across supported dialects."""

    # ------------------------------------------------------------------ #
    # 1. generate_assignment_query returns a non-empty SQL string
    # ------------------------------------------------------------------ #
    def test_generate_assignment_query_returns_string(self):
        sql = WarehouseQueryGenerator.generate_assignment_query(
            experiment_id="exp-123",
            assignments_table="assignments",
            dialect="default",
        )
        assert isinstance(sql, str)
        assert len(sql) > 0

    # ------------------------------------------------------------------ #
    # 2. SQL contains WHERE experiment_id clause
    # ------------------------------------------------------------------ #
    def test_generate_assignment_query_contains_experiment_id_filter(self):
        sql = WarehouseQueryGenerator.generate_assignment_query(
            experiment_id="exp-abc",
            assignments_table="assignments",
            dialect="default",
        )
        assert "experiment_id" in sql
        assert "exp-abc" in sql

    # ------------------------------------------------------------------ #
    # 3. SQL selects user_id and variant_id
    # ------------------------------------------------------------------ #
    def test_generate_assignment_query_selects_user_and_variant(self):
        sql = WarehouseQueryGenerator.generate_assignment_query(
            experiment_id="exp-123",
            assignments_table="assignments",
            dialect="default",
        )
        assert "user_id" in sql
        assert "variant_id" in sql

    # ------------------------------------------------------------------ #
    # 4. generate_results_query returns a non-empty SQL string
    # ------------------------------------------------------------------ #
    def test_generate_results_query_returns_string(self):
        sql = WarehouseQueryGenerator.generate_results_query(
            experiment_id="exp-123",
            assignments_table="assignments",
            events_table="events",
            metric_event="purchase",
            dialect="default",
        )
        assert isinstance(sql, str)
        assert len(sql) > 0

    # ------------------------------------------------------------------ #
    # 5. Results SQL contains GROUP BY variant_id
    # ------------------------------------------------------------------ #
    def test_generate_results_query_contains_group_by_variant(self):
        sql = WarehouseQueryGenerator.generate_results_query(
            experiment_id="exp-123",
            assignments_table="assignments",
            events_table="events",
            metric_event="purchase",
            dialect="default",
        )
        assert "GROUP BY" in sql.upper()
        assert "variant_id" in sql

    # ------------------------------------------------------------------ #
    # 6. Results SQL contains COUNT(DISTINCT user_id) for sample_size
    # ------------------------------------------------------------------ #
    def test_generate_results_query_contains_count_distinct_for_sample_size(self):
        sql = WarehouseQueryGenerator.generate_results_query(
            experiment_id="exp-123",
            assignments_table="assignments",
            events_table="events",
            metric_event="purchase",
            dialect="default",
        )
        sql_upper = sql.upper()
        assert "COUNT(DISTINCT" in sql_upper
        assert "sample_size" in sql.lower()

    # ------------------------------------------------------------------ #
    # 7. Results SQL contains SUM for conversions
    # ------------------------------------------------------------------ #
    def test_generate_results_query_contains_sum_for_conversions(self):
        sql = WarehouseQueryGenerator.generate_results_query(
            experiment_id="exp-123",
            assignments_table="assignments",
            events_table="events",
            metric_event="purchase",
            dialect="default",
        )
        assert "SUM" in sql.upper()
        assert "conversions" in sql.lower()

    # ------------------------------------------------------------------ #
    # 8. Snowflake dialect uses double-quote identifiers
    # ------------------------------------------------------------------ #
    def test_snowflake_dialect_uses_double_quote_identifiers(self):
        sql = WarehouseQueryGenerator.generate_assignment_query(
            experiment_id="exp-sf",
            assignments_table="my_assignments",
            dialect="snowflake",
        )
        assert '"my_assignments"' in sql

    # ------------------------------------------------------------------ #
    # 9. BigQuery dialect uses backtick identifiers
    # ------------------------------------------------------------------ #
    def test_bigquery_dialect_uses_backtick_identifiers(self):
        sql = WarehouseQueryGenerator.generate_assignment_query(
            experiment_id="exp-bq",
            assignments_table="my_assignments",
            dialect="bigquery",
        )
        assert "`my_assignments`" in sql

    # ------------------------------------------------------------------ #
    # 10. Redshift dialect uses double-quote identifiers
    # ------------------------------------------------------------------ #
    def test_redshift_dialect_uses_double_quote_identifiers(self):
        sql = WarehouseQueryGenerator.generate_assignment_query(
            experiment_id="exp-rs",
            assignments_table="my_assignments",
            dialect="redshift",
        )
        assert '"my_assignments"' in sql

    # ------------------------------------------------------------------ #
    # 11. validate_sql returns True for valid SELECT statements
    # ------------------------------------------------------------------ #
    def test_validate_sql_accepts_select_statement(self):
        sql = "SELECT user_id, variant_id FROM assignments WHERE experiment_id = 'x'"
        assert WarehouseQueryGenerator.validate_sql(sql) is True

    # ------------------------------------------------------------------ #
    # 12. validate_sql returns False for SQL containing dangerous keywords
    # ------------------------------------------------------------------ #
    @pytest.mark.parametrize(
        "dangerous_sql",
        [
            "DROP TABLE assignments",
            "DELETE FROM assignments",
            "INSERT INTO assignments VALUES (1)",
            "UPDATE assignments SET x=1",
        ],
    )
    def test_validate_sql_rejects_dangerous_statements(self, dangerous_sql):
        assert WarehouseQueryGenerator.validate_sql(dangerous_sql) is False

    # ------------------------------------------------------------------ #
    # 13. validate_sql returns False for empty string
    # ------------------------------------------------------------------ #
    def test_validate_sql_rejects_empty_string(self):
        assert WarehouseQueryGenerator.validate_sql("") is False
        assert WarehouseQueryGenerator.validate_sql("   ") is False

    # ------------------------------------------------------------------ #
    # 14. Generated SQL sanitizes table names (no SQL injection vectors)
    # ------------------------------------------------------------------ #
    def test_generated_sql_sanitizes_table_names(self):
        """
        The sanitizer strips characters that break out of identifier quoting
        (semicolons, spaces, dashes).  After sanitization the identifier is
        also quoted, so even if letters like "DROP" survive they appear
        *inside* a quoted string and cannot be executed as a standalone
        statement.  We verify the two structural injection vectors are gone.
        """
        malicious_table = "assignments; DROP TABLE users --"
        sql = WarehouseQueryGenerator.generate_assignment_query(
            experiment_id="exp-123",
            assignments_table=malicious_table,
            dialect="default",
        )
        # Structural injection characters must be stripped by the sanitizer
        assert ";" not in sql
        # Spaces between keywords are removed, so "DROP TABLE" cannot parse
        assert "DROP TABLE" not in sql
        assert " --" not in sql

    # ------------------------------------------------------------------ #
    # 15. sanitize_identifier strips non-alphanumeric chars except _ and .
    # ------------------------------------------------------------------ #
    def test_sanitize_identifier_strips_dangerous_characters(self):
        result = WarehouseQueryGenerator.sanitize_identifier("my-table; DROP--")
        assert ";" not in result
        assert " " not in result
        assert "-" not in result
        # alphanumeric and underscore should remain
        assert "my" in result
        assert "table" in result

    def test_sanitize_identifier_preserves_dot_for_schema_qualified(self):
        result = WarehouseQueryGenerator.sanitize_identifier("my_schema.my_table")
        assert result == "my_schema.my_table"


# ---------------------------------------------------------------------------
# TestWarehouseConnectionManager (10 tests)
# ---------------------------------------------------------------------------


class TestWarehouseConnectionManager:
    """Tests for WarehouseConnectionManager CRUD and credential handling."""

    def _make_manager(self, db=None):
        if db is None:
            db = MagicMock()
        return WarehouseConnectionManager(db)

    # ------------------------------------------------------------------ #
    # 16. test_connection returns a ConnectionTestResult
    # ------------------------------------------------------------------ #
    def test_test_connection_returns_connection_test_result(self):
        manager = self._make_manager()
        config = {
            "warehouse_type": "snowflake",
            "host": "account.snowflakecomputing.com",
        }
        result = manager.test_connection(config)
        assert isinstance(result, ConnectionTestResult)
        assert hasattr(result, "success")
        assert hasattr(result, "latency_ms")
        assert hasattr(result, "error")

    # ------------------------------------------------------------------ #
    # 17. Returns success=False for invalid warehouse type
    # ------------------------------------------------------------------ #
    def test_test_connection_returns_failure_for_invalid_type(self):
        manager = self._make_manager()
        config = {"warehouse_type": "oracle", "host": "myoracle.example.com"}
        result = manager.test_connection(config)
        assert result.success is False
        assert result.error is not None

    # ------------------------------------------------------------------ #
    # 18. Returns success=True for valid config (mocked)
    # ------------------------------------------------------------------ #
    def test_test_connection_returns_success_for_valid_config(self):
        manager = self._make_manager()
        config = {"warehouse_type": "bigquery", "project_id": "my-gcp-project"}
        result = manager.test_connection(config)
        assert result.success is True
        assert result.latency_ms >= 0

    # ------------------------------------------------------------------ #
    # 19. create_connection saves to DB and returns the connection
    # ------------------------------------------------------------------ #
    def test_create_connection_saves_to_db(self):
        db = MagicMock()

        # Simulate db.refresh populating id
        def fake_refresh(obj):
            obj.id = uuid.uuid4()

        db.refresh.side_effect = fake_refresh

        manager = WarehouseConnectionManager(db)

        # Patch at the model module level where the class is defined
        with patch(
            "modules.backend.app.models.warehouse_connection.WarehouseConnection"
        ) as MockConn:
            fake_conn = MagicMock()
            fake_conn.id = uuid.uuid4()
            fake_conn.name = "My Snowflake"
            fake_conn.warehouse_type = "snowflake"
            fake_conn.is_active = True
            MockConn.return_value = fake_conn

            conn = manager.create_connection(
                name="My Snowflake",
                warehouse_type="snowflake",
                config={"host": "account.snowflakecomputing.com", "username": "user"},
            )

        db.add.assert_called_once()
        db.commit.assert_called()
        assert conn is not None

    # ------------------------------------------------------------------ #
    # 20. get_connection returns connection by ID
    # ------------------------------------------------------------------ #
    def test_get_connection_returns_connection_by_id(self):
        db = MagicMock()
        fake_conn = MagicMock()
        fake_conn.id = uuid.uuid4()
        fake_conn.is_active = True

        # Set up query chain: db.query(...).filter(...).first() → fake_conn
        db.query.return_value.filter.return_value.first.return_value = fake_conn

        manager = WarehouseConnectionManager(db)
        # Patch at the model module where the class is actually defined
        with patch(
            "modules.backend.app.models.warehouse_connection.WarehouseConnection"
        ):
            result = manager.get_connection(fake_conn.id)

        assert result == fake_conn

    # ------------------------------------------------------------------ #
    # 21. list_connections returns all active connections
    # ------------------------------------------------------------------ #
    def test_list_connections_returns_all_active(self):
        db = MagicMock()
        fake_conns = [MagicMock(), MagicMock()]
        db.query.return_value.filter.return_value.all.return_value = fake_conns

        manager = WarehouseConnectionManager(db)
        # Patch at the model module where the class is actually defined
        with patch(
            "modules.backend.app.models.warehouse_connection.WarehouseConnection"
        ):
            results = manager.list_connections()

        assert results == fake_conns

    # ------------------------------------------------------------------ #
    # 22. delete_connection soft-deletes (sets is_active=False)
    # ------------------------------------------------------------------ #
    def test_delete_connection_sets_is_active_false(self):
        db = MagicMock()
        fake_conn = MagicMock()
        fake_conn.is_active = True

        manager = WarehouseConnectionManager(db)
        # Patch get_connection to return our fake_conn
        with patch.object(manager, "get_connection", return_value=fake_conn):
            manager.delete_connection(uuid.uuid4())

        assert fake_conn.is_active is False
        db.commit.assert_called()

    # ------------------------------------------------------------------ #
    # 23. Sensitive credentials not in plain-text response attributes
    # ------------------------------------------------------------------ #
    def test_sensitive_credentials_not_exposed_in_response(self):
        """The WarehouseConnection model must NOT have a 'password' or
        'private_key' column — credentials are stored encrypted."""
        from modules.backend.app.models.warehouse_connection import WarehouseConnection

        columns = [c.key for c in WarehouseConnection.__table__.columns]
        assert "password" not in columns
        assert "private_key" not in columns

    # ------------------------------------------------------------------ #
    # 24. encrypt_credentials returns a different string
    # ------------------------------------------------------------------ #
    def test_encrypt_credentials_returns_transformed_string(self):
        manager = self._make_manager()
        config = {"username": "user", "password": "s3cr3t"}
        encrypted = manager.encrypt_credentials(config)
        assert isinstance(encrypted, str)
        assert encrypted != str(config)
        assert "s3cr3t" not in encrypted  # plaintext password must not appear

    # ------------------------------------------------------------------ #
    # 25. decrypt_credentials round-trips back to original config
    # ------------------------------------------------------------------ #
    def test_decrypt_credentials_roundtrips_original(self):
        manager = self._make_manager()
        config = {"username": "user", "password": "s3cr3t", "host": "myhost"}
        encrypted = manager.encrypt_credentials(config)
        decrypted = manager.decrypt_credentials(encrypted)
        assert decrypted == config


# ---------------------------------------------------------------------------
# TestResultsImporter (5 tests)
# ---------------------------------------------------------------------------


class TestResultsImporter:
    """Tests for mapping warehouse query rows to experiment metric results."""

    # ------------------------------------------------------------------ #
    # 26. import_results maps rows to MetricResult-like dicts
    # ------------------------------------------------------------------ #
    def test_import_results_maps_rows_to_variant_results(self):
        rows = [
            {"variant_id": "control", "sample_size": 1000, "conversions": 120},
            {"variant_id": "treatment", "sample_size": 980, "conversions": 145},
        ]
        results = ResultsImporter.import_results(rows, experiment_id="exp-001")
        assert len(results) == 2
        variant_ids = {r["variant_id"] for r in results}
        assert "control" in variant_ids
        assert "treatment" in variant_ids

    # ------------------------------------------------------------------ #
    # 27. Handles missing conversion column (defaults to 0)
    # ------------------------------------------------------------------ #
    def test_import_results_handles_missing_conversions_column(self):
        rows = [{"variant_id": "control", "sample_size": 500}]
        results = ResultsImporter.import_results(rows, experiment_id="exp-002")
        assert len(results) == 1
        assert results[0]["conversions"] == 0

    # ------------------------------------------------------------------ #
    # 28. Skips rows with no variant_id
    # ------------------------------------------------------------------ #
    def test_import_results_skips_rows_without_variant_id(self):
        rows = [
            {"variant_id": None, "sample_size": 500, "conversions": 50},
            {"sample_size": 300, "conversions": 30},  # missing variant_id key
            {"variant_id": "treatment", "sample_size": 700, "conversions": 80},
        ]
        results = ResultsImporter.import_results(rows, experiment_id="exp-003")
        assert len(results) == 1
        assert results[0]["variant_id"] == "treatment"

    # ------------------------------------------------------------------ #
    # 29. Returns list of VariantResult-like dicts with expected fields
    # ------------------------------------------------------------------ #
    def test_import_results_returns_list_of_dicts_with_required_fields(self):
        rows = [{"variant_id": "control", "sample_size": 1000, "conversions": 100}]
        results = ResultsImporter.import_results(rows, experiment_id="exp-004")
        assert isinstance(results, list)
        result = results[0]
        assert "variant_id" in result
        assert "sample_size" in result
        assert "conversions" in result
        assert "mean" in result

    # ------------------------------------------------------------------ #
    # 30. estimate_query_cost returns cost metadata dict
    # ------------------------------------------------------------------ #
    def test_estimate_query_cost_returns_cost_metadata(self):
        sql = "SELECT user_id, variant_id FROM assignments WHERE experiment_id = 'x'"
        cost = ResultsImporter.estimate_query_cost(sql, dialect="snowflake")
        assert isinstance(cost, dict)
        assert "estimated_bytes_scanned" in cost
        assert "estimated_cost_usd" in cost
        assert "dialect" in cost
        assert cost["dialect"] == "snowflake"
        assert cost["estimated_bytes_scanned"] > 0
