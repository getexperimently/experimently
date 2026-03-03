# Creating Feature Flags

This guide walks through creating, configuring, and activating feature flags via both the dashboard and the REST API.

---

## Prerequisites

You need one of the following to create a feature flag:

- A **user account** with DEVELOPER or ADMIN role (for dashboard and API access via JWT token)
- An **API key** with `write` scope (for server-to-server API access)

To obtain access, contact your platform administrator or use the Admin UI under Settings → Users.

---

## Creating a Flag via the Dashboard

### Step 1: Navigate to Feature Flags

Open the dashboard at `http://localhost:3000` (or your production URL), click **Feature Flags** in the left navigation, then click **New Flag**.

### Step 2: Fill in the Basic Details

| Field | Description | Example |
|-------|-------------|---------|
| **Key** | Unique identifier used in code. Cannot be changed after creation. | `new-checkout-flow` |
| **Name** | Human-readable label shown in the dashboard. | `New Checkout Flow` |
| **Description** | What this flag controls and when it should be removed. | `Redesigned single-page checkout experience` |

### Step 3: Set the Default Value

Choose whether the flag is boolean (on/off) or multivariate (multiple string variants).

For a standard on/off flag, leave the type as **Boolean**. The default value determines what users who are not in the rollout percentage see:
- **Default: OFF** — the feature is disabled for all users not explicitly rolled out
- **Default: ON** — the feature is enabled by default; the rollout percentage restricts it

Most flags should default to OFF.

### Step 4: Configure Targeting Rules (Optional)

Targeting rules restrict which users are eligible for the flag. Users who do not match the rules always see the default value regardless of rollout percentage.

Click **Add Rule** and configure conditions:

```
country IN [US, CA]          — Only show to North American users
plan EQUALS enterprise       — Only enterprise plan users
account_age_days > 30        — Only users with accounts older than 30 days
```

Rules can be combined with AND/OR logic. Leave empty to target all users.

### Step 5: Set the Rollout Percentage

Set how many eligible users see the feature:

| Percentage | Effect |
|------------|--------|
| `0%` | Flag is disabled for everyone — safe to save and activate without any users seeing it |
| `5%` | 5% of eligible users see the feature |
| `100%` | All eligible users see the feature |

Start at `0%` and increase gradually once you are confident the flag is working correctly.

### Step 6: Save and Activate

Click **Save as Draft** to save without making it live, or click **Activate** to immediately start serving the flag.

A flag in **DRAFT** status is saved but not evaluated. A flag in **ACTIVE** status is evaluated for every eligible user request. You can move a flag from DRAFT to ACTIVE at any time.

---

## Creating a Flag via API

### Obtain a Token

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"your-username","password":"your-password"}' \
  | jq -r '.access_token')
```

Or use an API key:

```bash
# Pass in header instead of Bearer token
curl -H "X-API-Key: your-api-key" ...
```

### Create the Flag

```bash
curl -X POST http://localhost:8000/api/v1/feature-flags \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "key": "new-checkout-flow",
    "name": "New Checkout Flow",
    "description": "Redesigned single-page checkout experience",
    "rollout_percentage": 0,
    "status": "DRAFT"
  }'
```

**Response: 201 Created**

```json
{
  "id": "flag-uuid-here",
  "key": "new-checkout-flow",
  "name": "New Checkout Flow",
  "description": "Redesigned single-page checkout experience",
  "status": "DRAFT",
  "rollout_percentage": 0,
  "targeting_rules": [],
  "created_at": "2026-03-02T10:00:00Z",
  "updated_at": "2026-03-02T10:00:00Z"
}'
```

### Add Targeting Rules

```bash
curl -X PUT http://localhost:8000/api/v1/feature-flags/flag-uuid-here \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "targeting_rules": [
      {
        "attribute": "plan",
        "operator": "equals",
        "value": "enterprise"
      },
      {
        "attribute": "country",
        "operator": "in",
        "value": ["US", "CA", "GB"]
      }
    ]
  }'
```

### Activate the Flag at 10%

```bash
curl -X PUT http://localhost:8000/api/v1/feature-flags/flag-uuid-here \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "rollout_percentage": 10,
    "status": "ACTIVE"
  }'
```

---

## Flag Key Naming Conventions

Flag keys must be URL-safe strings. Follow these conventions to keep your flag inventory readable:

- Use lowercase letters, numbers, and hyphens only: `new-checkout-flow`, `dark-mode-v2`
- Use a noun or noun phrase describing what the flag controls: `redesigned-header`, `ai-recommendations`
- Include a version suffix if you anticipate multiple iterations: `checkout-flow-v2`
- Do not include environment names in the key — environments are handled by separate API keys
- Avoid overly generic names: `experiment-1`, `flag-test` are hard to interpret months later

---

## Setting the Default Value

The default value is what users receive when:
- The flag is in DRAFT status
- The user's rollout hash falls outside the rollout percentage
- The user does not match the targeting rules
- The flag evaluation call fails (error fallback)

For most feature flags, the correct default is `false` (feature disabled). This ensures that before you deliberately roll out the feature, no users are accidentally exposed.

---

## Evaluating the Flag from Your Application

Once a flag is active, evaluate it using an SDK or the tracking API.

### JavaScript SDK

```javascript
import { ExperimentationClient } from '@experimently/js-sdk';

const client = new ExperimentationClient({
  apiUrl: 'https://your-platform.example.com',
  apiKey: 'your-api-key',
});

const isEnabled = await client.isFeatureEnabled('new-checkout-flow', 'user-123', {
  plan: 'enterprise',
  country: 'US',
});

if (isEnabled) {
  showNewCheckoutFlow();
} else {
  showCurrentCheckoutFlow();
}
```

### Python SDK

```python
from experimentation import ExperimentationClient

client = ExperimentationClient(
    api_url="https://your-platform.example.com",
    api_key="your-api-key",
)

is_enabled = client.is_feature_enabled(
    flag_key="new-checkout-flow",
    user_id="user-123",
    user_attributes={"plan": "enterprise", "country": "US"},
)
```

### REST API (Direct)

```bash
curl -X POST http://localhost:8000/api/v1/feature-flags/new-checkout-flow/evaluate \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user-123",
    "attributes": {"plan": "enterprise", "country": "US"}
  }'
```

```json
{
  "flag_key": "new-checkout-flow",
  "enabled": true,
  "rollout_percentage": 10
}
```

---

## Next Steps

- [Gradual Rollouts](rollouts.md) — set up a staged rollout schedule with automatic progression
- [Safety Monitoring](safety.md) — configure automatic rollback if error rates spike
- [SDK Documentation](../sdk/javascript.md) — full SDK integration guide
