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
}

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
  correction_method: string;
  sample_size_adequate: boolean;
  computed_at: string;
  summary: ExperimentSummaryData;
  metrics: MetricResult[];
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
