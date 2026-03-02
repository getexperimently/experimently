/**
 * TypeScript types for Sequential Testing & Early Stopping (EP-021).
 * Matches backend schemas in backend/app/schemas/sequential.py
 */

export type SequentialTestingMethod = 'msprt' | 'always_valid';

export type SpendingFunction = 'obrien_fleming' | 'pocock';

export type EvidenceStrength =
  | 'strong_for_effect'
  | 'moderate_for_effect'
  | 'inconclusive'
  | 'moderate_for_null'
  | 'strong_for_null';

export type RecommendedAction = 'stop_for_effect' | 'stop_for_futility' | 'continue';

export interface MSPRTResult {
  lambda_ratio: number;
  always_valid_p_value: number;
  can_stop: boolean;
  evidence_strength: EvidenceStrength;
  boundary: number;
}

export interface ConfidenceSequence {
  lower: number;
  upper: number;
  width: number;
  sample_size: number;
}

export interface AlphaSpendingBoundary {
  look_number: number;
  cumulative_alpha: number;
  boundary_z: number;
  boundary_p: number;
}

export interface EvidencePoint {
  sample_size: number;
  lambda_ratio: number;
  always_valid_p_value: number;
  can_stop: boolean;
}

export interface LongRunningRisk {
  is_at_risk: boolean;
  expected_duration_days: number;
  actual_duration_days: number;
  risk_ratio: number;
  recommendation: string;
}

export interface SequentialTestingResponse {
  method: SequentialTestingMethod;
  msprt_result: MSPRTResult | null;
  confidence_sequence: ConfidenceSequence | null;
  evidence_trajectory: EvidencePoint[];
  alpha_spending: AlphaSpendingBoundary[];
  long_running_risk: LongRunningRisk | null;
  recommended_action: RecommendedAction;
}
