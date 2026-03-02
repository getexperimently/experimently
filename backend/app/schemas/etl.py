"""
ETL & Glue Job schemas for P3-A: ETL & Glue Jobs for S3 Data Lake.

Provides Pydantic models for:
- ETL job requests and responses (Glue job management)
- Athena query execution and results
- Glue partition management
- Glue crawler status
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from enum import Enum
from datetime import datetime


class GlueJobStatus(str, Enum):
    """Possible states for a Glue job run."""

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"


class ETLJobType(str, Enum):
    """Supported ETL job types."""

    EVENTS_TO_PARQUET = "events_to_parquet"
    METRICS_AGGREGATION = "metrics_aggregation"
    DAILY_SUMMARY = "daily_summary"


class ETLJobRequest(BaseModel):
    """Request body for triggering an ETL job run."""

    model_config = ConfigDict(extra="forbid")

    job_type: ETLJobType
    date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")  # YYYY-MM-DD
    experiment_id: Optional[str] = None  # None = all experiments
    force_reprocess: bool = False


class ETLJobResponse(BaseModel):
    """Response returned after starting or querying a Glue job run."""

    model_config = ConfigDict(extra="ignore")

    job_run_id: str
    job_name: str
    job_type: ETLJobType
    status: GlueJobStatus
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    input_records: Optional[int] = None
    output_records: Optional[int] = None


class AthenaQueryRequest(BaseModel):
    """Request body for executing an Athena SQL query."""

    model_config = ConfigDict(extra="forbid")

    sql: str = Field(..., min_length=10, max_length=10000)
    database: str = "experimentation"
    output_location: Optional[str] = None  # S3 path; defaults to settings value


class AthenaQueryResult(BaseModel):
    """Result of an Athena SQL query execution."""

    model_config = ConfigDict(extra="ignore")

    query_execution_id: str
    status: str  # QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED
    rows: list[dict] = []
    column_names: list[str] = []
    rows_returned: int = 0
    execution_time_ms: Optional[int] = None
    data_scanned_bytes: Optional[int] = None


class PartitionInfo(BaseModel):
    """Metadata about a Glue catalog partition."""

    model_config = ConfigDict(extra="ignore")

    database: str
    table: str
    partition_values: dict[str, str]
    location: str
    creation_time: Optional[str] = None


class GlueCrawlerStatus(BaseModel):
    """Status of a Glue crawler."""

    model_config = ConfigDict(extra="ignore")

    crawler_name: str
    state: str  # READY, RUNNING, STOPPING
    last_run_status: Optional[str] = None
    last_run_time: Optional[str] = None
    tables_created: int = 0
    tables_updated: int = 0
