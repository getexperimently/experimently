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

```bash
curl -X POST http://localhost:8000/api/v1/integrations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Salesforce CRM Sync",
    "integration_type": "SALESFORCE",
    "description": "Syncs experiment completion to Salesforce campaigns",
    "config": {
      "instance_url": "https://your-org.my.salesforce.com",
      "client_id": "3MVG9...",
      "client_secret": "1234567890ABCDEF..."
    }
  }'
```

**Response: 201 Created**

```json
{
  "id": "int-uuid-here",
  "name": "Salesforce CRM Sync",
  "integration_type": "SALESFORCE",
  "is_active": true,
  "created_at": "2026-03-02T10:00:00Z"
}
```

Save the `id` — you will need it for the webhook endpoint URL.

---

## Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `instance_url` | string | Yes | Your Salesforce instance URL, e.g., `https://your-org.my.salesforce.com` |
| `client_id` | string | Yes | OAuth 2.0 Consumer Key from the Connected App |
| `client_secret` | string | Yes | OAuth 2.0 Consumer Secret from the Connected App |
| `access_token` | string | No | Pre-seeded OAuth 2.0 access token. The platform manages token refresh automatically; you do not need to supply this. |

The platform uses the **OAuth 2.0 Client Credentials** flow. Credentials are stored encrypted in the database. The `client_secret` is never returned in GET responses — it is masked as `***REDACTED***`.

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
{"processed": true}
```

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

If you rotate your Salesforce Connected App credentials:

```bash
curl -X PUT http://localhost:8000/api/v1/integrations/int-uuid-here \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "instance_url": "https://your-org.my.salesforce.com",
      "client_id": "3MVG9-new-key...",
      "client_secret": "new-secret..."
    }
  }'
```
