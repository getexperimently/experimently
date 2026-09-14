# Experimently Documentation

## Start Here

| Guide | Audience | Description |
|-------|----------|-------------|
| [Quick Start](getting-started/quick-start.md) | Everyone | Zero to first experiment in 30 minutes |
| [User Guide](guides/user-guide.md) | Product / Analysts | Designing, running, and interpreting experiments |
| [Technical Guide](architecture/technical-guide.md) | Engineers | Architecture, data models, implementation details |
| [SDK Guide](sdk-guide.md) | Engineers | Endpoint contract for SDKs and per-SDK status |
| [ShopLab Demo](../demo/shoplab/README.md) | Everyone | A storefront running five live experiments through the React SDK (`./demo/setup-local.sh`) |
| [Testing Guide](development/testing-guide.md) | Engineers | Writing and running tests |

---

## API Reference

| Doc | Description |
|-----|-------------|
| [Endpoints](api/endpoints.md) | Complete REST API reference |
| [API Specs](api/specs.md) | OpenAPI request/response schemas |
| [RBAC](api/rbac.md) | Role-based access control API |
| [Data Export](api/data-export.md) | CSV/JSON streaming export endpoints |

### Advanced Analytics APIs
| Doc | Description |
|-----|-------------|
| [Sequential Testing](api/sequential-testing.md) | mSPRT early stopping, always-valid confidence intervals |
| [CUPED](api/cuped.md) | Variance reduction using pre-experiment covariates |
| [Multi-Armed Bandit](api/multi-armed-bandit.md) | Thompson Sampling, UCB1, Epsilon-Greedy algorithms |
| [Dimensional Analysis](api/dimensional-analysis.md) | Segment breakdowns with Bonferroni correction |
| [Interaction Detection](api/interaction-detection.md) | Cross-experiment overlap and interference detection |

### Platform Capabilities
| Doc | Description |
|-----|-------------|
| [Mutual Exclusion & Holdout](api/mutual-exclusion-groups.md) | Prevent experiment conflicts, global holdout configuration |
| [Warehouse Analytics](api/warehouse-analytics.md) | Snowflake, BigQuery, Redshift connector setup and sync |
| [Audit Logging & Bulk Toggle](api/audit-logging.md) | Audit trail, SSE stream, bulk feature flag operations |
| [Alerting](api/alerting.md) | Slack and email notifications for platform events |

### Developer & Integration Guides
| Doc | Description |
|-----|-------------|
| [MCP Server](mcp-server.md) | AI coding assistant integration, experiment design tools |
| [Experiment Wizard](guides/experiment-wizard.md) | No-code 5-step experiment builder |

---

## SDKs

| SDK | Description |
|-----|-------------|
| [SDK Guide](sdk-guide.md) | Python and JavaScript SDK overview |
| [Java SDK](sdk/java.md) | JVM SDK with Spring Boot auto-configuration, LRU cache, MD5 hashing |
| [React SDK](sdk/react.md) | React hooks, context provider, HOC, SSR/Next.js support |
| [Go SDK](sdk/go.md) | Go SDK with local evaluation, context cancellation, goroutine safety |
| [iOS SDK](sdk/ios.md) | Swift SDK with async/await, offline fallback, SwiftUI integration |
| [Android SDK](sdk/android.md) | Kotlin SDK with Coroutines, OkHttp, Compose integration |

---

## Getting Started

- [Quick Start](getting-started/quick-start.md) — full setup in 30 minutes
- [Requirements](getting-started/requirements.md) — Python, Node.js, Docker, AWS CLI versions
- [Environment Setup](getting-started/environment-setup.md) — `.env` configuration
- [Docker Guide](getting-started/docker-guide.md) — local Postgres, Redis, LocalStack
- [Python Virtual Environment](getting-started/python-virtual-env-setup.md)
- [Pre-commit Hooks](getting-started/pre-commit-hooks.md)
- [VSCode Settings](getting-started/vscode-settings.md)

---

## Architecture

- [Overview](architecture/overview.md) — AWS architecture, component diagram
- [Technical Guide](architecture/technical-guide.md) — implementation details, subsystems
- [Models](architecture/models.md) — SQLAlchemy data model reference
- [Models Overview](architecture/models-overview.md) — quick reference for entity relationships

---

## Authentication

- [Auth Developer Docs](auth/auth-developer-docs.md) — Cognito JWT, middleware, auth service
- [Auth Flow Diagrams](auth/flow.md) — registration, login, password reset, token refresh
- [Auth Environment Variables](auth/auth-environment-variables.md) — Cognito configuration
- [Auth User Guide](auth/auth-user-guide.md) — registration, login, password policies
- [Cognito Testing](auth/cognito-auth-testing.md) — testing auth locally
- [SSO](auth/sso.md) — SAML 2.0 and OIDC setup for Okta, Azure AD, Google, GitHub (the `sso` module)

---

## Development

- [Guidelines](development/guidelines.md) — coding standards, git workflow, TDD
- [Testing Guide](development/testing-guide.md) — unit, integration, E2E, contract tests
- [Dependency Injection](development/dependency-injection.md) — FastAPI deps.py patterns
- [Workflow Explanation](development/workflow-explanation.md) — GitHub Actions CI
- [Database Migrations](development/database/migrations.md) — Alembic workflow
- [Database Usage](development/database/usage.md) — Aurora, DynamoDB, Redis patterns
- [Database Backup](development/database/backup.md) — backup and recovery procedures

---

## Deployment & Operations

- [Deployment Guide](deployment/deployment-guide.md) — ECS Fargate, Blue/Green deployment
- [Launch Checklist](deployment/launch-checklist.md) — pre-launch go/no-go checklist
- [Rollback Runbook](deployment/rollback-runbook.md) — rollback decision tree and procedures
- [Disaster Recovery](deployment/disaster-recovery.md) — RTO/RPO, failure scenarios
- [Secrets Management](deployment/secrets-management.md) — AWS Secrets Manager, rotation
- [Route 53 Setup](deployment/AWS_ROUTE53_DEPLOYMENT.md) — DNS configuration

---

## Security

- [Security Architecture](security-architecture.md) — system security design
- [Threat Model](security/threat-model.md) — threat scenarios and countermeasures
- [Security Policies](security/security-policies.md) — access control, data protection
- [Hardening Changes](security/hardening-changes.md) — WAF, headers, rate limiting
- [GDPR Compliance](security/gdpr-compliance-checklist.md) — data privacy checklist
- [Incident Response](security/incident-response-plan.md) — severity levels, response process

---

## Monitoring

- [Monitoring Guide](monitoring/monitoring-guide.md) — Prometheus, structured logging, CloudWatch
- [Setup Guide](monitoring/setup-guide.md) — initial monitoring setup
- [Dashboard Reference](monitoring/dashboard-reference.md) — CloudWatch dashboard widgets
- [Log Insights Queries](monitoring/log-insights-queries.md) — common query patterns
- [Troubleshooting](monitoring/troubleshooting-guide.md) — missing metrics, slow queries, alerts

---

## Infrastructure

- [Aurora PostgreSQL](infrastructure/aurora-postgres-readme.md) — RDS CDK stack
- [DynamoDB](infrastructure/dynamodb-readme.md) — table schemas, access patterns
- [Redis / ElastiCache](infrastructure/redis-summary.md) — caching strategy
- [CloudWatch Setup](infrastructure/cloudwatch-setup.md) — log groups, agent config
- [IAM Setup](infrastructure/aws-iam-setup.md) — roles and permissions
- [Network Security](infrastructure/network-security-readme.md) — VPC, WAF, ALB
- [VPC Stack](infrastructure/vpc-stack-implementation.md) — CDK networking stack

---

## Planning records

- [Modules](getting-started/modules.md) — the core and full profiles, and what each module adds
- `planning/go-to-market/` — the earlier commercial strategy (design partners, paid tiers), superseded on
  2026-09-12 by the decision to be fully open source under Apache-2.0; kept as a record, see
  [planning/open-core-launch-plan-2026-09.md](planning/open-core-launch-plan-2026-09.md)
