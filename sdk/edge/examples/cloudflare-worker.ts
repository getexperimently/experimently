/**
 * Complete Cloudflare Worker example using the Edge SDK.
 *
 * This example demonstrates:
 *  1. Pre-loading flags from Cloudflare KV at worker startup
 *  2. Zero-latency flag evaluation in the request handler
 *  3. Background KV refresh so the next request gets fresh flags
 *  4. Event tracking for analytics
 *
 * Deploy with: wrangler deploy
 *
 * wrangler.toml:
 * ```toml
 * name = "my-worker"
 * main = "examples/cloudflare-worker.ts"
 * compatibility_date = "2024-01-01"
 *
 * [[kv_namespaces]]
 * binding = "FLAGS_KV"
 * id = "your-kv-namespace-id"
 *
 * [vars]
 * EP_API_KEY = "your-api-key"
 * ```
 */

import { withExperimentation } from '../src/adapters/cloudflare';
import type { CloudflareExperimentationClient } from '../src/adapters/cloudflare';

interface Env {
  FLAGS_KV: import('../src/adapters/cloudflare').KVNamespace;
  EP_API_KEY: string;
  EP_CLIENT?: CloudflareExperimentationClient;
}

async function handler(
  request: Request,
  env: Record<string, unknown>,
): Promise<Response> {
  const typedEnv = env as unknown as Env;
  const client = typedEnv.EP_CLIENT!;

  // Extract user ID from cookie or generate anonymous ID
  const userId = getUserId(request) ?? 'anonymous';

  // Zero-latency evaluation — uses KV-loaded bootstrap flags
  const newCheckoutEnabled = client.evaluateFlagSync('new-checkout', userId, {
    country: request.headers.get('CF-IPCountry') ?? 'unknown',
  });

  const darkModeEnabled = client.evaluateFlagSync('dark-mode', userId);

  // Route to appropriate handler
  const url = new URL(request.url);

  if (url.pathname === '/checkout' && newCheckoutEnabled) {
    // Track the experiment exposure
    client.track('checkout_viewed', userId, {
      variant: 'new-checkout',
      path: url.pathname,
    }).catch(() => {}); // fire-and-forget

    return new Response(
      JSON.stringify({ checkout: 'new', darkMode: darkModeEnabled }),
      {
        headers: {
          'Content-Type': 'application/json',
          'X-EP-User-Id': userId,
          'X-EP-Flag-new-checkout': 'true',
        },
      },
    );
  }

  return new Response(
    JSON.stringify({
      checkout: 'original',
      darkMode: darkModeEnabled,
      flags: {
        'new-checkout': newCheckoutEnabled,
        'dark-mode': darkModeEnabled,
      },
    }),
    {
      headers: { 'Content-Type': 'application/json' },
    },
  );
}

function getUserId(request: Request): string | null {
  // Try to get userId from cookie
  const cookieHeader = request.headers.get('Cookie') ?? '';
  for (const part of cookieHeader.split(';')) {
    const [name, ...rest] = part.trim().split('=');
    if (name.trim() === 'user_id' && rest.length > 0) {
      return decodeURIComponent(rest.join('='));
    }
  }
  // Fall back to a header
  return request.headers.get('X-User-Id');
}

// Export the wrapped handler — flags are loaded from KV automatically
export default {
  fetch: withExperimentation(
    handler,
    {
      apiKey: '', // Will be overridden from env.EP_API_KEY at runtime
      baseUrl: 'https://api.your-experimentation-platform.com',
      cacheTtlMs: 60_000,
    },
  ),
};
