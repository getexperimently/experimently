import React from 'react';

interface WizardDraftSummary {
  experimentType: string | null;
  hypothesis: string | null;
  primaryMetricId: string | null;
  baselineRate: number | null;
  mde: number | null;
}

interface StepReviewProps {
  draft: WizardDraftSummary;
  onLaunch: () => void;
  isSubmitting?: boolean;
}

function ReviewRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between py-3 border-b border-slate-100 last:border-0">
      <dt className="text-sm font-medium text-slate-500 w-1/3">{label}</dt>
      <dd className="text-sm text-slate-800 w-2/3 text-right">{value ?? '—'}</dd>
    </div>
  );
}

function formatExperimentType(type: string | null): string {
  switch (type) {
    case 'ab':
      return 'A/B Test';
    case 'multivariate':
      return 'Multivariate';
    case 'feature_flag_rollout':
      return 'Feature Flag Rollout';
    default:
      return type ?? '—';
  }
}

/**
 * Wizard step 5 — review all choices before launching the experiment.
 */
export function StepReview({ draft, onLaunch, isSubmitting = false }: StepReviewProps) {
  return (
    <div data-testid="step-review" className="space-y-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-slate-800">Review &amp; Launch</h2>
        <p className="text-sm text-slate-500 mt-1">
          Review your experiment configuration before launching.
        </p>
      </div>

      {/* Summary card */}
      <div className="bg-white border border-slate-200 rounded-lg overflow-hidden">
        <div className="bg-slate-50 px-5 py-3 border-b border-slate-200">
          <h3 className="text-sm font-semibold text-slate-700">Experiment Summary</h3>
        </div>
        <dl className="px-5">
          <ReviewRow
            label="Experiment Type"
            value={formatExperimentType(draft.experimentType)}
          />
          <ReviewRow
            label="Hypothesis"
            value={
              draft.hypothesis ? (
                <span className="italic text-slate-600">{draft.hypothesis}</span>
              ) : (
                <span className="text-slate-400">Not specified</span>
              )
            }
          />
          <ReviewRow
            label="Primary Metric"
            value={
              draft.primaryMetricId ? (
                <code className="text-xs bg-slate-100 px-1.5 py-0.5 rounded">
                  {draft.primaryMetricId}
                </code>
              ) : (
                <span className="text-red-400">Required</span>
              )
            }
          />
          <ReviewRow
            label="Baseline Rate"
            value={
              draft.baselineRate !== null
                ? `${(draft.baselineRate * 100).toFixed(1)}%`
                : null
            }
          />
          <ReviewRow
            label="Min. Detectable Effect"
            value={
              draft.mde !== null ? `${(draft.mde * 100).toFixed(1)}%` : null
            }
          />
        </dl>
      </div>

      {/* Launch button */}
      <div className="flex justify-end">
        <button
          type="button"
          data-testid="launch-button"
          onClick={onLaunch}
          disabled={isSubmitting}
          className="px-6 py-2.5 bg-green-600 hover:bg-green-700 disabled:bg-green-300 text-white font-semibold rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-green-400"
        >
          {isSubmitting ? 'Launching…' : 'Launch Experiment'}
        </button>
      </div>
    </div>
  );
}
