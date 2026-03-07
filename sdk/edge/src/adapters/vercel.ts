/**
 * Vercel Edge Functions / Edge Middleware adapter.
 *
 * Pattern: the middleware evaluates feature flags and injects the results as
 * request headers so that origin functions (serverless or edge) can read them
 * without an additional API call.
 *
 * Header convention:
 *   X-EP-Flag-{flagKey}: "true" | "false"
 *   X-EP-User-Id: the resolved user ID (from cookie or header)
 *
 * Usage (middleware.ts):
 * ```ts
 * import { createEdgeMiddleware } from '@experimentation-platform/edge-sdk/vercel';
 *
 * export const middleware = createEdgeMiddleware({
 *   apiKey: process.env.EP_API_KEY!,
 *   flagKeys: ['new-checkout', 'dark-mode'],
 * });
 *
 * export const config = { matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'] };
 * ```
 */

import { EdgeExperimentationClient } from '../client';
import type { EdgeSdkConfig } from '../types';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export interface VercelEdgeConfig extends EdgeSdkConfig {
  /**
   * List of flag keys to evaluate and inject as request headers.
   * If omitted, all bootstrap flags are evaluated.
   */
  flagKeys?: string[];
  /**
   * Cookie name to read the user ID from. Defaults to 'ep_user_id'.
   */
  userIdCookieName?: string;
  /**
   * Header name to read the user ID from (checked before the cookie).
   * Defaults to 'X-User-Id'.
   */
  userIdHeaderName?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Extract the user ID from the request:
 *   1. Check the configurable header
 *   2. Fall back to the configurable cookie
 *   3. Fall back to an empty string (anonymous)
 */
function extractUserId(request: Request, config: VercelEdgeConfig): string {
  const headerName = config.userIdHeaderName ?? 'X-User-Id';
  const fromHeader = request.headers.get(headerName);
  if (fromHeader) return fromHeader;

  const cookieName = config.userIdCookieName ?? 'ep_user_id';
  const cookieHeader = request.headers.get('Cookie') ?? '';
  for (const part of cookieHeader.split(';')) {
    const [name, ...rest] = part.trim().split('=');
    if (name.trim() === cookieName && rest.length > 0) {
      return decodeURIComponent(rest.join('='));
    }
  }

  return '';
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Create a Vercel Edge middleware function that evaluates feature flags
 * and injects the results as request headers.
 *
 * The returned function has the same signature as a Vercel Edge middleware:
 *   `(request: Request) => Promise<Response>`
 *
 * When no `Response` constructor is needed the function just modifies headers
 * on a NextResponse.next() — here we pass-through using fetch() or a redirect,
 * but in practice the consumer calls `NextResponse.next({ request: { headers } })`.
 */
export function createEdgeMiddleware(config: VercelEdgeConfig) {
  return async function middleware(request: Request): Promise<Response> {
    const client = new EdgeExperimentationClient(config);

    // Warm the client from the bootstrap endpoint
    try {
      await client.refreshFlags();
    } catch {
      // If the bootstrap call fails, continue without flag injection
      // This ensures the middleware never breaks the request pipeline
    }

    const userId = extractUserId(request, config);
    const newHeaders = new Headers(request.headers);

    // Determine which flags to evaluate
    const keysToEvaluate: string[] = config.flagKeys && config.flagKeys.length > 0
      ? config.flagKeys
      : Array.from((client as unknown as { flags: Map<string, unknown> }).flags.keys());

    // Evaluate each flag and inject as a header
    for (const flagKey of keysToEvaluate) {
      const enabled = client.evaluateFlagSync(flagKey, userId);
      const headerKey = `X-EP-Flag-${flagKey}`;
      newHeaders.set(headerKey, String(enabled));
    }

    // Inject the resolved user ID for downstream use
    if (userId) {
      newHeaders.set('X-EP-User-Id', userId);
    }

    // Pass through: in real Vercel middleware this would be NextResponse.next()
    // Here we rewrite the request with injected headers and pass through.
    // The consumer can use these headers in their pages/api routes.
    return fetch(new Request(request, { headers: newHeaders }));
  };
}
