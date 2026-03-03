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

---

## Individual Stack Deployment

Deploy specific stacks during development or when updating a single component:

```bash
# Deploy only the API service (faster for code changes)
cdk deploy ApiStack

# Deploy only Lambda functions
cdk deploy LambdaStack

# Deploy only monitoring resources
cdk deploy MonitoringStack
```

---

## What Gets Deployed

### NetworkStack

- VPC with public and private subnets across 2 availability zones
- NAT Gateway for outbound internet access from private subnets
- Security groups for ALB, ECS tasks, RDS, and ElastiCache

### DatabaseStack

- **Aurora PostgreSQL** cluster (writer + 1 reader instance, `db.r6g.large` by default)
- **ElastiCache Redis** cluster (single node, `cache.t3.medium` by default)
- Subnet groups and parameter groups
- Automated backups (7-day retention)

### ApiStack

- **ECS Fargate** cluster
- ECS task definition (2 vCPU, 4 GB memory, configurable)
- ECS service with 2 minimum tasks, auto-scaling to 10
- **Application Load Balancer** with HTTPS listener
- AWS CodeDeploy deployment group for blue/green deployments
- IAM task role with permissions for DynamoDB, Kinesis, Secrets Manager, and Cognito

### LambdaStack

- **Assignment Lambda**: Evaluates experiment targeting and buckets users
- **Event Processor Lambda**: Processes Kinesis events, updates DynamoDB counters, indexes to OpenSearch
- **Feature Flag Evaluation Lambda**: Evaluates flag targeting and rollout percentage
- Lambda event source mapping (Kinesis → EventProcessor)

### DynamoStack

- **ExperimentCounters** DynamoDB table with on-demand billing
- Global secondary indexes for querying by experiment and metric

### StreamingStack

- **Kinesis Data Stream** (`ExperimentEvents`, 2 shards by default)
- **OpenSearch Service** domain (single-node `t3.medium.search` for development; multi-node for production)

### MonitoringStack

- CloudWatch log groups: `/experimentation-platform/api`, `/services`, `/errors`
- CloudWatch dashboards: API latency, error rates, Lambda invocations, DynamoDB throughput
- CloudWatch alarms: p99 latency, error rate, dead letter queue depth
- SNS topic for alarm notifications

### SplitUrlStack

- **CloudFront distribution** attached to the ALB origin
- **Lambda@Edge function** (deployed to `us-east-1`) for split URL experiment assignment
- Origin Access Control for S3 static assets

---

## Blue/Green Deployment for Zero-Downtime Updates

The API service uses blue/green deployment through AWS CodeDeploy. When you run `cdk deploy ApiStack` with a new image:

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
cdk diff ApiStack
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

Aurora provisioning can take 15–20 minutes. If CDK times out, check the CloudFormation console for the DatabaseStack — the deployment may still be running.

### Lambda@Edge deployment fails

Lambda@Edge functions must be deployed to `us-east-1` regardless of your primary region. The CDK construct handles this automatically, but ensure your AWS CLI is not locked to a different region via environment variables.

### "Resource handler returned message" errors

These are usually IAM or service limit errors. Check the full error message in the CloudFormation events console for details.
