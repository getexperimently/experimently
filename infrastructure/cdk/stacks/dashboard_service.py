"""The dashboard as its own ECS service behind the API's load balancer (#69).

One public origin (DECISIONS D5, D14): the ALB's HTTPS listener sends `/api/*`
and the API's four root routes to the API's live target group, and everything
else -- its default action -- to this service. The dashboard image is
`frontend/Dockerfile`: a static Next.js export served by unprivileged nginx on
port 8080.

Kept in its own module rather than inline in `fargate_service_stack.py`
because `backend/tests/unit/infrastructure/test_deployment_secrets.py` reads
the API container out of that file by taking its `add_container(...)` call; a
second call there would make which container it reads depend on AST order.

What this service deliberately is NOT:

* **Not a CodeDeploy service.** ECS rolling deployment with the deployment
  circuit breaker (rollback on). It serves static files; a second blue/green
  pair and deployment group would buy nothing for it.
* **Not a proxy for the API.** The image's nginx proxies `/api/` to
  `API_UPSTREAM` (default `http://api:8000`, a compose service name). In AWS
  the ALB owns `/api`, so `API_UPSTREAM` is `http://127.0.0.1:1`: a request
  that reaches this nginx for `/api` gets a 502 rather than being forwarded
  somewhere. The default would not merely be wrong here -- nginx refuses to
  start when the upstream host does not resolve (principal-engineer, measured
  on nginx-unprivileged:1.29-alpine: `[emerg] host not found in upstream`).
* **Not the owner of its repository.** Imported by name, like the backend's
  (see `stacks/names.py`).
"""

from __future__ import annotations

from aws_cdk import Duration
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_logs as logs
from constructs import Construct

from stacks.environments import data_removal_policy
from stacks.names import DASHBOARD_ECR_REPOSITORY

#: The port the dashboard image's nginx listens on (`frontend/nginx.conf`,
#: `listen 8080`; the image runs as the unprivileged `nginx` user).
DASHBOARD_PORT = 8080

#: `http://127.0.0.1:1`: nothing listens there, so nginx starts (the host is
#: an address, not a name to resolve) and any `/api` request that reaches it
#: fails with 502 instead of being proxied.
API_UPSTREAM_NOWHERE = "http://127.0.0.1:1"


def dashboard_image_tag(scope: Construct) -> str:
    """The `dashboard_image_tag` context value, default `bootstrap`.

    Refused: `latest` (the deploy workflow's moving tag, #82), and an empty or
    non-string value -- `-c dashboard_image_tag=` supplies "" and `cdk.json`
    can supply a number, and either silently falling back to `bootstrap`
    would pin nothing while looking pinned. The same rules as
    `backend_image_tag` in `fargate_service_stack.py`.
    """
    tag = scope.node.try_get_context("dashboard_image_tag")
    if tag is None:
        return "bootstrap"
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError(
            f"dashboard_image_tag context must be a non-empty string; got {tag!r}"
        )
    if tag == "latest":
        raise ValueError(
            "dashboard_image_tag must not be `latest`: the deploy workflow "
            "moves that tag on every build, which is #82"
        )
    return tag


class DashboardService(Construct):
    """Task definition, security group, target group and ECS service."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        cluster: ecs.ICluster,
        env_name: str,
        desired_count: int,
    ) -> None:
        super().__init__(scope, construct_id)

        if not isinstance(desired_count, int) or desired_count < 1:
            raise ValueError(
                f"the dashboard needs at least one task; got {desired_count!r}"
            )

        repository = ecr.Repository.from_repository_name(
            self, "Repository", repository_name=DASHBOARD_ECR_REPOSITORY
        )

        log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name=f"/ecs/experimentation-dashboard-{env_name}",
            retention=logs.RetentionDays.THREE_MONTHS,
            # Named: kept in prod only (stacks/environments.py), so a rebuilt
            # staging does not collide with its predecessor's log group.
            removal_policy=data_removal_policy(env_name),
        )

        # 0.25 vCPU / 0.5 GB: the smallest Fargate size, for static nginx.
        self.task_definition = ecs.FargateTaskDefinition(
            self,
            "TaskDef",
            family=f"experimentation-dashboard-{env_name}",
            cpu=256,
            memory_limit_mib=512,
        )
        container = self.task_definition.add_container(
            "dashboard",
            image=ecs.ContainerImage.from_ecr_repository(
                repository, tag=dashboard_image_tag(self)
            ),
            logging=ecs.LogDrivers.aws_logs(
                stream_prefix="dashboard", log_group=log_group
            ),
            environment={"API_UPSTREAM": API_UPSTREAM_NOWHERE},
            # ECS ignores the Dockerfile's HEALTHCHECK; this is the same probe.
            # busybox wget is in the nginx-unprivileged alpine base.
            health_check=ecs.HealthCheck(
                command=[
                    "CMD-SHELL",
                    f"wget -qO- http://127.0.0.1:{DASHBOARD_PORT}/healthz "
                    ">/dev/null 2>&1 || exit 1",
                ],
                interval=Duration.seconds(15),
                timeout=Duration.seconds(5),
                retries=3,
                start_period=Duration.seconds(10),
            ),
            essential=True,
        )
        container.add_port_mappings(
            ecs.PortMapping(container_port=DASHBOARD_PORT, protocol=ecs.Protocol.TCP)
        )

        # Its own group, in this stack. The service's only way in is the
        # load balancer: attaching it to the target group below makes CDK
        # write the pair of rules -- ingress on this group from the ALB's
        # group, egress on the ALB's group to this one, both tcp 8080 -- and
        # the synth tests pin both halves.
        self.security_group = ec2.SecurityGroup(
            self,
            "SecurityGroup",
            vpc=vpc,
            description="Dashboard tasks: reachable only from the load balancer",
            # Image pulls (ECR endpoints) and logs go out on 443.
            allow_all_outbound=True,
        )

        self.target_group = elbv2.ApplicationTargetGroup(
            self,
            "TargetGroup",
            vpc=vpc,
            port=DASHBOARD_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(
                path="/healthz",
                interval=Duration.seconds(30),
                timeout=Duration.seconds(5),
                healthy_threshold_count=2,
                unhealthy_threshold_count=3,
                healthy_http_codes="200",
            ),
            deregistration_delay=Duration.seconds(30),
        )

        self.service = ecs.FargateService(
            self,
            "Service",
            service_name=f"experimentation-dashboard-{env_name}",
            cluster=cluster,
            task_definition=self.task_definition,
            desired_count=desired_count,
            # With one task (staging, D13) a rolling deploy starts the new
            # task before stopping the old one: no gap.
            min_healthy_percent=100,
            max_healthy_percent=200,
            deployment_controller=ecs.DeploymentController(
                type=ecs.DeploymentControllerType.ECS
            ),
            circuit_breaker=ecs.DeploymentCircuitBreaker(enable=True, rollback=True),
            security_groups=[self.security_group],
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            assign_public_ip=False,
            health_check_grace_period=Duration.seconds(30),
        )
        self.service.attach_to_application_target_group(self.target_group)
