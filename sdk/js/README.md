# @experimentation-platform/js-sdk

JavaScript/TypeScript client for the Experimentation Platform public API. Node >= 18 and browsers,
zero runtime dependencies (global `fetch`), CommonJS build with type declarations.

Flag evaluation and experiment assignment are **decided by the server**; results are cached per
user + key in memory. Nothing is bucketed locally.

Full documentation: [`docs/sdk/javascript.md`](../../docs/sdk/javascript.md).

## Quick start

```ts
import { ExperimentationClient } from '@experimentation-platform/js-sdk';

const client = new ExperimentationClient({ apiUrl: 'http://localhost:8000', apiKey: 'eptk_...' });
const user = { userId: 'user-123', attributes: { plan: 'pro' } };

const assignment = await client.getAssignment('checkout_flow', user); // { experimentKey, userId, variantId, variantName, isControl, configuration }
const variant = await client.getVariant('checkout_flow', user);       // variantName, 'control' on failure
const { enabled, config, reason } = await client.evaluateFlag('new_search', user); // attributes sent as ?context=
const on = await client.isFeatureEnabled('new_search', user);         // false on failure

await client.track('user-123', 'purchase', { value: 49.99, experimentKey: 'checkout_flow' });
await client.track('user-123', 'page_view'); // no key → fans out to every cached assignment + flag
```

## API

| Method | Returns | On failure |
|---|---|---|
| `getAssignment(experimentKey, user)` | `Promise<Assignment>` | rejects with `ExperimentationError` (`code`, `status`, `body`) |
| `getVariant(experimentKey, user)` | `Promise<string>` | `defaultVariant` (`'control'`) |
| `evaluateFlag(flagKey, user)` | `Promise<FlagEvaluation>` — `{ key, enabled, config, reason? }` | rejects with `ExperimentationError` |
| `isFeatureEnabled(flagKey, user)` | `Promise<boolean>` | `false` |
| `getAllFlags(userId, attributes?)` | `Promise<Record<string, boolean>>` (not cached) | rejects |
| `track(userId, eventName, { value?, properties?, experimentKey?, featureFlagKey?, eventType?, timestamp? })` | `Promise<void>` | never rejects; `onError` |
| `trackBatch(events)` | `Promise<{ successCount, failureCount, errors }>` (chunked at 100) | never rejects |
| `fetchAssignments(userId, { activeOnly? })` | `Promise<AssignmentRecord[]>` from the server | rejects |
| `getAssignments(userId)`, `getEvaluatedFlags(userId)`, `clearCache()` | in-memory cache access | — |
| `consistentHash(userId, flagKey)`, `md5Hex(s)`, `md5Bytes(s)` | compatibility hash utilities (unused for bucketing) | — |

Config: `apiUrl`, `apiKey` (required); `timeoutMs` (5000), `cacheTtlMs` (300000),
`defaultVariant` (`'control'`), `fetch`, `onError(err, 'track' | 'trackBatch')`.
Failures are never cached; concurrent calls for the same user + key share one request; a 429 is
retried once after `Retry-After`.

`user.attributes` is sent as `context` on assignment **and** on flag evaluation
(`&context=<url-encoded JSON>`, omitted when empty), so flag targeting rules evaluate against it
(`country` also matches `user.country`; nested objects flatten to dotted keys such as `app.version`).
Caches are keyed by user + key only — call `clearCache()` after changing a user's attributes.

## Backend endpoints used

Every request carries `X-API-Key`, `Content-Type: application/json`, `Accept: application/json`.

| SDK call | Method and path | 200 response |
|---|---|---|
| `getAssignment`, `getVariant` | `POST /api/v1/tracking/assign` `{experiment_key, user_id, context?}` | `{experiment_key, user_id, variant_id, variant_name, is_control, configuration}` |
| `evaluateFlag`, `isFeatureEnabled` | `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…&context=<url-encoded JSON>` | `{key, enabled, config, reason}` |
| `getAllFlags` | `GET /api/v1/feature-flags/user/{user_id}?context=<url-encoded JSON>` | `{"<flag_key>": bool}` |
| `track` with a key | `POST /api/v1/tracking/track` | ignored |
| `track` without keys, `trackBatch` | `POST /api/v1/tracking/batch` `{events: [...]}` (≤ 100) | `{success_count, failure_count, errors}` |
| `fetchAssignments` | `GET /api/v1/tracking/assignments/{user_id}?active_only=true` | list of rows |

Errors: 401 bad key, 404 flag/experiment not ACTIVE (never cached), 422 track without a key, 429 rate limited.

## Contract smoke

```bash
cd sdk/js && npm run build --silent && node examples/contract_smoke.mjs
```

Env: `EXPERIMENTLY_API_URL` (default `http://localhost:8000`), `EXPERIMENTLY_API_KEY` (required),
`CONTRACT_EXPERIMENT_KEY` (`sdk_contract_ab`), `CONTRACT_FLAG_KEY` (`sdk_contract_flag`), `CONTRACT_USER_ID`.

Verified against a live backend: **yes (2026-09-11)**.

## Development

```bash
npm install
npm test          # 105 Jest tests (fetch mocked)
npm run build     # tsc → dist/ (CommonJS + .d.ts)
```
