# Security Documentation

This directory contains the security compliance documentation for Experimently.

| Document | Description |
|----------|-------------|
| [Threat Model](threat-model.md) | System threats and mitigations |
| [Incident Response Plan](incident-response-plan.md) | How to respond to security incidents |
| [Security Policies](security-policies.md) | Access control and data policies |
| [Hardening Changes](hardening-changes.md) | Security controls implemented |

## Quick Reference

- Report a security issue: security@yourcompany.com
- On-call for P0 incidents: See PagerDuty runbook
- Last audit date: March 2026
- Next review: June 2026

## Severity SLAs

| Severity | Initial Response | Description |
|----------|-----------------|-------------|
| P0 — Critical | < 15 minutes | Data breach, compromised admin credentials, service down |
| P1 — High | < 1 hour | Suspected unauthorized access, account takeover |
| P2 — Medium | < 4 hours | Anomalous access patterns, expired credentials |
| P3 — Low | < 24 hours | Informational findings, policy violations |

## Key Security Controls (Implemented)

- Security headers: HSTS (1yr + preload), CSP (`default-src 'none'`), X-Frame-Options: DENY — `backend/app/middleware/security_middleware.py`
- RBAC enforcement: 4 roles (ADMIN, DEVELOPER, ANALYST, VIEWER) — `backend/app/core/permissions.py`
- bcrypt password hashing — `backend/app/core/security.py`
- API key scoping and expiry — `backend/app/models/api_key.py`
- Audit logging for all CRUD operations — `backend/app/models/audit_log.py`
- Safety auto-rollback for feature flags — `backend/app/core/safety_scheduler.py`
- Structured logging with error sanitization — `backend/app/middleware/`

## Critical Items Before Production Launch

1. Replace `decode_token` stub with real Cognito JWT validation (`backend/app/core/security.py`)
2. Override weak default credentials (`FIRST_SUPERUSER_PASSWORD = "admin"` in `config.py`)
3. Hash API keys at rest (currently stored in plaintext in `api_keys.key`)
4. Add rate limiting to `/api/v1/auth/token` login endpoint
5. Reduce JWT expiry from 8 days to 1 hour with refresh token rotation
6. Enable AWS WAF with OWASP Core Rule Set
7. Enable AWS GuardDuty in all regions

See [Threat Model](threat-model.md) for full risk details and [Security Policies](security-policies.md) for controls.
