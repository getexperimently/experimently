export interface SdkConfig {
  apiKey: string;
  baseUrl: string;
  /** Per-request timeout (default 5000 ms). */
  timeoutMs?: number;
  /** TTL for the per-user flag/assignment caches (default 300 000 ms). */
  cacheTtlMs?: number;
}

export interface UserContext {
  userId: string;
  attributes?: Record<string, unknown>;
}

/**
 * Result of evaluating a feature flag for a user.
 *
 * `variant` is derived from the server response: `null` when the flag is off,
 * otherwise `config.variant` when that is a string, else `'on'`.
 */
export interface FeatureFlagEvaluation {
  flagKey: string;
  variant: string | null; // null = off
  isEnabled: boolean;
  config: unknown | null;
  loading: boolean;
  error: Error | null;
}

/**
 * Result of assigning a user to an experiment variant.
 *
 * While loading or on error the defaults are
 * `variantKey: 'control', variantName: 'Control', variantId: null, isControl: true, configuration: null`.
 */
export interface ExperimentAssignment {
  experimentKey: string;
  variantKey: string;
  variantName: string;
  variantId: string | null;
  isControl: boolean;
  configuration: Record<string, unknown> | null;
  loading: boolean;
  error: Error | null;
}

export interface TrackEventOptions {
  /** Attach the event to this experiment (sends `experiment_key`). */
  experimentKey?: string;
  /** Attach the event to this feature flag (sends `feature_flag_key`). */
  featureFlagKey?: string;
  /** Numeric value, e.g. an order total. */
  value?: number;
  /** Server `event_type`; defaults to the event name. */
  eventType?: string;
  /** Client-side timestamp; sent as an ISO-8601 string. */
  timestamp?: Date;
}

// ─── Raw backend response shapes (see backend/app/schemas/tracking.py) ──────

/** `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…` */
export interface FeatureFlagEvaluateResponse {
  key: string;
  enabled: boolean;
  config: unknown | null;
}

/** `POST /api/v1/tracking/assign` */
export interface ExperimentAssignResponse {
  experiment_key: string;
  user_id: string;
  variant_id: string;
  variant_name: string;
  is_control?: boolean;
  configuration?: Record<string, unknown> | null;
}
