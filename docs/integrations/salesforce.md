# Salesforce Integration

!!! info "Part of the `integrations` module"
    Third-party integrations is one of the optional modules -- present in the **full profile**, absent from the core one. A core deployment does not serve these routes. See [Modules and profiles](../getting-started/modules.md) for what each profile includes and how to run the full one.

The Salesforce integration enables the platform to synchronize experiment status and results with your Salesforce CRM. Experiment lifecycle events can update Salesforce Campaign objects, and Salesforce outbound messages can trigger actions in the platform.

---

## What the Integration Does

- **Outbound (Platform → Salesforce)**: Push experiment status changes and results to Salesforce Campaign records. When an experiment completes or reaches statistical significance, the associated Salesforce campaign can be automatically updated.
- **Inbound (Salesforce → Platform)**: Receive Salesforce outbound messages via webhook. For example, when a Salesforce campaign status changes to "Completed", the platform can be notified to finalize an associated experiment.

---

## Prerequisites

Before creating the integration, you need:

1. A **Salesforce Connected App** configured in your Salesforce org with OAuth 2.0 enabled
2. The **Consumer Key** (Client ID) and **Consumer Secret** (Client Secret) from the connected app
3. Your **Salesforce instance URL** (e.g., `https://your-org.my.salesforce.com`)
4. A Salesforce user account with permission to access the objects you want to sync

### Creating a Salesforce Connected App

1. In Salesforce, go to **Setup → App Manager → New Connected App**
2. Enable **OAuth Settings**
3. Set the callback URL (not used for client credentials, but required): `https://login.salesforce.com/services/oauth2/success`
4. Add the following OAuth scopes:
   - `api` (Access and manage your data)
   - `refresh_token, offline_access` (Perform requests at any time)
5. Save and copy the **Consumer Key** and **Consumer Secret**

---

## Creating the Integration

Creating, changing and deleting an integration needs an **ADMIN** bearer token; an ADMIN or a DEVELOPER can read it. `is_active` defaults to `false`, and only an active integration answers webhook deliveries, so send `true`.

```bash
curl -X POST http://localhost:8000/api/v1/integrations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "integration_type": "salesforce",
    "is_active": true,
    "encrypted_config": {
      "instance_url": "https://your-org.my.salesforce.com",
      "client_id": "3MVG9...",
      "client_secret": "1234567890ABCDEF...",
      "webhook_secret": "a-strong-random-secret-at-least-32-chars"
    }
  }'
```

**Response: 201 Created**

```json
{
  "id": "3f1a9c62-6f5e-4a3b-9a0c-6d2b8e7f1a45",
  "integration_type": "salesforce",
  "is_active": true,
  "encrypted_config": {
    "instance_url": "https://your-org.my.salesforce.com",
    "client_id": "3MVG9..."
  },
  "stored_secrets": ["client_secret", "webhook_secret"],
  "last_sync_at": null,
  "last_error": null,
  "created_at": "2026-03-02T10:00:00Z",
  "updated_at": "2026-03-02T10:00:00Z"
}
```

There is one Salesforce configuration, and it is addressed by its type, `salesforce`, not by the `id`: `GET`, `PUT` and `DELETE` use `/api/v1/integrations/salesforce`, and the webhook URL below has no id in it either. The request and response are described in [Create Integration](../api/integrations.md#create-integration).

---

## Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `instance_url` | string | Yes | Your Salesforce instance URL, e.g., `https://your-org.my.salesforce.com` |
| `client_id` | string | Yes | OAuth 2.0 Consumer Key from the Connected App |
| `client_secret` | string | Yes | OAuth 2.0 Consumer Secret from the Connected App |
| `webhook_secret` | string | Yes | A secret you choose (for example `openssl rand -hex 32`). An inbound delivery to the webhook endpoint below must present it; see [Webhook Endpoints](../api/integrations.md#webhook-endpoints) |
| `access_token` | string | No | Pre-seeded OAuth 2.0 access token. The platform manages token refresh automatically; you do not need to supply this. |

The platform uses the **OAuth 2.0 Client Credentials** flow. The credentials are stored in the database as given; they are not encrypted. The `client_secret`, an `access_token` and the `webhook_secret` are not returned in any response, not even masked: a response shows `instance_url` and `client_id` and lists the names of the other keys in `stored_secrets` (see [What a response shows](../api/integrations.md#what-a-response-shows)).

---

## Webhook Endpoint

To receive incoming events from Salesforce, configure a Salesforce Outbound Message (or Process Builder / Flow) to POST to:

```
POST /api/v1/integrations/webhooks/salesforce
```

### Configuring Outbound Messages in Salesforce

1. In Salesforce, go to **Setup → Workflow Actions → Outbound Messages → New Outbound Message**
2. Set the **Endpoint URL** to your webhook URL:
   `https://your-platform.example.com/api/v1/integrations/webhooks/salesforce`
3. Set the **User to Send As** to a user with API access
4. Select the fields you want to include in the payload
5. Send the integration's `webhook_secret` with every delivery, as described next

### Authenticating a delivery

The platform reads a delivery only after the sender has presented the integration's `webhook_secret`, in one of two forms. Without it the answer is `401` and the body is not read.

| How | Header | Value |
|-----|--------|-------|
| Shared secret | `X-Experimently-Webhook-Secret` | The `webhook_secret` itself |
| Signature, from a callout that can compute one | `X-Hub-Signature-256` | `sha256=` followed by the hex HMAC-SHA256 of the raw request body, keyed with the `webhook_secret` |

A Salesforce outbound message cannot compute an HMAC over the body it sends, so it uses the shared-secret header. The secret then travels with every delivery, so the endpoint must be HTTPS. A callout that can sign should send the signature instead. A delivery that carries a signature is judged on the signature alone: a wrong signature is refused even when the shared-secret header is right.

Every refused delivery gets the same answer, `401` with the body `{"detail": "Webhook authentication failed"}`: a wrong or missing secret, an integration that is not active, an integration with no `webhook_secret`, and no Salesforce integration at all are not told apart. If every delivery is refused, check with `GET /api/v1/integrations/salesforce` that `is_active` is `true` and that `stored_secrets` lists `webhook_secret`. See [Webhook Endpoints](../api/integrations.md#webhook-endpoints) for the whole contract.

### Incoming Webhook Payload Format

The platform accepts JSON payloads from Salesforce outbound messages or custom REST calls. The expected format:

```json
{
  "event_type": "campaign_updated",
  "campaign_id": "701xx000000001AAAQ",
  "campaign_name": "Q1 Checkout Optimization",
  "status": "Completed",
  "experiment_key": "checkout-button-color"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | string | Type of event (e.g., `campaign_updated`, `opportunity_closed`) |
| `campaign_id` | string | Salesforce Campaign record ID |
| `campaign_name` | string | Human-readable campaign name |
| `status` | string | New status of the Salesforce record |
| `experiment_key` | string | Optional. Links the Salesforce record to a specific experiment |

**Response: 200 OK**

```json
{"status": "received"}
```

A delivery from an authenticated sender is answered `200` even when the platform could not process the event: the failure is logged, so the provider does not retry something it cannot fix. A body that is not a JSON object is `400 Bad Request`, and that is checked only after the sender is authenticated.

---

## What Data Is Synced

When the platform pushes experiment data to Salesforce:

| Platform Event | Salesforce Action |
|----------------|-------------------|
| Experiment completed | Updates associated Campaign status to `Completed` |
| Experiment reached significance | Adds a note to the Campaign with the result summary |
| Experiment rolled back | Updates Campaign status to `Paused` |

The `experiment_key` field in the Salesforce record links the Campaign to the platform experiment. This linkage is created manually or via webhook when the campaign is first associated with an experiment.

---

## Troubleshooting

### OAuth Token Errors

**Symptom**: Integration fails with `401 Unauthorized` when trying to call Salesforce.

**Causes and fixes**:
1. **Expired or invalid access token**: The platform automatically refreshes tokens using the client credentials. If this fails, verify your `client_id` and `client_secret` are correct and that the Connected App is active.
2. **IP restrictions**: Salesforce may have IP allowlisting enabled. Add the IP addresses of your ECS Fargate tasks to the Connected App's IP relaxation settings.
3. **Scope issues**: Verify the Connected App has the `api` and `refresh_token` scopes enabled.

### Test the OAuth Flow Manually

```bash
curl -X POST "https://your-org.my.salesforce.com/services/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=YOUR_CLIENT_ID&client_secret=YOUR_CLIENT_SECRET"
```

If this returns a token, the credentials are correct.

### Webhook Not Receiving Events

1. Confirm the **Endpoint URL** in the Salesforce Outbound Message matches your integration webhook URL exactly
2. Ensure your platform is accessible from the public internet (Salesforce requires a reachable HTTPS endpoint)
3. Check the platform's delivery log: `GET /api/v1/notifications/delivery-log`
4. In Salesforce, check **Setup → Monitoring → Outbound Messages** for delivery failures

### Updating Integration Credentials

If you rotate your Salesforce Connected App credentials, send the new values with `PUT /api/v1/integrations/salesforce` and an ADMIN token. The integration is addressed by its type, not by an id. `PUT` merges `encrypted_config` key by key, so send only the keys that changed: the keys you leave out, such as `instance_url` and `webhook_secret`, are kept.

```bash
curl -X PUT http://localhost:8000/api/v1/integrations/salesforce \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "encrypted_config": {
      "client_id": "3MVG9-new-key...",
      "client_secret": "new-secret..."
    }
  }'
```

The whole request is described in [Update Integration](../api/integrations.md#update-integration). To change the `webhook_secret` instead, use the recipe in [Upgrading an integration created before webhook authentication](../api/integrations.md#upgrading-an-integration-created-before-webhook-authentication) with `TYPE=salesforce`.
