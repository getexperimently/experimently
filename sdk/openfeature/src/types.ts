/**
 * Internal types for the Experimentation Platform OpenFeature Provider.
 */

/** A single variant within a feature flag. */
export interface FlagVariant {
  /** Variant identifier (e.g., "control", "treatment"). */
  key: string;
  /** Fractional weight in [0.0, 1.0]; all variants within a flag sum to 1.0. */
  weight: number;
  /** Arbitrary value associated with this variant. */
  value?: unknown;
}

/** A targeting rule that must be satisfied for a user to receive the flag. */
export interface TargetingRule {
  attribute: string;
  operator: string;
  value: unknown;
}

/** Feature flag definition as returned by the platform API. */
export interface FeatureFlagDefinition {
  /** Unique flag key. */
  key: string;
  /** Whether the flag is enabled at all. */
  enabled: boolean;
  /** Percentage of traffic exposed to this flag (0–100). */
  rollout_percentage: number;
  /** Variants; empty list means the flag is a simple boolean on/off. */
  variants?: FlagVariant[];
  /** Targeting rules (AND-combined). */
  rules?: TargetingRule[];
}

/** Response envelope from GET /api/v1/openfeature/flags */
export interface FlagsResponse {
  flags: FeatureFlagDefinition[];
}

/** Response envelope from POST /api/v1/openfeature/evaluate */
export interface EvaluateResponse {
  value: unknown;
  variant: string | null;
  reason: string;
}

/** Internal result of local flag evaluation. */
export interface LocalEvalResult {
  /** Resolved value (boolean, string, number, or object). */
  value: unknown;
  /** Variant key (null for boolean on/off flags). */
  variant: string | null;
  /** Evaluation reason code. */
  reason: EvalReason;
  /** Whether the flag was found in the local cache. */
  fromCache: boolean;
}

/** Supported evaluation reason codes. */
export type EvalReason = 'CACHED' | 'STATIC' | 'DEFAULT' | 'ERROR' | 'TARGETING_MATCH';

/** Cache entry for resolved flags. */
export interface CacheEntry {
  flags: Map<string, FeatureFlagDefinition>;
  fetchedAt: number;
}
