# Frequently Asked Questions

---

## General

### What is Experimently?

Experimently is a self-hosted experimentation platform for running A/B tests, feature flags, and controlled rollouts. It provides a complete solution for data-driven product development: design experiments, assign users to variants, track conversion events, run statistical analysis, and make shipping decisions — all in one platform.

The platform includes a REST API backend (FastAPI), a React management dashboard, client SDKs (JavaScript, Python, Java, React), AWS CDK infrastructure code, and Lambda functions for real-time event processing.

---

### Is it open source and self-hostable?

Yes. The platform is designed to be deployed in your own AWS account using the provided CDK infrastructure definitions. You own your data and control your deployment. There is no vendor lock-in and no data leaves your infrastructure.

Running `cdk deploy --all` from the `infrastructure/` directory provisions the complete AWS environment, including the ECS Fargate API service, Aurora PostgreSQL database, Redis cache, Lambda functions, and CloudFront distribution. A checkout that also has `modules/` gets the real-time DynamoDB counters table and the Kinesis/OpenSearch/Glue data lake alongside them — see [AWS CDK Deployment](../self-hosting/cdk.md) for which stacks each profile deploys.

---

### What AWS services does it require?

A full production deployment uses the following AWS services:

| Service | Purpose |
|---------|---------|
| ECS Fargate | Hosts the FastAPI application |
| Aurora PostgreSQL | Primary relational database |
| ElastiCache Redis | Session storage and caching |
| DynamoDB | Real-time impression and conversion counters |
| Lambda | Experiment assignment, event processing, feature flag evaluation |
| CloudFront | CDN and Lambda@Edge for split URL testing |
| Kinesis | Event streaming pipeline |
| OpenSearch | Event indexing and ad-hoc analytics queries |
| Cognito | User authentication and JWT token issuance |
| S3 | Static asset storage, Lambda deployment packages |
| CloudWatch | Logging, metrics, and dashboards |
| Secrets Manager | Encrypted storage for API keys and credentials |
| CodeDeploy | Blue/green deployments for the API service |

For local development, Docker Compose provides PostgreSQL and Redis, and LocalStack can emulate most AWS services.

---

### How is user assignment consistent across requests?

User-to-variant assignment uses a **deterministic consistent hash** of `experiment_key + user_id`. Because the hash is deterministic, the same user always receives the same variant for a given experiment — regardless of which server processes the request, whether the cache is warm, or whether the SDK has been restarted.

No database lookup is required to retrieve an assignment that has already been computed. The assignment is computed on the fly from the hash and the experiment's traffic weights.

---

### What statistical methods are supported?

The platform supports a range of statistical approaches:

| Method | Description |
|--------|-------------|
| Frequentist (z-test) | Standard two-sample proportion and mean comparison |
| Sequential testing (mSPRT) | Continuous monitoring with valid p-values at any sample size |
| Always-valid confidence intervals | Confidence sequences that are valid at every look |
| Alpha spending (O'Brien-Fleming, Pocock) | Planned interim analyses with controlled false positive rate |
| CUPED | Variance reduction using pre-experiment covariates (typically 20–40% sample size reduction) |
| Bayesian (Beta-Binomial) | Posterior credible intervals, Bayes factors, probability of superiority, ROPE |
| Multi-armed bandit | Thompson Sampling, UCB1, and Epsilon-Greedy adaptive traffic allocation |
| Dimensional analysis | Segment-level breakdowns with Bonferroni correction and heterogeneous treatment effect detection |
| Interaction detection | Jaccard overlap, chi-squared interaction tests, novelty effect analysis, SUTVA checks |

---

### What SDKs are available?

| SDK | Package |
|-----|---------|
| JavaScript / TypeScript | `@experimently/js-sdk` (npm) |
| Python | `experimently-sdk` (PyPI) |
| Java / JVM | `com.experimently:experimently-sdk` (Maven/Gradle) |
| React | `@experimently/react-sdk` (npm) |

All SDKs support experiment variant assignment, feature flag evaluation, and event tracking. The Java SDK includes Spring Boot auto-configuration. The React SDK includes hooks, an HOC, and SSR support for Next.js.

---

## Getting Started

### How do I get started?

Follow the [Quick Start Guide](quick-start.md) to go from zero to a running experiment in under 30 minutes. The guide walks you through:

1. Cloning the repository and configuring environment variables
2. Starting PostgreSQL and Redis with Docker Compose
3. Running database migrations
4. Starting the FastAPI backend and Next.js frontend
5. Creating your first experiment via the UI or API
6. Tracking events and viewing results

For a full AWS deployment, see [CDK Deployment](../self-hosting/cdk.md).

---

### What is the difference between a feature flag and an experiment?

**Feature flags** control whether a feature is visible to a user. They are primarily operational tools — used for gradual rollouts, kill switches, and beta programs. A flag has no statistical analysis attached to it.

**Experiments** are scientific tools for causal measurement. They split users into variants, track defined metrics, and apply statistical tests to determine whether a variant is better than the control. Experiments have a defined start and end date and produce a ship/no-ship recommendation.

You can combine both: run a feature behind a flag during an experiment, then graduate the flag to 100% after the experiment concludes.

---

## Data and Analytics

### Can I use my own data warehouse?

Yes. The warehouse-native analytics feature lets you connect to Snowflake, BigQuery, or Amazon Redshift and run experiment analysis directly against your existing data. This is useful when your source-of-truth metrics already live in the warehouse, or when you need to analyze large datasets.

See the [Warehouse-Native Analytics API](../api/warehouse-analytics.md) for setup instructions.

---

### How does CUPED variance reduction work?

CUPED (Controlled-experiment Using Pre-Experiment Data) reduces result noise by adjusting each user's observed metric by a term proportional to their pre-experiment behavior. The adjustment is computed using an OLS regression coefficient (`theta`) estimated from the control group.

In practice, CUPED typically reduces the variance of your metric estimates by 20–40%, meaning you can reach statistical significance with significantly fewer users — or equivalently, detect smaller effects with the same sample size.

To use CUPED, call `GET /api/v1/results/{experiment_id}/cuped`. The covariate (pre-experiment metric) must be available for your users. See [CUPED documentation](../api/cuped.md) for covariate selection guidance.

---

### What is Bayesian experimentation vs frequentist?

**Frequentist** testing (the default) computes a p-value: the probability of seeing results as extreme as these if there were no true effect. You make a binary decision: reject the null hypothesis (p < 0.05) or fail to reject it.

**Bayesian** testing maintains a probability distribution over the possible true values of the metric. It gives you:

- A **credible interval**: the range where the true effect likely falls, with a specified probability
- **Probability of superiority**: P(treatment > control), a natural way to communicate results
- A **Bayes factor**: how much more likely the data is under the alternative hypothesis than the null
- A **stopping rule** that is mathematically valid for early stopping without inflating false-positive rates

Bayesian methods are more flexible for continuous monitoring and provide richer output than a binary p-value. Frequentist methods are more familiar, have established reporting conventions, and are often required for regulatory or compliance reporting.

See [Bayesian Experimentation API](../api/bayesian.md) to enable Bayesian analysis on your experiments.

---

### How does Split URL testing work?

Split URL testing redirects different user segments to different URLs — for example, `/checkout` vs `/checkout-v2` — at the CDN layer using Lambda@Edge.

When a user visits your domain, a Lambda@Edge function on CloudFront reads a cookie to check if the user has already been assigned. If not, it performs consistent-hash bucketing on the user ID to assign a variant, then returns a 302 redirect to the variant URL and sets a 1-year persistence cookie. On all subsequent visits, the cookie is read and the user is redirected to the same URL without re-bucketing.

This approach provides zero-latency variant delivery (the redirect happens at the CDN edge, before the request reaches your origin) and works for full page-level experiments where the content differences are too large for a single-page A/B test.

See [Split URL Testing API](../api/split-url.md) for setup and the CDK construct reference.

---

## Compliance and Security

### What compliance certifications are supported?

The platform holds no certifications. It provides audit-trail controls that customers use as evidence in their own **SOC 2** or **ISO/IEC 27001** programs; the `compliance` module adds tamper-evident signing and report packs.

Every create, update, delete, login, permission change, and data export action is recorded as a tamper-evident audit event signed with HMAC-SHA256. The signing secret is stored in AWS Secrets Manager and rotated quarterly.

Pre-built compliance reports are available at:
- `GET /api/v1/compliance/reports/soc2` — rolling 365-day SOC 2 report
- `GET /api/v1/compliance/reports/iso27001` — rolling 730-day ISO 27001 report

Full audit log export (JSON or CSV) is available for SIEM ingestion at `GET /api/v1/compliance/export`.

See [Compliance Audit Logging API](../api/compliance.md) for full documentation.

---

### Can I integrate with Jira, Salesforce, or GitHub?

Yes. The platform supports bidirectional integrations with all three:

- **Jira**: Link experiments to Jira issues and receive status transition events via webhook
- **Salesforce**: Push experiment results to Salesforce campaign objects via OAuth 2.0
- **GitHub**: Receive push/pull_request/issues events; webhook payloads are validated using HMAC-SHA256 against your webhook secret

Integrations are created at `POST /api/v1/integrations` and have per-service webhook endpoints at `POST /api/v1/integrations/webhooks/github   (also /jira, /salesforce)`.

See [Integrations API](../api/integrations.md), [Salesforce Integration](../integrations/salesforce.md), and [GitHub Integration](../integrations/github.md) for detailed setup guides.

---

## Access Control

### What roles and permissions are available?

The platform uses a layered role-based access control system with four built-in roles:

| Role | What They Can Do |
|------|-----------------|
| **VIEWER** | Read-only access to approved experiments and results |
| **ANALYST** | View all experiments, results, audit logs, and reports |
| **DEVELOPER** | Create and manage experiments, feature flags, and integrations |
| **ADMIN** | Full access: user management, compliance exports, global settings |

Beyond the four base roles, admins can create **custom roles** with specific per-resource and per-action permissions. They can also grant **direct permission** to a user for a specific resource, with an optional expiry timestamp for temporary access.

See [RBAC API Reference](../api/rbac.md) for the full role and permission management API.

---

### How do API keys work?

API keys are used for SDK authentication and server-to-server calls. Unlike JWT tokens (which are user-session credentials), API keys are long-lived and scoped to specific operations.

Create an API key via `POST /api/v1/api-keys` with a name and desired scopes (`read`, `write`, `admin`). The full key value is shown only once at creation time — store it securely. To use it, pass the key in the `X-API-Key: <key>` header on all SDK requests.

Keys can be listed (without exposing the secret) and revoked at any time. See [API Key Management](../security/api-keys.md) for best practices.
