# Production Launch Checklist — Experimently

**Version:** 1.0
**Date:** March 2026
**Target Launch:** Q1 2026 (Sprint 12)

This checklist must be completed and signed off before any traffic is sent to the production environment. All items marked as mandatory must be checked. Items marked as conditional apply only in the indicated circumstances.

---

## Security (EP-018 Dependency)

- [ ] Security audit (EP-018) completed — zero CRITICAL vulnerabilities, all HIGH findings remediated or risk-accepted with documentation
- [ ] Static application security testing (SAST) scan passing in CI with no new CRITICAL/HIGH findings
- [ ] All secrets stored in AWS Secrets Manager under `/prod/experimentation/` prefix — none in code, `.env` files, or environment variables baked into images
- [ ] WAF (AWS WAF v2) enabled on the production ALB with rate-limit rules active
- [ ] HTTPS enforced: HTTP traffic redirected to HTTPS at the ALB listener level (no HTTP-only endpoints)
- [ ] Rate limiting active: test by sending 20 requests to `/api/v1/auth/token` in 1 minute — 429 response expected after threshold
- [ ] Security headers present on all API responses — verify with `securityheaders.com` or:
  ```bash
  curl -I https://api.experimentation.example.com/health | grep -i "strict-transport\|x-content-type\|x-frame\|content-security"
  ```
- [ ] `.env.*` files confirmed absent from git history:
  ```bash
  git log --all --full-history -- "**/.env*"
  # Expected: no output
  ```
- [ ] API keys scoped with least privilege (tracking-only keys cannot access admin endpoints)
- [ ] MFA enabled for all AWS IAM users with console access (enforced via IAM policy)
- [ ] Cognito user pool has MFA enabled for ADMIN and DEVELOPER roles
- [ ] ECR image scanning enabled on the `experimentation-platform/backend` repository
- [ ] No IAM access keys stored in GitHub secrets that have `AdministratorAccess` policy — deployment role must be scoped

---

## Infrastructure

- [ ] All CDK stacks deployed and in `CREATE_COMPLETE` or `UPDATE_COMPLETE` status:
  ```bash
  aws cloudformation list-stacks \
    --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
    --query 'StackSummaries[?contains(StackName,`Experimentation`)].{Name:StackName,Status:StackStatus}'
  ```
  Required stacks: VPC, Database, Redis, Compute, FargateService, MigrationTask, Monitoring
- [ ] Auto-scaling configured: minimum 3 tasks, maximum 10 tasks, CPU target 70%, memory target 80%
  ```bash
  aws application-autoscaling describe-scaling-policies \
    --service-namespace ecs \
    --resource-id service/experimentation-prod/experimentation-backend-prod
  ```
- [ ] ALB health checks passing: all 3 initial tasks healthy in the target group
  ```bash
  aws elbv2 describe-target-health \
    --target-group-arn <tg-arn> \
    --query 'TargetHealthDescriptions[*].{Target:Target.Id,Health:TargetHealth.State}'
  ```
- [ ] Aurora automated backups enabled with 35-day retention:
  ```bash
  aws rds describe-db-clusters \
    --db-cluster-identifier experimentation-prod \
    --query 'DBClusters[0].{BackupRetentionPeriod:BackupRetentionPeriod,BackupWindow:PreferredBackupWindow}'
  ```
- [ ] CloudWatch alarms configured and in `OK` state (not `INSUFFICIENT_DATA`):
  - Error rate alarm: > 1% for 5 min → PagerDuty
  - p99 latency alarm: > 500ms for 5 min → Slack
  - CPU alarm: > 85% for 10 min → Slack
  - ECS tasks down alarm: < 3 running tasks → PagerDuty
- [ ] PagerDuty on-call rotation set up with at least 2 engineers and escalation policy configured
- [ ] DNS configured: `api.experimentation.example.com` resolves to the production ALB
  ```bash
  dig api.experimentation.example.com
  ```
- [ ] SSL/TLS certificate attached to ALB — certificate covers the production domain, not expired
  ```bash
  aws acm describe-certificate --certificate-arn <cert-arn> \
    --query 'Certificate.{Domain:DomainName,Status:Status,Expiry:NotAfter}'
  ```
- [ ] CloudFront distribution deployed for frontend assets (if applicable)
- [ ] VPC flow logs enabled for security auditing
- [ ] CloudTrail enabled in us-west-2 with S3 delivery

---

## Application

- [ ] All backend unit tests passing (target: zero failures):
  ```bash
  source venv/bin/activate && python -m pytest backend/tests/unit/ -q
  ```
- [ ] All backend integration tests passing:
  ```bash
  source venv/bin/activate && python -m pytest backend/tests/integration/ -q
  ```
- [ ] All frontend tests passing: `cd frontend && npm test`
- [ ] Smoke tests passing against **staging** environment with the same tag being deployed to production:
  ```bash
  STAGING_API_URL=https://api.staging.experimentation.example.com
  curl -f "$STAGING_API_URL/health"
  curl -f -H "Authorization: Bearer $STAGING_TOKEN" "$STAGING_API_URL/api/v1/experiments"
  ```
- [ ] Database migrations applied to production database and verified:
  ```bash
  python -m alembic -c backend/app/db/alembic.ini current
  # Expected: current revision matches HEAD
  ```
- [ ] Performance benchmarks met (EP-012):
  - Variant assignment: > 50,000 req/s (Lambda path) or > 5,000 req/s (API path)
  - Feature flag evaluation: > 100,000 req/s
  - Rules evaluation: > 125,000 ops/s
- [ ] API documentation accessible at `/docs` (or explicitly disabled in production with `DISABLE_DOCS=true`)
- [ ] Health endpoint returns 200 with all components healthy:
  ```bash
  curl https://api.experimentation.example.com/health
  # Expected: {"status": "healthy", "db": "ok", "redis": "ok", "version": "X.Y.Z"}
  ```
- [ ] All feature flags set to 0% rollout for clean production launch:
  ```bash
  curl -H "Authorization: Bearer $TOKEN" \
    https://api.experimentation.example.com/api/v1/feature-flags \
    | jq '.items[] | select(.rollout_percentage > 0) | {key, rollout_percentage}'
  # Expected: no output (all flags at 0%)
  ```
- [ ] Lambda functions deployed and passing smoke tests:
  - Assignment Lambda
  - Event Processor Lambda
  - Feature Flag Evaluation Lambda (71 tests)
- [ ] No `DEBUG=true` or `APP_ENV=development` in production ECS task environment variables

---

## Monitoring and Observability

- [ ] CloudWatch dashboards configured and loading data (not showing "No data"):
  - `ExperimentationPlatform-Production` overview dashboard
  - API latency and error rate panels populated
  - RDS and Redis metrics visible
- [ ] Log groups created with correct retention policies:
  ```bash
  aws logs describe-log-groups \
    --log-group-name-prefix /experimentation-platform \
    --query 'logGroups[*].{Name:logGroupName,Retention:retentionInDays}'
  ```
  Expected: `/api` (90 days), `/services` (90 days), `/errors` (365 days)
- [ ] Error rate alarm tested: manually trigger a 500 error and verify PagerDuty receives the alert within 5 minutes
- [ ] Latency alarm tested: simulate high latency in staging and verify Slack notification fires
- [ ] Synthetics canary configured and running every 5 minutes against production health endpoint
- [ ] Status page configured (Statuspage.io or equivalent) with components:
  - API
  - Database
  - Feature Flag Evaluation
  - Experiment Assignment
- [ ] Log-based metric filters in place for authentication failures and audit log anomalies

---

## Operations

- [ ] On-call rotation set up and all engineers have confirmed their PagerDuty accounts are active
- [ ] All on-call engineers have reviewed this runbook and the rollback runbook:
  - [Deployment Guide](deployment-guide.md)
  - [Rollback Runbook](rollback-runbook.md)
  - [Disaster Recovery Plan](disaster-recovery.md)
  - [Incident Response Plan](../security/incident-response-plan.md)
- [ ] Deployment procedure performed as a dry run in staging — all stages green, total time recorded
- [ ] Rollback procedure tested in staging — confirmed working, time-to-rollback < 5 minutes
- [ ] Database restore tested: Aurora snapshot restored to staging, data integrity verified (see [Disaster Recovery](disaster-recovery.md) monthly test procedure)
- [ ] All engineers attending the launch have been briefed on:
  - How to trigger a rollback (GitHub Actions and CLI paths)
  - How to reach the on-call engineer
  - Who is the Incident Commander for launch day
- [ ] Escalation paths documented and contacts verified:
  - On-call → Engineering Lead → Incident Commander → VP Engineering
  - DPO contact verified for data incidents
- [ ] Launch day on-call schedule confirmed (dedicated coverage for 48 hours post-launch)

---

## Documentation

- [ ] API documentation up to date — all new v1 endpoints documented with request/response examples
- [ ] User guide reviewed and accurate: `docs/guides/user-guide.md`
- [ ] Quick start guide tested by a new team member who was not involved in development
- [ ] Architecture diagrams reflect current production topology (check `docs/architecture/`)
- [ ] All runbooks linked from the on-call handbook:
  - This checklist
  - [Deployment Guide](deployment-guide.md)
  - [Rollback Runbook](rollback-runbook.md)
  - [Disaster Recovery](disaster-recovery.md)
  - [Secrets Management](secrets-management.md)

---

## Business / Compliance

- [ ] GDPR compliance checklist complete — see `docs/security/gdpr-compliance-checklist.md`
- [ ] Privacy policy published at a publicly accessible URL
- [ ] Data retention policies enforced in application (experiments data: 2 years, event tracking data: 1 year)
- [ ] Legal review of Terms of Service complete and ToS published
- [ ] Customer support team trained on escalation procedures for platform issues
- [ ] Data Processing Agreement (DPA) in place with all third-party processors (AWS, any analytics vendors)
- [ ] GDPR Article 30 Record of Processing Activities updated to include Experimently

---

## Go / No-Go Decision

All category owners must sign GO before the launch window opens. If any owner signs NO-GO, the launch is blocked until the blocking issue is resolved and the owner re-signs GO.

| Category | Owner | Decision | Notes | Signed At |
|----------|-------|----------|-------|-----------|
| Security | Security Lead | ☐ GO / ☐ NO-GO | | |
| Infrastructure | DevOps Lead | ☐ GO / ☐ NO-GO | | |
| Application | Engineering Lead | ☐ GO / ☐ NO-GO | | |
| Operations | SRE Lead | ☐ GO / ☐ NO-GO | | |
| Business / Legal | Product Lead | ☐ GO / ☐ NO-GO | | |

**All five owners must sign GO before deployment begins.**

Launch meeting: Scheduled for [DATE] at [TIME] UTC. All owners required to attend or delegate a proxy with authority to sign.

---

## Launch Day Timeline

| Time (UTC) | Activity | Owner |
|-----------|----------|-------|
| T-24h | Final checklist review, confirm all items checked | Engineering Lead |
| T-4h | Final staging smoke test with production tag | DevOps |
| T-2h | Go/No-Go meeting | All leads |
| T-1h | Notify #general: "Launching experimentation platform at T+0" | Product Lead |
| T-0 | Tag production release, trigger deployment workflow | DevOps |
| T+20m | Deployment complete, smoke tests passing | DevOps |
| T+1h | First monitoring review — check CloudWatch dashboards | SRE |
| T+4h | Second monitoring review, confirm no anomalies | On-call |
| T+24h | Post-launch stability review | Engineering Lead |
| T+48h | Dedicated launch coverage ends, normal on-call resumes | SRE Lead |
