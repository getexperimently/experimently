/**
 * SegmentComparisonTable — Issue #28: Dimensional Analysis & Segment Breakdown
 *
 * Shows per-segment variant means and significance badges.
 * Displays "Exploratory only" warning and HTE alert when relevant.
 */

import React from 'react';
import { DimensionalBreakdownResponse } from '@/types/results';

export interface SegmentComparisonTableProps {
  breakdown: DimensionalBreakdownResponse;
}

function SignificanceBadge({ isSignificant }: { isSignificant: boolean }) {
  return isSignificant ? (
    <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
      Significant
    </span>
  ) : (
    <span className="inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
      Not significant
    </span>
  );
}

export function SegmentComparisonTable({
  breakdown,
}: SegmentComparisonTableProps) {
  const { segments, is_exploratory, has_heterogeneous_effects, hte_warning } =
    breakdown;

  return (
    <div className="space-y-4" data-testid="segment-comparison-table">
      {/* Exploratory warning */}
      {is_exploratory && (
        <div
          className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3"
          role="note"
          aria-label="Exploratory analysis warning"
        >
          <p className="text-sm font-medium text-amber-800">
            Exploratory only
          </p>
          <p className="mt-0.5 text-xs text-amber-700">
            Segment breakdowns are exploratory analyses. Results use
            Bonferroni-corrected significance thresholds (α ={' '}
            {breakdown.adjusted_alpha.toFixed(4)}) and should not be the sole
            basis for shipping decisions.
          </p>
        </div>
      )}

      {/* HTE warning */}
      {has_heterogeneous_effects && hte_warning && (
        <div
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3"
          role="alert"
          data-testid="hte-warning"
        >
          <p className="text-sm font-medium text-red-800">
            Heterogeneous treatment effects detected
          </p>
          <p className="mt-0.5 text-xs text-red-700">{hte_warning}</p>
        </div>
      )}

      {segments.length === 0 ? (
        <p className="text-sm text-slate-500">
          No segment data available for this dimension.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="min-w-full divide-y divide-slate-200">
            <thead className="bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                  Segment
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-slate-500">
                  Sample
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-slate-500">
                  Variant
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-slate-500">
                  Mean
                </th>
                <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-slate-500">
                  p-value
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-slate-500">
                  Significance
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {segments.flatMap((seg) =>
                seg.variants.map((v, vIdx) => (
                  <tr key={`${seg.segment_value}-${v.variant_id}`}>
                    {/* Only show segment value on first variant row */}
                    {vIdx === 0 ? (
                      <td
                        className="px-4 py-3 align-top text-sm font-medium text-slate-900"
                        rowSpan={seg.variants.length}
                      >
                        {seg.segment_value}
                        <span className="ml-1.5 text-xs text-slate-400">
                          (n={seg.sample_size.toLocaleString()})
                        </span>
                      </td>
                    ) : null}
                    <td className="px-4 py-3 text-right text-sm text-slate-600">
                      {v.sample_size.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-right text-sm text-slate-900">
                      {v.variant_name}
                      {v.is_control && (
                        <span className="ml-1 text-xs text-slate-400">
                          (ctrl)
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-sm tabular-nums text-slate-900">
                      {(v.mean * 100).toFixed(2)}%
                    </td>
                    <td className="px-4 py-3 text-right text-sm tabular-nums text-slate-600">
                      {v.p_value != null ? v.p_value.toFixed(4) : '—'}
                    </td>
                    <td className="px-4 py-3 text-sm">
                      {!v.is_control && (
                        <SignificanceBadge isSignificant={v.is_significant} />
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
