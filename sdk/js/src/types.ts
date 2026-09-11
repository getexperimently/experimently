import type { ExperimentationError } from './errors';

/** Operations whose failures are swallowed and reported through `onError`. */
export type SwallowedOperation = 'track' | 'trackBatch';

export interface ClientConfig {
  /** Backend origin, e.g. `https://api.example.com`. The SDK appends `/api/v1/...`. */
  apiUrl: string;
  /** API key sent as `X-API-Key`. */
  apiKey: string;
  /** Per-request timeout in milliseconds (default 5000). */
  timeoutMs?: number;
  /** How long a successful evaluation/assignment is reused, per user + key (default 300 000 ms). */
  cacheTtlMs?: number;
  /** Variant name returned by `getVariant` when assignment fails (default `'control'`). */
  defaultVariant?: string;
  /** Custom `fetch` implementation. Defaults to the global `fetch` (Node >= 18, browsers). */
  fetch?: typeof fetch;
  /**
   * Called with the error whenever `track` / `trackBatch` swallow a failure.
   * Those methods never reject; this is the only way to observe their failures.
   */
  onError?: (error: ExperimentationError, operation: SwallowedOperation) => void;
}

export interface UserContext {
  /** Stable identifier used by the server for sticky bucketing. */
  userId: string;
  /** Sent as `context` on experiment assignment (targeting rules). Not sent for flag evaluation. */
  attributes?: Record<string, unknown>;
}

/** Result of `POST /api/v1/tracking/assign`, mapped to camelCase. */
export interface Assignment {
  experimentKey: string;
  userId: string;
  variantId: string | null;
  variantName: string;
  isControl: boolean;
  configuration: Record<string, unknown> | null;
}

/** Result of `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…`. */
export interface FlagEvaluation {
  key: string;
  enabled: boolean;
  config: unknown | null;
}

export interface TrackOptions {
  /** Numeric value, e.g. an order total. */
  value?: number;
  /** Arbitrary event properties; sent as `metadata`. */
  properties?: Record<string, unknown>;
  /** Attach the event to this experiment (sends `experiment_key`). */
  experimentKey?: string;
  /** Attach the event to this feature flag (sends `feature_flag_key`). */
  featureFlagKey?: string;
  /** Server `event_type`; defaults to the event name. */
  eventType?: string;
  /** Client-side timestamp; sent as an ISO-8601 string. */
  timestamp?: Date | string;
}

/** One entry for `trackBatch`. */
export interface TrackEvent extends TrackOptions {
  userId: string;
  eventName: string;
}

/** Aggregated result of `trackBatch` across all chunks. */
export interface BatchResult {
  successCount: number;
  failureCount: number;
  /** Server-reported per-event errors plus one `{message, status?}` entry per failed chunk. */
  errors: unknown[];
}

/** One row of `GET /api/v1/tracking/assignments/{user_id}` (shape defined by the server). */
export type AssignmentRecord = Record<string, unknown>;

// ─── Raw backend response shapes (see backend/app/schemas/tracking.py) ──────

/** `POST /api/v1/tracking/assign` */
export interface AssignResponse {
  experiment_key: string;
  user_id: string;
  variant_id?: string | null;
  variant_name: string;
  is_control?: boolean;
  configuration?: Record<string, unknown> | null;
}

/** `GET /api/v1/feature-flags/evaluate/{flag_key}?user_id=…` */
export interface FlagEvaluateResponse {
  key: string;
  enabled: boolean;
  config?: unknown | null;
}

/** `POST /api/v1/tracking/batch` */
export interface BatchResponse {
  success_count: number;
  failure_count: number;
  errors?: unknown[] | null;
}

/** Body of `POST /api/v1/tracking/track` and of each `/tracking/batch` entry. */
export interface TrackBody {
  event_type: string;
  event_name: string;
  user_id: string;
  experiment_key?: string;
  feature_flag_key?: string;
  value?: number;
  metadata?: Record<string, unknown>;
  timestamp?: string;
}
