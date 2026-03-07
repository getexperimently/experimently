/**
 * Cloudflare Workers adapter for the Edge Experimentation SDK.
 *
 * Features:
 *  - KV namespace integration: flags are persisted in Cloudflare KV for sharing
 *    across worker instances in the same data centre
 *  - `withExperimentation` HOF: wraps a Cloudflare fetch handler and injects
 *    a pre-initialised client into the handler via the `env` object
 *  - `refreshAndStore`: fetches fresh flags from the API and writes them to KV
 *
 * KV layout:
 *   Key:   "ep:bootstrap"
 *   Value: JSON-serialised BootstrapResponse
 *   TTL:   kvTtlSeconds (default 300 s)
 *
 * Usage:
 *   export default withExperimentation(handler, {
 *     apiKey: env.EP_API_KEY,
 *     kvNamespace: env.EP_FLAGS_KV,
 *   });
 */

import { EdgeExperimentationClient } from '../client';
import type { EdgeSdkConfig, BootstrapResponse, FeatureFlag, Experiment } from '../types';

const KV_KEY = 'ep:bootstrap';
const DEFAULT_KV_TTL_SECONDS = 300; // 5 minutes

// ---------------------------------------------------------------------------
// KVNamespace interface (matches the Cloudflare Workers type)
// ---------------------------------------------------------------------------

export interface KVNamespace {
  get(key: string, options?: { type?: string }): Promise<string | null>;
  put(key: string, value: string, options?: { expirationTtl?: number }): Promise<void>;
}

// ---------------------------------------------------------------------------
// ExecutionContext interface (minimal — matches Cloudflare Workers type)
// ---------------------------------------------------------------------------

export interface ExecutionContext {
  waitUntil(promise: Promise<unknown>): void;
  passThroughOnException(): void;
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export interface CloudflareConfig extends EdgeSdkConfig {
  /** Cloudflare KV namespace binding for flag persistence across instances. */
  kvNamespace?: KVNamespace;
  /** TTL in seconds for KV entries. Defaults to 300 (5 minutes). */
  kvTtlSeconds?: number;
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export class CloudflareExperimentationClient extends EdgeExperimentationClient {
  private readonly kv: KVNamespace | undefined;
  private readonly kvTtlSeconds: number;
  private kvLoaded: boolean = false;

  constructor(config: CloudflareConfig) {
    super(config);
    this.kv = config.kvNamespace;
    this.kvTtlSeconds = config.kvTtlSeconds ?? DEFAULT_KV_TTL_SECONDS;
  }

  /**
   * Load flags from KV if available, falling back to the API.
   * Should be called at worker startup inside the fetch handler.
   */
  async loadFromKvOrApi(): Promise<void> {
    if (this.kv && !this.kvLoaded) {
      const raw = await this.kv.get(KV_KEY);
      if (raw) {
        try {
          const data: BootstrapResponse = JSON.parse(raw);
          this.flags.clear();
          for (const flag of data.flags) {
            this.flags.set(flag.key, flag);
          }
          this.experiments.clear();
          for (const exp of data.experiments) {
            this.experiments.set(exp.key, exp);
          }
          this.kvLoaded = true;
          return;
        } catch {
          // Corrupt KV data — fall through to API
        }
      }
    }

    // KV miss or no KV configured: fetch from API
    await this.refreshFlags();
    this.kvLoaded = true;
  }

  /**
   * Fetch fresh flags from the API and persist to KV.
   * Safe to call from `ctx.waitUntil()` for background refresh.
   */
  async refreshAndStore(): Promise<void> {
    await this.refreshFlags();

    if (this.kv) {
      const payload: BootstrapResponse = {
        flags: Array.from(this.flags.values()),
        experiments: Array.from(this.experiments.values()),
        ttl_seconds: this.kvTtlSeconds,
        version: '',
      };
      await this.kv.put(KV_KEY, JSON.stringify(payload), {
        expirationTtl: this.kvTtlSeconds,
      });
    }
  }
}

// ---------------------------------------------------------------------------
// Convenience wrapper
// ---------------------------------------------------------------------------

/**
 * Wrap a Cloudflare fetch handler with automatic flag loading.
 *
 * The wrapped handler receives the client as `env.EP_CLIENT` (or the key
 * specified by `clientEnvKey`).
 *
 * @example
 * ```ts
 * export default withExperimentation(
 *   async (request, env, ctx) => {
 *     const client: CloudflareExperimentationClient = env.EP_CLIENT;
 *     const enabled = client.evaluateFlagSync('new-checkout', userId);
 *     ...
 *   },
 *   { apiKey: 'key', kvNamespace: env.FLAGS_KV }
 * );
 * ```
 */
export function withExperimentation(
  handler: (request: Request, env: Record<string, unknown>, ctx: ExecutionContext) => Promise<Response>,
  config: CloudflareConfig,
  clientEnvKey = 'EP_CLIENT',
): (request: Request, env: Record<string, unknown>, ctx: ExecutionContext) => Promise<Response> {
  return async function wrappedHandler(
    request: Request,
    env: Record<string, unknown>,
    ctx: ExecutionContext,
  ): Promise<Response> {
    const client = new CloudflareExperimentationClient({
      ...config,
      kvNamespace: config.kvNamespace ?? (env['KV'] as KVNamespace | undefined),
    });

    // Load flags (KV → API fallback), non-blocking for warm instances
    await client.loadFromKvOrApi();

    // Background refresh: update KV without blocking the response
    ctx.waitUntil(client.refreshAndStore());

    // Inject client into env for the handler
    const enrichedEnv = { ...env, [clientEnvKey]: client };

    return handler(request, enrichedEnv, ctx);
  };
}
