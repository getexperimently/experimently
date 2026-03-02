import React from 'react';
import { SampleSizeResult } from '@/types/results';

interface SampleSizeMeterProps {
  data: SampleSizeResult;
}

export function SampleSizeMeter({ data }: SampleSizeMeterProps) {
  const {
    current_sample_size_per_variant,
    required_sample_size_per_variant,
    is_adequate,
    achieved_power,
    days_to_significance,
    projected_completion_date,
  } = data;

  const pct =
    required_sample_size_per_variant > 0
      ? Math.round(
          (current_sample_size_per_variant / required_sample_size_per_variant) * 100
        )
      : 100;

  const barColor = is_adequate
    ? 'bg-green-500'
    : pct >= 80
    ? 'bg-amber-400'
    : 'bg-red-400';

  const labelColor = is_adequate
    ? 'text-green-700'
    : pct >= 80
    ? 'text-amber-700'
    : 'text-red-700';

  return (
    <div className="space-y-3" data-testid="sample-size-meter">
      <div className="flex justify-between text-sm">
        <span className="font-medium text-slate-700">Sample Size Adequacy</span>
        <span className={`font-semibold ${labelColor}`}>
          {is_adequate ? 'Adequate ✓' : 'Insufficient'}
        </span>
      </div>

      <div>
        <div className="flex justify-between text-sm text-slate-600 mb-1">
          <span data-testid="sample-size-label">
            {current_sample_size_per_variant.toLocaleString()} /{' '}
            {required_sample_size_per_variant.toLocaleString()} ({pct}%)
          </span>
          <span data-testid="power-label">
            Power: {(achieved_power * 100).toFixed(0)}%
          </span>
        </div>
        <div
          className="w-full bg-gray-200 rounded-full h-4"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Sample size adequacy: ${pct}%`}
        >
          <div
            className={`h-4 rounded-full transition-all duration-300 ${barColor}`}
            style={{ width: `${Math.min(pct, 100)}%` }}
            data-testid="sample-size-bar"
          />
        </div>
      </div>

      {!is_adequate && (
        <div className="text-sm text-slate-500 space-y-1">
          {days_to_significance !== null && (
            <p data-testid="days-to-significance">
              Estimated days to significance:{' '}
              <span className="font-medium text-slate-700">{days_to_significance}</span>
            </p>
          )}
          {projected_completion_date && (
            <p data-testid="projected-date">
              Projected completion:{' '}
              <span className="font-medium text-slate-700">
                {new Date(projected_completion_date).toLocaleDateString()}
              </span>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
