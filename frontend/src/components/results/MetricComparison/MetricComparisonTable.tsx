import React, { useState } from 'react';
import { MetricResult, VariantResult } from '@/types/results';
import { StatisticalBadge } from '@/components/results/shared/StatisticalBadge';

interface MetricComparisonTableProps {
  metrics: MetricResult[];
  confidenceLevel: number;
}

type SortKey = 'metric' | 'variant' | 'sample_size' | 'mean' | 'improvement' | 'p_value';
type SortDir = 'asc' | 'desc';

function improvementClass(variant: VariantResult): string {
  if (variant.is_control) return 'text-slate-600';
  if (variant.relative_improvement_pct === null) return 'text-slate-500';
  if (!variant.is_significant) return 'text-slate-500';
  return variant.relative_improvement_pct >= 0 ? 'text-green-700' : 'text-red-700';
}

function formatPct(v: number | null): string {
  if (v === null) return '—';
  return `${(v * 100).toFixed(2)}%`;
}

function formatImprovement(v: number | null, isControl: boolean): string {
  if (isControl) return '—';
  if (v === null) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(1)}%`;
}

interface FlatRow {
  metricId: string;
  metricName: string;
  isPrimary: boolean;
  variant: VariantResult;
}

export function MetricComparisonTable({
  metrics,
  confidenceLevel,
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

  const rows: FlatRow[] = metrics.flatMap((m) =>
    m.variants.map((v) => ({
      metricId: m.metric_id,
      metricName: m.metric_name,
      isPrimary: m.is_primary,
      variant: v,
    }))
  );

  const sorted = [...rows].sort((a, b) => {
    let cmp = 0;
    switch (sortKey) {
      case 'metric':
        cmp = a.metricName.localeCompare(b.metricName);
        break;
      case 'variant':
        cmp = a.variant.variant_name.localeCompare(b.variant.variant_name);
        break;
      case 'sample_size':
        cmp = a.variant.sample_size - b.variant.sample_size;
        break;
      case 'mean':
        cmp = a.variant.mean - b.variant.mean;
        break;
      case 'improvement':
        cmp =
          (a.variant.relative_improvement_pct ?? -Infinity) -
          (b.variant.relative_improvement_pct ?? -Infinity);
        break;
      case 'p_value':
        cmp = (a.variant.p_value ?? 1) - (b.variant.p_value ?? 1);
        break;
    }
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

  function sortIcon(key: SortKey) {
    if (sortKey !== key) return '↕';
    return sortDir === 'asc' ? '↑' : '↓';
  }

  return (
    <div className="overflow-x-auto" data-testid="metric-comparison-table">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50">
          <tr>
            {(
              [
                ['metric', 'Metric'],
                ['variant', 'Variant'],
                ['sample_size', 'Sample Size'],
                ['mean', 'Rate / Mean'],
                ['improvement', 'Improvement'],
                ['p_value', 'p-value'],
              ] as [SortKey, string][]
            ).map(([key, label]) => (
              <th
                key={key}
                onClick={() => handleSort(key)}
                className="px-4 py-3 text-left font-medium text-slate-600 cursor-pointer hover:bg-slate-100 select-none"
                aria-sort={sortKey === key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
              >
                {label} <span aria-hidden>{sortIcon(key)}</span>
              </th>
            ))}
            <th className="px-4 py-3 text-left font-medium text-slate-600">
              Significance
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {sorted.map((row, i) => (
            <tr
              key={`${row.metricId}-${row.variant.variant_id}`}
              className={`${i % 2 === 0 ? '' : 'bg-slate-50/50'} ${
                row.isPrimary ? 'ring-1 ring-inset ring-blue-100' : ''
              }`}
            >
              <td className="px-4 py-3 font-medium text-slate-800">
                {row.metricName}
                {row.isPrimary && (
                  <span className="ml-1.5 text-xs text-blue-600 font-normal">
                    primary
                  </span>
                )}
              </td>
              <td className="px-4 py-3 text-slate-700">
                {row.variant.variant_name}
                {row.variant.is_control && (
                  <span className="ml-1.5 text-xs text-slate-400">(control)</span>
                )}
              </td>
              <td className="px-4 py-3 text-slate-700">
                {row.variant.sample_size.toLocaleString()}
              </td>
              <td className="px-4 py-3 text-slate-700">
                {formatPct(row.variant.mean)}
              </td>
              <td className={`px-4 py-3 font-medium ${improvementClass(row.variant)}`}>
                {formatImprovement(
                  row.variant.relative_improvement_pct,
                  row.variant.is_control
                )}
              </td>
              <td className="px-4 py-3 text-slate-700">
                {row.variant.p_value !== null
                  ? row.variant.p_value.toFixed(4)
                  : '—'}
              </td>
              <td className="px-4 py-3">
                <StatisticalBadge
                  pValue={row.variant.p_value}
                  confidenceLevel={confidenceLevel}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
