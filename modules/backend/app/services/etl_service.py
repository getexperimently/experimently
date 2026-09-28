"""
ETL Service for P3-A: ETL & Glue Jobs for S3 Data Lake.

Provides business logic for:
- Running Glue ETL jobs (events-to-parquet, metrics-aggregation, daily-summary)
- Polling Glue job run status
- Adding Hive-style partitions to the Glue catalog
- Starting and querying Glue crawlers

All AWS clients use boto3. The region is read from the core settings; the
Glue job and crawler names from the modules' settings.
"""

import logging
from typing import Optional

import boto3
from fastapi import HTTPException, status

from backend.app.core.config import settings
from modules.backend.app.schemas.etl import (
    ETLJobRequest,
    ETLJobResponse,
    ETLJobType,
    GlueCrawlerStatus,
    GlueJobStatus,
    PartitionInfo,
)
from modules.backend.app.settings import settings as modules_settings

logger = logging.getLogger(__name__)


def _glue_status_to_enum(raw: str) -> GlueJobStatus:
    """Convert a raw Glue status string to the GlueJobStatus enum."""
    try:
        return GlueJobStatus(raw.upper())
    except ValueError:
        logger.warning(f"Unknown Glue status '{raw}', defaulting to RUNNING")
        return GlueJobStatus.RUNNING


def _job_name_to_type(job_name: str) -> ETLJobType:
    """Derive ETLJobType from job name heuristics."""
    if "metrics" in job_name:
        return ETLJobType.METRICS_AGGREGATION
    return ETLJobType.EVENTS_TO_PARQUET


class ETLService:
    """
    Service layer for Glue ETL job, partition and crawler management.

    Creates boto3 clients lazily on first use so tests can apply moto
    decorators before the clients are instantiated.
    """

    def __init__(self) -> None:
        self._glue_client = None

    # ------------------------------------------------------------------
    # Internal client accessors
    # ------------------------------------------------------------------

    def _glue(self):
        if self._glue_client is None:
            self._glue_client = boto3.client("glue", region_name=settings.AWS_REGION)
        return self._glue_client

    # ------------------------------------------------------------------
    # Job name resolution
    # ------------------------------------------------------------------

    def _get_glue_job_name(self, job_type: ETLJobType) -> str:
        """Return the Glue job name for a given ETLJobType."""
        if job_type == ETLJobType.METRICS_AGGREGATION:
            return modules_settings.GLUE_METRICS_JOB_NAME
        # EVENTS_TO_PARQUET and DAILY_SUMMARY share the main ETL job
        return modules_settings.GLUE_ETL_JOB_NAME

    # ------------------------------------------------------------------
    # run_etl_job
    # ------------------------------------------------------------------

    def run_etl_job(self, request: ETLJobRequest) -> ETLJobResponse:
        """
        Start a Glue job run for the requested ETL job type.

        Args:
            request: ETLJobRequest containing job_type, date, optional experiment_id.

        Returns:
            ETLJobResponse with job_run_id and initial STARTING status.

        Raises:
            HTTPException 500: if the Glue API call fails.
        """
        job_name = self._get_glue_job_name(request.job_type)

        # Build Glue job arguments
        arguments = {
            "--date": request.date,
            "--job_type": request.job_type.value,
            "--force_reprocess": str(request.force_reprocess).lower(),
        }
        if request.experiment_id:
            arguments["--experiment_id"] = request.experiment_id

        logger.info(f"Starting Glue job '{job_name}' for date={request.date}")

        try:
            response = self._glue().start_job_run(JobName=job_name, Arguments=arguments)
        except Exception as exc:
            logger.error(f"Failed to start Glue job '{job_name}': {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start Glue job: {exc}",
            )

        job_run_id = response.get("JobRunId", "")

        return ETLJobResponse(
            job_run_id=job_run_id,
            job_name=job_name,
            job_type=request.job_type,
            status=GlueJobStatus.STARTING,
        )

    # ------------------------------------------------------------------
    # get_job_status
    # ------------------------------------------------------------------

    def get_job_status(
        self,
        job_run_id: str,
        job_name: str,
        job_type: Optional[ETLJobType] = None,
    ) -> ETLJobResponse:
        """
        Retrieve the current status of a Glue job run.

        Args:
            job_run_id: The Glue job run ID.
            job_name: The Glue job name.
            job_type: Optional ETLJobType (derived from job_name if None).

        Returns:
            ETLJobResponse with current status and timing fields.

        Raises:
            HTTPException 404: if the job run is not found.
            HTTPException 500: on unexpected AWS errors.
        """
        try:
            response = self._glue().get_job_run(JobName=job_name, RunId=job_run_id)
        except self._glue().exceptions.EntityNotFoundException:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Job run '{job_run_id}' not found for job '{job_name}'",
            )
        except Exception as exc:
            logger.error(f"Failed to get Glue job run status: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get job status: {exc}",
            )

        run = response.get("JobRun", {})
        raw_status = run.get("JobRunState", "RUNNING")
        glue_status = _glue_status_to_enum(raw_status)

        started_at = run.get("StartedOn")
        completed_at = run.get("CompletedOn")
        error_message = run.get("ErrorMessage")

        resolved_type = job_type or _job_name_to_type(job_name)

        return ETLJobResponse(
            job_run_id=job_run_id,
            job_name=job_name,
            job_type=resolved_type,
            status=glue_status,
            started_at=started_at.isoformat() if started_at else None,
            completed_at=completed_at.isoformat() if completed_at else None,
            error_message=error_message,
        )

    # ------------------------------------------------------------------
    # add_partitions
    # ------------------------------------------------------------------

    def add_partitions(
        self,
        database: str,
        table: str,
        date: str,
        base_location: Optional[str] = None,
    ) -> list[PartitionInfo]:
        """
        Register 24 hourly Hive partitions for a given date in the Glue catalog.

        Partition keys: year, month, day, hour.

        Args:
            database: Glue database name.
            table: Glue table name.
            date: Date string in YYYY-MM-DD format.
            base_location: Optional base S3 path (auto-derived if None).

        Returns:
            List of PartitionInfo objects, one per hour (24 total).

        Raises:
            HTTPException 500: if the Glue API call fails.
        """
        year, month, day = date.split("-")

        # Auto-derive base location from Glue table definition
        if base_location is None:
            try:
                table_response = self._glue().get_table(
                    DatabaseName=database, Name=table
                )
                base_location = (
                    table_response.get("Table", {})
                    .get("StorageDescriptor", {})
                    .get("Location", f"s3://experimentation-data/{database}/{table}/")
                )
            except Exception:
                base_location = f"s3://experimentation-data/{database}/{table}/"

        # Build partition inputs for all 24 hours
        partition_inputs = []
        for hour in range(24):
            hour_str = f"{hour:02d}"
            location = (
                f"{base_location.rstrip('/')}/"
                f"year={year}/month={month}/day={day}/hour={hour_str}/"
            )
            partition_inputs.append(
                {
                    "Values": [year, month, day, hour_str],
                    "StorageDescriptor": {
                        "Location": location,
                        "InputFormat": "org.apache.hadoop.mapred.TextInputFormat",
                        "OutputFormat": "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat",
                        "SerdeInfo": {
                            "SerializationLibrary": "org.openx.data.jsonserde.JsonSerDe"
                        },
                    },
                }
            )

        logger.info(f"Adding 24 partitions to {database}.{table} for date={date}")

        try:
            self._glue().batch_create_partition(
                DatabaseName=database,
                TableName=table,
                PartitionInputList=partition_inputs,
            )
        except Exception as exc:
            # Ignore AlreadyExistsException (partitions already registered)
            if "AlreadyExistsException" not in str(type(exc).__name__):
                logger.warning(f"batch_create_partition warning: {exc}")

        # Build PartitionInfo list from the inputs we constructed
        result = []
        for hour in range(24):
            hour_str = f"{hour:02d}"
            location = (
                f"{base_location.rstrip('/')}/"
                f"year={year}/month={month}/day={day}/hour={hour_str}/"
            )
            result.append(
                PartitionInfo(
                    database=database,
                    table=table,
                    partition_values={
                        "year": year,
                        "month": month,
                        "day": day,
                        "hour": hour_str,
                    },
                    location=location,
                )
            )

        return result

    # ------------------------------------------------------------------
    # run_crawler
    # ------------------------------------------------------------------

    def run_crawler(self, crawler_name: str) -> GlueCrawlerStatus:
        """
        Start a Glue crawler and return its status.

        Args:
            crawler_name: Name of the Glue crawler.

        Returns:
            GlueCrawlerStatus reflecting the post-start state.

        Raises:
            HTTPException 409: if the crawler is already running.
            HTTPException 500: on unexpected AWS errors.
        """
        try:
            self._glue().start_crawler(Name=crawler_name)
        except Exception as exc:
            exc_name = type(exc).__name__
            if "CrawlerRunningException" in exc_name:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Crawler '{crawler_name}' is already running.",
                )
            logger.error(f"Failed to start crawler '{crawler_name}': {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start crawler: {exc}",
            )

        return self.get_crawler_status(crawler_name)

    # ------------------------------------------------------------------
    # get_crawler_status
    # ------------------------------------------------------------------

    def get_crawler_status(self, crawler_name: str) -> GlueCrawlerStatus:
        """
        Retrieve the current status of a Glue crawler.

        Args:
            crawler_name: Name of the Glue crawler.

        Returns:
            GlueCrawlerStatus with state, last run info, and table counts.

        Raises:
            HTTPException 404: if the crawler is not found.
            HTTPException 500: on unexpected AWS errors.
        """
        try:
            response = self._glue().get_crawler(Name=crawler_name)
        except Exception as exc:
            exc_name = type(exc).__name__
            if "EntityNotFoundException" in exc_name:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Crawler '{crawler_name}' not found.",
                )
            logger.error(f"Failed to get crawler status: {exc}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to get crawler status: {exc}",
            )

        crawler = response.get("Crawler", {})
        state = crawler.get("State", "READY")
        last_crawl = crawler.get("LastCrawl", {})
        last_run_status = last_crawl.get("Status")
        last_run_time = last_crawl.get("StartTime")
        crawl_count = crawler.get("CrawlElapsedTime", {})

        return GlueCrawlerStatus(
            crawler_name=crawler_name,
            state=state,
            last_run_status=last_run_status,
            last_run_time=last_run_time.isoformat() if last_run_time else None,
            tables_created=crawl_count.get("TablesCreated", 0)
            if isinstance(crawl_count, dict)
            else 0,
            tables_updated=crawl_count.get("TablesUpdated", 0)
            if isinstance(crawl_count, dict)
            else 0,
        )
