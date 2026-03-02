"""ECS task definition for running database migrations."""
from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    aws_ecs as ecs,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_logs as logs,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct


class MigrationTaskStack(Stack):
    """
    One-shot ECS task definition for Alembic database migrations.

    This stack does NOT create a long-running ECS service. Instead it
    registers a Fargate task definition that can be invoked on-demand
    (e.g. from a CI/CD pipeline or a CodePipeline action) to run:

        python -m alembic -c app/db/alembic.ini upgrade head

    Usage in a deployment pipeline:
        aws ecs run-task \\
            --cluster <cluster-name> \\
            --task-definition experimentation-migrate \\
            --launch-type FARGATE \\
            --network-configuration "awsvpcConfiguration={subnets=[...],securityGroups=[...],assignPublicIp=DISABLED}"

    The task exits (succeeds or fails) after the migration completes, making
    it easy to detect failures and gate subsequent deployment steps.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        ecs_cluster,
        env_name: str = "prod",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.ecs_cluster = ecs_cluster

        # --- ECR Repository ---
        # Reuses the same backend image as the main Fargate service.
        # Migrations run from the same Docker image using a different entrypoint.
        ecr_repo = ecr.Repository.from_repository_name(
            self,
            "BackendECR",
            repository_name="experimentation-platform/backend",
        )

        # --- Secrets from Secrets Manager ---
        # Only the DB password is required; the migration task does not need
        # the JWT secret or Redis URL.
        db_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "DbSecret",
            f"/{env_name}/experimentation/db-password",
        )

        # --- IAM Task Execution Role ---
        # The execution role is used by the ECS agent to pull the image and
        # inject secrets before the container starts.
        execution_role = iam.Role(
            self,
            "MigrationExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="ECS task execution role for database migrations",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )
        # Allow the execution role to retrieve only the DB secret
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[db_secret.secret_arn],
            )
        )

        # --- CloudWatch Log Group ---
        # Separate log group from the main service for easy filtering.
        log_group = logs.LogGroup(
            self,
            "MigrationLogs",
            log_group_name=f"/ecs/experimentation-migrate-{env_name}",
            retention=logs.RetentionDays.ONE_MONTH,
            # RETAIN so that migration history is preserved even if the stack
            # is torn down and re-deployed.
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- ECS Task Definition ---
        # Smaller resource allocation than the main service — migrations are
        # short-lived and not performance-critical.
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "MigrationTaskDef",
            # family is shared across env so that the latest revision is always
            # used without hard-coding a specific revision number in pipelines.
            family="experimentation-migrate",
            cpu=512,            # 0.5 vCPU
            memory_limit_mib=1024,  # 1 GB
            execution_role=execution_role,
            # No separate task_role needed — the migration container only reads
            # from Secrets Manager (handled by the execution role) and connects
            # to PostgreSQL. If the application code ever requires AWS API
            # calls during migrations, add a task_role here.
        )

        self.task_definition.add_container(
            "backend",
            image=ecs.ContainerImage.from_ecr_repository(ecr_repo, tag="latest"),
            # Override the default image entrypoint to run Alembic migrations
            command=[
                "python",
                "-m",
                "alembic",
                "-c",
                "app/db/alembic.ini",
                "upgrade",
                "head",
            ],
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="migrate",
                log_group=log_group,
            ),
            environment={
                "APP_ENV": env_name,
                "POSTGRES_DB": "experimentation",
                "POSTGRES_SCHEMA": "experimentation",
                "POSTGRES_PORT": "5432",
                # Ensure Python output is flushed immediately so that
                # CloudWatch Logs captures the full migration output even if
                # the task exits quickly.
                "PYTHONUNBUFFERED": "1",
            },
            secrets={
                "POSTGRES_PASSWORD": ecs.Secret.from_secrets_manager(db_secret),
            },
            essential=True,
        )

        # --- CloudFormation Outputs ---
        CfnOutput(
            self,
            "MigrationTaskDefinitionArn",
            value=self.task_definition.task_definition_arn,
            description="ARN of the Alembic migration ECS task definition",
            export_name=f"{self.stack_name}-MigrationTaskDefArn",
        )
        CfnOutput(
            self,
            "MigrationTaskFamily",
            value=self.task_definition.family,
            description="Family name of the migration ECS task definition (use :LATEST for most recent)",
            export_name=f"{self.stack_name}-MigrationTaskFamily",
        )
        CfnOutput(
            self,
            "MigrationLogGroup",
            value=log_group.log_group_name,
            description="CloudWatch log group for migration task output",
            export_name=f"{self.stack_name}-MigrationLogGroup",
        )
