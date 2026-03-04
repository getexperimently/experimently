/**
 * OpenFeature Provider for the Experimentation Platform.
 *
 * Implements the @openfeature/server-sdk `Provider` interface, enabling any
 * application using the OpenFeature standard to evaluate feature flags and
 * A/B experiment variants from the Experimentation Platform without changing
 * application code.
 *
 * How it works:
 *   1. On initialize()  → fetches all flags from the platform API, builds
 *      an in-memory cache keyed by flag.key.
 *   2. On resolve*()   → evaluates the flag locally using the same MD5-based
 *      consistent hash algorithm used by the Go / Java / Python SDKs so that
 *      user assignments are identical across all clients.
 *   3. Cache TTL       → after `cacheTtlMs` milliseconds the next evaluation
 *      triggers a background refresh from the API.
 *   4. API errors      → the provider degrades gracefully: returns the
 *      caller-supplied defaultValue with reason=DEFAULT and an ErrorCode.
 */

import { createHash } from 'crypto';
import {
  Provider,
  ResolutionDetails,
  EvaluationContext,
  ProviderMetadata,
  Hook,
  JsonValue,
  ErrorCode,
  StandardResolutionReasons,
  Logger,
} from '@openfeature/server-sdk';
import {
  FeatureFlagDefinition,
  FlagVariant,
  FlagsResponse,
  CacheEntry,
  EvalReason,
} from './types';

export interface ExperimentationProviderOptions {
  /** API key used in the X-API-Key header. */
  apiKey: string;
  /** Base URL of the Experimentation Platform API. Defaults to http://localhost:8000. */
  baseUrl?: string;
  /** How long the flag cache is valid in milliseconds. Defaults to 300 000 (5 min). */
  cacheTtlMs?: number;
  /** HTTP request timeout in milliseconds. Defaults to 5 000 (5 s). */
  timeout?: number;
  /**
   * Optional fetch implementation. Allows injection of a mock fetch in tests.
   * Defaults to the global `fetch` available in Node 18+ / browsers.
   */
  fetch?: typeof fetch;
}

/**
 * ExperimentationProvider implements the OpenFeature Provider interface for
 * the Experimentation Platform. It performs local (client-side) flag evaluation
 * using a consistent MD5-based hash that is byte-for-byte compatible with the
 * Go, Java, and Python SDKs.
 */
export class ExperimentationProvider implements Provider {
  readonly metadata: ProviderMetadata = {
    name: 'experimentation-platform-provider',
  };

  hooks?: Hook[];

  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly cacheTtlMs: number;
  private readonly timeout: number;
  private readonly fetchImpl: typeof fetch;

  /** In-memory flag cache. */
  private cache: CacheEntry | null = null;
  /** Pending refresh promise to avoid thundering-herd on simultaneous misses. */
  private refreshPromise: Promise<void> | null = null;

  constructor(options: ExperimentationProviderOptions) {
    if (!options.apiKey) {
      throw new Error('ExperimentationProvider: apiKey is required');
    }
    this.apiKey = options.apiKey;
    this.baseUrl = (options.baseUrl ?? 'http://localhost:8000').replace(/\/$/, '');
    this.cacheTtlMs = options.cacheTtlMs ?? 300_000;
    this.timeout = options.timeout ?? 5_000;
    // Prefer injected fetch, fall back to global (Node 18+ / browser).
    this.fetchImpl = options.fetch ?? globalThis.fetch;
  }

  /**
   * Called by the OpenFeature SDK after the provider is registered.
   * Pre-warms the flag cache so the first evaluation is synchronous.
   */
  async initialize(_context?: EvaluationContext): Promise<void> {
    await this.refreshFlags();
  }

  /**
   * Called when the provider is replaced or the SDK shuts down.
   * Clears the in-memory cache to release references.
   */
  async onClose(): Promise<void> {
    this.cache = null;
    this.refreshPromise = null;
  }

  // ---------------------------------------------------------------------------
  // OpenFeature Provider interface methods
  // The @openfeature/server-sdk v1 interface uses *Evaluation (not *Value).
  // ---------------------------------------------------------------------------

  async resolveBooleanEvaluation(
    flagKey: string,
    defaultValue: boolean,
    context: EvaluationContext = {},
    _logger?: Logger,
  ): Promise<ResolutionDetails<boolean>> {
    const result = await this.evaluate(flagKey, context);
    if (result.reason === StandardResolutionReasons.DEFAULT || result.reason === StandardResolutionReasons.ERROR) {
      return this.defaultDetails(defaultValue, result.reason, result.errorCode, result.errorMessage);
    }
    // For boolean flags (no variants), the value is `enabled` (true/false).
    const value = typeof result.value === 'boolean' ? result.value : Boolean(result.value);
    return {
      value,
      reason: result.reason,
      variant: result.variant ?? undefined,
      flagMetadata: result.flagMetadata,
    };
  }

  async resolveStringEvaluation(
    flagKey: string,
    defaultValue: string,
    context: EvaluationContext = {},
    _logger?: Logger,
  ): Promise<ResolutionDetails<string>> {
    const result = await this.evaluate(flagKey, context);
    if (result.reason === StandardResolutionReasons.DEFAULT || result.reason === StandardResolutionReasons.ERROR) {
      return this.defaultDetails(defaultValue, result.reason, result.errorCode, result.errorMessage);
    }
    if (typeof result.value !== 'string') {
      return {
        value: defaultValue,
        reason: StandardResolutionReasons.ERROR,
        errorCode: ErrorCode.TYPE_MISMATCH,
        errorMessage: `Flag "${flagKey}" value is not a string`,
        flagMetadata: result.flagMetadata,
      };
    }
    return {
      value: result.value,
      reason: result.reason,
      variant: result.variant ?? undefined,
      flagMetadata: result.flagMetadata,
    };
  }

  async resolveNumberEvaluation(
    flagKey: string,
    defaultValue: number,
    context: EvaluationContext = {},
    _logger?: Logger,
  ): Promise<ResolutionDetails<number>> {
    const result = await this.evaluate(flagKey, context);
    if (result.reason === StandardResolutionReasons.DEFAULT || result.reason === StandardResolutionReasons.ERROR) {
      return this.defaultDetails(defaultValue, result.reason, result.errorCode, result.errorMessage);
    }
    if (typeof result.value !== 'number') {
      return {
        value: defaultValue,
        reason: StandardResolutionReasons.ERROR,
        errorCode: ErrorCode.TYPE_MISMATCH,
        errorMessage: `Flag "${flagKey}" value is not a number`,
        flagMetadata: result.flagMetadata,
      };
    }
    return {
      value: result.value,
      reason: result.reason,
      variant: result.variant ?? undefined,
      flagMetadata: result.flagMetadata,
    };
  }

  async resolveObjectEvaluation<T extends JsonValue>(
    flagKey: string,
    defaultValue: T,
    context: EvaluationContext = {},
    _logger?: Logger,
  ): Promise<ResolutionDetails<T>> {
    const result = await this.evaluate(flagKey, context);
    if (result.reason === StandardResolutionReasons.DEFAULT || result.reason === StandardResolutionReasons.ERROR) {
      return this.defaultDetails(defaultValue, result.reason, result.errorCode, result.errorMessage);
    }
    if (result.value === null || typeof result.value !== 'object') {
      return {
        value: defaultValue,
        reason: StandardResolutionReasons.ERROR,
        errorCode: ErrorCode.TYPE_MISMATCH,
        errorMessage: `Flag "${flagKey}" value is not an object`,
        flagMetadata: result.flagMetadata,
      };
    }
    return {
      value: result.value as T,
      reason: result.reason,
      variant: result.variant ?? undefined,
      flagMetadata: result.flagMetadata,
    };
  }

  // ---------------------------------------------------------------------------
  // Internal evaluation
  // ---------------------------------------------------------------------------

  /** Internal evaluation result (richer than ResolutionDetails). */
  private async evaluate(
    flagKey: string,
    context?: EvaluationContext,
  ): Promise<{
    value: unknown;
    variant: string | null;
    reason: string;
    errorCode?: ErrorCode;
    errorMessage?: string;
    flagMetadata?: Record<string, string | number | boolean>;
  }> {
    // Ensure we have a warm cache; refresh if TTL expired.
    await this.ensureFreshCache();

    const flag = this.cache?.flags.get(flagKey);
    if (!flag) {
      return {
        value: undefined,
        variant: null,
        reason: StandardResolutionReasons.DEFAULT,
        errorCode: ErrorCode.FLAG_NOT_FOUND,
        errorMessage: `Flag "${flagKey}" not found`,
      };
    }

    const userId = context?.targetingKey ?? '';
    const cacheWarm = this.isCacheWarm();
    const evalResult = this.evaluateLocally(flag, userId);

    return {
      value: evalResult.value,
      variant: evalResult.variant,
      reason: cacheWarm ? StandardResolutionReasons.CACHED : StandardResolutionReasons.STATIC,
      flagMetadata: {
        flagKey: flag.key,
        enabled: flag.enabled,
        rolloutPercentage: flag.rollout_percentage,
      },
    };
  }

  /**
   * Evaluates a flag locally using the consistent MD5 hash algorithm.
   *
   * Algorithm (matches Go / Java / Python SDKs byte-for-byte):
   *   1. Concatenate userId + ":" + flagKey as UTF-8.
   *   2. Compute MD5 digest.
   *   3. Read first 4 bytes as a little-endian uint32.
   *   4. Divide by 2^32 (4294967296) → float in [0.0, 1.0).
   */
  private evaluateLocally(
    flag: FeatureFlagDefinition,
    userId: string,
  ): { value: unknown; variant: string | null } {
    if (!flag.enabled) {
      return { value: false, variant: null };
    }

    const hash = this.hashUser(userId, flag.key);
    const rolloutFraction = flag.rollout_percentage / 100.0;

    if (hash >= rolloutFraction) {
      return { value: false, variant: null };
    }

    if (flag.variants && flag.variants.length > 0) {
      const variantResult = this.assignVariant(flag.variants, hash, rolloutFraction);
      return variantResult;
    }

    return { value: true, variant: null };
  }

  /**
   * Assigns a variant proportionally within the rollout band.
   * Re-scales hash from [0, rolloutFraction) → [0.0, 1.0) before selecting.
   */
  private assignVariant(
    variants: FlagVariant[],
    hash: number,
    rolloutFraction: number,
  ): { value: unknown; variant: string } {
    const variantHash = rolloutFraction > 0 ? hash / rolloutFraction : 0;
    let cumulative = 0;
    for (const v of variants) {
      cumulative += v.weight;
      if (variantHash < cumulative) {
        return { value: v.value ?? v.key, variant: v.key };
      }
    }
    // Fallback to last variant (floating-point edge case).
    const last = variants[variants.length - 1];
    return { value: last.value ?? last.key, variant: last.key };
  }

  /**
   * Computes a float in [0.0, 1.0) for the (userId, flagKey) pair using MD5.
   * This is byte-for-byte compatible with the Go, Java, and Python SDKs.
   *
   * Hash test vectors (for cross-SDK verification):
   *   hashUser("user-123", "my-flag")  → ~0.2358 (first 4 LE bytes of MD5)
   *   hashUser("",         "my-flag")  → hash of ":my-flag"
   */
  hashUser(userId: string, flagKey: string): number {
    const input = `${userId}:${flagKey}`;
    const digest = createHash('md5').update(input, 'utf8').digest();
    // Read first 4 bytes as little-endian unsigned 32-bit integer.
    const uint32 = digest.readUInt32LE(0);
    // Divide by 2^32 = 4294967296 to normalize to [0.0, 1.0).
    return uint32 / 4294967296;
  }

  // ---------------------------------------------------------------------------
  // Cache management
  // ---------------------------------------------------------------------------

  private isCacheWarm(): boolean {
    if (!this.cache) return false;
    return Date.now() - this.cache.fetchedAt < this.cacheTtlMs;
  }

  private async ensureFreshCache(): Promise<void> {
    if (this.isCacheWarm()) return;

    // Coalesce concurrent misses into a single refresh.
    if (!this.refreshPromise) {
      this.refreshPromise = this.refreshFlags()
        .catch((_err) => {
          // Refresh failed — continue with stale/empty cache and return DEFAULT
          // for any flag lookup. This allows graceful degradation.
        })
        .finally(() => {
          this.refreshPromise = null;
        });
    }
    await this.refreshPromise;
  }

  /** Fetches all flags from the platform API and populates the local cache. */
  async refreshFlags(): Promise<void> {
    const url = `${this.baseUrl}/api/v1/openfeature/flags`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await this.fetchImpl(url, {
        method: 'GET',
        headers: {
          'X-API-Key': this.apiKey,
          'Content-Type': 'application/json',
        },
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = (await response.json()) as FlagsResponse;
      const flagMap = new Map<string, FeatureFlagDefinition>();
      for (const flag of data.flags) {
        flagMap.set(flag.key, flag);
      }

      this.cache = {
        flags: flagMap,
        fetchedAt: Date.now(),
      };
    } finally {
      clearTimeout(timer);
    }
  }

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------

  private defaultDetails<T>(
    value: T,
    reason: string,
    errorCode?: ErrorCode,
    errorMessage?: string,
  ): ResolutionDetails<T> {
    return {
      value,
      reason,
      errorCode,
      errorMessage,
    };
  }
}
