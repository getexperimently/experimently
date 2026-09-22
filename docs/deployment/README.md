# Deployment Documentation

This directory contains all operational documentation for deploying and operating Experimently in production.

---

## Document Index

| Document | Audience | Description |
|----------|----------|-------------|
| [Deployment Guide](deployment-guide.md) | DevOps / Engineers | Step-by-step guide for deploying to production |
| [Rollback Runbook](rollback-runbook.md) | On-call Engineers | How to roll back a deployment in < 5 minutes |
| [Disaster Recovery](disaster-recovery.md) | SRE / DevOps | DR scenarios, runbooks, and recovery procedures |
| [Launch Checklist](launch-checklist.md) | All teams | Pre-launch approval checklist and Go/No-Go sign-off |
| [Secrets Management](secrets-management.md) | DevOps / Security | How secrets are stored, injected, and rotated |

---

## Quick Reference

### Deploy to Production

1. Create and push a git tag: `git tag v1.2.3 && git push origin v1.2.3`
2. Ensure **Release Gate** succeeded for the target commit/tag.
3. Go to **GitHub Actions** → **"Deploy to Production"** → **Run workflow** → enter the tag
   and pick the **profile** (see below)
4. Approve the deployment in the GitHub environment gate
5. Monitor progress in Slack `#deployments`

Full procedure: [deployment-guide.md](deployment-guide.md)

#### Which profile?

`Deploy to Production` asks for a `profile`, and the answer is a decision about
what production *is*, not a build detail:

| profile | image | compliance audit log |
|---------|-------|----------------------|
| `full` (default) | `backend/Dockerfile --target full`: `backend/` plus `modules/backend/` and the module-only dependencies | HMAC-SHA256 signed by the compliance module (`AuditSigningService`) |
| `core` | `--target core`: `backend/` only, no `modules/` directory at all | **unsigned** — `hooks.audit_signer` stays `NullAuditSigner`, every event is written with `hmac_signature = NULL`, and `verify()` reports those rows as intact |

Nothing at runtime flags the difference: `/health/ready` answers 200 either way
(it reports `profile`, it does not judge it) and `abort_if_modules_broken()`
only fires for a *broken* modules package, never for an absent one. So `core`
also requires ticking **`accept_unsigned_audit_log`**; the workflow refuses the
run otherwise, before it assumes the production AWS role.

The profile is the **API image's** only; this workflow builds no dashboard
image. It used to, and that step pushed to an ECR repository nothing creates,
so it never succeeded (#195). Production has no dashboard delivery path at all
at the moment — see #212, which is where the shape of one is being decided.
Until then, a core API deployed here is not paired with a dashboard build by
anything, so nothing enforces that the two agree on a profile.

`full` needs one secret `core` does not: **`/prod/experimentation/audit-hmac-key`**
(→ `AUDIT_HMAC_KEY`). `modules.register(hooks)` builds the modules' settings as
its very first step and their validator rejects the shipped dev default in
staging and production, so a full image without it never registers the modules
— `abort_if_modules_broken()` refuses to start the API and
`require_modules_or_absent()` fails every `alembic` command, including the
migration task. The workflow's **"Required secrets exist for this profile"**
step checks for it (and for the four every profile needs) before it builds
anything, so a missing secret is a red job, not a crash loop. Create it with
[secrets-management.md](secrets-management.md).

---

### Emergency Rollback (target: < 5 minutes)

**Method 1 — GitHub Actions (preferred):**
Go to **GitHub Actions** → **"Rollback Production"** → enter the previous task definition ARN and reason

**Method 2 — AWS CLI (fastest):**
```bash
PREV_TASK_DEF="arn:aws:ecs:us-west-2:ACCOUNT_ID:task-definition/experimentation-backend-prod:43"

aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-backend-prod \
  --task-definition $PREV_TASK_DEF \
  --force-new-deployment

aws ecs wait services-stable \
  --cluster experimentation-prod \
  --services experimentation-backend-prod
```

How to find the previous task definition ARN:
```bash
aws ecs list-task-definitions \
  --family-prefix experimentation-backend-prod \
  --sort DESC \
  --max-results 5 \
  --query 'taskDefinitionArns'
```

Full rollback procedure: [rollback-runbook.md](rollback-runbook.md)

---

### Database Migration

1. Go to **GitHub Actions** → **"Database Migration"**
2. Select environment (`staging` or `production`), direction (`upgrade` or `downgrade`), and target (`head` or `-1`)
3. Monitor the ECS migration task logs in CloudWatch log group `/ecs/experimentation-migration-prod`

---

### Health Checks

```bash
# API health
curl https://api.experimentation.example.com/health
# Expected: {"status": "healthy", "db": "ok", "redis": "ok", "version": "X.Y.Z"}

# ECS service status
aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-backend-prod \
  --query 'services[0].{Running:runningCount,Desired:desiredCount,Status:status}'

# Check recent ECS service events
aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-backend-prod \
  --query 'services[0].events[:5]'
```

---

## Required GitHub Secrets

These secrets must be set in the GitHub repository under **Settings → Secrets and variables → Actions → Secrets** in the `production` environment before any deployment can succeed.

| Secret | Description |
|--------|-------------|
| `DEV_AWS_ROLE_ARN` | IAM role ARN assumed via GitHub OIDC for dev frontend deploy |
| `PROD_AWS_ROLE_ARN` | IAM role ARN assumed via GitHub OIDC for production deploy/rollback |
| `STAGING_AWS_ROLE_ARN` | IAM role ARN assumed via GitHub OIDC for staging DB migrations |
| `PROD_API_URL` | Production API base URL (e.g., `https://api.experimentation.example.com`) |
| `PROD_SMOKE_TEST_API_KEY` | API key (`X-API-Key` header) used by automated smoke tests |
| `PROD_SMOKE_TEST_TOKEN` | JWT Bearer token used by automated smoke tests |
| `SLACK_BOT_TOKEN` | Slack bot OAuth token for `#deployments` notifications |
| `PROD_PRIVATE_SUBNET_IDS` | Comma-separated private subnet IDs for migration task VPC configuration |
| `PROD_ECS_SG_ID` | Security group ID attached to ECS tasks |

---

## Required AWS Secrets Manager Secrets

These secrets must be populated before the first deployment. See [secrets-management.md](secrets-management.md) for creation commands.

| Secret Path | Injected as | Description |
|-------------|-------------|-------------|
| `/prod/experimentation/db-password` | `POSTGRES_PASSWORD` | Aurora PostgreSQL application user password |
| `/prod/experimentation/jwt-secret` | `SECRET_KEY` | JWT signing secret (minimum 32 characters) |
| `/prod/experimentation/redis-url` | `REDIS_URL` | Redis connection URL with auth token |
| `/prod/experimentation/first-superuser-password` | `FIRST_SUPERUSER_PASSWORD` | Password for the first administrator; the default `admin` is refused in production |
| `/prod/experimentation/audit-hmac-key` | `AUDIT_HMAC_KEY` | **`profile: full` only** — signs the compliance audit log; the modules refuse to register without it |
| `/prod/experimentation/cognito-config` | — | Cognito user pool ID and client ID (JSON) |

Every row except `cognito-config` is injected by the ECS task definitions
(`infrastructure/cdk/stacks/fargate_service_stack.py` and
`migration_task_stack.py`) and is one the application refuses to start without:
the image ships no `.env` file, so the task definition is the only source.
`Deploy to Production` fails in **Pre-deployment Checks** if one is missing.

---

## Infrastructure Stack Deployment Order

CDK stacks must be deployed in this order. Each stack depends on outputs from the previous.

These are stack **ids** — what `cdk deploy` takes, and what `cdk list` prints.
`<env>` is `dev`, `staging` or `prod`.

1. `experimentation-auth-<env>` — Cognito user pool, client and groups
2. `experimentation-vpc-<env>` — VPC, subnets, NAT gateways
3. `experimentation-dynamodb-<env>` — the five DynamoDB tables
4. `experimentation-database-<env>` — Aurora PostgreSQL cluster
5. `experimentation-redis-<env>` — ElastiCache Redis replication group
6. `experimentation-compute-<env>` — ECS cluster, task security group, database-access Lambda
7. `experimentation-monitoring-<env>` — CloudWatch dashboards, alarms, log groups
8. `experimentation-fargate-<env>` — Fargate service, ALB, CodeDeploy blue/green
9. `experimentation-migrations-<env>` — ECS task definition for Alembic (plural)

With `modules/` present, three more: `experimentation-dynamodb-counters-<env>`,
`experimentation-analytics-<env>` and `experimentation-glue-etl-<env>`.

Deploy all at once (CDK handles ordering):
```bash
cd infrastructure/cdk
cdk deploy --all --require-approval never
```

---

## Useful AWS CLI Commands

```bash
# Watch ECS task replacement during deployment
watch -n 5 'aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-backend-prod \
  --query "services[0].{Running:runningCount,Desired:desiredCount,TaskDef:taskDefinition}"'

# Check recent application errors
aws logs filter-log-events \
  --log-group-name /experimentation-platform/api \
  --filter-pattern '"level":"ERROR"' \
  --start-time $(date -u -d '15 minutes ago' +%s000)

# Check Aurora cluster status
aws rds describe-db-clusters \
  --db-cluster-identifier experimentation-prod \
  --query 'DBClusters[0].{Status:Status,Endpoint:Endpoint,LatestRestorableTime:LatestRestorableTime}'

# List recent task definitions (useful during rollback)
aws ecs list-task-definitions \
  --family-prefix experimentation-backend-prod \
  --sort DESC \
  --max-results 5 \
  --query 'taskDefinitionArns'
```

---

## Recovery Time Objectives

| Scenario | RTO | RPO | See |
|----------|-----|-----|-----|
| Single ECS task crash | ~60 seconds | 0 | DR Plan — Scenario 1 |
| All ECS tasks down | ~5 minutes | 0 | DR Plan — Scenario 2 |
| Application rollback | < 5 minutes | 0 | Rollback Runbook |
| Aurora primary failure | ~2 minutes | 0 | DR Plan — Scenario 3 |
| Aurora cluster restore from snapshot | ~30 minutes | 5 minutes | DR Plan — Scenario 4 |
| Full region failover | ~60 minutes | 5 minutes | DR Plan — Scenario 6 |
