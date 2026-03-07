/**
 * EdgeExperimentationClient — the main client for edge environments.
 *
 * Design goals:
 *  - Zero Node.js built-ins (no `fs`, no `crypto` module, no `Buffer`)
 *  - Works in Cloudflare Workers, Vercel Edge Functions, Deno Deploy, and any
 *    WinterCG-compatible runtime
 *  - Sub-millisecond evaluation using bootstrap flags (pre-loaded from KV / env)
 *  - Async evaluation with caching for flags not in bootstrap set
 *  - AbortController-based timeouts (Web standard, supported everywhere)
 */

import { EdgeCache } from './cache';
import { evaluateFlag, assignVariant } from './evaluator';
import type { EdgeSdkConfig, FeatureFlag, BootstrapResponse, Experiment } from './types';

const DEFAULT_BASE_URL = 'https://api.experimentationplatform.io';
const DEFAULT_CACHE_TTL_MS = 60_000; // 1 minute
const DEFAULT_TIMEOUT_MS = 500;      // 500ms — edge functions must be fast

export class EdgeExperimentationClient {
  protected readonly apiKey: string;
  protected readonly baseUrl: string;
  protected readonly cacheTtlMs: number;
  protected readonly timeout: number;

  /** In-memory flag definitions (keyed by flag.key) */
  protected flags: Map<string, FeatureFlag>;
  /** In-memory experiment definitions (keyed by experiment.key) */
  protected experiments: Map<string, Experiment>;

  /** Per-user evaluation result cache (keyed by "userId:flagKey") */
  private readonly evalCache: EdgeCache<boolean>;
  /** Per-user assignment cache (keyed by "userId:experimentKey") */
  private readonly assignmentCache: EdgeCache<string | null>;
  /** Cache for dynamically-fetched flag definitions (TTL-bounded, not bootstrap) */
  private readonly fetchedFlagCache: EdgeCache<FeatureFlag>;
  /** Tracks whether a full bootstrap has been fetched */
  private bootstrapLoaded: boolean;

  constructor(config: EdgeSdkConfig) {
    if (!config.apiKey) throw new Error('apiKey is required');

    this.apiKey = config.apiKey;
    this.baseUrl = (config.baseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, '');
    this.cacheTtlMs = config.cacheTtlMs ?? DEFAULT_CACHE_TTL_MS;
    this.timeout = config.timeout ?? DEFAULT_TIMEOUT_MS;

    this.evalCache = new EdgeCache<boolean>(this.cacheTtlMs);
    this.assignmentCache = new EdgeCache<string | null>(this.cacheTtlMs);
    this.fetchedFlagCache = new EdgeCache<FeatureFlag>(this.cacheTtlMs);

    this.flags = new Map();
    this.experiments = new Map();
    this.bootstrapLoaded = false;

    // Pre-load bootstrap flags provided at construction time
    if (config.bootstrapFlags && config.bootstrapFlags.length > 0) {
      for (const flag of config.bootstrapFlags) {
        this.flags.set(flag.key, flag);
      }
      this.bootstrapLoaded = true;
    }
  }

  // ---------------------------------------------------------------------------
  // Synchronous evaluation (zero latency — uses bootstrap flags only)
  // ---------------------------------------------------------------------------

  /**
   * Evaluate a feature flag synchronously using pre-loaded bootstrap flags.
   * Returns `false` when the flag is not in the bootstrap set.
   *
   * Use this in the critical path of edge request handling.
   */
  evaluateFlagSync(
    flagKey: string,
    userId: string,
    attributes: Record<string, unknown> = {},
  ): boolean {
    const flag = this.flags.get(flagKey);
    if (!flag) return false;
    return evaluateFlag(flag, userId, attributes);
  }

  /**
   * Get the variant assignment for an experiment synchronously using
   * pre-loaded bootstrap data.
   * Returns `null` when the experiment is not in the bootstrap set or the
   * user is outside the rollout band.
   */
  getAssignmentSync(experimentKey: string, userId: string): string | null {
    // Experiments are treated as feature flags with variants for bucketing
    const experiment = this.experiments.get(experimentKey);
    if (!experiment || !experiment.enabled) return null;

    // Build a synthetic FeatureFlag for the variant assignment logic
    const syntheticFlag: FeatureFlag = {
      key: experimentKey,
      enabled: experiment.enabled,
      rolloutPercentage: 100,
      variants: experiment.variants.map((v) => ({ key: v.key, weight: v.weight })),
    };

    return assignVariant(syntheticFlag, userId);
  }

  // ---------------------------------------------------------------------------
  // Async evaluation (fetches from API on cache miss)
  // ---------------------------------------------------------------------------

  /**
   * Evaluate a feature flag asynchronously.
   * Returns the cached result if available; otherwise fetches the flag
   * definition from the API, caches it, and evaluates locally.
   */
  async evaluateFlag(
    flagKey: string,
    userId: string,
    attributes: Record<string, unknown> = {},
  ): Promise<boolean> {
    const cacheKey = `${userId}:${flagKey}`;
    const cached = this.evalCache.get(cacheKey);
    if (cached !== undefined) return cached;

    // Try bootstrap flags first (zero network — bootstrap flags never expire)
    const bootstrapFlag = this.flags.get(flagKey);
    if (bootstrapFlag) {
      const result = evaluateFlag(bootstrapFlag, userId, attributes);
      this.evalCache.set(cacheKey, result);
      return result;
    }

    // Check TTL-bounded cache for previously-fetched flag definitions
    const cachedFlag = this.fetchedFlagCache.get(flagKey);
    if (cachedFlag) {
      const result = evaluateFlag(cachedFlag, userId, attributes);
      this.evalCache.set(cacheKey, result);
      return result;
    }

    // Fetch single flag from API
    const flag = await this._fetchFlag(flagKey);
    if (!flag) {
      this.evalCache.set(cacheKey, false);
      return false;
    }

    // Cache the flag definition with TTL (expires when cacheTtlMs elapses)
    this.fetchedFlagCache.set(flagKey, flag);
    const result = evaluateFlag(flag, userId, attributes);
    this.evalCache.set(cacheKey, result);
    return result;
  }

  /**
   * Get the variant assignment for an experiment asynchronously.
   * Fetches experiment data on cache miss.
   */
  async getAssignment(experimentKey: string, userId: string): Promise<string | null> {
    const cacheKey = `${userId}:${experimentKey}`;
    const cached = this.assignmentCache.get(cacheKey);
    if (cached !== undefined) return cached;

    // Try bootstrap data first
    const syncResult = this.getAssignmentSync(experimentKey, userId);
    if (this.experiments.has(experimentKey)) {
      this.assignmentCache.set(cacheKey, syncResult);
      return syncResult;
    }

    // Fetch bootstrap to get experiments (single API call returns everything)
    await this.refreshFlags();
    const result = this.getAssignmentSync(experimentKey, userId);
    this.assignmentCache.set(cacheKey, result);
    return result;
  }

  /**
   * Send a tracking event to the platform.
   * Fire-and-forget: errors are swallowed so they never affect the critical path.
   */
  async track(
    eventName: string,
    userId: string,
    properties: Record<string, unknown> = {},
  ): Promise<void> {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), this.timeout);
      try {
        await fetch(`${this.baseUrl}/api/v1/events`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-API-Key': this.apiKey,
          },
          body: JSON.stringify({ event_name: eventName, user_id: userId, properties }),
          signal: controller.signal,
        });
      } finally {
        clearTimeout(timer);
      }
    } catch {
      // fire-and-forget — never throw
    }
  }

  /**
   * Fetch all flags and experiments from the edge bootstrap endpoint.
   * Call this at edge worker startup to warm the in-memory cache.
   */
  async refreshFlags(): Promise<void> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(`${this.baseUrl}/api/v1/edge/bootstrap`, {
        headers: {
          'X-API-Key': this.apiKey,
          'Accept': 'application/json',
        },
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Bootstrap failed: ${response.status} ${response.statusText}`);
      }

      const data: BootstrapResponse = await response.json();

      // Replace flag and experiment maps
      this.flags.clear();
      for (const flag of data.flags) {
        this.flags.set(flag.key, flag);
      }

      this.experiments.clear();
      for (const exp of data.experiments) {
        this.experiments.set(exp.key, exp);
      }

      this.bootstrapLoaded = true;
    } finally {
      clearTimeout(timer);
    }
  }

  // ---------------------------------------------------------------------------
  // Internal helpers
  // ---------------------------------------------------------------------------

  /**
   * Fetch a single flag definition from the API.
   * Returns `null` on error (404, network failure, timeout).
   */
  private async _fetchFlag(flagKey: string): Promise<FeatureFlag | null> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);

    try {
      const response = await fetch(
        `${this.baseUrl}/api/v1/feature-flags/${encodeURIComponent(flagKey)}`,
        {
          headers: {
            'X-API-Key': this.apiKey,
            'Accept': 'application/json',
          },
          signal: controller.signal,
        },
      );

      if (!response.ok) return null;

      const data = await response.json();
      // Normalize API response to our FeatureFlag type
      return {
        key: data.key,
        enabled: data.enabled ?? false,
        rolloutPercentage: data.rollout_percentage ?? data.rolloutPercentage ?? 0,
        variants: data.variants ?? [],
        rules: data.targeting_rules ?? data.rules ?? [],
      };
    } catch {
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  /**
   * Expose flag count (used in tests / adapters for introspection).
   */
  get flagCount(): number {
    return this.flags.size;
  }

  /**
   * Expose experiment count.
   */
  get experimentCount(): number {
    return this.experiments.size;
  }

  /**
   * Whether bootstrap flags have been loaded.
   */
  get isBootstrapped(): boolean {
    return this.bootstrapLoaded;
  }
}
