# Third-Party Integrations API

!!! info "Part of the `integrations` module"
    Third-party integrations is one of the optional modules -- present in the **full profile**, absent from the core one. A core deployment does not serve these routes. See [Modules and profiles](../getting-started/modules.md) for what each profile includes and how to run the full one.

This document describes the third-party integrations endpoints. The platform supports bidirectional sync with Jira, Salesforce, and GitHub, enabling experiment lifecycle events to flow into your existing tooling.

---

## Overview

Each integration is represented as a persisted configuration record containing the service type, credentials, and connection metadata. Incoming events from external services are handled via per-integration webhook endpoints.

**Base path**: `/api/v1/integrations` (an optional module — a core deployment does not serve these routes)

**One configuration per service.** An integration is identified by its *type*, not by an id: there is a unique constraint on `integration_type`, so the platform holds at most one Jira, one Salesforce and one GitHub configuration. Every path below addresses it by type.

**Authentication**: the CRUD endpoints require a Bearer token — **ADMIN or DEVELOPER** to read, **ADMIN** to create, update or delete. The three webhook endpoints take no platform credential at all; they authenticate the *sender* against the integration's own `webhook_secret` (see [Webhook Endpoints](#webhook-endpoints)).

---

## `IntegrationType` Enum

The value is lower case, in the body and in the path alike.

| Value | Description |
|---|---|
| `jira` | Atlassian Jira — link experiments to issues and sync status |
| `salesforce` | Salesforce CRM — push experiment results to campaign objects |
| `github` | GitHub — create issues/PRs and receive webhook events on repo activity |

---

## CRUD Endpoints

### Create Integration

```
POST /api/v1/integrations
```

Creates the configuration for one service. The `encrypted_config` object's structure varies by `integration_type` (see [Per-Service Config Schemas](#per-service-config-schemas) below).

**Authentication**: ADMIN.

**Request Body**

| Field | Type | Required | Description |
|---|---|---|---|
| `integration_type` | `string` | Yes | `jira`, `salesforce` or `github` |
| `is_active` | `boolean` | No | Default `false`. Only an **active** configuration answers webhooks |
| `encrypted_config` | `object` | No | The per-service credentials below |

```json
{
  "integration_type": "jira",
  "is_active": true,
  "encrypted_config": {
    "base_url": "https://your-org.atlassian.net",
    "email": "automation@your-org.com",
    "api_token": "ATATT3x...",
    "project_key": "EXP",
    "webhook_secret": "a-random-strong-secret"
  }
}
```

**Response: 201 Created**

```json
{
  "id": "3f1a9c62-6f5e-4a3b-9a0c-6d2b8e7f1a45",
  "integration_type": "jira",
  "is_active": true,
  "encrypted_config": { "base_url": "https://your-org.atlassian.net", "...": "..." },
  "last_sync_at": null,
  "last_error": null,
  "created_at": "2026-01-15T09:00:00Z",
  "updated_at": "2026-01-15T09:00:00Z"
}
```

A second configuration of the same type is `409 Conflict`.

---

### List Integrations

```
GET /api/v1/integrations
```

Returns every configured integration — at most three records. There are no query parameters and no pagination.

**Authentication**: ADMIN or DEVELOPER.

**Example Request**

```bash
curl -X GET "https://your-platform.example.com/api/v1/integrations" \
  -H "Authorization: Bearer your_access_token"
```

**Response: 200 OK** — an array of the object shown above.

---

### Get Integration

```
GET /api/v1/integrations/{integration_type}
```

Returns the configuration for one service.

**Authentication**: ADMIN or DEVELOPER.

**Path Parameters**

| Parameter | Type | Description |
|---|---|---|
| `integration_type` | `string` | `jira`, `salesforce` or `github` |

**Response: 200 OK** — the object shown above. `404 Not Found` when that service has no configuration.

---

### Update Integration

```
PUT /api/v1/integrations/{integration_type}
```

Updates the configuration. Every field is optional; omitted fields are left alone. `encrypted_config` is **replaced whole**, not merged — send the complete credentials object.

**Authentication**: ADMIN.

**Request Body** (all fields optional)

| Field | Type | Description |
|---|---|---|
| `is_active` | `boolean` | Activate or deactivate the integration |
| `encrypted_config` | `object` | The complete per-service credentials |
| `last_error` | `string` or `null` | Clear or set the last recorded error |

```json
{
  "is_active": true,
  "encrypted_config": {
    "base_url": "https://your-org.atlassian.net",
    "email": "new-automation@your-org.com",
    "api_token": "ATATT3x-new-token...",
    "project_key": "NEWPROJ",
    "webhook_secret": "a-random-strong-secret"
  }
}
```

**Response: 200 OK** — the updated object. `404 Not Found` when that service has no configuration.

---

### Delete Integration

```
DELETE /api/v1/integrations/{integration_type}
```

Deletes the record. This is a hard delete — nothing is retained; to stop an integration without losing its credentials, `PUT` it with `{"is_active": false}` instead.

**Authentication**: ADMIN.

**Response: 204 No Content**. `404 Not Found` when that service has no configuration.

---

## Webhook Endpoints

```
POST /api/v1/integrations/webhooks/jira
POST /api/v1/integrations/webhooks/salesforce
POST /api/v1/integrations/webhooks/github
```

These three are the only routes in the platform an anonymous caller can reach with a body of its own choosing, so every one of them **authenticates the sender against the integration's `webhook_secret` before the payload is read**. There is no path parameter: the handler uses the single *active* configuration of that type.

**Authenticating a delivery.** A sender presents the secret one of two ways:

| Method | Header | Value |
|---|---|---|
| Signature (preferred) | `X-Hub-Signature-256`, or `X-Hub-Signature` for Jira Cloud | `sha256=` + HMAC-SHA256 of the **raw** request body, hex |
| Shared secret | `X-Experimently-Webhook-Secret` | The `webhook_secret` itself |

```
expected = "sha256=" + HMAC-SHA256(webhook_secret, raw_body)
```

- **GitHub** signs every delivery, so only `X-Hub-Signature-256` is accepted. The legacy SHA-1 `X-Hub-Signature` GitHub also sends is ignored.
- **Jira** and **Salesforce** accept either. A Salesforce outbound message cannot compute an HMAC over the body it sends, and neither can a Jira Server webhook; a custom header is what they *can* set. The shared secret is replayable and puts the secret on the wire, so use it only over TLS, and prefer the signature where the sender can produce one.

Both comparisons are constant-time. An integration with **no `webhook_secret` configured cannot authenticate anybody** and every delivery to it is refused — an anonymous write path fails closed.

Only the secret is consulted. The *outbound* API credentials (`instance_url`/`client_id`/`client_secret` for Salesforce, `token`/`repo_owner`/`repo_name` for GitHub) are not read here and are not needed: a receive-only integration — one configured with nothing but a `webhook_secret` — authenticates its deliveries normally. It is answered `200` and the event is logged rather than parsed, because parsing is the service's and the service cannot be built without those credentials.

**Response: 401 Unauthorized** — with the same body whatever went wrong: a wrong secret, a missing header, no `webhook_secret` configured, no active integration of that type, or no such integration at all. The reply must not tell an anonymous caller which integrations this deployment has.

```json
{ "detail": "Webhook authentication failed" }
```

**Response: 200 OK** — for every authenticated delivery:

```json
{ "status": "received" }
```

That 200 is deliberate even when processing fails: a provider must not retry forever over something it cannot fix, so an error *inside* the platform is logged and still answered 200. Only a body that is not a JSON object is `400 Bad Request`, and that is checked after the sender is known.

### Upgrading an integration created before webhook authentication

Webhook authentication is **new**. Jira and Salesforce deliveries used to be accepted unauthenticated, and GitHub's signature was checked only when the sender sent one, so an integration configured before this release has no `webhook_secret` and **every delivery to it now answers 401**. The 401 says nothing (by design), so the platform log names the integration instead, once per process:

```
The active jira integration has no webhook_secret in its encrypted_config, so every
inbound delivery to /api/v1/integrations/webhooks/jira is refused with 401. Add one …
```

The remedy is one `PUT`, which replaces `encrypted_config` whole — so read the current value back, add the key, and send it. Set `TOKEN` to an ADMIN bearer token, and `TYPE` to the integration: `jira` below, or `salesforce` or `github`. The last line prints the secret to configure at the provider.

```bash
TOKEN=…
TYPE=jira
SECRET=$(openssl rand -hex 32)

curl -sf -H "Authorization: Bearer $TOKEN" \
     "http://localhost:8000/api/v1/integrations/$TYPE" \
  | jq --arg s "$SECRET" '{encrypted_config: (.encrypted_config + {webhook_secret: $s})}' \
  | curl -sf -X PUT -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
         --data @- "http://localhost:8000/api/v1/integrations/$TYPE"

echo "$SECRET"
```

Then set the same value at the provider: GitHub's webhook *Secret* field, Jira's webhook secret (Jira Cloud) or the `X-Experimently-Webhook-Secret` header on the relay in front of it, and the same header on the Salesforce outbound message or callout.

---

### Jira Webhook

Receives Jira issue events (created, updated, transitioned). The platform maps Jira issue transitions to experiment lifecycle actions.

**Headers**: `Content-Type: application/json`, plus `X-Hub-Signature` (Jira Cloud) or `X-Experimently-Webhook-Secret` (Jira Server).

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

---

### Salesforce Webhook

Receives Salesforce outbound messages (Campaign updated, Opportunity stage changed). The platform can push experiment results back to associated Salesforce objects.

**Headers**: `Content-Type: application/json`, plus `X-Experimently-Webhook-Secret` (an outbound message cannot sign its body) or `X-Hub-Signature-256` from a callout that can.

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

---

### GitHub Webhook

Receives GitHub events (push, pull_request, issues).

**Headers required by GitHub**:

| Header | Description |
|---|---|
| `X-GitHub-Event` | Event type (e.g., `push`, `pull_request`) |
| `X-Hub-Signature-256` | HMAC-SHA256 signature of the raw request body, prefixed with `sha256=` — **required** |
| `X-GitHub-Delivery` | Unique delivery GUID |
| `Content-Type` | `application/json` |

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

---

## Per-Service Config Schemas

These are the keys of `encrypted_config`. `webhook_secret` is required by all three: without it the service's webhook endpoint refuses every delivery.

### Jira Config

Authentication method: **HTTP Basic Auth** — `email:api_token`.

| Field | Type | Required | Description |
|---|---|---|---|
| `base_url` | `string` | Yes | Jira instance base URL (e.g., `https://your-org.atlassian.net`) |
| `email` | `string` | Yes | Atlassian account email used for API access |
| `api_token` | `string` | Yes | Jira API token (generated at `id.atlassian.com/manage-profile/security/api-tokens`) |
| `project_key` | `string` | No | Default project for issues the platform creates (e.g. `EXP`) |
| `webhook_secret` | `string` | Yes | Authenticates inbound deliveries to `/webhooks/jira` |

```json
{
  "base_url": "https://your-org.atlassian.net",
  "email": "automation@your-org.com",
  "api_token": "ATATT3xFfGF0...",
  "project_key": "EXP",
  "webhook_secret": "a-random-strong-secret"
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
| `webhook_secret` | `string` | Yes | Authenticates inbound deliveries to `/webhooks/salesforce` |

```json
{
  "instance_url": "https://your-org.my.salesforce.com",
  "client_id": "3MVG9...",
  "client_secret": "1234567890ABCDEF...",
  "webhook_secret": "a-random-strong-secret"
}
```

---

### GitHub Config

Authentication method: **Bearer Token** — uses a GitHub Personal Access Token (PAT) or GitHub App installation token in the `Authorization: Bearer <token>` header.

| Field | Type | Required | Description |
|---|---|---|---|
| `token` | `string` | Yes | GitHub PAT or GitHub App installation token with appropriate repo scopes |
| `repo_owner` | `string` | Yes | Owner (user or organisation) of the repository |
| `repo_name` | `string` | Yes | Repository name |
| `webhook_secret` | `string` | Yes | Verifies the `X-Hub-Signature-256` of inbound deliveries to `/webhooks/github` |

```json
{
  "token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  "repo_owner": "your-org",
  "repo_name": "your-repo",
  "webhook_secret": "a-random-strong-secret"
}
```

`POST`/`PUT` do not validate these keys — a configuration missing a required credential is stored and then fails at use: on the *outbound* side Salesforce and GitHub refuse to build a client at all and Jira builds one that cannot authenticate, while on the *inbound* side a missing `webhook_secret` makes the webhook endpoint answer 401. The two are independent: an integration that has only a `webhook_secret` receives, and one that has only API credentials sends.

---

## Error Responses

| Status | Meaning |
|---|---|
| `400 Bad Request` | Webhook body is not a JSON object |
| `401 Unauthorized` | CRUD: missing or invalid Bearer token. Webhooks: the sender did not present the integration's `webhook_secret`, or no active integration of that type is configured |
| `403 Forbidden` | Authenticated user lacks the required role (ADMIN, or ADMIN/DEVELOPER to read) |
| `404 Not Found` | No integration of that type is configured |
| `409 Conflict` | An integration of that type already exists |
| `422 Unprocessable Entity` | `integration_type` is not one of `jira`, `salesforce`, `github` |
| `500 Internal Server Error` | Unexpected server error |

```json
{
  "detail": "jira integration already configured"
}
```
