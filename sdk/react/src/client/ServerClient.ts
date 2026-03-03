import { SdkConfig, FeatureFlag, UserContext, FeatureFlagEvaluation } from './types';

/**
 * SSR/Node.js client for evaluating feature flags server-side.
 *
 * Unlike ExperimentationClient, this class:
 * - Does not use any browser-specific APIs (localStorage, document, window)
 * - Uses a simple per-instance in-memory Map cache (appropriate for request-scoped use)
 * - Always returns FeatureFlagEvaluation (never throws) for safe SSR rendering
 * - Accepts flags as (flagKey, user) to match server-side idioms
 */

interface ServerCacheEntry {
  evaluation: FeatureFlagEvaluation;
  expiresAt: number;
}

export class ServerClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly cacheTtlMs: number;
  private readonly cache = new Map<string, ServerCacheEntry>();

  constructor(config: SdkConfig) {
    if (!config.apiKey) throw new Error('apiKey is required');
    if (!config.baseUrl) throw new Error('baseUrl is required');
    this.apiKey = config.apiKey;
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
    this.timeoutMs = config.timeoutMs ?? 5000;
    this.cacheTtlMs = config.cacheTtlMs ?? 300_000;
  }

  private getCached(cacheKey: string): FeatureFlagEvaluation | null {
    const entry = this.cache.get(cacheKey);
    if (!entry) return null;
    if (Date.now() > entry.expiresAt) {
      this.cache.delete(cacheKey);
      return null;
    }
    return entry.evaluation;
  }

  private setCached(cacheKey: string, evaluation: FeatureFlagEvaluation): void {
    this.cache.set(cacheKey, {
      evaluation,
      expiresAt: Date.now() + this.cacheTtlMs,
    });
  }

  private makeDisabledEvaluation(flagKey: string, error: Error | null = null): FeatureFlagEvaluation {
    return {
      flagKey,
      variant: null,
      isEnabled: false,
      loading: false,
      error,
    };
  }

  /**
   * Evaluate a feature flag for the given user in a Node.js/SSR context.
   * Never throws — returns a disabled evaluation with an error field on failure.
   */
  async evaluateFeatureFlag(flagKey: string, user: UserContext): Promise<FeatureFlagEvaluation> {
    const cacheKey = `${user.userId}:${flagKey}`;
    const cached = this.getCached(cacheKey);
    if (cached !== null) return cached;

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(
        `${this.baseUrl}/api/v1/feature-flags/${encodeURIComponent(flagKey)}/evaluate`,
        {
          headers: {
            'X-API-Key': this.apiKey,
            'X-User-ID': user.userId,
            'Content-Type': 'application/json',
          },
          signal: controller.signal,
        }
      );

      if (!response.ok) {
        const err = new Error(`API error: ${response.status}`);
        const evaluation = this.makeDisabledEvaluation(flagKey, err);
        this.setCached(cacheKey, evaluation);
        return evaluation;
      }

      const flag: FeatureFlag = await response.json();
      const variant = this.evaluateLocally(user, flag);
      const evaluation: FeatureFlagEvaluation = {
        flagKey,
        variant,
        isEnabled: variant !== null,
        loading: false,
        error: null,
      };
      this.setCached(cacheKey, evaluation);
      return evaluation;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      const evaluation = this.makeDisabledEvaluation(flagKey, error);
      // Do not cache errors — allow retry on next request
      return evaluation;
    } finally {
      clearTimeout(timeout);
    }
  }

  /**
   * Evaluate multiple feature flags in parallel for the given user.
   * Returns a map of flagKey -> FeatureFlagEvaluation.
   */
  async getAll(flagKeys: string[], user: UserContext): Promise<Record<string, FeatureFlagEvaluation>> {
    if (flagKeys.length === 0) return {};

    const results = await Promise.all(
      flagKeys.map(key => this.evaluateFeatureFlag(key, user))
    );

    return Object.fromEntries(flagKeys.map((key, i) => [key, results[i]]));
  }

  private evaluateLocally(user: UserContext, flag: FeatureFlag): string | null {
    if (!flag.enabled) return null;
    const hash = this.computeHash(user.userId, flag.key);
    const rollout = flag.rolloutPercentage / 100;
    if (hash >= rollout) return null;
    if (!flag.variants || flag.variants.length === 0) return 'on';
    const variantHash = hash / rollout;
    let cumulative = 0;
    for (const variant of flag.variants) {
      cumulative += variant.weight;
      if (variantHash < cumulative) return variant.name;
    }
    return flag.variants[flag.variants.length - 1].name;
  }

  private computeHash(userId: string, flagKey: string): number {
    const str = `${userId}:${flagKey}`;
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; // Convert to 32-bit int
    }
    return Math.abs(hash) / 0x7fffffff;
  }

  clearCache(): void {
    this.cache.clear();
  }
}
