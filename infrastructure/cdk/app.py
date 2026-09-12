#!/usr/bin/env python3

import os
from aws_cdk import App, Environment

from stacks.vpc_stack import VpcStack
from stacks.compute_stack import ComputeStack
from stacks.api_stack import ApiStack
from stacks.analytics_stack import AnalyticsStack
from stacks.monitoring_stack import MonitoringStack
from stacks.enhanced_database_stack import EnhancedDatabaseStack
from stacks.dynamodb_tables_stack import DynamoDBTablesStack
from stacks.elasticache_redis_stack import (
    ElastiCacheRedisStack,
)  # Import the Redis stack
from stacks.authentication_stack import AuthenticationStack
from stacks.fargate_service_stack import FargateServiceStack
from stacks.migration_task_stack import MigrationTaskStack
from stacks.dynamodb_counters_stack import DynamoDBCountersStack
from stacks.glue_etl_stack import GlueETLStack

# Environment determination
VALID_ENVIRONMENTS = ["dev", "staging", "prod", "demo"]
env_name = os.environ.get("ENVIRONMENT", "dev")
if env_name not in VALID_ENVIRONMENTS:
    raise ValueError(
        f"Invalid ENVIRONMENT '{env_name}'. Must be one of: {', '.join(VALID_ENVIRONMENTS)}"
    )

# Demo environment uses smaller instance sizing to reduce cost
is_demo = env_name == "demo"
db_instance_size = "db.t3.small" if is_demo else "db.t3.medium"
cache_node_type = "cache.t3.micro" if is_demo else "cache.t3.small"
fargate_desired_count = 1 if is_demo else 2

# Define CDK environment (account and region)
# Account/region come from the environment only: CDK sets CDK_DEFAULT_ACCOUNT
# from the active credentials; AWS_ACCOUNT_ID is what CI (vars.AWS_ACCOUNT_ID)
# and demo/setup-aws.sh export. No account id is hard-coded in the repository.
account = os.environ.get("CDK_DEFAULT_ACCOUNT") or os.environ.get("AWS_ACCOUNT_ID")
region = os.environ.get("CDK_DEFAULT_REGION") or os.environ.get("AWS_REGION", "us-west-2")
if not account:
    raise SystemExit(
        "AWS account id not set: export AWS_ACCOUNT_ID (or let the CDK CLI set "
        "CDK_DEFAULT_ACCOUNT from your credentials) before synthesizing."
    )
env = Environment(account=account, region=region)

app = App()

# Create the authentication stack
auth_stack = AuthenticationStack(
    app, f"experimentation-auth-{env_name}", environment=env_name, env=env
)

# Create the networking stack (VPC, subnets, etc.)
vpc_stack = VpcStack(app, f"experimentation-vpc-{env_name}", env=env)

# Create the DynamoDB tables stack
dynamodb_stack = DynamoDBTablesStack(
    app, f"experimentation-dynamodb-{env_name}", environment=env_name, env=env
)

# P2-B: Real-time counters DynamoDB table
dynamodb_counters_stack = DynamoDBCountersStack(
    app,
    f"experimentation-dynamodb-counters-{env_name}",
    environment=env_name,
    env=env,
)

# Create the enhanced database stack (with improved Aurora PostgreSQL)
database_stack = EnhancedDatabaseStack(
    app,
    f"experimentation-database-{env_name}",
    vpc=vpc_stack.vpc,
    environment=env_name,
    env=env,
)
database_stack.add_dependency(vpc_stack)

# Create the ElastiCache Redis stack
redis_stack = ElastiCacheRedisStack(
    app,
    f"experimentation-redis-{env_name}",
    vpc=vpc_stack.vpc,
    environment=env_name,
    env=env,
)
redis_stack.add_dependency(vpc_stack)

# Create the compute stack (ECS, Lambda)
compute_stack = ComputeStack(
    app, f"experimentation-compute-{env_name}", vpc=vpc_stack.vpc, env=env
)
compute_stack.add_dependency(vpc_stack)
compute_stack.add_dependency(database_stack)
compute_stack.add_dependency(dynamodb_stack)
compute_stack.add_dependency(redis_stack)  # Add dependency on Redis stack

# Create the API Gateway stack
api_stack = ApiStack(
    app,
    f"experimentation-api-{env_name}",
    vpc=vpc_stack.vpc,
    compute=compute_stack,
    env=env,
)
api_stack.add_dependency(compute_stack)

# Create the analytics stack (Kinesis, OpenSearch)
analytics_stack = AnalyticsStack(
    app, f"experimentation-analytics-{env_name}", vpc=vpc_stack.vpc, env=env
)
analytics_stack.add_dependency(vpc_stack)
analytics_stack.add_dependency(dynamodb_stack)

# Create the monitoring stack (CloudWatch, Alarms)
monitoring_stack = MonitoringStack(
    app, f"experimentation-monitoring-{env_name}", vpc=vpc_stack.vpc, env=env
)
monitoring_stack.add_dependency(vpc_stack)

# ---------------------------------------------------------------------------
# EP-019: Production Deployment — ECS Fargate + ALB + Blue/Green + Migrations
# ---------------------------------------------------------------------------

# Optional: supply an ACM certificate ARN via the CERTIFICATE_ARN environment
# variable. Without this the HTTPS listeners cannot be created; the parameter
# defaults to None which produces a listener without a certificate (suitable
# only for development/testing stacks where certificate validation is not
# required).
certificate_arn = os.environ.get("CERTIFICATE_ARN", None)

# Fargate service stack: ALB, blue/green CodeDeploy, auto-scaling
fargate_stack = FargateServiceStack(
    app,
    f"experimentation-fargate-{env_name}",
    vpc=vpc_stack.vpc,
    ecs_cluster=compute_stack.ecs_cluster,
    ecs_security_group=compute_stack.ecs_security_group,
    env_name=env_name,
    certificate_arn=certificate_arn,
    env=env,
)
fargate_stack.add_dependency(compute_stack)
fargate_stack.add_dependency(database_stack)
fargate_stack.add_dependency(redis_stack)

# Migration task stack: one-shot Fargate task for Alembic migrations
migration_stack = MigrationTaskStack(
    app,
    f"experimentation-migrations-{env_name}",
    ecs_cluster=compute_stack.ecs_cluster,
    env_name=env_name,
    env=env,
)
migration_stack.add_dependency(fargate_stack)
migration_stack.add_dependency(database_stack)


# P3-A: ETL & Glue Jobs for S3 Data Lake
glue_etl_stack = GlueETLStack(
    app,
    f"experimentation-glue-etl-{env_name}",
    data_lake_bucket=analytics_stack.data_lake_bucket,
    env_name=env_name,
    env=env,
)
glue_etl_stack.add_dependency(analytics_stack)


app.synth()
