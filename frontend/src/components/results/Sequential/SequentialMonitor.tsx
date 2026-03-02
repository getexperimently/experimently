import React from 'react';
import { SequentialTestingResponse } from '@/types/sequential';
import { EarlyStoppingBanner } from './EarlyStoppingBanner';
import { EvidenceRatioChart } from './EvidenceRatioChart';

interface SequentialMonitorProps {
  data: SequentialTestingResponse;
}

export function SequentialMonitor({ data }: SequentialMonitorProps) {
  const boundary = data.msprt_result?.boundary ?? 1 / 0.05; // default 20

  return (
    <div data-testid="sequential-monitor" className="space-y-6">
      {/* Stopping banner */}
      <EarlyStoppingBanner
        msprtResult={data.msprt_result}
        recommendedAction={data.recommended_action}
      />

      {/* Evidence ratio chart */}
      <section aria-label="Evidence trajectory">
        <h4 className="text-sm font-semibold text-slate-700 mb-3">
          Evidence Ratio Over Time
        </h4>
        <EvidenceRatioChart
          trajectory={data.evidence_trajectory}
          boundary={boundary}
        />
      </section>

      {/* Confidence sequence */}
      {data.confidence_sequence && (
        <section
          aria-label="Confidence sequence"
          data-testid="confidence-sequence"
          className="bg-slate-50 rounded-lg p-4"
        >
          <h4 className="text-sm font-semibold text-slate-700 mb-2">
            Always-Valid Confidence Interval
          </h4>
          <div className="flex gap-8 text-sm">
            <div>
              <span className="text-slate-500">Lower: </span>
              <span className="font-mono font-medium" data-testid="ci-lower">
                {data.confidence_sequence.lower.toFixed(4)}
              </span>
            </div>
            <div>
              <span className="text-slate-500">Upper: </span>
              <span className="font-mono font-medium" data-testid="ci-upper">
                {data.confidence_sequence.upper.toFixed(4)}
              </span>
            </div>
            <div>
              <span className="text-slate-500">Width: </span>
              <span className="font-mono font-medium" data-testid="ci-width">
                {data.confidence_sequence.width.toFixed(4)}
              </span>
            </div>
            <div>
              <span className="text-slate-500">N: </span>
              <span className="font-mono font-medium" data-testid="ci-n">
                {data.confidence_sequence.sample_size.toLocaleString()}
              </span>
            </div>
          </div>
        </section>
      )}

      {/* Long-running risk */}
      {data.long_running_risk && data.long_running_risk.is_at_risk && (
        <div
          data-testid="long-running-risk"
          className="bg-red-50 border border-red-200 rounded-lg p-4"
          role="alert"
        >
          <p className="text-sm font-semibold text-red-800">
            Long-Running Experiment Risk
          </p>
          <p className="text-xs text-red-700 mt-1">
            Running {data.long_running_risk.actual_duration_days} of{' '}
            {data.long_running_risk.expected_duration_days} expected days (
            {(data.long_running_risk.risk_ratio * 100).toFixed(0)}%).{' '}
            {data.long_running_risk.recommendation}
          </p>
        </div>
      )}

      {/* Alpha spending boundaries */}
      {data.alpha_spending.length > 0 && (
        <section aria-label="Alpha spending boundaries">
          <h4 className="text-sm font-semibold text-slate-700 mb-2">
            Alpha Spending Schedule
          </h4>
          <div className="overflow-x-auto">
            <table
              className="min-w-full text-sm"
              data-testid="alpha-spending-table"
            >
              <thead>
                <tr className="border-b border-slate-200">
                  <th className="text-left py-2 pr-4 text-slate-600 font-medium">
                    Look
                  </th>
                  <th className="text-right py-2 pr-4 text-slate-600 font-medium">
                    Cumulative Alpha
                  </th>
                  <th className="text-right py-2 pr-4 text-slate-600 font-medium">
                    Boundary Z
                  </th>
                  <th className="text-right py-2 text-slate-600 font-medium">
                    Boundary P
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.alpha_spending.map((row) => (
                  <tr key={row.look_number} className="border-b border-slate-100">
                    <td className="py-1.5 pr-4">{row.look_number}</td>
                    <td className="py-1.5 pr-4 text-right font-mono">
                      {row.cumulative_alpha.toFixed(4)}
                    </td>
                    <td className="py-1.5 pr-4 text-right font-mono">
                      {row.boundary_z.toFixed(3)}
                    </td>
                    <td className="py-1.5 text-right font-mono">
                      {row.boundary_p.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
