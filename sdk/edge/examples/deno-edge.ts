/**
 * Deno Deploy example using the Edge SDK.
 *
 * Deno Deploy runs V8 isolates globally. This example shows:
 *  1. Loading flags from Deno KV at isolate startup
 *  2. Background KV refresh for subsequent requests
 *  3. Zero-latency flag evaluation in request handlers
 *
 * Deploy with: deployctl deploy --project=my-project deno-edge.ts
 */

import { createDenoHandler, DenoExperimentationClient } from '../src/adapters/deno';

// ---------------------------------------------------------------------------
// Main handler using createDenoHandler helper
// ---------------------------------------------------------------------------

/**
 * The inner handler receives a pre-warmed client and the original request.
 * Flags are loaded from Deno KV (or API on cold start).
 */
export default {
  fetch: createDenoHandler(
    async (request: Request, client: DenoExperimentationClient): Promise<Response> => {
      const url = new URL(request.url);
      const userId = request.headers.get('X-User-Id') ?? url.searchParams.get('userId') ?? 'anon';

      // Zero-latency sync evaluation using pre-loaded flags
      const newSearchEnabled = client.evaluateFlagSync('new-search', userId, {
        region: request.headers.get('CF-IPCountry') ?? 'unknown',
      });

      const betaFeaturesEnabled = client.evaluateFlagSync('beta-features', userId);

      if (url.pathname === '/health') {
        return new Response(
          JSON.stringify({
            status: 'ok',
            flagCount: client.flagCount,
            bootstrapped: client.isBootstrapped,
          }),
          { headers: { 'Content-Type': 'application/json' } },
        );
      }

      // Track exposure asynchronously
      client.track('page_view', userId, {
        path: url.pathname,
        newSearch: newSearchEnabled,
        betaFeatures: betaFeaturesEnabled,
      }).catch(() => {}); // fire-and-forget

      return new Response(
        JSON.stringify({
          userId,
          flags: {
            'new-search': newSearchEnabled,
            'beta-features': betaFeaturesEnabled,
          },
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      );
    },
    {
      apiKey: Deno.env.get('EP_API_KEY') ?? '',
      baseUrl: Deno.env.get('EP_BASE_URL') ?? 'https://api.your-platform.com',
      cacheTtlMs: 60_000,
      timeout: 500,
    },
  ),
};

// ---------------------------------------------------------------------------
// Alternative: Manual pattern for more control
// ---------------------------------------------------------------------------

/**
 * Manual Deno Deploy handler for use cases requiring custom KV or logic.
 * Demonstrates how to use the client directly with Deno.openKv().
 */
export async function manualHandler(request: Request): Promise<Response> {
  // Open Deno KV (persistent, shared across isolates in the same region)
  // const kv = await Deno.openKv(); // Uncomment in real Deno environment

  const client = new DenoExperimentationClient({
    apiKey: Deno.env.get('EP_API_KEY') ?? '',
    baseUrl: Deno.env.get('EP_BASE_URL') ?? 'https://api.your-platform.com',
    // kv, // Uncomment to enable Deno KV caching
    kvTtlMs: 300_000, // 5 minutes
  });

  await client.loadFromKvOrApi();

  const userId = request.headers.get('X-User-Id') ?? 'anonymous';
  const enabled = client.evaluateFlagSync('my-feature', userId);

  // Background refresh in Deno (no waitUntil — use Promise without await)
  Promise.resolve().then(() => client.refreshAndStore()).catch(() => {});

  return new Response(JSON.stringify({ enabled }), {
    headers: { 'Content-Type': 'application/json' },
  });
}
