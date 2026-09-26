# High-Level Architecture Design for Experimently on AWS

Based on the detailed requirements for an experimentation platform with A/B testing and feature flag capabilities, this document outlines a comprehensive architecture leveraging AWS services to build a robust, scalable solution.

## Architecture Overview

The architecture is designed to provide high-performance experiment evaluation, real-time event collection, advanced statistical analysis, and flexible targeting capabilities.

!!! warning "This is the design, not what the CDK deploys today"
    The diagram below is the target design. What `infrastructure/cdk` deploys
    today is the API and the dashboard on ECS Fargate behind one Application
    Load Balancer, with
    Aurora PostgreSQL, ElastiCache Redis and DynamoDB tables; see
    [AWS CDK Deployment](../self-hosting/cdk.md).

    **The dashboard is its own ECS service behind the same load balancer**: the
    HTTPS listener sends `/api/*`, `/health`, `/health/*` and `/metrics` to the
    API and everything else to the dashboard. `cdk deploy` starts it on the
    `experimentation-platform/web:bootstrap` image; the Deploy workflow rolls
    each release onto it by digest, after the API. No stack creates CloudFront
    or API Gateway. The dashboard is a static Next.js export served by nginx; in
    Docker Compose that nginx also proxies `/api/` to the API, and in AWS it
    proxies nothing.

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                                  Client Applications                             │
└───────────────────┬─────────────────────────────────────┬─────────────────────┬─┘
                    │                                     │                     │
                    ▼                                     ▼                     ▼
┌───────────────────────────┐     ┌───────────────────────────┐     ┌─────────────────────────┐
│  Amazon CloudFront        │     │    Application Load       │     │  Amazon API Gateway     │
│  (not created by the CDK) │     │       Balancer            │     │  (not created by CDK)   │
└─────────────┬─────────────┘     └──────────────┬────────────┘     └────────────┬────────────┘
              │                                  │                                │
              │                                  │                                │
              ▼                                  ▼                                ▼
┌───────────────────────────┐     ┌───────────────────────────┐     ┌─────────────────────────┐
│  Next.js dashboard        │     │   ECS/Fargate Containers  │     │   Lambda Functions      │
│  (ECS, behind the ALB)    │     │   (Core Backend Services) │     │   (Real-time Services)  │
└─────────────┬─────────────┘     └──────────────┬────────────┘     └────────────┬────────────┘
              │                                  │                                │
              │                                  │                                │
              │                                  ▼                                │
              │                   ┌───────────────────────────┐                  │
              └────────────────▶ │     Amazon RDS Aurora     │ ◀────────────────┘
                                 │     (Primary Database)     │
                                 └──────────────┬────────────┘
                                                │
                                                │
                                                ▼
          ┌────────────────────────────────────────────────────────────────┐
          │                                                                │
┌─────────┴─────────┐    ┌────────────────────┐    ┌─────────────────────┐│
│ Amazon DynamoDB   │    │ Amazon ElastiCache │    │ Amazon OpenSearch   ││
│ (High-throughput  │    │ (Redis for caching)│    │ (Analytics Engine)  ││
│  event storage)   │    │                    │    │                     ││
└─────────┬─────────┘    └────────────────────┘    └─────────────────────┘│
          │                                                                │
          └────────────────────────────────────────────────────────────────┘
               ▲                     ▲                          ▲
               │                     │                          │
               │                     │                          │
┌──────────────┴─────────┐  ┌───────┴───────────┐  ┌───────────┴───────────┐
│  Amazon Kinesis        │  │  AWS EventBridge  │  │  AWS Glue / Athena    │
│  (Event Stream)        │  │  (Event Bus)      │  │  (Data Processing)    │
└──────────────┬─────────┘  └───────────────────┘  └───────────────────────┘
               │
               │
               ▼
┌────────────────────────┐
│  Amazon S3             │
│  (Data Lake)           │
└────────────────────────┘
```

## Core Components

### 1. Client-Facing Layer

-   **Application Load Balancer**: For routing traffic to backend services. This is the only entry point the CDK creates: HTTPS, with HTTP redirected to HTTPS, in front of the API.
-   **Amazon CloudFront** (design only, not created by the CDK): Global CDN for delivering static assets and caching API responses
-   **Amazon API Gateway** (design only, not created by the CDK): Manages APIs for experiment evaluation, event tracking, and admin functions

### 2. Application Layer

-   **Next.js dashboard**: Web UI for experiment management, feature flag configuration, and dashboards. It runs as the nginx image built from `frontend/Dockerfile`: in AWS as its own ECS service behind the load balancer (started on `web:bootstrap`; per-release rollout is #69), and in Docker Compose
-   **Core Backend Services (ECS/Fargate)**:
    -   Experiment Management Service
    -   Feature Flag Service
    -   Segmentation Service
    -   Analysis Service
    -   User Management Service
-   **Real-time Services (Lambda)**:
    -   Feature Flag Evaluation
    -   Experiment Assignment
    -   Event Processing

### 3. Data Storage Layer

-   **Amazon Aurora PostgreSQL**: Primary database for:
    -   Experiment definitions
    -   Feature flag configurations
    -   User accounts and permissions
    -   Segmentation rules
-   **Amazon DynamoDB**: High-throughput NoSQL database for:
    -   Experiment assignments (user to variant mappings)
    -   Feature flag evaluations
    -   Real-time event tracking
-   **Amazon ElastiCache (Redis)**: In-memory caching for:
    -   Feature flag configurations
    -   Experiment assignments
    -   Segment membership
-   **Amazon S3**: Data lake for:
    -   Raw event data
    -   Analytics exports
    -   Audit logs

### 4. Analytics & Processing Layer

-   **Amazon Kinesis**: Real-time data streaming for event collection
-   **AWS EventBridge**: Event bus for internal service communication
-   **Amazon OpenSearch Service**: Analytics engine for experiment results and dashboards
-   **AWS Glue & Athena**: ETL and ad-hoc query services for data analysis

### 5. Supporting Services

-   **Amazon Cognito**: User authentication and authorization
-   **AWS Lambda**: Serverless compute for real-time evaluation and event processing
-   **Amazon CloudWatch**: Monitoring, logging, and alerting
-   **AWS WAF**: Web application firewall for security
-   **AWS Secrets Manager**: Secure credential storage

## Key Service Implementations

### 1. Experiment Management & Feature Flags System

```text
┌───────────────────────────────────────┐
│      Experiment Management UI         │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│   Experiment Management Service       │
│   - Create/Edit/Delete experiments    │
│   - Manage variants                   │
│   - Configure targeting rules         │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│   Feature Flag Service                │
│   - Feature flag definitions          │
│   - Targeting rules                   │
│   - Rollout configurations            │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│   Assignment Service (Lambda)         │
│   - User-to-experiment assignment     │
│   - Feature flag evaluation           │
│   - Traffic allocation                │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│   DynamoDB + ElastiCache              │
│   - Assignment storage                │
│   - Configuration cache               │
└───────────────────────────────────────┘
```

### 2. Real-Time Event Collection & Analysis

```text
┌───────────────────────────────────────┐
│      Client SDK                       │
│      - Experiment exposure tracking   │
│      - Conversion events              │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│   API Gateway                         │
│   - Event collection endpoints        │
│   - Validation & authentication       │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│   Kinesis Data Streams                │
│   - High-throughput event ingestion   │
└─────────────────┬─────────────────────┘
                  │
                  ▼
┌───────────────────────────────────────┐
│   Lambda Event Processors             │
│   - Event enrichment                  │
│   - Metric calculation                │
└─────────────────┬─────────────────────┘
                  │
        ┌─────────┴─────────┐
        │                   │
        ▼                   ▼
┌───────────────────┐ ┌────────────────────┐
│   DynamoDB        │ │   S3 Data Lake     │
│   - Real-time     │ │   - Historical     │
│     metrics       │ │     event data     │
└─────────┬─────────┘ └──────────┬─────────┘
          │                      │
          │                      ▼
          │           ┌────────────────────┐
          │           │   Glue ETL Jobs    │
          │           │   - Data transform │
          │           └──────────┬─────────┘
          │                      │
          └──────────┐          │
                     ▼          ▼
          ┌────────────────────────────┐
          │   OpenSearch Service       │
          │   - Analytics engine       │
          │   - Visualization          │
          └────────────────────────────┘
```

## Key Technical Capabilities

### 1. Real-Time Feature Flag & Experiment Evaluation

-   **Lambda-based evaluation service** with <50ms p99 latency
-   **Consistent hashing algorithm** for stable user assignment
-   **Redis caching layer** for configuration data
-   **SDK implementations** for web, mobile, and server environments

### 2. High-Performance Event Collection

-   **Kinesis Data Streams** for handling millions of events per minute
-   **Batched event processing** to optimize throughput
-   **Event schema validation** and enrichment
-   **Real-time metrics aggregation** using DynamoDB counters

### 3. Statistical Analysis System

-   **Real-time significance testing** using OpenSearch aggregations
-   **Multi-metric analysis** with correction for multiple testing
-   **Bayesian analysis** for more nuanced experiment interpretation
-   **Automated experiment stopping** based on significance thresholds

### 4. Segmentation & Targeting Engine

-   **Rich targeting rule evaluation** supporting complex logical operations
-   **User attribute-based targeting** (device, location, behavior)
-   **Sticky bucket assignment** for consistent user experience
-   **Gradual rollout control** with percentage-based targeting

## Scalability & Reliability Considerations

1. **High Availability**

    - Multi-AZ deployments for all services
    - Database read replicas for read scaling
    - Service auto-scaling based on load

2. **Performance Optimization**

    - Redis caching for feature flag/experiment configurations
    - DynamoDB for high-throughput event ingestion
    - API response caching at CloudFront edge locations

3. **Operational Excellence**
    - Infrastructure as Code using AWS CDK or CloudFormation
    - Automated CI/CD pipelines for deployment
    - Comprehensive monitoring and alerting

## Implementation Requirements Fulfillment

This architecture addresses all core requirements from the project specification:

1. **Experiment Creation and Management**

    - Supports all experiment types (A/B, multivariate, split URL, multi-armed bandit)
    - Provides variant management with traffic distribution control
    - Enables advanced segmentation and scheduling capabilities
    - Allows real-time experiment control

2. **Metrics and Events Tracking**

    - Supports custom metrics definition
    - Provides comprehensive event logging
    - Offers real-time metrics reporting
    - Includes statistical analysis capabilities

3. **Randomization and Traffic Allocation**

    - Implements random user assignment
    - Supports controlled traffic allocation
    - Enables real-time allocation adjustments

4. **Feature Flags Integration**

    - Provides complete feature flag management
    - Implements targeting rules
    - Enables real-time feature control
    - Supports multivariate flag configuration
    - Allows gradual rollouts and immediate rollbacks

5. **User Access Control and Permissions**

    - Implements role-based access control
    - Provides experiment-level permissions
    - Maintains comprehensive audit logs

6. **Results and Analysis**
    - Offers robust statistical analysis
    - Provides visualizations and dashboards
    - Implements automated significance calculations

---

## Post-MVP Components

The following capabilities were added after the initial platform release. See the linked docs for full details.

### Advanced Statistical Methods

| Component | Description | Doc |
|-----------|-------------|-----|
| Sequential Testing (EP-021) | mSPRT continuous monitoring, always-valid CIs, alpha spending (O'Brien-Fleming, Pocock) | [sequential-testing.md](../api/sequential-testing.md) |
| CUPED Variance Reduction (#21) | Pre-experiment covariate adjustment (OLS θ), Winsorization, 20–40% variance reduction | [cuped.md](../api/cuped.md) |
| Multi-Armed Bandit (#22) | Thompson Sampling, UCB1, Epsilon-Greedy; background MAB scheduler | [multi-armed-bandit.md](../api/multi-armed-bandit.md) |
| Dimensional Analysis (#28) | Per-segment breakdowns with Bonferroni correction, HTE detection | [dimensional-analysis.md](../api/dimensional-analysis.md) |
| Interaction Detection (#25) | Jaccard overlap, chi-squared interaction test, novelty effects, SUTVA violation detection | [interaction-detection.md](../api/interaction-detection.md) |

### Traffic Management

| Component | Description | Doc |
|-----------|-------------|-----|
| Mutual Exclusion Groups (EP-022) | Consistent-hashing traffic partitioning to prevent cross-experiment contamination | [mutual-exclusion-groups.md](../api/mutual-exclusion-groups.md) |
| Global Holdout (EP-022) | Platform-wide clean control group for cumulative impact measurement | [mutual-exclusion-groups.md](../api/mutual-exclusion-groups.md) |

### Data & Integrations

| Component | Description | Doc |
|-----------|-------------|-----|
| Warehouse-Native Analytics (#26) | Snowflake, BigQuery, Redshift connectors; SQL-sanitized sync | [warehouse-analytics.md](../api/warehouse-analytics.md) |
| Real-time DynamoDB Counters (P2-B) | Atomic ADD operations, bulk counter updates, Lambda integration | [dynamodb-readme.md](../infrastructure/dynamodb-readme.md) |

### Platform Experience

| Component | Description | Doc |
|-----------|-------------|-----|
| Guided experiment builder (#27) | 5-step draft-and-submit API; no dashboard UI in this release | [experiment-wizard.md](../guides/experiment-wizard.md) |
| AI Experiment Design (#23) | Claude API–powered design suggestions, results interpretation, MCP server | [mcp-server.md](../mcp-server.md) |
| Audit Logging & Bulk Toggle (P1-B) | Immutable audit trail, SSE real-time stream, bulk flag operations | [audit-logging.md](../api/audit-logging.md) |
| RBAC Post-MVP (P2-A) | Custom roles, direct permission grants, effective permissions resolution | [rbac.md](../api/rbac.md) |
| Slack / Email Alerting (EP-030) | Event-driven notifications via Slack Block Kit and SendGrid/SMTP | [alerting.md](../api/alerting.md) |
| Admin UI (EP-029) | React admin panel for users, roles, audit logs, notifications, and resource management | — |
