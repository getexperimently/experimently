import React from 'react';
import { ExperimentResultsResponse, RecommendationAction } from '@/types/results';
import { WinnerIndicator } from '@/components/results/shared/WinnerIndicator';

interface ExperimentSummaryProps {
  experiment: ExperimentResultsResponse;
}

const RECOMMENDATION_CONFIG: Record<
  RecommendationAction,
  { label: string; className: string }
> = {
  SHIP_VARIANT: {
    label: 'Ship Variant ✓',
    className: 'bg-green-100 text-green-800',
  },
  KEEP_CONTROL: {
    label: 'Keep Control',
    className: 'bg-blue-100 text-blue-800',
  },
  CONTINUE_TESTING: {
    label: 'Continue Testing',
    className: 'bg-amber-100 text-amber-800',
  },
  INCONCLUSIVE: {
    label: 'Inconclusive',
    className: 'bg-gray-100 text-gray-700',
  },
};

function StatusBadge({ status }: { status: string }) {
  const colorMap: Record<string, string> = {
    ACTIVE: 'bg-green-100 text-green-800',
    COMPLETED: 'bg-blue-100 text-blue-800',
    PAUSED: 'bg-amber-100 text-amber-800',
    DRAFT: 'bg-gray-100 text-gray-700',
  };
  const cls = colorMap[status] ?? 'bg-gray-100 text-gray-700';
  return (
    <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {status}
    </span>
  );
}

export function ExperimentSummary({ experiment }: ExperimentSummaryProps) {
  const { summary } = experiment;
  const rec = RECOMMENDATION_CONFIG[summary.recommendation];

  // Find the winning variant name if there is one
  let winnerName = '';
  if (summary.has_winner && summary.winning_variant_id) {
    for (const metric of experiment.metrics) {
      const v = metric.variants.find(
        (vr) => vr.variant_id === summary.winning_variant_id
      );
      if (v) {
        winnerName = v.variant_name;
        break;
      }
    }
  }

  return (
    <div
      className="bg-white rounded-xl border border-slate-200 p-6 space-y-4"
      data-testid="experiment-summary"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-slate-900">
            {experiment.experiment_name}
          </h2>
          <div className="mt-1 flex items-center gap-2">
            <StatusBadge status={experiment.status} />
            <span className="text-sm text-slate-500">
              {summary.duration_days} day{summary.duration_days !== 1 ? 's' : ''}
            </span>
          </div>
        </div>
        {/* Recommendation pill */}
        <span
          className={`inline-flex px-3 py-1.5 rounded-lg text-sm font-semibold ${rec.className}`}
          data-testid="recommendation-pill"
        >
          {rec.label}
        </span>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Stat label="Total Users" value={summary.total_users.toLocaleString()} />
        <Stat label="Total Events" value={summary.total_events.toLocaleString()} />
        <Stat label="Duration" value={`${summary.duration_days}d`} />
        <Stat
          label="Sample Size"
          value={experiment.sample_size_adequate ? 'Adequate' : 'Insufficient'}
          valueClass={
            experiment.sample_size_adequate ? 'text-green-700' : 'text-amber-700'
          }
        />
      </div>

      {/* Winner */}
      {summary.has_winner && winnerName && (
        <div className="pt-2">
          <p className="text-sm text-slate-500 mb-1">Winner</p>
          <WinnerIndicator variantName={winnerName} show />
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  valueClass = 'text-slate-800',
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div>
      <p className="text-xs text-slate-500 uppercase tracking-wide">{label}</p>
      <p className={`text-lg font-semibold ${valueClass}`}>{value}</p>
    </div>
  );
}
