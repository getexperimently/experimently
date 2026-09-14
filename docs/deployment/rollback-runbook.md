# Rollback Runbook — Experimently

**Version:** 1.0
**Date:** March 2026
**Audience:** On-call Engineers
**Time Target:** < 5 minutes from decision to rollback complete

---

## Decision Tree: When to Rollback

Use this tree to decide your response within the first 2 minutes of an issue. When in doubt, roll back. Hotfixes are only appropriate for simple one-line changes that can be safely deployed without a full deployment cycle.

```
Post-deployment issue detected
          |
          v
Is any of the following true?
  - Health check /health returning non-200
  - 5xx error rate > 5% (vs. pre-deploy baseline)
  - p99 API latency > 5000ms
  - Data corruption detected (missing rows, wrong values)
  - ECS tasks crash-looping (stopped reason in logs)
          |
    NO ---+--- YES
          |         |
          |         v
          |   Is there a workaround (feature flag at 0%)?
          |         |
          |   YES --+-- NO ──→ ROLLBACK IMMEDIATELY (go to Method 1)
          |         |
          |         v
          |   Can a hotfix be written and tested in < 30 min?
          |         |
          |   YES --+-- NO ──→ ROLLBACK IMMEDIATELY (go to Method 1)
          |         |
          |         v
          |   Is it a database schema issue?
          |         |
          |   YES ──→ ROLLBACK APPLICATION + DATABASE (Method 1 + DB Rollback section)
          |   NO  ──→ HOTFIX (deploy new tag following standard procedure)
          |
          v
   Monitor for 5 more minutes; page if it worsens
```

**Rollback triggers — no deliberation required:**

| Condition | Threshold | Action |
|-----------|-----------|--------|
| Health check failure | `/health` returning non-200 | Immediate rollback |
| 5xx error rate spike | > 5% of requests over 2 min | Immediate rollback |
| p99 API latency | > 5000ms sustained for 2 min | Immediate rollback |
| Data corruption | Any confirmed case | Immediate rollback + escalate |
| ECS tasks crash-looping | Tasks not stabilizing after 5 min | Immediate rollback |

---

## Method 1: GitHub Actions Manual Rollback (Preferred — ~3 minutes)

This is the preferred method for all non-emergency rollbacks. It is audited, sends Slack notifications, and runs smoke tests after rollback completes.

### Step 1: Find the Previous Task Definition ARN

```bash
# Option A: List recent task definitions for the family (newest first)
# The current bad version is first; you want the one directly below it.
aws ecs list-task-definitions \
  --family-prefix experimentation-backend-prod \
  --sort DESC \
  --max-results 5 \
  --query 'taskDefinitionArns'
# Example output:
# [
#   "arn:aws:ecs:us-west-2:123456789012:task-definition/experimentation-backend-prod:44",  <- current (bad)
#   "arn:aws:ecs:us-west-2:123456789012:task-definition/experimentation-backend-prod:43",  <- target (good)
#   ...
# ]

# Option B: Check what ECS is currently running, then subtract 1 from the revision
aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-api-prod \
  --query 'services[0].taskDefinition' \
  --output text
# Returns: arn:...:task-definition/experimentation-backend-prod:44
# You want revision :43 (the one before it)

# Option C: Review service events to identify what was running before this deployment
aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-api-prod \
  --query 'services[0].events[:5]'
```

### Step 2: Trigger the Rollback Workflow

1. Navigate to **GitHub → Actions → "Rollback Production"** (file: `rollback.yml`)
2. Click **Run workflow**
3. Fill in the required inputs:
   - **Reason for rollback:** Brief description, e.g., `"Error rate 8% after v1.2.3 deploy, p99 latency 5200ms"`
   - **Previous task definition ARN:** The ARN from Step 1 (the last known-good revision)
4. Click **Run workflow**

The workflow will:
- Update the ECS service to the specified task definition
- Wait for the service to stabilize (blocks up to 10 minutes)
- Run smoke tests against `/health`, `/api/v1/experiments`, and `/api/v1/tracking/assign`
- Notify `#deployments` Slack channel with rollback status and reason

### Step 3: Monitor Progress

Watch the GitHub Actions run. Simultaneously run:

```bash
# Watch ECS task replacement in real time (refreshes every 5 seconds)
watch -n 5 'aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-api-prod \
  --query "services[0].{Running:runningCount,Desired:desiredCount,TaskDef:taskDefinition}"'
```

Running task count should remain at 3 or above throughout. Tasks are replaced one at a time in a rolling update.

---

## Method 2: AWS CLI Direct Rollback (Emergency — ~2 minutes)

Use this method when GitHub Actions is unavailable or you need to act faster than the workflow allows. This method is faster but does not automatically run smoke tests — you must run them manually after.

```bash
# Step 1: Set the target task definition ARN (last known-good revision)
PREV_TASK_DEF="arn:aws:ecs:us-west-2:ACCOUNT_ID:task-definition/experimentation-backend-prod:43"

# Step 2: Get previous task def if you need it dynamically
# (subtracts 1 from the current revision number)
CURRENT=$(aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-api-prod \
  --query 'services[0].taskDefinition' \
  --output text)
echo "Current task def: $CURRENT"
# Manually construct the previous revision by decrementing the number at the end

# Step 3: Update the ECS service to use the previous task definition
aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-api-prod \
  --task-definition $PREV_TASK_DEF \
  --force-new-deployment

# Step 4: Wait for the service to stabilize (blocks until complete or times out in ~10 min)
aws ecs wait services-stable \
  --cluster experimentation-prod \
  --services experimentation-api-prod

echo "Rollback complete. Running verification..."

# Step 5: Verify health
curl -sf https://api.experimentation.example.com/health && echo "Health check PASSED" || echo "Health check FAILED"
```

After using Method 2, post an incident note in `#deployments` and open a follow-up task to capture it in the GitHub Actions audit log.

---

## Method 3: CodeDeploy Automatic Rollback

CodeDeploy is configured to automatically roll back when a deployment fails its health checks during blue/green traffic shifting. No manual action is required in most cases.

**When it triggers automatically:**
- ECS health check fails on the new (green) task group
- Smoke tests configured in the deployment group fail
- Deployment times out before reaching healthy state

**To stop an in-progress deployment and force immediate rollback:**

```bash
# Step 1: Get the active deployment ID
aws deploy list-deployments \
  --application-name experimentation-backend-prod \
  --deployment-group-name experimentation-backend-prod-dg \
  --include-only-statuses InProgress \
  --query 'deployments[0]' \
  --output text

# Step 2: Stop the deployment and trigger automatic rollback to blue environment
aws deploy stop-deployment \
  --deployment-id d-XXXXXXXXX \
  --auto-rollback-enabled

# Step 3: Confirm rollback status
aws deploy get-deployment \
  --deployment-id d-XXXXXXXXX \
  --query 'deploymentInfo.{Status:status,RollbackInfo:rollbackInfo}'
```

This immediately reverts traffic to the previous (blue) target group. The green tasks are terminated and the old task definition remains active.

---

## Database Rollback Procedure

**Only use this section if a database migration caused the issue.** Application rollback (Methods 1–3) must be completed first or in parallel. Database rollback is higher risk and requires Engineering Lead approval if data loss is possible.

### Step 1: Confirm Migration is the Root Cause

Before touching the database, confirm all of the following:

- Error logs contain schema-related errors (e.g., `column "X" does not exist`, `relation "Y" does not exist`, `UndefinedColumn`, `ProgrammingError`)
- The failure correlates with the migration that ran during this deployment
- Application rollback alone did not resolve the issue

```bash
# Check migration logs from the ECS migration task
aws logs filter-log-events \
  --log-group-name /ecs/experimentation-migration-prod \
  --filter-pattern '"alembic"' \
  --start-time $(date -u -v-1H +%s000 2>/dev/null || date -u --date='1 hour ago' +%s000)

# Check current alembic revision applied to production DB
# (requires bastion or VPC access)
python -m alembic -c backend/app/db/alembic.ini current
```

### Step 2: Run Migration Downgrade via GitHub Actions

1. Navigate to **GitHub → Actions → "Database Migration"** (file: `db-migrate.yml`)
2. Fill in the required inputs:
   - **Environment:** `production`
   - **Direction:** `downgrade`
   - **Target:** `-1` (reverts the single most recent migration)
3. Click **Run workflow**

After the downgrade completes, redeploy the previous application version using Method 1.

### Step 3: Emergency — Restore from Aurora Snapshot

**This causes data loss for the period since the snapshot was taken. Escalate to the Engineering Lead before proceeding.**

Only take this path if:
- The migration downgrade failed or is not available
- The migration caused data corruption or irreversible data loss
- The Engineering Lead has explicitly approved this path

```bash
# Find the most recent pre-deployment snapshot (taken automatically before each deploy)
aws rds describe-db-cluster-snapshots \
  --db-cluster-identifier experimentation-prod \
  --query 'sort_by(DBClusterSnapshots, &SnapshotCreateTime)[-5:].{ID:DBClusterSnapshotIdentifier,Time:SnapshotCreateTime,Status:Status}'

# Aurora supports point-in-time recovery (PITR) to any 5-minute window in the last 35 days.
# Restore to a new cluster from the target snapshot (~30 min):
aws rds restore-db-cluster-to-point-in-time \
  --db-cluster-identifier experimentation-prod-restored \
  --source-db-cluster-identifier experimentation-prod \
  --restore-to-time "2026-03-01T14:25:00Z" \
  --db-subnet-group-name experimentation-prod-subnet-group \
  --vpc-security-group-ids <aurora-sg-id>

# After restore completes, update the application DB connection string in Secrets Manager
# and force ECS to restart with the new endpoint
aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-api-prod \
  --force-new-deployment
```

**RTO for snapshot restore: ~30 minutes. RPO: 5 minutes (PITR window).**

---

## Post-Rollback Checklist

Complete every item before closing the incident. Do not declare the incident resolved until all boxes are checked.

### Immediate Verification (within 5 minutes of rollback)

- [ ] `GET /health` returns `{"status": "healthy"}` with HTTP 200
- [ ] 5xx error rate returned to < 0.1% baseline
- [ ] p99 API latency returned to < 500ms
- [ ] ECS running task count equals desired count (minimum 3)
- [ ] ECS deployment status is `PRIMARY` with a single active deployment

```bash
# Quick health verification commands
curl -sf https://api.experimentation.example.com/health | python3 -m json.tool
aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-api-prod \
  --query 'services[0].{Running:runningCount,Desired:desiredCount,Status:status}'
```

### Smoke Tests (within 10 minutes of rollback)

- [ ] Experiments list endpoint returning 200
- [ ] Tracking assignment endpoint operational
- [ ] Feature flag evaluation endpoint operational
- [ ] Authentication endpoint accepting valid tokens

### Incident Documentation (within 30 minutes of rollback)

- [ ] Incident posted in `#incidents` Slack channel with:
  - Timeline: when issue started, when detected, when rollback triggered, when resolved
  - Impact: which endpoints were affected, estimated user impact
  - Root cause hypothesis (preliminary is fine)
- [ ] Bad Docker image tagged to prevent accidental re-deploy:

```bash
aws ecr put-image \
  --repository-name experimentation-backend \
  --image-tag "bad-v1.2.3-do-not-deploy" \
  --image-manifest "$(aws ecr batch-get-image \
    --repository-name experimentation-backend \
    --image-ids imageTag=v1.2.3 \
    --query 'images[0].imageManifest' --output text)"
```

- [ ] Git tag removed from rotation to prevent re-triggering this deployment:

```bash
git tag -d v1.2.3
git push origin :refs/tags/v1.2.3
```

- [ ] Postmortem scheduled within 5 business days
- [ ] Investigation ticket opened in GitHub Issues with `P1` label and link to failed deployment

---

## Escalation Path

If rollback does not resolve the issue within 15 minutes, escalate immediately — do not wait.

| Time Since Issue | Action | Who |
|-----------------|--------|-----|
| T+0 | Detect issue, start rollback | On-call engineer |
| T+5 | Rollback not complete or not resolving | Page Engineering Lead |
| T+15 | Service not restored | Activate Incident Commander, open P0 bridge |
| T+30 | Data loss confirmed or outage continuing | Page VP Engineering |
| T+60 | Full region or account-level issue | Initiate disaster recovery plan |

Contacts: See `docs/security/incident-response-plan.md` Section 9 for PagerDuty escalation policies and after-hours contacts.
