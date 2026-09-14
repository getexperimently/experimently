# GitHub Integration

!!! info "Part of the `integrations` module"
    Third-party integrations is one of the optional modules -- present in the **full profile**, absent from the core one. A core deployment does not serve these routes. See [Modules and profiles](../getting-started/modules.md) for what each profile includes and how to run the full one.

The GitHub integration connects the platform to your GitHub repositories. You can receive push and pull request events to link code changes to experiments, and create GitHub issues directly from the platform.

---

## What the Integration Does

- **Inbound (GitHub → Platform)**: Receive webhook events from GitHub (`push`, `pull_request`, `issues`). The platform validates the payload using HMAC-SHA256 and processes the event.
- **Outbound (Platform → GitHub)**: Create GitHub issues to track experiment-related action items, and link pull requests to active experiments.

---

## Prerequisites

Before creating the integration, you need:

1. A **GitHub Personal Access Token (PAT)** with appropriate repository scopes, or a GitHub App installation token
2. A strong **webhook secret** that you will configure both in the platform and in the GitHub webhook settings
3. A GitHub repository where you will configure the webhook

### Creating a GitHub PAT

1. In GitHub, go to **Settings → Developer Settings → Personal access tokens → Tokens (classic)**
2. Click **Generate new token**
3. Select the following scopes:
   - `repo` — Full repository access (or `public_repo` for public repositories only)
   - `issues` — If you want to create issues from the platform
4. Generate and copy the token

---

## Creating the Integration

```bash
curl -X POST http://localhost:8000/api/v1/integrations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GitHub Experiments Repo",
    "integration_type": "GITHUB",
    "description": "Webhook integration for the experiments monorepo",
    "config": {
      "token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "webhook_secret": "a-strong-random-secret-at-least-32-chars"
    }
  }'
```

**Response: 201 Created**

```json
{
  "id": "int-uuid-here",
  "name": "GitHub Experiments Repo",
  "integration_type": "GITHUB",
  "is_active": true,
  "created_at": "2026-03-02T10:00:00Z"
}
```

Save the `id` — you need it for the webhook endpoint URL.

---

## Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `token` | string | Yes | GitHub PAT or GitHub App installation token. Passed as `Authorization: Bearer <token>` on outbound API calls to GitHub. |
| `webhook_secret` | string | Yes | A secret string used to verify incoming webhook payloads. Must match what you set in GitHub's webhook configuration. |

The `token` is stored encrypted and never returned in GET responses. The `webhook_secret` is also masked in responses.

---

## Configuring the Webhook in GitHub

1. In your GitHub repository, go to **Settings → Webhooks → Add webhook**
2. Set the **Payload URL** to:
   ```
   https://your-platform.example.com/api/v1/integrations/{integration_id}/webhook/github
   ```
3. Set **Content type** to `application/json`
4. Set the **Secret** to the same value you used as `webhook_secret` when creating the integration
5. Under **Which events would you like to trigger this webhook?**, select:
   - Individual events: `Push`, `Pull requests`, `Issues`
   - Or "Send me everything" if you want all events
6. Ensure **Active** is checked and click **Add webhook**

---

## Webhook Endpoint

```
POST /api/v1/integrations/{integration_id}/webhook/github
```

### Required Headers

GitHub sends the following headers with every webhook delivery:

| Header | Description |
|--------|-------------|
| `X-GitHub-Event` | Event type (e.g., `push`, `pull_request`, `issues`) |
| `X-Hub-Signature-256` | HMAC-SHA256 signature of the raw request body |
| `X-GitHub-Delivery` | Unique delivery GUID for idempotency |
| `Content-Type` | `application/json` |

### HMAC-SHA256 Signature Validation

The platform validates every incoming webhook using the `X-Hub-Signature-256` header. The validation algorithm:

```
expected_signature = "sha256=" + HMAC-SHA256(webhook_secret, raw_request_body)
provided_signature = X-Hub-Signature-256 header value

if not constant_time_compare(expected_signature, provided_signature):
    return 401 Unauthorized
```

Requests with a missing or invalid `X-Hub-Signature-256` header receive `401 Unauthorized` and are not processed. This prevents spoofed webhook deliveries.

---

## Supported Event Types

### Push Events

Received when code is pushed to the repository.

```json
{
  "ref": "refs/heads/main",
  "commits": [
    {
      "id": "abc123",
      "message": "feat: add new checkout flow",
      "author": {"name": "Jane Smith", "email": "jane@example.com"},
      "url": "https://github.com/your-org/your-repo/commit/abc123"
    }
  ],
  "repository": {
    "full_name": "your-org/your-repo"
  }
}
```

### Pull Request Events

Received when a pull request is opened, updated, merged, or closed.

```json
{
  "action": "opened",
  "number": 42,
  "pull_request": {
    "title": "feat: Add new checkout flow experiment",
    "html_url": "https://github.com/your-org/your-repo/pull/42",
    "head": {"ref": "feat/checkout-experiment", "sha": "abc123"},
    "base": {"ref": "main"},
    "body": "experiment_key: checkout-flow-v2"
  },
  "repository": {
    "full_name": "your-org/your-repo"
  }
}
```

### Issues Events

Received when an issue is opened, edited, closed, or labeled.

```json
{
  "action": "opened",
  "issue": {
    "number": 101,
    "title": "Track experiment: checkout-flow-v2",
    "html_url": "https://github.com/your-org/your-repo/issues/101",
    "body": "Track the progress of the checkout flow experiment.",
    "labels": [{"name": "experiment"}]
  }
}
```

**Response: 200 OK**

```json
{"processed": true}
```

---

## Linking an Experiment to a Pull Request

To link a pull request to a platform experiment, include the experiment key in the pull request body using the convention:

```
experiment_key: checkout-flow-v2
```

The platform parses this field from incoming `pull_request` webhook events and creates an association between the PR and the experiment. This association appears in the experiment's activity feed and allows the dashboard to show which PRs are part of a given experiment.

---

## Troubleshooting

### 400 Bad Request — Bad HMAC Signature

**Symptom**: GitHub webhook deliveries show status `400` with error `invalid signature`.

**Causes and fixes**:
1. **Secret mismatch**: The `webhook_secret` in the platform does not match the secret in GitHub's webhook settings. Delete and recreate the integration with a consistent secret.
2. **Encoding issue**: Ensure the secret does not contain leading or trailing whitespace. Copy-paste carefully.
3. **Content type**: Confirm GitHub is sending `application/json` (not `application/x-www-form-urlencoded`).

### 401 Unauthorized — Missing Signature

**Symptom**: Webhook deliveries fail with `401`.

**Cause**: GitHub is not sending the `X-Hub-Signature-256` header. This typically means the webhook secret was not configured in GitHub. Go to your GitHub webhook settings and ensure the secret field is populated.

### Webhook Deliveries Not Reaching the Platform

1. Confirm the webhook payload URL is reachable from the public internet
2. Check GitHub's webhook delivery logs: **Repository → Settings → Webhooks → [Your Webhook] → Recent Deliveries**
3. Verify the integration is active: `GET /api/v1/integrations/{id}`
4. Check the platform's application logs for any processing errors

### Rotating the Webhook Secret

If you need to rotate the webhook secret:

```bash
# Step 1: Update the integration in the platform
curl -X PUT http://localhost:8000/api/v1/integrations/int-uuid-here \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "config": {
      "token": "ghp_xxxx",
      "webhook_secret": "new-strong-secret-here"
    }
  }'

# Step 2: Update the secret in GitHub webhook settings immediately
# (There will be a brief window during rotation where deliveries may fail)
```
