# AWS CDK Deployment

The entire platform infrastructure is defined as code using **AWS CDK v2** (TypeScript). A single `cdk deploy --all` command provisions everything needed to run the platform in your AWS account.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| AWS Account | Any | [Sign up](https://aws.amazon.com/) |
| Node.js | 18+ | `node --version` |
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

Set these before deploying. They are passed as CDK context variables or environment variables:

```bash
export CDK_DEFAULT_ACCOUNT=123456789012
export CDK_DEFAULT_REGION=us-east-1

# Application configuration
export POSTGRES_PASSWORD=your-secure-db-password
export SECRET_KEY=your-32-char-minimum-secret-key
export COGNITO_USER_POOL_ID=us-east-1_xxxxxxxxx
export COGNITO_CLIENT_ID=your-cognito-client-id

# Optional alerting
export SLACK_BOT_TOKEN=xoxb-your-slack-token
export SENDGRID_API_KEY=SG.your-sendgrid-key
export ANTHROPIC_API_KEY=sk-ant-your-key
```

---

## Deploy All Stacks

```bash
cd infrastructure
npm install
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
- NAT Gateway for outbound internet access from private subnets
- Security groups for ALB, ECS tasks, RDS, and ElastiCache

### experimentation-database-<env> and experimentation-redis-<env>

- **Aurora PostgreSQL** cluster (writer + 1 reader instance, `db.r6g.large` by default)
- **ElastiCache Redis** cluster (single node, `cache.t3.medium` by default)
- Subnet groups and parameter groups
- Automated backups (7-day retention)

### experimentation-compute-<env> and experimentation-fargate-<env>

- **ECS Fargate** cluster
- ECS task definition (2 vCPU, 4 GB memory, configurable)
- ECS service with 2 minimum tasks, auto-scaling to 10
- **Application Load Balancer** with HTTPS listener
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

| Service | Estimated Monthly Cost |
|---------|----------------------|
| Aurora PostgreSQL (db.r6g.large writer + reader) | ~$300 |
| ElastiCache Redis (cache.t3.medium) | ~$50 |
| ECS Fargate (2 tasks, 2 vCPU / 4 GB each, 24/7) | ~$150 |
| Lambda invocations (1M events/month) | ~$5 |
| Kinesis (2 shards) | ~$30 |
| OpenSearch (t3.medium.search) | ~$60 |
| CloudFront + Lambda@Edge | ~$20–50 depending on traffic |
| ALB | ~$25 |
| **Total estimate** | **~$640–700/month** |

For development/staging environments, you can significantly reduce costs by:
- Using smaller instance types (`db.t3.medium`, `cache.t3.micro`)
- Reducing Aurora to a single instance (disable the reader)
- Using on-demand Lambda scaling instead of reserved capacity

---

## Troubleshooting Common Deployment Issues

### "Stack already exists" error

If a stack was partially created, you may need to delete it from the AWS CloudFormation console before redeploying.

### Aurora takes too long / times out

Aurora provisioning can take 15–20 minutes. If CDK times out, check the CloudFormation console for `experimentation-database-<env>` — the deployment may still be running.

### Lambda@Edge deployment fails

Lambda@Edge functions must be deployed to `us-east-1` regardless of your primary region. The CDK construct handles this automatically, but ensure your AWS CLI is not locked to a different region via environment variables.

### "Resource handler returned message" errors

These are usually IAM or service limit errors. Check the full error message in the CloudFormation events console for details.
