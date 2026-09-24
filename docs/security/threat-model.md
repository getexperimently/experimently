# Threat Model — Experimently

**Version:** 1.0
**Date:** March 2026
**Status:** Active
**Owner:** Security Team

---

## 1. System Overview

Experimently is an AWS-hosted A/B testing and feature flag management service. It enables product teams to run controlled experiments, gradually roll out features, and evaluate results through a statistical engine.

### Primary Assets

| Asset | Classification | Description |
|-------|---------------|-------------|
| User credentials | Restricted | Hashed passwords, AWS Cognito tokens, `hashed_password` column in `experimentation.users` |
| API keys | Restricted | `eptk_<hex32>` tokens stored in `experimentation.api_keys`, used for SDK and server-to-server calls |
| Experiment data | Confidential | Hypothesis text, targeting rules (JSON), variant configurations, traffic allocations — competitive intelligence |
| Assignment records | Confidential | `experimentation.assignments` — which real user IDs were bucketed into which variants |
| Event / tracking data | Confidential | `experimentation.events` — user behavioral data, conversion values, revenue figures |
| Business metrics | Confidential | Computed p-values, conversion rates, effect sizes, statistical results from `analytics_results_engine` |
| Feature flag state | Internal | `experimentation.feature_flags` — rollout percentages, targeting rules |
| Safety rollback records | Internal | `experimentation.safety_rollback_records` — evidence of auto-rollbacks |
| Audit logs | Internal | `experimentation.audit_logs` — complete action history, immutable record |
| Infrastructure secrets | Restricted | DB passwords, Redis credentials, Cognito client secrets — stored in AWS Secrets Manager |
| PII (indirect) | Confidential | User email in `experimentation.users`; `user_id` strings in events and assignments may be PII |

---

## 2. Trust Boundaries

The platform has five distinct trust boundaries:

```
BOUNDARY 1: Internet — Untrusted
  Public internet, SDK clients, browsers, anonymous callers

  [Web Browser / SDK / Server]
         |
         | HTTPS (TLS 1.2+)
         v

BOUNDARY 2: AWS Edge — Partially Trusted
  [CloudFront CDN]  →  (static frontend assets, S3)
  [AWS WAF]         →  (rate limiting, IP reputation, OWASP CRS rules)
  [API Gateway]     →  (routes /api/v1/* to ECS; /evaluate/* to Lambda)

         |
         | VPC-internal HTTPS
         v

BOUNDARY 3: Application Layer — Trusted with Auth
  [FastAPI on ECS Fargate]
    Middleware stack, outermost first — the order is what decides which
    layers see a response that an inner one short-circuits, so it is stated
    as an order and pinned by backend/tests/unit/middleware/:
      CORSMiddleware            → Origin allowlist from settings.BACKEND_CORS_ORIGINS.
                                  Outermost, so a 429 the rate limiter returns
                                  without calling through still carries the
                                  CORS headers a browser needs before it will
                                  let the page read the status (#85)
      RequestIDMiddleware       → X-Request-ID, bound into the log context
      PrometheusMetricsMiddleware → latency and throughput instrumentation
      SecurityHeadersMiddleware → HSTS, CSP, X-Frame-Options. Outside the rate
                                  limiter for the same reason CORS is outside
                                  everything
      RateLimitMiddleware       → per-IP, per-path; CORS preflights exempt
      RelativeSlashRedirectMiddleware
                                → a redirect whose authority is the one the
                                  request arrived on is rewritten to a path,
                                  so the trailing-slash redirect cannot send a
                                  browser cross-origin (dropping
                                  Authorization) or downgrade it to http
                                  (sending the bearer token in cleartext).
                                  Every other Location is untouched (#86)

    NOT trusted, and not yet addressed: the `Host` header itself. Nothing
    validates it — there is no TrustedHostMiddleware — and
    modules/.../sso.py builds the OIDC redirect_uri from request.base_url.
    Tracked as #220.

    API routes: /api/v1/experiments, /api/v1/feature-flags,
                /api/v1/tracking/*, /api/v1/results/*, /api/v1/safety/*

  [AWS Lambda Functions]
    Assignment Lambda    — high-throughput variant assignment
    Event Processor      — Kinesis stream consumer
    Feature Flag Eval    — sub-10ms evaluation, local Redis cache

         |
         | VPC subnets, security groups
         v

BOUNDARY 4: Data Layer — Highly Trusted
  [Aurora PostgreSQL]  — `experimentation` schema, TLS connections required
  [ElastiCache Redis]  — session tokens, rule compilation cache, assignment cache
  [AWS DynamoDB]       — Lambda assignment fast-path storage

         |
         | AWS internal network
         v

BOUNDARY 5: Analytics Pipeline — Internal
  [Kinesis Data Streams]  →  [Event Processor Lambda]  →  [OpenSearch]
  CloudWatch Logs → SIEM
```

### API Authentication at Each Boundary

| Caller Type | Auth Method | Code Path |
|------------|-------------|-----------|
| Dashboard users | Bearer JWT (Cognito-issued) | `oauth2_scheme` in `security.py`, RBAC in `permissions.py` |
| SDK / server apps | `X-API-Key: eptk_<hex>` header | `deps.get_api_key()`, key hashed and looked up in `api_keys` table |
| Lambda → RDS | IAM role (no long-lived creds) | ECS task role, Lambda execution role |
| Internal schedulers | Process-local, no network auth | Background threads within the FastAPI process |

---

## 3. Threat Actors

### TA-1: External Attacker (Unauthenticated)

- **Motivation:** Data theft, service disruption, reconnaissance
- **Capabilities:** Web scanning tools (Nuclei, ZAP), SQL injection frameworks (SQLMap), credential stuffing
- **Access point:** Public internet → API Gateway / CloudFront
- **Constraints:** No valid credentials; blocked by WAF if deploying pattern-matching rules

### TA-2: Authenticated Malicious Insider / Compromised Account

- **Motivation:** Exfiltrate experiment data, manipulate A/B test outcomes, cover tracks
- **Capabilities:** Valid JWT or API key, knows platform data model
- **Access point:** Directly to FastAPI after clearing auth middleware
- **Constraints:** Bounded by RBAC role (VIEWER, ANALYST, DEVELOPER, ADMIN)

### TA-3: Rogue SDK User / Compromised API Key

- **Motivation:** Inject fraudulent events, bias experiment results, enumerate user assignments
- **Capabilities:** Valid `eptk_*` API key (possibly stolen or leaked), SDK knowledge
- **Access point:** `/api/v1/tracking/*` and `/evaluate/*` endpoints
- **Constraints:** API keys are scoped (comma-separated `scopes` column); cannot access admin APIs

### TA-4: Compromised AWS Account / Infrastructure Attacker

- **Motivation:** Mass data exfiltration from Aurora, full service takeover
- **Capabilities:** AWS console access, IAM privilege escalation, S3/DynamoDB direct access
- **Access point:** AWS management plane
- **Constraints:** Mitigated by least-privilege IAM, GuardDuty, CloudTrail, MFA enforcement

### TA-5: Supply Chain Attacker

- **Motivation:** Backdoor the platform via a compromised Python or npm dependency
- **Capabilities:** Malicious package update, typosquatting
- **Access point:** `requirements.txt`, `package.json`, Docker base images
- **Constraints:** Mitigated by Dependabot, Snyk, Trivy image scanning, hash pinning

---

## 4. Data Flow Diagram

```
                           PUBLIC INTERNET
                                 |
                    ┌────────────▼──────────────┐
                    │     CloudFront CDN         │
                    │  (static assets: S3)       │
                    └────────────┬──────────────┘
                                 |
                    ┌────────────▼──────────────┐
                    │       AWS WAF              │
                    │  Rate limit / OWASP rules  │
                    └────────────┬──────────────┘
                                 |
               ┌─────────────────▼──────────────────┐
               │           API Gateway               │
               │  /api/v1/* → ECS Fargate            │
               │  /evaluate/* → Lambda               │
               └──────┬──────────────────┬───────────┘
                      │                  │
          ┌───────────▼────┐   ┌─────────▼──────────┐
          │  FastAPI (ECS) │   │ Feature Flag Lambda │
          │  Port 8000     │   │ (local Redis cache) │
          └──────┬─────────┘   └─────────────────────┘
                 │
     ┌───────────┼──────────────┬────────────────┐
     │           │              │                │
     ▼           ▼              ▼                ▼
 ┌───────┐  ┌────────┐   ┌──────────┐   ┌────────────────┐
 │Aurora │  │ Redis  │   │ Kinesis  │   │ DynamoDB       │
 │ (RDS) │  │(cache) │   │ Stream   │   │ (Lambda store) │
 └───────┘  └────────┘   └────┬─────┘   └────────────────┘
                               │
                    ┌──────────▼───────────┐
                    │  Event Processor     │
                    │  Lambda              │
                    └──────────┬───────────┘
                               │
                    ┌──────────▼───────────┐
                    │    OpenSearch        │
                    │  (analytics index)   │
                    └──────────────────────┘

Data flows carrying PII/sensitive data:
  [1] Browser/SDK → API Gateway: JWT/API key + user_id + event data (TLS)
  [2] FastAPI → Aurora: user assignments, events, experiment state (TLS, VPC)
  [3] FastAPI → Redis: session tokens, rule cache (VPC, optional auth)
  [4] FastAPI → Kinesis: event records with user_id (VPC, IAM)
  [5] Kinesis → Event Processor Lambda → OpenSearch: aggregated events (VPC)
```

---

## 5. STRIDE Analysis

### 5.1 FastAPI Application Layer

| Threat | Category | Description | Likelihood | Impact | Risk |
|--------|----------|-------------|-----------|--------|------|
| JWT token forgery | Spoofing | Attacker forges a JWT to authenticate as another user | Low | Critical | High |
| `decode_token` stub in production | Spoofing | `security.py:decode_token` is a placeholder that returns static claims; if deployed as-is, any token is accepted | High | Critical | Critical |
| Horizontal privilege escalation via IDOR | Elevation of Privilege | User reads another user's experiment via guessing UUID (`/api/v1/experiments/{uuid}`) | Medium | High | High |
| Mass assignment via Pydantic schemas | Tampering | Attacker sends extra fields (e.g. `is_superuser=true`) in JSON body | Low | High | Medium |
| SQL injection via ORM | Injection | Raw SQL queries with unsanitized user input | Low | Critical | Medium |
| Verbose error messages | Information Disclosure | Stack traces returned in 500 responses expose module paths | Medium | Medium | Medium |
| Missing authentication on `/health` | Information Disclosure | Health endpoint reveals service status without auth (acceptable for liveness probes) | High | Low | Low |
| Replay attack on API keys | Spoofing | API key captured in transit and replayed | Low | High | Medium |
| CSRF on state-changing endpoints | Tampering | Cross-origin form submission if CORS misconfigured | Low | High | Medium |

### 5.2 Authentication & Session Management

| Threat | Category | Description | Likelihood | Impact | Risk |
|--------|----------|-------------|-----------|--------|------|
| Cognito token not validated in prod | Spoofing | See `decode_token` stub above | High | Critical | Critical |
| Long token expiry (8 days) | Elevation of Privilege | `ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 8`; stolen tokens remain valid 8 days | Medium | High | High |
| No token revocation | Spoofing | Logout does not invalidate token server-side; relies on expiry | Medium | High | High |
| Brute force on login endpoint | Spoofing | `/api/v1/auth/login` not rate-limited in current code | High | High | High |
| Weak default credentials | Spoofing | `FIRST_SUPERUSER_PASSWORD = "admin"` in `config.py` if not overridden | High | Critical | Critical |
| API key stored in plaintext | Information Disclosure | `api_keys.key` column stores the full key string (not hashed) | Medium | High | High |

### 5.3 RBAC / Authorization

| Threat | Category | Description | Likelihood | Impact | Risk |
|--------|----------|-------------|-----------|--------|------|
| Superuser bypass | Elevation of Privilege | `is_superuser=True` bypasses all RBAC; if an account is compromised, all data is exposed | Low | Critical | High |
| DEVELOPER can delete own experiments | Elevation of Privilege | Role matrix allows DELETE on experiments for DEVELOPER; no separate approval workflow | Low | Medium | Low |
| Ownership check race condition | Tampering | `check_ownership` compares `str(owner_id) == str(user.id)`; UUID coercion may fail silently | Low | Medium | Low |
| Feature flag safety config visible to VIEWER | Information Disclosure | Safety thresholds may reveal internal SLA commitments | Low | Low | Low |

### 5.4 Tracking / Event Pipeline

| Threat | Category | Description | Likelihood | Impact | Risk |
|--------|----------|-------------|-----------|--------|------|
| Fraudulent event injection | Tampering | Rogue SDK user submits fake conversion events to bias experiment results | Medium | Critical | High |
| Event replay / duplicate inflation | Repudiation | Re-submitting events to inflate conversion metrics | Medium | High | High |
| Kinesis stream unauthorized write | Tampering | If Kinesis stream is publicly writable, attacker floods pipeline | Low | High | Medium |
| user_id enumeration | Information Disclosure | Assignment endpoint reveals whether a given user_id is assigned; leaks user existence | Medium | Medium | Medium |
| Missing experiment_id validation | Tampering | Event submitted with a non-existent experiment_id is silently accepted | Medium | Low | Low |

### 5.5 Feature Flag & Safety System

| Threat | Category | Description | Likelihood | Impact | Risk |
|--------|----------|-------------|-----------|--------|------|
| Forced rollback DoS | Denial of Service | Attacker triggers repeated errors to force auto-rollback of a critical feature flag | Medium | High | High |
| Safety config manipulation | Tampering | DEVELOPER raises `max_error_rate` to prevent legitimate rollback | Medium | High | High |
| Rollout schedule state machine bypass | Elevation of Privilege | Manually advancing stages out of sequence to jump to 100% rollout | Low | Medium | Low |
| Cache poisoning (Redis) | Tampering | Attacker who gains Redis access poisons cached feature flag state | Low | High | Medium |

### 5.6 Infrastructure & AWS

| Threat | Category | Description | Likelihood | Impact | Risk |
|--------|----------|-------------|-----------|--------|------|
| Secrets in environment variables | Information Disclosure | If ECS task definitions are readable, DB passwords are exposed | Medium | Critical | High |
| Aurora publicly accessible | Information Disclosure | Misconfigured security group exposes port 5432 | Low | Critical | High |
| S3 bucket public access | Information Disclosure | Frontend S3 bucket ACL set to public-read-write | Low | High | Medium |
| Lambda IAM over-permissions | Elevation of Privilege | Lambda execution role with `*` DynamoDB / S3 actions | Medium | High | High |
| CloudWatch log exfiltration | Information Disclosure | Log groups lack resource policies; readable by any IAM principal in account | Medium | Medium | Medium |
| Container image with known CVEs | Tampering | Stale base image with unpatched OS vulnerabilities | High | High | High |

---

## 6. Top Threats — Likelihood × Impact Matrix

```
         IMPACT
         Low    Medium   High   Critical
L  High   [ ]    [T4]    [T5]    [T1,T2]
I  Med    [ ]    [T9]    [T6]   [T7,T8]
K  Low    [ ]    [T10]  [T11]   [T3]
E
L
I
H
O
O
D
```

| ID | Threat | Likelihood | Impact | Risk Score |
|----|--------|-----------|--------|-----------|
| T1 | `decode_token` stub deployed to production | High | Critical | **Critical** |
| T2 | Weak default superuser password (`admin`) | High | Critical | **Critical** |
| T3 | API key stored in plaintext in database | Medium | High | **High** |
| T4 | No rate limiting on auth/login endpoint | High | High | **High** |
| T5 | JWT 8-day expiry with no server-side revocation | Medium | High | **High** |
| T6 | Fraudulent event injection biasing experiment results | Medium | Critical | **High** |
| T7 | Lambda IAM over-permissions | Medium | High | **High** |
| T8 | Container image with unpatched CVEs | High | High | **High** |
| T9 | CORS misconfiguration enabling CSRF | Low | High | **Medium** |
| T10 | Redis cache poisoning | Low | High | **Medium** |
| T11 | Forced safety rollback via error injection | Medium | High | **High** |

---

## 7. Mitigations

### Implemented

| Control | Where | What It Does |
|---------|-------|--------------|
| Security headers | `backend/app/middleware/security_middleware.py` | HSTS (1yr + preload), CSP (`default-src 'none'`), X-Frame-Options: DENY, X-Content-Type-Options: nosniff, Referrer-Policy, Permissions-Policy |
| CORS allowlist | `main.py` + `settings.BACKEND_CORS_ORIGINS` | Only configured origins may make credentialed requests |
| RBAC enforcement | `backend/app/core/permissions.py` | Role matrix applied to all endpoints via `check_permission()` |
| bcrypt password hashing | `backend/app/core/security.py` | `CryptContext(schemes=["bcrypt"])` with auto-deprecation |
| API key scopes | `backend/app/models/api_key.py` | `scopes` column limits what each key can do |
| API key expiry | `backend/app/models/api_key.py` | `expires_at` column + `is_valid` property check |
| Audit logging | `backend/app/models/audit_log.py` | All CRUD actions on experiments, feature flags, users, permissions recorded |
| Structured error responses | `backend/app/middleware/error_middleware.py` | No stack traces in production responses |
| Server header removal | `backend/app/middleware/security_middleware.py` | `server` and `x-powered-by` headers stripped |
| Secrets Manager | AWS infrastructure | DB credentials, Cognito secrets stored in Secrets Manager (not env vars) |
| Safety auto-rollback | `backend/app/core/safety_scheduler.py` | Feature flags automatically rolled back on error rate / latency breach |

### Planned / Required Before Production

| Control | Priority | Addresses |
|---------|----------|-----------|
| Replace `decode_token` stub with real Cognito JWT validation | P0 | T1 |
| Rotate and enforce strong default admin credentials | P0 | T2 |
| Hash API keys at rest (store only SHA-256 of key) | P0 | T3 |
| Implement rate limiting on `/api/v1/auth/token` (max 5 attempts/min/IP) | P0 | T4 |
| Reduce token expiry to 1 hour; implement refresh token rotation | P1 | T5 |
| Add event deduplication via idempotency key on tracking endpoints | P1 | T6 |
| Scope Lambda IAM roles to minimum required actions and resources | P1 | T7 |
| Weekly Trivy image scanning in CI/CD pipeline | P1 | T8 |
| Restrict CORS to production frontend domain only | P1 | T9 |
| Enable Redis AUTH and TLS | P1 | T10 |
| Rate-limit safety rollback trigger per flag per hour | P2 | T11 |
| Enable AWS WAF with OWASP Core Rule Set on API Gateway | P1 | Multiple |
| Enable AWS GuardDuty across all regions | P1 | TA-4 |
| Enable AWS Security Hub and set score target > 90% | P2 | TA-4 |
| Implement Content-Security-Policy for dashboard frontend (Next.js) | P2 | XSS |
