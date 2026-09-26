# Architecture Overview

This document describes the high-level technical architecture of the platform: how the components fit together, how data flows, and how the system is deployed on AWS.

---

## High-Level Components

```text
┌──────────────────────────────────────────────────────────────────┐
│                        Client Applications                        │
│           (web, mobile, server — via SDK or REST API)            │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                Application Load Balancer (HTTPS)                 │
│  (no CloudFront; /api/* → API, everything else → the dashboard)  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    API Layer (FastAPI)                            │
│        Experiments / Feature Flags / Analytics / Auth            │
└──────┬───────────────┬───────────────┬───────────────────────────┘
       │               │               │
       ▼               ▼               ▼
  PostgreSQL        Redis           DynamoDB
  (Aurora)      (ElastiCache)    (Real-time counters)
                                       │
                                       ▼
                              Kinesis → Lambda → OpenSearch
                                  (Analytics pipeline)
```

---

## API Layer

### FastAPI Application

The core of the platform is a **FastAPI** application that exposes a comprehensive REST API. It is deployed on **ECS Fargate** and scales horizontally behind an Application Load Balancer.

The API is organized into resource-specific endpoint groups:

| Endpoint Group | Description |
|----------------|-------------|
| `/api/v1/experiments` | Create, update, start, pause, stop, and query experiments |
| `/api/v1/feature-flags` | Manage feature flags, targeting rules, and rollout percentages |
| `/api/v1/results` | Read statistical results, run CUPED, dimensional analysis, sequential testing |
| `/api/v1/tracking` | Ingest assignment and event data from client applications |
| `/api/v1/users` | User management and authentication |
| `/api/v1/compliance` | Audit event log and compliance reports |
| `/api/v1/integrations` | Jira, Salesforce, and GitHub integrations |
| `/api/v1/notifications` | Slack and email alert preferences |
| `/api/v1/rbac` | Role management and permission grants |
| `/api/v1/bandit` | Multi-armed bandit state and weight management |
| `/api/v1/warehouse` | Warehouse-native analytics connections and syncs |

Interactive API documentation is available at `/docs` (Swagger UI) and `/redoc`.

### Background Schedulers

Several background tasks run on a configurable cycle alongside the API process:

| Scheduler | Default Cycle | Responsibility |
|-----------|---------------|----------------|
| Experiment scheduler | 15 minutes | Auto-starts experiments at `start_date`, auto-stops at `end_date` |
| Rollout scheduler | 15 minutes | Advances rollout schedule stages based on time-based triggers |
| Metrics collector | 15 minutes | Aggregates raw events into experiment metric summaries |
| Safety monitor | 5 minutes | Checks error rate and latency thresholds; triggers auto-rollback if breached |
| Bandit scheduler | 5 minutes (`BANDIT_UPDATE_INTERVAL_MINUTES`) | Recomputes variant weights for active multi-armed bandit experiments from DynamoDB counters, falling back to PostgreSQL assignments + conversion events; `/tracking/assign` routes new users by these weights |

---

## Database Layer

### PostgreSQL (Aurora)

Amazon Aurora PostgreSQL is the primary relational database. It stores all persistent application data:

- Experiments, variants, metrics definitions
- Feature flags, targeting rules, rollout schedules
- User accounts, roles, permissions
- Audit events and compliance records
- Integration configurations
- Results aggregations

All schema changes are managed with **Alembic** migrations. The schema is namespaced under the `experimentation` PostgreSQL schema.

The production Aurora cluster is configured with a read replica. Write operations go to the primary instance; read-heavy queries (results, audit log reads) can be directed to the replica.

### Redis (ElastiCache)

Redis serves two purposes:

1. **Session storage**: User session tokens are stored in Redis with a configurable TTL. This allows horizontal scaling of the API layer without sticky sessions.

2. **Application cache**: Feature flag configurations and experiment assignments are cached in Redis to reduce database load. The default cache TTL is 60 seconds, meaning flag changes propagate to all users within one minute.

---

## Lambda Functions

Three Lambda functions handle high-throughput, latency-sensitive operations:

### Experiment Assignment Lambda

Evaluates experiment targeting rules and assigns users to variants. Called directly by SDK clients for server-side assignment.

- Input: `experiment_key`, `user_id`, `attributes`
- Output: `variant_key`, assignment metadata
- Uses consistent hash bucketing for deterministic results

### Event Processor Lambda

Processes incoming tracking events (impressions and conversions) at scale. Triggered by events arriving on the Kinesis stream.

- Validates events against known experiment/metric configurations
- Writes processed events to OpenSearch for analytics queries
- Updates DynamoDB counters atomically

### Feature Flag Evaluation Lambda

Evaluates feature flag targeting rules and rollout percentages for a given user. Called by SDK clients for server-side flag evaluation.

- Input: `flag_key`, `user_id`, `attributes`
- Output: `enabled` (boolean), flag metadata
- Results are cached at the Lambda layer using an in-memory LRU cache

---

## Real-Time Counters (DynamoDB)

Impression and conversion counts are tracked in DynamoDB using atomic `ADD` operations. This provides high-throughput, conflict-free counter increments without database locking.

### Why DynamoDB for Counters

Traditional relational databases struggle with high-frequency counter updates because each update requires a read-modify-write cycle. DynamoDB's atomic `ADD` operation performs the increment server-side, making it safe for concurrent writes from many Lambda instances.

### Counter Schema

```text
partition_key: experiment_id
sort_key:      variant_id#metric_key
impressions:   (atomic counter)
conversions:   (atomic counter)
```

The metrics collector scheduler reads from DynamoDB every 15 minutes and writes aggregated results to PostgreSQL for historical storage and statistical analysis.

---

## Analytics Pipeline

Raw events flow through a pipeline for aggregation and search:

```text
Client App
    |
    v
POST /api/v1/tracking/track
    |
    v
Kinesis Data Stream
    |
    v
Event Processor Lambda
    |
    +---> DynamoDB (atomic counters, real-time)
    |
    +---> OpenSearch (full event index, for ad-hoc queries)
```

**Kinesis** buffers events and decouples ingestion from processing. The platform can handle spikes without dropping events.

**OpenSearch** provides the backing store for dimensional analysis, segment breakdowns, and ad-hoc event queries.

---

## Split URL Testing (Lambda@Edge)

Split URL experiments use a different flow from standard A/B tests. Instead of modifying a component within a page, the entire URL path changes between variants. This is handled at the CDN layer:

```text
User Request
    |
    v
CloudFront Distribution
    |
    v
Lambda@Edge (viewer-request event)
    |
    +-- Read cookie exp_{experiment_key}
    |     - Present: use stored variant
    |     - Absent: consistent-hash bucket user_id → assign variant
    |
    +-- Return 302 redirect to variant URL
    |
    +-- Set-Cookie: exp_{key}=variant; Max-Age=31536000; Secure; SameSite=Lax
```

The Lambda@Edge function is deployed to `us-east-1` (a requirement for Lambda@Edge) and runs globally on every CloudFront PoP. The `split_url_config` is fetched from the API at cold start and cached for 60 seconds.

---

## Authentication

### AWS Cognito

User authentication is handled by **AWS Cognito**. The platform integrates with a Cognito User Pool:

1. Users log in via the dashboard or API
2. Cognito issues a **JWT access token** (valid for 30 minutes) and a refresh token
3. The JWT is passed in the `Authorization: Bearer <token>` header on all API requests
4. The API validates the JWT signature against Cognito's public keys

### API Key Authentication

SDK clients and server-to-server integrations use **API keys** instead of JWT tokens. API keys are:

- Created by admins via `POST /api/v1/api-keys`
- Passed in the `X-API-Key: <key>` header
- Scoped to specific operations (read, write, or admin)
- Revocable without affecting user accounts

### Role-Based Access Control

Every user has one of four roles, each with progressively broader permissions:

| Role | Description |
|------|-------------|
| **VIEWER** | Read-only access to approved experiments and results |
| **ANALYST** | View all experiments, results, audit logs, and reports |
| **DEVELOPER** | Create and manage experiments and feature flags |
| **ADMIN** | Full access: user management, global settings, compliance exports |

Custom roles and direct permission grants extend the base role system for fine-grained access control.

---

## CDK Infrastructure

The AWS infrastructure is defined as code using **AWS CDK v2**, in Python (`infrastructure/cdk/app.py`). Running `cdk deploy --all` from `infrastructure/cdk` provisions the stacks below.

The Fargate stack runs the dashboard as its own ECS service behind the API's load
balancer: `/api/*`, `/health`, `/health/*` and `/metrics` go to the API, everything
else to the dashboard. `cdk deploy` starts it on `experimentation-platform/web:bootstrap`;
the Deploy workflow rolls each release onto it by digest, after the API. No
stack creates CloudFront. The split-URL module's CloudFront construct
exists but `app.py` does not use it. See [AWS CDK Deployment](../self-hosting/cdk.md).

### Stacks

| Stack (`<env>` is `dev`, `staging` or `prod`) | Contents |
|---|---|
| `experimentation-vpc-<env>` | VPC, public/private/isolated subnets, NAT, route tables, network ACLs, gateway endpoints, security groups |
| `experimentation-auth-<env>` | Cognito user pool, app client and groups |
| `experimentation-database-<env>` | Aurora PostgreSQL cluster, parameter group, KMS key, security group |
| `experimentation-redis-<env>` | ElastiCache Redis replication group, subnet group, security group |
| `experimentation-dynamodb-<env>` | Five DynamoDB tables (assignments, events, experiments, feature flags, overrides) |
| `experimentation-compute-<env>` | ECS cluster, task security group, the database-access Lambda |
| `experimentation-fargate-<env>` | ALB, HTTPS + test listeners, blue/green target groups, the API's Fargate service, CodeDeploy application and deployment group, auto-scaling; the dashboard's ECS service and target group |
| `experimentation-migrations-<env>` | One-off ECS task definition that runs the alembic upgrade |
| `experimentation-monitoring-<env>` | CloudWatch dashboards, alarms, log groups, metric filters, SNS topic |
| `experimentation-dynamodb-counters-<env>` | **Full profile only** — the real-time experiment-counters table |
| `experimentation-analytics-<env>` | **Full profile only** — Kinesis stream, Firehose, S3 data lake, OpenSearch domain, consumer Lambda |
| `experimentation-glue-etl-<env>` | **Full profile only** — Glue database and crawler, two ETL jobs, Athena results bucket, daily trigger |

A core deployment builds the first nine; a full one builds all twelve. The
names are the stack **ids** `cdk deploy` takes, not class names -- run
`cdk list` to see them for your environment.

### Deployment Model

The API service uses **blue/green deployment** via AWS CodeDeploy:

1. A new task definition is registered (the "green" environment)
2. CodeDeploy gradually shifts traffic from the old (blue) to the new (green) deployment
3. If health checks fail, traffic is automatically shifted back to blue
4. The full cutover completes within minutes with zero downtime

---

## Health and Observability

| Endpoint / Resource | Purpose |
|---------------------|---------|
| `GET /health` | Returns `{"status": "ok"}` when the API is healthy |
| `GET /metrics` | Prometheus-format metrics (request count, latency histograms, error rates) |
| CloudWatch Dashboards | API latency, Lambda invocations, error rates, queue depth |
| CloudWatch Alarms | p99 latency > 1s, error rate > 1%, DLQ messages > 0 |
| Structlog JSON logs | Structured logs with `request_id`, `user_id`, `action`, `duration_ms` |
| AWS X-Ray | Distributed tracing across API, Lambda, and DynamoDB calls |
