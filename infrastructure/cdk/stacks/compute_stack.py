from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
)
from constructs import Construct

from stacks.names import ecs_cluster_name


class ComputeStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, vpc, env_name: str, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # The environment is a required argument, from app.py's ENVIRONMENT.
        # It used to be `self.node.try_get_context("env") or "dev"`: a CDK
        # context key nothing sets, so every environment -- staging and prod
        # included -- built a cluster named `experimentation-dev`, and the
        # second environment deployed into an account failed on the name
        # (#142). Required rather than defaulted so that a caller cannot fall
        # back to dev silently again.
        #
        # Named, because the deploy workflows address it by name (#80). The
        # name is `experimentation-<env>` (stacks/names.py).
        #
        # Renaming the cluster REPLACES it, and the cluster's Ref is an export
        # the fargate stack imports -- CloudFormation refuses to change an
        # export that is in use. An environment deployed before this change is
        # therefore moved by: destroy the fargate stack, deploy this one,
        # deploy the fargate stack again (docs/self-hosting/cdk.md, "Moving an
        # existing environment"). `test_environments_do_not_collide.py` derives
        # that list from the synthesised import graph.
        self.ecs_cluster = ecs.Cluster(
            self,
            "ECSCluster",
            vpc=vpc,
            cluster_name=ecs_cluster_name(env_name),
            container_insights=True,
        )

        # Create a security group for the ECS tasks
        self.ecs_security_group = ec2.SecurityGroup(
            self,
            "ECSSecurityGroup",
            vpc=vpc,
            description="Allow ECS access",
            allow_all_outbound=True,
        )

        # No ingress rule here on purpose. This used to be
        # `ec2.Peer.any_ipv4()` on 8000 -- anything routable inside the VPC
        # could reach the task port directly, bypassing the load balancer.
        #
        # It could not safely be removed before #174, because it was the only
        # reason the ALB could reach the tasks at all: passing this group's
        # object to the Fargate service made CDK write the real rule into the
        # *compute* stack, which is what created the dependency cycle, and the
        # fix imports the group `mutable=False` so CDK writes nothing here.
        # `fargate_service_stack.py` now states that rule explicitly -- this
        # ALB's security group, port 8000, nothing else -- and
        # `test_the_load_balancer_can_still_reach_the_tasks` pins it.
        #
        # So the blanket rule has no job left. Removing it means the tasks are
        # reachable from the load balancer and from nothing else.

        # Create database access Lambda role with additional permissions
        db_lambda_role = iam.Role(
            self,
            "DatabaseLambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaVPCAccessExecutionRole"
                ),
            ],
        )

        # Add specific policy for database access (Secrets Manager and SSM)
        db_access_policy = iam.Policy(
            self,
            "DatabaseAccessPolicy",
            statements=[
                iam.PolicyStatement(
                    actions=[
                        "secretsmanager:GetSecretValue",
                        "secretsmanager:DescribeSecret",
                    ],
                    resources=["*"],  # In production, restrict to specific secrets
                ),
                iam.PolicyStatement(
                    actions=[
                        "ssm:GetParameter",
                        "ssm:GetParameters",
                    ],
                    resources=[
                        f"arn:aws:ssm:{self.region}:{self.account}:parameter/experimentation/{env_name}/database/*"
                    ],
                ),
            ],
        )

        # Attach the policy to the role
        db_access_policy.attach_to_role(db_lambda_role)

        # Create a simplified database access Lambda
        # Note: In a real application, you should store this code in a separate file
        self.db_access_lambda = lambda_.Function(
            self,
            "DatabaseAccessLambda",
            runtime=lambda_.Runtime.PYTHON_3_11,
            code=lambda_.Code.from_inline(
                "def handler(event, context):\n"
                "    # This is a simplified placeholder\n"
                "    # In production, use lambda_.Code.from_asset() instead\n"
                "    return {\n"
                "        'statusCode': 200,\n"
                "        'body': '{\"message\": \"Database access placeholder\"}'\n"
                "    }\n"
            ),
            handler="index.handler",
            timeout=Duration.seconds(60),
            memory_size=512,
            role=db_lambda_role,
            environment={
                "ENVIRONMENT": env_name,
            },
        )

        # Create a log group with retention policy
        db_logs = logs.LogGroup(
            self,
            "DatabaseLambdaLogs",
            log_group_name=f"/aws/lambda/{self.db_access_lambda.function_name}",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
