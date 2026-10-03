# AWS Integration

Experimently works with AWS. This document describes how each AWS service is used and how to configure the integration.

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
2. CodeDeploy starts the new tasks in the idle target group; the Deploy workflow approves the shift once every one is healthy
3. The canary shifts 10% of traffic, waits 5 minutes, then shifts the rest
4. Two 5xx alarms, one per target group, watch the API through the canary and the hour after it: while either is in ALARM, CodeDeploy stops the deployment and rolls the API back by itself. They watch the API's target 5xx only, so a release that answers wrongly with a 2xx is not caught, and after that hour the [Rollback workflow](../deployment/rollback-runbook.md) is the response to a bad release

To deploy a new version, run **Actions → Deploy** with a release tag
([deployment guide, section 3](../deployment/deployment-guide.md#3-every-deploy)).
The API's revision moves through CodeDeploy, not through `cdk deploy`: the
service has a CODE_DEPLOY deployment controller, and ECS refuses a
task-definition change through UpdateService on such a service.

### Environment Variables

The ECS task reads configuration from AWS Secrets Manager at startup. Set the following as ECS task environment variables or Secrets Manager references:

| Variable | Description |
|----------|-------------|
| `POSTGRES_SERVER` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Aurora PostgreSQL connection (the image does not read `DATABASE_URL`) |
| `REDIS_HOST` / `REDIS_PORT` | ElastiCache primary endpoint and port (from the Redis stack) |
| `REDIS_SSL` | `true` on AWS: the replication group requires TLS |
| `SECRET_KEY` | Application secret key (min 32 chars) |
| `COGNITO_USER_POOL_ID` | AWS Cognito User Pool ID |
| `COGNITO_CLIENT_ID` | Cognito app client ID |
| `AWS_REGION` | AWS region for DynamoDB and Kinesis calls |

---

## Aurora PostgreSQL

**Amazon Aurora PostgreSQL** is the primary relational database, storing all experiments, feature flags, users, results, and audit data.

### Connection Configuration

The API connects with the `POSTGRES_*` variables, not a `DATABASE_URL`:

```bash
POSTGRES_SERVER=aurora-cluster.cluster-xxxx.region.rds.amazonaws.com
POSTGRES_PORT=5432
POSTGRES_USER=username
POSTGRES_PASSWORD=password
POSTGRES_DB=experimentation
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

`REDIS_HOST` is the cluster's primary endpoint. `REDIS_SSL` is `true` because
in-transit encryption is on, and a plaintext client is refused.

```bash
REDIS_HOST=master.your-cluster.xxxxx.use1.cache.amazonaws.com
REDIS_PORT=6379
REDIS_SSL=true
```

### Application Cache

Experiment assignments are cached in Redis. The default TTL is 60 seconds, and changes to experiments propagate to all users within one cache cycle. The API does not cache feature flags: it reads them from the database on every request, so a flag change is served on the next one.

`REDIS_CACHE_TTL` is the cache TTL in seconds, and `REDIS_CACHE_MAX_SIZE` the
maximum number of items in the cache:

```bash
REDIS_CACHE_TTL=60
REDIS_CACHE_MAX_SIZE=10000
```

---

## DynamoDB

The `counters` module (full profile) keeps real-time assignment, event and conversion counters
in **Amazon DynamoDB**, and increments them with atomic `ADD` update expressions so that
concurrent writers never contend on a row.

### Table Structure

| Table | Partition Key | Sort Key | Purpose |
|-------|--------------|----------|---------|
| `experiment-counters-<env>` | `pk` | `sk` | Per-variant counters, with an `experiment-id-index` GSI |

### Atomic Increment

`DynamoDBCounterService` (`modules/backend/app/services/dynamodb_counter_service.py`) does the
increments. The API's real-time counter endpoints call it, and the bandit scheduler reads the
counters (`backend/app/core/bandit_scheduler.py`).

### Configuration

`DYNAMODB_COUNTERS_TABLE` names the table the API uses (default `experiment-counters`). On the
full profile the counters stack creates `experiment-counters-<env>`, and the Fargate stack sets
the variable on the API task to that same name (both come from `counters_table_name` in
`infrastructure/cdk/stacks/names.py`). It also sets `AWS_DEFAULT_REGION` to the stack's region,
because the counter service builds its DynamoDB client without naming a region, and gives the
task role `dynamodb:Query` and `dynamodb:UpdateItem` on that one table: the two calls the
service makes. The intent is that the `/api/v1/counters` routes and the bandit scheduler's
DynamoDB read reach the table once this is deployed; nothing writes counters automatically
yet, so the scheduler still takes its statistics from PostgreSQL while the table is empty.
The core profile creates no table and sets neither variable.

---

## Lambda Functions

**No Lambda function serves requests or processes events.** The stacks deploy three:

| Function | Stack | What it does |
|----------|-------|--------------|
| `DatabaseAccessLambda` | `experimentation-compute-<env>` | A placeholder. Its inline code returns 200 and does nothing |
| `AnalyticsLambda` | `experimentation-analytics-<env>` (full profile) | A placeholder on the Kinesis stream. Its inline code returns 200 and processes nothing |
| `ETLTriggerLambda` | `experimentation-glue-etl-<env>` (full profile) | Starts the Glue ETL jobs, from a daily EventBridge rule |

The repository has Lambda code for event processing and flag evaluation under
`backend/lambda/`, but no stack deploys it. SDKs call the API (`/api/v1/tracking/*`,
`/api/v1/feature-flags/evaluate/*`) for assignment and evaluation.
`infrastructure/tests/test_lambda_functions_doc.py` pins this list against a synth.

---

## CloudFront and Lambda@Edge

**The CDK does not create a CloudFront distribution**, and there is no S3 bucket
for frontend assets. The dashboard is an ECS service behind the same Application
Load Balancer as the API, which sends it every path except `/api/*`, `/health`,
`/health/*` and `/metrics`; see [AWS CDK Deployment](../self-hosting/cdk.md).

### Lambda@Edge for Split URL Testing

The split-URL module ships a CDK construct,
`modules/infrastructure/constructs/split_url_distribution.py`, that creates a
CloudFront distribution with a Lambda@Edge `viewer-request` router in front of
your application. `infrastructure/cdk/app.py` does not use it, so a deployment
gets it only if you add it to a stack yourself. The router
(`modules/lambda/split_url_router/handler.py`):

1. Reads the assignment cookie
2. If absent, hashes the client fingerprint (IP + User-Agent) to assign a variant
3. Returns a `302 Found` redirect to the variant URL
4. Sets a `Set-Cookie` header recording the assignment (30 days by default; `cookie_ttl_days` in the experiment config)

Lambda@Edge functions must be deployed to `us-east-1` (a CloudFront requirement) and are globally replicated to all edge locations.

The construct is Python, like the rest of the CDK app. Its usage, and how the
router receives its configuration, are in
[Split URL testing](../api/split-url.md#cloudfront-cdk-construct).

---

## Kinesis and OpenSearch

The full profile's analytics stack (`experimentation-analytics-<env>`) creates a **Kinesis Data
Stream** that Firehose delivers to the S3 data lake, and an **Amazon OpenSearch Service**
domain. The resource names are generated by CloudFormation.

The API does not publish tracking events to the stream today: `POST /api/v1/tracking/track`
and `/tracking/batch` store events in PostgreSQL. Nothing indexes events into OpenSearch
either, because the Lambda on the stream is a placeholder (see
[Lambda Functions](#lambda-functions)).

---

## CDK Deployment

All infrastructure is defined in `infrastructure/cdk` using AWS CDK v2, in Python.

### Prerequisites

- AWS account with appropriate IAM permissions
- Node.js 18+
- AWS CDK v2: `npm install -g aws-cdk`
- AWS CLI configured: `aws configure`

### Deploy

One-time bootstrap (per account/region):

```bash
cd infrastructure
cdk bootstrap aws://YOUR_ACCOUNT_ID/YOUR_REGION
```

Deploy all stacks:

```bash
export ALARM_EMAIL=ops@your-domain.com
cdk deploy --all
```

Deploy a specific stack (a stack id from `cdk list`):

```bash
cdk deploy experimentation-fargate-prod
```

`ALARM_EMAIL` is the address every alarm emails, including the API rollback
alarms. It is required for `staging` and `prod`, and synth refuses to run
without it. Confirm the subscription it creates from the inbox; see
[AWS CDK Deployment](../self-hosting/cdk.md#required-environment-variables) for
that and for the other required settings.

### Stacks Deployed

| Stack (`<env>` is `dev`, `staging` or `prod`) | Contents |
|---|---|
| `experimentation-vpc-<env>` | VPC, public/private/isolated subnets, NAT, route tables, network ACLs, gateway endpoints, security groups |
| `experimentation-auth-<env>` | Cognito user pool, app client and groups |
| `experimentation-database-<env>` | Aurora PostgreSQL cluster, parameter group, KMS key, security group |
| `experimentation-redis-<env>` | ElastiCache Redis replication group, subnet group, security group |
| `experimentation-dynamodb-<env>` | Five DynamoDB tables (assignments, events, experiments, feature flags, overrides) |
| `experimentation-compute-<env>` | ECS cluster, task security group, a placeholder Lambda (`DatabaseAccessLambda`) |
| `experimentation-fargate-<env>` | ALB, HTTPS + test listeners, blue/green target groups, Fargate service, CodeDeploy application and deployment group, auto-scaling |
| `experimentation-migrations-<env>` | One-off ECS task definition that runs the alembic upgrade |
| `experimentation-monitoring-<env>` | CloudWatch dashboards, alarms, log groups, metric filters, SNS topic |
| `experimentation-dynamodb-counters-<env>` | **Full profile only** — the real-time experiment-counters table |
| `experimentation-analytics-<env>` | **Full profile only** — Kinesis stream, Firehose, S3 data lake, OpenSearch domain, a placeholder consumer Lambda |
| `experimentation-glue-etl-<env>` | **Full profile only** — Glue database and crawler, two ETL jobs, Athena results bucket, daily trigger |

A core deployment builds the first nine; a full one builds all twelve. The
names are the stack **ids** `cdk deploy` takes, not class names -- run
`cdk list` to see them for your environment.

---

## Required IAM Permissions

The CDK (`infrastructure/cdk/stacks/fargate_service_stack.py`) gives the API's ECS task role
these permissions:

### ECS Task Role

- the `CloudWatchLogsFullAccess` managed policy
- `secretsmanager:GetSecretValue` on the secrets the task reads
- `ssmmessages:CreateControlChannel`, `CreateDataChannel`, `OpenControlChannel`,
  `OpenDataChannel`, `logs:DescribeLogGroups`, `CreateLogStream`, `DescribeLogStreams` and
  `PutLogEvents`, which come with ECS Exec
- full profile only: `dynamodb:Query` and `dynamodb:UpdateItem` on
  `arn:aws:dynamodb:<region>:<account>:table/experiment-counters-<env>` (see [DynamoDB](#dynamodb))
- full profile only, for the `etl` module's routes (see [Glue](#glue-the-etl-routes)):
    - `glue:StartJobRun` and `glue:GetJobRun` on
      `arn:aws:glue:<region>:<account>:job/experimentation-events-etl-<env>` and
      `job/experimentation-metrics-etl-<env>`
    - `glue:StartCrawler` and `glue:GetCrawler` on `crawler/experimentation-crawler-<env>`
    - `glue:GetTable` and `glue:BatchCreatePartition` on `catalog`,
      `database/experimentation_<env>` and `table/experimentation_<env>/*`

There is no Kinesis, Cognito, Athena, S3 or other DynamoDB permission, and no other Glue action
or Glue object.

### Glue: the ETL routes

On the full profile the Fargate stack tells the API the Glue names the glue-etl stack creates
(`GLUE_ETL_JOB_NAME`, `GLUE_METRICS_JOB_NAME`, `GLUE_CRAWLER_NAME`, `GLUE_DATABASE`, all from
`glue_names` in `infrastructure/cdk/stacks/names.py`) and grants the six calls above on those
objects alone. The routes accept only those names (see the ETL section of the API reference).

The Glue client is built without naming a region, so it takes the region from
`AWS_DEFAULT_REGION`. The client never reads `AWS_REGION`. The CDK sets `AWS_DEFAULT_REGION` on
the task to the stack's region, and the repository's `docker-compose.yml` sets it from
`AWS_REGION`. **Anywhere else** (Helm, a container you run yourself), set `AWS_DEFAULT_REGION`
to the region your Glue job and crawler are in. Without it the job, crawler and partitions
routes answer 500 and the API logs `NoRegionError`. On Helm, put it in `api.extraEnv` alongside the `GLUE_*` names. The chart has
no value of its own for it.

`GLUE_EVENTS_TABLE` (default `raw_events`) names the one catalog table `POST /etl/partitions/add`
accepts, and the CDK does not set it. It must be the table the crawler creates. The crawler is
given an S3 path and no table prefix, so it picks the table's name itself when it runs. Check
the name after the first crawl and set `GLUE_EVENTS_TABLE` to it; until then that route
answers 404.

---

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_SERVER` | Yes | Aurora endpoint; with `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`. `DATABASE_URL` is not read; in staging and production the container's start-up check refuses to start with it set |
| `REDIS_HOST` | Yes | ElastiCache primary endpoint (`localhost` if unset) |
| `REDIS_PORT` | No | ElastiCache port (default `6379`) |
| `REDIS_SSL` | Yes, on AWS | `true` to connect over TLS (default `false`) |
| `SECRET_KEY` | Yes | Application secret key (min 32 chars) |
| `COGNITO_USER_POOL_ID` | Yes | AWS Cognito User Pool ID |
| `COGNITO_CLIENT_ID` | Yes | Cognito app client ID |
| `AWS_REGION` | Yes | Primary AWS region, read by Cognito and the other settings that name it. The Glue and DynamoDB counter clients do not read it |
| `AWS_DEFAULT_REGION` | Full profile: yes, for the ETL routes | The region the Glue client (see [Glue](#glue-the-etl-routes)) and the DynamoDB counter client (see [DynamoDB](#dynamodb)) use. The CDK sets it to the stack's region. Outside the CDK set it yourself (Helm: `api.extraEnv`); without it the job and crawler routes answer 500 |
| `GLUE_ETL_JOB_NAME`, `GLUE_METRICS_JOB_NAME`, `GLUE_CRAWLER_NAME`, `GLUE_DATABASE` | Full profile, for the ETL routes | The Glue job, crawler and database names the ETL routes accept. The CDK sets them to the glue-etl stack's `-<env>` names |
| `GLUE_EVENTS_TABLE` | Full profile, for `POST /etl/partitions/add` | The catalog table that route accepts (default `raw_events`). Not set by the CDK: set it to the table the crawler creates (see [Glue](#glue-the-etl-routes)) |
| `DYNAMODB_COUNTERS_TABLE` | No | Full profile: the counters table, set by the CDK to `experiment-counters-<env>` (default `experiment-counters`; see [DynamoDB](#dynamodb)) |
| `SLACK_BOT_TOKEN` | No | Slack bot token for alerting |
| `SENDGRID_API_KEY` | No | SendGrid API key for email alerts |
| `AUDIT_HMAC_SECRET` | Yes | Secret for HMAC-SHA256 audit event signing |
| `ANTHROPIC_API_KEY` | No | Claude API key for AI experiment design |
