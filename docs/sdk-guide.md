# SDK Integration Guide

SDKs integrate experiment assignment, feature-flag evaluation and event tracking into your application.
Every SDK talks to the same small public API surface, authenticated with an API key.

## Endpoint contract

All SDK traffic uses the `X-API-Key` header and addresses experiments and flags by their public **keys**.
The server decides bucketing; SDKs must not bucket locally.

| Purpose | Method and path | Body / query | Response |
|---|---|---|---|
| Assign a user to an experiment (sticky) | `POST /api/v1/tracking/assign` | `{experiment_key, user_id, context?}` | `{experiment_key, user_id, variant_id, variant_name, is_control, configuration}` |
| Evaluate a flag | `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…` | — | `{key, enabled, config}` |
| All flags for a user | `GET /api/v1/feature-flags/user/{user_id}` | — | `{flag_key: boolean, …}` |
| Track one event | `POST /api/v1/tracking/track` | `{event_type, event_name?, user_id, experiment_key? \| feature_flag_key?, value?, metadata?, timestamp?}` | stored event |
| Track up to 100 events | `POST /api/v1/tracking/batch` | `{events: [...]}` | `{success_count, failure_count, errors}` |
| A user's assignments | `GET /api/v1/tracking/assignments/{user_id}` | — | list |

Conversions are matched to experiment metrics by `event_name` (exposures excluded), whatever `event_type`
an SDK sends. Full request/response examples: [API Specs](api/specs.md#tracking-api-sdk). Per-IP rate
limit for these paths: `SDK_RATE_LIMIT_PER_MINUTE` (default 6000/min).

## SDK status (2026-09-11)

| SDK | Location | Status against the contract above |
|---|---|---|
| React | `sdk/react` | **Verified end to end** (v1.1; the ShopLab demo runs on it). See [React SDK](sdk/react.md). |
| Python, JavaScript | `sdk/python`, `sdk/js` | Placeholders only (no client code); the examples below describe the intended API, not shipped code. |
| Go, Java, iOS, Android, Flutter, React Native, Edge, .NET, Elixir, Ruby, PHP | `sdk/*` | Ship consistent-hash bucketing and pass the cross-SDK hash contract tests, but still call `/api/v1/events`, `/api/v1/assignments` or `/api/v1/experiments/{key}/assign`, which the backend does not serve. They need the same endpoint rewiring the React SDK received before they work against this API. |

Until an SDK is marked verified, integrate with the raw HTTP contract above (any HTTP client works).

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

Use the dedicated React SDK (`sdk/react`, verified end to end). Full reference: [React SDK](sdk/react.md).

```tsx
import {
  ExperimentationProvider,
  useExperiment,
  useFeatureFlag,
  useTrackEvent,
} from '@experimentation-platform/react-sdk';

function App() {
  return (
    <ExperimentationProvider
      config={{ apiKey: process.env.NEXT_PUBLIC_EXPERIMENTLY_API_KEY!, baseUrl: 'http://localhost:8000' }}
      user={{ userId: currentUser.id, attributes: { plan: currentUser.plan } }}
    >
      <CheckoutButton />
    </ExperimentationProvider>
  );
}

function CheckoutButton() {
  const { variantKey, configuration, loading } = useExperiment('checkout-cta');   // POST /tracking/assign
  const darkMode = useFeatureFlag('dark-mode');                                    // GET /feature-flags/evaluate/dark-mode
  const track = useTrackEvent();

  if (loading) return <DefaultButton />;
  return (
    <button
      style={{ background: (configuration?.color as string) ?? '#0f172a' }}
      onClick={() => track('purchase', { plan: currentUser.plan }, { value: 49 })}  // fans out to every assigned experiment
    >
      {variantKey === 'treatment' ? 'Buy now' : 'Add to cart'}
    </button>
  );
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

## Java SDK

### Installation

**Maven** (`pom.xml`):

```xml
<dependency>
    <groupId>com.experimentation</groupId>
    <artifactId>experimentation-sdk</artifactId>
    <version>1.0.0</version>
</dependency>
```

**Gradle** (`build.gradle`):

```groovy
implementation 'com.experimentation:experimentation-sdk:1.0.0'
```

### Quick Start

```java
import com.experimentation.sdk.ExperimentationClient;
import com.experimentation.sdk.ExperimentationConfig;

ExperimentationClient client = new ExperimentationClient(
    ExperimentationConfig.builder()
        .apiUrl("https://your-platform.example.com")
        .apiKey("your-api-key")
        .build()
);

// Get experiment variant assignment
String variant = client.getVariant(
    "checkout-button-color",   // experimentKey
    "user-123",                // userId
    Map.of("country", "US", "plan", "pro")  // attributes
);
System.out.println(variant); // "control" or "treatment"

// Check feature flag
boolean isEnabled = client.isFeatureEnabled(
    "dark-mode",  // flagKey
    "user-123",   // userId
    Map.of()      // attributes
);

// Track a conversion event
client.trackEvent(
    "user-123",           // userId
    "checkout_completed", // eventKey
    49.99                 // value
);

// Close the client when done (releases connection pool)
client.close();
```

### Client Configuration

```java
ExperimentationClient client = new ExperimentationClient(
    ExperimentationConfig.builder()
        .apiUrl("https://your-platform.example.com")
        .apiKey("your-api-key")
        .timeoutSeconds(2)         // HTTP call timeout. Default: 5
        .cacheTtlSeconds(60)       // Local assignment cache TTL. Default: 300
        .cacheMaxSize(1000)        // Max entries in local cache. Default: 10000
        .defaultVariant("control") // Fallback when API is unreachable
        .build()
);
```

### Experiment Variant Assignment

```java
// Simple variant lookup (returns defaultVariant on error)
String variant = client.getVariant("experiment-key", "user-123", Map.of());

// With targeting attributes
String variant = client.getVariant(
    "premium-checkout",
    "user-123",
    Map.of(
        "country", "US",
        "plan", "enterprise",
        "accountAge", "365"
    )
);

// Full assignment metadata
Assignment assignment = client.getAssignment(
    "experiment-key",
    "user-123",
    Map.of("plan", "pro")
);
System.out.println(assignment.getVariantKey());    // "treatment-a"
System.out.println(assignment.getExperimentId());  // UUID string
System.out.println(assignment.isControl());        // false
```

### Feature Flag Evaluation

```java
// Boolean flag
boolean enabled = client.isFeatureEnabled("flag-key", "user-123", Map.of());

// With targeting attributes
boolean enabled = client.isFeatureEnabled(
    "new-checkout",
    "user-123",
    Map.of("country", "US", "segment", "beta")
);
```

### Event Tracking

```java
// Simple event (no value)
client.trackEvent("user-123", "page_view", null);

// Event with a numeric value
client.trackEvent("user-123", "purchase_completed", 149.00);
```

### Consistent-Hash Bucketing

The Java SDK uses MD5-based consistent hashing for deterministic variant assignment. Given the same `experimentKey` and `userId`, `getVariant()` always returns the same variant without a network call when the assignment is already cached. The hash input is `"{experimentKey}:{userId}"` and bucket boundaries are derived from the experiment's traffic allocation configuration returned by the API. This guarantees that:

- The same user always sees the same variant for a given experiment.
- Variant assignment is stable across SDK restarts (within cache TTL).
- No sticky-session infrastructure is required.

### Spring Boot Auto-Configuration

Add the starter dependency to use Spring Boot auto-configuration:

**Maven**:

```xml
<dependency>
    <groupId>com.experimentation</groupId>
    <artifactId>experimentation-spring-boot-starter</artifactId>
    <version>1.0.0</version>
</dependency>
```

**Gradle**:

```groovy
implementation 'com.experimentation:experimentation-spring-boot-starter:1.0.0'
```

Enable the integration in your application class:

```java
import com.experimentation.spring.EnableExperimentation;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
@EnableExperimentation
public class MyApplication {
    public static void main(String[] args) {
        SpringApplication.run(MyApplication.class, args);
    }
}
```

The `ExperimentationClient` bean is then available for injection:

```java
import com.experimentation.sdk.ExperimentationClient;
import org.springframework.stereotype.Service;

@Service
public class CheckoutService {

    private final ExperimentationClient experimentationClient;

    public CheckoutService(ExperimentationClient experimentationClient) {
        this.experimentationClient = experimentationClient;
    }

    public String resolveCheckoutVariant(String userId, Map<String, String> attributes) {
        return experimentationClient.getVariant("checkout-flow", userId, attributes);
    }
}
```

### Spring Boot Properties

Configure the SDK via `application.properties` or `application.yml`:

| Property | Type | Default | Description |
|---|---|---|---|
| `experimentation.api-url` | `String` | _(required)_ | Base URL of the Experimentation Platform API |
| `experimentation.api-key` | `String` | _(required)_ | API key for SDK authentication (`X-API-Key` header) |
| `experimentation.cache-ttl-seconds` | `int` | `300` | Seconds before a cached assignment expires |
| `experimentation.cache-max-size` | `int` | `10000` | Maximum number of entries held in the local LRU cache |
| `experimentation.timeout-seconds` | `int` | `5` | HTTP request timeout in seconds |
| `experimentation.default-variant` | `String` | `"control"` | Variant returned when the API is unreachable |

**Example `application.yml`**:

```yaml
experimentation:
  api-url: https://your-platform.example.com
  api-key: ${EXPERIMENTATION_API_KEY}
  cache-ttl-seconds: 120
  cache-max-size: 5000
  timeout-seconds: 2
  default-variant: control
```

---

## React SDK

The React SDK is the one SDK verified end to end against this backend (the ShopLab demo in `demo/shoplab`
runs on it). Its full reference — provider, hooks, HOC, SSR client, types and the exact backend calls — lives
in [docs/sdk/react.md](sdk/react.md); `sdk/react/README.md` is the package README.

Highlights:

- `ExperimentationProvider` takes `config={{ apiKey, baseUrl }}` and `user={{ userId, attributes }}`.
- `useExperiment(key)` → `{ variantKey, variantName, variantId, isControl, configuration, loading, error }`
  via `POST /api/v1/tracking/assign` (sticky on the server).
- `useFeatureFlag(key)` → `{ isEnabled, variant, config, loading, error }` via
  `GET /api/v1/feature-flags/evaluate/{key}?user_id=`; `useVariant` and `useMultipleFlags` build on it.
- `useTrackEvent()` → `track(eventName, properties?, { experimentKey?, featureFlagKey?, value? })`; without a
  key the event fans out to every experiment the user is assigned to.
- `ServerClient` (from `@experimentation-platform/react-sdk/ssr`) offers the same calls for Node/SSR and never throws.

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
