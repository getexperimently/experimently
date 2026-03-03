# AWS Integration

The platform is designed to run natively on AWS. This document describes how each AWS service is used and how to configure the integration.

---

## ECS Fargate

The FastAPI application runs on **Amazon ECS Fargate** — a serverless container execution environment that removes the need to manage EC2 instances.

### Deployment Architecture

- The Fargate service runs multiple task replicas behind an Application Load Balancer (ALB)
- Task health is monitored via the `/health` endpoint; unhealthy tasks are automatically replaced
- Horizontal scaling is configured via ECS service auto-scaling based on CPU and memory utilization

### Blue/Green Deployments

The platform uses **AWS CodeDeploy** for zero-downtime blue/green deployments:

1. A new task definition is registered with the updated container image
2. CodeDeploy creates a "green" target group and shifts 10% of traffic to it
3. After a configurable bake time (default 5 minutes), full traffic is shifted to green
4. If health checks fail at any stage, traffic shifts back to the blue target group automatically

To deploy a new version:

```bash
# Build and push the Docker image
docker build -t your-account.dkr.ecr.region.amazonaws.com/experimentation-api:latest .
docker push your-account.dkr.ecr.region.amazonaws.com/experimentation-api:latest

# Deploy via CDK (re-deploys the ECS service with the new image)
cd infrastructure && cdk deploy ApiStack
```

### Environment Variables

The ECS task reads configuration from AWS Secrets Manager at startup. Set the following as ECS task environment variables or Secrets Manager references:

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Aurora PostgreSQL connection string |
| `REDIS_URL` | ElastiCache Redis URL |
| `SECRET_KEY` | Application secret key (min 32 chars) |
| `COGNITO_USER_POOL_ID` | AWS Cognito User Pool ID |
| `COGNITO_CLIENT_ID` | Cognito app client ID |
| `AWS_REGION` | AWS region for DynamoDB and Kinesis calls |

---

## Aurora PostgreSQL

**Amazon Aurora PostgreSQL** is the primary relational database, storing all experiments, feature flags, users, results, and audit data.

### Connection Configuration

```bash
# Environment variable format
DATABASE_URL=postgresql://username:password@aurora-cluster.cluster-xxxx.region.rds.amazonaws.com:5432/experimentation
```

### Read Replicas

Aurora automatically maintains a read replica. To direct read-heavy queries to the replica, set:

```bash
DATABASE_REPLICA_URL=postgresql://username:password@aurora-cluster.cluster-ro-xxxx.region.rds.amazonaws.com:5432/experimentation
```

The API uses the replica URL for read-only queries (results pages, audit log reads) to reduce load on the primary.

### Connection Pooling

The application uses SQLAlchemy with a connection pool. For production, configure:

```bash
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=10
DATABASE_POOL_TIMEOUT=30
```

---

## ElastiCache Redis

**Amazon ElastiCache for Redis** provides two functions:

### Session Storage

User JWT sessions are stored in Redis with a TTL matching the token expiry time. This allows the API service to scale horizontally without sticky sessions — any task can validate any user's session.

```bash
REDIS_URL=redis://your-cluster.xxxxx.0001.use1.cache.amazonaws.com:6379
```

### Application Cache

Feature flag configurations and experiment assignments are cached in Redis. The default TTL is 60 seconds. Changes to flags and experiments propagate to all users within one cache cycle.

```bash
REDIS_CACHE_TTL=60           # Cache TTL in seconds
REDIS_CACHE_MAX_SIZE=10000   # Max items in cache
```

---

## DynamoDB

**Amazon DynamoDB** stores real-time impression and conversion counters using atomic `ADD` operations. This allows thousands of concurrent Lambda invocations to increment counters without database contention.

### Table Structure

| Table | Partition Key | Sort Key | Purpose |
|-------|--------------|----------|---------|
| `ExperimentCounters` | `experiment_id` | `variant_id#metric_key` | Per-variant metric counts |

### Atomic Increment

The Event Processor Lambda uses the DynamoDB `UpdateItem` with `SET #counter = if_not_exists(#counter, :zero) + :increment` to safely increment counters from concurrent invocations.

### Configuration

```bash
DYNAMODB_TABLE_NAME=ExperimentCounters
DYNAMODB_REGION=us-east-1
```

---

## Lambda Functions

Three Lambda functions handle high-throughput operations. They are deployed in the same AWS region as the API service.

### Experiment Assignment Lambda

- **Trigger**: Direct invocation from SDK clients
- **Function**: Evaluates targeting rules, performs consistent-hash bucketing, returns variant assignment
- **Environment variables**: `EXPERIMENTATION_API_URL`, `DYNAMODB_TABLE_NAME`

### Event Processor Lambda

- **Trigger**: Kinesis Data Stream (`ExperimentEvents`)
- **Function**: Validates events, updates DynamoDB counters, indexes events in OpenSearch
- **Batch size**: 100 records per invocation (configurable)
- **Bisect on error**: Enabled — failed batches are split to isolate bad records

### Feature Flag Evaluation Lambda

- **Trigger**: Direct invocation from SDK clients
- **Function**: Evaluates feature flag targeting rules and rollout percentage
- **Cache**: In-memory LRU cache (TTL 60s, max 1000 entries) to reduce API calls

### Lambda Environment Variables

```bash
EXPERIMENTATION_API_URL=https://your-api.example.com
EXPERIMENTATION_API_KEY=your-internal-key
DYNAMODB_TABLE_NAME=ExperimentCounters
OPENSEARCH_ENDPOINT=https://your-domain.es.amazonaws.com
```

---

## CloudFront and Lambda@Edge

**Amazon CloudFront** serves as the CDN for static frontend assets and as the execution layer for split URL experiments via Lambda@Edge.

### Static Asset Distribution

The Next.js frontend build output is hosted in an S3 bucket and served through CloudFront with long-lived cache headers for hashed assets and short TTLs for HTML.

### Lambda@Edge for Split URL Testing

For split URL experiments, a Lambda@Edge function is attached to the CloudFront distribution's `viewer-request` event:

1. Reads the assignment cookie (`exp_{experiment_key}`)
2. If absent, hashes the user ID to assign a variant
3. Returns a `302 Found` redirect to the variant URL
4. Sets a 1-year `Set-Cookie` header for assignment persistence

Lambda@Edge functions must be deployed to `us-east-1` (a CloudFront requirement) and are globally replicated to all edge locations.

```typescript
// CDK construct usage (infrastructure/app.ts)
import { SplitUrlDistribution } from './constructs/SplitUrlDistribution';

new SplitUrlDistribution(this, 'CheckoutSplitUrl', {
  experimentKey: 'checkout-flow-v2',
  originDomainName: alb.loadBalancerDnsName,
  experimentationApiUrl: 'https://your-api.example.com',
  experimentationApiKey: apiKeySecret.secretValue.toString(),
});
```

---

## Kinesis and OpenSearch

### Kinesis Data Stream

Raw tracking events (impressions and conversions) are published to a **Kinesis Data Stream** (`ExperimentEvents`). This decouples event ingestion from processing and buffers traffic spikes.

```bash
KINESIS_STREAM_NAME=ExperimentEvents
KINESIS_REGION=us-east-1
```

### OpenSearch

The Event Processor Lambda indexes processed events into **Amazon OpenSearch Service** for ad-hoc queries, dimensional analysis, and segment breakdowns.

```bash
OPENSEARCH_ENDPOINT=https://your-domain.us-east-1.es.amazonaws.com
OPENSEARCH_INDEX_PREFIX=experimentation-events
```

---

## CDK Deployment

All infrastructure is defined in `infrastructure/` using AWS CDK v2 (TypeScript).

### Prerequisites

- AWS account with appropriate IAM permissions
- Node.js 18+
- AWS CDK v2: `npm install -g aws-cdk`
- AWS CLI configured: `aws configure`

### Deploy

```bash
# One-time bootstrap (per account/region)
cd infrastructure
cdk bootstrap aws://YOUR_ACCOUNT_ID/YOUR_REGION

# Deploy all stacks
cdk deploy --all

# Deploy a specific stack
cdk deploy ApiStack
```

### Stacks Deployed

| Stack | Resources |
|-------|-----------|
| `NetworkStack` | VPC, subnets, NAT gateways, security groups |
| `DatabaseStack` | Aurora cluster, ElastiCache cluster, subnet groups |
| `ApiStack` | ECS cluster, Fargate service, ALB, IAM roles |
| `LambdaStack` | Assignment, EventProcessor, FeatureFlagEvaluation Lambda functions |
| `DynamoStack` | DynamoDB table for counters |
| `StreamingStack` | Kinesis stream, OpenSearch domain |
| `MonitoringStack` | CloudWatch dashboards, alarms, log groups |
| `SplitUrlStack` | CloudFront distribution, Lambda@Edge |

---

## Required IAM Permissions

The ECS task role and Lambda execution roles need the following permissions:

### ECS Task Role

```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:GetItem",
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:Query",
    "kinesis:PutRecord",
    "kinesis:PutRecords",
    "secretsmanager:GetSecretValue",
    "cognito-idp:AdminGetUser",
    "cognito-idp:ListUsers"
  ],
  "Resource": "*"
}
```

### Lambda Execution Role (Event Processor)

```json
{
  "Effect": "Allow",
  "Action": [
    "dynamodb:UpdateItem",
    "kinesis:GetRecords",
    "kinesis:GetShardIterator",
    "kinesis:DescribeStream",
    "kinesis:ListShards",
    "es:ESHttpPost",
    "es:ESHttpPut"
  ],
  "Resource": "*"
}
```

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | Aurora PostgreSQL connection string |
| `REDIS_URL` | Yes | ElastiCache Redis URL |
| `SECRET_KEY` | Yes | Application secret key (min 32 chars) |
| `COGNITO_USER_POOL_ID` | Yes | AWS Cognito User Pool ID |
| `COGNITO_CLIENT_ID` | Yes | Cognito app client ID |
| `AWS_REGION` | Yes | Primary AWS region |
| `DYNAMODB_TABLE_NAME` | Yes | DynamoDB table name for counters |
| `KINESIS_STREAM_NAME` | Yes | Kinesis stream name for events |
| `OPENSEARCH_ENDPOINT` | Yes | OpenSearch domain endpoint |
| `SLACK_BOT_TOKEN` | No | Slack bot token for alerting |
| `SENDGRID_API_KEY` | No | SendGrid API key for email alerts |
| `AUDIT_HMAC_SECRET` | Yes | Secret for HMAC-SHA256 audit event signing |
| `ANTHROPIC_API_KEY` | No | Claude API key for AI experiment design |
