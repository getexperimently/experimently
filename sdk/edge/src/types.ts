/**
 * Type definitions for the Edge SDK.
 *
 * Designed to be compatible with the platform's existing TypeScript SDKs
 * (React SDK, JS SDK) while adding edge-specific configuration options.
 */

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export interface EdgeSdkConfig {
  /** API key for the experimentation platform. Required. */
  apiKey: string;
  /** Base URL of the experimentation platform backend. Defaults to the production URL. */
  baseUrl?: string;
  /** Cache TTL in milliseconds. Defaults to 60_000 (1 minute). Edge functions have short lifetimes. */
  cacheTtlMs?: number;
  /** Feature flags pre-loaded at edge startup (e.g. from KV or environment variables). */
  bootstrapFlags?: FeatureFlag[];
  /** Request timeout in milliseconds. Defaults to 500ms. Edge functions must be fast. */
  timeout?: number;
}

// ---------------------------------------------------------------------------
// Feature Flags
// ---------------------------------------------------------------------------

export interface TargetingRule {
  attribute: string;
  operator: string;
  value: unknown;
  /** Optional percentage to roll out to users matching this rule (0-100). */
  rolloutPercentage?: number;
}

export interface FlagVariant {
  key: string;
  weight: number;
  value?: unknown;
}

export interface FeatureFlag {
  key: string;
  enabled: boolean;
  rolloutPercentage: number;
  variants?: FlagVariant[];
  rules?: TargetingRule[];
}

// ---------------------------------------------------------------------------
// Experiments
// ---------------------------------------------------------------------------

export interface ExperimentVariant {
  key: string;
  name: string;
  weight: number;
}

export interface Experiment {
  key: string;
  enabled: boolean;
  variants: ExperimentVariant[];
}

// ---------------------------------------------------------------------------
// Bootstrap response (GET /api/v1/edge/bootstrap)
// ---------------------------------------------------------------------------

export interface BootstrapResponse {
  flags: FeatureFlag[];
  experiments: Experiment[];
  /** Cache TTL the server recommends, in seconds. */
  ttl_seconds: number;
  /** SHA-256 hash of the payload for cache invalidation comparisons. */
  version: string;
}

// ---------------------------------------------------------------------------
// Assignment / Evaluation results
// ---------------------------------------------------------------------------

export interface EvalResult {
  enabled: boolean;
  reason: string;
  variantKey?: string;
  value?: unknown;
}

// ---------------------------------------------------------------------------
// Cache entry (internal)
// ---------------------------------------------------------------------------

export interface CacheEntry<T> {
  value: T;
  expiresAt: number;
}
