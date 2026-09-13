# Deployment Guide — Experimentation Platform

**Version:** 1.0
**Date:** March 2026
**Audience:** DevOps Engineers, Backend Engineers
**Target:** Production (AWS ECS Fargate / Aurora / ElastiCache)

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [First-Time Setup (One-Time)](#2-first-time-setup-one-time)
3. [Standard Deployment Procedure](#3-standard-deployment-procedure)
4. [Pre-Deployment Checklist](#4-pre-deployment-checklist)
5. [Post-Deployment Verification](#5-post-deployment-verification)
6. [Deployment Architecture](#6-deployment-architecture)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Prerequisites

Before you can deploy, verify all of the following are in place.

### 1.1 AWS Credentials

The deploying identity must have the `ExperimentationPlatformDeployRole` IAM role assumed or be attached to a policy that grants:

- `ecs:UpdateService`, `ecs:RegisterTaskDefinition`, `ecs:DescribeServices`
- `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`, `ecr:PutImage`
- `secretsmanager:GetSecretValue` (scoped to `/prod/experimentation/*`)
- `cloudwatch:PutMetricData`, `logs:CreateLogGroup`, `logs:PutLogEvents`
- `codedeploy:CreateDeployment`, `codedeploy:GetDeployment`

Verify your identity:

```bash
aws sts get-caller-identity
# Expected: ARN containing the deployment role or CI user
```

### 1.2 GitHub Actions Secrets

All of the following secrets must be set in the GitHub repository under **Settings → Secrets and variables → Actions → Secrets** (environment: `production`):

| Secret | Description |
|--------|-------------|
| `AWS_ACCESS_KEY_ID` | AWS deployment role access key |
| `AWS_SECRET_ACCESS_KEY` | AWS deployment role secret key |
| `PROD_API_URL` | Production API base URL (e.g., `https://api.experimentation.example.com`) |
| `PROD_SMOKE_TEST_API_KEY` | API key (`X-API-Key` header) used by smoke tests |
| `PROD_SMOKE_TEST_TOKEN` | JWT Bearer token used by smoke tests |
| `SLACK_BOT_TOKEN` | Slack bot token for `#deployments` notifications |
| `PROD_PRIVATE_SUBNET_IDS` | Comma-separated private subnet IDs for migration task VPC config |
| `PROD_ECS_SG_ID` | Security group ID attached to ECS tasks |

To verify a secret is set (without revealing its value):

```bash
gh secret list --env production
```

### 1.3 ECR Repositories

Two ECR repositories must exist before the first deployment:

```bash
# Create backend image repository
aws ecr create-repository \
  --repository-name experimentation-backend \
  --region us-west-2 \
  --image-scanning-configuration scanOnPush=true

# Create migration image repository
aws ecr create-repository \
  --repository-name experimentation-migrations \
  --region us-west-2 \
  --image-scanning-configuration scanOnPush=true

# Verify both exist
aws ecr describe-repositories \
  --repository-names experimentation-backend experimentation-migrations \
  --region us-west-2 \
  --query 'repositories[*].{Name:repositoryName,URI:repositoryUri}'
```

### 1.4 ECS Cluster and Services Deployed

CDK stacks must already be deployed (see [Section 2](#2-first-time-setup-one-time)):

```bash
# Verify cluster exists
aws ecs describe-clusters \
  --clusters experimentation-prod \
  --query 'clusters[0].{Name:clusterName,Status:status,ActiveServices:activeServicesCount}'

# Verify backend service exists
aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-backend-prod \
  --query 'services[0].{Name:serviceName,Status:status,RunningCount:runningCount}'
```

### 1.5 Secrets Manager Secrets Populated

The following secrets must exist and contain valid values before the application can start:

| Secret Path | Description |
|-------------|-------------|
| `/prod/experimentation/db-password` | Aurora PostgreSQL password for the application user |
| `/prod/experimentation/jwt-secret` | JWT signing secret (minimum 32 characters) |
| `/prod/experimentation/redis-url` | Redis connection URL including auth token |
| `/prod/experimentation/cognito-config` | Cognito user pool ID and client ID (JSON) |

See [Secrets Management](secrets-management.md) for how to create these.

### 1.6 GitHub Environments Configured

Two GitHub environments must be configured with required reviewers:

- **staging** — no required reviewers (auto-deploys on push to `main`)
- **production** — requires at least 1 reviewer from the `production-approvers` team

Configure at: **Settings → Environments → production → Required reviewers**

---

## 2. First-Time Setup (One-Time)

Run these steps exactly once when provisioning a new production environment. They are not part of normal deployments.

### Step 1: Bootstrap CDK

```bash
cd /path/to/experimentation-platform/infrastructure/cdk

# Bootstrap the AWS account/region for CDK
cdk bootstrap aws://ACCOUNT_ID/us-west-2

# Verify bootstrap was successful
aws cloudformation describe-stacks \
  --stack-name CDKToolkit \
  --query 'Stacks[0].StackStatus'
```

### Step 2: Deploy Infrastructure Stacks in Order

Order matters — each stack depends on outputs from the previous one.

```bash
cd infrastructure/cdk

# 1. VPC and networking
cdk deploy ExperimentationVpcStack --require-approval never

# 2. Aurora PostgreSQL database
cdk deploy ExperimentationDatabaseStack --require-approval never

# 3. ElastiCache Redis
cdk deploy ExperimentationRedisStack --require-approval never

# 4. ECS cluster, task roles, security groups
cdk deploy ExperimentationComputeStack --require-approval never

# 5. ECS Fargate service and ALB
cdk deploy ExperimentationFargateServiceStack --require-approval never

# 6. ECS migration task definition
cdk deploy ExperimentationMigrationTaskStack --require-approval never

# 7. CloudWatch dashboards, alarms, log groups
cdk deploy ExperimentationMonitoringStack --require-approval never

# Or deploy all at once (respects dependency order)
cdk deploy --all --require-approval never
```

Verify all stacks are in `CREATE_COMPLETE` or `UPDATE_COMPLETE`:

```bash
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query 'StackSummaries[?contains(StackName, `Experimentation`)].{Name:StackName,Status:StackStatus}'
```

### Step 3: Populate Secrets Manager

See [Secrets Management](secrets-management.md) for the complete commands. Summary:

```bash
# Database password (generated securely)
aws secretsmanager create-secret \
  --name /prod/experimentation/db-password \
  --secret-string "$(openssl rand -base64 32)"

# JWT signing secret
aws secretsmanager create-secret \
  --name /prod/experimentation/jwt-secret \
  --secret-string "$(openssl rand -base64 48)"

# Redis URL (replace placeholders)
aws secretsmanager create-secret \
  --name /prod/experimentation/redis-url \
  --secret-string "redis://:REDIS_AUTH_TOKEN@experimentation-redis.prod.internal:6379/0"

# Cognito config
aws secretsmanager create-secret \
  --name /prod/experimentation/cognito-config \
  --secret-string '{"user_pool_id":"us-west-2_XXXXX","client_id":"XXXXXXXXXXXXX"}'
```

### Step 4: Create ECR Repositories

```bash
# See Section 1.3 above for commands
aws ecr create-repository --repository-name experimentation-backend --region us-west-2
aws ecr create-repository --repository-name experimentation-migrations --region us-west-2
```

### Step 5: Configure GitHub Environments and Required Approvers

1. Go to **GitHub → Settings → Environments → New environment → production**
2. Add required reviewers from the engineering leads group
3. Set deployment branches to `main` only
4. Add all secrets listed in Section 1.2 to the `production` environment

### Step 6: Run Initial Database Migration

Before the first application deployment, run database migrations:

```bash
# Via GitHub Actions: "Database Migration" workflow
# Environment: production
# Direction: upgrade
# Target: head
```

Or manually from a bastion host with VPC access:

```bash
source venv/bin/activate
export POSTGRES_DB=experimentation
export POSTGRES_SCHEMA=experimentation
export DATABASE_URL="postgresql://appuser:PASSWORD@experimentation-prod.cluster-XXXXX.us-west-2.rds.amazonaws.com:5432/experimentation"

python -m alembic -c backend/app/db/alembic.ini upgrade heads
python -m alembic -c backend/app/db/alembic.ini current
```

---

## 3. Standard Deployment Procedure

This is the procedure for every routine production deployment.

### Step 1: Create and Push a Git Tag

Tags are the unit of deployment. Never deploy from a branch directly.

```bash
# Ensure you are on main with all changes merged
git checkout main
git pull origin main

# Create a semantic version tag
git tag v1.2.3

# Push the tag to trigger the deployment workflow
git push origin v1.2.3
```

Versioning convention: `v{MAJOR}.{MINOR}.{PATCH}`
- MAJOR: Breaking API changes
- MINOR: New features, backward compatible
- PATCH: Bug fixes, no new features

### Step 2: Trigger the Deployment Workflow

1. Navigate to **GitHub → Actions → "Deploy to Production"**
2. Click **Run workflow**
3. Select the tag you just pushed (e.g., `v1.2.3`)
4. Click **Run workflow**

The deployment will pause at the **Approval Gate** and wait for a reviewer to approve. A notification is sent to `#deployments` in Slack.

### Step 3: Approve the Deployment

A reviewer (not the person who triggered the deployment) must:

1. Go to the GitHub Actions run and click **Review deployments**
2. Verify the pre-deployment checks passed (all green)
3. Click **Approve and deploy**

The deployment then proceeds through these automated stages:

| Stage | Description | Typical Duration |
|-------|-------------|-----------------|
| Pre-deployment checks | Verify no active incidents, backup exists | ~2 min |
| Build Docker image | Build and tag the backend image | ~5 min |
| Security scan | ECR image scan for CVEs | ~2 min |
| Push to ECR | Push to `experimentation-backend:v1.2.3` | ~1 min |
| Database migration | Run `alembic upgrade heads` via ECS task | ~2 min |
| Deploy to ECS | Register new task definition, update service | ~3 min |
| Wait for stabilization | ECS replaces tasks (rolling or blue/green) | ~3 min |
| Smoke tests | Hit health, experiments list, tracking endpoints | ~1 min |
| Post-deployment notification | Slack message with status | ~30 sec |

**Total: ~20 minutes**

### Step 4: Monitor the Deployment

Watch progress in GitHub Actions. Simultaneously:

```bash
# Watch ECS service events in real time
aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-backend-prod \
  --query 'services[0].events[:5]'

# Watch running task count (should stay >= 3 during rolling deploy)
watch -n 10 'aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-backend-prod \
  --query "services[0].{Running:runningCount,Pending:pendingCount,Desired:desiredCount}"'
```

Watch the **#deployments** Slack channel for automated progress updates.

### Step 5: Verify Smoke Tests Pass

The workflow automatically runs smoke tests after deployment. Verify:

- `GET /health` returns `{"status": "healthy"}`
- `GET /api/v1/experiments` returns `200` with a list
- `POST /api/v1/tracking/assign` returns `200` or `201`

If smoke tests fail, the workflow automatically triggers rollback.

### Step 6: Check CloudWatch Dashboards

After deployment stabilizes (~5 min post-deploy):

```bash
# Quick CLI check: error rate in last 10 min
aws cloudwatch get-metric-statistics \
  --namespace ExperimentationPlatform \
  --metric-name api.error_rate \
  --period 300 \
  --start-time $(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --statistics Average \
  --query 'Datapoints[*].Average'
```

Navigate to CloudWatch → Dashboards → `ExperimentationPlatform-Production` and verify:

- Error rate < 0.1%
- p99 latency < 500ms
- CPU utilization < 70%
- Active ECS tasks = 3 (or more if auto-scaled)

---

## 4. Pre-Deployment Checklist

Complete this checklist before triggering any production deployment.

### Mandatory Checks

- [ ] All tests passing on `main` branch (check GitHub Actions CI badge)
- [ ] Security scan passing — no new CRITICAL or HIGH CVEs (EP-018 audit complete)
- [ ] Database backup exists and was verified by the workflow
- [ ] No active P0 or P1 incidents (check `#incidents` Slack channel and PagerDuty)
- [ ] Team notified in `#deployments`: "Deploying v1.2.3 at HH:MM UTC"
- [ ] Deployment is during office hours (09:00–17:00 local time), unless emergency
- [ ] Change request approved in your change management system (if required)
- [ ] Staging deployment of the same tag succeeded

### Database Migration Checks (if migration is included)

- [ ] Migration tested in staging — no errors, no data loss
- [ ] Migration is backward-compatible (old code can run against new schema)
- [ ] `alembic history` on staging shows expected migration chain
- [ ] Rollback migration (`alembic downgrade -1`) tested in staging

### Post-Incident or Post-Hotfix Deploys

- [ ] Root cause of previous incident documented
- [ ] Fix verified in staging
- [ ] On-call engineer standing by for 30 min post-deployment

---

## 5. Post-Deployment Verification

Run these checks after every deployment, before declaring success.

### 5.1 Health and Availability

```bash
export API_URL="https://api.experimentation.example.com"
export API_KEY="your-smoke-test-api-key"
export TOKEN="your-smoke-test-token"

# Health check
curl -f "$API_URL/health"
# Expected: {"status": "healthy", "version": "1.2.3", "db": "ok", "redis": "ok"}

# Experiments endpoint
curl -f -H "Authorization: Bearer $TOKEN" "$API_URL/api/v1/experiments"
# Expected: 200 with {"items": [...], "total": N}

# Tracking endpoint (assignment)
curl -f -X POST \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"smoke-test-user","experiment_key":"smoke-test","context":{}}' \
  "$API_URL/api/v1/tracking/assign"
# Expected: 200 or 404 (experiment not found is acceptable; 500 is not)
```

### 5.2 ECS Service Health

```bash
# Verify desired task count is running
aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-backend-prod \
  --query 'services[0].{Running:runningCount,Desired:desiredCount,Pending:pendingCount,Deployments:deployments[*].{Status:status,TaskDef:taskDefinition}}'
```

Expected: `Running == Desired`, no tasks in `Pending`, deployment status `PRIMARY`.

### 5.3 CloudWatch Error Rate

```bash
# Check error rate for last 5 minutes
aws cloudwatch get-metric-statistics \
  --namespace ExperimentationPlatform \
  --metric-name HTTPErrors5xx \
  --period 300 \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --statistics Sum
```

Pass criteria: error rate < 0.1% of total requests, p99 latency < 500ms.

### 5.4 Auto-Scaling Verification

```bash
# Verify auto-scaling policy is attached
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs \
  --resource-id service/experimentation-prod/experimentation-backend-prod
```

Expected: CPU scale-out policy at 70%, memory scale-out at 80%, min 3 tasks, max 10 tasks.

### 5.5 Declare Success

When all verifications pass:

1. Post to `#deployments`: ":white_check_mark: v1.2.3 deployed successfully. Error rate nominal, latency nominal."
2. Update the status page to "Operational" if it was in maintenance mode.
3. Close any deployment-related change request ticket.

---

## 6. Deployment Architecture

```
GitHub Actions
      |
      v (git tag push)
┌─────────────────────────────────────────────────────┐
│   Deploy to Production Workflow                     │
│                                                     │
│  1. Pre-checks     → Verify backups, no incidents   │
│  2. Build          → Docker image + ECR push        │
│  3. DB Migration   → ECS run-task (migration image) │
│  4. ECS Deploy     → Update service task definition │
│  5. Smoke Tests    → Hit /health + key endpoints    │
│  6. Notify         → Slack #deployments             │
└─────────────────────────────────────────────────────┘
      |
      v
┌─────────────────────────────────────────────────────┐
│   ECS Fargate — experimentation-prod cluster        │
│                                                     │
│  Service: experimentation-backend-prod              │
│  Tasks: 3 (min) → 10 (max)                          │
│  Image: ACCOUNT.dkr.ecr.us-west-2.amazonaws.com/   │
│         experimentation-backend:v1.2.3              │
│                                                     │
│  Secrets injected at runtime from Secrets Manager:  │
│    DATABASE_URL   ← /prod/experimentation/db-*      │
│    JWT_SECRET     ← /prod/experimentation/jwt-*     │
│    REDIS_URL      ← /prod/experimentation/redis-*   │
└────────────────────┬────────────────────────────────┘
                     |
          ┌──────────┴──────────┐
          v                     v
    Aurora PostgreSQL      ElastiCache Redis
    (experimentation-prod) (experimentation-redis-prod)
```

---

## 7. Troubleshooting

### "Deployment stuck in Pending"

```bash
# Check why tasks are not starting
aws ecs describe-tasks \
  --cluster experimentation-prod \
  --tasks $(aws ecs list-tasks --cluster experimentation-prod --query 'taskArns[0]' --output text) \
  --query 'tasks[0].{Status:lastStatus,StopCode:stopCode,StopReason:stoppedReason,Containers:containers[*].{Name:name,Status:lastStatus,Reason:reason}}'
```

Common causes: secrets not found (check Secrets Manager paths), image not found (check ECR), IAM permission denied (check task role).

### "Migration task failed"

```bash
# Get migration task logs
aws logs get-log-events \
  --log-group-name /ecs/experimentation-migration-prod \
  --log-stream-name $(aws logs describe-log-streams \
    --log-group-name /ecs/experimentation-migration-prod \
    --order-by LastEventTime --descending \
    --query 'logStreams[0].logStreamName' --output text)
```

If migration failed mid-run, run the rollback migration before re-deploying (see [Rollback Runbook](rollback-runbook.md)).

### "Smoke tests failing after deployment"

If smoke tests fail, the workflow triggers automatic rollback. If you need to investigate first:

```bash
# Check recent application logs for errors
aws logs filter-log-events \
  --log-group-name /experimentation-platform/api \
  --filter-pattern '"level":"ERROR"' \
  --start-time $(date -u -d '10 minutes ago' +%s000)
```

### "ECS service not stabilizing"

If ECS tasks keep stopping and restarting:

```bash
# Check stopped task reasons (last 10 stopped tasks)
aws ecs list-tasks \
  --cluster experimentation-prod \
  --desired-status STOPPED \
  --query 'taskArns[:10]'

# Get stop reason for a specific task
aws ecs describe-tasks \
  --cluster experimentation-prod \
  --tasks <task-arn> \
  --query 'tasks[0].{StopReason:stoppedReason,ContainerReason:containers[0].reason}'
```
