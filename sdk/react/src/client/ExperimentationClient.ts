import { SdkConfig, FeatureFlag, UserContext } from './types';

interface CacheEntry {
  value: string;
  expiresAt: number;
}

export class ExperimentationClient {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly cache = new Map<string, CacheEntry>();
  private readonly cacheTtlMs: number;

  constructor(config: SdkConfig) {
    if (!config.apiKey) throw new Error('apiKey is required');
    if (!config.baseUrl) throw new Error('baseUrl is required');
    this.apiKey = config.apiKey;
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
    this.timeoutMs = config.timeoutMs ?? 5000;
    this.cacheTtlMs = config.cacheTtlMs ?? 300_000;
  }

  private getCached(key: string): string | null {
    const entry = this.cache.get(key);
    if (!entry) return null;
    if (Date.now() > entry.expiresAt) {
      this.cache.delete(key);
      return null;
    }
    return entry.value;
  }

  private setCached(key: string, value: string): void {
    this.cache.set(key, { value, expiresAt: Date.now() + this.cacheTtlMs });
  }

  async evaluateFeatureFlag(user: UserContext, flagKey: string): Promise<string | null> {
    const cacheKey = `${user.userId}:${flagKey}`;
    const cached = this.getCached(cacheKey);
    if (cached !== null) return cached === 'off' ? null : cached;

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
        throw new Error(`API error: ${response.status}`);
      }

      const flag: FeatureFlag = await response.json();
      const variant = this.evaluateLocally(user, flag);
      this.setCached(cacheKey, variant ?? 'off');
      return variant;
    } finally {
      clearTimeout(timeout);
    }
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
    // Simple hash for browser bucketing (not crypto-grade).
    // Use server-side evaluation for security-critical decisions.
    const str = `${userId}:${flagKey}`;
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      const char = str.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; // Convert to 32-bit int
    }
    return Math.abs(hash) / 0x7fffffff;
  }

  async trackEvent(
    userId: string,
    eventName: string,
    properties?: Record<string, unknown>
  ): Promise<void> {
    try {
      await fetch(`${this.baseUrl}/api/v1/events`, {
        method: 'POST',
        headers: {
          'X-API-Key': this.apiKey,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ user_id: userId, event_name: eventName, properties }),
      });
    } catch {
      // fire-and-forget: never throw
    }
  }

  clearCache(): void {
    this.cache.clear();
  }
}
