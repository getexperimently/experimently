# @experimentation-platform/react-sdk

React hooks and clients for the Experimentation Platform public API. Feature flags and
experiment assignments are decided **by the server** (sticky per user); the SDK caches the
answers per user + key and never buckets locally.

## Install

```bash
npm install @experimentation-platform/react-sdk   # peer deps: react >=17, react-dom >=17
```

Consuming from source (as the ShopLab demo does): alias `@experimentation-platform/react-sdk`
to `sdk/react/src` in your bundler and tsconfig.

## Provider setup

```tsx
import { ExperimentationProvider } from '@experimentation-platform/react-sdk';

<ExperimentationProvider
  config={{ apiKey: process.env.NEXT_PUBLIC_EXPERIMENTLY_API_KEY!, baseUrl: 'http://localhost:8000' }}
  user={{ userId: visitorId, attributes: { device: 'mobile', country: 'US', returning: false } }}
>
  <App />
</ExperimentationProvider>
```

`SdkConfig`: `apiKey`, `baseUrl`, optional `timeoutMs` (default 5000) and `cacheTtlMs` (default 300 000).
`user.attributes` is sent as `context` on experiment assignment.

## Hooks

### `useFeatureFlag(flagKey): FeatureFlagEvaluation`

```tsx
const { isEnabled, variant, config, loading, error } = useFeatureFlag('shoplab_new_search');
if (loading) return <Spinner />;
return isEnabled ? <NewSearch engine={(config as any)?.engine} /> : <LegacySearch />;
```

`variant` is `null` when off, `config.variant` when the server config contains a string
`variant`, otherwise `'on'`. On error the flag is reported off with `error` set.

### `useVariant(flagKey): string | null` — just the variant string (or `null` while loading / off / error).

### `useMultipleFlags(flagKeys): Record<string, FeatureFlagEvaluation | null>`

```tsx
const flags = useMultipleFlags(['shoplab_new_search', 'shoplab_free_shipping_banner']);
const showBanner = flags['shoplab_free_shipping_banner']?.isEnabled ?? false;  // null while loading
```

### `useExperiment(experimentKey): ExperimentAssignment`

```tsx
const { variantKey, configuration, isControl, loading } = useExperiment('shoplab_hero_banner');
const headline = (configuration?.headline as string) ?? 'Gear up for the season';
```

While loading or on error you get the control defaults:
`variantKey: 'control', variantName: 'Control', variantId: null, isControl: true, configuration: null`.

### `useTrackEvent(): (eventName, properties?, options?) => void`

```tsx
const track = useTrackEvent();
track('add_to_cart', { product_id, quantity: 1 }, { experimentKey: 'shoplab_pdp_buy_button', value: 49 });
track('search', { query, results: 12 }, { featureFlagKey: 'shoplab_new_search' });
track('page_view', { page: '/products' });           // no key -> fanned out, see below
```

`TrackEventOptions`: `experimentKey?`, `featureFlagKey?`, `value?`, `eventType?` (defaults to
`eventName`), `timestamp?` (Date, sent as ISO-8601). Tracking is fire-and-forget and never throws.

### `useExperimentation(): { client, user }`

Escape hatch to the underlying `ExperimentationClient`, e.g. `client.getAssignments(user.userId)`
for a debug overlay. `useExperimentationContext` is an alias.

### `withExperimentation(Component, flagKey)`

HOC that injects `flagEvaluation: FeatureFlagEvaluation` into `Component`.

## Tracking fan-out rule

`trackEvent` (and `useTrackEvent`) sends:

- **with** `experimentKey` and/or `featureFlagKey` → one `POST /api/v1/tracking/track` with
  `{event_type, event_name, user_id, experiment_key?, feature_flag_key?, value?, metadata, timestamp?}`;
- **without** keys → one `POST /api/v1/tracking/batch` containing one entry per experiment the
  user has been assigned to (`experiment_key`) **plus** one per flag evaluated for the user
  (`feature_flag_key`), taken from the client's cache (successful, unexpired results only);
- if nothing is cached for the user, nothing is sent and the call resolves.

## Clients

`ExperimentationClient` (browser) — `evaluateFeatureFlag(user, key)`, `evaluateFeatureFlagDetailed`,
`assignExperiment(user, key)`, `trackEvent(userId, name, props?, options?)`, `getAssignments(userId)`,
`getEvaluatedFlags(userId)`, `clearCache()`. Evaluate/assign throw on failure (the hooks turn that into
`error`); concurrent calls for the same user + key share one request; failures are never cached.

`ServerClient` (Node/SSR) — same requests, `(key, user)` argument order, **never throws**:

```ts
import { ServerClient } from '@experimentation-platform/react-sdk/ssr';

export async function getServerSideProps({ req }) {
  const client = new ServerClient({ apiKey: process.env.EXPERIMENTLY_API_KEY!, baseUrl: process.env.EXPERIMENTLY_API_URL! });
  const user = { userId: req.cookies.visitor_id };
  const flags = await client.getAll(['shoplab_new_search', 'shoplab_free_shipping_banner'], user);
  const hero = await client.assignExperiment('shoplab_hero_banner', user);  // control defaults + error on failure
  return { props: { flags, hero } };
}
```

## Backend endpoints used

Every request carries `X-API-Key: <key>` and `Content-Type: application/json`.

| SDK call | Method & path | Body / query | Response used |
|---|---|---|---|
| `evaluateFeatureFlag*`, `useFeatureFlag`, `useVariant`, `useMultipleFlags`, `ServerClient.getAll` | `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…` | — | `{key, enabled, config}` (404 when not ACTIVE) |
| `assignExperiment`, `useExperiment` | `POST /api/v1/tracking/assign` | `{experiment_key, user_id, context?}` | `{experiment_key, variant_id, variant_name, is_control, configuration}` (404 when not ACTIVE) |
| `trackEvent` with a key | `POST /api/v1/tracking/track` | `{event_type, event_name, user_id, experiment_key?, feature_flag_key?, value?, metadata?, timestamp?}` | ignored |
| `trackEvent` without keys | `POST /api/v1/tracking/batch` | `{events: [<track body>, …]}` (≤ 100 per request) | ignored |

## Development

```bash
cd sdk/react && npm install
npx jest            # unit tests (fetch is mocked)
npm run build       # tsc, strict
```
