"""
AWS Glue ETL Script: events_to_parquet

Transforms raw JSON events from the S3 data lake into optimised Parquet files
partitioned by experiment_id and date.

Glue job arguments (passed via --Arguments in start_job_run):
    --JOB_NAME          : Glue job name (required by Glue SDK)
    --input_path        : S3 URI of the raw JSON input prefix
                          e.g. s3://exp-data-bucket/raw/events/year=2024/month=01/day=15/
    --output_path       : S3 URI for Parquet output prefix
                          e.g. s3://exp-data-bucket/processed/events/
    --date              : Processing date in YYYY-MM-DD format
    --experiment_id     : (Optional) filter to a single experiment; omit for all

Output schema (Parquet, snappy):
    event_id       string
    experiment_id  string
    variant_id     string
    user_id        string
    event_type     string
    event_ts       timestamp
    properties     string   (JSON string of the properties map)
    year           string   (partition key)
    month          string   (partition key)
    day            string   (partition key)

Partitioned by: experiment_id / date  (date format YYYY-MM-DD)
"""

import sys
import json
import logging

from awsglue.transforms import *  # noqa: F401, F403  (Glue transform API)
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql.functions import col, to_timestamp, date_format, lit, coalesce
from pyspark.sql.types import (
    StructType,
    StructField,
    StringType,
    TimestampType,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parse job arguments
# ---------------------------------------------------------------------------

args = getResolvedOptions(
    sys.argv,
    ["JOB_NAME", "input_path", "output_path", "date"],
)

job_name = args["JOB_NAME"]
input_path = args["input_path"]
output_path = args["output_path"]
processing_date = args["date"]  # YYYY-MM-DD

# Optional experiment_id filter (may not be present)
experiment_id_filter = args.get("experiment_id")  # None if not supplied

# ---------------------------------------------------------------------------
# Initialise Glue / Spark context
# ---------------------------------------------------------------------------

sc = SparkContext()
glue_context = GlueContext(sc)
spark = glue_context.spark_session
job = Job(glue_context)
job.init(job_name, args)

logger.info(
    f"Starting events_to_parquet | date={processing_date} "
    f"input={input_path} output={output_path} "
    f"experiment_id_filter={experiment_id_filter}"
)

# ---------------------------------------------------------------------------
# Read raw JSON events from S3
# ---------------------------------------------------------------------------

try:
    raw_df = spark.read.option("multiLine", False).json(input_path)
except Exception as exc:
    logger.error(f"Failed to read raw events from {input_path}: {exc}")
    job.commit()
    sys.exit(1)

input_count = raw_df.count()
logger.info(f"Read {input_count} raw events from S3")

if input_count == 0:
    logger.warning("No events found for the specified date/path. Exiting.")
    job.commit()
    sys.exit(0)

# ---------------------------------------------------------------------------
# Cast and clean fields
# ---------------------------------------------------------------------------

# Normalise timestamp field (event_ts or timestamp column from raw events)
df = raw_df.withColumn(
    "event_ts",
    coalesce(
        to_timestamp(col("timestamp"), "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"),
        to_timestamp(col("timestamp"), "yyyy-MM-dd'T'HH:mm:ss"),
        to_timestamp(col("event_ts")),
    ),
)

# Ensure core string fields exist; fill nulls with empty string
for field in ["event_id", "experiment_id", "variant_id", "user_id", "event_type"]:
    if field not in df.columns:
        df = df.withColumn(field, lit(""))
    else:
        df = df.withColumn(field, col(field).cast(StringType()))

# Serialise properties map/struct to JSON string for storage compatibility
if "properties" in df.columns:
    df = df.withColumn("properties", col("properties").cast(StringType()))
else:
    df = df.withColumn("properties", lit("{}"))

# Add partition date columns
df = df.withColumn("year", lit(processing_date[:4]))
df = df.withColumn("month", lit(processing_date[5:7]))
df = df.withColumn("day", lit(processing_date[8:10]))

# ---------------------------------------------------------------------------
# Optionally filter by experiment_id
# ---------------------------------------------------------------------------

if experiment_id_filter:
    df = df.filter(col("experiment_id") == experiment_id_filter)
    logger.info(
        f"Filtered to experiment_id={experiment_id_filter}; "
        f"rows after filter: {df.count()}"
    )

# ---------------------------------------------------------------------------
# Select output columns
# ---------------------------------------------------------------------------

output_df = df.select(
    "event_id",
    "experiment_id",
    "variant_id",
    "user_id",
    "event_type",
    "event_ts",
    "properties",
    "year",
    "month",
    "day",
)

# Drop rows where experiment_id or event_id is null/empty
output_df = output_df.filter(
    col("event_id").isNotNull()
    & (col("event_id") != "")
    & col("experiment_id").isNotNull()
    & (col("experiment_id") != "")
)

output_count = output_df.count()
logger.info(f"Writing {output_count} cleansed events to Parquet")

# ---------------------------------------------------------------------------
# Write Parquet to S3 partitioned by experiment_id / date
# ---------------------------------------------------------------------------

try:
    (
        output_df.repartition("experiment_id", "year", "month", "day")
        .write.mode("overwrite")
        .option("compression", "snappy")
        .partitionBy("experiment_id", "year", "month", "day")
        .parquet(output_path)
    )
    logger.info(
        f"Successfully wrote {output_count} events to {output_path}"
    )
except Exception as exc:
    logger.error(f"Failed to write Parquet output: {exc}")
    job.commit()
    sys.exit(1)

# ---------------------------------------------------------------------------
# Commit job
# ---------------------------------------------------------------------------

job.commit()
logger.info("Job completed successfully")
