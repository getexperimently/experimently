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

## Java SDK (EP-031)

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

## React SDK (EP-032)

### Installation

```bash
npm install @experimentation/react-sdk
# or
yarn add @experimentation/react-sdk
```

### Quick Start — Provider Setup

Wrap your application (or the subtree that needs experimentation) with `ExperimentationProvider`:

```tsx
import React from 'react';
import { ExperimentationProvider } from '@experimentation/react-sdk';

function App() {
  return (
    <ExperimentationProvider
      apiUrl="https://your-platform.example.com"
      apiKey="your-api-key"
      userId="user-123"
      userAttributes={{ country: 'US', plan: 'pro' }}
    >
      <YourApplication />
    </ExperimentationProvider>
  );
}

export default App;
```

### Hooks Reference

#### `useFeatureFlag(flagKey, defaultValue?)`

Evaluates a single feature flag for the current user. Returns the flag's boolean state. Falls back to `defaultValue` (default: `false`) while loading or on error.

```tsx
import { useFeatureFlag } from '@experimentation/react-sdk';

function SettingsPanel() {
  const darkMode = useFeatureFlag('dark-mode', false);

  return <Panel theme={darkMode ? 'dark' : 'light'} />;
}
```

#### `useExperiment(experimentKey)`

Returns the variant assignment and loading state for an experiment.

```tsx
import { useExperiment } from '@experimentation/react-sdk';

function CheckoutButton() {
  const { variant, loading, error } = useExperiment('checkout-button-color');

  if (loading) return <DefaultButton />;
  if (error) return <DefaultButton />;

  return variant === 'green' ? <GreenButton /> : <DefaultButton />;
}
```

#### `useTrackEvent()`

Returns a `trackEvent` function for recording conversion events. The function is stable across renders.

```tsx
import { useTrackEvent } from '@experimentation/react-sdk';

function PurchaseButton({ amount }: { amount: number }) {
  const trackEvent = useTrackEvent();

  const handleClick = async () => {
    await trackEvent('purchase_completed', amount);
  };

  return <button onClick={handleClick}>Buy Now</button>;
}
```

Signature:

```ts
trackEvent(eventKey: string, value?: number, properties?: Record<string, unknown>): Promise<void>
```

#### `useVariant(experimentKey, variantKey)`

Returns `true` if the current user is assigned to the specified variant of an experiment. Useful for conditional rendering without an explicit switch statement.

```tsx
import { useVariant } from '@experimentation/react-sdk';

function HeroBanner() {
  const isNewHero = useVariant('hero-image-test', 'new-hero');

  return isNewHero ? <NewHeroBanner /> : <ClassicHeroBanner />;
}
```

#### `useMultipleFlags(flagKeys)`

Evaluates multiple feature flags in a single call. Returns a map of `flagKey → boolean` and a shared `loading` state, avoiding multiple round-trips.

```tsx
import { useMultipleFlags } from '@experimentation/react-sdk';

function FeatureSuite() {
  const { flags, loading } = useMultipleFlags([
    'dark-mode',
    'new-checkout',
    'beta-dashboard',
  ]);

  if (loading) return <Spinner />;

  return (
    <div>
      {flags['dark-mode'] && <DarkModeToggle />}
      {flags['new-checkout'] && <NewCheckoutFlow />}
      {flags['beta-dashboard'] && <BetaDashboard />}
    </div>
  );
}
```

### `withExperimentation` Higher-Order Component

Use the HOC to inject experimentation props into class components or when you prefer a HOC pattern over hooks:

```tsx
import { withExperimentation } from '@experimentation/react-sdk';

interface OwnProps {
  productId: string;
}

interface InjectedProps {
  variant: string;
  isFeatureEnabled: (flagKey: string) => boolean;
  trackEvent: (eventKey: string, value?: number) => void;
}

type Props = OwnProps & InjectedProps;

class ProductCard extends React.Component<Props> {
  handleAddToCart = () => {
    this.props.trackEvent('add_to_cart', 1);
  };

  render() {
    const { variant, isFeatureEnabled } = this.props;
    const showNewLayout = isFeatureEnabled('new-product-layout');

    return (
      <div className={showNewLayout ? 'card-v2' : 'card-v1'}>
        {variant === 'treatment' && <PriceHighlight />}
        <button onClick={this.handleAddToCart}>Add to Cart</button>
      </div>
    );
  }
}

export default withExperimentation(ProductCard, {
  experimentKey: 'product-card-layout',
});
```

### SSR / Next.js Support

For server-side rendering, use the `ServerClient` to evaluate flags and experiments on the server before hydration. This prevents layout shift and ensures consistent rendering.

```ts
// app/layout.tsx (Next.js App Router)
import { ServerClient } from '@experimentation/react-sdk/server';

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const serverClient = new ServerClient({
    apiUrl: process.env.EXPERIMENTATION_API_URL!,
    apiKey: process.env.EXPERIMENTATION_API_KEY!,
  });

  // Pre-fetch flags for the request's user (from session/cookie)
  const userId = await getUserIdFromSession();
  const flags = await serverClient.getAllFlags(userId, {
    country: 'US',
    plan: 'pro',
  });

  return (
    <html>
      <body>
        <ExperimentationProvider
          apiUrl={process.env.NEXT_PUBLIC_EXPERIMENTATION_API_URL!}
          apiKey={process.env.NEXT_PUBLIC_EXPERIMENTATION_API_KEY!}
          userId={userId}
          initialFlags={flags}  // Hydrate client with server-fetched values
        >
          {children}
        </ExperimentationProvider>
      </body>
    </html>
  );
}
```

**Pages Router** (`getServerSideProps`):

```ts
// pages/checkout.tsx
import { ServerClient } from '@experimentation/react-sdk/server';
import type { GetServerSideProps } from 'next';

export const getServerSideProps: GetServerSideProps = async (context) => {
  const serverClient = new ServerClient({
    apiUrl: process.env.EXPERIMENTATION_API_URL!,
    apiKey: process.env.EXPERIMENTATION_API_KEY!,
  });

  const userId = context.req.cookies['user_id'] ?? 'anonymous';
  const variant = await serverClient.getVariant('checkout-flow', userId, {});
  const flags = await serverClient.getAllFlags(userId, {});

  return {
    props: {
      variant,
      initialFlags: flags,
    },
  };
};

export default function CheckoutPage({
  variant,
  initialFlags,
}: {
  variant: string;
  initialFlags: Record<string, boolean>;
}) {
  return (
    <ExperimentationProvider initialFlags={initialFlags} userId="...">
      {variant === 'express' ? <ExpressCheckout /> : <StandardCheckout />}
    </ExperimentationProvider>
  );
}
```

**`ServerClient` API**:

| Method | Signature | Description |
|---|---|---|
| `getVariant` | `(experimentKey, userId, attributes) => Promise<string>` | Returns the assigned variant key |
| `isFeatureEnabled` | `(flagKey, userId, attributes) => Promise<boolean>` | Returns the flag's boolean state |
| `getAllFlags` | `(userId, attributes) => Promise<Record<string, boolean>>` | Returns all flags for pre-hydration |

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
