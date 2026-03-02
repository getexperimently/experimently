# GDPR Compliance Checklist — Experimentation Platform

**Version:** 1.0
**Date:** March 2026
**Status:** In Progress
**Owner:** Data Protection Officer (DPO) + Engineering
**Review Cycle:** Annually, or after any significant data model change

---

## 1. Data Inventory (Article 30 — Records of Processing Activities)

### 1.1 Personal Data Categories Collected

| Data Category | Where Stored | Purpose | Retention |
|--------------|-------------|---------|-----------|
| **Account email** | `experimentation.users.email` | Authentication, notification, audit attribution | Duration of account + 2 years |
| **Username** | `experimentation.users.username` | Authentication, UI display | Duration of account + 2 years |
| **First / Last name** | `experimentation.users.first_name`, `last_name` | UI display, communications | Duration of account + 2 years |
| **Hashed password** | `experimentation.users.hashed_password` | Authentication (bcrypt, never reversible) | Duration of account |
| **Cognito external_id** | `experimentation.users.external_id` | Federated identity linkage | Duration of account |
| **User ID (app users)** | `experimentation.assignments.user_id`, `experimentation.events.user_id` | Experiment assignment + event correlation | 2 years from collection |
| **Event data** | `experimentation.events` — `event_type`, `event_name`, `value`, `event_metadata` (JSONB) | Experiment metric computation | 1 year from collection |
| **Assignment records** | `experimentation.assignments` | Experiment analysis, sticky bucketing | 2 years from experiment completion |
| **Audit log entries** | `experimentation.audit_logs.user_email` | Compliance audit trail | 3 years minimum |
| **API key metadata** | `experimentation.api_keys` — `name`, `scopes`, `last_used_at` | API access management | Duration of key lifetime + 1 year |
| **User agent / IP** (logs) | CloudWatch Logs `/experimentation-platform/api` | Security monitoring, debugging | 90 days |

### 1.2 Data Not Collected (Intentional Minimization)

The platform deliberately does NOT collect:
- Browsing history beyond tracked events
- Device fingerprint beyond user-agent string in logs
- Geographic coordinates (user IP is logged briefly but not stored in the database)
- Health, financial, or other special-category data (GDPR Article 9) — platform operators are responsible for ensuring their experiment targeting rules do not use such attributes

### 1.3 Data Flow Map

```
End User (app user, not platform account)
  → SDK / app server → POST /api/v1/tracking/assign or /track
    → FastAPI → experimentation.assignments / experimentation.events (Aurora)
    → Kinesis Data Stream → Event Processor Lambda → OpenSearch (aggregated)

Platform Account User (ADMIN, DEVELOPER, ANALYST, VIEWER)
  → Browser / API → POST /api/v1/auth/login
    → AWS Cognito → JWT token
    → FastAPI → experimentation.audit_logs (all actions recorded)
```

---

## 2. Lawful Basis for Processing (Article 6)

| Data Subject | Processing Activity | Lawful Basis | Notes |
|-------------|--------------------|-----------------------------|-------|
| Platform account holders (employees of customers) | Account creation, authentication, audit logging | **Contract** (Article 6(1)(b)) — necessary to provide the service | Covered by platform Terms of Service |
| App end users (users of customers' products) | Experiment assignment, event tracking | **Legitimate Interest** (Article 6(1)(f)) — enabling data-driven product improvement; OR **Consent** if customer's app obtains it | Platform customers are data controllers; platform is a data processor. Customers must ensure they have a lawful basis for passing `user_id` to the platform |
| Security incident investigation | Audit logs, access logs | **Legitimate Interest** (Article 6(1)(f)) — security monitoring is a legitimate interest | Proportionate to the security risk |

**Note on processor relationship:** For end-user data (assignments and events), the platform acts as a **data processor** under Article 28. Customers are data controllers and are responsible for obtaining consent or establishing another lawful basis for their users' data flowing to this platform. A Data Processing Agreement (DPA) must be in place with all customers.

---

## 3. Data Minimization (Article 5(1)(c))

| Feature | Data Required | Minimum Viable | Assessment |
|---------|--------------|----------------|-----------|
| Experiment assignment | `user_id` (opaque string), `experiment_key`, `context` attributes | `user_id` + deterministic hash — no need to store context attributes permanently | Context attributes used only for rules evaluation; not persisted to the database |
| Event tracking | `user_id`, `event_type`, `event_name`, `value` (optional) | Minimum required for statistical computation | `event_metadata` JSONB field can hold arbitrary PII — customers must be advised not to store PII here |
| Feature flag evaluation | `user_id`, targeting attributes | Evaluation is stateless; attributes not stored | Lambda evaluation uses attributes to compute flag state but does not log them |
| Audit logging | `user_id` (UUID), `user_email`, `action_type`, `entity_id` | Both user_id and email are needed for attribution | Email is stored as a denormalized field; acceptable for audit purposes |
| Safety monitoring | Feature flag error rate, latency percentiles | Aggregated metrics only; no per-user data | No PII in safety monitoring system |

**Action Required:** Document guidance for SDK users warning that `event_metadata` JSONB field must not contain PII. Add validation or warning in SDK documentation.

---

## 4. Retention Policy (Article 5(1)(e))

| Data Type | Table(s) | Retention Period | Deletion Method |
|-----------|---------|-----------------|----------------|
| Platform user accounts | `experimentation.users` | Active: indefinite; Inactive/deleted: purged after 2 years from deactivation | Hard delete via `DELETE` with cascade |
| Experiment records | `experimentation.experiments`, `experimentation.variants`, `experimentation.metrics` | 2 years from completion date | Soft-delete then purge |
| Assignment records | `experimentation.assignments` | 2 years from experiment completion | Batch delete on experiment purge |
| Events | `experimentation.events` | 1 year from collection date | Scheduled batch delete; can be triggered on user erasure request |
| Audit logs | `experimentation.audit_logs` | 3 years minimum (required for compliance) | Cannot be deleted except by legal process |
| API keys (inactive/expired) | `experimentation.api_keys` | 1 year after expiry/revocation | Hard delete |
| Redis cache entries | ElastiCache | Session tokens: per `ACCESS_TOKEN_EXPIRE_MINUTES` (currently 8 days); Assignment cache: 3600s; Rule cache: 300s | Automatic TTL expiry |
| CloudWatch Logs (access logs) | `/experimentation-platform/api` | 90 days | CloudWatch log retention policy |
| CloudTrail (AWS API calls) | S3 / CloudTrail | 1 year | S3 lifecycle policy |
| OpenSearch (analytics) | OpenSearch indices | 1 year rolling | Index lifecycle management (ILM) |

**Implementation Status:** Retention policies defined; automated purge jobs not yet implemented (required for GDPR Article 5(1)(e) compliance). See Section 13.

---

## 5. Right of Access (Article 15)

**Current state:** No self-service data export endpoint exists. Customer platform accounts can download their own audit log history via manual request.

**Required Implementation:**

```
GET /api/v1/users/me/data-export
```

This endpoint must return all data associated with the authenticated platform user:
- Account details (from `experimentation.users`)
- All experiments owned (`experimentation.experiments WHERE owner_id = user.id`)
- All feature flags owned (`experimentation.feature_flags WHERE owner_id = user.id`)
- All audit log entries (`experimentation.audit_logs WHERE user_id = user.id`)
- All API keys (metadata only, not the key value) (`experimentation.api_keys WHERE user_id = user.id`)

For **end users** (app users tracked via `user_id` string): customers (data controllers) must provide their own access mechanism. The platform provides an internal admin API for customers to extract all events and assignments for a given `user_id`.

```
GET /api/v1/admin/user-data/{user_id}   (ADMIN role required)
Returns: all assignments and events for the given user_id string
```

---

## 6. Right to Erasure (Article 17)

**Current state:** Manual deletion only; no self-service erasure endpoint.

**Required Implementation:**

```
DELETE /api/v1/users/me
```

This must trigger cascading deletion (or anonymization) across:

```sql
-- Order of deletion to respect foreign key constraints

-- 1. Anonymize or delete events (user_id is a string; replace with hash)
UPDATE experimentation.events
SET user_id = 'DELETED-' || md5(user_id)
WHERE user_id = '<target_user_id>';

-- 2. Anonymize or delete assignments
UPDATE experimentation.assignments
SET user_id = 'DELETED-' || md5(user_id)
WHERE user_id = '<target_user_id>';

-- 3. For platform accounts: delete the user record
-- This cascades via FK constraints to:
--   experimentation.api_keys (CASCADE DELETE)
--   experimentation.rollout_schedules (CASCADE DELETE)
--   experimentation.segments (CASCADE DELETE)
-- audit_logs.user_id is SET NULL (preserved for audit trail integrity)

DELETE FROM experimentation.users WHERE id = '<user_uuid>';
```

**Note on audit logs:** Audit log entries must be retained for compliance purposes (3 years); the `user_id` FK is set to NULL on user deletion but `user_email` is retained in the `user_email` column. This is permissible under GDPR Article 17(3)(b) (compliance with legal obligations). The DPO must confirm this approach.

**Redis / Cache:** Upon user deletion, invalidate all Redis session keys for the user:
```bash
redis-cli DEL "session:<user_id>:*"
```

---

## 7. Right to Data Portability (Article 20)

**Current state:** Not implemented.

**Required Implementation:**

```
GET /api/v1/users/me/data-export?format=json   # or csv
```

Response format for JSON export:
```json
{
  "export_date": "2026-03-01T10:00:00Z",
  "account": {
    "username": "...",
    "email": "...",
    "full_name": "...",
    "role": "DEVELOPER",
    "created_at": "..."
  },
  "experiments": [...],
  "feature_flags": [...],
  "audit_history": [...]
}
```

For app-level end users, the portability right is exercised via the customer's own systems; the platform provides the underlying data via the admin API described in Section 5.

---

## 8. Data Transfers Outside the EU (Chapter V)

| Data Transfer | AWS Region | Basis | Notes |
|--------------|-----------|-------|-------|
| Platform account data (users, audit logs) | us-east-1 (primary) | Standard Contractual Clauses (SCCs) with AWS | AWS is a signatory to the EU-US Data Privacy Framework |
| Event / assignment data | us-east-1 (primary) | SCCs with AWS | Data stored in Aurora in the primary region |
| Backup data | us-west-2 (DR) | SCCs with AWS | Same DPF coverage |
| OpenSearch analytics | us-east-1 | SCCs with AWS | Aggregated data; lower PII risk |

**If EU customers are onboarded:** Evaluate whether to deploy an EU region stack (eu-west-1). Until then, document transfer basis in customer DPAs.

**AWS Data Processing Addendum:** AWS provides a GDPR DPA at https://aws.amazon.com/agreement/. This must be signed / activated in the AWS console.

---

## 9. Data Processing Agreements (Article 28)

| Sub-processor | Service Used | Data Shared | DPA Status |
|--------------|-------------|-------------|------------|
| Amazon Web Services | Aurora, ElastiCache, Lambda, Kinesis, CloudWatch, Secrets Manager, DynamoDB | All platform data | AWS DPA in place (AWS GDPR DPA) |
| Amazon Cognito | User authentication | Platform account email, username, groups | Covered by AWS DPA |
| Snyk (if enabled) | Dependency scanning | Code metadata only, no user data | Verify Snyk DPA |
| PagerDuty (if used) | Incident alerting | Alert payloads (may contain email addresses) | Verify PagerDuty DPA |

**Action Required:** Sign DPAs with all customers who are EU data controllers before processing their data.

---

## 10. Privacy by Design (Article 25)

Implementation of privacy-by-design principles in the platform:

| Principle | Implementation |
|-----------|---------------|
| **Data minimization** | Context attributes used for rules evaluation are not persisted to the database; only the resulting assignment is stored |
| **Pseudonymization** | `user_id` in assignments and events is an opaque string (controlled by the customer); the platform does not link it to PII unless the customer passes PII as the user_id |
| **Separation of concerns** | Platform accounts (authentication) are kept in `experimentation.users`; app end users are referenced only by string `user_id` in `assignments` and `events` tables — no join to a user profile |
| **Access controls** | RBAC enforces need-to-know: VIEWER cannot create or modify data; ANALYST can only view; role-based access prevents broad data access |
| **Audit trail** | All modifications to experiments, feature flags, and user accounts are recorded in `experimentation.audit_logs` with timestamps |
| **Automatic expiry** | Redis cache entries expire automatically; API keys support `expires_at`; session tokens have a configurable TTL |
| **Default security** | New user accounts default to VIEWER role; API keys default to minimal scopes; feature flags default to inactive |

---

## 11. Breach Notification Procedure (Articles 33 and 34)

### 33 — Notification to Supervisory Authority (within 72 hours)

If a personal data breach is discovered:

1. **Hour 0-1:** Security Lead confirms a breach has occurred; DPO notified immediately
2. **Hour 1-4:** DPO assesses whether notification is required (is the breach likely to result in a risk to individual rights?)
3. **Hour 4-24:** If notification required, DPO drafts Article 33 notification using the template in the Incident Response Plan (Section 6.3)
4. **Within 72 hours:** Submit to the relevant supervisory authority (e.g., ICO if UK users affected, CNIL if French users affected, etc.)

**Notification is NOT required if:**
- The breach affects only pseudonymized data with no re-identification risk, AND
- The breach is unlikely to result in a risk to the rights and freedoms of natural persons

### 34 — Communication to Data Subjects (without undue delay)

If the breach is "likely to result in a high risk" to individuals:
- Notify affected data subjects using the customer notification email template (Incident Response Plan Section 6.2)
- Notification must be clear, plain-language, and include all Article 34(2) required elements
- For app-level end users, notification is the responsibility of the customer (data controller)

---

## 12. Cookie Consent (if applicable)

The Next.js frontend (`http://localhost:3000`) does not currently set non-essential cookies. If analytics or third-party scripts are added, a cookie consent banner compliant with PECR/ePrivacy Directive must be implemented before launch.

**Current cookie inventory:**
- Session authentication cookie / JWT stored in `localStorage` or `sessionStorage` — strictly necessary
- No third-party analytics scripts (no Google Analytics, etc.) confirmed as of March 2026

---

## 13. GDPR Compliance Checklist

| Requirement | Article | Status | Owner | Notes |
|------------|---------|--------|-------|-------|
| Records of processing activities (ROPA) maintained | Art. 30 | In Progress | DPO | This document is the starting ROPA; needs customer-facing version |
| Lawful basis identified and documented for all processing | Art. 6 | In Progress | DPO | See Section 2; DPA required with customers |
| Privacy Notice published | Art. 13/14 | Not Started | Legal / Product | Must be published before public launch |
| Cookie banner for frontend | PECR / Art. 7 | N/A | Frontend team | No non-essential cookies currently set |
| Data minimization implemented | Art. 5(1)(c) | Implemented | Engineering | Context attributes not persisted; see Section 3 |
| Data retention policies defined | Art. 5(1)(e) | In Progress | Engineering | Policies defined; automated purge jobs not implemented |
| Automated data purge jobs | Art. 5(1)(e) | Not Started | Engineering | Required: scheduled jobs to purge events > 1yr, assignments > 2yr |
| Right of Access (data export) endpoint | Art. 15 | Not Started | Engineering | `GET /api/v1/users/me/data-export` required |
| Right to Erasure endpoint | Art. 17 | Not Started | Engineering | `DELETE /api/v1/users/me` with cascading anonymization |
| Right to Portability (JSON/CSV export) | Art. 20 | Not Started | Engineering | Combined with data export endpoint |
| Data subject request handling procedure | Art. 12 | Not Started | DPO | 30-day response SLA required |
| DPA signed with AWS | Art. 28 | Implemented | Legal | AWS GDPR DPA active |
| DPA template for customers | Art. 28 | Not Started | Legal | Required before onboarding EU customers |
| Sub-processor list maintained | Art. 28(4) | In Progress | DPO | See Section 9 |
| International transfer basis documented | Chapter V | In Progress | DPO | SCCs / DPF with AWS; see Section 8 |
| Privacy by Design implemented | Art. 25 | Implemented | Engineering | See Section 10 |
| Breach notification procedure documented | Art. 33/34 | Implemented | DPO | See Section 11 and IRP |
| 72-hour breach notification process tested | Art. 33 | Not Started | DPO | Include in annual tabletop exercise |
| DPO appointed (if required) | Art. 37 | Not Started | Legal | Assess if platform meets Art. 37 threshold |
| Data protection impact assessment (DPIA) | Art. 35 | Not Started | DPO | May be required if processing special-category data |
| SDK documentation warns against PII in event_metadata | Art. 25 | Not Started | Engineering | Add warning to SDK docs |
| Audit log retention (3 years) enforced | Art. 5(1)(e) | In Progress | Engineering | Policy set; enforcement via lifecycle rule needed |
| Redis cache TTL configured for session tokens | Art. 5(1)(e) | Implemented | Engineering | `ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 8` (8 days — consider reducing) |

**Legend:**
- **Implemented** — In place and verified
- **In Progress** — Partially implemented or documented
- **Not Started** — Required but not yet begun
- **N/A** — Not applicable to current platform state
