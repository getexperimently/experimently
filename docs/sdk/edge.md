# Edge SDK

The Edge SDK provides sub-millisecond feature flag evaluation and experiment assignment for edge runtimes — including Cloudflare Workers, Vercel Edge Functions, and Deno Deploy — with zero Node.js dependencies.

---

## Why Edge-Native Evaluation?

| Approach | Latency | Cold Start |
|---|---|---|
| API call from edge function | ~50-100ms | Yes |
| Edge SDK (bootstrap pattern) | <1ms | No |

Edge functions execute close to the user, but every round-trip to your origin API adds 50-100ms of latency. The Edge SDK eliminates this by:

1. **Pre-loading** all flag definitions from the `/api/v1/edge/bootstrap` endpoint at worker startup.
2. **Evaluating locally** using the same MD5-based consistent hash algorithm as the Go, Java, Python, iOS, and Android SDKs.
3. **Caching** results in memory (and optionally in KV/Deno KV) so subsequent evaluations are instant.

---

## Installation

```bash
npm install @experimentation-platform/edge-sdk
```

---

## Cloudflare Workers Quickstart

```typescript
import { withExperimentation } from '@experimentation-platform/edge-sdk/cloudflare';

// Wrap your fetch handler with automatic flag loading
export default withExperimentation(
  async (request, env, ctx) => {
    const client = env.EP_CLIENT; // injected by the wrapper
    const userId = request.headers.get('X-User-Id') ?? 'anon';

    // Sub-millisecond sync evaluation — no network call
    const newCheckout = client.evaluateFlagSync('new-checkout', userId);

    if (newCheckout) {
      return Response.redirect('https://checkout-v2.example.com', 302);
    }

    return fetch(request); // pass through to origin
  },
  {
    apiKey: process.env.EP_API_KEY,
    baseUrl: 'https://api.your-platform.example.com',
    kvNamespace: EP_FLAGS_KV, // optional: Cloudflare KV for flag persistence
  }
);
```

### KV Caching

When a `kvNamespace` is provided, the SDK:

1. Reads the bootstrap payload from KV on each worker startup (cache hit = zero API calls).
2. After serving the request, uses `ctx.waitUntil()` to refresh KV in the background.
3. Stores flag data with a 5-minute TTL by default (configurable via `kvTtlSeconds`).

This pattern means flags are always served from local memory, and KV is refreshed asynchronously without blocking the request.

```typescript
// wrangler.toml
[[kv_namespaces]]
binding = "EP_FLAGS_KV"
id = "your-kv-namespace-id"

// Worker
export default withExperimentation(handler, {
  apiKey: env.EP_API_KEY,
  kvNamespace: env.EP_FLAGS_KV,
  kvTtlSeconds: 300,  // how long KV entries last (default: 300)
  cacheTtlMs: 60_000, // in-memory eval cache TTL (default: 60s)
});
```

### Direct Client Usage

```typescript
import { CloudflareExperimentationClient } from '@experimentation-platform/edge-sdk/cloudflare';

export default {
  async fetch(request, env, ctx) {
    const client = new CloudflareExperimentationClient({
      apiKey: env.EP_API_KEY,
      kvNamespace: env.EP_FLAGS_KV,
    });

    // Load from KV, fall back to API if KV is empty
    await client.loadFromKvOrApi();

    // Background refresh without blocking the response
    ctx.waitUntil(client.refreshAndStore());

    const enabled = client.evaluateFlagSync('my-feature', getUserId(request));
    return new Response(enabled ? 'new' : 'old');
  },
};
```

---

## Vercel Edge Middleware Quickstart

```typescript
// middleware.ts
import { createEdgeMiddleware } from '@experimentation-platform/edge-sdk/vercel';

export const middleware = createEdgeMiddleware({
  apiKey: process.env.EP_API_KEY!,
  baseUrl: 'https://api.your-platform.example.com',
  flagKeys: ['new-checkout', 'dark-mode', 'beta-feature'],
});

// Apply middleware to all routes except static assets
export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
```

The middleware:

1. Loads all flags from the bootstrap endpoint.
2. Evaluates each flag in `flagKeys` for the current user.
3. Injects evaluation results as request headers (`X-EP-Flag-{flagKey}: "true"|"false"`).
4. Downstream pages/API routes can read these headers without making additional API calls.

### Reading Injected Headers

```typescript
// pages/api/checkout.ts
export default function handler(req, res) {
  const newCheckout = req.headers['x-ep-flag-new-checkout'] === 'true';
  // ...
}
```

### User ID Extraction

The middleware extracts the user ID from (in order of priority):

1. The `X-User-Id` header (configurable via `userIdHeaderName`)
2. The `ep_user_id` cookie (configurable via `userIdCookieName`)
3. An empty string (anonymous user) as fallback

---

## Deno Deploy Quickstart

```typescript
// main.ts
import { createDenoHandler } from 'npm:@experimentation-platform/edge-sdk/deno';

export default createDenoHandler(
  async (req, client) => {
    const userId = req.headers.get('X-User-Id') ?? 'anon';
    const enabled = client.evaluateFlagSync('new-feature', userId);
    return new Response(enabled ? 'Feature enabled' : 'Feature disabled');
  },
  {
    apiKey: Deno.env.get('EP_API_KEY')!,
    baseUrl: 'https://api.your-platform.example.com',
  }
);
```

### Deno KV Persistence

```typescript
import { DenoExperimentationClient } from 'npm:@experimentation-platform/edge-sdk/deno';

const kv = await Deno.openKv();

const client = new DenoExperimentationClient({
  apiKey: Deno.env.get('EP_API_KEY')!,
  kv,
  kvTtlMs: 300_000, // 5 minutes (default)
});

// Load from Deno KV, fall back to API
await client.loadFromKvOrApi();
```

---

## Bootstrap Pattern for Zero-Latency Evaluation

The most important pattern for edge environments is **bootstrapping** — loading all flag definitions at startup so that every evaluation is synchronous:

```typescript
import { EdgeExperimentationClient } from '@experimentation-platform/edge-sdk';

// Option 1: Pass bootstrap flags at construction time (ideal for KV-backed workers)
const flagsFromKv = JSON.parse(await env.EP_FLAGS_KV.get('ep:bootstrap'));
const client = new EdgeExperimentationClient({
  apiKey: env.EP_API_KEY,
  bootstrapFlags: flagsFromKv.flags,
});

// All evaluations are now synchronous — no await needed
const enabled = client.evaluateFlagSync('my-flag', userId); // <1ms

// Option 2: Fetch bootstrap at startup (async once, then sync)
const client2 = new EdgeExperimentationClient({ apiKey: env.EP_API_KEY });
await client2.refreshFlags(); // one async call per worker lifetime
const enabled2 = client2.evaluateFlagSync('my-flag', userId); // <1ms
```

---

## Consistent Hash Algorithm

All SDKs (Go, Java, Python, iOS, Android, React, Edge) use the same bucketing algorithm:

```
MD5("{userId}:{flagKey}") → first 4 bytes little-endian uint32 → ÷ 2^32
```

This guarantees that a given user always lands in the same bucket across all platforms.

**Verification vector:**
```
hashUser('user-123', 'my-flag') === 0.6927449859213084
```

The Edge SDK implements this using a pure-JavaScript MD5 (no external dependencies, no Node.js `crypto` module) that produces byte-for-byte identical output to the reference implementations.

---

## Configuration Reference

```typescript
interface EdgeSdkConfig {
  apiKey: string;          // Required. Your platform API key.
  baseUrl?: string;        // API base URL. Defaults to production URL.
  cacheTtlMs?: number;     // Evaluation result cache TTL (default: 60_000ms).
  bootstrapFlags?: FeatureFlag[]; // Pre-loaded flag definitions (zero-latency eval).
  timeout?: number;        // Fetch timeout in ms (default: 500ms).
}
```

---

## API Reference

### `EdgeExperimentationClient`

| Method | Returns | Description |
|---|---|---|
| `evaluateFlagSync(flagKey, userId, attributes?)` | `boolean` | Synchronous evaluation from bootstrap flags. Returns `false` if flag not loaded. |
| `evaluateFlag(flagKey, userId, attributes?)` | `Promise<boolean>` | Async evaluation. Fetches from API on cache miss. |
| `getAssignmentSync(experimentKey, userId)` | `string \| null` | Synchronous variant assignment. |
| `getAssignment(experimentKey, userId)` | `Promise<string \| null>` | Async variant assignment with API fetch fallback. |
| `track(eventName, userId, properties?)` | `Promise<void>` | Fire-and-forget event tracking. Never throws. |
| `refreshFlags()` | `Promise<void>` | Fetch all flags and experiments from bootstrap endpoint. |

---

## Performance Characteristics

- **Sync evaluation**: <1ms (pure in-memory hash computation)
- **First async evaluation (cache miss)**: ~50-100ms (API call to origin)
- **Subsequent async evaluations (cache hit)**: <1ms
- **Bootstrap load**: ~50-100ms (single API call, done once per worker lifetime)
- **Memory footprint**: ~1KB per 100 flags

---

## Error Handling

The Edge SDK is designed to never break your request pipeline:

- `evaluateFlag` returns `false` on any error (network failure, timeout, 404).
- `track` swallows all errors (fire-and-forget pattern).
- Vercel middleware continues without flag injection if the bootstrap endpoint is unavailable.
- Cloudflare adapter falls back from KV to API, and from API to empty flag set.
