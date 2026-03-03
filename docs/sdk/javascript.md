# JavaScript SDK

The JavaScript SDK provides experiment variant assignment, feature flag evaluation, and event tracking for browser and Node.js environments.

---

## Installation

```bash
npm install @experimently/js-sdk
# or
yarn add @experimently/js-sdk
```

---

## Initializing the Client

```typescript
import { ExperimentationClient } from '@experimently/js-sdk';

const client = new ExperimentationClient({
  apiUrl: 'https://your-platform.example.com',
  apiKey: process.env.EXPERIMENTATION_API_KEY,
});
```

### Configuration Options

```typescript
const client = new ExperimentationClient({
  apiUrl: 'https://your-platform.example.com',   // Required
  apiKey: 'your-api-key',                         // Required
  timeoutMs: 2000,                                // HTTP timeout (default: 5000)
  cacheTtlSeconds: 60,                            // Local assignment cache TTL (default: 300)
  defaultVariant: 'control',                      // Fallback on error (default: 'control')
});
```

---

## Experiment Variant Assignment

### `getVariant(experimentKey, userId, attributes?)`

Returns the variant key assigned to the user for the given experiment. On error (network failure, timeout), returns `defaultVariant`.

```typescript
const variant = await client.getVariant(
  'checkout-button-color',    // experimentKey
  'user-123',                 // userId
  {                           // optional attributes for targeting rules
    country: 'US',
    plan: 'pro',
  }
);

console.log(variant); // 'control' or 'treatment'

if (variant === 'treatment') {
  showGreenButton();
} else {
  showBlueButton();
}
```

### Attribute Types

Attributes are passed as a `Record<string, string | number | boolean | string[]>` object. The platform evaluates targeting rules against these values at assignment time.

| Attribute Type | Example |
|----------------|---------|
| `string` | `{ country: 'US' }` |
| `number` | `{ accountAgeDays: 45 }` |
| `boolean` | `{ isPremium: true }` |
| `string[]` | `{ tags: ['beta', 'power-user'] }` |

---

## Feature Flag Evaluation

### `isFeatureEnabled(flagKey, userId, attributes?)`

Returns `true` if the feature flag is enabled for the given user, `false` otherwise. On error, returns `false` (safe default).

```typescript
const isEnabled = await client.isFeatureEnabled(
  'dark-mode',    // flagKey
  'user-123',     // userId
  {               // optional targeting attributes
    plan: 'enterprise',
    country: 'US',
  }
);

if (isEnabled) {
  applyDarkTheme();
} else {
  applyLightTheme();
}
```

---

## Event Tracking

### `trackEvent(userId, eventKey, value?)`

Records a conversion or behavioral event for a user. Events are used to compute experiment metrics.

```typescript
// Simple event (no numeric value)
await client.trackEvent('user-123', 'button_clicked');

// Event with a numeric value (used for revenue/count metrics)
await client.trackEvent('user-123', 'purchase_completed', 49.99);

// Additional properties (optional)
await client.trackEvent('user-123', 'checkout_completed', 149.00);
```

Tracking failures are logged but do not throw by default. The SDK continues operating normally even if event delivery fails.

---

## Consistent Hash Bucketing

The SDK implements client-side consistent hash bucketing. Assignment is computed as a deterministic hash of `experimentKey + userId`:

- The same `userId` always receives the same variant for a given `experimentKey`
- No network call is needed for a cached assignment
- Assignment is stable across SDK restarts and cache clears (within the cache TTL)

This means you can call `getVariant` as often as needed (for example, on every page render) without incurring network overhead after the first call.

---

## Async/Await Pattern

All SDK methods return Promises. Use `async/await` or `.then()`:

```typescript
// async/await (recommended)
async function renderCheckout() {
  const variant = await client.getVariant('checkout-flow', userId);
  return variant === 'simplified' ? <SimplifiedCheckout /> : <StandardCheckout />;
}

// .then() equivalent
client.getVariant('checkout-flow', userId)
  .then(variant => {
    renderCheckout(variant);
  });
```

---

## Error Handling and Fallback Values

The SDK is designed to fail safely. If the API is unreachable, times out, or returns an error:

- `getVariant` returns `defaultVariant` (configured at initialization, default: `'control'`)
- `isFeatureEnabled` returns `false`
- `trackEvent` logs the failure and resolves (does not reject)

This ensures that SDK failures never break your application.

```typescript
// Explicit error handling if needed
try {
  const variant = await client.getVariant('experiment-key', userId);
  // variant is always a string — never throws
} catch (error) {
  // This block is never reached for assignment calls
  // SDK handles errors internally
}

// To enable strict mode (throws on tracking failure)
await client.trackEvent('user-123', 'purchase', 49.99, { throwOnError: true });
```

---

## TypeScript Types

The SDK ships with full TypeScript definitions:

```typescript
import type {
  ExperimentationClient,
  ClientConfig,
  Assignment,
} from '@experimently/js-sdk';

// Assignment object returned by getAssignment()
interface Assignment {
  variantKey: string;
  experimentId: string;
  isControl: boolean;
  assignedAt: string; // ISO 8601 timestamp
}

// Get full assignment metadata
const assignment: Assignment = await client.getAssignment(
  'experiment-key',
  'user-123',
  { plan: 'pro' }
);
console.log(assignment.isControl); // false
console.log(assignment.variantKey); // 'treatment-a'
```

---

## Browser vs Node.js Usage

The SDK is isomorphic and works in both environments.

### Browser

In the browser, the API key is visible to end users. Use a **read-only scoped key** and avoid granting `admin` scope to browser-facing keys.

```typescript
// In a React app
const client = new ExperimentationClient({
  apiUrl: process.env.NEXT_PUBLIC_EXPERIMENTATION_API_URL,
  apiKey: process.env.NEXT_PUBLIC_EXPERIMENTATION_API_KEY,
});
```

### Node.js / Server-Side

In server environments, the API key is kept private. You can use a key with broader scopes.

```typescript
// In a Node.js service
const client = new ExperimentationClient({
  apiUrl: process.env.EXPERIMENTATION_API_URL,
  apiKey: process.env.EXPERIMENTATION_API_KEY,
  timeoutMs: 1000, // Lower timeout for server-side use cases
});
```

---

## Local Development

Point the client at your local development instance:

```typescript
const client = new ExperimentationClient({
  apiUrl: 'http://localhost:8000',
  apiKey: 'dev-api-key',
});
```

---

## Complete Usage Example

```typescript
import { ExperimentationClient } from '@experimently/js-sdk';

const client = new ExperimentationClient({
  apiUrl: process.env.EXPERIMENTATION_API_URL!,
  apiKey: process.env.EXPERIMENTATION_API_KEY!,
  defaultVariant: 'control',
});

async function handleCheckout(userId: string, userPlan: string) {
  // Check if new checkout is enabled
  const useNewCheckout = await client.isFeatureEnabled('new-checkout-flow', userId, {
    plan: userPlan,
  });

  // Get variant for the checkout CTA experiment
  const ctaVariant = await client.getVariant('checkout-cta-copy', userId, {
    plan: userPlan,
  });

  // Render appropriate UI
  const checkout = useNewCheckout ? renderNewCheckout() : renderOldCheckout();
  const ctaText = ctaVariant === 'urgent' ? 'Buy Now — Limited Time!' : 'Complete Purchase';

  // Track when user reaches checkout
  await client.trackEvent(userId, 'checkout_started');

  return { checkout, ctaText };
}

// After purchase completes
async function onPurchaseComplete(userId: string, orderValue: number) {
  await client.trackEvent(userId, 'purchase_completed', orderValue);
}
```
