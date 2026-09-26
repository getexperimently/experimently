# Rollback Runbook — Experimently

**Version:** 1.0
**Date:** March 2026
**Audience:** On-call Engineers
**Time Target:** < 5 minutes from decision to rollback complete

Every command below is written for either environment. Set this first, in the
shell you will paste into:

```bash
export ENV=prod   # or staging
```

**Rehearse it.** Before prod is ever relied on, do it in staging: two gated
deploys of two tags, then roll back to the first
([deployment guide, section 2](deployment-guide.md#2-the-first-deploys-and-the-rollback-rehearsal)).

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

This is the preferred method. It is audited and sends Slack notifications. It does **not** run smoke tests; Step 5 of Method 2 and the post-rollback checklist are by hand.

The deploy that went wrong printed the target for you: its run summary ends
with `Rollback: Actions → Rollback → environment=<env>, task_definition_arn=experimentation-backend-<env>:<n>`.
Use that, and skip Step 1.

### Step 1: Find the Previous Task Definition ARN

> **Two producers write to this family, and only one of them is runnable.**
> `cdk deploy` registers revisions too, and those carry the CDK's `bootstrap`
> image tag rather than a released build (#82). Rolling onto one starts tasks
> that cannot pull an image. **Never pick a revision by subtracting 1** —
> read the image off a candidate before you deploy it.

```bash
# Option A: List recent task definitions for the family (newest first) WITH
# the image each one carries, so a CloudFormation-registered revision is
# visible rather than a number in a list.
for arn in $(aws ecs list-task-definitions \
      --family-prefix experimentation-backend-$ENV \
      --sort DESC --max-results 10 --query 'taskDefinitionArns' --output text); do
  image=$(aws ecs describe-task-definition --task-definition "$arn" \
    --query "taskDefinition.containerDefinitions[?name=='backend'].image" --output text)
  echo "$arn  $image"
done
# arn:...:experimentation-backend-$ENV:45  ...backend:bootstrap   <- CloudFormation; NOT a rollback target
# arn:...:experimentation-backend-$ENV:44  ...backend@sha256:9f2c…   <- current (bad): a deploy registered it, by digest
# arn:...:experimentation-backend-$ENV:43  ...backend@sha256:41ab…   <- target (good): the last known-good release

# Option B: Ask which revision is actually serving traffic.
# NOT `services[0].taskDefinition`: on a service with a CodeDeploy deployment
# controller that field is "specified when the service is created with
# CreateService, and it can be modified with UpdateService" -- and UpdateService
# is the one call ECS refuses on such a service. So it names the revision
# CloudFormation created when the stack was first deployed, for the life of the
# service, and is never the running one. The PRIMARY task set is.
aws ecs describe-services \
  --cluster "experimentation-$ENV" \
  --services experimentation-backend-$ENV \
  --query "services[0].taskSets[?status=='PRIMARY'].taskDefinition" \
  --output text
# Returns: arn:...:task-definition/experimentation-backend-$ENV:44
# Then use Option A to choose the released revision below it.

# Option C: Review service events to identify what was running before this deployment
aws ecs describe-services \
  --cluster "experimentation-$ENV" \
  --services experimentation-backend-$ENV \
  --query 'services[0].events[:5]'
```

### Step 2: Trigger the Rollback Workflow

1. Navigate to **GitHub → Actions → "Rollback"** (file: `rollback.yml`)
2. Click **Run workflow**, from `main` (any other ref is refused)
3. Fill in the required inputs:
   - **Environment:** `$ENV` (`staging` or `prod`). A revision of the other
     environment's family is refused with "Re-run with environment=…"
   - **Reason for rollback:** Brief description, e.g., `"Error rate 8% after v1.2.3 deploy, p99 latency 5200ms"`
   - **Previous task definition ARN:** The ARN from Step 1 (the last known-good revision)
4. Click **Run workflow**

The workflow will:
- Check the target revision is ACTIVE, in the right family, has a container
  named `backend`, and is not a CloudFormation-registered `:bootstrap` revision
- Stop any CodeDeploy deployment still in flight (during an incident the bad
  deploy usually is, and CodeDeploy refuses a second one)
- Create a **CodeDeploy** deployment naming that revision, all-at-once rather
  than the canary the forward path uses
- **Approve the traffic shift** (`aws deploy continue-deployment`) — without
  this the deployment parks for 30 minutes and is then stopped, which
  auto-rollback turns back into the revision you were rolling away from
- Wait until the target revision is the **PRIMARY task set** and every desired
  task is running
- Notify `#deployments` with the result, success or failure

It does **not** run smoke tests; `/health` is Step 5 below, by hand.

### Step 3: Monitor Progress

Watch the GitHub Actions run. Simultaneously run:

```bash
# Watch the PRIMARY task set, which is what actually moves.
#
# NOT `services[0].taskDefinition`: on a CODE_DEPLOY service that field is set
# by CreateService and changed only by UpdateService -- the call ECS refuses
# here -- so it names the revision CloudFormation created and never changes.
# Watching it during a rollback shows nothing happening and reads as a failure.
watch -n 5 'aws ecs describe-services \
  --cluster "experimentation-$ENV" \
  --services experimentation-backend-$ENV \
  --query "services[0].{Running:runningCount,Desired:desiredCount,Serving:taskSets[?status==\`PRIMARY\`].taskDefinition|[0]}"'
```

Running task count should stay at the desired count throughout. This is a
**blue/green** deployment, not a rolling update: a second (green) task set is
provisioned alongside the current one and traffic moves to it in one shift, so
`Serving` changes from the old revision to the new one at once rather than
tasks being replaced one at a time.

---

## Method 2: AWS CLI Direct Rollback (Emergency — ~2 minutes)

Use this method when GitHub Actions is unavailable or you need to act faster than the workflow allows. This method is faster but does not automatically run smoke tests — you must run them manually after.

```bash
# Step 1: Set the target task definition ARN (last known-good revision)
PREV_TASK_DEF="arn:aws:ecs:us-west-2:ACCOUNT_ID:task-definition/experimentation-backend-$ENV:43"

# Step 2: Get the running task def if you need it dynamically.
# Use the PRIMARY task set, not `services[0].taskDefinition` -- see the note in
# Method 1 Step 1: on a CodeDeploy-controlled service that field never moves
# off the revision CloudFormation created.
CURRENT=$(aws ecs describe-services \
  --cluster "experimentation-$ENV" \
  --services experimentation-backend-$ENV \
  --query "services[0].taskSets[?status=='PRIMARY'].taskDefinition" \
  --output text)
echo "Running task def: $CURRENT"
# Do NOT decrement the revision number to find the target. CloudFormation
# registers into this family too, and its revisions carry the `bootstrap`
# image tag; pick the target with Method 1 Step 1's listing, which prints the
# image beside each revision.

# Step 3: Deploy the previous task definition through CodeDeploy.
#
# NOT `aws ecs update-service --task-definition`. This service has a
# CodeDeploy deployment controller, and ECS refuses a task-definition change
# through UpdateService on one: "Unable to update task definition on services
# with a CODE_DEPLOY deployment controller". Going back is the same call as
# going forward, with an older revision.
APPSPEC=$(jq -cn --arg td "$PREV_TASK_DEF" '{
  version: 1,
  Resources: [{ TargetService: {
    Type: "AWS::ECS::Service",
    Properties: {
      TaskDefinition: $td,
      LoadBalancerInfo: { ContainerName: "backend", ContainerPort: 8000 }
    }
  }}]
}')

# --deployment-config-name: all-at-once, NOT the deployment group's
# CANARY_10_PERCENT_5_MINUTES. The canary is right going forward, on a revision
# nobody has run. Rolling back, the target was serving production minutes ago
# and the revision being replaced is the one hurting users -- a canary would
# leave 90% of traffic on it for another five minutes.
DEPLOYMENT_ID=$(aws deploy create-deployment \
  --application-name experimentation-platform-$ENV \
  --deployment-group-name "experimentation-$ENV" \
  --deployment-config-name CodeDeployDefault.ECSAllAtOnce \
  --description "manual rollback" \
  --revision "$(jq -cn --arg c "$APPSPEC" '{revisionType:"AppSpecContent",appSpecContent:{content:$c}}')" \
  --query deploymentId --output text)
echo "deployment: $DEPLOYMENT_ID"

# Step 3b: APPROVE THE TRAFFIC SHIFT. Do not skip this.
#
# The deployment group sets deployment_approval_wait_time = 30 minutes. When
# the green task set is provisioned CodeDeploy goes to status `Ready` and
# WAITS. If ContinueDeployment is not called it stops the deployment, and the
# group's auto_rollback(stopped_deployment=True) then puts back the revision
# you are rolling away from. A rollback that is never approved is a rollback
# that silently undoes itself half an hour later.
while [ "$(aws deploy get-deployment --deployment-id "$DEPLOYMENT_ID" \
             --query deploymentInfo.status --output text)" != "Ready" ]; do
  sleep 5
done
aws deploy continue-deployment --deployment-id "$DEPLOYMENT_ID" \
  --deployment-wait-type READY_WAIT

# Step 4: Wait for the ROLLBACK, not for the service.
#
# `aws ecs wait services-stable` returns almost immediately here: during a
# blue/green deployment the old task set is serving the whole time, so the
# service is stable and the waiter says nothing about whether the rollback
# took. Watch the PRIMARY task set instead: that is what moves, and it tells
# you traffic has shifted without waiting for CodeDeploy to terminate the old
# task set (the group keeps it for an hour).
until [ "$(aws ecs describe-services --cluster "experimentation-$ENV" \
             --services experimentation-backend-$ENV \
             --query "services[0].taskSets[?status=='PRIMARY'].taskDefinition" \
             --output text)" = "$PREV_TASK_DEF" ]; do
  sleep 5
done

# (the old, misleading form -- every line commented, because this block is
#  meant to be pasted and two bare flag lines would run as a command)
# aws ecs wait services-stable \
#   --cluster "experimentation-$ENV" \
#   --services experimentation-backend-$ENV

echo "Rollback complete. Running verification..."

# Step 5: Verify health
curl -sf "https://app.<domain>/health" && echo "Health check PASSED" || echo "Health check FAILED"
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
  --application-name experimentation-platform-$ENV \
  --deployment-group-name "experimentation-$ENV" \
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
  --log-group-name /ecs/experimentation-migrate-$ENV \
  --filter-pattern '"alembic"' \
  --start-time $(date -u -v-1H +%s000 2>/dev/null || date -u --date='1 hour ago' +%s000)

```

The current revision is printed by the Database Migration workflow's
"Show the current revision" step, which runs `alembic current` in the VPC.

### Step 2: Run Migration Downgrade via GitHub Actions

1. Navigate to **GitHub → Actions → "Database Migration"** (file: `db-migrate.yml`)
2. Fill in the required inputs:
   - **Environment:** `$ENV` (`staging` or `prod`)
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
# The cluster's identifier is generated by CloudFormation; the stack publishes it.
CLUSTER=$(aws cloudformation describe-stacks --stack-name "experimentation-database-$ENV" \
  --query "Stacks[0].Outputs[?OutputKey=='ClusterIdentifier'].OutputValue" --output text)

# Find the most recent pre-deployment snapshot (a deploy takes one before
# migrating: pre-deploy-<env>-<tag>-<time>; a manual migration: pre-migration-...)
aws rds describe-db-cluster-snapshots \
  --db-cluster-identifier "$CLUSTER" \
  --query 'sort_by(DBClusterSnapshots, &SnapshotCreateTime)[-5:].{ID:DBClusterSnapshotIdentifier,Time:SnapshotCreateTime,Status:Status}'

# Aurora supports point-in-time recovery (PITR) to any 5-minute window in the last 35 days.
# Restore to a new cluster from the target snapshot (~30 min):
aws rds restore-db-cluster-to-point-in-time \
  --db-cluster-identifier "$CLUSTER-restored" \
  --source-db-cluster-identifier "$CLUSTER" \
  --restore-to-time "2026-03-01T14:25:00Z" \
  --db-subnet-group-name <the cluster's DB subnet group> \
  --vpc-security-group-ids <aurora-sg-id>

# ---------------------------------------------------------------------------
# STOP. A restore to a NEW cluster cannot be picked up by a redeploy today.
#
# Both backend task definitions take POSTGRES_SERVER from the database STACK's
# writer endpoint, and POSTGRES_USER / POSTGRES_PASSWORD from the stack's
# generated secret, as CloudFormation imports (#78). A cluster restored beside
# the stack is not that endpoint, so there is no "connection string in Secrets
# Manager" to update, and a new deployment would bring the tasks back pointing
# at the original cluster -- while this runbook reported success. (The restored
# cluster also keeps the master password of the snapshot, which is the one in
# the secret only if it has not been rotated since.)
#
# So restoring to `$CLUSTER-restored` means one of:
#
#   - restore IN PLACE instead, so the endpoint the tasks already resolve does
#     not change; or
#   - repoint the DNS name the tasks use at the restored cluster; or
#   - change the database stack to own the restored cluster and `cdk deploy`
#     it and the Fargate stack, which rewrites the imported endpoint.
#
# Decide which BEFORE an incident. Tracked as a gap in the deploy path.
# ---------------------------------------------------------------------------
#
# The restart below is correct for this controller and is what you run once the
# tasks would come back pointing at the right database. Through CodeDeploy,
# naming the revision already serving: `aws ecs update-service
# --force-new-deployment` is the usual way to restart a service and is not
# documented either way for a CODE_DEPLOY-controlled service, which this one
# is. Rather than find out during a restore, use the call that is correct for
# this controller regardless.
CURRENT=$(aws ecs describe-services \
  --cluster "experimentation-$ENV" \
  --services experimentation-backend-$ENV \
  --query "services[0].taskSets[?status=='PRIMARY'].taskDefinition" \
  --output text)

APPSPEC=$(jq -cn --arg td "$CURRENT" '{
  version: 1,
  Resources: [{ TargetService: {
    Type: "AWS::ECS::Service",
    Properties: {
      TaskDefinition: $td,
      LoadBalancerInfo: { ContainerName: "backend", ContainerPort: 8000 }
    }
  }}]
}')

aws deploy create-deployment \
  --application-name experimentation-platform-$ENV \
  --deployment-group-name "experimentation-$ENV" \
  --description "restart after PITR restore" \
  --revision "$(jq -cn --arg c "$APPSPEC" '{revisionType:"AppSpecContent",appSpecContent:{content:$c}}')"
```

**RTO for snapshot restore: ~30 minutes. RPO: 5 minutes (PITR window).**

---

## Post-Rollback Checklist

Complete every item before closing the incident. Do not declare the incident resolved until all boxes are checked.

### Immediate Verification (within 5 minutes of rollback)

- [ ] `GET /health` returns `{"status": "healthy"}` with HTTP 200
- [ ] 5xx error rate returned to < 0.1% baseline
- [ ] p99 API latency returned to < 500ms
- [ ] ECS running task count equals desired count (2 in staging, 3 in prod)
- [ ] ECS deployment status is `PRIMARY` with a single active deployment

```bash
# Quick health verification commands
curl -sf "https://app.<domain>/health" | python3 -m json.tool
aws ecs describe-services \
  --cluster "experimentation-$ENV" \
  --services experimentation-backend-$ENV \
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
- [ ] Bad image tagged so nobody mistakes it for a good one (the deploy pushes
      `:<tag>-<profile>`):

```bash
aws ecr put-image \
  --repository-name experimentation-platform/backend \
  --image-tag "bad-v1.2.3-full-do-not-deploy" \
  --image-manifest "$(aws ecr batch-get-image \
    --repository-name experimentation-platform/backend \
    --image-ids imageTag=v1.2.3-full \
    --query 'images[0].imageManifest' --output text)"
```

- [ ] The release notes of the bad release say so. **Do not delete the git
      tag**: it is a published release, other environments and people may be
      on it, and a deleted tag the next deploy cannot even refuse by name.

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
