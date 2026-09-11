# Backend Security Hardening Changes

**Epic**: EP-018 — Security Audit
**Date**: 2026-03-01
**Author**: Agent 2 (Backend Security Hardening)

---

## Summary

This document describes the concrete security improvements applied to the FastAPI backend as part of EP-018.  The changes fall into five areas: security response headers, in-memory rate limiting, CORS hardening, Pydantic input length constraints, and security.py improvements.

---

## 1. Security Response Headers (`backend/app/middleware/security_middleware.py`)

### What changed

The existing `SecurityHeadersMiddleware` was rewritten to:

- Apply a **strict Content-Security-Policy** (`default-src 'none'; frame-ancestors 'none'`) instead of the permissive policy that allowed `unsafe-inline` and `unsafe-eval`.  An API-only service has no need to serve scripts, styles, or frames.
- Always emit **HSTS** (`max-age=31536000; includeSubDomains; preload`) on all responses, not only in production.  HTTPS enforcement is the responsibility of the load balancer; the header is safe to emit unconditionally.
- **Remove server fingerprinting headers** (`server`, `x-powered-by`) to reduce the information available to an attacker.
- Expand **Permissions-Policy** to additionally restrict `usb` and `magnetometer`.

Headers now set on every response:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `X-XSS-Protection` | `1; mode=block` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `geolocation=(), microphone=(), camera=(), payment=(), usb=(), magnetometer=()` |
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains; preload` |
| `Content-Security-Policy` | `default-src 'none'; frame-ancestors 'none'` |

### Why it matters

Security headers are the last line of defence against a range of client-side attacks (XSS, clickjacking, MIME-sniffing, information disclosure).  The old CSP was effectively disabled by `unsafe-inline` and `unsafe-eval`; the new policy is appropriate for a JSON API that serves no HTML.

---

## 2. Rate Limiting (`backend/app/middleware/rate_limiter.py`)

### What changed

`RateLimitMiddleware` enforces per-IP, per-path sliding-window limits. Counters live in Redis
(`RedisRateLimiter`, shared across API instances); when Redis is unreachable the middleware falls back to
an in-process sliding window so requests are never rejected because the limiter is down.

Limits are resolved by `resolve_rate_limit(path)`: exact entries first, then SDK path prefixes, then the
default.

| Route | Limit | Window |
|---|---|---|
| `POST /api/v1/auth/token` | 10 req | 60 s |
| `POST /api/v1/auth/signup` | 5 req | 60 s |
| `POST /api/v1/auth/forgot-password` | 5 req | 60 s |
| `POST /api/v1/auth/reset-password` | 5 req | 60 s |
| SDK traffic: `/api/v1/tracking/*`, `/api/v1/feature-flags/evaluate/*`, `/api/v1/feature-flags/user/*` | `SDK_RATE_LIMIT_PER_MINUTE` (default 6 000 req) | 60 s |
| All other routes | 300 req | 60 s |

The SDK ceiling is per IP and deliberately high: one server-side SDK or one office NAT egress legitimately
fans out thousands of assignments and events a minute. Tune it with the `SDK_RATE_LIMIT_PER_MINUTE`
setting.

Rate-limited responses return HTTP 429 with `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Window` headers.  Successful responses also carry the `X-RateLimit-*` informational headers.

### Why it matters

Without rate limiting, authentication endpoints are vulnerable to credential-stuffing and brute-force attacks.  Tracking endpoints without limits could be used to generate arbitrary event noise or exhaust server resources.

---

## 3. CORS Hardening (`backend/app/main.py`)

### What changed

The CORS middleware configuration was tightened:

- `allow_methods` changed from `["*"]` to an explicit list: `["GET", "POST", "PUT", "DELETE", "PATCH"]`.  `OPTIONS` is handled automatically by the CORS middleware; `HEAD` and `TRACE` are not needed.
- `allow_headers` changed from `["*"]` to an explicit list: `["Authorization", "Content-Type", "X-API-Key"]`.  Only headers the API actually uses are permitted.
- `expose_headers` was added: `["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"]` so clients can read these response headers cross-origin.
- A safe fallback (`http://localhost:3000`) is applied if `BACKEND_CORS_ORIGINS` is empty, preventing inadvertent wildcard origins.

### Why it matters

Wildcard CORS settings (`allow_methods=["*"]`, `allow_headers=["*"]`) provide no protection.  Restricting to explicitly needed values reduces the CORS attack surface.

---

## 4. Input Length Constraints (`backend/app/schemas/`)

### What changed

**`experiment.py`**

| Field | Before | After |
|---|---|---|
| `ExperimentBase.name` | `max_length=100` | `max_length=255` |
| `ExperimentBase.description` | no constraint | `max_length=2000` |
| `ExperimentBase.hypothesis` | no constraint | `max_length=2000` |
| `ExperimentUpdate.name` | `max_length=100` | `max_length=255` |
| `ExperimentUpdate.description` | no constraint | `max_length=2000` |
| `ExperimentUpdate.hypothesis` | no constraint | `max_length=2000` |

**`feature_flag.py`**

| Field | Before | After |
|---|---|---|
| `FeatureFlagBase.name` | `max_length=100` | `max_length=255` |
| `FeatureFlagBase.description` | no constraint | `max_length=2000` |
| `FeatureFlagBase.key` validator | lowercase + alnum check | stricter regex `^[a-z0-9][a-z0-9_-]*$` |

**`tracking.py`**

| Field | Before | After |
|---|---|---|
| `EventBase.user_id` | no constraint | `max_length=255` |
| `EventBase.session_id` | no constraint | `max_length=255` |
| `EventBase.experiment_id` | no constraint | `max_length=255` |
| `EventBase.feature_flag_id` | no constraint | `max_length=255` |
| `EventBase.variant_id` | no constraint | `max_length=255` |
| `AssignmentBase.*` | same as above | `max_length=255` |
| `AssignmentRequest.experiment_key` | `min_length=1` only | + `max_length=100` |
| `AssignmentRequest.user_id` | `min_length=1` only | + `max_length=255` |
| `EventRequest.event_type` | no constraint | `min_length=1, max_length=100` |
| `EventQueryParams.user_id` | no constraint | `max_length=255` |
| `EventQueryParams.event_type` | no constraint | `max_length=100` |

### Why it matters

Unbounded string fields can be exploited to:
- Cause excessively large database rows / index entries.
- Trigger O(n) processing in downstream logic (e.g., logging, serialisation).
- In the absence of a WAF, provide a vector for simple denial-of-service via large payloads.

Pydantic validates these limits before any database interaction occurs.

---

## 5. Configuration Hardening (`backend/app/core/config.py`)

### What changed

1. Added `CORS_ORIGINS: List[str]` as an alternative plain-string CORS origins config that can be set via env var as a comma-separated string.

2. Added a `validate_secret_key` field validator that raises a `ValueError` at application startup if:
   - `ENVIRONMENT == "prod"` **and** `TESTING` env var is not set
   - `SECRET_KEY` is shorter than 32 characters **or** is one of the well-known weak defaults (`default-secret-key-for-testing`, `secret`, `changeme`, etc.)

   This prevents the application from starting in production with a weak key.

3. Added `model_validator` import (was missing after adding the new validator).

### Why it matters

A weak `SECRET_KEY` in production allows an attacker who obtains the key to forge arbitrary JWT tokens and bypass authentication entirely.  Failing fast at startup prevents silent misconfiguration from reaching production traffic.

---

## 6. Security Utility Improvements (`backend/app/core/security.py`)

### What changed

- Added a security-focused module docstring explaining the role of each function and clearly stating that `decode_token` is a stub for testing only.
- `decode_token` now logs a `WARNING` if called outside a test context (i.e. when `TESTING` env var is not set), making it easier to detect accidental non-test usage.

### Why it matters

The `decode_token` stub returns hardcoded values and performs no signature verification.  Making its test-only nature explicit both in documentation and at runtime reduces the risk of it being used accidentally in production code paths.

---

## Follow-Up Items

| Priority | Item |
|---|---|
| High | Replace in-memory rate limiter with Redis-backed solution before horizontal scaling |
| High | Audit all remaining schemas for missing length constraints (user.py, auth.py, metrics.py) |
| Medium | Consider adding a WAF (AWS WAF) in front of the API for additional protection |
| Medium | Evaluate whether `Access-Token-Expire-Minutes` (currently 8 days) is too long for the security posture |
| Low | Remove `JSONResponse` import from `main.py` if it is no longer used after this change |
| Low | Add integration tests that verify security headers are present in API responses |
| Low | Add integration tests that verify rate limiting triggers HTTP 429 on auth endpoints |
