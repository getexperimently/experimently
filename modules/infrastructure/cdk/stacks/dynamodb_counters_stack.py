"""
CDK Stack: DynamoDB Experiment Counters (P2-B).

Creates the ``experiment-counters`` DynamoDB table used by the real-time
counter service to store per-variant assignment, event, and conversion counts.

Table design:
    pk  (String)  — Partition key: "EXPERIMENT#{experiment_id}"
    sk  (String)  — Sort key:      "VARIANT#{variant_id}"
    assignments  (Number)  — atomic counter
    events       (Number)  — atomic counter
    conversions  (Number)  — atomic counter
    last_updated (String)  — ISO-8601 timestamp of last update
    expires_at   (Number)  — Unix epoch (TTL) for automatic cleanup

A GSI on ``experiment_id`` (plain string attribute) is created for direct
lookups by experiment ID when the composite pk/sk scheme is not convenient.

IAM grants are exposed via helper methods so the Fargate task role and
Lambda execution roles can be granted access.
"""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    CfnOutput,
    Tags,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_ssm as ssm,
)
from constructs import Construct


class DynamoDBCountersStack(Stack):
    """
    Stack that creates the experiment-counters DynamoDB table for real-time
    counter tracking.

    Args:
        scope:       CDK construct scope.
        construct_id: Unique construct identifier.
        environment: Deployment environment name (``"dev"``, ``"staging"``,
                     ``"prod"``).  Controls billing mode and removal policy.
        **kwargs:    Passed through to the parent ``Stack``.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        environment: str = "dev",
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # NOT `self.environment`: aws_cdk.Stack.environment is a read-only
        # property (the "aws://account/region" string), and assigning to it
        # raised AttributeError before this stack produced anything.  Nothing
        # noticed because the stack was gated behind an environment variable
        # the repository never set, so it had never been synthesised.
        self.environment_name = environment
        self.table_name = f"experiment-counters-{environment}"

        # Billing mode: on-demand for dev/staging; provisioned for prod
        billing_mode = (
            dynamodb.BillingMode.PAY_PER_REQUEST
            if environment in ("dev", "staging")
            else dynamodb.BillingMode.PAY_PER_REQUEST  # still PAY_PER_REQUEST for counters
        )

        # Removal policy: destroy in dev (cost), retain in prod (safety)
        removal_policy = (
            RemovalPolicy.DESTROY if environment == "dev" else RemovalPolicy.RETAIN
        )

        # ----------------------------------------------------------------
        # Main counters table
        # ----------------------------------------------------------------
        self.counters_table = dynamodb.Table(
            self,
            "ExperimentCountersTable",
            table_name=self.table_name,
            partition_key=dynamodb.Attribute(
                name="pk",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="sk",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=billing_mode,
            removal_policy=removal_policy,
            point_in_time_recovery=True,
            # TTL enables automatic cleanup of old experiment data
            time_to_live_attribute="expires_at",
        )

        # ----------------------------------------------------------------
        # GSI: look up all variants by experiment_id without knowing the pk
        # format.  The service stores ``experiment_id`` as a plain attribute
        # so dashboards can query via GSI instead of using begins_with on pk.
        # ----------------------------------------------------------------
        self.counters_table.add_global_secondary_index(
            index_name="experiment-id-index",
            partition_key=dynamodb.Attribute(
                name="experiment_id",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="variant_id",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # ----------------------------------------------------------------
        # SSM Parameters for service discovery
        # ----------------------------------------------------------------
        ssm.StringParameter(
            self,
            "CountersTableNameParam",
            parameter_name=f"/experimentation/{environment}/dynamodb/counters-table",
            string_value=self.counters_table.table_name,
            description="Experiment counters DynamoDB table name",
        )

        ssm.StringParameter(
            self,
            "CountersTableArnParam",
            parameter_name=f"/experimentation/{environment}/dynamodb/counters-table-arn",
            string_value=self.counters_table.table_arn,
            description="Experiment counters DynamoDB table ARN",
        )

        # ----------------------------------------------------------------
        # Tags
        # ----------------------------------------------------------------
        Tags.of(self.counters_table).add("Service", "experimently")
        Tags.of(self.counters_table).add("Component", "realtime-counters")
        Tags.of(self.counters_table).add("Environment", environment)

        # ----------------------------------------------------------------
        # CloudFormation outputs
        # ----------------------------------------------------------------
        CfnOutput(
            self,
            "CountersTableNameOutput",
            value=self.counters_table.table_name,
            description="Experiment counters DynamoDB table name",
            export_name=f"{self.stack_name}-CountersTableName",
        )

        CfnOutput(
            self,
            "CountersTableArnOutput",
            value=self.counters_table.table_arn,
            description="Experiment counters DynamoDB table ARN",
            export_name=f"{self.stack_name}-CountersTableArn",
        )

    # ------------------------------------------------------------------
    # IAM grant helpers
    # ------------------------------------------------------------------

    def grant_read_write(self, grantee: iam.IGrantable) -> iam.Grant:
        """
        Grant read and write access to the counters table.

        Suitable for the API / Fargate task role and the event processor
        Lambda execution role that need to call UpdateItem and Query.

        Args:
            grantee: IAM principal to grant access to (e.g. a Lambda
                     function's ``role`` or an ECS ``task_role``).

        Returns:
            The CDK ``Grant`` object (for chaining or inspection).
        """
        return self.counters_table.grant_read_write_data(grantee)

    def grant_read(self, grantee: iam.IGrantable) -> iam.Grant:
        """
        Grant read-only access to the counters table.

        Suitable for dashboard / analytics roles that only need to read
        counter values.

        Args:
            grantee: IAM principal to grant access to.

        Returns:
            The CDK ``Grant`` object.
        """
        return self.counters_table.grant_read_data(grantee)
