# Audit Logging & Bulk Toggle

The audit log is an append-only record of who changed what. In this release it records
**feature-flag status changes**: turning a flag on or off (one at a time or in bulk) and
archiving it in bulk, and an administrator changing a user's role or active status with
`PATCH /api/v1/admin/users/{user_id}`. Other actions, such as creating an experiment, logging in or
assigning a role, are not written to it yet
([#221](https://github.com/getexperimently/experimently/issues/221)). The Quick Start's
demo data includes entries of those kinds, written by the seed script, not by the
platform.

Creating, changing and deleting a feature flag or an experiment is recorded in a separate
table, the compliance audit trail, which `GET /api/v1/compliance/audit-events` lists in
every profile; see [Compliance Audit Trail](compliance.md#what-is-recorded) for what it
holds. Logging in and assigning a role are recorded in neither.

Run the commands on this page in one terminal, in order, against the stack from the
[Quick Start](../getting-started/quick-start.md). Each uses the shell variables set by the
ones before it. Log in first:

```{.bash exec}
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.com","password":"Demo1234!"}' | jq -r .access_token)

curl -s localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN" | jq .role
```
<!-- expect: "ADMIN" -->

It prints `"ADMIN"`.

---

## Bulk Feature Flag Toggle

Toggle several feature flags in one call. Each flag succeeds or fails on its own: the
call answers `200` with a result per flag, even when some of them fail.

These two flags give the call something to change. They are created on
(`"is_active": true`; a new flag is off otherwise). This saves their ids in `$DARK_ID`
and `$CHECKOUT_ID`:

```{.bash exec}
DARK_ID=$(curl -s -X POST localhost:8000/api/v1/feature-flags/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"key": "dark-mode", "name": "Dark mode", "is_active": true}' | jq -r .id)
CHECKOUT_ID=$(curl -s -X POST localhost:8000/api/v1/feature-flags/ \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"key": "new-checkout", "name": "New checkout", "is_active": true}' | jq -r .id)

echo "$DARK_ID $CHECKOUT_ID" | wc -w
```
<!-- expect: 2 -->

It prints `2`, one id per flag.

### POST /api/v1/feature-flags/bulk-toggle

`action` is `enable`, `disable` or `archive`, and `reason` is optional. This turns off
both flags, and a third id that doesn't exist:

```{.bash exec}
curl -s -X POST localhost:8000/api/v1/feature-flags/bulk-toggle \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{
    "flag_ids": ["'"$DARK_ID"'", "'"$CHECKOUT_ID"'", "00000000-0000-0000-0000-000000000000"],
    "action": "disable",
    "reason": "Checkout incident"
  }' | jq '{total, succeeded, failed, errors: [.results[].error]}'
```
<!-- expect: "total": 3 -->
<!-- expect: "succeeded": 2 -->
<!-- expect: "failed": 1 -->
<!-- expect: "Feature flag not found" -->

It prints `"succeeded": 2` and `"failed": 1`, with the error `"Feature flag not found"`
for the third id. The full response lists each flag's result, and the id of the audit
entry written for each flag that changed:

```json
{
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "results": [
    {"flag_id": "851811d2-…", "flag_key": "dark-mode", "success": true, "error": null, "old_status": "ACTIVE", "new_status": "INACTIVE"},
    {"flag_id": "392fd547-…", "flag_key": "new-checkout", "success": true, "error": null, "old_status": "ACTIVE", "new_status": "INACTIVE"},
    {"flag_id": "00000000-0000-0000-0000-000000000000", "flag_key": "unknown", "success": false, "error": "Feature flag not found", "old_status": null, "new_status": null}
  ],
  "audit_log_ids": ["9d0a668c-…", "b0322b63-…"]
}
```

A flag the caller may not change (an ANALYST or VIEWER changes none) fails with
`"Not enough permissions to change this feature flag"` and is left as it was.

---

## Audit Log API

### GET /api/v1/audit-logs/

Query the audit log with filters. The URL ends with a slash; without it the API answers
`307`.

**Query Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity_type` | string | `feature_flag`, `experiment`, `user`, `role`, `permission`, `safety_config`, `rollout_schedule` |
| `entity_id` | UUID | Filter by specific entity ID |
| `action_type` | string | Filter by action (see Action Types below) |
| `user_id` | UUID | Filter by the user who performed the action |
| `from_date` | datetime | Entries at or after this time (ISO 8601) |
| `to_date` | datetime | Entries at or before this time (ISO 8601) |
| `page` | int | Page number, from 1 (default: 1) |
| `limit` | int | Page size (default: 50, max: 1000) |

An unknown `entity_type` or `action_type` answers `400`. This lists the two entries the
bulk toggle wrote:

```{.bash exec}
curl -s "localhost:8000/api/v1/audit-logs/?entity_type=feature_flag&action_type=toggle_disable" \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{total, entries: [.items[] | {entity_name, old_value, new_value, reason}]}'
```
<!-- expect: "total": 2 -->
<!-- expect: "old_value": "ACTIVE" -->
<!-- expect: "new_value": "INACTIVE" -->
<!-- expect: "reason": "Checkout incident" -->

It prints `"total": 2`, and for each flag its old and new status and the reason given.
One entry in full:

```json
{
  "user_email": "admin@demo.com",
  "action_type": "toggle_disable",
  "entity_type": "feature_flag",
  "entity_id": "851811d2-58aa-464b-9ebc-8cc3650f19ae",
  "entity_name": "Dark mode",
  "old_value": "ACTIVE",
  "new_value": "INACTIVE",
  "reason": "Checkout incident",
  "id": "9d0a668c-8ef3-4046-8fd5-49053afddb0a",
  "user_id": "2658dd18-4167-4803-9aff-a3ffb1f603ce",
  "timestamp": "2026-09-26T22:52:28.781081Z",
  "action_description": "disabled",
  "created_at": "2026-09-26T22:52:28.781394",
  "updated_at": "2026-09-26T22:52:28.781395"
}
```

The list also carries `page`, `limit` and `total_pages`.

---

### GET /api/v1/audit-logs/entity/{entity_type}/{entity_id}

Every entry recorded against one entity, most recent first. There is no fetch-one-by-id
route; query by entity, by actor (`/audit-logs/user/{user_id}`), or filter the collection
(`/audit-logs/`):

```{.bash exec}
curl -s localhost:8000/api/v1/audit-logs/entity/feature_flag/$DARK_ID \
  -H "Authorization: Bearer $TOKEN" | jq -r '.[].action_type'
```
<!-- expect: toggle_disable -->

It prints `toggle_disable`, the one entry for the dark-mode flag.

---

### GET /api/v1/audit-logs/stats

Returns counts: the total, per action type, per entity type, and per user. `from_date` and
`to_date` narrow it:

```{.bash exec}
curl -s localhost:8000/api/v1/audit-logs/stats \
  -H "Authorization: Bearer $TOKEN" | jq '.action_counts.toggle_disable'
```
<!-- expect: 2 -->

It prints `2`. The whole response has the shape
`{"total_logs", "action_counts", "entity_counts", "most_active_users", "date_range"}`.

---

## Action Types

| Action Type | Written when |
|-------------|--------------|
| `toggle_enable` | A flag is turned on (`/toggle`, `/enable`, or bulk `enable`) |
| `toggle_disable` | A flag is turned off (`/toggle`, `/disable`, or bulk `disable`) |
| `feature_flag_update` | A flag is archived by bulk toggle, or unarchived (`/unarchive`) |
| `user_update` | A superuser changes a user's role or active status (`PATCH /api/v1/admin/users/{user_id}`); `old_value` and `new_value` are JSON with `role` and `is_active` |

`ActionType` also defines `feature_flag_create`, `feature_flag_delete`, `feature_flag_activate`, `feature_flag_deactivate`,
`experiment_create`, `experiment_update`, `experiment_delete`, `experiment_start`,
`experiment_pause`, `experiment_complete`, `user_create`, `user_delete`,
`user_login`, `user_logout`, `permission_grant`, `permission_revoke`, `role_assign`,
`role_unassign`, `safety_rollback` and `safety_config_update`. You can filter on them, but
nothing in this release writes them
([#221](https://github.com/getexperimently/experimently/issues/221)).

---

## Recent Entries as a Stream (SSE)

`GET /api/v1/audit-logs/stream` sends the most recent entries as Server-Sent Events: one
`data:` line per entry, newest first, then a final `{"event": "end"}`, and closes. It does
not stay open for new entries. `limit` (default 50, max 100) and `entity_type` narrow it:

```{.bash exec}
curl -s -N "localhost:8000/api/v1/audit-logs/stream?limit=2&entity_type=feature_flag" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: text/event-stream"
```
<!-- expect: data: {"id": -->
<!-- expect: "action_type": "toggle_disable" -->
<!-- expect: data: {"event": "end"} -->

It prints the two `toggle_disable` entries, then the end event:

```text
data: {"id": "b0322b63-…", "timestamp": "2026-09-26T22:52:28.784985+00:00", "user_email": "admin@demo.com", "action_type": "toggle_disable", "entity_type": "feature_flag", "entity_name": "New checkout", "old_value": "ACTIVE", "new_value": "INACTIVE"}

data: {"id": "9d0a668c-…", "timestamp": "2026-09-26T22:52:28.781081+00:00", "user_email": "admin@demo.com", "action_type": "toggle_disable", "entity_type": "feature_flag", "entity_name": "Dark mode", "old_value": "ACTIVE", "new_value": "INACTIVE"}

data: {"event": "end"}
```

---

## Feature Flag Change History

### GET /api/v1/feature-flags/{flag_id}/history

The audit entries for one flag, most recent first, with `limit` (default 50, max 200) and
`offset`:

```{.bash exec}
curl -s localhost:8000/api/v1/feature-flags/$CHECKOUT_ID/history \
  -H "Authorization: Bearer $TOKEN" \
  | jq '{flag_key, total_changes, latest: .history[0] | {action_type, old_value, new_value, user_email}}'
```
<!-- expect: "flag_key": "new-checkout" -->
<!-- expect: "total_changes": 1 -->
<!-- expect: "action_type": "toggle_disable" -->

It prints `"total_changes": 1` and the bulk toggle's entry: `toggle_disable`, from
`ACTIVE` to `INACTIVE`, by `admin@demo.com`.

---

## Permissions

ADMIN and ANALYST (and superusers) read every audit entry. DEVELOPER and
VIEWER read only the entries they made themselves.

| Route | ADMIN, ANALYST | DEVELOPER, VIEWER |
|-------|----------------|-------------------|
| `GET /audit-logs/` | Every entry; `user_id` filters by any user | Own entries only; a `user_id` naming anyone else is replaced by their own |
| `GET /audit-logs/user/{user_id}` | Any user | Their own id only; any other id is 403 |
| `GET /audit-logs/entity/{entity_type}/{entity_id}` | Every entry | 403 |
| `GET /audit-logs/stats` | Every entry | 403 |
| `GET /audit-logs/stream` | Every entry | Own entries only |
| `GET /feature-flags/{flag_id}/history` | Every entry | Own entries only; `total_changes` counts only those |

`POST /feature-flags/bulk-toggle` changes flags, so it follows the flag rule:
ADMIN and DEVELOPER may use it, ANALYST and VIEWER may not.
