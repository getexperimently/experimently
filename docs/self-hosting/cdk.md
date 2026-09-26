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
# Default region name: us-east-1
# Default output format: json
```

---

## One-Time Bootstrap

CDK bootstrap provisions the S3 bucket and IAM roles that CDK needs to deploy assets. Run this once per AWS account/region combination:

```bash
cdk bootstrap aws://YOUR_ACCOUNT_ID/YOUR_REGION

# Example
cdk bootstrap aws://123456789012/us-east-1
```

You can find your account ID with:

```bash
aws sts get-caller-identity --query Account --output text
```

---

## Required Environment Variables

`infrastructure/cdk/app.py` reads these from the environment. `cdk synth` and `cdk deploy` fail without the two marked required:

```bash
export CDK_DEFAULT_ACCOUNT=123456789012
export CDK_DEFAULT_REGION=us-east-1

# dev (the default), staging, prod or demo
export ENVIRONMENT=prod

# Required: the ACM certificate for the load balancer's HTTPS listeners
export CERTIFICATE_ARN=arn:aws:acm:us-east-1:123456789012:certificate/your-certificate-id

# Required: the absolute https:// origin users reach the API at
export PUBLIC_BASE_URL=https://api.example.com
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
- Two NAT Gateways (one per availability zone) for outbound internet access from private subnets
- Security groups for ALB, ECS tasks, RDS, and ElastiCache

### experimentation-database-<env> and experimentation-redis-<env>

- **Aurora PostgreSQL** cluster: writer + 1 reader on `db.r5.large` for `prod`, writer + 1 reader on `db.t3.medium` for `staging`, a single `db.t3.medium` otherwise
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

## Destroy All Resources

To tear down the entire environment:

```bash
cdk destroy --all
```

**Warning**: This action is irreversible and will delete:
- The Aurora PostgreSQL database and all stored data
- All S3 bucket contents
- All CloudWatch logs

Before destroying, export any data you need to retain:
- Dump the database: `pg_dump`
- Export audit logs: `GET /api/v1/compliance/export`
- Archive CloudWatch logs

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
  (`cache.m6g.large` for staging) and, outside `prod` and `staging`, a
  single Aurora instance rather than a writer/reader pair
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
