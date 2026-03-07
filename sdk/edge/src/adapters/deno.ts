/**
 * Deno Deploy adapter for the Edge Experimentation SDK.
 *
 * Deno Deploy runs Deno-compatible JavaScript/TypeScript at the edge.
 * This adapter provides:
 *  - A `DenoExperimentationClient` that extends the base client
 *  - A `serve` helper that wraps Deno.serve() with automatic flag loading
 *  - KV-backed persistence using Deno KV (available in Deno Deploy)
 *
 * Deno KV layout:
 *   Key:   ["ep", "bootstrap"]
 *   Value: BootstrapResponse
 *   TTL:   configurable (default 300 seconds)
 *
 * Usage:
 * ```ts
 * import { createDenoHandler } from '@experimentation-platform/edge-sdk/deno';
 *
 * export default createDenoHandler(
 *   async (req, client) => {
 *     const userId = req.headers.get('X-User-Id') ?? 'anon';
 *     const enabled = client.evaluateFlagSync('new-feature', userId);
 *     return new Response(enabled ? 'new' : 'old');
 *   },
 *   { apiKey: Deno.env.get('EP_API_KEY')! }
 * );
 * ```
 */

import { EdgeExperimentationClient } from '../client';
import type { EdgeSdkConfig, BootstrapResponse } from '../types';

// ---------------------------------------------------------------------------
// Deno KV interface (minimal, compatible with Deno's built-in Deno.openKv)
// ---------------------------------------------------------------------------

export interface DenoKv {
  get<T>(key: string[]): Promise<{ value: T | null }>;
  set(key: string[], value: unknown, options?: { expireIn?: number }): Promise<unknown>;
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export interface DenoConfig extends EdgeSdkConfig {
  /**
   * Deno KV instance for flag persistence.
   * If provided, flags are cached in KV and shared across isolates.
   */
  kv?: DenoKv;
  /**
   * TTL for KV entries in milliseconds (Deno KV uses ms).
   * Defaults to 300_000 (5 minutes).
   */
  kvTtlMs?: number;
}

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

const KV_KEY = ['ep', 'bootstrap'];
const DEFAULT_KV_TTL_MS = 300_000; // 5 minutes

export class DenoExperimentationClient extends EdgeExperimentationClient {
  private readonly kv: DenoKv | undefined;
  private readonly kvTtlMs: number;

  constructor(config: DenoConfig) {
    super(config);
    this.kv = config.kv;
    this.kvTtlMs = config.kvTtlMs ?? DEFAULT_KV_TTL_MS;
  }

  /**
   * Load flags from Deno KV if available, falling back to the API.
   */
  async loadFromKvOrApi(): Promise<void> {
    if (this.kv) {
      const entry = await this.kv.get<BootstrapResponse>(KV_KEY);
      if (entry.value) {
        try {
          const data = entry.value;
          this.flags.clear();
          for (const flag of data.flags) {
            this.flags.set(flag.key, flag);
          }
          this.experiments.clear();
          for (const exp of data.experiments) {
            this.experiments.set(exp.key, exp);
          }
          return;
        } catch {
          // Corrupt KV entry — fall through to API
        }
      }
    }

    await this.refreshFlags();
  }

  /**
   * Fetch fresh flags from the API and persist to Deno KV.
   */
  async refreshAndStore(): Promise<void> {
    await this.refreshFlags();

    if (this.kv) {
      const payload: BootstrapResponse = {
        flags: Array.from(this.flags.values()),
        experiments: Array.from(this.experiments.values()),
        ttl_seconds: Math.floor(this.kvTtlMs / 1000),
        version: '',
      };
      await this.kv.set(KV_KEY, payload, { expireIn: this.kvTtlMs });
    }
  }
}

// ---------------------------------------------------------------------------
// Convenience factory for Deno.serve()
// ---------------------------------------------------------------------------

export type DenoHandler = (
  request: Request,
  client: DenoExperimentationClient,
) => Promise<Response>;

/**
 * Create a Deno.serve-compatible handler with automatic flag loading.
 *
 * The returned handler loads flags from KV (or API) once per isolate startup,
 * then passes the pre-warmed client to the inner handler.
 */
export function createDenoHandler(
  handler: DenoHandler,
  config: DenoConfig,
): (request: Request) => Promise<Response> {
  let client: DenoExperimentationClient | null = null;

  return async function denoHandler(request: Request): Promise<Response> {
    // Initialise the client once per isolate
    if (!client) {
      client = new DenoExperimentationClient(config);
      await client.loadFromKvOrApi();
    }

    return handler(request, client);
  };
}
