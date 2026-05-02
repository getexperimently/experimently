# Operational Drills Runbook

**Purpose**: Phase 3 of the production-readiness hardening plan (#40) requires validating SLO alerting against pre-prod and exercising DB restore drills against real backups. This runbook documents how to execute and record those drills.

**Audience**: SRE / on-call. Requires AWS console + CLI access to the staging account.

**Companion to**: [`disaster-recovery.md`](./disaster-recovery.md) (theoretical RTO/RPO + scenarios) and [`rollback-runbook.md`](./rollback-runbook.md) (production rollback steps).

---

## Drill 1 — SLO Alert Validation

### Goal
Verify that latency, error-rate, and saturation alarms in CloudWatch fire when their underlying SLO is breached, and that paging routes to the correct on-call channel.

### Pre-flight
- [ ] Confirm staging is healthy and traffic is flowing (Grafana / CloudWatch).
- [ ] Identify the alarms to test:
  - `api-p95-latency-sla` (P95 > 500ms for 5m)
  - `api-error-rate-sla` (5xx rate > 1% for 5m)
  - `db-cpu-saturation-sla` (Aurora CPU > 80% for 10m)
  - `redis-evictions-sla` (Redis evictions > 0 for 5m)
- [ ] Confirm Slack `#sre-alerts-staging` is subscribed.

### Procedure (per alarm)

| # | Step | Expected | Record |
|---|---|---|---|
| 1 | Inject a controlled fault (load test, dependency stub, etc. — see fault catalogue below) | Metric breaches threshold | Time, metric value |
| 2 | Wait for alarm evaluation period | Alarm transitions OK -> ALARM | Time-to-alarm |
| 3 | Confirm Slack notification arrived | Message in `#sre-alerts-staging` with alarm name + dashboard link | Time-to-page |
| 4 | Resolve the fault | Metric returns to healthy | Time |
| 5 | Confirm alarm transitions ALARM -> OK | OK message in Slack | Time-to-resolve |

### Fault catalogue

- **P95 latency**: `locust -f load/p95_drill.py --users 200 --spawn-rate 50 -H https://staging.experimentation.example.com` (the file ships a 600ms `time.sleep` injection on a stub endpoint).
- **5xx rate**: temporarily set `ARTIFICIAL_500_RATE=0.05` env var on one ECS task via `aws ecs update-service` (revert immediately after).
- **DB CPU**: run `pg_bench -c 50 -j 10 -T 600` against the staging DB read replica.
- **Redis evictions**: `redis-cli -h staging-cache.xxx.cache.amazonaws.com debug sleep 60` then flood `SET` until maxmemory hits.

### Record
File a `uat-reports/slo-drill-<date>.md` with timing for each alarm + screenshots of the Slack messages.

### Pass criteria
- [ ] Every alarm fires within its evaluation window + 60s tolerance.
- [ ] Every alarm pages the correct Slack channel.
- [ ] Every alarm clears within 5 minutes of fault resolution.

---

## Drill 2 — Database Restore Drill

### Goal
Verify that we can restore the production Aurora cluster to a point-in-time within RPO targets, and that the restored data is queryable + consistent.

### Pre-flight
- [ ] Identify the RPO target: 5 minutes (per `disaster-recovery.md`).
- [ ] Identify a target staging snapshot (most recent automated snapshot).
- [ ] Confirm Aurora cluster has PITR enabled (`aws rds describe-db-clusters --db-cluster-identifier ep-staging --query 'DBClusters[0].BackupRetentionPeriod'`).
- [ ] Reserve a maintenance window — drill takes 30-90 minutes.

### Procedure

| # | Step | Command | Expected |
|---|---|---|---|
| 1 | Snapshot existing staging | `aws rds create-db-cluster-snapshot --db-cluster-identifier ep-staging --db-cluster-snapshot-identifier ep-staging-pre-drill-$(date +%s)` | Snapshot in `available` state |
| 2 | Pick a restore point (15 min ago) | record ISO timestamp | Within retention window |
| 3 | Initiate PITR clone | `aws rds restore-db-cluster-to-point-in-time --db-cluster-identifier ep-staging-restore-test --source-db-cluster-identifier ep-staging --restore-to-time $TIMESTAMP --use-latest-restorable-time false` | Cluster in `creating` state |
| 4 | Wait for cluster ready | poll `aws rds describe-db-clusters --db-cluster-identifier ep-staging-restore-test` | `Status: available` |
| 5 | Add a primary instance | `aws rds create-db-instance --db-cluster-identifier ep-staging-restore-test --db-instance-identifier ep-staging-restore-test-0 --db-instance-class db.r6g.large --engine aurora-postgresql` | Instance available |
| 6 | Connect + verify | `psql $RESTORE_DB_URL -c "SELECT count(*) FROM experimentation.experiments"` | Count matches expected at restore-time |
| 7 | Run consistency probes | see consistency-probes.sql below | All probes green |
| 8 | Tear down | `aws rds delete-db-cluster --db-cluster-identifier ep-staging-restore-test --skip-final-snapshot` + delete the instance | Cluster gone |

### Consistency probes (`consistency-probes.sql`)

```sql
-- 1. Row counts on the largest tables
SELECT 'experiments' AS table, count(*) FROM experimentation.experiments
UNION ALL SELECT 'feature_flags', count(*) FROM experimentation.feature_flags
UNION ALL SELECT 'assignments', count(*) FROM experimentation.assignments
UNION ALL SELECT 'events', count(*) FROM experimentation.events;

-- 2. No orphan FKs
SELECT count(*) AS orphan_assignments
FROM experimentation.assignments a
LEFT JOIN experimentation.experiments e ON a.experiment_id = e.id
WHERE e.id IS NULL;

-- 3. Latest timestamp ~ restore-target
SELECT max(created_at) FROM experimentation.events;

-- 4. Migration head matches expected
SELECT version_num FROM experimentation.alembic_version;
```

### Pass criteria
- [ ] Restored cluster is queryable.
- [ ] Row counts match expected at restore-target time (within tolerance for in-flight rows).
- [ ] No orphaned FKs.
- [ ] `alembic_version` head matches the source cluster at restore time.
- [ ] End-to-end drill completes within 90 minutes.

### Record
File a `uat-reports/db-restore-drill-<date>.md` with all timings, the SQL probe outputs, and any deviations.

---

## Drill 3 — Workflow Consolidation Audit

### Goal
Phase 3 calls for "consolidate redundant deployment paths/workflows". The current workflows directory has 19 files. Confirm there is no actual duplication; if any exists, file removal PRs.

### Procedure

| # | Workflow | Purpose | Verdict |
|---|---|---|---|
| 1 | `deploy.yml` | CDK infrastructure deploy on push to main | Keep (infra concern) |
| 2 | `deploy-dev.yml` | Frontend S3 sync to dev bucket | Keep (app concern, dev) |
| 3 | `deploy-prod.yml` | Full ECS Blue/Green prod deploy | Keep (app concern, prod) |
| 4 | `db-migrate.yml` | Alembic migrations | Keep (decoupled) |
| 5 | `rollback.yml` | Revert ECS to previous task def | Keep (incident response) |
| 6 | `release-gate.yml` | PR-time backend/frontend/security gate | Keep (gate, no overlap) |
| 7 | `pr-qa-gate.yml` | PR-time QA suite | **Audit overlap with release-gate.yml** |
| 8 | `nightly-qa.yml` | Nightly full QA suite | Keep (cadence different) |
| 9 | `backend-tests.yml` | Backend unit + integration matrix | **Audit overlap with release-gate.yml backend-gate** |
| 10-19 | `*-tests.yml` per surface (frontend, etl, infra, scheduler, segments, integration, performance, sdk-contract, cognito-integration, realtime-counters, security-scan) | Keep (per-surface focus) |

Two workflows worth a closer look (#7 and #9 above). If one strictly subsumes the other, retire the redundant one.

### Pass criteria
- [ ] Each retained workflow has a documented unique purpose.
- [ ] Any redundant workflow is removed via PR with rationale.

---

## When to run

| Drill | Cadence | Owner |
|---|---|---|
| Drill 1 (SLO alerts) | Quarterly | SRE on-call rotation |
| Drill 2 (DB restore) | Quarterly | DBA / SRE jointly |
| Drill 3 (workflow audit) | Annually or after major workflow change | DevX |

After each drill, file the report under `uat-reports/` and link it from this runbook in a "Drill history" log so trends are visible.
