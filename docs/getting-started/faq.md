# Frequently Asked Questions

---

## General

### What is Experimently?

Experimently is a self-hosted experimentation platform for running A/B tests, feature flags, and controlled rollouts. It provides a complete solution for data-driven product development: design experiments, assign users to variants, track conversion events, run statistical analysis, and make shipping decisions — all in one platform.

The platform includes a REST API backend (FastAPI), a React management dashboard, client SDKs (JavaScript, Python, Java, React), AWS CDK infrastructure code, and Lambda functions for real-time event processing.

---

### Is it open source and self-hostable?

Yes. The platform is designed to be deployed in your own AWS account using the provided CDK infrastructure definitions. You own your data and control your deployment. There is no vendor lock-in and no data leaves your infrastructure.

Running `cdk deploy --all` from the `infrastructure/cdk/` directory provisions the AWS environment: the API and the dashboard as ECS Fargate services behind one Application Load Balancer, the Aurora PostgreSQL database, the Redis cache and Lambda functions. The dashboard starts on the `web:bootstrap` image you push first; the Deploy workflow does not yet roll releases onto it (#69). It does not create a CloudFront distribution. A checkout that also has `modules/` gets the real-time DynamoDB counters table and the Kinesis/OpenSearch/Glue data lake alongside them — see [AWS CDK Deployment](../self-hosting/cdk.md) for which stacks each profile deploys.

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
| CloudFront | Not created by the CDK. Only needed if you wire in the split-URL module's Lambda@Edge construct yourself |
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
| Alpha spending (O'Brien-Fleming, Pocock) | Not computed yet: the response's `alpha_spending` is empty; use the mSPRT, which is valid under continuous monitoring |
| CUPED (beta) | Variance reduction; the covariate is not yet a pre-experiment metric, so it reduces almost no variance today (#217) |
| Bayesian (Beta-Binomial) | Posterior credible intervals, Bayes factors, probability of superiority, ROPE |
| Multi-armed bandit | Thompson Sampling, UCB1, and Epsilon-Greedy adaptive traffic allocation |
| Dimensional analysis | Segment-level breakdowns with Bonferroni correction and heterogeneous treatment effect detection |
| Interaction detection (beta) | Jaccard overlap between experiments; the interaction, novelty and SUTVA analyses are not computed yet (#219) |

---

### What SDKs are available?

**Not yet published.** None of the packages below is on its registry yet, so installing them by
name fails today. Each SDK's page ([JavaScript](../sdk/javascript.md), [Python](../sdk/python.md),
[Java](../sdk/java.md), [React](../sdk/react.md)) says how to install it from this repository
instead.

| SDK | Package |
|-----|---------|
| JavaScript / TypeScript | `@getexperimently/js-sdk` (npm) |
| Python | `experimently` (PyPI) |
| Java / JVM | `com.getexperimently:experimently-sdk` (Maven/Gradle) |
| React | `@getexperimently/react-sdk` (npm) |

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

Not today. The warehouse endpoints have been removed, and warehouse analysis is being rebuilt (#312). See [Warehouse Analytics](../api/warehouse-analytics.md).

---

### How does CUPED variance reduction work?

CUPED (Controlled-experiment Using Pre-Experiment Data) reduces result noise by adjusting each user's observed metric by a term proportional to their pre-experiment behavior. The adjustment is computed using an OLS regression coefficient (`theta`) estimated from the control group.

With a covariate that predicts the outcome, lower variance means you reach statistical significance with fewer users, or detect smaller effects with the same sample size.

**Beta:** `GET /api/v1/results/{experiment_id}/cuped` does not yet use a pre-experiment metric as the covariate, so in this release it removes almost no variance, and its responses say so in `analysis_status` ([#217](https://github.com/getexperimently/experimently/issues/217)). See [CUPED documentation](../api/cuped.md).

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

API keys are used for SDK authentication and server-to-server calls. Unlike JWT tokens (which are user-session credentials), API keys are long-lived. Any active key authenticates every API-key route (flag evaluation, tracking) as the user who created it; its `scopes` do not narrow that. The one exception is the server-side local-evaluation routes (`GET /api/v1/sdk/ruleset`, `POST /api/v1/tracking/evaluations`), which require the `sdk:ruleset` scope.

Create an API key via `POST /api/v1/api-keys` with a name. The full key value is shown only once at creation time — store it securely. To use it, pass the key in the `X-API-Key: <key>` header on all SDK requests.

Keys can be listed (without exposing the secret) and revoked at any time. See [API Key Management](../security/api-keys.md) for best practices.
