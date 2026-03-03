# SDK Integration Guide

The platform provides official SDKs for Python and JavaScript to integrate experiment assignment and feature flag evaluation directly into your application.

---

## Python SDK

### Installation

```bash
pip install experimentation-sdk
# or from source:
pip install -e ./sdk/python
```

### Quick Start

```python
from experimentation import ExperimentationClient

client = ExperimentationClient(
    api_url="https://your-platform.example.com",
    api_key="your-api-key",
)

# Get experiment variant assignment
variant = client.get_variant(
    experiment_key="checkout-button-color",
    user_id="user-123",
    user_attributes={"country": "US", "plan": "pro"},
)
print(variant)  # "control" or "treatment"

# Check feature flag
is_enabled = client.is_feature_enabled(
    flag_key="dark-mode",
    user_id="user-123",
)

# Track a conversion event
client.track(
    user_id="user-123",
    event_type="checkout_completed",
    event_value=49.99,
    properties={"payment_method": "card"},
)
```

### Client Configuration

```python
client = ExperimentationClient(
    api_url="https://your-platform.example.com",
    api_key="your-api-key",
    timeout_seconds=2.0,         # Default: 5.0
    cache_ttl_seconds=60,        # Local assignment cache TTL. Default: 300
    default_variant="control",   # Fallback when API is unreachable
)
```

### Experiments

```python
# Get variant assignment (returns default_variant on error)
variant = client.get_variant("experiment-key", user_id="user-123")

# Get assignment with full metadata
assignment = client.get_assignment(
    experiment_key="experiment-key",
    user_id="user-123",
    user_attributes={"plan": "enterprise"},
)
print(assignment.variant_key)      # "treatment-a"
print(assignment.experiment_id)    # UUID
print(assignment.is_control)       # False
```

### Feature Flags

```python
# Boolean flag check
enabled = client.is_feature_enabled("flag-key", user_id="user-123")

# Get flag with targeting evaluation
flag = client.get_feature_flag(
    flag_key="new-checkout",
    user_id="user-123",
    user_attributes={"country": "US"},
)
print(flag.enabled)         # True / False
print(flag.rollout_pct)     # 0.5 (50% rollout)
```

### Event Tracking

```python
# Simple event
client.track("user-123", "page_view")

# Event with value and properties
client.track(
    user_id="user-123",
    event_type="purchase_completed",
    event_value=149.00,
    properties={
        "product_id": "prod-456",
        "currency": "USD",
    },
)

# Batch track (more efficient for high-volume scenarios)
client.track_batch([
    {"user_id": "user-1", "event_type": "click", "event_value": None},
    {"user_id": "user-2", "event_type": "click", "event_value": None},
])
```

---

## JavaScript / TypeScript SDK

### Installation

```bash
npm install @experimentation/sdk
# or from source:
npm install ./sdk/js
```

### Quick Start

```typescript
import { ExperimentationClient } from '@experimentation/sdk';

const client = new ExperimentationClient({
  apiUrl: 'https://your-platform.example.com',
  apiKey: 'your-api-key',
});

// Get variant assignment
const variant = await client.getVariant('checkout-button-color', {
  userId: 'user-123',
  attributes: { country: 'US', plan: 'pro' },
});
console.log(variant); // "control" or "treatment"

// Feature flag check
const isEnabled = await client.isFeatureEnabled('dark-mode', { userId: 'user-123' });

// Track event
await client.track('user-123', 'checkout_completed', { value: 49.99 });
```

### React Integration

```tsx
import { useExperiment, useFeatureFlag } from '@experimentation/sdk/react';

function CheckoutButton() {
  const { variant, loading } = useExperiment('checkout-cta', {
    userId: currentUser.id,
    attributes: { plan: currentUser.plan },
  });

  if (loading) return <DefaultButton />;

  return variant === 'treatment' ? <GreenButton /> : <DefaultButton />;
}

function SettingsPanel() {
  const darkMode = useFeatureFlag('dark-mode', { userId: currentUser.id });

  return <Panel theme={darkMode ? 'dark' : 'light'} />;
}
```

### Client Configuration

```typescript
const client = new ExperimentationClient({
  apiUrl: 'https://your-platform.example.com',
  apiKey: 'your-api-key',
  timeoutMs: 2000,          // Default: 5000
  cacheTtlSeconds: 60,      // Default: 300
  defaultVariant: 'control', // Fallback on error
});
```

---

## API Key Authentication

The SDK uses API key authentication, separate from user JWT tokens. API keys are intended for server-side and client-side SDK use.

**Obtaining an API Key**: Contact your platform ADMIN or use the Admin UI under Settings → API Keys.

The API key is passed as `X-API-Key: your-api-key` in all SDK requests.

---

## Error Handling

Both SDKs handle API failures gracefully:

```python
# Python — falls back to default_variant, never raises on assignment
variant = client.get_variant("my-experiment", user_id="user-123")
# Returns "control" (default_variant) if API is unreachable
```

```typescript
// JavaScript — falls back to defaultVariant, never rejects on assignment
const variant = await client.getVariant('my-experiment', { userId: 'user-123' });
// Returns 'control' (defaultVariant) if API is unreachable
```

For event tracking, failures are logged but do not throw exceptions by default. Pass `throwOnError: true` to opt into strict mode.

---

## Local Development

Point the SDK at your local instance during development:

```python
client = ExperimentationClient(
    api_url="http://localhost:8000",
    api_key="dev-api-key",
)
```

```typescript
const client = new ExperimentationClient({
  apiUrl: 'http://localhost:8000',
  apiKey: 'dev-api-key',
});
```
