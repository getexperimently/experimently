import { SequentialTestingResponse } from './sequential';

// Issue #28: Dimensional breakdown types
export interface SegmentVariantResult {
  variant_id: string;
  variant_name: string;
  is_control: boolean;
  sample_size: number;
  conversions: number | null;
  mean: number;
  confidence_interval: [number, number] | null;
  p_value: number | null;
  is_significant: boolean;
}

export interface SegmentBreakdown {
  segment_value: string;
  sample_size: number;
  variants: SegmentVariantResult[];
}

export interface DimensionalBreakdownResponse {
  dimension: string;
  is_exploratory: boolean;
  adjusted_alpha: number;
  has_heterogeneous_effects: boolean;
  hte_warning: string | null;
  segments: SegmentBreakdown[];
}

export type RecommendationAction =
  | 'SHIP_VARIANT'
  | 'KEEP_CONTROL'
  | 'CONTINUE_TESTING'
  | 'INCONCLUSIVE';

export type EffectSizeLabel = 'negligible' | 'small' | 'medium' | 'large';

export interface ExperimentSummaryData {
  total_users: number;
  total_events: number;
  duration_days: number;
  has_winner: boolean;
  winning_variant_id: string | null;
  recommendation: RecommendationAction;
  /** The engine's one-sentence explanation of the recommendation. */
  recommendation_reason: string;
}

/** The test that produced a variant's p_value (backend StatisticalTest). */
export type StatisticalTestUsed = 'fisher_exact' | 'z_test_proportions' | 'welch_t_test';

/** Multiple-comparison correction (backend CorrectionMethod). Only these three exist. */
export type CorrectionMethod = 'none' | 'bonferroni' | 'benjamini_hochberg';

export interface VariantResult {
  variant_id: string;
  variant_name: string;
  is_control: boolean;
  sample_size: number;
  conversions: number | null;
  mean: number;
  std_dev: number | null;
  confidence_interval: [number, number] | null;
  p_value: number | null;
  adjusted_p_value: number | null;
  is_significant: boolean;
  effect_size: number | null;
  effect_size_label: EffectSizeLabel | null;
  relative_improvement_pct: number | null;
  power: number | null;
  /** The test behind p_value; null for the control variant. */
  statistical_test_used?: StatisticalTestUsed | null;
}

export interface MetricResult {
  metric_id: string;
  metric_name: string;
  metric_type: 'conversion' | 'revenue' | 'count' | 'duration' | 'custom';
  is_primary: boolean;
  variants: VariantResult[];
}

export interface ExperimentResultsResponse {
  experiment_id: string;
  experiment_name: string;
  status: string;
  start_date: string | null;
  end_date: string | null;
  confidence_level: number;
  correction_method: CorrectionMethod;
  sample_size_adequate: boolean;
  computed_at: string;
  summary: ExperimentSummaryData;
  metrics: MetricResult[];
  sequential_testing?: SequentialTestingResponse | null;
  // Issue #28: Dimensional breakdown (null when not requested)
  breakdown?: DimensionalBreakdownResponse | null;
}

export interface DailyDataPoint {
  date: string;
  sample_size: number;
  conversions: number | null;
  mean: number;
}

export interface VariantTimeSeries {
  variant_id: string;
  variant_name: string;
  is_control: boolean;
  values: DailyDataPoint[];
  cumulative: DailyDataPoint[];
}

export interface DailyResultsResponse {
  experiment_id: string;
  metric_id: string | null;
  series: VariantTimeSeries[];
}

export interface SampleSizeResult {
  required_sample_size_per_variant: number;
  current_sample_size_per_variant: number;
  is_adequate: boolean;
  achieved_power: number;
  days_to_significance: number | null;
  projected_completion_date: string | null;
  baseline_rate: number;
  mde: number;
  confidence_level: number;
  power_target: number;
}
