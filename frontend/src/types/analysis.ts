/**
 * Whether an analysis's numbers can be relied on.
 * Matches backend/app/core/analysis_status.py: `analysis_notice` is a string
 * exactly when `analysis_status` is "beta", and null when it is "ga".
 */
export type AnalysisStatus = 'ga' | 'beta';

/** Fields the sequential, CUPED and interaction-pair responses carry. */
export interface AnalysisStatusFields {
  analysis_status?: AnalysisStatus | null;
  analysis_notice?: string | null;
}
