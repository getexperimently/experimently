# React SDK

The React SDK provides hooks, a context provider, a higher-order component, and SSR support for integrating experiments and feature flags into React and Next.js applications.

---

## Installation

```bash
npm install @experimently/react-sdk
# or
yarn add @experimently/react-sdk
```

---

## Provider Setup

Wrap your application (or the subtree that needs experimentation) with `ExperimentationProvider`. The provider fetches flag and experiment data for the current user and makes it available to all child components via React context.

```tsx
import React from 'react';
import { ExperimentationProvider } from '@experimently/react-sdk';

function App() {
  return (
    <ExperimentationProvider
      apiUrl="https://your-platform.example.com"
      apiKey={process.env.NEXT_PUBLIC_EXPERIMENTATION_API_KEY}
      userId={currentUser.id}
      userAttributes={{
        country: currentUser.country,
        plan: currentUser.plan,
      }}
    >
      <YourApplication />
    </ExperimentationProvider>
  );
}

export default App;
```

### Provider Props

| Prop | Type | Required | Description |
|------|------|----------|-------------|
| `apiUrl` | `string` | Yes | Base URL of the experimentation platform |
| `apiKey` | `string` | Yes | API key for authentication |
| `userId` | `string` | Yes | Current user's unique identifier |
| `userAttributes` | `Record<string, string \| number \| boolean>` | No | Targeting attributes passed to all evaluations |
| `initialFlags` | `Record<string, boolean>` | No | Pre-fetched flag values for SSR hydration |
| `defaultVariant` | `string` | No | Fallback variant on error (default: `"control"`) |

The provider catches all errors internally. If the API is unavailable, hooks return safe defaults without throwing.

---

## Hooks Reference

### `useFeatureFlag(flagKey, defaultValue?)`

Evaluates a single feature flag for the current user. Returns the flag's boolean state (`true` = enabled). Falls back to `defaultValue` (default: `false`) while loading or on error.

```tsx
import { useFeatureFlag } from '@experimently/react-sdk';

function SettingsPanel() {
  const isDarkMode = useFeatureFlag('dark-mode', false);

  return <Panel theme={isDarkMode ? 'dark' : 'light'} />;
}
```

The hook is synchronous after the initial load. On the first render (while flags are being fetched), it returns `defaultValue`.

---

### `useExperiment(experimentKey)`

Returns the variant assignment and loading state for an experiment.

```tsx
import { useExperiment } from '@experimently/react-sdk';

function CheckoutButton() {
  const { variant, isLoading, error } = useExperiment('checkout-button-color');

  if (isLoading) return <DefaultButton />;
  if (error) return <DefaultButton />;

  return variant === 'green' ? <GreenButton /> : <DefaultButton />;
}
```

**Return Value**

| Field | Type | Description |
|-------|------|-------------|
| `variant` | `string` | The assigned variant key (e.g., `'control'`, `'treatment'`) |
| `isLoading` | `boolean` | `true` while the assignment is being fetched |
| `error` | `Error \| null` | Error object if the assignment failed; `null` otherwise |

---

### `useVariant(experimentKey, variantKey)`

Returns `true` if the current user is assigned to the specified variant. Useful for conditional rendering without an explicit switch statement.

```tsx
import { useVariant } from '@experimently/react-sdk';

function HeroBanner() {
  const isNewHero = useVariant('hero-image-test', 'new-hero');

  return isNewHero ? <NewHeroBanner /> : <ClassicHeroBanner />;
}
```

---

### `useMultipleFlags(flagKeys)`

Evaluates multiple feature flags in a single call. Returns a map of `flagKey → boolean` and a shared `isLoading` state.

```tsx
import { useMultipleFlags } from '@experimently/react-sdk';

function FeatureSuite() {
  const { flags, isLoading } = useMultipleFlags([
    'dark-mode',
    'new-checkout',
    'beta-dashboard',
  ]);

  if (isLoading) return <Spinner />;

  return (
    <div>
      {flags['dark-mode'] && <DarkModeToggle />}
      {flags['new-checkout'] && <NewCheckoutFlow />}
      {flags['beta-dashboard'] && <BetaDashboard />}
    </div>
  );
}
```

**Return Value**

| Field | Type | Description |
|-------|------|-------------|
| `flags` | `Record<string, boolean>` | Map of flag key to enabled state |
| `isLoading` | `boolean` | `true` while flags are being fetched |

---

### `useTrackEvent()`

Returns a stable `trackEvent` function for recording conversion events. The function reference is stable across renders — safe to pass as a prop or use in event handlers without causing unnecessary re-renders.

```tsx
import { useTrackEvent } from '@experimently/react-sdk';

function PurchaseButton({ amount }: { amount: number }) {
  const trackEvent = useTrackEvent();

  const handleClick = async () => {
    // Process the purchase...
    await trackEvent('purchase_completed', amount);
  };

  return <button onClick={handleClick}>Buy Now</button>;
}
```

**Function Signature**

```typescript
trackEvent(
  eventKey: string,
  value?: number,
  properties?: Record<string, unknown>
): Promise<void>
```

Tracking failures are swallowed internally and logged. The returned Promise always resolves.

---

## `withExperimentation` Higher-Order Component

The `withExperimentation` HOC injects experimentation props into class components or when you prefer a HOC pattern over hooks.

```tsx
import { withExperimentation } from '@experimently/react-sdk';

interface OwnProps {
  productId: string;
}

interface InjectedProps {
  variant: string;
  isFeatureEnabled: (flagKey: string) => boolean;
  trackEvent: (eventKey: string, value?: number) => Promise<void>;
}

type Props = OwnProps & InjectedProps;

class ProductCard extends React.Component<Props> {
  handleAddToCart = async () => {
    await this.props.trackEvent('add_to_cart', 1);
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

---

## SSR / Next.js Support

For server-side rendering, use `ServerClient` to evaluate flags and experiments on the server before sending the response. This prevents layout shift and ensures the correct variant is rendered on first paint.

### Pages Router (`getServerSideProps`)

```tsx
// pages/checkout.tsx
import { ServerClient } from '@experimently/react-sdk/server';
import { ExperimentationProvider } from '@experimently/react-sdk';
import type { GetServerSideProps } from 'next';

export const getServerSideProps: GetServerSideProps = async (context) => {
  const serverClient = new ServerClient({
    apiUrl: process.env.EXPERIMENTATION_API_URL!,
    apiKey: process.env.EXPERIMENTATION_API_KEY!,
  });

  const userId = context.req.cookies['user_id'] ?? 'anonymous';

  const [variant, initialFlags] = await Promise.all([
    serverClient.getVariant('checkout-flow', userId, {}),
    serverClient.getAllFlags(userId, {}),
  ]);

  return {
    props: { variant, initialFlags, userId },
  };
};

export default function CheckoutPage({
  variant,
  initialFlags,
  userId,
}: {
  variant: string;
  initialFlags: Record<string, boolean>;
  userId: string;
}) {
  return (
    <ExperimentationProvider
      apiUrl={process.env.NEXT_PUBLIC_EXPERIMENTATION_API_URL!}
      apiKey={process.env.NEXT_PUBLIC_EXPERIMENTATION_API_KEY!}
      userId={userId}
      initialFlags={initialFlags}
    >
      {variant === 'express' ? <ExpressCheckout /> : <StandardCheckout />}
    </ExperimentationProvider>
  );
}
```

### App Router (Next.js 13+)

In the App Router, use `ServerClient` directly in async server components:

```tsx
// app/checkout/page.tsx
import { ServerClient } from '@experimently/react-sdk/server';
import { cookies } from 'next/headers';

export default async function CheckoutPage() {
  const serverClient = new ServerClient({
    apiUrl: process.env.EXPERIMENTATION_API_URL!,
    apiKey: process.env.EXPERIMENTATION_API_KEY!,
  });

  const userId = cookies().get('user_id')?.value ?? 'anonymous';
  const variant = await serverClient.getVariant('checkout-flow', userId, {});
  const isDarkMode = await serverClient.isFeatureEnabled('dark-mode', userId, {});

  return (
    <div className={isDarkMode ? 'dark' : 'light'}>
      {variant === 'express' ? <ExpressCheckout /> : <StandardCheckout />}
    </div>
  );
}
```

### Root Layout with Pre-Hydration

Pre-fetch all flags in the root layout to avoid loading states in child components:

```tsx
// app/layout.tsx
import { ServerClient } from '@experimently/react-sdk/server';
import { ExperimentationProvider } from '@experimently/react-sdk';
import { cookies } from 'next/headers';

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const serverClient = new ServerClient({
    apiUrl: process.env.EXPERIMENTATION_API_URL!,
    apiKey: process.env.EXPERIMENTATION_API_KEY!,
  });

  const userId = cookies().get('user_id')?.value ?? 'anonymous';
  const initialFlags = await serverClient.getAllFlags(userId, {});

  return (
    <html>
      <body>
        <ExperimentationProvider
          apiUrl={process.env.NEXT_PUBLIC_EXPERIMENTATION_API_URL!}
          apiKey={process.env.NEXT_PUBLIC_EXPERIMENTATION_API_KEY!}
          userId={userId}
          initialFlags={initialFlags}
        >
          {children}
        </ExperimentationProvider>
      </body>
    </html>
  );
}
```

### `ServerClient` API

| Method | Signature | Description |
|--------|-----------|-------------|
| `getVariant` | `(experimentKey: string, userId: string, attributes: object) => Promise<string>` | Returns the assigned variant key |
| `isFeatureEnabled` | `(flagKey: string, userId: string, attributes: object) => Promise<boolean>` | Returns the flag's boolean state |
| `getAllFlags` | `(userId: string, attributes: object) => Promise<Record<string, boolean>>` | Returns all flags for the user; used for `initialFlags` hydration |

---

## TypeScript Types

```typescript
import type {
  ExperimentResult,
  FlagMap,
} from '@experimently/react-sdk';

// useExperiment return type
interface ExperimentResult {
  variant: string;
  isLoading: boolean;
  error: Error | null;
}

// useMultipleFlags return type
interface FlagMap {
  flags: Record<string, boolean>;
  isLoading: boolean;
}
```

---

## Error Handling

The provider catches all errors from the platform API. If the API is unavailable:

- `useFeatureFlag` returns `defaultValue` (default: `false`)
- `useExperiment` returns `{ variant: defaultVariant, isLoading: false, error: <Error> }`
- `useVariant` returns `false`
- `useMultipleFlags` returns `{ flags: {}, isLoading: false }`

No unhandled promise rejections or React error boundaries are triggered by SDK failures. Your application continues to render normally with safe fallback values.
