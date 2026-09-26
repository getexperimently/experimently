# Disaster Recovery Plan — Experimently

**Version:** 1.0
**Date:** March 2026
**Owner:** SRE / DevOps Team
**Review Cycle:** Quarterly

---

## Recovery Objectives

| Objective | Target | Mechanism |
|-----------|--------|-----------|
| **RTO** (Recovery Time Objective) | 1 hour | Aurora failover + ECS restart |
| **RPO** (Recovery Point Objective) | 5 minutes | Aurora PITR (Point-in-Time Recovery) |

Aurora's continuous backup with PITR means data loss is bounded to the last 5 minutes of transactions in the worst case. For most scenarios (ECS-level failures, Redis failures), RPO is zero — no data is lost.

---

## Backup Strategy

| Data | Backup Method | Frequency | Retention | RTO |
|------|--------------|-----------|-----------|-----|
| PostgreSQL (Aurora) | Automated snapshots + PITR | Continuous (snapshots: daily) | 35 days | 2–30 min |
| Redis cache | AOF (append-only file) persistence | Every write | 7 days | 5 min |
| S3 assets (frontend, exports) | Cross-region replication (us-east-1) | Real-time | Indefinite | 5 min |
| ECS task definitions | AWS API (immutable, versioned) | Per deployment | Indefinite | 1 min |
| Secrets Manager | Multi-region replication (us-east-1) | Real-time | Indefinite | 1 min |
| Application logs | CloudWatch + S3 export (daily) | Real-time ingest | 90 days (CW) / 7 years (S3) | N/A |
| Alembic migration history | Git repository | Per commit | Indefinite | N/A |
| CDK infrastructure definitions | Git repository | Per commit | Indefinite | ~30 min to redeploy |

---

## Scenario 1: Single ECS Task Crash

**Detection:** ECS replaces the task automatically; no alarm fires.
**RTO:** ~60 seconds (ECS health check grace period + task startup time).

### Response

No action required. ECS automatically:
1. Detects the failing task via ALB health checks (`/health` endpoint, 30s interval, 3 consecutive failures)
2. Stops the unhealthy task
3. Starts a replacement task from the current task definition
4. Registers the new task with the ALB target group after health checks pass

### Verification

```bash
# Verify replacement task is running
aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-backend-prod \
  --query 'services[0].{Running:runningCount,Desired:desiredCount,Events:events[:3]}'
```

If running count drops below 3 and does not recover within 5 minutes, escalate to Scenario 2.

---

## Scenario 2: All ECS Tasks Down

**Detection:** CloudWatch alarm `ExperimentationPlatform-AllTasksDown` fires → PagerDuty P1 page.
**RTO:** ~5 minutes.

### Immediate Response

```bash
# Step 1: Check why tasks are failing
aws ecs describe-services \
  --cluster experimentation-prod \
  --services experimentation-backend-prod \
  --query 'services[0].{Status:status,Running:runningCount,Events:events[:10]}'

# Step 2: Check stopped task reasons
STOPPED_TASKS=$(aws ecs list-tasks \
  --cluster experimentation-prod \
  --desired-status STOPPED \
  --query 'taskArns[:3]' \
  --output json)

aws ecs describe-tasks \
  --cluster experimentation-prod \
  --tasks $STOPPED_TASKS \
  --query 'tasks[*].{StopReason:stoppedReason,ContainerReason:containers[0].reason,ExitCode:containers[0].exitCode}'

# Step 3: Check recent application logs for the crash reason
aws logs filter-log-events \
  --log-group-name /experimentation-platform/api \
  --filter-pattern '"level":"ERROR"' \
  --start-time $(date -u -d '15 minutes ago' +%s000) \
  --limit 50

# Step 4: Force a new deployment using the current (or previous) task definition
aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-backend-prod \
  --force-new-deployment

# Step 5: Wait for stabilization
aws ecs wait services-stable \
  --cluster experimentation-prod \
  --services experimentation-backend-prod
```

### Verification

```bash
curl -f https://api.experimentation.example.com/health
```

### Escalation

If tasks continue to fail after force-new-deployment, the root cause is likely:
- Secret rotation broke the secret format → check Secrets Manager values
- New container image is crashing → roll back to previous task definition (see [Rollback Runbook](rollback-runbook.md))
- Aurora or Redis unreachable → proceed to Scenario 3 or 5

If not resolved within 30 minutes: escalate to Engineering Lead.

---

## Scenario 3: Aurora Database Primary Instance Failure

**Detection:** CloudWatch alarm `RDS-FreeableMemory-Low` or `RDS-DatabaseConnections-High` fires; application logs show `could not connect to server` errors. Aurora automatically detects the failure.
**RTO:** ~2 minutes (Aurora automatic failover to read replica promoted to primary).

### Automatic Failover (Aurora handles this)

Aurora automatically:
1. Detects the primary instance failure (within ~30 seconds)
2. Promotes a read replica to primary (failover takes ~1–2 minutes)
3. Updates the cluster endpoint DNS (application reconnects automatically)

The application's database connection pool (SQLAlchemy) automatically reconnects after the DNS TTL expires (~5 seconds) and the new primary is ready.

### Verify Failover Completed

```bash
# Check cluster status
aws rds describe-db-clusters \
  --db-cluster-identifier experimentation-prod \
  --query 'DBClusters[0].{Status:Status,Endpoint:Endpoint,ReaderEndpoint:ReaderEndpoint,Members:DBClusterMembers[*].{Role:IsClusterWriter,ID:DBInstanceIdentifier,Status:DBInstanceStatus}}'

# Watch until status is "available" and a new writer is identified
watch -n 10 'aws rds describe-db-clusters \
  --db-cluster-identifier experimentation-prod \
  --query "DBClusters[0].{Status:Status,Writer:DBClusterMembers[?IsClusterWriter].DBInstanceIdentifier|[0]}"'
```

### Force ECS Service Reconnect (if automatic reconnection does not occur)

```bash
# Force ECS tasks to restart and pick up new cluster endpoint
aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-backend-prod \
  --force-new-deployment
```

### Escalation

If Aurora failover does not complete within 5 minutes, or if both the primary and replica are unavailable: escalate to Scenario 4.

---

## Scenario 4: Full Aurora Database Cluster Failure

**Detection:** `aws rds describe-db-clusters` returns status `failed`; all DB connection errors in application logs. PagerDuty P0 page via CloudWatch composite alarm.
**RTO:** ~30 minutes (restore from automated snapshot).
**RPO:** 5 minutes (PITR).

### Immediate Response

```bash
# Step 1: Confirm cluster is down
aws rds describe-db-clusters \
  --db-cluster-identifier experimentation-prod \
  --query 'DBClusters[0].{Status:Status,LatestRestorableTime:LatestRestorableTime}'

# Step 2: Identify the most recent automated snapshot
aws rds describe-db-cluster-snapshots \
  --db-cluster-identifier experimentation-prod \
  --snapshot-type automated \
  --query 'sort_by(DBClusterSnapshots, &SnapshotCreateTime)[-3:].{ID:DBClusterSnapshotIdentifier,Time:SnapshotCreateTime,Status:Status}'
```

### Restore from PITR (Point-in-Time Recovery — preferred)

PITR restores to a 5-minute window and minimizes data loss:

```bash
# Restore cluster to 5 minutes before the failure
# Replace YYYY-MM-DDTHH:MM:SSZ with the timestamp just before the failure
aws rds restore-db-cluster-to-point-in-time \
  --source-db-cluster-identifier experimentation-prod \
  --db-cluster-identifier experimentation-prod-restored \
  --restore-to-time 2026-03-01T14:55:00Z \
  --db-subnet-group-name experimentation-prod-subnet-group \
  --vpc-security-group-ids sg-XXXXXXXXX

# Wait for cluster to be available (~20 min)
aws rds wait db-cluster-available \
  --db-cluster-identifier experimentation-prod-restored

# Get the new cluster endpoint
aws rds describe-db-clusters \
  --db-cluster-identifier experimentation-prod-restored \
  --query 'DBClusters[0].Endpoint'
```

### Update Application to Use Restored Cluster

```bash
# Update the database connection secret with the new endpoint
# (password remains the same; only host changes)
EXISTING_SECRET=$(aws secretsmanager get-secret-value \
  --secret-id experimentation-database-prod-aurora-credentials \
  --query 'SecretString' --output text)

# Update with new hostname in your connection string
aws secretsmanager put-secret-value \
  --secret-id /prod/experimentation/db-url-override \
  --secret-string "postgresql://appuser:PASSWORD@experimentation-prod-restored.cluster-XXXXX.us-west-2.rds.amazonaws.com:5432/experimentation"

# Force ECS to restart and pick up the new endpoint
aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-backend-prod \
  --force-new-deployment

aws ecs wait services-stable \
  --cluster experimentation-prod \
  --services experimentation-backend-prod
```

### Verification

```bash
curl -f https://api.experimentation.example.com/health
# Verify: {"status": "healthy", "db": "ok"}
```

### Escalation

If restore does not complete within 30 minutes: escalate to Engineering Lead and VP Engineering. Contact AWS Premium Support for assistance with the Aurora cluster.

---

## Scenario 5: ElastiCache Redis Failure

**Detection:** CloudWatch alarm `Redis-CacheMisses-High` or `Redis-Replication-Lag-High`; application logs show Redis connection errors.
**RTO:** ~5 minutes.

### Application Behavior During Redis Failure

The application degrades gracefully when Redis is unavailable:
- Feature flag state is fetched directly from Aurora (slower but functional)
- Session tokens are re-validated against Aurora or Cognito on each request (higher DB load)
- Rules evaluation cache is bypassed (performance degradation, not failure)
- Assignment results are fetched from Aurora on every request

Expect ~3–5x increase in Aurora query load during Redis outage.

### Immediate Response

```bash
# Step 1: Check ElastiCache cluster status
aws elasticache describe-replication-groups \
  --replication-group-id experimentation-redis-prod \
  --query 'ReplicationGroups[0].{Status:Status,MemberClusters:MemberClusters,AtRestEncryption:AtRestEncryptionEnabled}'

# Step 2: Check if primary node is available
aws elasticache describe-cache-clusters \
  --query 'CacheClusters[?ReplicationGroupId==`experimentation-redis-prod`].{ID:CacheClusterId,Status:CacheClusterStatus,Endpoint:CacheNodes[0].Endpoint}'
```

### If Primary Failed, Promote Replica

```bash
# Force failover to replica
aws elasticache test-failover \
  --replication-group-id experimentation-redis-prod \
  --node-group-id 0001

# Wait for failover to complete
aws elasticache wait replication-group-available \
  --replication-group-id experimentation-redis-prod
```

### Force ECS to Reconnect

```bash
aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-backend-prod \
  --force-new-deployment
```

### Verification

```bash
# Verify Redis is responding
redis-cli -h <redis-primary-endpoint> -p 6379 --tls PING
# Expected: PONG

# Verify application health (Redis: ok)
curl https://api.experimentation.example.com/health
```

### Escalation

If Redis cannot be recovered within 30 minutes: continue running without Redis (graceful degradation mode). File a critical ticket to provision a new ElastiCache cluster. Do not attempt to deploy application changes while Redis is down — the elevated Aurora load could impact the deployment.

---

## Scenario 6: Full AWS Region Failure (us-west-2)

**Detection:** AWS Service Health Dashboard shows us-west-2 disruption; all health checks failing; PagerDuty P0.
**RTO:** ~1 hour (manual failover to DR region us-east-1).

### Prerequisites for Regional Failover

The following must already be configured (part of the initial infrastructure setup):

- Secrets Manager secrets replicated to us-east-1
- S3 buckets with cross-region replication to us-east-1
- Aurora Global Database with a secondary cluster in us-east-1 (if configured)
- CDK stacks deployable to us-east-1 (environment context: `us-east-1`)

### Failover Procedure

```bash
# Step 1: Confirm it is a regional outage, not an application issue
aws health describe-events \
  --filter eventTypeCategories=issue \
  --region us-east-1

# Step 2: Promote Aurora secondary cluster to primary (if Aurora Global DB is configured)
aws rds failover-global-cluster \
  --global-cluster-identifier experimentation-global \
  --target-db-cluster-identifier arn:aws:rds:us-east-1:ACCOUNT:cluster:experimentation-prod-us-east-1

# Wait for promotion (~5 min)
aws rds wait db-cluster-available \
  --db-cluster-identifier experimentation-prod-us-east-1 \
  --region us-east-1

# Step 3: Deploy CDK stacks in us-east-1
cd infrastructure/cdk
cdk deploy --all --context env=prod --context region=us-east-1

# Step 4: Update DNS to point to us-east-1 ALB
# (Update Route53 record for api.experimentation.example.com)
aws route53 change-resource-record-sets \
  --hosted-zone-id <hosted-zone-id> \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "api.experimentation.example.com",
        "Type": "CNAME",
        "TTL": 60,
        "ResourceRecords": [{"Value": "<us-east-1-alb-dns>"}]
      }
    }]
  }'

# Step 5: Verify services are running in us-east-1
curl -f https://api.experimentation.example.com/health
```

### Communication

- Immediately post in `#incidents`: "Regional failover in progress to us-east-1. ETA 60 min."
- Update status page to "Major Outage — Failover in Progress"
- Notify customers if SLA breach is expected

### Escalation

Regional failover requires Engineering Lead and VP Engineering approval due to data implications. Do not proceed without explicit approval from the Incident Commander.

---

## Scenario 7: Security Breach

**Detection:** AWS GuardDuty alert, CloudWatch anomaly, or customer report.

Refer immediately to `docs/security/incident-response-plan.md` for the complete security incident response procedure.

Key immediate actions:

```bash
# Disable suspected compromised account
UPDATE experimentation.users SET is_active = false WHERE email = '<suspected>';

# Revoke API keys
UPDATE experimentation.api_keys SET is_active = false WHERE user_id = '<user-uuid>';

# If AWS credentials are compromised, deactivate immediately
aws iam update-access-key --access-key-id <key-id> --status Inactive

# Take forensic snapshot before any remediation
aws rds create-db-snapshot \
  --db-instance-identifier experimentation-platform-prod \
  --db-snapshot-identifier incident-$(date +%Y%m%d)-pre-remediation
```

---

## Scenario 8: Complete Data Loss

**Detection:** Database tables empty or corrupted; results API returning empty data; operator error confirmed.
**RPO:** Time of last automated Aurora snapshot (worst case: 24 hours; typical: 5 minutes with PITR).

### Response

```bash
# Step 1: STOP the application immediately to prevent further writes to corrupted state
aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-backend-prod \
  --desired-count 0

# Step 2: Confirm the extent of data loss
# Connect to Aurora and check key tables
SELECT table_name, COUNT(*)
FROM information_schema.tables t
JOIN experimentation.experiments e ON true
GROUP BY table_name;

# Step 3: Use PITR to restore to just before the data loss event
# (See Scenario 4 for full PITR procedure)
aws rds restore-db-cluster-to-point-in-time \
  --source-db-cluster-identifier experimentation-prod \
  --db-cluster-identifier experimentation-prod-pre-loss \
  --restore-to-time <timestamp-before-loss>

# Step 4: Validate restored data
# Connect to restored cluster and verify row counts match expectations

# Step 5: Restart application pointing at restored cluster
aws ecs update-service \
  --cluster experimentation-prod \
  --service experimentation-backend-prod \
  --desired-count 3 \
  --force-new-deployment
```

Escalation: Data loss incidents require immediate escalation to Engineering Lead and DPO if customer PII (experiment assignment records containing `user_id`) is involved.

---

## DR Testing Schedule

| Test | Frequency | Scope | Who |
|------|-----------|-------|-----|
| Restore Aurora snapshot to staging, verify data integrity | Monthly | DB restore | SRE |
| Full failover drill in staging (simulate all ECS tasks down) | Quarterly | Application layer | DevOps + Engineering |
| Full DR simulation (regional failover simulation) | Annually | All layers | Full engineering team |
| Rollback procedure walkthrough (tabletop) | Each deploy | Application | On-call engineer |

### Monthly DB Restore Test Procedure

```bash
# 1. Find latest automated snapshot
aws rds describe-db-cluster-snapshots \
  --db-cluster-identifier experimentation-prod \
  --snapshot-type automated \
  --query 'sort_by(DBClusterSnapshots, &SnapshotCreateTime)[-1].DBClusterSnapshotIdentifier'

# 2. Restore to staging cluster
aws rds restore-db-cluster-from-snapshot \
  --db-cluster-identifier experimentation-staging-dr-test \
  --snapshot-identifier <snapshot-id> \
  --engine aurora-postgresql \
  --db-subnet-group-name experimentation-staging-subnet-group

# 3. Connect to restored cluster and verify
# Expected: all tables present, row counts match production within expected delta

# 4. Clean up
aws rds delete-db-cluster \
  --db-cluster-identifier experimentation-staging-dr-test \
  --skip-final-snapshot
```

Document test results in the monthly DR testing log in Confluence.

---

## Emergency Contacts

| Role | Contact | Notes |
|------|---------|-------|
| On-call engineer | PagerDuty rotation | First responder |
| Engineering Lead | PagerDuty escalation | Required for DB/region failover |
| Incident Commander | PagerDuty L2 escalation | P0/P1 auto-pages |
| AWS Support | https://console.aws.amazon.com/support | Premium Support (use for Aurora and regional failures) |
| DPO | dpo@yourcompany.com | Required if customer data is affected |

Full contact list: `docs/security/incident-response-plan.md` Section 9.
