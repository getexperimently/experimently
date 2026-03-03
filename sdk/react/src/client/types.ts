export interface SdkConfig {
  apiKey: string;
  baseUrl: string;
  timeoutMs?: number;
  cacheTtlMs?: number;
}

export interface UserContext {
  userId: string;
  attributes?: Record<string, unknown>;
}

export interface FeatureFlag {
  id: string;
  key: string;
  name: string;
  enabled: boolean;
  rolloutPercentage: number;
  variants?: Array<{ name: string; weight: number }>;
}

export interface FeatureFlagEvaluation {
  flagKey: string;
  variant: string | null; // null = off
  isEnabled: boolean;
  loading: boolean;
  error: Error | null;
}

export interface ExperimentAssignment {
  experimentKey: string;
  variantKey: string;
  variantName: string;
  loading: boolean;
  error: Error | null;
}
