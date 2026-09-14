# Security Policies — Experimently

**Version:** 1.0
**Date:** March 2026
**Status:** Active
**Owner:** Security Team
**Review Cycle:** Annually, or after any significant security incident

---

## 1. Access Control Policy

### 1.1 Account Lifecycle

**Account Creation:**
- All platform accounts (ADMIN, DEVELOPER, ANALYST, VIEWER) are provisioned via AWS Cognito by an ADMIN user
- New accounts are created with the minimum necessary role (VIEWER by default; see `backend/app/core/config.py` Cognito group mapping)
- Every account must have a unique email address in `experimentation.users.email`
- Service accounts for automated systems must be created with a dedicated email (e.g., `ci-deploy@yourcompany.com`) and the DEVELOPER role; they must not be used for human access
- Shared accounts are prohibited

**Account Modification:**
- Role changes must be approved by an ADMIN user and logged in `experimentation.audit_logs` (`action_type = 'role_assign'`)
- The `is_superuser` flag grants total bypass of RBAC; it must only be granted to designated platform administrators and requires approval from at least one additional ADMIN

**Account Deactivation:**
- Accounts must be deactivated within 4 hours of an employee's departure (set `is_active = false` and disable in Cognito)
- API keys owned by the departing employee must be revoked simultaneously
- Quarterly access reviews (see Section 1.3) will catch accounts not deactivated through normal offboarding

**Account Deletion:**
- Accounts may be deleted 90 days after deactivation (to allow investigation if needed)
- Deletion triggers cascade delete of API keys, rollout schedules, and segments per the SQLAlchemy model relationships in `backend/app/models/user.py`
- Audit log entries are preserved with `user_id` set to NULL (foreign key `SET NULL` on delete)

### 1.2 RBAC Matrix

The following permissions are enforced by `backend/app/core/permissions.py`:

| Resource | Action | ADMIN | DEVELOPER | ANALYST | VIEWER |
|----------|--------|-------|----------|---------|--------|
| Experiments | Create | Yes | Yes | No | No |
| Experiments | Read | Yes | Yes | Yes | Yes |
| Experiments | Update | Yes | Yes | No | No |
| Experiments | Delete | Yes | Yes | No | No |
| Experiments | List | Yes | Yes | Yes | Yes |
| Feature Flags | Create | Yes | Yes | No | No |
| Feature Flags | Read | Yes | Yes | Yes | Yes |
| Feature Flags | Update | Yes | Yes | No | No |
| Feature Flags | Delete | Yes | Yes | No | No |
| Feature Flags | List | Yes | Yes | Yes | Yes |
| Users | Create | Yes | No | No | No |
| Users | Read | Yes | Yes | Yes | Yes |
| Users | Update | Yes | No | No | No |
| Users | Delete | Yes | No | No | No |
| Users | List | Yes | Yes | No | No |
| Reports | Create | Yes | No | Yes | No |
| Reports | Read | Yes | Yes | Yes | Yes |
| Reports | Update | Yes | No | Yes | No |
| Reports | Delete | Yes | No | Yes | No |
| Reports | List | Yes | Yes | Yes | Yes |
| Roles / Permissions | All | Yes | Read only | Read only | Read only |

**Special rules:**
- Feature flag and report permission checks in `backend/app/api/deps.py` are async functions; experiment checks are synchronous
- Ownership-based permissions apply in addition to role-based permissions: owners can modify their own resources even if their role would not normally permit it
- The `is_superuser` flag overrides all RBAC checks (see `check_permission` in `permissions.py`)

### 1.3 Access Review Cycle

- **Quarterly:** ADMIN users must review the full user list and confirm all accounts are still required
- **On role change:** When an employee changes teams or responsibilities, their role must be reviewed and adjusted within 5 business days
- **Annually:** Full RBAC matrix review to confirm permissions are still appropriate
- Review evidence must be stored in the compliance records system

---

## 2. API Key Policy

### 2.1 Key Lifecycle

**Creation:**
- API keys are created via `POST /api/v1/api-keys` by an authenticated user with DEVELOPER or ADMIN role
- Keys use the format `eptk_<32 hex characters>` generated via `secrets.token_hex(16)` in `backend/app/models/api_key.py`
- Every key must have a descriptive `name` field (e.g., `production-web-app`, `ci-pipeline`)
- Every key must have an `expires_at` date set; keys without expiry are prohibited in production
- Scopes must be explicitly set to the minimum required (e.g., `tracking:write` only for SDK clients)

**Usage:**
- API keys are passed via `X-API-Key` header for all tracking and evaluation endpoints
- Keys must not be embedded in client-side JavaScript or mobile app binaries
- Keys must be stored in secrets management systems (AWS Secrets Manager, environment variables in ECS task definitions); never in source code or configuration files checked into version control

**Rotation:**
- API keys must be rotated at minimum every 90 days for production environments
- Keys must be rotated immediately upon: suspected compromise, employee departure who had access to the key, or after any P0/P1 security incident
- The rotation procedure: create new key → update all consumers → verify → deactivate old key → delete after 7-day grace period

**Revocation:**
- Immediate revocation: set `is_active = false` via `PATCH /api/v1/api-keys/{id}` or directly in the database
- Revoked keys remain in the `api_keys` table for audit purposes with `is_active = false`
- Deletion: keys may be deleted 30 days after revocation

### 2.2 Key Storage Requirements

| Environment | Storage Method | Prohibited Methods |
|------------|---------------|-------------------|
| Production | AWS Secrets Manager, ECS task environment (injected from Secrets Manager) | Hardcoded in code, `.env` files in version control, plaintext in S3 |
| Staging/QA | AWS Secrets Manager (separate secret path from production) | Same as production |
| Development | Local `.env` file (not committed to git; in `.gitignore`) | Committed `.env` files, shared Slack messages |
| CI/CD | GitHub Actions Secrets or equivalent | Logged in CI output, stored in artifact storage |

**Action Required (P0):** API key values are currently stored in plaintext in the `api_keys.key` column. Before production launch, keys must be stored as their SHA-256 hash; the plaintext key is shown only once at creation time. See threat model T3.

---

## 3. Secret Management Policy

### 3.1 Secret Categories

| Secret Type | Example | Storage Location | Rotation Frequency |
|------------|---------|-----------------|-------------------|
| Database credentials | `POSTGRES_PASSWORD` | AWS Secrets Manager | 90 days |
| Redis password | `REDIS_PASSWORD` | AWS Secrets Manager | 90 days |
| Cognito client secret | AWS Cognito app client secret | AWS Secrets Manager | On rotation by AWS |
| Application secret key | `SECRET_KEY` in `config.py` | AWS Secrets Manager | 180 days |
| API keys (eptk_*) | SDK authentication | AWS Secrets Manager (by customer) | 90 days |
| AWS access keys (if any) | IAM user keys for CI | AWS IAM + Secrets Manager | 90 days; prefer IAM roles |

### 3.2 Rules

1. **No secrets in source code.** Running `git log -S 'password'` or Semgrep with `hardcoded-secrets` rule must return zero results in the main branch. The `config.py` file contains defaults for development only; production must override all credential fields via environment variables injected from Secrets Manager.

2. **No secrets in logs.** The `LoggingMiddleware` must not log request bodies, headers containing `Authorization` or `X-API-Key`, or any field with names matching `password`, `secret`, `key`, or `token`.

3. **Secrets Manager path convention:**
   ```
   /experimentation-platform/{environment}/{secret-name}
   # e.g.
   /experimentation-platform/prod/postgres-password
   /experimentation-platform/prod/redis-password
   /experimentation-platform/prod/secret-key
   ```

4. **Rotation:** AWS Secrets Manager rotation must be configured with a Lambda rotation function for database credentials. ECS tasks must support graceful secret rotation (read from Secrets Manager on startup; restart tasks after rotation).

5. **Access audit:** CloudTrail must log all `GetSecretValue` calls. Alert on unexpected callers.

### 3.3 Identified Issue: Weak Default Secret Key

The `SECRET_KEY` field in `backend/app/core/config.py` defaults to `"default-secret-key-for-testing"`. This default must be blocked from use in production environments. Add a startup check:

```python
if settings.ENVIRONMENT == "prod" and settings.SECRET_KEY == "default-secret-key-for-testing":
    raise RuntimeError("Production environment must set a strong SECRET_KEY")
```

Similarly, `FIRST_SUPERUSER_PASSWORD = "admin"` must be overridden before any production deployment.

---

## 4. Dependency Management Policy

### 4.1 Approved Dependency Sources

- Python: PyPI (https://pypi.org) — no private mirrors unless explicitly configured
- Node.js: npm (https://registry.npmjs.org) — no private mirrors unless explicitly configured
- Container base images: Official images from Docker Hub or AWS ECR Public Gallery only

### 4.2 Vulnerability Response SLAs

| Severity | CVSS Score | Response SLA | Action |
|---------|-----------|-------------|--------|
| Critical | 9.0 – 10.0 | Patch or mitigate within **7 days** | Immediate notification to security team; may trigger P1 incident |
| High | 7.0 – 8.9 | Patch or mitigate within **30 days** | Security team review required |
| Medium | 4.0 – 6.9 | Patch or mitigate within **90 days** | Standard sprint process |
| Low | 0.1 – 3.9 | Patch within **180 days** | Backlog item |

**Tooling:**
- Python: `safety check -r requirements.txt` + Snyk in CI
- Node.js: `npm audit` + Snyk in CI
- Containers: Trivy scan in CI (`trivy image backend:latest`)
- Automated PRs: Dependabot configured for weekly updates to `requirements.txt` and `package.json`

**CI/CD Gate:** PRs introducing a new Critical dependency vulnerability must be blocked by the CI pipeline until resolved.

### 4.3 Dependency Pinning

- `requirements.txt` must use exact version pins for all direct and transitive dependencies (e.g., `fastapi==0.104.1`, not `fastapi>=0.100`)
- `package.json` must use exact versions in `dependencies`; `devDependencies` may use caret ranges
- Container base images must be pinned to a specific digest (SHA256), not just a tag

### 4.4 Review Cycle

- **Weekly:** Automated Dependabot PRs reviewed by on-call engineer
- **Monthly:** Full dependency audit report reviewed by Security Lead
- **Before each release:** Run `safety check` and `npm audit`; zero Critical/High issues required for release approval

---

## 5. Code Review Policy

### 5.1 Security Checklist for Pull Requests

Every PR to the main branch must be reviewed against this checklist. The reviewer must confirm each item before approving:

**Authentication and Authorization:**
- [ ] All new API endpoints require authentication (`Depends(get_current_active_user)` or `Depends(get_api_key)`)
- [ ] New endpoints have appropriate RBAC checks (`check_permission` with correct resource and action)
- [ ] No endpoints that should be protected are marked `include_in_schema=False` as a substitute for authentication
- [ ] Feature flag and report endpoints use async permission functions; experiment endpoints use sync

**Input Validation:**
- [ ] All user inputs are validated via Pydantic schemas before reaching business logic
- [ ] No raw SQL queries; all queries use SQLAlchemy ORM
- [ ] JSONB fields (targeting_rules, event_metadata, configuration) have schema validation where applicable
- [ ] File uploads (if any) validate MIME type, size, and content

**Secrets and Configuration:**
- [ ] No hardcoded credentials, API keys, or passwords in the diff
- [ ] New configuration values use environment variables via `settings` object
- [ ] No debug flags left enabled (`DEBUG = True`, `TESTING = True`) in production code paths

**Data Handling:**
- [ ] PII is not logged (check logging statements for `user.email`, `password`, API key values)
- [ ] Error responses do not include internal stack traces or path information
- [ ] New database columns that store PII are documented in the GDPR data inventory

**Security Controls:**
- [ ] Rate limiting applied to any new public endpoint
- [ ] New external HTTP calls use TLS and validate certificates
- [ ] No `shell=True` in subprocess calls; no `os.system()` usage
- [ ] No use of `eval()` or `exec()` on user-controlled data

### 5.2 Mandatory Reviewers for Security-Sensitive Changes

The following change types require review by the Security Lead in addition to the standard peer review:

- Changes to `backend/app/core/security.py`
- Changes to `backend/app/core/permissions.py`
- Changes to `backend/app/api/deps.py`
- Changes to `backend/app/middleware/*.py`
- New database models containing PII fields
- Changes to IAM policies or CDK infrastructure
- Changes to CORS configuration
- Dependency updates for `fastapi`, `pydantic`, `sqlalchemy`, `passlib`, `boto3`

---

## 6. Incident Classification Policy

The following events constitute a security incident and must be reported to the Security Lead within the timeframes specified:

| Event | Classification | Report Within |
|-------|---------------|--------------|
| Confirmed unauthorized access to any production system | P0 | Immediate |
| Suspected personal data breach (any PII potentially exposed) | P0 | Immediate |
| Loss or theft of a device with access to production credentials | P0 | 1 hour |
| Compromised API key or credential (confirmed) | P1 | 1 hour |
| Successful brute-force or credential stuffing on auth endpoint | P1 | 1 hour |
| Critical CVE found in a deployed dependency | P1 | 4 hours |
| Safety system failure enabling unauthorized feature flag state | P1 | 4 hours |
| Multiple failed authentication attempts (> 100 in 10 minutes) | P2 | 4 hours |
| Anomalous access pattern detected by GuardDuty | P2 | 4 hours |
| Expired but unrevoked credentials discovered | P2 | 24 hours |
| Non-critical misconfiguration found | P3 | 48 hours |

**Non-events (do not require incident report):**
- Normal authentication failures below threshold
- Automated vulnerability scan results (handled via dependency management policy)
- Test/staging environment issues with no production data exposure

---

## 7. Acceptable Use Policy

### 7.1 Platform Operators and Administrators

Platform operators (ADMIN, DEVELOPER roles) agree to:

- Use the platform only for legitimate A/B testing and feature flag management for their organization
- Not access, export, or share experiment data belonging to other organizations
- Not create experiments or feature flags designed to manipulate or deceive end users in harmful ways
- Not use the targeting rules engine to discriminate based on protected characteristics
- Not attempt to access data beyond the scope of their assigned role
- Report any suspected security vulnerabilities to security@yourcompany.com rather than exploiting them

### 7.2 What is Prohibited

The following actions are prohibited and may result in immediate account suspension:

- Sharing account credentials with other individuals (no shared accounts)
- Storing credentials in plaintext in unauthorized locations
- Bypassing RBAC controls through unauthorized means
- Submitting fraudulent events to bias experiment results
- Using the platform to collect special-category personal data (health, race, religion, political views) without explicit DPA amendment
- Using the event tracking API to build user profiles beyond what is necessary for experiment analysis
- Running automated credential stuffing or brute-force attacks
- Probing other customers' experiment data

---

## 8. Data Classification Policy

| Classification | Definition | Examples in Platform | Handling Requirements |
|---------------|-----------|---------------------|----------------------|
| **Public** | Information that can be freely shared externally | API documentation, platform feature announcements | No restrictions |
| **Internal** | Information for internal use; not harmful if disclosed but not intended for public | Experiment key naming conventions, internal architecture diagrams, non-sensitive audit log summaries | Do not post externally; share only with employees |
| **Confidential** | Business-sensitive data whose disclosure could cause competitive harm or violate privacy expectations | Experiment hypotheses and results, targeting rules, assignment records, feature flag configurations, `experimentation.events` data, user email addresses | Store encrypted at rest; transmit only via TLS; access via RBAC; do not copy to non-approved systems |
| **Restricted** | Highly sensitive data whose disclosure causes significant harm | API keys, credentials, hashed passwords, Cognito secrets, PII subject to GDPR access/erasure rights, safety rollback thresholds | Encrypt at rest and in transit; access only with explicit business need; log all access; never log in plaintext; store in Secrets Manager |

### Classification Application to Platform Tables

| Table | Classification | Notes |
|-------|---------------|-------|
| `experimentation.users` | Restricted | Contains email, hashed_password, is_superuser |
| `experimentation.api_keys` | Restricted | Contains plaintext key value (to be changed to hash; see T3) |
| `experimentation.experiments` | Confidential | Business intelligence; competitive data |
| `experimentation.events` | Confidential | Behavioral data linked to user_id |
| `experimentation.assignments` | Confidential | User bucketing data |
| `experimentation.audit_logs` | Confidential | Contains user_email; forensic evidence |
| `experimentation.feature_flags` | Confidential | Rollout state; safety thresholds |
| `experimentation.safety_settings` | Internal | Operational configuration |
| CloudWatch Logs | Confidential | May contain user_id in structured log fields |
| CloudTrail | Internal | AWS API call history |

---

## 9. Audit Log Retention Policy

### 9.1 Retention Requirements

| Log Type | Minimum Retention | Storage | Access Control |
|----------|------------------|---------|---------------|
| `experimentation.audit_logs` (application audit) | **3 years** | Aurora PostgreSQL (primary + backup) | ADMIN role + Security Lead only for deletion |
| AWS CloudTrail | **1 year** | S3 with SSE-S3 encryption; CloudTrail Insights enabled | IAM-restricted S3 bucket |
| CloudWatch application logs | **90 days** | CloudWatch Log Groups with retention policy | Engineering team read-only |
| Security incident evidence | **3 years** | S3 with SSE-KMS; evidence bucket | Incident Commander + Security Lead only |
| GDPR erasure request records | **5 years** | Compliance records system | DPO only |

### 9.2 Immutability Requirements

- `experimentation.audit_logs` rows must never be modified or deleted by application code; only the DBA can delete rows under legal process, with written approval from the DPO and Security Lead
- CloudTrail logs must be stored with S3 Object Lock (Compliance mode, 1-year retention) to prevent tampering
- Evidence collected during security incidents must be stored with S3 Object Lock

### 9.3 Audit Log Contents

The `experimentation.audit_logs` table records (`backend/app/models/audit_log.py`):

- `user_id` (UUID) — platform account who performed the action
- `user_email` — denormalized for attribution after account deletion
- `action_type` — one of: `feature_flag_create`, `feature_flag_update`, `feature_flag_delete`, `experiment_create`, `experiment_update`, `experiment_delete`, `user_create`, `user_update`, `user_delete`, `user_login`, `user_logout`, `permission_grant`, `permission_revoke`, `role_assign`, `role_unassign`, `safety_rollback`, `safety_config_update`
- `entity_type` + `entity_id` — what was acted upon
- `old_value` + `new_value` — before/after state for update actions
- `timestamp` — UTC timestamp with timezone

**What is NOT currently logged (gap):** Failed authentication attempts, authorization denials (403 responses), API key creation/deletion. These should be added as a P1 improvement.

---

## 10. Change Management Policy

All changes to the production environment must:

1. Be reviewed and approved via pull request with at least one reviewer (two reviewers for security-sensitive changes per Section 5.2)
2. Pass all CI checks including automated security scans
3. Be deployed via the CI/CD pipeline; no manual `kubectl` / `aws ecs update-service` pushes without an approved change ticket
4. Be rolled back via the same pipeline if issues are detected within 30 minutes of deployment
5. Have associated tests covering the changed behavior

**Emergency deployments** (P0 hotfix):
- May bypass normal review process with IC and Engineering Lead verbal approval
- Must be followed by a formal PR review within 24 hours
- Must be documented in the incident record

---

## 11. Vendor Management Policy

Third-party tools and services (SaaS, open source libraries) that process Confidential or Restricted data must:

1. Have a signed Data Processing Agreement (DPA) in place before onboarding
2. Be listed in the sub-processor register (GDPR Compliance Checklist Section 9)
3. Be reviewed annually for security posture (SOC 2 report, penetration test results, or equivalent)
4. Have a security contact identified for incident coordination

New third-party tools with data access must be approved by the Security Lead before integration.
