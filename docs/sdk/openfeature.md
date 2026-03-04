# OpenFeature Provider

## What is OpenFeature?

[OpenFeature](https://openfeature.dev) is a CNCF (Cloud Native Computing Foundation) standard
for feature flag management. It defines a vendor-neutral API so that application code only
talks to a single, stable interface — **without depending on any specific feature flag
vendor's SDK**.

This means you can:
- Switch feature flag providers without changing a line of application code.
- Use the same `client.getBooleanValue("my-flag", false)` call whether you are using
  LaunchDarkly, Split, Flagsmith, or this Experimentation Platform.
- Add OpenFeature hooks (logging, metrics, tracing) once and have them apply to all providers.

---

## TypeScript / Node.js Provider

### Installation

```bash
# The provider package (local path for now; publish to npm for production)
npm install @openfeature/server-sdk
# Copy sdk/openfeature/ into your project or add as a local package.
```

### Quick start

```typescript
import { OpenFeature } from '@openfeature/server-sdk';
import { ExperimentationProvider } from '@experimentation-platform/openfeature-provider';

// 1. Register the provider (called once at app startup).
await OpenFeature.setProviderAndWait(
  new ExperimentationProvider({
    apiKey: process.env.EP_API_KEY!,
    baseUrl: 'https://api.yourplatform.com',
    cacheTtlMs: 5 * 60_000,  // cache for 5 minutes
  })
);

// 2. Get a client (reuse it throughout your application).
const client = OpenFeature.getClient('my-service');

// 3. Evaluate flags using the standard OpenFeature API.
const enabled = await client.getBooleanValue('dark-mode', false, {
  targetingKey: userId,
});
```

### EvaluationContext mapping

The OpenFeature `EvaluationContext` maps to the Experimentation Platform user model as follows:

| OpenFeature field       | Platform concept  | Notes                                     |
|-------------------------|-------------------|-------------------------------------------|
| `targetingKey`          | `userId`          | Used for consistent hash bucketing.       |
| `attributes.*`          | User attributes   | Available for future targeting rule eval. |

```typescript
const ctx = {
  targetingKey: 'user-12345',      // → userId for MD5 hash
  attributes: {
    country: 'US',                 // optional — for targeting rules
    plan: 'pro',
    accountAge: 365,
  },
};

const variant = await client.getStringValue('hero-experiment', 'control', ctx);
```

### Supported flag types

| OpenFeature method      | Returns     | Use case                              |
|-------------------------|-------------|---------------------------------------|
| `getBooleanValue`       | `boolean`   | Simple on/off flags                   |
| `getStringValue`        | `string`    | A/B test variants, string configs     |
| `getNumberValue`        | `number`    | Numeric configs, price experiments    |
| `getObjectValue`        | `JsonValue` | Complex config objects                |

### Resolution reasons

| Reason     | Meaning                                                           |
|------------|-------------------------------------------------------------------|
| `CACHED`   | Evaluated from a warm in-memory flag cache.                       |
| `STATIC`   | Evaluated from a stale (expired) cache during refresh.            |
| `DEFAULT`  | Flag not found; the caller's default value was returned.          |
| `ERROR`    | An error occurred (see `errorCode` for details).                  |

### Constructor options

```typescript
new ExperimentationProvider({
  apiKey: string,       // Required. X-API-Key header value.
  baseUrl?: string,     // Default: 'http://localhost:8000'
  cacheTtlMs?: number,  // Default: 300_000 (5 minutes)
  timeout?: number,     // Default: 5_000 (5 seconds)
  fetch?: typeof fetch, // Custom fetch impl (useful for testing)
})
```

---

## Python Provider

### Installation

```bash
pip install openfeature-sdk requests
# Install the provider (local path; publish to PyPI for production):
pip install -e sdk/openfeature-python/
```

### Quick start

```python
from openfeature import api
from openfeature.evaluation_context import EvaluationContext
from experimentation_openfeature import ExperimentationProvider

# 1. Register the provider.
api.set_provider(ExperimentationProvider(
    api_key=os.environ["EP_API_KEY"],
    base_url="https://api.yourplatform.com",
    cache_ttl=300,   # seconds
    timeout=10,
))

# 2. Get a client.
client = api.get_client()

# 3. Evaluate flags.
ctx = EvaluationContext(targeting_key="user-12345")
enabled = client.get_boolean_value("dark-mode", False, ctx)
variant = client.get_string_value("checkout-experiment", "control", ctx)
max_items = client.get_integer_value("cart-max-items", 10, ctx)
price = client.get_float_value("price-multiplier", 1.0, ctx)
config = client.get_object_value("feature-config", {}, ctx)
```

### EvaluationContext mapping

Same as the TypeScript provider: `targeting_key` is the `userId` passed to the MD5 hash.

### Constructor options

```python
ExperimentationProvider(
    api_key: str,       # Required. X-API-Key header value.
    base_url: str = "http://localhost:8000",
    cache_ttl: int = 300,   # seconds
    timeout: int = 10,
)
```

---

## Backend API endpoints

The providers use two platform API endpoints:

### `GET /api/v1/openfeature/flags`

Returns all feature flag definitions accessible to the API key. Providers call this
on initialization to warm their local cache. Subsequent evaluations are performed
locally without a network round-trip.

**Request:**
```http
GET /api/v1/openfeature/flags
X-API-Key: your-api-key
```

**Response:**
```json
{
  "flags": [
    {
      "key": "dark-mode",
      "enabled": true,
      "rollout_percentage": 75.0,
      "variants": [],
      "rules": []
    },
    {
      "key": "checkout-experiment",
      "enabled": true,
      "rollout_percentage": 100.0,
      "variants": [
        {"key": "control",   "weight": 0.5, "value": "original"},
        {"key": "treatment", "weight": 0.5, "value": "new-checkout"}
      ],
      "rules": []
    }
  ]
}
```

### `POST /api/v1/openfeature/evaluate`

Evaluates a single flag server-side. Use when local evaluation is not possible.

**Request:**
```json
{"flagKey": "dark-mode", "userId": "user-12345", "attributes": {}}
```

**Response:**
```json
{"value": true, "variant": null, "reason": "in_rollout", "flagKey": "dark-mode"}
```

### `POST /api/v1/openfeature/bulk-evaluate`

Evaluates multiple flags in one request.

**Request:**
```json
[
  {"flagKey": "dark-mode",            "userId": "u1"},
  {"flagKey": "checkout-experiment",  "userId": "u1"}
]
```

---

## Hash algorithm (cross-SDK consistency)

All providers use the same consistent hash for deterministic user bucketing:

```
input  = "{userId}:{flagKey}"  (UTF-8)
digest = MD5(input)
uint32 = first 4 bytes of digest, little-endian unsigned 32-bit int
hash   = uint32 / 2^32         ∈ [0.0, 1.0)
```

**Test vector** (all SDKs must produce this value):

```
hash_user("user-123", "my-flag") ≈ 0.69274
  MD5("user-123:my-flag") = 43bc57b1e81dec71c5242122ac05170f
  First 4 bytes LE → uint32 = 2975317059
  2975317059 / 4294967296 ≈ 0.69274...
```

---

## Migration guide

### Switching from LaunchDarkly to this platform

**Before (LaunchDarkly SDK):**
```typescript
import * as ld from 'launchdarkly-node-server-sdk';
const client = ld.init('sdk-key');
await client.waitForInitialization();
const value = await client.variation('my-flag', user, false);
```

**After (OpenFeature + Experimentation Platform provider):**
```typescript
import { OpenFeature } from '@openfeature/server-sdk';
import { ExperimentationProvider } from '@experimentation-platform/openfeature-provider';
await OpenFeature.setProviderAndWait(new ExperimentationProvider({ apiKey: 'api-key' }));
const client = OpenFeature.getClient();
const value = await client.getBooleanValue('my-flag', false, { targetingKey: userId });
```

The application logic does not change — only the provider initialization at startup.

### Switching from Split.io

**Before:**
```python
from splitio import get_factory
factory = get_factory('api-key')
factory.block_until_ready()
client = factory.client()
treatment = client.get_treatment('user-123', 'my_feature')
```

**After:**
```python
from openfeature import api
from experimentation_openfeature import ExperimentationProvider
api.set_provider(ExperimentationProvider(api_key='api-key'))
client = api.get_client()
treatment = client.get_string_value('my_feature', 'off', EvaluationContext('user-123'))
```

---

## Advanced: OpenFeature hooks

OpenFeature hooks let you add cross-cutting concerns (logging, metrics, tracing) that apply
to every flag evaluation, regardless of the provider:

```typescript
import { OpenFeature, Hook, HookContext } from '@openfeature/server-sdk';

const loggingHook: Hook = {
  before(hookContext: HookContext) {
    console.log(`Evaluating flag: ${hookContext.flagKey}`);
  },
  after(hookContext: HookContext, details) {
    console.log(`Flag ${hookContext.flagKey} = ${details.value} (reason: ${details.reason})`);
  },
  error(hookContext: HookContext, error) {
    console.error(`Flag evaluation error for ${hookContext.flagKey}:`, error);
  },
};

OpenFeature.addHooks(loggingHook);
```
