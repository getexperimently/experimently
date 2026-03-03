# Compliance Audit Logging API (EP-033)

This document describes the compliance audit logging endpoints introduced in EP-033. The system provides SOC 2 Type II and ISO 27001-aligned audit trails with HMAC-SHA256 tamper-evident signing for all platform events.

---

## Overview

Every create, update, delete, login, permission change, and data export action performed through the platform is recorded as a signed `AuditEvent`. Each event carries an `X-Audit-Signature` header (HMAC-SHA256) so that downstream consumers can verify that logs have not been altered in transit or at rest.

**Base path**: `/api/v1/compliance`

**Authentication**: All compliance endpoints require a valid Bearer token. Minimum role: **ANALYST** for read access; **ADMIN** for export.

---

## Endpoints

### List Audit Events

```
GET /api/v1/compliance/audit-events
```

Returns a paginated list of audit events, optionally filtered by action type, resource type, actor, or time range.

**Query Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `page` | `int` | No | Page number (1-indexed, default: `1`) |
| `page_size` | `int` | No | Items per page (default: `50`, max: `500`) |
| `action` | `string` | No | Filter by `AuditAction` enum value (e.g., `CREATE`, `DELETE`) |
| `resource_type` | `string` | No | Filter by resource type (e.g., `experiment`, `feature_flag`, `user`) |
| `actor_id` | `string` | No | Filter by the UUID of the user who performed the action |
| `start_date` | `datetime` | No | ISO 8601 UTC start of time window (inclusive) |
| `end_date` | `datetime` | No | ISO 8601 UTC end of time window (inclusive) |

**Example Request**

```bash
curl -X GET "https://your-platform.example.com/api/v1/compliance/audit-events?action=DELETE&resource_type=experiment&page=1&page_size=20" \
  -H "Authorization: Bearer your_access_token"
```

**Response: 200 OK**

```json
{
  "items": [
    {
      "id": "ae1c3f22-7b4d-4e1a-9b2c-0f3d5e6a7b8c",
      "action": "DELETE",
      "resource_type": "experiment",
      "resource_id": "exp-uuid-here",
      "actor_id": "usr-uuid-here",
      "actor_username": "jane.smith",
      "timestamp": "2026-01-15T10:30:00Z",
      "ip_address": "203.0.113.45",
      "user_agent": "Mozilla/5.0 ...",
      "details": {
        "experiment_name": "Button Color Test",
        "previous_status": "DRAFT"
      },
      "signature": "sha256=a1b2c3d4e5f6..."
    }
  ],
  "total": 142,
  "page": 1,
  "page_size": 20,
  "pages": 8
}
```

---

### SOC 2 Compliance Report

```
GET /api/v1/compliance/reports/soc2
```

Returns a rolling 365-day compliance summary covering all audit events relevant to SOC 2 Trust Service Criteria (Security, Availability, Confidentiality, Processing Integrity, Privacy).

**Authentication**: ADMIN role required.

**Example Request**

```bash
curl -X GET "https://your-platform.example.com/api/v1/compliance/reports/soc2" \
  -H "Authorization: Bearer your_admin_token"
```

**Response: 200 OK**

```json
{
  "report_type": "SOC2",
  "generated_at": "2026-03-02T00:00:00Z",
  "period_start": "2025-03-02T00:00:00Z",
  "period_end": "2026-03-02T00:00:00Z",
  "summary": {
    "total_events": 58341,
    "by_action": {
      "CREATE": 12450,
      "UPDATE": 28901,
      "DELETE": 3210,
      "READ": 9800,
      "LOGIN": 2100,
      "LOGOUT": 1880,
      "PERMISSION_CHANGE": 320,
      "CONFIG_CHANGE": 154,
      "EXPORT": 526
    },
    "unique_actors": 47,
    "flagged_events": 3,
    "failed_login_attempts": 18
  },
  "controls": [
    {
      "control_id": "CC6.1",
      "description": "Logical and physical access controls",
      "status": "COMPLIANT",
      "evidence_count": 2420
    }
  ]
}
```

---

### ISO 27001 Compliance Report

```
GET /api/v1/compliance/reports/iso27001
```

Returns a rolling 730-day compliance summary aligned with ISO/IEC 27001:2022 Annex A controls.

**Authentication**: ADMIN role required.

**Example Request**

```bash
curl -X GET "https://your-platform.example.com/api/v1/compliance/reports/iso27001" \
  -H "Authorization: Bearer your_admin_token"
```

**Response: 200 OK**

```json
{
  "report_type": "ISO27001",
  "generated_at": "2026-03-02T00:00:00Z",
  "period_start": "2024-03-02T00:00:00Z",
  "period_end": "2026-03-02T00:00:00Z",
  "summary": {
    "total_events": 119882,
    "unique_actors": 63,
    "flagged_events": 7,
    "by_action": {
      "CREATE": 24900,
      "UPDATE": 57802,
      "DELETE": 6420,
      "LOGIN": 4200,
      "LOGOUT": 3760,
      "PERMISSION_CHANGE": 640,
      "CONFIG_CHANGE": 308,
      "EXPORT": 1052,
      "READ": 20800
    }
  },
  "controls": [
    {
      "control_id": "A.9.4.1",
      "description": "Information access restriction",
      "status": "COMPLIANT",
      "evidence_count": 4840
    },
    {
      "control_id": "A.12.4.1",
      "description": "Event logging",
      "status": "COMPLIANT",
      "evidence_count": 119882
    }
  ]
}
```

---

### Export Audit Events

```
GET /api/v1/compliance/export
```

Streams the full audit log (or a filtered subset) as either JSON or CSV. Suitable for ingestion into SIEM tools or long-term archival storage.

**Authentication**: ADMIN role required.

**Query Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `format` | `string` | No | `json` or `csv` (default: `json`) |
| `action` | `string` | No | Filter by `AuditAction` value |
| `resource_type` | `string` | No | Filter by resource type |
| `actor_id` | `string` | No | Filter by actor UUID |
| `start_date` | `datetime` | No | ISO 8601 UTC start (inclusive) |
| `end_date` | `datetime` | No | ISO 8601 UTC end (inclusive) |

**Example Requests**

```bash
# JSON export — last 30 days
curl -X GET "https://your-platform.example.com/api/v1/compliance/export?format=json&start_date=2026-02-01T00:00:00Z" \
  -H "Authorization: Bearer your_admin_token" \
  --output audit_export.json

# CSV export — all DELETE events
curl -X GET "https://your-platform.example.com/api/v1/compliance/export?format=csv&action=DELETE" \
  -H "Authorization: Bearer your_admin_token" \
  --output deletes.csv
```

**Response**: `200 OK` with `Content-Type: application/json` (or `text/csv`) and `Transfer-Encoding: chunked` for streaming.

---

## HMAC-SHA256 Signing

Every audit event is signed server-side before it is persisted. The `signature` field on each event can be independently verified by consumers.

### Signature Header

For API responses that include a collection of audit events, the HTTP response also carries the header:

```
X-Audit-Signature: sha256=<hex-encoded HMAC>
```

The HMAC covers the JSON-serialised response body (UTF-8 encoded, compact form without trailing whitespace).

### Per-Event Payload Format

The HMAC input for each individual event is a canonical JSON string containing the following fields in this exact order:

```json
{
  "id": "<uuid>",
  "action": "<AuditAction>",
  "resource_type": "<string>",
  "resource_id": "<string>",
  "actor_id": "<string>",
  "timestamp": "<ISO8601-UTC>",
  "details": { ... }
}
```

The HMAC secret is an environment secret (`AUDIT_HMAC_SECRET`) stored in AWS Secrets Manager and rotated quarterly. The algorithm is **HMAC-SHA256** with hex encoding (lowercase).

### Verification Example (Python)

```python
import hmac
import hashlib
import json

def verify_audit_event(event: dict, secret: str) -> bool:
    payload = json.dumps({
        "id": event["id"],
        "action": event["action"],
        "resource_type": event["resource_type"],
        "resource_id": event["resource_id"],
        "actor_id": event["actor_id"],
        "timestamp": event["timestamp"],
        "details": event["details"],
    }, separators=(",", ":"), sort_keys=False)

    expected = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    provided = event["signature"].removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)
```

---

## `AuditAction` Enum

| Value | Description |
|---|---|
| `CREATE` | A new resource was created (experiment, flag, user, integration, etc.) |
| `UPDATE` | An existing resource was modified |
| `DELETE` | A resource was deleted or deactivated |
| `READ` | A sensitive resource was accessed (e.g., audit log export, PII read) |
| `LOGIN` | A user successfully authenticated |
| `LOGOUT` | A user session was terminated |
| `PERMISSION_CHANGE` | A user's role or permissions were modified |
| `CONFIG_CHANGE` | A platform-level configuration was updated (safety settings, scheduler config) |
| `EXPORT` | Data was exported (compliance report, CSV/JSON export) |

---

## Error Responses

| Status | Meaning |
|---|---|
| `401 Unauthorized` | Missing or invalid Bearer token |
| `403 Forbidden` | Authenticated user lacks required role (ANALYST / ADMIN) |
| `422 Unprocessable Entity` | Invalid query parameter value (e.g., bad date format) |
| `500 Internal Server Error` | Unexpected server error |

```json
{
  "detail": "Not enough permissions to access compliance endpoints"
}
```
