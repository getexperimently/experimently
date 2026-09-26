from aws_cdk import (
    Stack,
    Duration,
    aws_ec2 as ec2,
    aws_kinesis as kinesis,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_s3 as s3,
    aws_kinesisfirehose as firehose,
    aws_opensearchservice as opensearch,
    aws_lambda_event_sources as lambda_event_sources,
)
from constructs import Construct

from stacks.environments import data_removal_policy, retains_data


class AnalyticsStack(Stack):
    """Kinesis -> Firehose -> S3 data lake, with OpenSearch and a Lambda consumer.

    **No resource here carries an explicit physical name**, and that is the
    point.  Until now every one of them was built from
    ``random.choices(...)`` evaluated *at synth time*:

        random_id = "".join(random.choices(ascii_lowercase + digits, k=8))
        stream_name       = f"exp-events-{random_id}"
        bucket_name       = f"exp-data-{random_id}-{region}"
        delivery_stream   = f"exp-delivery-{random_id}"
        domain_name       = f"exp-{random_id[:8]}"

    So two synths of the same source produced two different templates, and
    ``cdk deploy`` replaced the Kinesis stream, the S3 bucket, the Firehose
    delivery stream and the OpenSearch domain **every single time** -- with
    ``cdk diff`` showing a full replacement of the data lake on a no-op deploy.
    The bucket is ``RemovalPolicy.RETAIN``, so each of those replacements left
    the previous one behind, full of events nothing could find.

    That is not hypothetical.  ``exp-data-hdv7dl4h-us-west-2`` is sitting in
    this account today, created 2025-03-22, orphaned by exactly this, from the
    one and only deploy this repository has ever had.  It is empty, so the
    damage this time was nil.

    Omitting the name entirely is better than deriving a deterministic one:
    CloudFormation generates a physical name from the stack name and the
    logical id, which is stable across synths, unique per account, and does not
    have to be hand-checked against each service's length and character rules
    (OpenSearch domains are 3-28 lowercase characters; S3 buckets are globally
    unique -- see #176).  Everything downstream already refers to these by
    object -- ``.stream_arn``, ``.bucket_name``, ``.domain_endpoint`` -- so
    nothing needed to change to follow them.
    """

    def __init__(
        self, scope: Construct, construct_id: str, vpc, env_name: str, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # From app.py's ENVIRONMENT. It was the CDK context key `env`, which
        # nothing sets, so the Lambda below was told ENVIRONMENT=dev in every
        # environment (#142, the same defect as the compute stack's cluster).
        retain = retains_data(env_name)

        # No explicit physical names anywhere in this stack -- see the class
        # docstring. CloudFormation derives one from the stack name and the
        # logical id, which is stable across synths and unique per account.
        self.events_stream = kinesis.Stream(
            self,
            "EventsStream",
            shard_count=1,  # Increase for production
            retention_period=Duration.hours(24),
            # Kept on teardown in prod only (stacks/environments.py). A
            # retained stream bills per shard-hour with nothing writing to it.
            removal_policy=data_removal_policy(env_name),
        )

        # RETAIN plus a name that changed every synth is what orphaned
        # `exp-data-hdv7dl4h-us-west-2` in this account: the replacement was
        # created and the old bucket kept, with nothing pointing at it.
        #
        # Outside prod the bucket is destroyed with the stack, which
        # CloudFormation can only do to an EMPTY bucket -- and this one is
        # versioned and written by Firehose, so it never is. auto_delete_objects
        # adds a custom resource (a CDK-provided Lambda,
        # Custom::S3AutoDeleteObjectsCustomResourceProvider, and its role) that
        # on stack deletion denies new writes and deletes every object version
        # and delete marker. It acts only on a bucket carrying the
        # `aws-cdk:auto-delete-objects` tag, i.e. one deployed with this code.
        self.data_lake_bucket = s3.Bucket(
            self,
            "DataLakeBucket",
            removal_policy=data_removal_policy(env_name),
            auto_delete_objects=not retain,
            versioned=True,
        )

        # Create a policy document with Kinesis permissions
        kinesis_policy = iam.PolicyDocument(
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "kinesis:DescribeStream",
                        "kinesis:GetShardIterator",
                        "kinesis:GetRecords",
                        "kinesis:ListShards",
                    ],
                    resources=[self.events_stream.stream_arn],
                )
            ]
        )

        # Create Firehose role with inline policy
        firehose_role = iam.Role(
            self,
            "FirehoseRole",
            assumed_by=iam.ServicePrincipal("firehose.amazonaws.com"),
            inline_policies={"KinesisPolicy": kinesis_policy},
        )

        # Create inline policy for S3 access
        firehose_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "s3:AbortMultipartUpload",
                    "s3:GetBucketLocation",
                    "s3:GetObject",
                    "s3:ListBucket",
                    "s3:ListBucketMultipartUploads",
                    "s3:PutObject",
                ],
                resources=[
                    self.data_lake_bucket.bucket_arn,
                    f"{self.data_lake_bucket.bucket_arn}/*",
                ],
            )
        )

        # Create inline policy for CloudWatch Logs access
        firehose_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:PutLogEvents",
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                ],
                resources=["arn:aws:logs:*:*:*"],
            )
        )

        delivery_stream = firehose.CfnDeliveryStream(
            self,
            "EventsDeliveryStream",
            delivery_stream_type="KinesisStreamAsSource",
            kinesis_stream_source_configuration=firehose.CfnDeliveryStream.KinesisStreamSourceConfigurationProperty(
                kinesis_stream_arn=self.events_stream.stream_arn,
                role_arn=firehose_role.role_arn,
            ),
            s3_destination_configuration=firehose.CfnDeliveryStream.S3DestinationConfigurationProperty(
                bucket_arn=self.data_lake_bucket.bucket_arn,
                buffering_hints=firehose.CfnDeliveryStream.BufferingHintsProperty(
                    interval_in_seconds=60, size_in_m_bs=5
                ),
                compression_format="GZIP",
                prefix="raw/events/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/",
                error_output_prefix="errors/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/",
                role_arn=firehose_role.role_arn,
            ),
        )
        delivery_stream.node.add_dependency(self.events_stream)

        # Create an OpenSearch domain for analytics (with simplified configuration)
        opensearch_domain = opensearch.Domain(
            self,
            "ExperimentationDomain",
            version=opensearch.EngineVersion.OPENSEARCH_1_3,
            capacity=opensearch.CapacityConfig(
                data_nodes=1, data_node_instance_type="t3.small.search"
            ),
            ebs=opensearch.EbsOptions(
                enabled=True, volume_size=10, volume_type=ec2.EbsDeviceVolumeType.GP2
            ),
            access_policies=[
                iam.PolicyStatement(
                    actions=["es:*"],
                    effect=iam.Effect.ALLOW,
                    principals=[iam.AccountRootPrincipal()],
                    resources=["*"],
                )
            ],
            encryption_at_rest=opensearch.EncryptionAtRestOptions(enabled=True),
            node_to_node_encryption=True,
            # Kept on teardown in prod only: a retained domain bills per
            # instance-hour whether or not anything queries it.
            removal_policy=data_removal_policy(env_name),
        )

        # Rest of implementation unchanged...
        # Create a Lambda function to process events and send to OpenSearch
        lambda_role = iam.Role(
            self,
            "AnalyticsLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        # Grant permissions to the Lambda function
        self.events_stream.grant_read(lambda_role)
        lambda_role.add_to_policy(
            iam.PolicyStatement(
                actions=["es:ESHttpPost", "es:ESHttpPut"],
                resources=[opensearch_domain.domain_arn + "/*"],
            )
        )

        # Analytics Lambda function with placeholder code
        analytics_lambda = lambda_.Function(
            self,
            "AnalyticsLambda",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_inline(
                """
                def handler(event, context):
                    return {
                        'statusCode': 200,
                        'body': 'Event processed'
                    }
                """
            ),
            handler="index.handler",
            environment={
                "OPENSEARCH_DOMAIN": opensearch_domain.domain_endpoint,
                "ENVIRONMENT": env_name,
            },
            timeout=Duration.seconds(30),
            memory_size=256,
            role=lambda_role,
        )

        # Add Kinesis as an event source for the Lambda function
        analytics_lambda.add_event_source(
            lambda_event_sources.KinesisEventSource(
                self.events_stream,
                starting_position=lambda_.StartingPosition.LATEST,
                batch_size=100,
                max_batching_window=Duration.seconds(10),
            )
        )
