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

Creating, changing and deleting an integration needs an **ADMIN** bearer token; an ADMIN or a DEVELOPER can read it. `is_active` defaults to `false`, and only an active integration answers webhook deliveries, so send `true`.

```bash
curl -X POST http://localhost:8000/api/v1/integrations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "integration_type": "github",
    "is_active": true,
    "encrypted_config": {
      "token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "repo_owner": "your-org",
      "repo_name": "your-repo",
      "webhook_secret": "a-strong-random-secret-at-least-32-chars"
    }
  }'
```

**Response: 201 Created**

```json
{
  "id": "3f1a9c62-6f5e-4a3b-9a0c-6d2b8e7f1a45",
  "integration_type": "github",
  "is_active": true,
  "encrypted_config": {
    "repo_owner": "your-org",
    "repo_name": "your-repo"
  },
  "stored_secrets": ["token", "webhook_secret"],
  "last_sync_at": null,
  "last_error": null,
  "created_at": "2026-03-02T10:00:00Z",
  "updated_at": "2026-03-02T10:00:00Z"
}
```

There is one GitHub configuration, and it is addressed by its type, `github`, not by the `id`: `GET`, `PUT` and `DELETE` use `/api/v1/integrations/github`, and the webhook URL below has no id in it either. The request and response are described in [Create Integration](../api/integrations.md#create-integration).

---

## Configuration Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `token` | string | Yes | GitHub PAT or GitHub App installation token. Passed as `Authorization: Bearer <token>` on outbound API calls to GitHub. |
| `repo_owner` | string | Yes | Owner (user or organisation) of the repository |
| `repo_name` | string | Yes | Repository name |
| `webhook_secret` | string | Yes | A secret string used to verify incoming webhook payloads. Must match what you set in GitHub's webhook configuration. |

Neither the `token` nor the `webhook_secret` is returned in any response: a response shows `repo_owner` and `repo_name` and lists the names of the other keys in `stored_secrets` (see [What a response shows](../api/integrations.md#what-a-response-shows)). Both are stored in the database as given; they are not encrypted.

---

## Configuring the Webhook in GitHub

1. In your GitHub repository, go to **Settings → Webhooks → Add webhook**
2. Set the **Payload URL** to:
   ```
   https://your-platform.example.com/api/v1/integrations/webhooks/github
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
POST /api/v1/integrations/webhooks/github
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

Every refused delivery gets the same answer, whatever the reason: `401` with the body `{"detail": "Webhook authentication failed"}`. A wrong or missing signature, an integration that is not active, an integration with no `webhook_secret`, and no GitHub integration at all are not told apart.

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
{"status": "received"}
```

A delivery from an authenticated sender is answered `200` even when the platform could not process the event: the failure is logged, so the provider does not retry something it cannot fix. A body that is not a JSON object is `400 Bad Request`, and that is checked only after the sender is authenticated.

---

## Linking an Experiment to a Pull Request

To link a pull request to a platform experiment, include the experiment key in the pull request body using the convention:

```
experiment_key: checkout-flow-v2
```

The platform parses this field from incoming `pull_request` webhook events and creates an association between the PR and the experiment. This association appears in the experiment's activity feed and allows the dashboard to show which PRs are part of a given experiment.

---

## Troubleshooting

### 401 Unauthorized

**Symptom**: GitHub's delivery log shows status `401` and the body `{"detail": "Webhook authentication failed"}`.

Every refused delivery is answered the same way, so the status does not say which of these it is:

1. **Secret mismatch**: The `webhook_secret` in the platform does not match the secret in GitHub's webhook settings. Set it again with the recipe in [Rotating the Webhook Secret](#rotating-the-webhook-secret) and use the same value in GitHub. As a last resort you can `DELETE /api/v1/integrations/github` and create the integration again, but that removes the stored `token` and repository settings too, so you send them again.
2. **No secret in GitHub**: GitHub sends no `X-Hub-Signature-256` header when the webhook's **Secret** field is empty. Open the webhook's settings in GitHub and fill it in.
3. **Not active, or no `webhook_secret` stored**: `GET /api/v1/integrations/github` must show `"is_active": true` and list `webhook_secret` in `stored_secrets`. The platform log also names an active integration that has no secret, once per process.
4. **Encoding issue**: Ensure the secret does not contain leading or trailing whitespace. Copy-paste carefully.

### 400 Bad Request

**Symptom**: GitHub's delivery log shows status `400` with the body `{"detail": "Invalid JSON payload"}`.

The signature was accepted, but the body is not a JSON object. Confirm the webhook's **Content type** is `application/json`, not `application/x-www-form-urlencoded`.

### Webhook Deliveries Not Reaching the Platform

1. Confirm the webhook payload URL is reachable from the public internet
2. Check GitHub's webhook delivery logs: **Repository → Settings → Webhooks → [Your Webhook] → Recent Deliveries**
3. Verify the integration is active: `GET /api/v1/integrations/github` (an ADMIN or a DEVELOPER can call it) and check that `is_active` is `true`
4. Check the platform's application logs for any processing errors

### Rotating the Webhook Secret

If you need to rotate the webhook secret:

Step 1: Change the secret in the platform. Use the recipe in [Upgrading an integration created before webhook authentication](../api/integrations.md#upgrading-an-integration-created-before-webhook-authentication) with `TYPE=github` and an ADMIN token. It sends one `PUT /api/v1/integrations/github` that carries only the new `webhook_secret`; the stored `token` and repository settings are kept, and it prints the new secret.

Step 2: Update the secret in GitHub webhook settings immediately (There will be a brief window during rotation where deliveries may fail)
