/**
 * Core types for the React Native Experimentation Platform SDK.
 */

/** Configuration for {@link ExperimentationClient}. */
export interface SdkConfig {
  /** API key for authenticating with the Experimentation Platform. */
  apiKey: string;
  /** Base URL, e.g. `'https://api.getexperimently.com'`. */
  baseUrl: string;
  /** HTTP request timeout in milliseconds. Defaults to 5000. */
  timeoutMs?: number;
  /**
   * TTL for the in-memory evaluation cache in milliseconds.
   * Defaults to 300_000 (5 minutes).
   */
  cacheTtlMs?: number;
  /**
   * When true, last-known values are persisted to AsyncStorage and served
   * as fallback when the API is unreachable.
   * Defaults to true.
   */
  offlineFallback?: boolean;
}

/** A feature flag returned by the Experimentation Platform API. */
export interface FeatureFlag {
  id: string;
  key: string;
  name: string;
  enabled: boolean;
  /** Rollout percentage (0–100). */
  rolloutPercentage: number;
  variants?: Array<{ key: string; weight: number; value?: unknown }>;
}

/** An experiment assignment response from the API. */
export interface ExperimentAssignment {
  experimentKey: string;
  variantKey: string | null;
  variantName: string | null;
}

/** Return type of {@link useFlag}. */
export interface FlagState {
  value: boolean;
  loading: boolean;
  error: Error | null;
}

/** Return type of {@link useExperiment}. */
export interface ExperimentState {
  variant: string | null;
  loading: boolean;
  error: Error | null;
}

/** Internal cache entry (in-memory). */
export interface CacheEntry<T> {
  value: T;
  expiresAt: number;
}
