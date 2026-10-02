import { CorrectionMethod, MetricResult, VariantResult } from '@/types/results';

/** Shown wherever a number is missing, NaN or infinite. Never "NaN", "∞" or "0.00%". */
export const NOT_ENOUGH_DATA = 'Not enough data to estimate';

export function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/**
 * The p-value the engine decided significance from: the adjusted one when a
 * correction applied, otherwise the raw one. `is_significant`, the row
 * colour and the recommendation all come from this same value.
 */
export function decisivePValue(v: VariantResult): number | null | undefined {
  return v.adjusted_p_value !== null && v.adjusted_p_value !== undefined
    ? v.adjusted_p_value
    : v.p_value;
}

/** Short display name of a correction; null when no correction applies. */
export function correctionLabel(method: CorrectionMethod | undefined): string | null {
  switch (method) {
    case 'bonferroni':
      return 'Bonferroni';
    case 'benjamini_hochberg':
      return 'BH';
    default:
      return null;
  }
}

/**
 * True when the engine analysed this metric as a share of users with an event
 * (a conversion test), whatever its declared type. Today every metric is
 * analysed that way (the per-variant test is fisher_exact); a revenue, count
 * or duration metric is only a mean once its test is welch_t_test.
 */
export function analysedAsRate(metric: MetricResult): boolean {
  if (metric.metric_type === 'conversion') return true;
  return !metric.variants.some((v) => v.statistical_test_used === 'welch_t_test');
}

/** What the value in a metric's rate column is. */
export function rateDescription(metric: MetricResult): string {
  if (metric.metric_type === 'conversion') return 'conversion rate';
  return 'share of users with at least one event';
}

/** A rate in [0, 1] as a percentage; NOT_ENOUGH_DATA when it cannot be estimated. */
export function formatRate(v: number | null | undefined, sampleSize: number): string {
  if (!isFiniteNumber(v) || sampleSize <= 0) return NOT_ENOUGH_DATA;
  return `${(v * 100).toFixed(2)}%`;
}

/** A signed percentage with a real minus sign, so the direction is in the text. */
export function formatSignedPct(v: number, digits = 1): string {
  if (v > 0) return `+${v.toFixed(digits)}%`;
  if (v < 0) return `−${Math.abs(v).toFixed(digits)}%`;
  return `${v.toFixed(digits)}%`;
}
