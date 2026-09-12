/**
 * Safety-monitoring types — mirrors `backend/app/schemas/safety.py`.
 *
 * These live in the types layer (not in a service) so both `@/services/admin`
 * and `@/services/featureFlags` can depend on them without a service importing
 * another service's types. `GET /api/v1/safety/feature-flags/{id}/check` has a
 * single client: `FeatureFlagsService.safetyCheck()`.
 */

/** `MetricStatus` — one metric of a safety check. */
export interface SafetyMetricStatus {
  name: string;
  description?: string | null;
  current_value: number;
  threshold: number;
  unit?: string | null;
  is_healthy: boolean;
  details?: Record<string, unknown> | null;
}

/** `SafetyCheckResponse` — `GET /api/v1/safety/feature-flags/{id}/check`. */
export interface SafetyCheckResponse {
  feature_flag_id: string;
  is_healthy: boolean;
  metrics: SafetyMetricStatus[];
  last_checked: string;
  details?: Record<string, unknown> | null;
}
