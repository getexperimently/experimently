import React, { useState } from 'react';
import { CorrectionMethod, MetricResult, VariantResult } from '@/types/results';
import { StatisticalBadge } from '@/components/results/shared/StatisticalBadge';
import {
  NOT_ENOUGH_DATA,
  analysedAsRate,
  correctionLabel,
  decisivePValue,
  formatRate,
  formatSignedPct,
  isFiniteNumber,
  rateDescription,
} from '@/components/results/shared/resultFormat';

interface MetricComparisonTableProps {
  metrics: MetricResult[];
  confidenceLevel: number;
  /** The response's correction_method; names the adjusted p-values. */
  correctionMethod?: CorrectionMethod;
}

type SortKey = 'metric' | 'variant' | 'sample_size' | 'mean' | 'improvement' | 'p_value';
type SortDir = 'asc' | 'desc';

// Colour follows the engine's is_significant — the same decision as the
// badge and the recommendation. The sign and the badge text carry the
// meaning; the colour only repeats it.
function improvementClass(variant: VariantResult): string {
  if (variant.is_control) return 'text-slate-600';
  if (!isFiniteNumber(variant.relative_improvement_pct)) return 'text-slate-500';
  if (!variant.is_significant) return 'text-slate-500';
  return variant.relative_improvement_pct >= 0 ? 'text-green-700' : 'text-red-700';
}

function formatImprovement(v: number | null | undefined, isControl: boolean): string {
  if (isControl) return '—';
  if (!isFiniteNumber(v)) return NOT_ENOUGH_DATA;
  return formatSignedPct(v);
}

function formatValue(metric: MetricResult, variant: VariantResult): string {
  if (analysedAsRate(metric)) return formatRate(variant.mean, variant.sample_size);
  // A mean (welch_t_test). Units arrive with the mean analysis; until then a
  // plain number, never a currency or "per user".
  if (!isFiniteNumber(variant.mean) || variant.sample_size <= 0) return NOT_ENOUGH_DATA;
  return variant.mean.toFixed(2);
}

/** Sort key for a possibly non-finite number: unknowns sort first ascending. */
function sortable(v: number | null | undefined): number {
  return isFiniteNumber(v) ? v : -Infinity;
}

function PValueCell({
  variant,
  correctionMethod,
}: {
  variant: VariantResult;
  correctionMethod?: CorrectionMethod;
}) {
  if (variant.is_control) return <>—</>;
  const correction = correctionLabel(correctionMethod);
  const adjusted = variant.adjusted_p_value;
  const raw = variant.p_value;

  if (correction && isFiniteNumber(adjusted)) {
    return (
      <span className="flex flex-col">
        <span>{adjusted.toFixed(4)}</span>
        <span className="text-xs text-slate-600">adjusted ({correction})</span>
        {isFiniteNumber(raw) && (
          <span className="text-xs text-slate-600">raw {raw.toFixed(4)}</span>
        )}
      </span>
    );
  }
  if (!isFiniteNumber(raw)) return <>{NOT_ENOUGH_DATA}</>;
  // The dashboard requests no correction, so this is the usual case: the
  // engine decided significance from the raw p, and the label says so.
  return (
    <span className="flex flex-col">
      <span>{raw.toFixed(4)}</span>
      <span className="text-xs text-slate-600">unadjusted</span>
    </span>
  );
}

const COLUMNS: [SortKey, string][] = [
  ['metric', 'Metric'],
  ['variant', 'Variant'],
  ['sample_size', 'Sample Size'],
  ['mean', 'Value'],
  ['improvement', 'Improvement'],
  ['p_value', 'p-value'],
];

interface FlatRow {
  metric: MetricResult;
  variant: VariantResult;
}

export function MetricComparisonTable({
  metrics,
  confidenceLevel,
  correctionMethod,
}: MetricComparisonTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('metric');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  if (!metrics.length) {
    return (
      <p className="text-slate-500 text-sm" data-testid="no-metrics">
        No metrics available
      </p>
    );
  }

  const correction = correctionLabel(correctionMethod);

  const rows: FlatRow[] = metrics.flatMap((m) =>
    m.variants.map((v) => ({ metric: m, variant: v }))
  );

  const ordered = [...rows].sort((a, b) => {
    let cmp = 0;
    switch (sortKey) {
      case 'metric':
        cmp = a.metric.metric_name.localeCompare(b.metric.metric_name);
        break;
      case 'variant':
        cmp = a.variant.variant_name.localeCompare(b.variant.variant_name);
        break;
      case 'sample_size':
        cmp = a.variant.sample_size - b.variant.sample_size;
        break;
      case 'mean':
        cmp = sortable(a.variant.mean) - sortable(b.variant.mean);
        break;
      case 'improvement':
        cmp =
          sortable(a.variant.relative_improvement_pct) -
          sortable(b.variant.relative_improvement_pct);
        break;
      case 'p_value': {
        const pa = decisivePValue(a.variant);
        const pb = decisivePValue(b.variant);
        cmp = (isFiniteNumber(pa) ? pa : 1) - (isFiniteNumber(pb) ? pb : 1);
        break;
      }
    }
    if (Number.isNaN(cmp)) cmp = 0;
    return sortDir === 'asc' ? cmp : -cmp;
  });

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  function ariaSort(key: SortKey): 'ascending' | 'descending' | 'none' {
    if (sortKey !== key) return 'none';
    return sortDir === 'asc' ? 'ascending' : 'descending';
  }

  function sortIcon(key: SortKey) {
    if (sortKey !== key) return '↕';
    return sortDir === 'asc' ? '↑' : '↓';
  }

  return (
    <div className="overflow-x-auto" data-testid="metric-comparison-table">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr>
            {COLUMNS.map(([key, label]) => (
              <th
                key={key}
                onClick={() => handleSort(key)}
                scope="col"
                className="px-4 py-3 text-left font-medium text-slate-600 cursor-pointer hover:bg-slate-100 select-none"
                aria-sort={ariaSort(key)}
              >
                <span className="inline-flex items-center gap-1">
                  {label}
                  <span aria-hidden="true">{sortIcon(key)}</span>
                </span>
              </th>
            ))}
            <th scope="col" className="px-4 py-3 text-left font-medium text-slate-600">
              Significance
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {ordered.map((row, i) => {
            const { metric, variant } = row;
            const decisive = decisivePValue(variant);
            const adjustedShown = correction !== null && isFiniteNumber(variant.adjusted_p_value);
            return (
              <tr
                key={`${metric.metric_id}-${variant.variant_id}`}
                className={`${i % 2 === 0 ? '' : 'bg-slate-50/50'} ${
                  metric.is_primary ? 'ring-1 ring-inset ring-blue-100' : ''
                }`}
              >
                <td className="px-4 py-3 font-medium text-slate-800">
                  {metric.metric_name}
                  {metric.is_primary && (
                    <span className="ml-1.5 text-xs text-blue-700 font-normal">primary</span>
                  )}
                </td>
                <td className="px-4 py-3 text-slate-700">
                  {variant.variant_name}
                  {variant.is_control && (
                    <span className="ml-1.5 text-xs text-slate-600">(control)</span>
                  )}
                </td>
                <td className="px-4 py-3 text-slate-700">
                  {variant.sample_size.toLocaleString()}
                </td>
                <td className="px-4 py-3 text-slate-700">
                  <span className="flex flex-col">
                    <span>{formatValue(metric, variant)}</span>
                    {metric.metric_type !== 'conversion' && (
                      <span className="text-xs text-slate-600">
                        {analysedAsRate(metric) ? rateDescription(metric) : 'mean'}
                      </span>
                    )}
                  </span>
                </td>
                <td className={`px-4 py-3 font-medium ${improvementClass(variant)}`}>
                  {formatImprovement(variant.relative_improvement_pct, variant.is_control)}
                </td>
                <td className="px-4 py-3 text-slate-700">
                  <PValueCell variant={variant} correctionMethod={correctionMethod} />
                </td>
                <td className="px-4 py-3">
                  <StatisticalBadge
                    pValue={variant.is_control ? null : isFiniteNumber(decisive) ? decisive : NaN}
                    confidenceLevel={confidenceLevel}
                    isSignificant={variant.is_significant}
                    pLabel={adjustedShown ? 'adjusted p' : 'p'}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
