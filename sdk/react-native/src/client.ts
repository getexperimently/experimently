/**
 * React Native Experimentation Platform client.
 *
 * Provides feature-flag evaluation, experiment assignment, and event tracking.
 * Results are cached in memory (configurable TTL) and optionally persisted to
 * AsyncStorage for offline fallback.
 *
 * @example
 * ```typescript
 * const client = new ExperimentationClient({
 *   apiKey: 'your-api-key',
 *   baseUrl: 'https://api.getexperimently.com',
 * });
 *
 * const enabled = await client.evaluateFlag('dark-mode', 'user-123');
 * const variant = await client.getAssignment('checkout-experiment', 'user-123');
 * await client.track('button_clicked', 'user-123', { page: 'home' });
 * ```
 */

import type { SdkConfig, FeatureFlag, ExperimentAssignment } from './types';
import { evaluateLocally } from './evaluator';
import { EvaluationCache } from './cache';
import { OfflineStorage } from './storage';

const DEFAULT_TIMEOUT_MS = 5_000;
const DEFAULT_CACHE_TTL_MS = 300_000; // 5 minutes

export class ExperimentationClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly offlineFallback: boolean;

  private readonly flagCache: EvaluationCache<boolean>;
  private readonly assignmentCache: EvaluationCache<string | null>;
  private readonly storage: OfflineStorage;

  constructor(
    config: SdkConfig,
    storage?: OfflineStorage
  ) {
    if (!config.apiKey) throw new Error('ExperimentationClient: apiKey is required');
    if (!config.baseUrl) throw new Error('ExperimentationClient: baseUrl is required');

    this.apiKey = config.apiKey;
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
    this.timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.offlineFallback = config.offlineFallback ?? true;

    const ttl = config.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
    this.flagCache = new EvaluationCache<boolean>(ttl);
    this.assignmentCache = new EvaluationCache<string | null>(ttl);
    this.storage = storage ?? new OfflineStorage();
  }

  /**
   * Evaluates whether `flagKey` is enabled for `userId`.
   *
   * Evaluation order:
   *   1. In-memory cache (fast path).
   *   2. API fetch → local evaluation via consistent hash.
   *   3. AsyncStorage offline fallback (if enabled).
   *   4. Returns `false` as safe default.
   */
  async evaluateFlag(
    flagKey: string,
    userId: string,
    attributes?: Record<string, unknown>
  ): Promise<boolean> {
    const cacheKey = `${userId}:${flagKey}`;

    // 1. In-memory cache
    const cached = this.flagCache.get(cacheKey);
    if (cached !== undefined) return cached;

    // 2. Network evaluation
    try {
      const flag = await this.fetchFlag(flagKey, userId, attributes);
      const enabled = evaluateLocally(flag, userId);

      this.flagCache.set(cacheKey, enabled);

      if (this.offlineFallback) {
        await this.storage.setFlag(cacheKey, enabled);
      }

      return enabled;
    } catch {
      // 3. Offline fallback
      if (this.offlineFallback) {
        const stored = await this.storage.getFlag(cacheKey);
        if (stored !== null) return stored ?? false;
      }
      return false;
    }
  }

  /**
   * Returns the variant key for `userId` in experiment `experimentKey`.
   *
   * Returns `null` if the user is not in the experiment or on error.
   */
  async getAssignment(
    experimentKey: string,
    userId: string,
    attributes?: Record<string, unknown>
  ): Promise<string | null> {
    const cacheKey = `${userId}:exp:${experimentKey}`;

    // 1. In-memory cache (null is a valid cached value)
    if (this.assignmentCache.has(cacheKey)) {
      return this.assignmentCache.get(cacheKey) ?? null;
    }

    // 2. Network call
    try {
      const assignment = await this.fetchAssignment(experimentKey, userId, attributes);

      this.assignmentCache.set(cacheKey, assignment.variantKey);

      if (this.offlineFallback) {
        await this.storage.setAssignment(cacheKey, assignment.variantKey);
      }

      return assignment.variantKey;
    } catch {
      // 3. Offline fallback
      if (this.offlineFallback) {
        const stored = await this.storage.getAssignment(cacheKey);
        if (stored !== undefined) return stored;
      }
      return null;
    }
  }

  /**
   * Sends a tracking event. Fire-and-forget: this method never throws.
   */
  async track(
    eventName: string,
    userId: string,
    properties?: Record<string, unknown>
  ): Promise<void> {
    try {
      await this.fetchWithTimeout(`${this.baseUrl}/api/v1/events`, {
        method: 'POST',
        headers: {
          'X-API-Key': this.apiKey,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          event_name: eventName,
          user_id: userId,
          ...(properties ? { properties } : {}),
        }),
      });
    } catch {
      // Fire-and-forget — intentionally swallow all errors.
    }
  }

  /** Clears the in-memory evaluation caches. */
  clearCache(): void {
    this.flagCache.clear();
    this.assignmentCache.clear();
  }

  // ---------------------------------------------------------------------------
  // Private helpers
  // ---------------------------------------------------------------------------

  private async fetchFlag(
    flagKey: string,
    userId: string,
    _attributes?: Record<string, unknown>
  ): Promise<FeatureFlag> {
    const url = `${this.baseUrl}/api/v1/feature-flags/${encodeURIComponent(flagKey)}/evaluate`;
    const res = await this.fetchWithTimeout(url, {
      headers: {
        'X-API-Key': this.apiKey,
        'X-User-ID': userId,
        'Content-Type': 'application/json',
      },
    });

    if (!res.ok) {
      throw new Error(`API error: ${res.status}`);
    }

    return res.json() as Promise<FeatureFlag>;
  }

  private async fetchAssignment(
    experimentKey: string,
    userId: string,
    _attributes?: Record<string, unknown>
  ): Promise<ExperimentAssignment> {
    const url = `${this.baseUrl}/api/v1/experiments/${encodeURIComponent(experimentKey)}/assign?user_id=${encodeURIComponent(userId)}`;
    const res = await this.fetchWithTimeout(url, {
      headers: {
        'X-API-Key': this.apiKey,
        'Content-Type': 'application/json',
      },
    });

    if (!res.ok) {
      throw new Error(`API error: ${res.status}`);
    }

    return res.json() as Promise<ExperimentAssignment>;
  }

  private fetchWithTimeout(url: string, init?: RequestInit): Promise<Response> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    return fetch(url, { ...init, signal: controller.signal }).finally(() =>
      clearTimeout(timer)
    );
  }
}
