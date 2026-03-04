# React Native SDK

The Experimentation Platform React Native SDK provides feature flag evaluation, A/B experiment assignment, and event tracking for React Native applications. It includes React hooks, a context provider, and AsyncStorage-backed offline fallback.

## Features

- Consistent MD5 hashing for cross-SDK compatible bucket assignment
- React hooks: `useFlag`, `useExperiment`, `useExperimentationClient`
- `ExperimentationProvider` context for tree-wide access
- In-memory cache with configurable TTL
- AsyncStorage offline persistence
- TypeScript-first with full type definitions
- Zero React Native-specific native modules (fetch + AsyncStorage only)

## Installation

```bash
npm install @experimentation-platform/react-native-sdk md5 @react-native-async-storage/async-storage
# or
yarn add @experimentation-platform/react-native-sdk md5 @react-native-async-storage/async-storage
```

### iOS additional step

```bash
cd ios && pod install
```

This is required for `@react-native-async-storage/async-storage`.

## Provider Setup

Wrap your root component with `ExperimentationProvider`:

```tsx
import {
  ExperimentationProvider,
  ExperimentationClient,
} from '@experimentation-platform/react-native-sdk';

const client = new ExperimentationClient({
  apiKey: 'your-api-key',
  baseUrl: 'https://api.getexperimently.com',
  cacheTtlMs: 300_000,       // 5 minutes (default)
  timeoutMs: 5_000,          // 5 seconds (default)
  offlineFallback: true,     // true (default)
});

export default function App() {
  return (
    <ExperimentationProvider
      client={client}
      userId="user-123"
      attributes={{ plan: 'pro', country: 'US' }}
    >
      <YourAppNavigator />
    </ExperimentationProvider>
  );
}
```

## useFlag Hook

```tsx
import { useFlag } from '@experimentation-platform/react-native-sdk';

function DarkModeToggle() {
  const { value, loading, error } = useFlag('dark-mode');

  if (loading) return <ActivityIndicator />;
  if (error) return <Text>Error: {error.message}</Text>;

  return (
    <Switch
      value={value}
      onValueChange={() => {/* your logic */}}
    />
  );
}
```

The hook re-runs when `userId` or `flagKey` changes.

## useExperiment Hook

```tsx
import { useExperiment } from '@experimentation-platform/react-native-sdk';

function CheckoutPage() {
  const { variant, loading, error } = useExperiment('checkout-experiment');

  if (loading) return <ActivityIndicator />;
  if (error) return <OldCheckout />;

  return variant === 'treatment' ? <NewCheckout /> : <OldCheckout />;
}
```

## useExperimentationClient Hook

For imperative access to the client (e.g. manual event tracking):

```tsx
import { useExperimentationClient } from '@experimentation-platform/react-native-sdk';

function PurchaseButton() {
  const { client, userId } = useExperimentationClient();

  const handlePress = async () => {
    // ... handle purchase ...
    await client.track('purchase_completed', userId, {
      amount: 49.99,
      currency: 'USD',
    });
  };

  return <Button title="Buy Now" onPress={handlePress} />;
}
```

## Direct Client API

You can also use the client directly, without hooks:

```typescript
import { ExperimentationClient } from '@experimentation-platform/react-native-sdk';

const client = new ExperimentationClient({
  apiKey: 'your-api-key',
  baseUrl: 'https://api.getexperimently.com',
});

// Feature flag evaluation
const enabled = await client.evaluateFlag('dark-mode', 'user-123', {
  plan: 'pro',
  country: 'US',
});

// Experiment assignment
const variant = await client.getAssignment('checkout-experiment', 'user-123');

// Event tracking (fire-and-forget, never throws)
await client.track('button_clicked', 'user-123', { screen: 'home' });

// Clear in-memory cache
client.clearCache();
```

## Evaluation Order

For `evaluateFlag` and `getAssignment`:

1. **In-memory cache** — fast path, returns cached result if not expired.
2. **API call** — fetches and evaluates locally using the consistent hash.
3. **AsyncStorage fallback** — serves last-known value when the API is unreachable.
4. **Safe default** — returns `false` / `null` if no data is available.

## AsyncStorage Configuration

The SDK uses `@react-native-async-storage/async-storage` with keys prefixed
`ep_sdk_flag:` and `ep_sdk_asgn:` to avoid collisions.

To disable offline persistence:

```typescript
const client = new ExperimentationClient({
  apiKey: 'your-api-key',
  baseUrl: 'https://api.getexperimently.com',
  offlineFallback: false,
});
```

## Platform-Specific Notes

### iOS

- Requires `pod install` for the AsyncStorage native module.
- Tested on iOS 14+. Works with both old and new architecture (Fabric).

### Android

- No additional setup beyond standard React Native configuration.
- Tested on Android API 21+ (minSdk 21).
- AsyncStorage uses SQLite on Android by default.

### Expo

If using Expo Managed Workflow:

```bash
npx expo install @react-native-async-storage/async-storage
```

The SDK works with Expo SDK 49+.

## Hash Algorithm

The consistent hash is identical across all SDK implementations:

```
MD5("{userId}:{flagKey}") → first 4 bytes as little-endian uint32 → ÷ 2^32
```

The divisor is **4294967296** (2^32), not `4294967295` (MaxUInt32). This
ensures bit-identical results with the Java, Python, Go, iOS, Android, and
Flutter SDKs.

```typescript
import { hashUser } from '@experimentation-platform/react-native-sdk';

const h = hashUser('user-123', 'my-flag');
// h ≈ 0.6927449859  (verified against all SDK implementations)
```

## Testing

### Jest Setup

The SDK ships with a Jest mock for AsyncStorage. Add it to your Jest config:

```json
{
  "moduleNameMapper": {
    "@react-native-async-storage/async-storage": "<rootDir>/node_modules/@experimentation-platform/react-native-sdk/__mocks__/@react-native-async-storage/async-storage"
  }
}
```

Or copy the mock to your project's `__mocks__` directory.

### Mocking the Client in Tests

```typescript
import { ExperimentationClient } from '@experimentation-platform/react-native-sdk';

const mockClient = {
  evaluateFlag: jest.fn().mockResolvedValue(true),
  getAssignment: jest.fn().mockResolvedValue('treatment'),
  track: jest.fn().mockResolvedValue(undefined),
  clearCache: jest.fn(),
} as unknown as ExperimentationClient;
```

### Testing Hooks with ExperimentationProvider

```tsx
import { render, waitFor } from '@testing-library/react-native';
import { ExperimentationProvider, useFlag } from '@experimentation-platform/react-native-sdk';

function TestComponent() {
  const { value, loading } = useFlag('my-flag');
  if (loading) return <Text>Loading</Text>;
  return <Text testID="result">{value ? 'on' : 'off'}</Text>;
}

test('useFlag returns true', async () => {
  const client = { evaluateFlag: jest.fn().mockResolvedValue(true) } as any;

  const { getByTestId } = render(
    <ExperimentationProvider client={client} userId="u1">
      <TestComponent />
    </ExperimentationProvider>
  );

  await waitFor(() => {
    expect(getByTestId('result').props.children).toBe('on');
  });
});
```

## Troubleshooting

### `useExperimentationContext must be used inside an <ExperimentationProvider>`

Ensure `ExperimentationProvider` wraps the component calling the hook.
Check that there is no second copy of React in your bundle (version mismatch).

### Flags always return `false`

1. Verify your `apiKey` and `baseUrl` are correct.
2. Check network connectivity — the SDK returns `false` as a safe default on errors.
3. Enable `offlineFallback: true` to serve cached values during outages.
4. Check the flag's rollout percentage in the platform dashboard.

### Type errors with `md5`

Install the type definitions:

```bash
npm install --save-dev @types/md5
```
