# Third-Party Integrations API (EP-034)

This document describes the third-party integrations endpoints introduced in EP-034. The platform supports bidirectional sync with Jira, Salesforce, and GitHub, enabling experiment lifecycle events to flow into your existing tooling.

---

## Overview

Each integration is represented as a persisted configuration record containing the service type, credentials, and connection metadata. Incoming events from external services are handled via per-integration webhook endpoints.

**Base path**: `/api/v1/integrations`

**Authentication**: All endpoints require a valid Bearer token. Minimum role: **DEVELOPER** for create/update/delete; **ANALYST** for read.

---

## `IntegrationType` Enum

| Value | Description |
|---|---|
| `JIRA` | Atlassian Jira — link experiments to issues and sync status |
| `SALESFORCE` | Salesforce CRM — push experiment results to campaign objects |
| `GITHUB` | GitHub — create issues/PRs and receive webhook events on repo activity |

---

## CRUD Endpoints

### Create Integration

```
POST /api/v1/integrations
```

Creates a new integration configuration. The `config` object structure varies by `integration_type` (see [Per-Service Config Schemas](#per-service-config-schemas) below).

**Authentication**: DEVELOPER role required.

**Request Body**

```json
{
  "name": "My Jira Integration",
  "integration_type": "JIRA",
  "description": "Links experiments to Jira tickets in the EXP project",
  "config": {
    "base_url": "https://your-org.atlassian.net",
    "username": "automation@your-org.com",
    "api_token": "ATATT3x..."
  }
}
```

**Response: 201 Created**

```json
{
  "id": "int-uuid-here",
  "name": "My Jira Integration",
  "integration_type": "JIRA",
  "description": "Links experiments to Jira tickets in the EXP project",
  "is_active": true,
  "created_at": "2026-01-15T09:00:00Z",
  "updated_at": "2026-01-15T09:00:00Z",
  "created_by": "usr-uuid-here"
}
```

---

### List Integrations

```
GET /api/v1/integrations
```

Returns all integrations visible to the authenticated user. Optionally filter by type.

**Authentication**: ANALYST role required.

**Query Parameters**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `type` | `string` | No | Filter by `IntegrationType` value (`JIRA`, `SALESFORCE`, `GITHUB`) |
| `is_active` | `boolean` | No | Filter by active/inactive status |
| `skip` | `int` | No | Pagination offset (default: `0`) |
| `limit` | `int` | No | Page size (default: `50`, max: `200`) |

**Example Request**

```bash
curl -X GET "https://your-platform.example.com/api/v1/integrations?type=GITHUB" \
  -H "Authorization: Bearer your_access_token"
```

**Response: 200 OK**

```json
[
  {
    "id": "int-uuid-here",
    "name": "GitHub Experiments Repo",
    "integration_type": "GITHUB",
    "description": "Webhook integration for the experiments monorepo",
    "is_active": true,
    "created_at": "2026-01-10T14:22:00Z",
    "updated_at": "2026-01-10T14:22:00Z",
    "created_by": "usr-uuid-here"
  }
]
```

---

### Get Integration

```
GET /api/v1/integrations/{id}
```

Returns the full configuration for a single integration, including credentials (secrets are masked).

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `id` | `string` (UUID) | Integration ID |

**Response: 200 OK**

```json
{
  "id": "int-uuid-here",
  "name": "My Jira Integration",
  "integration_type": "JIRA",
  "description": "Links experiments to Jira tickets",
  "is_active": true,
  "config": {
    "base_url": "https://your-org.atlassian.net",
    "username": "automation@your-org.com",
    "api_token": "***REDACTED***"
  },
  "created_at": "2026-01-15T09:00:00Z",
  "updated_at": "2026-01-15T09:00:00Z",
  "created_by": "usr-uuid-here"
}
```

---

### Update Integration

```
PUT /api/v1/integrations/{id}
```

Updates the configuration of an existing integration. Partial updates are supported — only supply fields you want to change.

**Authentication**: DEVELOPER role required (or owner).

**Request Body** (all fields optional)

```json
{
  "name": "Updated Jira Integration",
  "description": "Now points to the NEWPROJ project",
  "config": {
    "base_url": "https://your-org.atlassian.net",
    "username": "new-automation@your-org.com",
    "api_token": "ATATT3x-new-token..."
  }
}
```

**Response: 200 OK** — returns the updated integration object.

---

### Delete (Deactivate) Integration

```
DELETE /api/v1/integrations/{id}
```

Marks the integration as inactive. Existing webhook subscriptions are revoked. The record is retained for audit purposes.

**Authentication**: DEVELOPER role required (or owner).

**Response: 204 No Content**

---

## Webhook Endpoints

Webhook endpoints receive push events from external services. Each webhook validates the incoming payload before processing.

### Jira Webhook

```
POST /api/v1/integrations/{id}/webhook/jira
```

Receives Jira issue events (created, updated, transitioned). The platform maps Jira issue transitions to experiment lifecycle actions.

**Headers required by Jira**: `Content-Type: application/json`

**Example Payload** (Jira issue transitioned to "Done"):

```json
{
  "webhookEvent": "jira:issue_updated",
  "issue": {
    "id": "10042",
    "key": "EXP-123",
    "fields": {
      "summary": "Checkout Button Color Experiment",
      "status": { "name": "Done" }
    }
  },
  "changelog": {
    "items": [
      { "field": "status", "fromString": "In Progress", "toString": "Done" }
    ]
  }
}
```

**Response: 200 OK**

```json
{ "processed": true }
```

---

### Salesforce Webhook

```
POST /api/v1/integrations/{id}/webhook/salesforce
```

Receives Salesforce outbound messages (Campaign updated, Opportunity stage changed). The platform can push experiment results back to associated Salesforce objects.

**Headers required**: `Content-Type: application/json`

**Example Payload**:

```json
{
  "event_type": "campaign_updated",
  "campaign_id": "701xx000000001AAAQ",
  "campaign_name": "Q1 Checkout Optimization",
  "status": "Completed",
  "experiment_key": "checkout-button-color"
}
```

**Response: 200 OK**

```json
{ "processed": true }
```

---

### GitHub Webhook

```
POST /api/v1/integrations/{id}/webhook/github
```

Receives GitHub events (push, pull_request, issues). Validates the `X-Hub-Signature-256` header using HMAC-SHA256 before processing.

**Headers required by GitHub**:

| Header | Description |
|---|---|
| `X-GitHub-Event` | Event type (e.g., `push`, `pull_request`) |
| `X-Hub-Signature-256` | HMAC-SHA256 signature of the raw request body, prefixed with `sha256=` |
| `X-GitHub-Delivery` | Unique delivery GUID |
| `Content-Type` | `application/json` |

**Signature Validation**

The platform validates the incoming signature using the `webhook_secret` stored in the integration's config:

```
expected = "sha256=" + HMAC-SHA256(webhook_secret, raw_body)
```

Requests with a missing or invalid `X-Hub-Signature-256` receive `401 Unauthorized`.

**Example Payload** (pull request opened):

```json
{
  "action": "opened",
  "number": 42,
  "pull_request": {
    "title": "feat: Add new checkout flow experiment",
    "html_url": "https://github.com/your-org/your-repo/pull/42",
    "head": { "ref": "feat/checkout-experiment" },
    "base": { "ref": "main" }
  },
  "repository": {
    "full_name": "your-org/your-repo"
  }
}
```

**Response: 200 OK**

```json
{ "processed": true }
```

---

## Per-Service Config Schemas

### Jira Config

Authentication method: **HTTP Basic Auth** — `username:api_token` encoded as Base64.

| Field | Type | Required | Description |
|---|---|---|---|
| `base_url` | `string` | Yes | Jira instance base URL (e.g., `https://your-org.atlassian.net`) |
| `username` | `string` | Yes | Atlassian account email used for API access |
| `api_token` | `string` | Yes | Jira API token (generated at `id.atlassian.com/manage-profile/security/api-tokens`) |

```json
{
  "base_url": "https://your-org.atlassian.net",
  "username": "automation@your-org.com",
  "api_token": "ATATT3xFfGF0..."
}
```

---

### Salesforce Config

Authentication method: **OAuth 2.0 Client Credentials** — exchanges `client_id` + `client_secret` for an access token at the Salesforce token endpoint.

| Field | Type | Required | Description |
|---|---|---|---|
| `instance_url` | `string` | Yes | Salesforce instance URL (e.g., `https://your-org.my.salesforce.com`) |
| `client_id` | `string` | Yes | Connected App consumer key |
| `client_secret` | `string` | Yes | Connected App consumer secret |
| `access_token` | `string` | No | Cached OAuth2 access token (managed automatically; supply to pre-seed) |

```json
{
  "instance_url": "https://your-org.my.salesforce.com",
  "client_id": "3MVG9...",
  "client_secret": "1234567890ABCDEF..."
}
```

---

### GitHub Config

Authentication method: **Bearer Token** — uses a GitHub Personal Access Token (PAT) or GitHub App installation token in the `Authorization: Bearer <token>` header.

| Field | Type | Required | Description |
|---|---|---|---|
| `token` | `string` | Yes | GitHub PAT or GitHub App installation token with appropriate repo scopes |
| `webhook_secret` | `string` | Yes | Secret used to verify incoming `X-Hub-Signature-256` webhook signatures |

```json
{
  "token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "webhook_secret": "a-random-strong-secret"
}
```

---

## Error Responses

| Status | Meaning |
|---|---|
| `400 Bad Request` | Invalid request body or missing required config fields |
| `401 Unauthorized` | Missing or invalid Bearer token; also returned for GitHub webhooks with invalid signature |
| `403 Forbidden` | Authenticated user lacks required role |
| `404 Not Found` | Integration ID does not exist |
| `409 Conflict` | An active integration with the same name and type already exists |
| `422 Unprocessable Entity` | Validation error on config schema |
| `500 Internal Server Error` | Unexpected server error |

```json
{
  "detail": "Integration with name 'My Jira Integration' and type 'JIRA' already exists"
}
```
