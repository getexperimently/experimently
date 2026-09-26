# Security Architecture Document

## Overview

This document describes the security architecture of the experimentation platform, including threat model, security controls, data classification, and encryption standards.

## System Architecture — Security View

What the CDK deploys (`infrastructure/cdk`):

```
┌─────────────────────────────────────────────────────────────────┐
│                         INTERNET                                │
├─────────────────────────────────────────────────────────────────┤
│  ALB (HTTPS; HTTP redirected to HTTPS) → ECS Fargate            │
│  (public subnets)                         (Security Groups)     │
│                                                                 │
│                        ┌──────────────────┐                     │
│                        │  FastAPI Backend │                     │
│                        │  (RBAC + Rate    │                     │
│                        │   Limiting)      │                     │
│                        └──────┬───────────┘                     │
│                               │                                 │
│            ┌──────────────────┼──────────────────┐              │
│            ▼                  ▼                  ▼              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐           │
│  │  Aurora PG   │  │  ElastiCache │  │  DynamoDB    │           │
│  │  (Encrypted) │  │  Redis       │  │  (Encrypted) │           │
│  │  (VPC only)  │  │  (VPC only)  │  │  (IAM auth)  │           │
│  └──────────────┘  └──────────────┘  └──────────────┘           │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │  AWS Cognito │  │  KMS         │                             │
│  │  (Auth/MFA)  │  │  (Key Mgmt)  │                             │
│  └──────────────┘  └──────────────┘                             │
└─────────────────────────────────────────────────────────────────┘
```

Not in that picture, because nothing deploys it:

- **No AWS WAF, CloudFront or API Gateway.** The load balancer is the public
  edge, and the API's own rate limiter is the only request throttling.
- **The dashboard is not yet deployed by the CDK** (#69). Where it runs today
  (Docker Compose, or the image built from `frontend/Dockerfile`) it is a
  static Next.js export served by an **nginx web container**, which sets the
  Content-Security-Policy and the other security headers
  (`frontend/nginx.conf`) and proxies `/api/`, `/ws/` and `/health` to the API.
  In that arrangement the browser talks only to nginx.

## Authentication & Authorization

### Authentication Flow

1. **User Authentication**: AWS Cognito handles user registration, login, MFA
2. **JWT Tokens**: Cognito issues JWTs with short expiry (60 minutes)
3. **Token Validation**: Backend validates JWTs against Cognito JWKS
4. **API Key Auth**: Server-to-server communication uses hashed API keys

### Role-Based Access Control (RBAC)

| Role | Experiments | Feature Flags | Users | Reports |
|---|---|---|---|---|
| ADMIN | Full CRUD | Full CRUD | Full CRUD | Full CRUD |
| DEVELOPER | Create/Update | Create/Update | Read | Create |
| ANALYST | Read | Read | Read | Read |
| VIEWER | Read | Read | - | Read |

### API Key Security

- API keys are stored as SHA-256 hashes (not plaintext)
- Constant-time comparison prevents timing attacks
- Keys have expiration dates and can be revoked
- Each key is bound to a specific user account

## Data Classification

| Classification | Examples | Controls |
|---|---|---|
| **Critical** | Passwords, API keys, secrets | Bcrypt/SHA-256 hashing, KMS encryption, Secrets Manager |
| **Sensitive** | User PII (email, names) | Encryption at rest, field-level masking in logs |
| **Internal** | Experiment configs, flag rules | Database encryption, RBAC access control |
| **Public** | API documentation, health status | Rate limiting, no sensitive data exposure |

## Encryption Standards

### At Rest
- **Aurora PostgreSQL**: AES-256 encryption via AWS KMS
- **DynamoDB**: AWS-managed encryption (AES-256)
- **S3 Data Lake**: SSE-S3 or SSE-KMS encryption
- **Redis (ElastiCache)**: At-rest encryption enabled

### In Transit
- **TLS 1.2+** required for all connections
- **HSTS** enforced in production with 1-year max-age
- **Internal traffic**: VPC-internal communication uses TLS

### Secrets Management
- Production secrets stored in AWS Secrets Manager
- SECRET_KEY validated for minimum 32 characters in production
- Superuser password validated against weak defaults
- No hardcoded secrets in source code (Gitleaks CI check)

## Security Controls Matrix

| Control | Implementation | OWASP | Status |
|---|---|---|---|
| Access Control | RBAC with 4 roles + superuser | #1 | Active |
| Password Hashing | bcrypt (12 rounds) | #2 | Active |
| API Key Hashing | SHA-256 + constant-time compare | #2 | Active |
| SQL Injection Prevention | SQLAlchemy ORM (parameterized) | #3 | Active |
| XSS Prevention | CSP headers, input validation | #3 | Active |
| Security Headers | HSTS, CSP, X-Frame-Options, etc. | #5 | Active |
| Rate Limiting | Per-IP, per-route sliding window | #5 | Active |
| JWT Authentication | AWS Cognito + short expiry | #7 | Active |
| Audit Logging | All CRUD + auth events logged | #9 | Active |
| CORS Restriction | Explicit origin allowlist | #5 | Active |
| Sensitive Data Masking | Headers + body fields in logs | #2 | Active |
| Request Size Limits | 1 MB max body size | #5 | Active |
| Dependency Scanning | Safety + Trivy + Semgrep in CI | #6 | Active |
| Secret Detection | Gitleaks in CI + pre-commit | #2 | Active |

## Threat Model

### Threat Actors
1. **External Attacker**: Unauthenticated, targets public API surface
2. **Malicious User**: Authenticated, attempts privilege escalation
3. **Compromised SDK**: Client SDK sending malicious payloads
4. **Insider Threat**: Employee with legitimate access

### Attack Surface

| Surface | Threats | Mitigations |
|---|---|---|
| Public API | Injection, DDoS, brute force | Rate limiting, input validation (no WAF is deployed) |
| Authentication | Credential stuffing, token theft | Cognito MFA, short token expiry |
| Database | SQL injection, data exfiltration | ORM, encryption, VPC isolation |
| Admin Dashboard | XSS, CSRF, session hijack | CSP, CORS, secure cookies |
| Infrastructure | Misconfigured IAM, open ports | CIS benchmarks, Security Hub |

### STRIDE Analysis

| Threat | Category | Risk | Mitigation |
|---|---|---|---|
| Spoofed API requests | Spoofing | Medium | API key auth + JWT validation |
| Modified experiment data | Tampering | High | RBAC + audit logging |
| Denied experiment results | Repudiation | Medium | Immutable audit trail |
| Exposed user PII | Information Disclosure | High | Encryption + log masking |
| API overload | Denial of Service | Medium | Application rate limiting (no WAF is deployed) |
| Privilege escalation | Elevation of Privilege | Critical | RBAC + permission checks |

## Network Security

### VPC Architecture
- Public subnets: ALB only
- Private subnets: ECS tasks, Lambda functions
- Isolated subnets: RDS, ElastiCache, DynamoDB endpoints
- VPC endpoints for AWS services (S3, DynamoDB, Secrets Manager)

### Security Groups
- ALB: Ingress 443 from 0.0.0.0/0
- ECS: Ingress from ALB security group only
- RDS: Ingress 5432 from ECS security group only
- Redis: Ingress 6379 from ECS security group only

## Monitoring & Alerting

### Security Events Monitored
- Failed authentication attempts (> 5 in 1 minute)
- Authorization failures (403 responses)
- Rate limit violations (429 responses)
- Unusual data access patterns
- Configuration changes (audit log)

### Alert Channels
- CloudWatch Alarms → SNS → PagerDuty (critical)
- CloudWatch Alarms → SNS → Slack (high)
- Weekly security scan reports → Email

## Compliance

### GDPR Requirements
- Data inventory documented
- Privacy policy published
- Cookie consent implemented
- Data retention policies: 90 days for events, 1 year for audit logs
- Right to be forgotten: User deletion cascade
- Data portability: Export API endpoints

### SOC 2 Controls
- Access controls documented and enforced
- Change management via PR reviews
- Vendor management for AWS services
- Business continuity: Multi-AZ deployment
