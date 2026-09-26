# AWS CDK Deployment

The platform's AWS infrastructure is defined as code using **AWS CDK v2**, in **Python**: the app is `infrastructure/cdk/app.py`, and `infrastructure/cdk/cdk.json` runs it with `python3 app.py`. `cdk deploy --all` provisions the API and the data stores it needs in your AWS account.

**The dashboard is not yet deployed by the CDK.** No stack builds, stores or serves it: the Fargate stack runs the API container alone, behind the one load balancer the CDK creates. Until that lands (#69), the dashboard runs where the `frontend/Dockerfile` image runs, such as the Docker Compose stack in the [Quick Start](../getting-started/quick-start.md).

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| AWS Account | Any | [Sign up](https://aws.amazon.com/) |
| Python | 3.11+ | The CDK app is Python |
| Node.js | 18+ | Only for the CDK CLI: `node --version` |
| AWS CDK | v2 | `npm install -g aws-cdk` |
| Docker | 20+ | Required for building container images |
| AWS CLI | v2 | [Install guide](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) |

### Configure AWS CLI

```bash
aws configure
# AWS Access Key ID: your-access-key
# AWS Secret Access Key: your-secret-key
# Default region name: us-west-2
# Default output format: json
```

---

## One-Time Bootstrap

CDK bootstrap provisions the S3 bucket and IAM roles that CDK needs to deploy assets. Run this once per AWS account/region combination:

```bash
cdk bootstrap aws://YOUR_ACCOUNT_ID/YOUR_REGION

# Example
cdk bootstrap aws://123456789012/us-west-2
```

You can find your account ID with:

```bash
aws sts get-caller-identity --query Account --output text
```

---

## Required Environment Variables

`infrastructure/cdk/app.py` reads these from the environment. `cdk synth` and `cdk deploy` fail without the two marked required.

**One region.** The Deploy, Rollback and Database Migration workflows act in
`us-west-2` (`AWS_REGION` at the top of each), so deploy the stacks, the ECR
repositories, the secrets and the certificate there too. To use another region,
change it in all three workflows and use it everywhere below.

```bash
export CDK_DEFAULT_ACCOUNT=123456789012
export CDK_DEFAULT_REGION=us-west-2

# dev (the default), staging, prod or demo
export ENVIRONMENT=prod

# Required: the ACM certificate for the load balancer's HTTPS listeners
export CERTIFICATE_ARN=arn:aws:acm:us-west-2:123456789012:certificate/your-certificate-id

# Required: the absolute https:// origin users reach the platform at (one host, app.<domain>)
export PUBLIC_BASE_URL=https://app.example.com
```

The application's own secrets (database password, JWT secret and the rest) are
not read from your shell. The task definition takes them from Secrets Manager
under `/<env>/experimentation/`, and they must exist before the first deploy:
see [Secrets Management](../deployment/secrets-management.md) and the list in
the [Deployment README](../deployment/README.md). The API image is pulled from
the ECR repository `experimentation-platform/backend`, which the CDK does not
create.

---

## Deploy All Stacks

```bash
cd infrastructure/cdk
pip install -r requirements.txt
cdk deploy --all
```

CDK will display a diff of all resources to be created and prompt for confirmation. Review the output carefully before confirming.

The first full deployment takes approximately 20–40 minutes (Aurora and OpenSearch provisioning are the slowest steps).

### Which stacks you get: core or full

The CDK app deploys the stacks your checkout has, the same way the API loads
the modules it finds. A **core** checkout has no `modules/` directory and gets
the core stacks below. A **full** checkout also has
`modules/infrastructure/cdk/stacks`, and `cdk deploy --all` then adds three
more:

| Stack | Module | What it is |
|-------|--------|------------|
| `experimentation-dynamodb-counters-<env>` | `counters` | The real-time counter table the bandit scheduler reads |
| `experimentation-analytics-<env>` | `etl` | Kinesis stream, Firehose delivery, OpenSearch domain, data-lake bucket |
| `experimentation-glue-etl-<env>` | `etl` | Glue crawler and ETL jobs over the data-lake bucket |

The first line the app prints says which profile it picked:

```
[cdk] profile: full (modules/infrastructure/cdk/stacks present)
```

`EXPERIMENTLY_PROFILE` — the same variable the container images and the API
use — overrides the choice:

```bash
EXPERIMENTLY_PROFILE=core cdk deploy --all   # core stacks only, from a full checkout
EXPERIMENTLY_PROFILE=full cdk deploy --all   # fail if the module stacks are absent
```

Two things follow from the profile, so a core deployment is consistent rather
than half-configured:

- The monitoring stack's Kinesis widget and its iterator-age alarm are created
  only alongside the analytics stack, and they watch the stream that stack
  actually creates. A core deployment has neither.
- Without the `counters` stack there is no counter table: the bandit scheduler
  falls back to PostgreSQL for its statistics, which is the core behaviour.

---

## Individual Stack Deployment

Deploy specific stacks during development or when updating a single component:

`cdk deploy` takes a stack **id**, which `cdk list` prints for your
environment -- not a class name:

```bash
# Deploy only the API service (faster for code changes)
cdk deploy experimentation-fargate-dev

# Deploy only monitoring resources
cdk deploy experimentation-monitoring-dev
```

---

## What Gets Deployed

### experimentation-vpc-<env>

- VPC with public and private subnets across 2 availability zones
- NAT gateways for outbound internet access from private subnets: two in `prod` (one per availability zone), one in every other environment
- Security groups for ALB, ECS tasks, RDS, and ElastiCache

### experimentation-database-<env> and experimentation-redis-<env>

- **Aurora PostgreSQL** cluster: writer + 1 reader on `db.r5.large` for `prod`, a single `db.t3.medium` in every other environment
- **ElastiCache Redis** replication group: 3 nodes on `cache.r6g.large` for `prod`, 2 on `cache.m6g.large` for `staging`, a single `cache.t4g.medium` otherwise
- Subnet groups and parameter groups
- Redis snapshots kept 7 days in `prod`, 3 in `staging`, 1 otherwise

### experimentation-compute-<env> and experimentation-fargate-<env>

- **ECS Fargate** cluster
- ECS task definition for the API container (1 vCPU, 2 GB memory)
- ECS service with 3 tasks (`desired_count=3`), auto-scaling between 3 and 10
- **Application Load Balancer** with an HTTPS listener and an HTTP-to-HTTPS redirect, in front of the API only
- AWS CodeDeploy deployment group for blue/green deployments
- IAM task role with permissions for DynamoDB, Kinesis, Secrets Manager, and Cognito

### experimentation-dynamodb-<env> and experimentation-dynamodb-counters-<env>

- Core: the assignment, event and flag-evaluation tables
- Full profile only (the `counters` module): the **experiment-counters**
  DynamoDB table with on-demand billing and a GSI for querying by experiment

### experimentation-analytics-<env> (full profile only — the `etl` module)

- **Kinesis Data Stream** (name generated by CloudFormation; it used to be
  `exp-events-<random>`, regenerated on every synth -- see #96)
- **Firehose delivery stream** into the data-lake bucket
- **OpenSearch Service** domain (single-node `t3.medium.search` for development; multi-node for production)

### experimentation-monitoring-<env>

- CloudWatch log groups: `/experimentation-platform/api`, `/services`, `/errors`
- CloudWatch dashboards: API latency, error rates, Lambda invocations, DynamoDB throughput
- CloudWatch alarms: p99 latency, error rate, dead letter queue depth
- SNS topic for alarm notifications
- With the `etl` module: a Kinesis widget and an iterator-age alarm on that
  module's event stream. A core deployment gets neither, rather than an alarm
  on a stream that does not exist.

### What is not deployed

- **The dashboard.** The CDK does not deploy it today (#69); see the top of this page.
- **CloudFront.** No stack creates a distribution. The split-URL module ships a
  construct for one (`modules/infrastructure/constructs/split_url_distribution.py`),
  but `app.py` does not use it; see [Split URL testing](../api/split-url.md).

---

## Blue/Green Deployment for Zero-Downtime Updates

The API service uses blue/green deployment through AWS CodeDeploy. When you run `cdk deploy experimentation-fargate-<env>` with a new image:

1. CDK registers a new ECS task definition
2. CodeDeploy creates a "green" target group and starts new tasks
3. After new tasks pass health checks, CodeDeploy shifts 10% of traffic to green
4. After a 5-minute bake period, 100% of traffic shifts to green
5. Old (blue) tasks are terminated after another 5 minutes
6. If health checks fail at any step, CodeDeploy automatically shifts traffic back to blue

This process runs with zero downtime for end users.

---

## Preview Changes with cdk diff

Before deploying, preview what will change:

```bash
cdk diff experimentation-fargate-dev
```

This shows additions, modifications, and deletions. Review carefully — some changes (like modifying an Aurora parameter group) require a replacement and will cause brief downtime.

---

## Destroying an environment

Only `prod` keeps its data when its stacks are destroyed. Every other
environment (`dev`, `staging`, `demo`) is disposable: its database, tables,
buckets, stream, search domain, user pool, key and log groups are deleted with
it, so the next deploy of the same environment starts clean instead of failing
on the names the last one left behind. The rule is one line,
`retains_data(env) == (env == "prod")`, in
`infrastructure/cdk/stacks/environments.py`.

Before destroying `prod`, export anything you need that the retained resources
below do not already keep: `pg_dump` the database, export audit logs
(`GET /api/v1/compliance/export`), archive CloudWatch logs.

### Tearing an environment down

`cdk destroy --all` destroys the stacks in dependency order. By hand, the same
order is: a stack that imports from another, or depends on it, goes first --
so monitoring and the Glue stack go before analytics, and fargate before
compute.

```bash
cdk destroy experimentation-migrations-<env>
cdk destroy experimentation-fargate-<env>
cdk destroy experimentation-glue-etl-<env>
cdk destroy experimentation-monitoring-<env>
cdk destroy experimentation-analytics-<env>
cdk destroy experimentation-compute-<env>
cdk destroy experimentation-redis-<env>
cdk destroy experimentation-database-<env>
cdk destroy experimentation-dynamodb-counters-<env>
cdk destroy experimentation-dynamodb-<env>
cdk destroy experimentation-auth-<env>
cdk destroy experimentation-vpc-<env>
```

The glue, analytics and counters stacks exist only in a full checkout; skip
their lines in a core one. `infrastructure/tests/test_environments_do_not_collide.py`
checks this order against the synthesised imports and stack dependencies.

The buckets outside `prod` are emptied before they are deleted:
`auto_delete_objects=True` adds a custom resource backed by a CDK-provided
Lambda (`Custom::S3AutoDeleteObjectsCustomResourceProvider`, with its own IAM
role) that, when the stack is deleted, denies new writes to the bucket and
deletes every object version and delete marker. It acts only on a bucket
carrying the `aws-cdk:auto-delete-objects` tag, which is to say **a bucket
deployed with this version or later**. A bucket deployed before it -- by an
earlier version, whose template also said RETAIN -- is left behind by the
teardown and must be emptied and deleted by hand.

### What `cdk destroy` leaves behind and bills

Everything below survives `cdk destroy --all`. The first group is kept on
purpose, in `prod` only; the rest is created outside the stacks' templates and
is yours to remove.

| What | Where it comes from | Environments | Billed while it exists | How to remove it |
|------|---------------------|--------------|------------------------|------------------|
| The final snapshot CloudFormation takes of the Aurora cluster | the cluster's SNAPSHOT policy | prod | snapshot storage | `aws rds delete-db-cluster-snapshot` |
| KMS key (the alias is deleted) | RETAIN; the final snapshot is encrypted with it | prod | per key per month | `aws kms schedule-key-deletion` -- only after the snapshot is gone |
| Cognito user pool `experimentation-platform-users-prod` | RETAIN | prod | per monthly active user | `aws cognito-idp delete-user-pool` |
| DynamoDB tables `experimentation-{assignments,events,experiments,feature-flags,overrides}-prod`, `experiment-counters-prod` | RETAIN | prod | capacity (the core tables are provisioned in prod) and storage | `aws dynamodb delete-table` |
| Log groups `/ecs/experimentation-{backend,dashboard,migrate}-prod` | RETAIN | prod | log storage | `aws logs delete-log-group` |
| Data-lake, Athena-results and Glue-scripts buckets | RETAIN | prod (full) | storage, every object version | empty (all versions), then `aws s3 rb` |
| Kinesis stream and OpenSearch domain | RETAIN | prod (full) | per shard-hour; per instance-hour | `aws kinesis delete-stream`; `aws opensearch delete-domain` |
| `pre-migration-*` and `pre-deploy-*` Aurora cluster snapshots | taken by the deploy and migrate workflows, not by CloudFormation | every environment they ran against | snapshot storage | `aws rds delete-db-cluster-snapshot`. Outside prod the KMS key they are encrypted with is deleted with the stack, so they cannot be restored afterwards |
| The secrets under `/<env>/experimentation/` | created by hand before the first deploy ([Secrets Management](../deployment/secrets-management.md)) | every environment | per secret per month | `aws secretsmanager delete-secret` |
| ECR repositories `experimentation-platform/backend` and `experimentation-platform/web`, and their images | created by hand once per account ([Deployment Guide](../deployment/deployment-guide.md)) | shared by all environments | image storage | `aws ecr delete-repository --force`, once no environment needs them |
| The CDK bootstrap stack `CDKToolkit`: its `cdk-*-assets-<account>-<region>` bucket and `cdk-*-container-assets-*` repository | `cdk bootstrap`, once per account and region | shared by all environments | storage | `aws cloudformation delete-stack --stack-name CDKToolkit`, after emptying the bucket |
| Log groups AWS services create at run time: `/aws/lambda/<function>` for the functions without a managed log group, `/aws/ecs/containerinsights/<cluster>/performance`, `/aws-glue/*` | the services themselves, not CloudFormation | every environment | log storage | `aws logs delete-log-group` |

Two things are deleted but not immediately:

- **The database credentials secret** (`experimentation-database-<env>-aurora-credentials`)
  may be scheduled for deletion with a recovery window rather than removed. If
  the next deploy of the same environment fails with "a secret with this name is
  already scheduled for deletion", remove it with
  `aws secretsmanager delete-secret --secret-id <name> --force-delete-without-recovery`.
- **The KMS key outside prod** is scheduled for deletion after the 30-day
  waiting period, and its alias is removed at once, so it does not block a
  redeploy.

### Moving an environment deployed before the rename

This version names the ECS cluster from `ENVIRONMENT` (`experimentation-<env>`;
it was `experimentation-dev` in every environment, #142) and renames the
CodeDeploy application to `experimentation-platform-<env>` (#139). **An
environment deployed by an earlier version cannot be updated in place.** The
cluster's name is part of an export the fargate stack imports, and
CloudFormation refuses to change an export another stack is using, so
`cdk deploy --all` fails on the compute stack.

The fargate stack is the only importer of that export -- the analytics stack
imports nothing from compute and is not touched. So, for each environment
deployed before this change:

```bash
cdk destroy --exclusively experimentation-fargate-<env>
aws logs delete-log-group --log-group-name /ecs/experimentation-backend-<env>
aws logs delete-log-group --log-group-name /ecs/experimentation-dashboard-<env>
cdk deploy experimentation-compute-<env>
cdk deploy experimentation-fargate-<env>
cdk deploy --all
```

- `--exclusively` matters: without it the CDK CLI also destroys the stacks that
  depend on fargate, which is the migrations stack.
- The two `delete-log-group` lines are needed because the earlier version's
  template retained those log groups, and the destroy follows the template that
  is deployed, not this one. A recreated fargate stack would otherwise fail on
  the names. Skip the dashboard line if that log group does not exist.
- Destroying fargate stops the API and the dashboard until the last step
  finishes; the database, Redis and the data stores are not touched.
- `infrastructure/tests/test_environments_do_not_collide.py` derives the list
  of stacks to destroy from the synthesised import graph and checks it against
  the commands above.

---

## Estimated AWS Costs

Costs depend heavily on traffic volume and configuration. The following is a rough estimate for a small production deployment:

The instance types below are what the CDK actually deploys with
`environment=prod`, not a suggested sizing — read them out of
`enhanced_database_stack.py`, `elasticache_redis_stack.py` and
`fargate_service_stack.py` if you change them.

| Service | What the stack deploys | Estimated Monthly Cost |
|---------|------------------------|----------------------|
| Aurora PostgreSQL | `db.r5.large` (`MEMORY5`/`LARGE`), 2 instances — writer + reader | ~$300 |
| ElastiCache Redis | `cache.r6g.large` | ~$150 |
| ECS Fargate | 3 tasks (`desired_count=3`, autoscaling 3–10), 1 vCPU / 2 GB each, 24/7 | ~$110 |
| Lambda invocations | 1M events/month | ~$5 |
| Kinesis | 2 shards | ~$30 |
| OpenSearch | `t3.medium.search` | ~$60 |
| ALB | one | ~$25 |
| **Total estimate** | | **~$680/month** |

Autoscaling is the figure to watch: Fargate is costed at the floor of three
tasks. At the ceiling of ten it is roughly $370 rather than $110, so a
sustained-load month lands nearer $940.

For development/staging environments, you can significantly reduce costs by:
- Non-prod environments already size down on their own: the CDK picks a
  smaller Aurora instance, `cache.t4g.medium` for dev/test
  (`cache.m6g.large` for staging), a single Aurora instance rather than a
  writer/reader pair, and one NAT gateway rather than two
- Reducing Aurora to a single instance (disable the reader)
- Using on-demand Lambda scaling instead of reserved capacity

---

## Troubleshooting Common Deployment Issues

### "Stack already exists" error

If a stack was partially created, you may need to delete it from the AWS CloudFormation console before redeploying.

### Aurora takes too long / times out

Aurora provisioning can take 15–20 minutes. If CDK times out, check the CloudFormation console for `experimentation-database-<env>` — the deployment may still be running.

### "Resource handler returned message" errors

These are usually IAM or service limit errors. Check the full error message in the CloudFormation events console for details.
