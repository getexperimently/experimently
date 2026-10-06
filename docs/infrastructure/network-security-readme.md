# Network Security Configuration

The network is defined by the AWS CDK app in `infrastructure/cdk/`, and nowhere
else: the repository contains no Terraform. `infrastructure/cdk/stacks/vpc_stack.py`
(`VpcStack`, deployed as `experimentation-vpc-<env>`) creates the VPC, its subnets,
NAT gateways, VPC endpoints and network ACLs. The other stacks add their own
security groups to it. This page describes the network those stacks create; to deploy
it, see [AWS CDK Deployment](../self-hosting/cdk.md) and the
[deployment documentation](../deployment/README.md).

## Layout

One VPC, `10.0.0.0/16`, across two availability zones, with three tiers of `/24`
subnets, one subnet per tier per zone.

| Tier | CDK subnet type | Subnets | What runs there |
|------|-----------------|---------|-----------------|
| Public | `PUBLIC`, public IP on launch | `10.0.0.0/24`, `10.0.1.0/24` | The load balancer and the NAT gateways |
| Private | `PRIVATE_WITH_EGRESS` | `10.0.2.0/24`, `10.0.3.0/24` | API and dashboard tasks, the migration task, Redis, the interface endpoints; Aurora in every environment except `prod` |
| Isolated | `PRIVATE_ISOLATED` | `10.0.4.0/24`, `10.0.5.0/24` | Aurora in `prod`; nothing else |

The load balancer is the only internet-facing resource. Both ECS services run in the
private tier with no public IP address. `infrastructure/cdk/stacks/enhanced_database_stack.py`
chooses the Aurora tier by environment.

Every subnet is tagged `SubnetType` and `Name`. The VPC id, the subnet ids and
three security group ids are also written to SSM parameters under
`/experimentation/<env>/vpc/` (`id`, `public-subnet-ids`, `private-subnet-ids`,
`isolated-subnet-ids`, `app-sg-id`, `db-sg-id`, `bastion-sg-id`) and exported as
CloudFormation outputs named `<stack name>-VpcId`, `-PublicSubnets` and so on.

## NAT Gateway Setup

- Two NAT gateways in `prod`, one per availability zone, so losing a zone does not
  cut off the other zone's outbound traffic.
- One NAT gateway in every other environment.
- Each gateway has its own Elastic IP.

The count comes from `nat_gateway_count` in `infrastructure/cdk/stacks/environments.py`
and is passed to `VpcStack` by `infrastructure/cdk/app.py`. Each gateway is billed by
the hour whether or not traffic uses it.

## VPC Endpoints

`vpc_stack.py` adds six endpoints so that traffic to these AWS services stays on the
AWS network:

| Endpoint | Kind | Notes |
|----------|------|-------|
| S3 | Gateway | Route-table based, no charge |
| DynamoDB | Gateway | Route-table based, no charge |
| Secrets Manager | Interface | Private tier, private DNS on |
| ECR API | Interface | Private tier, private DNS on |
| ECR Docker | Interface | Private tier, private DNS on |
| CloudWatch Logs | Interface | Private tier, private DNS on |

Each interface endpoint has its own security group that admits TCP 443 from the VPC
CIDR and nothing else.

## Security Group Configuration

CDK writes these rules. The ones that join two stacks are written in
`infrastructure/cdk/stacks/fargate_service_stack.py`, the one stack that knows both
groups.

| Group | Defined in | Inbound | Outbound |
|-------|------------|---------|----------|
| Load balancer | `fargate_service_stack.py` (created by CDK with the load balancer) | TCP 80 and 443 from `0.0.0.0/0`; port 80 only redirects to 443 | TCP 8000 to the API task group, TCP 8080 to the dashboard group |
| API tasks (`ECSSecurityGroup`) | `compute_stack.py` | TCP 8000 from the load balancer group, written as `AlbToTasksIngress` | All |
| Dashboard tasks | `dashboard_service.py` | TCP 8080 from the load balancer group | All |
| Aurora (`RDSSecurityGroup`) | `enhanced_database_stack.py` | TCP 5432 from the API task group, written as `TasksToDatabaseIngress`; the migration task runs in the same task group | None |
| Redis (`RedisSecurityGroup`) | `elasticache_redis_stack.py` | TCP 6379 from the VPC CIDR | None |
| Interface endpoints | `vpc_stack.py` | TCP 443 from the VPC CIDR | All |

The only inbound rules open to the whole internet are the load balancer's ports 80 and
443. `infrastructure/tests/test_no_world_open_ingress.py` fails on any other. The load
balancer's extra HTTPS listener on 8443, which CodeDeploy uses to test a new version
before traffic moves, is created closed (`open=False`), so no rule admits it.

### The groups in the VPC stack

`VpcStack` also creates an application group, a database group and a bastion group
(`ApplicationSecurityGroup`, `DatabaseSecurityGroup`, `BastionSecurityGroup`). Their ids
are published to SSM and as outputs, as listed above, and they are wired to each other:
the database group admits TCP 5432 from the application and bastion groups, and the
application group admits TCP 22 from the bastion group. The bastion group has no inbound
rule unless you deploy with `-c bastion_ssh_cidr=<cidr>`, which adds SSH from that CIDR
only.

None of the other stacks attaches a resource to these three groups, and nothing in the
CDK app launches a bastion host. Aurora and the tasks use the groups in the table above.

## Network ACL Configuration

`vpc_stack.py` creates one network ACL per tier. Network ACLs are stateless, so each
direction has its own rule. The rules are coarse; the security groups above do the
narrowing.

| Tier | Inbound | Outbound |
|------|---------|----------|
| Public | All traffic from any IPv4 address (rule 100) | All traffic to any IPv4 address (rule 100) |
| Private | TCP 80 (rule 100), 443 (110) and 22 (120), and TCP 1024-65535 for return traffic and the tasks' own ports (140), all from any IPv4 address | All traffic to any IPv4 address (rule 100) |
| Isolated | TCP 5432 from `10.0.0.0/16` (rule 100) | TCP 1024-65535 to `10.0.0.0/16` (rule 100) |

The ports the private tier needs for its own traffic (8000, 8080, 6379, and 5432 where
Aurora is in the private tier) all fall in the 1024-65535 range. In `prod` Aurora is in
the isolated tier, and that ACL admits only PostgreSQL from inside the VPC.

## Changing the network

- Edit `vpc_stack.py` for the VPC, subnets, endpoints and ACLs; edit the stack that owns
  a service for that service's group. A rule between two stacks belongs in
  `fargate_service_stack.py`.
- `infrastructure/tests/test_vpc_stack.py`, `test_no_world_open_ingress.py`,
  `test_alb_egress_to_tasks.py` and `test_environments_do_not_collide.py` pin the
  pieces above. Run them with the rest of `infrastructure/tests/`.
- A CIDR change replaces the VPC and everything in it. Treat it as a migration, not an
  edit.
