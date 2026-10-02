# Compliance Audit Trail API

!!! info "Partly in the `compliance` module"
    The event listing, `GET /api/v1/compliance/audit-events`, is core and answers in every
    profile. The SOC 2 / ISO 27001 reports and the export are the **compliance module's**:
    a core deployment still declares those two routes but answers them `501`, after the
    role check. HMAC signing of new events is also the module's; in a core deployment
    events are recorded unsigned. See [Modules and profiles](../getting-started/modules.md)
    for what each profile includes and how to run the full one.

The compliance audit trail is an append-only table of changes to experiments, feature flags
and (in the full profile) warehouse connections and sources. It is evidence for a
customer's SOC 2 or ISO 27001 program; the platform itself holds no certification.

It is a separate record from the [audit log](audit-logging.md) at `/api/v1/audit-logs`,
which records feature-flag status changes (toggle, enable, disable, bulk toggle). A flag
toggled on or off is written there, not here.

---

## What is recorded

Each row is a `ComplianceAuditEvent` with `outcome` `SUCCESS`. These are the only actions
that write one in this release:

| Action | `resource_type` | Written when | Profile |
|---|---|---|---|
| `CREATE` | `feature_flag` | `POST /api/v1/feature-flags/` | every |
| `UPDATE` | `feature_flag` | `PUT /api/v1/feature-flags/{id}` | every |
| `DELETE` | `feature_flag` | `DELETE /api/v1/feature-flags/{id}` | every |
| `CREATE` | `experiment` | `POST /api/v1/experiments/` | every |
| `UPDATE` | `experiment` | `PUT /api/v1/experiments/{id}` | every |
| `DELETE` | `experiment` | `DELETE /api/v1/experiments/{id}` | every |
| `CREATE`, `UPDATE`, `DELETE` | `warehouse_connection` | creating, changing or deleting a warehouse connection | full |
| `KEY_CREATE` | `warehouse_connection` | a new key is generated (`/regenerate-key`), or a pending key becomes current after a passing connection test | full |
| `CREATE`, `UPDATE`, `DELETE` | `warehouse_source` | creating, changing, validating or deleting a warehouse source | full |

Each event carries the actor's id, the resource id, and a snapshot of a few fields in
`old_value` and `new_value`: for a flag update, its key, name, status and rollout percentage;
for an experiment update, its name, status and targeting rules; a create records the new
key and name (a flag) or name (an experiment), and a delete the old key, name and status (a
flag) or name, status and owner (an experiment). Field names containing `password`, `token`,
`api_key` or `secret` are replaced with `[REDACTED]`.

Not recorded here: logins and logouts, failed logins, role changes, API key changes, flag
status changes (they go to the [audit log](audit-logging.md)), experiment start, pause and
completion, and reading, reporting on or exporting this trail. `AuditAction` defines `READ`,
`LOGIN`, `LOGOUT`, `LOGIN_FAILED`, `ROLE_GRANT`, `ROLE_REVOKE`, `KEY_REVOKE`, `EXPORT` and
`REPORT_GENERATED`, and you can filter on them, but nothing in this release writes them.

For flags and experiments, a failure to write the event does not fail the request that made
the change: the change is kept and the failure is logged as a warning.

**Base path**: `/api/v1/compliance`. Every route needs a Bearer token; without one it
answers `401`.

---

## Endpoints

### List Audit Events

```text
GET /api/v1/compliance/audit-events
```

Core, every profile. ADMIN or ANALYST (or a superuser); DEVELOPER and VIEWER get `403`.
Events are listed most recent first.

**Query Parameters**

| Parameter | Type | Description |
|---|---|---|
| `page` | int | Page number, from 1 (default `1`) |
| `limit` | int | Page size (default `50`, max `200`; more answers `422`) |
| `action` | string | An `AuditAction` value, e.g. `CREATE`; an unknown value answers `422` |
| `resource_type` | string | e.g. `experiment`, `feature_flag` |
| `actor_id` | UUID | The user who made the change |
| `start_time` | datetime | Events at or after this time (ISO 8601) |
| `end_time` | datetime | Events at or before this time (ISO 8601) |

**Example Request**

```bash
curl -s "localhost:8000/api/v1/compliance/audit-events?action=UPDATE&resource_type=experiment&limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

**Response: 200 OK**

```json
{
  "items": [
    {
      "id": "a5fd175e-7579-4cf8-92cf-832fa8dfe0b6",
      "timestamp": "2026-10-02T07:59:23.446805Z",
      "actor_id": "a5a661c7-2d02-46da-bf61-03e23b709ab6",
      "actor_ip": null,
      "actor_user_agent": null,
      "session_id": null,
      "request_id": null,
      "action": "UPDATE",
      "resource_type": "experiment",
      "resource_id": "15bdc848-21c5-4fb8-aa9f-462a34e375a6",
      "old_value": {"name": "Checkout Button Color", "status": "active", "targeting_rules": {}},
      "new_value": {"name": "Checkout Button Color", "status": "active", "targeting_rules": {}},
      "outcome": "SUCCESS",
      "hmac_signature": "09f48eec6ee1388d942b1a7a73eb2e08d4d4e4cfe78cec0121f4c7f6a7b480b2",
      "archived_at": null,
      "retention_expires_at": "2027-10-02T07:59:23.446828Z"
    }
  ],
  "total": 2,
  "page": 1,
  "limit": 20
}
```

`hmac_signature` is `null` for an event written without the compliance module.

---

### Compliance Report

```text
GET /api/v1/compliance/reports/{standard}
```

Compliance module. ADMIN or ANALYST (or a superuser). `standard` is `soc2` or `iso27001`;
any other value answers `400`. `start_time` and `end_time` (ISO 8601) set the period; by
default it ends now and starts `AUDIT_RETENTION_DAYS_SOC2` (365) or
`AUDIT_RETENTION_DAYS_ISO27001` (730) days earlier.

```bash
curl -s localhost:8000/api/v1/compliance/reports/soc2 \
  -H "Authorization: Bearer $TOKEN"
```

**Response: 200 OK**

```json
{
  "standard": "soc2",
  "period_start": "2025-10-02T07:59:24.089800Z",
  "period_end": "2026-10-02T07:59:24.089800Z",
  "generated_at": "2026-10-02T07:59:24.095773Z",
  "total_events": 5,
  "events_by_action": {"UPDATE": 3, "CREATE": 1, "DELETE": 1},
  "events_by_outcome": {"SUCCESS": 5},
  "events_by_resource_type": {"experiment": 2, "feature_flag": 3},
  "integrity_checks": 5,
  "tampered_events": 0,
  "integrity_pass_rate": 1.0,
  "unsigned_events": 0,
  "integrity_coverage": 1.0,
  "signing_enabled": true
}
```

The report counts the events in the period and checks each signature:

| Field | Meaning |
|---|---|
| `integrity_checks` | Events that carry a signature, all of which were checked |
| `tampered_events` | Signed events whose signature no longer matches |
| `integrity_pass_rate` | `(integrity_checks - tampered_events) / integrity_checks`; `1.0` when nothing was checked |
| `unsigned_events` | Events with no signature, which cannot be checked |
| `integrity_coverage` | `integrity_checks / total_events`: `1.0` only when every event in the period is signed |
| `signing_enabled` | Whether this process signs new events |

---

### Export Audit Events

```text
GET /api/v1/compliance/export
```

Compliance module. ADMIN (or a superuser) only; ANALYST gets `403`. `format` is `json`
(default) or `csv`, and `start_time` / `end_time` narrow it. The response is a download
(`Content-Disposition: attachment; filename=audit_export.json` or `.csv`) of every matching
event, oldest first, with the fields `id`, `timestamp`, `action`, `resource_type`,
`resource_id`, `actor_id`, `outcome` and `hmac_signature`. `old_value` and `new_value` are
not included.

```bash
curl -s "localhost:8000/api/v1/compliance/export?format=csv&start_time=2026-09-01T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN" \
  --output audit_export.csv
```

---

## Signing

With the compliance module installed, every new event is signed with HMAC-SHA256 before it
is stored, and the hex digest (64 characters) is kept in `hmac_signature`. The signature
covers the event's `id`, `timestamp`, `action`, `resource_type`, `resource_id`, `actor_id`
and `outcome`; `old_value` and `new_value` are not covered. The key is the `AUDIT_HMAC_KEY`
setting. In staging and production the API refuses to start with the development default
or with a key shorter than the minimum secret length.

The signatures are checked by the platform, in the compliance report above
(`integrity_checks`, `tampered_events`). Responses carry no signature header, and the
canonical form signed is not a published format, so check integrity through the report
rather than by recomputing a signature yourself.

---

## `AuditAction` Values

| Value | Written in this release |
|---|---|
| `CREATE` | Yes, see [What is recorded](#what-is-recorded) |
| `UPDATE` | Yes |
| `DELETE` | Yes |
| `KEY_CREATE` | Yes, warehouse connections only (full profile) |
| `READ`, `LOGIN`, `LOGOUT`, `LOGIN_FAILED`, `ROLE_GRANT`, `ROLE_REVOKE`, `KEY_REVOKE`, `EXPORT`, `REPORT_GENERATED` | No |

`outcome` is one of `SUCCESS`, `FAILURE` and `DENIED`; every event written in this release
is `SUCCESS`.

---

## Error Responses

| Status | Meaning |
|---|---|
| `400 Bad Request` | Unknown report `standard` |
| `401 Unauthorized` | Missing or invalid Bearer token |
| `403 Forbidden` | The caller's role may not use the route (see each route) |
| `422 Unprocessable Entity` | An invalid query parameter, e.g. an unknown `action`, a `limit` over 200, a bad date |
| `501 Not Implemented` | The report or export, on a deployment without the compliance module |

```json
{
  "detail": "Compliance audit logs require ADMIN or ANALYST role"
}
```
