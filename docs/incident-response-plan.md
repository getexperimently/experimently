# Incident Response Plan

## Purpose

This document defines the process for detecting, responding to, and recovering from security incidents in the experimentation platform.

## Severity Levels

| Level | Description | Response Time | Examples |
|---|---|---|---|
| **P1 Critical** | Active data breach, complete service outage | 15 minutes | Data exfiltration, compromised credentials |
| **P2 High** | Partial service impact, vulnerability exploited | 1 hour | Privilege escalation, DDoS attack |
| **P3 Medium** | No immediate impact, vulnerability discovered | 4 hours | Failed penetration attempt, CVE in dependency |
| **P4 Low** | Informational, minor issue | 24 hours | Scanner false positive, non-critical misconfiguration |

## Response Process

### 1. Detection

Security events are detected through:
- **Automated monitoring**: CloudWatch alarms, GuardDuty findings
- **CI/CD scanning**: Bandit, Semgrep, Safety, Gitleaks, Trivy
- **Audit logs**: Unusual patterns in audit trail
- **External reports**: Bug bounty, customer reports

### 2. Triage (15 minutes)

1. Acknowledge the alert
2. Determine severity level (P1-P4)
3. Identify affected systems and data
4. Assign incident commander

### 3. Containment (P1: immediate, P2: 1 hour)

**Immediate actions for P1/P2:**
- Rotate compromised credentials
- Block attacker IP addresses (WAF rules)
- Disable compromised API keys
- Isolate affected systems (security group changes)

**Commands:**
```bash
# Rotate database password
aws secretsmanager rotate-secret --secret-id prod/db-password

# Block IP in WAF
aws wafv2 update-ip-set --name blocked-ips --addresses "1.2.3.4/32"

# Disable compromised API key (via admin API)
curl -X POST https://api.example.com/api/v1/admin/api-keys/{key_id}/revoke
```

### 4. Eradication

1. Identify root cause
2. Patch vulnerability
3. Remove attacker access
4. Verify fix with security scan

### 5. Recovery

1. Restore services from known-good state
2. Verify data integrity
3. Monitor for recurrence
4. Re-enable disabled features

### 6. Post-Incident Review (within 48 hours)

1. Timeline of events
2. Root cause analysis
3. What went well / what to improve
4. Action items with owners and deadlines
5. Update this playbook if needed

## Communication

### Internal
- Slack: #security-incidents (real-time updates)
- Email: security@company.com (formal notifications)
- PagerDuty: On-call rotation for P1/P2

### External (if required)
- Affected users: Within 72 hours (GDPR requirement)
- Regulators: As required by jurisdiction
- Legal counsel: Before any external communication

## Contacts

| Role | Responsibility |
|---|---|
| Incident Commander | Overall coordination, severity decisions |
| Security Lead | Technical investigation, containment |
| DevOps Lead | Infrastructure changes, deployment |
| Communications Lead | Internal/external messaging |
| Legal | Compliance, breach notification |

## Regular Testing

- **Quarterly**: Tabletop exercise with incident scenarios
- **Annually**: Full incident response drill
- **After incidents**: Review and update this plan
