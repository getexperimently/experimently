# Audit Logging & Bulk Toggle

The platform maintains a complete audit trail of all system actions — experiment state changes, feature flag toggles, permission grants, user management operations, and more. Audit logs are immutable and append-only.

---

## Audit Log API

### GET /api/v1/audit-logs

Query the audit log with filters.

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity_type` | string | Filter by entity: `experiment`, `feature_flag`, `user`, `role` |
| `entity_id` | UUID | Filter by specific entity ID |
| `action_type` | string | Filter by action (see Action Types below) |
| `user_id` | UUID | Filter by the user who performed the action |
| `start_date` | datetime | Filter actions after this timestamp |
| `end_date` | datetime | Filter actions before this timestamp |
| `skip` | int | Pagination offset |
| `limit` | int | Page size (default: 50, max: 200) |

```bash
curl -X GET "http://localhost:8000/api/v1/audit-logs?entity_type=feature_flag&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

**Response**

```json
{
  "items": [
    {
      "id": "log-uuid",
      "action_type": "TOGGLE_ENABLE",
      "entity_type": "feature_flag",
      "entity_id": "flag-uuid",
      "entity_name": "dark-mode",
      "user_id": "user-uuid",
      "username": "jane.doe",
      "changes": {
        "status": {"before": "inactive", "after": "active"}
      },
      "ip_address": "10.0.1.42",
      "created_at": "2026-03-02T14:32:00Z"
    }
  ],
  "total": 284,
  "skip": 0,
  "limit": 20
}
```

---

### GET /api/v1/audit-logs/{log_id}

Retrieve a single audit log entry with full detail.

---

### GET /api/v1/audit-logs/stats

Returns aggregate statistics: total events, events by action type, most active users, most modified entities.

```bash
curl -X GET "http://localhost:8000/api/v1/audit-logs/stats" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Action Types

| Action Type | Description |
|-------------|-------------|
| `CREATE` | Entity created |
| `UPDATE` | Entity updated |
| `DELETE` | Entity deleted |
| `TOGGLE_ENABLE` | Feature flag enabled |
| `TOGGLE_DISABLE` | Feature flag disabled |
| `ARCHIVE` | Entity archived |
| `ACTIVATE` | Experiment activated |
| `PAUSE` | Experiment paused |
| `COMPLETE` | Experiment completed |
| `PERMISSION_GRANT` | Permission granted to user |
| `PERMISSION_REVOKE` | Permission revoked from user |
| `BULK_TOGGLE` | Multiple flags toggled in one operation |

---

## Real-Time Audit Stream (SSE)

Subscribe to a Server-Sent Events (SSE) stream of live audit events. The stream replays the last 100 events on connect, then pushes new events as they occur.

```bash
curl -N "http://localhost:8000/api/v1/audit-logs/stream" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: text/event-stream"
```

**Stream Format**

```
data: {"id": "log-uuid", "action_type": "TOGGLE_ENABLE", "entity_type": "feature_flag", "entity_name": "dark-mode", "username": "jane.doe", "created_at": "2026-03-02T14:32:00Z"}

data: {"id": "log-uuid-2", "action_type": "ACTIVATE", "entity_type": "experiment", "entity_name": "checkout-v2", "username": "john.smith", "created_at": "2026-03-02T14:33:00Z"}
```

The SSE stream is used by the Admin UI's real-time activity feed. Each event is a JSON object on a `data:` line.

---

## Bulk Feature Flag Toggle

Toggle multiple feature flags in a single API call. Results are returned per-flag — the operation is partial-success by design, meaning some flags can succeed even if others fail.

### POST /api/v1/feature-flags/bulk-toggle

```bash
curl -X POST "http://localhost:8000/api/v1/feature-flags/bulk-toggle" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "flag_ids": ["flag-uuid-1", "flag-uuid-2", "flag-uuid-3"],
    "action": "disable"
  }'
```

**Actions**: `enable`, `disable`, `archive`

**Response**

```json
{
  "results": [
    {"flag_id": "flag-uuid-1", "flag_key": "dark-mode", "success": true, "error": null},
    {"flag_id": "flag-uuid-2", "flag_key": "new-checkout", "success": true, "error": null},
    {"flag_id": "flag-uuid-3", "flag_key": "beta-feature", "success": false, "error": "Feature flag not found"}
  ],
  "audit_log_ids": ["log-uuid-1", "log-uuid-2"],
  "succeeded": 2,
  "failed": 1
}
```

Each successfully processed flag generates an individual audit log entry.

---

## Feature Flag Change History

### GET /api/v1/feature-flags/{flag_id}/history

Returns the full change history for a specific feature flag, ordered by most recent first.

```bash
curl -X GET "http://localhost:8000/api/v1/feature-flags/flag-uuid/history" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "flag_id": "flag-uuid",
  "flag_key": "dark-mode",
  "history": [
    {
      "action_type": "TOGGLE_ENABLE",
      "username": "jane.doe",
      "changes": {"status": {"before": "inactive", "after": "active"}},
      "created_at": "2026-03-02T14:32:00Z"
    },
    {
      "action_type": "UPDATE",
      "username": "john.smith",
      "changes": {"rollout_percentage": {"before": 25, "after": 50}},
      "created_at": "2026-02-28T09:15:00Z"
    }
  ]
}
```

---

## Permissions

| Action | Minimum Role |
|--------|-------------|
| View audit logs | ANALYST |
| View audit stats | ANALYST |
| Subscribe to SSE stream | ANALYST |
| Bulk toggle feature flags | DEVELOPER |
| View flag change history | ANALYST |
