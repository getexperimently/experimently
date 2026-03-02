# Deployment Documentation

This directory contains all operational documentation for deploying and operating the Experimentation Platform in production.

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
2. Go to **GitHub Actions** → **"Deploy to Production"** → **Run workflow** → enter the tag
3. Approve the deployment in the GitHub environment gate
4. Monitor progress in Slack `#deployments`

Full procedure: [deployment-guide.md](deployment-guide.md)

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
| `AWS_ACCESS_KEY_ID` | AWS deployment role access key ID |
| `AWS_SECRET_ACCESS_KEY` | AWS deployment role secret access key |
| `PROD_API_URL` | Production API base URL (e.g., `https://api.experimentation.example.com`) |
| `PROD_SMOKE_TEST_API_KEY` | API key (`X-API-Key` header) used by automated smoke tests |
| `PROD_SMOKE_TEST_TOKEN` | JWT Bearer token used by automated smoke tests |
| `SLACK_BOT_TOKEN` | Slack bot OAuth token for `#deployments` notifications |
| `PROD_PRIVATE_SUBNET_IDS` | Comma-separated private subnet IDs for migration task VPC configuration |
| `PROD_ECS_SG_ID` | Security group ID attached to ECS tasks |

---

## Required AWS Secrets Manager Secrets

These secrets must be populated before the first deployment. See [secrets-management.md](secrets-management.md) for creation commands.

| Secret Path | Description |
|-------------|-------------|
| `/prod/experimentation/db-password` | Aurora PostgreSQL application user password |
| `/prod/experimentation/jwt-secret` | JWT signing secret (minimum 32 characters) |
| `/prod/experimentation/redis-url` | Redis connection URL with auth token |
| `/prod/experimentation/cognito-config` | Cognito user pool ID and client ID (JSON) |

---

## Infrastructure Stack Deployment Order

CDK stacks must be deployed in this order. Each stack depends on outputs from the previous.

1. `ExperimentationVpcStack` — VPC, subnets, NAT gateways
2. `ExperimentationDatabaseStack` — Aurora PostgreSQL cluster
3. `ExperimentationRedisStack` — ElastiCache Redis replication group
4. `ExperimentationComputeStack` — ECS cluster, Lambda functions, IAM roles
5. `ExperimentationFargateServiceStack` — ECS Fargate service and Application Load Balancer
6. `ExperimentationMigrationTaskStack` — ECS task definition for Alembic migrations
7. `ExperimentationMonitoringStack` — CloudWatch dashboards, alarms, log groups

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
