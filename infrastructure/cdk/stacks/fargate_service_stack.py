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
      constructor. Without it this stack refuses to build -- at ``cdk synth``,
      not at deploy, which is what this note used to say: both listeners are
      HTTPS and CDK validates that at the end of synthesis. A synth-only check
      may pass any well-formed ARN; nothing resolves it until a deployment.
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
            iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchLogsFullAccess")
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

        # --- The image this task definition carries ---------------------------
        # The pipeline owns what actually runs.
        # `.github/workflows/deploy-prod.yml` reads the task definition the
        # service is *currently running*, rewrites the backend container's
        # image to the one it just built, registers that as a new revision and
        # hands it to CodeDeploy. CloudFormation never gets to choose: ECS
        # refuses a task-definition change on a service with a CODE_DEPLOY
        # controller outright -- "Unable to update task definition on services
        # with a CODE_DEPLOY deployment controller".
        #
        # So the tag below is a *bootstrap* image: the one thing that has to
        # exist before an environment can be stood up at all, because
        # CloudFormation cannot create an ECS service without a task
        # definition, and a task definition cannot name no image.
        #
        # It is deliberately not `latest`, and the reason is narrower than it
        # first looks -- this comment was rewritten after reading the ECS API
        # model rather than reasoning from the template.
        #
        # What is NOT true: that a `cdk deploy` can roll the running service
        # back. ECS refuses a task-definition change through `UpdateService`
        # on a CODE_DEPLOY service, and CodeDeploy deployments name a revision
        # ARN outright, so nothing here decides what serves traffic.
        #
        # What IS true: this revision is the one `Service.taskDefinition`
        # keeps pointing at forever. That field is "specified when the service
        # is created with CreateService, and it can be modified with
        # UpdateService" -- and UpdateService is the call just ruled out -- so
        # for the life of the service it names the revision CloudFormation
        # created, not the one serving traffic (that is
        # `taskSets[?status=='PRIMARY'].taskDefinition`). Anything that reads
        # the service to find "the current task definition" therefore lands
        # here.
        #
        # `:latest` made that a live image: the deploy workflow moves the tag
        # on every build, including builds that failed verification or were
        # rolled back, so the revision everyone mistakes for current pointed
        # at an arbitrary later build. A tag the pipeline never writes cannot
        # drift, so the mistake becomes visible instead of plausible.
        #
        # `-c backend_image_tag=<tag>` overrides it, for pinning a `cdk deploy`
        # on a running environment to the image already in service.
        #
        # migration_task_stack.py keeps `latest` deliberately, for the opposite
        # reason: the deploy workflow pushes `:latest` and runs that task
        # within the same job, so there it means "the image being deployed".
        image_tag = self.node.try_get_context("backend_image_tag")
        if image_tag is None:
            image_tag = "bootstrap"
        if not isinstance(image_tag, str) or not image_tag.strip():
            # `-c backend_image_tag=` supplies "", and cdk.json can supply a
            # number. Both used to fall through an `or` to "bootstrap", so an
            # operator who thought they had pinned production got the drifted
            # revision they were trying to avoid, silently.
            raise ValueError(
                "backend_image_tag context must be a non-empty string; got "
                f"{image_tag!r}"
            )
        if image_tag == "latest":
            raise ValueError(
                "backend_image_tag must not be `latest`: the deploy workflow "
                "moves that tag on every build, which is #82"
            )
        self.backend_image_tag = image_tag

        # --- ECS Task Definition ---
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "BackendTaskDef",
            family=f"experimentation-backend-{env_name}",
            cpu=1024,  # 1 vCPU
            memory_limit_mib=2048,  # 2 GB
            task_role=task_role,
            execution_role=execution_role,
        )

        self.container = self.task_definition.add_container(
            "backend",
            image=ecs.ContainerImage.from_ecr_repository(
                self.ecr_repo, tag=self.backend_image_tag
            ),
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
                    {"AUDIT_HMAC_KEY": ecs.Secret.from_secrets_manager(audit_secret)}
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
        # An ACM certificate ARN is required. Provision one via AWS Certificate
        # Manager and pass it as the `certificate_arn` constructor parameter or
        # the CERTIFICATE_ARN environment variable; the format is
        # `arn:aws:acm:<region>:<account>:certificate/<uuid>`.
        #
        # Required at SYNTH, not at deploy -- which is what the note here used
        # to say. Both listeners below are HTTPS, and CDK validates at the end
        # of synthesis that an HTTPS listener has a certificate:
        #
        #   ValidationFailedWithErrors: [.../HttpsListener] HTTPS Listener
        #   needs at least one certificate (call addCertificates)
        #
        # So `cdk synth` fails without one, and the guard below says that in
        # those words rather than leaving the reader to map CDK's message back
        # to a missing environment variable. A synth-only check (CI) can pass
        # any well-formed ARN: nothing resolves it until deploy.
        #
        # Deliberately NOT falling back to an HTTP listener when the ARN is
        # absent. That would make `cdk synth` succeed and hand anyone who
        # forgot the variable a load balancer that terminates in plaintext --
        # trading a loud failure for a quiet downgrade, on the public edge of
        # the platform.
        if not certificate_arn:
            raise ValueError(
                "FargateServiceStack requires an ACM certificate: set the "
                "CERTIFICATE_ARN environment variable (or pass certificate_arn) "
                "to an arn:aws:acm:<region>:<account>:certificate/<uuid>. Both "
                "the production and the CodeDeploy test listener are HTTPS, and "
                "cdk synth fails validation without one."
            )

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
            # Imported immutably, and this is the whole fix for the dependency
            # cycle. Passing the ComputeStack's SecurityGroup *object* here
            # made `attach_to_application_target_group` below reach back into
            # it: CDK's ApplicationListener.registerConnectable calls
            # `connections.allowFrom(loadBalancer, ...)`, and
            # `determineRuleScope` puts BOTH halves of the rule pair under the
            # initiating security group -- the ECS one, in the compute stack --
            # each referencing the ALB's security group, which lives here. That
            # is compute -> fargate, against the fargate -> compute dependency
            # app.py already declares, and `cdk synth` has refused to complete
            # since EP-019 first added this stack.
            #
            # `mutable=False` makes CDK decline to write rules onto the
            # imported group; the rule it would have written is created
            # explicitly below, in this stack, where it belongs.
            security_groups=[
                ec2.SecurityGroup.from_security_group_id(
                    self,
                    "ImportedEcsSecurityGroup",
                    ecs_security_group.security_group_id,
                    mutable=False,
                )
            ],
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
        self.fargate_service.attach_to_application_target_group(self.blue_target_group)

        # The ingress CDK would have added implicitly, written explicitly and on
        # this side of the stack boundary. With the security group imported
        # `mutable=False` above, CDK silently declines to create this rule --
        # no warning, no annotation -- and the service would still be reachable
        # only because `compute_stack.py` opens 0.0.0.0/0 on 8000. That is a
        # rule nobody should rely on, and tightening it later would take the
        # load balancer down with it. So the real rule is stated here: this ALB,
        # to the task port, and nothing else.
        ec2.CfnSecurityGroupIngress(
            self,
            "AlbToTasksIngress",
            group_id=ecs_security_group.security_group_id,
            ip_protocol="tcp",
            from_port=8000,
            to_port=8000,
            source_security_group_id=self.alb.connections.security_groups[
                0
            ].security_group_id,
            description="Load balancer to target",
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
