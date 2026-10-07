/**
 * How an experiment's results are judged (#580): its stored confidence level
 * and its correction for comparing several variants with the control.
 *
 * Shared by the new-experiment form, the experiment page and the results page,
 * so every place names a setting with the same words.
 */
import { CorrectionMethod, MetricResult } from '@/types/results';

/** What a new experiment starts with; the API's defaults are the same. */
export const DEFAULT_CONFIDENCE_LEVEL = 0.95;
export const DEFAULT_CORRECTION_METHOD: CorrectionMethod = 'benjamini_hochberg';

/** The levels the forms offer. The API accepts any level from 0.80 to 0.99. */
export const CONFIDENCE_OPTIONS = [0.9, 0.95, 0.99] as const;

/** The order the forms list the corrections in, the recommended one first. */
export const CORRECTION_OPTIONS: CorrectionMethod[] = ['benjamini_hochberg', 'bonferroni', 'none'];

/** The full name of a correction, as the forms and the results page show it. */
export function correctionName(method: CorrectionMethod): string {
  switch (method) {
    case 'benjamini_hochberg':
      return 'Benjamini-Hochberg';
    case 'bonferroni':
      return 'Bonferroni';
    default:
      return 'None';
  }
}

/** 0.95 -> "95%", 0.925 -> "92.5%". */
export function formatConfidence(level: number): string {
  return `${Number((level * 100).toFixed(1))}%`;
}

/** 1 - level, as the threshold an adjusted p-value is compared with: 0.95 -> "0.05". */
export function formatAlpha(level: number): string {
  return String(Number((1 - level).toFixed(4)));
}

/** "95% confidence · Benjamini-Hochberg correction" (the Review row's wording). */
export function describeSettings(level: number, method: CorrectionMethod): string {
  const correction = method === 'none' ? 'no correction' : `${correctionName(method)} correction`;
  return `${formatConfidence(level)} confidence · ${correction}`;
}

/**
 * The number of treatments compared with the control on one metric: those with
 * a p-value. A treatment with no p (not enough data) takes no part in the
 * correction, so it is not counted.
 */
export function comparisonsOf(metric: MetricResult): number {
  return metric.variants.filter(
    (v) => !v.is_control && typeof v.p_value === 'number' && Number.isFinite(v.p_value),
  ).length;
}

/** The largest number of comparisons on any one metric (0 with no metrics). */
export function mostComparisons(metrics: MetricResult[]): number {
  return metrics.reduce((most, m) => Math.max(most, comparisonsOf(m)), 0);
}
