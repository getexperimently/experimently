"""
AWS CDK Stack: GlueETLStack (P3-A)

Provisions the full Glue ETL infrastructure for the experimentation platform:

Resources created:
    1. Glue IAM Role          — Glue service principal with S3, Glue catalog, and
                                CloudWatch permissions.
    2. Glue Database          — 'experimentation_<env>' catalog database.
    3. Glue ETL Job           — 'experimentation-events-etl-<env>' (JSON → Parquet).
    4. Glue Metrics Job       — 'experimentation-metrics-etl-<env>' (metric aggregation).
    5. Glue Crawler           — 'experimentation-crawler-<env>' for raw_events table.
    6. EventBridge Rule       — Daily cron trigger at 02:00 UTC.
    7. Lambda Invoker         — Lambda function that calls glue:StartJobRun from
                                EventBridge events.
    8. Athena Results Bucket  — S3 bucket for Athena query output.

Usage:
    glue_stack = GlueETLStack(
        app,
        f"experimentation-glue-etl-{env_name}",
        data_lake_bucket=analytics_stack.data_lake_bucket,
        env_name=env_name,
        env=cdk_env,
    )
    glue_stack.add_dependency(analytics_stack)
"""

from aws_cdk import (
    Stack,
    Duration,
    aws_glue as glue,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_events as events,
    aws_events_targets as targets,
    aws_s3 as s3,
)
from constructs import Construct

from stacks.environments import data_removal_policy, retains_data
from stacks.names import glue_names


class GlueETLStack(Stack):
    """CDK stack for Glue ETL jobs, crawler, and EventBridge scheduling."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        data_lake_bucket: s3.IBucket,
        env_name: str = "dev",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.data_lake_bucket = data_lake_bucket

        # Stable, environment-scoped names (stacks/names.py). The FastAPI
        # service calls these by name; they were literal and account-scoped,
        # so two environments in one account collided on all four (#139). The
        # Fargate stack gives the API the same names from the same function.
        names = glue_names(env_name)
        self.ETL_JOB_NAME = names["GLUE_ETL_JOB_NAME"]
        self.METRICS_JOB_NAME = names["GLUE_METRICS_JOB_NAME"]
        self.GLUE_DATABASE_NAME = names["GLUE_DATABASE"]
        self.CRAWLER_NAME = names["GLUE_CRAWLER_NAME"]

        # Outside prod both buckets go with the stack (stacks/environments.py);
        # CloudFormation deletes only an empty bucket, so auto_delete_objects
        # adds the CDK's Custom::S3AutoDeleteObjects Lambda to empty them.
        removal_policy = data_removal_policy(env_name)
        auto_delete_objects = not retains_data(env_name)

        # ----------------------------------------------------------------
        # 1. Athena query-results bucket
        # ----------------------------------------------------------------
        self.athena_results_bucket = s3.Bucket(
            self,
            "AthenaResultsBucket",
            # No bucket_name: S3 is a GLOBAL namespace, so
            # `experimentation-athena-results-us-west-2` is claimed by whoever
            # deploys this repository first and every later adopter gets
            # BucketAlreadyExists mid-deploy (#176). Nothing refers to either
            # bucket by name -- both are passed around as constructs.
            removal_policy=removal_policy,
            auto_delete_objects=auto_delete_objects,
            lifecycle_rules=[
                s3.LifecycleRule(
                    expiration=Duration.days(30),
                    enabled=True,
                    id="expire-old-athena-results",
                )
            ],
        )

        # ----------------------------------------------------------------
        # 2. Glue script storage bucket
        # ----------------------------------------------------------------
        glue_scripts_bucket = s3.Bucket(
            self,
            "GlueScriptsBucket",
            # Unnamed, for the reason above. `glue-scripts-dev-us-west-2`
            # is generic enough to be taken by someone unrelated already.
            removal_policy=removal_policy,
            auto_delete_objects=auto_delete_objects,
        )

        # ----------------------------------------------------------------
        # 3. IAM Role for Glue jobs and crawlers
        # ----------------------------------------------------------------
        self.glue_role = iam.Role(
            self,
            "GlueETLRole",
            assumed_by=iam.ServicePrincipal("glue.amazonaws.com"),
            role_name=f"experimentation-glue-role-{env_name}",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSGlueServiceRole"
                )
            ],
        )

        # S3 data lake read/write
        self.glue_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:GetObject",
                    "s3:PutObject",
                    "s3:DeleteObject",
                    "s3:ListBucket",
                    "s3:GetBucketLocation",
                    "s3:AbortMultipartUpload",
                    "s3:ListMultipartUploadParts",
                ],
                resources=[
                    data_lake_bucket.bucket_arn,
                    f"{data_lake_bucket.bucket_arn}/*",
                    glue_scripts_bucket.bucket_arn,
                    f"{glue_scripts_bucket.bucket_arn}/*",
                    self.athena_results_bucket.bucket_arn,
                    f"{self.athena_results_bucket.bucket_arn}/*",
                ],
            )
        )

        # Glue catalog permissions
        self.glue_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "glue:GetDatabase",
                    "glue:GetTable",
                    "glue:GetPartition",
                    "glue:GetPartitions",
                    "glue:CreatePartition",
                    "glue:BatchCreatePartition",
                    "glue:UpdateTable",
                    "glue:UpdateDatabase",
                ],
                resources=["*"],
            )
        )

        # CloudWatch Logs
        self.glue_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                resources=["arn:aws:logs:*:*:/aws-glue/*"],
            )
        )

        # ----------------------------------------------------------------
        # 4. Glue Database (catalog database)
        # ----------------------------------------------------------------
        glue_database = glue.CfnDatabase(
            self,
            "ExperimentationDatabase",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name=self.GLUE_DATABASE_NAME,
                description="Glue catalog database for the experimentation platform",
            ),
        )

        # ----------------------------------------------------------------
        # 5. Glue ETL Job — events JSON → Parquet
        # ----------------------------------------------------------------
        etl_script_location = (
            f"s3://{glue_scripts_bucket.bucket_name}/glue/events_to_parquet.py"
        )

        self.events_etl_job = glue.CfnJob(
            self,
            "EventsToParquetJob",
            name=self.ETL_JOB_NAME,
            role=self.glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=etl_script_location,
            ),
            default_arguments={
                "--job-language": "python",
                "--job-bookmark-option": "job-bookmark-enable",
                "--enable-metrics": "",
                "--enable-continuous-cloudwatch-log": "true",
                "--enable-glue-datacatalog": "",
                "--TempDir": f"s3://{glue_scripts_bucket.bucket_name}/tmp/",
                "--input_path": f"s3://{data_lake_bucket.bucket_name}/raw/events/",
                "--output_path": f"s3://{data_lake_bucket.bucket_name}/processed/events/",
                "--date": "1970-01-01",  # overridden at runtime
            },
            glue_version="4.0",
            worker_type="G.1X",
            number_of_workers=2,
            timeout=60,  # minutes
            max_retries=1,
            description="Transforms raw JSON events from S3 into Parquet format",
            tags={"Environment": env_name, "Project": "experimently"},
        )
        self.events_etl_job.node.add_dependency(glue_database)

        # ----------------------------------------------------------------
        # 6. Glue Metrics Aggregation Job
        # ----------------------------------------------------------------
        metrics_script_location = (
            f"s3://{glue_scripts_bucket.bucket_name}/glue/metrics_aggregation.py"
        )

        self.metrics_etl_job = glue.CfnJob(
            self,
            "MetricsAggregationJob",
            name=self.METRICS_JOB_NAME,
            role=self.glue_role.role_arn,
            command=glue.CfnJob.JobCommandProperty(
                name="glueetl",
                python_version="3",
                script_location=metrics_script_location,
            ),
            default_arguments={
                "--job-language": "python",
                "--job-bookmark-option": "job-bookmark-enable",
                "--enable-metrics": "",
                "--enable-continuous-cloudwatch-log": "true",
                "--enable-glue-datacatalog": "",
                "--TempDir": f"s3://{glue_scripts_bucket.bucket_name}/tmp/",
                "--input_path": f"s3://{data_lake_bucket.bucket_name}/processed/events/",
                "--output_path": f"s3://{data_lake_bucket.bucket_name}/processed/metrics/",
                "--date": "1970-01-01",
            },
            glue_version="4.0",
            worker_type="G.1X",
            number_of_workers=2,
            timeout=60,
            max_retries=1,
            description="Aggregates experiment metrics from Parquet event files",
            tags={"Environment": env_name, "Project": "experimently"},
        )
        self.metrics_etl_job.node.add_dependency(glue_database)

        # ----------------------------------------------------------------
        # 7. Glue Crawler — discovers partitions in raw events
        # ----------------------------------------------------------------
        self.glue_crawler = glue.CfnCrawler(
            self,
            "EventsCrawler",
            name=self.CRAWLER_NAME,
            role=self.glue_role.role_arn,
            database_name=self.GLUE_DATABASE_NAME,
            targets=glue.CfnCrawler.TargetsProperty(
                s3_targets=[
                    glue.CfnCrawler.S3TargetProperty(
                        path=f"s3://{data_lake_bucket.bucket_name}/raw/events/"
                    )
                ]
            ),
            schema_change_policy=glue.CfnCrawler.SchemaChangePolicyProperty(
                update_behavior="UPDATE_IN_DATABASE",
                delete_behavior="LOG",
            ),
            description="Crawls raw S3 events to update the Glue catalog",
            tags={"Environment": env_name, "Project": "experimently"},
        )
        self.glue_crawler.node.add_dependency(glue_database)

        # ----------------------------------------------------------------
        # 8. Lambda function — invokes Glue job from EventBridge
        # ----------------------------------------------------------------
        lambda_role = iam.Role(
            self,
            "ETLLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["glue:StartJobRun"],
                resources=[
                    f"arn:aws:glue:{self.region}:{self.account}:job/{self.ETL_JOB_NAME}",
                    f"arn:aws:glue:{self.region}:{self.account}:job/{self.METRICS_JOB_NAME}",
                ],
            )
        )

        self.etl_trigger_lambda = lambda_.Function(
            self,
            "ETLTriggerLambda",
            function_name=f"experimentation-etl-trigger-{env_name}",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="index.handler",
            code=lambda_.Code.from_inline(
                """
import boto3
import datetime
import os

glue = boto3.client('glue')

ETL_JOB_NAME = os.environ['ETL_JOB_NAME']
METRICS_JOB_NAME = os.environ['METRICS_JOB_NAME']


def handler(event, context):
    # Derive the processing date as yesterday (UTC)
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

    # Start events ETL job
    etl_resp = glue.start_job_run(
        JobName=ETL_JOB_NAME,
        Arguments={
            '--date': yesterday,
            '--job_type': 'events_to_parquet',
        }
    )

    # Start metrics aggregation job
    metrics_resp = glue.start_job_run(
        JobName=METRICS_JOB_NAME,
        Arguments={
            '--date': yesterday,
            '--job_type': 'metrics_aggregation',
        }
    )

    return {
        'date': yesterday,
        'etl_run_id': etl_resp['JobRunId'],
        'metrics_run_id': metrics_resp['JobRunId'],
    }
"""
            ),
            environment={
                "ETL_JOB_NAME": self.ETL_JOB_NAME,
                "METRICS_JOB_NAME": self.METRICS_JOB_NAME,
            },
            timeout=Duration.seconds(30),
            memory_size=128,
            role=lambda_role,
            description="Triggered daily by EventBridge to run Glue ETL jobs",
        )

        # ----------------------------------------------------------------
        # 9. EventBridge Rule — daily at 02:00 UTC
        # ----------------------------------------------------------------
        self.daily_etl_rule = events.Rule(
            self,
            "DailyETLRule",
            rule_name=f"experimentation-daily-etl-{env_name}",
            description="Triggers Glue ETL jobs daily at 02:00 UTC",
            schedule=events.Schedule.cron(
                minute="0",
                hour="2",
                day="*",
                month="*",
                year="*",
            ),
        )
        self.daily_etl_rule.add_target(
            targets.LambdaFunction(self.etl_trigger_lambda)
        )
