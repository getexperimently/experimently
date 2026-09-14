# Multi-Tenant Team Workspaces — Quickstart

!!! info "Part of the `workspaces` module"
    Team workspaces is one of the optional modules -- present in the **full profile**, absent from the core one. A core deployment does not serve these routes. See [Modules and profiles](../getting-started/modules.md) for what each profile includes and how to run the full one.

This guide shows you how to create a workspace, invite your team, generate a
scoped API key, and start using the workspace-scoped API in the SDK.

---

## 1. Create a Workspace

Any authenticated platform user can create a workspace.

```http
POST /api/v1/workspaces/
Authorization: Bearer <your-token>
Content-Type: application/json

{
  "name": "Acme Mobile Team",
  "slug": "acme-mobile",
  "description": "Experiments for the iOS and Android apps",
  "plan": "free"
}
```

**Response (201 Created):**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "Acme Mobile Team",
  "slug": "acme-mobile",
  "plan": "free",
  "is_active": true,
  "max_experiments": 10,
  "max_feature_flags": 50,
  "max_members": 5,
  "max_api_keys": 3,
  "created_at": "2026-03-07T00:00:00Z",
  "updated_at": "2026-03-07T00:00:00Z"
}
```

The user who creates the workspace is automatically assigned the **OWNER** role.

---

## 2. Invite Team Members

### Option A — Invite by email

```http
POST /api/v1/workspaces/{workspace_id}/invites
Authorization: Bearer <admin-token>
Content-Type: application/json

{
  "email": "alice@example.com",
  "role": "DEVELOPER"
}
```

Send the returned `token` to Alice.  Alice can accept the invite once she is
logged into the platform:

```http
POST /api/v1/workspaces/invites/{token}/accept
Authorization: Bearer <alice-token>
```

### Option B — Add existing user directly

If you already know the user's platform ID:

```http
POST /api/v1/workspaces/{workspace_id}/members
Authorization: Bearer <admin-token>
Content-Type: application/json

{
  "user_id": "alice-uuid-here",
  "role": "DEVELOPER"
}
```

---

## 3. Generate a Scoped API Key

```http
POST /api/v1/workspaces/{workspace_id}/api-keys
Authorization: Bearer <admin-token>
Content-Type: application/json

{
  "name": "Production SDK Key",
  "scopes": ["flags:read", "experiments:read", "track:write"]
}
```

**Response (201 Created):**
```json
{
  "id": "key-uuid",
  "name": "Production SDK Key",
  "key_prefix": "ep_live_",
  "key": "ep_live_a1b2c3d4e5f6...",
  "scopes": ["flags:read", "experiments:read", "track:write"],
  "created_at": "2026-03-07T00:00:00Z"
}
```

> **Important**: Copy the `key` value now — it is shown exactly once and cannot
> be retrieved later.  If you lose it, rotate the key to generate a new one.

---

## 4. Use the Workspace-Scoped API in the SDK

### JavaScript SDK

```javascript
import { ExperimentationClient } from '@experimentation/sdk';

const client = new ExperimentationClient({
  apiKey: 'ep_live_a1b2c3d4e5f6...',
  baseUrl: 'https://your-platform.example.com'
});

// Evaluate a feature flag
const enabled = await client.isEnabled('my-feature-flag', { userId: 'user-123' });

// Get experiment assignment
const variant = await client.getVariant('checkout-experiment', { userId: 'user-123' });

// Track an event
await client.track('purchase', { userId: 'user-123', value: 49.99 });
```

### Python SDK

```python
from experimentation import ExperimentationClient

client = ExperimentationClient(
    api_key="ep_live_a1b2c3d4e5f6...",
    base_url="https://your-platform.example.com"
)

# Evaluate a feature flag
enabled = client.is_enabled("my-feature-flag", user_id="user-123")

# Get experiment assignment
variant = client.get_variant("checkout-experiment", user_id="user-123")

# Track an event
client.track("purchase", user_id="user-123", properties={"value": 49.99})
```

---

## 5. Manage API Keys

### List all API keys

```http
GET /api/v1/workspaces/{workspace_id}/api-keys
Authorization: Bearer <admin-token>
```

### Revoke a key

```http
DELETE /api/v1/workspaces/{workspace_id}/api-keys/{key_id}
Authorization: Bearer <admin-token>
```

### Rotate a key

```http
POST /api/v1/workspaces/{workspace_id}/api-keys/{key_id}/rotate
Authorization: Bearer <admin-token>
```

The old key is immediately invalidated.  The response contains the new plaintext
key (shown once only).

---

## Next Steps

- [Workspace Overview](./overview.md) — detailed role hierarchy and plan limits
- [API Reference](http://localhost:8000/docs#/Workspaces) — interactive Swagger UI
