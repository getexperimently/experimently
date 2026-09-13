"""
Unit tests for ETL Pydantic schemas (P3-A TDD - Red phase).

Tests cover:
- ETLJobRequest date format validation
- ETLJobType enum values
- GlueJobStatus enum values
- AthenaQueryRequest length constraints
- ETLJobResponse field handling
- AthenaQueryResult defaults
- PartitionInfo structure
- GlueCrawlerStatus structure
"""

import pytest
from pydantic import ValidationError

from modules.backend.app.schemas.etl import (
    AthenaQueryRequest,
    AthenaQueryResult,
    ETLJobRequest,
    ETLJobResponse,
    ETLJobType,
    GlueCrawlerStatus,
    GlueJobStatus,
    PartitionInfo,
)

# ---------------------------------------------------------------------------
# GlueJobStatus enum tests
# ---------------------------------------------------------------------------


class TestGlueJobStatus:
    def test_all_statuses_present(self):
        """All 7 Glue job statuses must be defined."""
        values = {s.value for s in GlueJobStatus}
        assert values == {
            "STARTING",
            "RUNNING",
            "STOPPING",
            "STOPPED",
            "SUCCEEDED",
            "FAILED",
            "TIMEOUT",
        }

    def test_status_is_string_enum(self):
        """GlueJobStatus values should be strings."""
        assert GlueJobStatus.SUCCEEDED == "SUCCEEDED"
        assert GlueJobStatus.FAILED == "FAILED"

    def test_status_string_comparison(self):
        """GlueJobStatus members compare equal to plain strings."""
        assert GlueJobStatus.RUNNING == "RUNNING"
        assert GlueJobStatus.TIMEOUT == "TIMEOUT"


# ---------------------------------------------------------------------------
# ETLJobType enum tests
# ---------------------------------------------------------------------------


class TestETLJobType:
    def test_all_job_types_present(self):
        """All 3 ETL job types must be defined."""
        values = {t.value for t in ETLJobType}
        assert values == {
            "events_to_parquet",
            "metrics_aggregation",
            "daily_summary",
        }

    def test_job_type_is_string_enum(self):
        """ETLJobType values should be lowercase strings."""
        assert ETLJobType.EVENTS_TO_PARQUET == "events_to_parquet"
        assert ETLJobType.METRICS_AGGREGATION == "metrics_aggregation"
        assert ETLJobType.DAILY_SUMMARY == "daily_summary"


# ---------------------------------------------------------------------------
# ETLJobRequest validation tests
# ---------------------------------------------------------------------------


class TestETLJobRequest:
    def test_valid_request(self):
        """A fully-valid ETLJobRequest is accepted."""
        req = ETLJobRequest(
            job_type=ETLJobType.EVENTS_TO_PARQUET,
            date="2024-01-15",
        )
        assert req.date == "2024-01-15"
        assert req.job_type == ETLJobType.EVENTS_TO_PARQUET
        assert req.experiment_id is None
        assert req.force_reprocess is False

    def test_valid_date_formats(self):
        """Dates in YYYY-MM-DD format are accepted."""
        for valid_date in ["2024-01-01", "2023-12-31", "2025-06-15"]:
            req = ETLJobRequest(job_type=ETLJobType.DAILY_SUMMARY, date=valid_date)
            assert req.date == valid_date

    def test_invalid_date_slash_format(self):
        """Dates using slashes (2024/01/15) are rejected."""
        with pytest.raises(ValidationError) as exc_info:
            ETLJobRequest(job_type=ETLJobType.EVENTS_TO_PARQUET, date="2024/01/15")
        assert (
            "date" in str(exc_info.value).lower()
            or "pattern" in str(exc_info.value).lower()
        )

    def test_invalid_date_partial(self):
        """Partial dates like '2024-01' are rejected."""
        with pytest.raises(ValidationError):
            ETLJobRequest(job_type=ETLJobType.EVENTS_TO_PARQUET, date="2024-01")

    def test_invalid_date_wrong_order(self):
        """Dates in DD-MM-YYYY format are rejected."""
        with pytest.raises(ValidationError):
            ETLJobRequest(job_type=ETLJobType.EVENTS_TO_PARQUET, date="15-01-2024")

    def test_invalid_date_text(self):
        """Non-date strings are rejected."""
        with pytest.raises(ValidationError):
            ETLJobRequest(job_type=ETLJobType.EVENTS_TO_PARQUET, date="not-a-date")

    def test_optional_experiment_id(self):
        """experiment_id can be provided or omitted."""
        req = ETLJobRequest(
            job_type=ETLJobType.METRICS_AGGREGATION,
            date="2024-03-10",
            experiment_id="exp-abc-123",
        )
        assert req.experiment_id == "exp-abc-123"

    def test_force_reprocess_flag(self):
        """force_reprocess defaults to False but can be set True."""
        req = ETLJobRequest(
            job_type=ETLJobType.EVENTS_TO_PARQUET,
            date="2024-01-01",
            force_reprocess=True,
        )
        assert req.force_reprocess is True

    def test_invalid_job_type(self):
        """Unknown job_type values are rejected."""
        with pytest.raises(ValidationError):
            ETLJobRequest(job_type="unknown_job", date="2024-01-01")


# ---------------------------------------------------------------------------
# ETLJobResponse tests
# ---------------------------------------------------------------------------


class TestETLJobResponse:
    def test_minimal_response(self):
        """ETLJobResponse works with only required fields."""
        resp = ETLJobResponse(
            job_run_id="jr-12345",
            job_name="experimentation-events-etl",
            job_type=ETLJobType.EVENTS_TO_PARQUET,
            status=GlueJobStatus.RUNNING,
        )
        assert resp.job_run_id == "jr-12345"
        assert resp.status == GlueJobStatus.RUNNING
        assert resp.error_message is None
        assert resp.input_records is None
        assert resp.output_records is None

    def test_full_response(self):
        """ETLJobResponse accepts all optional fields."""
        resp = ETLJobResponse(
            job_run_id="jr-99999",
            job_name="experimentation-events-etl",
            job_type=ETLJobType.DAILY_SUMMARY,
            status=GlueJobStatus.SUCCEEDED,
            started_at="2024-01-15T02:00:00Z",
            completed_at="2024-01-15T02:15:00Z",
            input_records=50000,
            output_records=48500,
        )
        assert resp.input_records == 50000
        assert resp.output_records == 48500
        assert resp.completed_at == "2024-01-15T02:15:00Z"

    def test_failed_response_with_error(self):
        """ETLJobResponse captures error_message for failed runs."""
        resp = ETLJobResponse(
            job_run_id="jr-error",
            job_name="experimentation-events-etl",
            job_type=ETLJobType.EVENTS_TO_PARQUET,
            status=GlueJobStatus.FAILED,
            error_message="OutOfMemoryError: Java heap space",
        )
        assert resp.status == GlueJobStatus.FAILED
        assert "OutOfMemoryError" in resp.error_message


# ---------------------------------------------------------------------------
# AthenaQueryRequest tests
# ---------------------------------------------------------------------------


class TestAthenaQueryRequest:
    def test_valid_query(self):
        """A valid SQL query is accepted."""
        req = AthenaQueryRequest(sql="SELECT * FROM raw_events LIMIT 10")
        assert req.database == "experimentation"
        assert req.output_location is None

    def test_sql_too_short(self):
        """SQL shorter than 10 characters is rejected."""
        with pytest.raises(ValidationError):
            AthenaQueryRequest(sql="SELECT 1")  # 8 chars

    def test_sql_too_long(self):
        """SQL longer than 10000 characters is rejected."""
        with pytest.raises(ValidationError):
            AthenaQueryRequest(sql="SELECT " + "x" * 9994)  # > 10000

    def test_sql_exactly_min_length(self):
        """SQL of exactly 10 characters is accepted."""
        req = AthenaQueryRequest(sql="SELECT 1=1")
        assert len(req.sql) == 10

    def test_custom_database(self):
        """Custom database name overrides the default."""
        req = AthenaQueryRequest(
            sql="SELECT COUNT(*) FROM events",
            database="analytics_db",
        )
        assert req.database == "analytics_db"

    def test_custom_output_location(self):
        """Custom S3 output location is accepted."""
        req = AthenaQueryRequest(
            sql="SELECT COUNT(*) FROM events",
            output_location="s3://my-bucket/athena-results/",
        )
        assert req.output_location == "s3://my-bucket/athena-results/"


# ---------------------------------------------------------------------------
# AthenaQueryResult tests
# ---------------------------------------------------------------------------


class TestAthenaQueryResult:
    def test_defaults(self):
        """AthenaQueryResult has sensible defaults."""
        result = AthenaQueryResult(
            query_execution_id="qe-abc",
            status="SUCCEEDED",
        )
        assert result.rows == []
        assert result.column_names == []
        assert result.rows_returned == 0
        assert result.execution_time_ms is None
        assert result.data_scanned_bytes is None

    def test_with_rows(self):
        """AthenaQueryResult stores rows and column names."""
        result = AthenaQueryResult(
            query_execution_id="qe-xyz",
            status="SUCCEEDED",
            rows=[{"col1": "val1"}, {"col1": "val2"}],
            column_names=["col1"],
            rows_returned=2,
            execution_time_ms=1234,
            data_scanned_bytes=8192,
        )
        assert result.rows_returned == 2
        assert len(result.rows) == 2
        assert result.execution_time_ms == 1234


# ---------------------------------------------------------------------------
# PartitionInfo tests
# ---------------------------------------------------------------------------


class TestPartitionInfo:
    def test_partition_info_structure(self):
        """PartitionInfo stores partition metadata correctly."""
        info = PartitionInfo(
            database="experimentation",
            table="raw_events",
            partition_values={"year": "2024", "month": "01", "day": "15", "hour": "02"},
            location="s3://exp-data-bucket/raw/events/year=2024/month=01/day=15/hour=02/",
        )
        assert info.database == "experimentation"
        assert info.partition_values["year"] == "2024"
        assert info.creation_time is None


# ---------------------------------------------------------------------------
# GlueCrawlerStatus tests
# ---------------------------------------------------------------------------


class TestGlueCrawlerStatus:
    def test_crawler_status_defaults(self):
        """GlueCrawlerStatus has sensible defaults for optional fields."""
        status = GlueCrawlerStatus(
            crawler_name="experimentation-crawler",
            state="RUNNING",
        )
        assert status.crawler_name == "experimentation-crawler"
        assert status.state == "RUNNING"
        assert status.last_run_status is None
        assert status.tables_created == 0
        assert status.tables_updated == 0

    def test_crawler_status_full(self):
        """GlueCrawlerStatus captures all fields."""
        status = GlueCrawlerStatus(
            crawler_name="experimentation-crawler",
            state="READY",
            last_run_status="SUCCEEDED",
            last_run_time="2024-01-15T01:00:00Z",
            tables_created=3,
            tables_updated=5,
        )
        assert status.last_run_status == "SUCCEEDED"
        assert status.tables_created == 3
        assert status.tables_updated == 5
