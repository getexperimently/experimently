from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    aws_codedeploy as codedeploy,
    aws_secretsmanager as secretsmanager,
    aws_logs as logs,
)
from constructs import Construct


class FargateServiceStack(Stack):
    """
    ECS Fargate service with blue/green CodeDeploy deployment.

    Provides:
    - ALB with HTTPS listener and HTTP->HTTPS redirect
    - Blue/green target groups for zero-downtime deployments
    - ECS Fargate service with CodeDeploy controller
    - Auto-scaling based on CPU and memory utilization
    - Secrets Manager integration for sensitive configuration

    Prerequisites:
    - An ACM certificate must exist for the HTTPS listener. Set the
      CERTIFICATE_ARN environment variable or pass certificate_arn to the
      constructor. Without a valid ACM certificate the HTTPS listener cannot
      be created and the stack will fail during deployment.
    - The Secrets Manager secrets listed in docs/deployment/README.md must
      exist. ECS cannot start a task whose task definition names a secret that
      is not there, and the application cannot start without their values.

    ``include_modules`` is the deployment's profile (``app.py`` passes
    ``ENABLE_MODULE_STACKS``). ``True`` adds the full profile's own secret,
    ``AUDIT_HMAC_KEY``; see the comment beside it.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        vpc,
        ecs_cluster,
        ecs_security_group,
        env_name: str = "prod",
        certificate_arn: str = None,
        include_modules: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.env_name = env_name
        self.include_modules = include_modules

        # --- ECR Repository ---
        self.ecr_repo = ecr.Repository.from_repository_name(
            self,
            "BackendECR",
            repository_name="experimentation-platform/backend",
        )

        # --- Secrets from Secrets Manager ---
        # These secrets must be created manually (or by another stack) before
        # deploying this stack. The secret paths follow the convention:
        #   /<env>/experimentation/<secret-name>
        db_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "DbSecret", f"/{env_name}/experimentation/db-password"
        )
        jwt_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "JwtSecret", f"/{env_name}/experimentation/jwt-secret"
        )
        redis_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "RedisSecret", f"/{env_name}/experimentation/redis-url"
        )
        # Every secret below is one the container REFUSES TO START without in a
        # hardened environment, and the task definition is the only thing that
        # can supply it: the image ships no .env file (.dockerignore keeps
        # .env.* out of the build context).
        #
        # FIRST_SUPERUSER_PASSWORD defaults to "admin", which
        # `Settings.validate_superuser_password` rejects in staging/production
        # -- so `import backend.app.core.config` raised ValidationError and
        # uvicorn never bound, on BOTH profiles.
        superuser_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "SuperuserPasswordSecret",
            f"/{env_name}/experimentation/first-superuser-password",
        )
        required_secrets = [db_secret, jwt_secret, redis_secret, superuser_secret]

        # AUDIT_HMAC_KEY is the full profile's: `modules.register(hooks)` builds
        # ModulesSettings as its first step and its validator rejects the dev
        # default in staging/production, so a full image without this secret
        # fails the registration -- which `abort_if_modules_broken()` turns into
        # a refusal to start, and which kills every alembic command too
        # (migrations/env.py calls require_modules_or_absent()).
        #
        # Only for the full profile: a core image never reads it, and naming a
        # secret that does not exist stops ECS from starting the task at all.
        audit_secret = None
        if include_modules:
            audit_secret = secretsmanager.Secret.from_secret_name_v2(
                self,
                "AuditHmacSecret",
                f"/{env_name}/experimentation/audit-hmac-key",
            )
            required_secrets.append(audit_secret)

        # --- IAM Task Role ---
        # The task role is assumed by the application code running inside the
        # container. It has least-privilege access to only the secrets it needs.
        task_role = iam.Role(
            self,
            "ECSTaskRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            description="IAM role for ECS Fargate tasks",
        )
        task_role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "CloudWatchLogsFullAccess"
            )
        )
        # Least-privilege Secrets Manager access — only the required secrets
        task_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[secret.secret_arn for secret in required_secrets],
            )
        )

        # --- IAM Task Execution Role ---
        # The execution role is used by the ECS agent to pull the container
        # image from ECR and inject secrets as environment variables at startup.
        execution_role = iam.Role(
            self,
            "ECSExecutionRole",
            assumed_by=iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AmazonECSTaskExecutionRolePolicy"
                )
            ],
        )
        # The execution role also needs GetSecretValue so that ECS can inject
        # the secrets as environment variables before the container starts.
        execution_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[secret.secret_arn for secret in required_secrets],
            )
        )

        # --- CloudWatch Log Group ---
        log_group = logs.LogGroup(
            self,
            "BackendLogGroup",
            log_group_name=f"/ecs/experimentation-backend-{env_name}",
            retention=logs.RetentionDays.THREE_MONTHS,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- ECS Task Definition ---
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "BackendTaskDef",
            family=f"experimentation-backend-{env_name}",
            cpu=1024,           # 1 vCPU
            memory_limit_mib=2048,  # 2 GB
            task_role=task_role,
            execution_role=execution_role,
        )

        self.container = self.task_definition.add_container(
            "backend",
            image=ecs.ContainerImage.from_ecr_repository(self.ecr_repo, tag="latest"),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="backend",
                log_group=log_group,
            ),
            environment={
                "APP_ENV": env_name,
                "LOG_LEVEL": "INFO",
                "PYTHONUNBUFFERED": "1",
                "POSTGRES_DB": "experimentation",
                "POSTGRES_SCHEMA": "experimentation",
                "POSTGRES_PORT": "5432",
            },
            secrets={
                "POSTGRES_PASSWORD": ecs.Secret.from_secrets_manager(db_secret),
                "SECRET_KEY": ecs.Secret.from_secrets_manager(jwt_secret),
                "REDIS_URL": ecs.Secret.from_secrets_manager(redis_secret),
                "FIRST_SUPERUSER_PASSWORD": ecs.Secret.from_secrets_manager(
                    superuser_secret
                ),
                **(
                    {
                        "AUDIT_HMAC_KEY": ecs.Secret.from_secrets_manager(
                            audit_secret
                        )
                    }
                    if audit_secret is not None
                    else {}
                ),
            },
            health_check=ecs.HealthCheck(
                command=["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"],
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(60),
            ),
            essential=True,
        )

        self.container.add_port_mappings(
            ecs.PortMapping(container_port=8000, protocol=ecs.Protocol.TCP)
        )

        # --- Application Load Balancer ---
        # The ALB is internet-facing and placed in the public subnets. ECS tasks
        # run in private subnets and receive traffic only through the ALB.
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "BackendALB",
            vpc=vpc,
            internet_facing=True,
            load_balancer_name=f"experimentation-{env_name}",
            # ALB is placed in public subnets by default when internet_facing=True
        )

        # HTTP (port 80) -> HTTPS (port 443) permanent redirect
        self.alb.add_redirect(
            source_port=80,
            source_protocol=elbv2.ApplicationProtocol.HTTP,
            target_port=443,
            target_protocol=elbv2.ApplicationProtocol.HTTPS,
        )

        # --- Blue Target Group (current / stable version) ---
        self.blue_target_group = elbv2.ApplicationTargetGroup(
            self,
            "BlueTargetGroup",
            vpc=vpc,
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
                healthy_http_codes="200",
            ),
            deregistration_delay=Duration.seconds(30),
        )

        # --- Green Target Group (new version during blue/green deployment) ---
        self.green_target_group = elbv2.ApplicationTargetGroup(
            self,
            "GreenTargetGroup",
            vpc=vpc,
            port=8000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/health",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
                healthy_http_codes="200",
            ),
            deregistration_delay=Duration.seconds(30),
        )

        # --- HTTPS Production Listener (port 443) ---
        # IMPORTANT: An ACM certificate ARN is required for the HTTPS listener.
        # In production, provision a certificate via AWS Certificate Manager
        # (either via the console or a separate CDK stack) and pass its ARN as
        # the `certificate_arn` constructor parameter or the CERTIFICATE_ARN
        # environment variable. Without a certificate this listener cannot be
        # created and the stack deploy will fail.
        #
        # Example certificate ARN format:
        #   arn:aws:acm:<region>:<account>:certificate/<uuid>
        https_listener_kwargs = dict(
            port=443,
            protocol=elbv2.ApplicationProtocol.HTTPS,
            default_target_groups=[self.blue_target_group],
            open=True,
        )
        if certificate_arn:
            https_listener_kwargs["certificates"] = [
                elbv2.ListenerCertificate.from_arn(certificate_arn)
            ]

        self.https_listener = self.alb.add_listener(
            "HttpsListener",
            **https_listener_kwargs,
        )

        # --- Test Listener (port 8443) ---
        # CodeDeploy uses this listener to route traffic to the green (new)
        # version during deployment so that health checks can pass before
        # shifting production traffic. Access to the test port is restricted
        # (open=False) so that it is not publicly accessible.
        test_listener_kwargs = dict(
            port=8443,
            protocol=elbv2.ApplicationProtocol.HTTPS,
            default_target_groups=[self.green_target_group],
            open=False,
        )
        if certificate_arn:
            test_listener_kwargs["certificates"] = [
                elbv2.ListenerCertificate.from_arn(certificate_arn)
            ]

        self.test_listener = self.alb.add_listener(
            "TestListener",
            **test_listener_kwargs,
        )

        # --- ECS Fargate Service (CodeDeploy deployment controller) ---
        # Using CODE_DEPLOY controller disables rolling updates managed by ECS
        # and hands deployment control entirely to CodeDeploy, enabling the
        # blue/green strategy defined below.
        self.fargate_service = ecs.FargateService(
            self,
            "BackendService",
            service_name=f"experimentation-backend-{env_name}",
            cluster=ecs_cluster,
            task_definition=self.task_definition,
            desired_count=3,
            min_healthy_percent=100,
            max_healthy_percent=200,
            security_groups=[ecs_security_group],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            deployment_controller=ecs.DeploymentController(
                type=ecs.DeploymentControllerType.CODE_DEPLOY
            ),
            health_check_grace_period=Duration.seconds(60),
            # ECS Exec enables interactive debugging sessions on running tasks
            # via `aws ecs execute-command`. Disable in high-security environments.
            enable_execute_command=True,
        )

        # Attach the service to the blue target group. CodeDeploy will manage
        # shifting traffic between blue and green during deployments.
        self.fargate_service.attach_to_application_target_group(
            self.blue_target_group
        )

        # --- CodeDeploy IAM Role ---
        codedeploy_role = iam.Role(
            self,
            "CodeDeployRole",
            assumed_by=iam.ServicePrincipal("codedeploy.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "AWSCodeDeployRoleForECS"
                )
            ],
        )

        # --- CodeDeploy Application ---
        self.codedeploy_app = codedeploy.EcsApplication(
            self,
            "CodeDeployApp",
            application_name="experimentation-platform",
        )

        # --- CodeDeploy Deployment Group ---
        # Uses CANARY_10_PERCENT_5_MINUTES: routes 10 % of traffic to green,
        # waits 5 minutes for alarms/health checks, then shifts the remaining
        # 90 % if all checks pass.
        self.deployment_group = codedeploy.EcsDeploymentGroup(
            self,
            "DeploymentGroup",
            application=self.codedeploy_app,
            deployment_group_name=f"experimentation-{env_name}",
            service=self.fargate_service,
            blue_green_deployment_config=codedeploy.EcsBlueGreenDeploymentConfig(
                listener=self.https_listener,
                test_listener=self.test_listener,
                blue_target_group=self.blue_target_group,
                green_target_group=self.green_target_group,
                # Allow up to 30 minutes of manual approval before auto-rolling
                # back, giving operators time to validate the deployment via the
                # test listener before committing the traffic shift.
                deployment_approval_wait_time=Duration.minutes(30),
                # Keep the blue (old) task set alive for 1 hour after a
                # successful deployment so that a quick rollback is possible
                # without a full re-deployment.  The property is
                # `termination_wait_time` (a Duration): the name this used --
                # `terminate_blue_instances_on_deployment_success=
                # codedeploy.InstanceTerminationWaitTime.after(...)` -- is from
                # the EC2/on-premises deployment group and does not exist in
                # aws_cdk.aws_codedeploy at all, so `cdk synth` raised
                # AttributeError before it produced a single template.
                termination_wait_time=Duration.hours(1),
            ),
            deployment_config=codedeploy.EcsDeploymentConfig.CANARY_10_PERCENT_5_MINUTES,
            role=codedeploy_role,
            auto_rollback=codedeploy.AutoRollbackConfig(
                failed_deployment=True,
                stopped_deployment=True,
            ),
        )

        # --- Application Auto-Scaling ---
        # Scale between 3 (minimum for high availability across 3 AZs) and 10
        # tasks. Scale-out is aggressive (30 s cooldown) to respond quickly to
        # traffic spikes; scale-in is conservative (60 s) to avoid thrashing.
        scaling = self.fargate_service.auto_scale_task_count(
            min_capacity=3,
            max_capacity=10,
        )

        scaling.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
            scale_in_cooldown=Duration.seconds(60),
            scale_out_cooldown=Duration.seconds(30),
        )

        scaling.scale_on_memory_utilization(
            "MemoryScaling",
            target_utilization_percent=80,
            scale_in_cooldown=Duration.seconds(60),
            scale_out_cooldown=Duration.seconds(30),
        )

        # --- CloudFormation Outputs ---
        CfnOutput(
            self,
            "ALBDnsName",
            value=self.alb.load_balancer_dns_name,
            description="DNS name of the Application Load Balancer",
            export_name=f"{self.stack_name}-ALBDnsName",
        )
        CfnOutput(
            self,
            "ECSServiceArn",
            value=self.fargate_service.service_arn,
            description="ARN of the ECS Fargate service",
            export_name=f"{self.stack_name}-ECSServiceArn",
        )
        CfnOutput(
            self,
            "CodeDeployAppName",
            value=self.codedeploy_app.application_name,
            description="CodeDeploy application name",
            export_name=f"{self.stack_name}-CodeDeployApp",
        )
        CfnOutput(
            self,
            "DeploymentGroupName",
            value=self.deployment_group.deployment_group_name,
            description="CodeDeploy deployment group name",
            export_name=f"{self.stack_name}-DeploymentGroup",
        )
