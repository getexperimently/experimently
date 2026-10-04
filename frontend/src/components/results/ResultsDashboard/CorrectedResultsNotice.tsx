import React from 'react';
import { CorrectionMethod, MetricResult } from '@/types/results';
import {
  CORRECTED_RESULTS_SINCE,
  mostComparisons,
} from '@/components/results/shared/analysisSettings';

interface CorrectedResultsNoticeProps {
  metrics: MetricResult[];
  /** The correction the response was computed with. */
  correctionMethod: CorrectionMethod;
}

export const CORRECTED_RESULTS_NOTICE =
  `Since ${CORRECTED_RESULTS_SINCE}, results for experiments with several variants use the ` +
  "experiment's correction; earlier versions showed them uncorrected, so a variant marked " +
  'significant then may not be significant now.';

/**
 * Says that multi-variant results changed in a release (#580). Shown only when
 * a correction actually changed something: two or more treatments with a
 * p-value on some metric, and a correction other than none. It is for one
 * release; #821 removes it.
 *
 * Visible text in a region, not an alert: it qualifies the numbers.
 */
export function CorrectedResultsNotice({ metrics, correctionMethod }: CorrectedResultsNoticeProps) {
  if (correctionMethod === 'none' || mostComparisons(metrics) < 2) return null;
  return (
    <section
      aria-label="Change to these results"
      data-testid="corrected-results-notice"
      className="rounded-lg border border-amber-300 bg-amber-50 p-4"
    >
      <p className="text-sm text-amber-900">{CORRECTED_RESULTS_NOTICE}</p>
    </section>
  );
}
