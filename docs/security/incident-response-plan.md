# Incident Response Plan — Experimently

**Version:** 1.0
**Date:** March 2026
**Status:** Active
**Owner:** Security Team
**Review Cycle:** Quarterly

---

## 1. Severity Levels and SLAs

| Level | Name | Definition | Initial Response SLA | Resolution SLA |
|-------|------|------------|---------------------|----------------|
| **P0** | Critical | Active data breach, mass PII exfiltration, complete service unavailability, compromised admin credentials in production | **< 15 minutes** | Ongoing until contained |
| **P1** | High | Suspected unauthorized access, single-user account takeover, significant data loss, safety system failure allowing bad rollout, service degraded > 50% | **< 1 hour** | < 8 hours |
| **P2** | Medium | Anomalous access patterns, expired but unrotated credentials, non-critical dependency vulnerability, isolated rate-limiting bypass | **< 4 hours** | < 72 hours |
| **P3** | Low | Informational findings from scans, policy violations, non-exploitable misconfigurations | **< 24 hours** | Next sprint |

---

## 2. Incident Response Team

| Role | Responsibilities | Backup |
|------|-----------------|--------|
| **Incident Commander (IC)** | Declares severity, coordinates response, owns communication, makes go/no-go decisions on rollbacks and isolations | Engineering Lead |
| **Security Lead** | Investigates root cause, collects forensic evidence, recommends containment steps, interfaces with AWS Support | Senior Engineer with security knowledge |
| **Engineering Lead** | Executes technical containment (feature flag rollback, key revocation, service isolation), deploys hotfixes | On-call engineer |
| **Communications Lead** | Drafts customer notifications, regulatory filings, internal status updates, manages public communications | Product Manager |
| **Data Protection Officer (DPO)** | Engaged immediately for P0/P1 involving PII; responsible for GDPR breach notification decision | Legal counsel |

**Escalation Path:** On-call engineer → Engineering Lead → Incident Commander → VP Engineering → Legal (DPO) for P0

---

## 3. Detection Sources

The following signals may indicate a security incident:

- **AWS GuardDuty:** Unusual API call patterns, compromised IAM credentials, port scanning
- **CloudWatch Alarms:** Error rate spikes, unusual `experimentation.audit_logs` write volume, auth failure rate
- **Safety Scheduler Alerts:** Repeated auto-rollbacks on a feature flag (`experimentation.safety_rollback_records`)
- **SIEM Correlation Rules:** Multiple failed login attempts to `/api/v1/auth/token`, access from new geolocation
- **User Reports:** Customer reports of seeing unexpected variant assignments or data from other accounts
- **Dependency Scanner (Snyk/Dependabot):** Critical CVE in `requirements.txt` or `package.json`
- **AWS Security Hub:** Compliance finding drops, new HIGH/CRITICAL findings

---

## 4. General Response Procedure

For all incidents:

1. **Detect** — Alert fires or report received
2. **Triage** — Assign severity level using the matrix in Section 1
3. **Declare** — IC declares incident, opens incident channel (`#incident-YYYY-MM-DD-<name>`)
4. **Contain** — Implement immediate containment (see runbooks below)
5. **Investigate** — Root cause analysis using logs, CloudTrail, audit_logs
6. **Eradicate** — Remove attacker access, patch vulnerability, rotate credentials
7. **Recover** — Restore service to known-good state, verify integrity
8. **Review** — Post-incident review within 5 business days (see Section 9)

---

## 5. Runbooks

### Runbook 1: Suspected Data Breach

**Trigger:** GuardDuty alert on unusual data exfiltration, audit_log shows bulk SELECT on sensitive tables, customer report of receiving another user's data.

**Immediate Actions (first 15 minutes for P0):**

```bash
# 1. Identify the source IP and user account from CloudWatch Logs
aws logs filter-log-events \
  --log-group-name /experimentation-platform/api \
  --filter-pattern '"status":5' \
  --start-time $(date -d '1 hour ago' +%s000)

# 2. Check audit_logs for anomalous bulk reads
# Connect to Aurora (via RDS Proxy or bastion)
SELECT user_email, action_type, COUNT(*), MIN(timestamp), MAX(timestamp)
FROM experimentation.audit_logs
WHERE timestamp > NOW() - INTERVAL '1 hour'
GROUP BY user_email, action_type
ORDER BY COUNT(*) DESC
LIMIT 50;

# 3. Identify suspected user account
# Query for the account in question
SELECT id, username, email, role, is_superuser, external_id
FROM experimentation.users
WHERE email = '<suspected email>';

# 4. Immediately disable the suspected account
UPDATE experimentation.users SET is_active = false WHERE email = '<suspected email>';

# 5. Revoke all API keys for the account
UPDATE experimentation.api_keys SET is_active = false WHERE user_id = '<user UUID>';

# 6. If Cognito account, disable in Cognito
aws cognito-idp admin-disable-user \
  --user-pool-id <pool-id> \
  --username <username>
```

**Investigation:**
- Pull CloudTrail logs for the account's AWS activity
- Review all `experimentation.audit_logs` entries for the past 24 hours for the account
- Determine what data was accessed: which experiments, which feature flags, which assignment records
- Determine if data was exported via the results API (`GET /api/v1/results/{experiment_id}` and its sub-routes)
- Check if any experiment configurations were modified (`action_type = 'experiment_update'`)

**Containment:**
- If breach is platform-wide: invoke WAF emergency rule to block all non-internal traffic
- Enable maintenance mode via feature flag if available
- Take Aurora snapshot for forensic preservation: `aws rds create-db-snapshot`

**Notification trigger:** If PII (user email or identifiable `user_id`) was accessed, DPO must be notified within 1 hour for GDPR 72-hour clock assessment.

---

### Runbook 2: Compromised API Key / Credential

**Trigger:** API key appearing in a public repository (GitHub secret scanning alert), unusual volume from a single API key, Snyk/GuardDuty credential exposure alert.

**Immediate Actions:**

```bash
# 1. Identify the compromised key from the partial value or alert
SELECT id, name, key, user_id, scopes, last_used_at, created_at
FROM experimentation.api_keys
WHERE key LIKE 'eptk_%'
  AND last_used_at > NOW() - INTERVAL '24 hours'
ORDER BY last_used_at DESC;

# 2. Immediately deactivate the key
UPDATE experimentation.api_keys
SET is_active = false
WHERE key = '<compromised key>';

# 3. Audit what the key was used for in the past 24 hours
# Check CloudWatch logs filtering by the key prefix (first 12 chars)
aws logs filter-log-events \
  --log-group-name /experimentation-platform/api \
  --filter-pattern '"api_key_prefix":"eptk_<prefix>"' \
  --start-time $(date -d '24 hours ago' +%s000)

# 4. If AWS credentials are compromised
aws iam update-access-key \
  --access-key-id <key-id> \
  --status Inactive

# 5. Generate a replacement key for the legitimate owner
# Via API: POST /api/v1/api-keys
```

**Investigation:**
- Review all requests made with the compromised key: endpoints, parameters, IP addresses
- Determine if any write operations occurred (event injection, experiment modification)
- If experiment data was read, treat as potential data disclosure
- If events were injected: flag affected experiments as potentially tainted; analysts must re-evaluate results

**Recovery:**
- Issue new API key to legitimate owner
- Notify owner of compromise and request investigation on their end (source of leak)
- If events were injected, work with data team to identify and remove fraudulent records

---

### Runbook 3: Unauthorized Access Detected

**Trigger:** Audit log shows action performed by an account the owner claims they did not perform; successful login from unexpected geography.

**Immediate Actions:**

```bash
# 1. Pull all recent actions for the account
SELECT *
FROM experimentation.audit_logs
WHERE user_email = '<user>'
  AND timestamp > NOW() - INTERVAL '24 hours'
ORDER BY timestamp DESC;

# 2. Check for session tokens still active in Redis
# Connect to Redis
redis-cli -h <redis-host> KEYS "session:*<user_id>*"

# 3. Force all sessions to expire
redis-cli -h <redis-host> DEL "session:<user_id>:<token_hash>"

# 4. Reset Cognito password (forces re-authentication)
aws cognito-idp admin-set-user-password \
  --user-pool-id <pool-id> \
  --username <username> \
  --password "$(openssl rand -base64 20)" \
  --permanent

# 5. Notify user to reset password and enable MFA
```

**Investigation:**
- Cross-reference login timestamps against CloudFront access logs (IP address, user-agent)
- Check if role was elevated: `action_type = 'role_assign'` or `is_superuser` changed
- Review what resources were accessed or modified
- Check if new API keys were created by the account

**Rollback Actions:**
- Revert any experiment or feature flag changes made during the unauthorized session
- Use `experimentation.audit_logs` `old_value` / `new_value` columns to reconstruct prior state

---

### Runbook 4: DDoS / Rate Limiting Triggered

**Trigger:** CloudWatch alarm on elevated request rate, WAF rate-limit rule triggered, ECS task CPU > 90%, Aurora connection pool exhausted.

**Immediate Actions:**

```bash
# 1. Check current request rates by endpoint
aws logs insights query \
  --log-group-names /experimentation-platform/api \
  --start-time $(date -d '10 minutes ago' +%s) \
  --end-time $(date +%s) \
  --query-string 'fields endpoint | stats count() as requests by endpoint | sort requests desc'

# 2. Identify top IP addresses in CloudFront logs
aws logs filter-log-events \
  --log-group-name /experimentation-platform/cloudfront \
  --filter-pattern '[timestamp, x_edge_location, sc_bytes, c_ip, ...]' \
  | jq -r '.events[].message' | awk '{print $5}' | sort | uniq -c | sort -rn | head 20

# 3. Block offending IP(s) in WAF
aws wafv2 update-ip-set \
  --scope CLOUDFRONT \
  --id <ip-set-id> \
  --addresses "['<attacker-ip>/32']" \
  --lock-token <token>

# 4. If auth endpoint is being brute-forced, add temporary geo-block or rate rule
aws wafv2 create-web-acl-association ...

# 5. Scale ECS service if legitimate traffic spike
aws ecs update-service \
  --cluster experimentation-platform \
  --service api \
  --desired-count <increased-count>
```

**Investigation:**
- Determine if attack is volumetric (random IPs) or targeted (same ASN / user account)
- Check if attack correlates with a deployment or a public mention of the platform
- Review whether attack successfully exhausted DB connections (Aurora `max_connections`)

**Recovery:**
- Once attack subsides, remove emergency WAF blocks after 24 hours (automated expiry if using rule groups)
- Scale back ECS if over-provisioned
- File WAF rule improvement ticket if new attack patterns emerged

---

### Runbook 5: Feature Flag Safety Rollback Triggered

**Trigger:** `safety_scheduler.py` triggered an automatic rollback; `experimentation.safety_rollback_records` shows a new entry; customer reports feature regression.

**Immediate Actions:**

```bash
# 1. Check recent rollback records
SELECT srr.*, ff.key, ff.rollout_percentage
FROM experimentation.safety_rollback_records srr
JOIN experimentation.feature_flags ff ON srr.feature_flag_id = ff.id
ORDER BY srr.created_at DESC
LIMIT 10;

# 2. Review the safety config that triggered the rollback
SELECT ssc.*
FROM experimentation.feature_flag_safety_configs ssc
WHERE ssc.feature_flag_id = '<flag_id>';

# 3. Check current error rates for the feature flag
# Query events table for error events in the past 5 minutes
SELECT
  COUNT(*) FILTER (WHERE event_type = 'error') AS errors,
  COUNT(*) AS total,
  COUNT(*) FILTER (WHERE event_type = 'error')::float / NULLIF(COUNT(*), 0) AS error_rate
FROM experimentation.events
WHERE feature_flag_id = '<flag_id>'
  AND created_at > (NOW() - INTERVAL '5 minutes')::text;

# 4. If rollback was false positive (spurious errors), manually re-enable the flag
# Via API: PUT /api/v1/feature-flags/<flag_id>
# Body: {"rollout_percentage": <previous_value>}

# 5. If rollback was legitimate, keep at 0% and investigate root cause
# Check application logs for the error type that triggered rollback
aws logs filter-log-events \
  --log-group-name /experimentation-platform/api \
  --filter-pattern '"feature_flag_key":"<flag_key>" "ERROR"'
```

**Determination:**
- If rollback was a true positive (real errors): escalate to engineering team for fix, keep flag at 0%
- If rollback was a false positive: adjust safety thresholds after investigation, document reason
- Always file a post-incident ticket regardless of outcome

**Re-enablement Gate:**
- Engineering Lead must approve re-enablement of any flag that triggered a safety rollback
- Safety config must be reviewed and confirmed before re-enabling
- Consider re-enabling at lower percentage (e.g., 1%) with closer monitoring

---

## 6. Communication Templates

### 6.1 Internal Slack Alert (post to #security-incidents)

```
:rotating_light: *SECURITY INCIDENT DECLARED* :rotating_light:

*Severity:* P[0/1/2/3] — [Critical/High/Medium/Low]
*Time Detected:* [UTC timestamp]
*Incident Commander:* @[name]
*Channel:* #incident-[date]-[short-name]

*Summary:* [2-3 sentence description of what was detected]

*Immediate Impact:*
- [e.g., "Experiments in ACTIVE status may have received fraudulent events"]
- [e.g., "User account [email] has been disabled pending investigation"]

*Current Status:* [Investigating / Containing / Recovering]

*Next Update:* [UTC time of next update]

cc: @security-team @[engineering-lead] @[ic]
```

### 6.2 Customer Notification Email (P0/P1 involving customer data)

```
Subject: Important Security Notice — Experimently

Dear [Customer Name],

We are writing to notify you of a security incident that may have affected
your data on Experimently.

What happened:
[Clear, non-technical description of the incident, what data was involved,
and the timeframe (e.g., "Between [date] and [date], an unauthorized party
may have had access to experiment configuration data...")]

What data was involved:
[Specific data types: e.g., "Experiment names and targeting rule configurations.
No user PII beyond email addresses for platform accounts was accessed.
Assignment records for users in experiments [list experiment keys] may have
been visible."]

What we have done:
- [Action 1: e.g., "Immediately terminated the unauthorized session"]
- [Action 2: e.g., "Rotated all API keys associated with your account"]
- [Action 3: e.g., "Enhanced monitoring to detect similar activity"]

What you should do:
- [Action for customer: e.g., "Rotate your API keys via the platform dashboard"]
- [Action for customer: e.g., "Review recent experiment results for anomalies"]

We take the security of your data seriously. If you have any questions,
please contact security@yourcompany.com.

[Name]
[Title]
Experimently Security Team
```

### 6.3 Regulatory / GDPR Notification (within 72 hours of identifying P0 breach involving PII)

```
To: [Data Protection Authority — e.g., ICO for UK, CNIL for France]
Subject: Personal Data Breach Notification — Article 33 GDPR

1. Nature of the breach:
   [Description of what occurred]

2. Categories and approximate number of data subjects affected:
   [e.g., "Approximately X platform users; data categories: email addresses,
   experiment assignment records"]

3. Categories and approximate number of records affected:
   [e.g., "X rows in the assignments table, Y rows in the users table"]

4. Contact details of DPO:
   Name: [DPO Name]
   Email: [dpo@yourcompany.com]
   Phone: [+X XXXX XXXX]

5. Likely consequences of the breach:
   [Assessment: e.g., "Low risk of identity fraud; moderate risk of
   competitive intelligence disclosure"]

6. Measures taken or proposed to address the breach:
   [Containment steps taken]
   [Technical measures to prevent recurrence]

Submitted by: [DPO Name, Title]
Date: [UTC date and time]
```

---

## 7. Evidence Collection and Preservation

For any P0 or P1 incident, the Security Lead must collect and preserve the following before any remediation that might destroy evidence:

```bash
# 1. Export relevant CloudWatch logs to S3 for preservation
aws logs create-export-task \
  --log-group-name /experimentation-platform/api \
  --from $(date -d '48 hours ago' +%s000) \
  --to $(date +%s000) \
  --destination s3://your-incident-evidence-bucket \
  --destination-prefix incident-$(date +%Y%m%d)/api-logs/

# 2. Create Aurora database snapshot before any remediation
aws rds create-db-snapshot \
  --db-instance-identifier experimentation-platform-prod \
  --db-snapshot-identifier incident-$(date +%Y%m%d)-pre-remediation

# 3. Export audit_logs for the relevant timeframe
SELECT * FROM experimentation.audit_logs
WHERE timestamp BETWEEN '[incident_start]' AND '[incident_end]'
ORDER BY timestamp;
-- Save result as CSV to incident evidence bucket

# 4. Capture GuardDuty findings
aws guardduty list-findings --detector-id <id> --finding-criteria '...'
aws guardduty get-findings --detector-id <id> --finding-ids [...]

# 5. Export CloudTrail events
aws cloudtrail lookup-events \
  --start-time <timestamp> \
  --end-time <timestamp>
```

All evidence must be:
- Stored in the `s3://your-incident-evidence-bucket/incident-YYYYMMDD/` prefix
- Tagged with incident ID, date, and handler
- Retained for a minimum of 3 years
- Access restricted to Incident Commander and Security Lead

---

## 8. Post-Incident Review Template

Complete within 5 business days of incident resolution.

```markdown
# Post-Incident Review: [Incident Name]

## Incident Summary
- **Date/Time Detected:** [UTC]
- **Date/Time Resolved:** [UTC]
- **Duration:** [hours/minutes]
- **Severity:** P[0/1/2/3]
- **Incident Commander:** [Name]
- **Attendees:** [Names of review participants]

## Timeline
| Time (UTC) | Event |
|-----------|-------|
| [time]    | [What happened] |
| [time]    | [Alert fired / Incident declared] |
| [time]    | [Containment step taken] |
| [time]    | [Root cause identified] |
| [time]    | [Incident resolved] |

## Impact Assessment
- **Data affected:** [What data, how many records, which tables]
- **Users affected:** [Count and description]
- **Service impact:** [Availability degradation, if any]
- **Regulatory impact:** [GDPR notification required? Filed?]

## Root Cause Analysis
[5-Why or fishbone analysis. Be specific about the technical cause.]

Primary cause: [e.g., "decode_token was a stub implementation; any JWT was accepted"]
Contributing factors:
1. [e.g., "No CI check verified Cognito validation was enabled in prod config"]
2. [e.g., "No alert existed for authentication bypass attempts"]

## What Went Well
- [e.g., "Audit logs provided complete visibility into what was accessed"]
- [e.g., "Safety rollback system prevented further harm"]

## What Could Have Gone Better
- [e.g., "Alert took 45 minutes to fire; SLA is 15 minutes"]
- [e.g., "Runbook for this scenario did not exist"]

## Corrective Actions
| Action | Owner | Priority | Due Date |
|--------|-------|----------|----------|
| [e.g., Implement real JWT validation] | [Name] | P0 | [Date] |
| [e.g., Add auth bypass alert] | [Name] | P1 | [Date] |
| [e.g., Update runbook] | [Name] | P2 | [Date] |

## Lessons Learned
[Free-form section for team learnings]

## Sign-off
- Security Lead: _______________
- Incident Commander: _______________
- Engineering Lead: _______________
```

---

## 9. Contact List

| Role | Contact | Notes |
|------|---------|-------|
| Security team | security@yourcompany.com | Primary security contact |
| On-call engineer | See PagerDuty schedule | 24/7 rotation |
| Incident Commander | See PagerDuty escalation | P0/P1 auto-pages |
| Data Protection Officer | dpo@yourcompany.com | Required for PII incidents |
| AWS Premium Support | https://console.aws.amazon.com/support | Account ID: [ACCOUNT-ID] |
| AWS Security Emergency | security@amazon.com | Report AWS service abuse |
| Legal / Counsel | legal@yourcompany.com | Required for P0, regulatory filing |
| PR / Communications | comms@yourcompany.com | External communication approval |
| UK ICO (Data Protection) | https://ico.org.uk/report-a-breach/ | 72-hour GDPR reporting |
| US-CERT | https://www.cisa.gov/report | Critical infrastructure incidents |

---

## 10. Incident Response Testing

The incident response plan must be tested:

- **Tabletop exercise:** Quarterly — walk through a scenario (e.g., "API key leaked to GitHub") with the full IRT
- **Live drill:** Bi-annually — simulate a P1 incident end-to-end in a staging environment
- **Runbook review:** After each real incident and quarterly otherwise

Test scenarios to rotate through:
1. API key leaked to public GitHub repository
2. Fraudulent events injected into an active experiment
3. Admin account taken over via credential stuffing
4. Safety rollback triggered by attacker-induced errors
5. Container image with critical CVE deployed to production
