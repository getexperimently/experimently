import React from 'react';

interface StepSampleSizeProps {
  baselineRate: number;
  mde: number;
  requiredSampleSize: number;
  daysEstimate: number | null;
}

/**
 * Wizard step 4 — sample size calculator display.
 * Shows the required sample size and estimated days to reach it.
 */
export function StepSampleSize({
  baselineRate,
  mde,
  requiredSampleSize,
  daysEstimate,
}: StepSampleSizeProps) {
  const formattedSampleSize = requiredSampleSize.toLocaleString();

  return (
    <div data-testid="step-sample-size" className="space-y-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-slate-800">
          Sample size &amp; duration estimate
        </h2>
        <p className="text-sm text-slate-500 mt-1">
          Based on your baseline conversion rate and minimum detectable effect, here is what you
          need.
        </p>
      </div>

      {/* Input summary */}
      <div className="bg-slate-50 rounded-lg p-4 grid grid-cols-2 gap-4 text-sm">
        <div>
          <div className="text-slate-500 text-xs uppercase tracking-wide mb-1">
            Baseline Rate
          </div>
          <div className="font-semibold text-slate-800">
            {(baselineRate * 100).toFixed(1)}%
          </div>
        </div>
        <div>
          <div className="text-slate-500 text-xs uppercase tracking-wide mb-1">
            Min. Detectable Effect
          </div>
          <div className="font-semibold text-slate-800">
            {(mde * 100).toFixed(1)}%
          </div>
        </div>
      </div>

      {/* Results */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-blue-50 rounded-lg p-5 flex flex-col items-center justify-center text-center border border-blue-100">
          <div className="text-xs uppercase tracking-wide text-blue-500 mb-2">
            Required Sample Size
            <span className="block text-slate-400 normal-case font-normal">
              (per variant)
            </span>
          </div>
          <div
            data-testid="sample-size-value"
            className="text-3xl font-bold text-blue-700"
          >
            {formattedSampleSize}
          </div>
          <div className="text-xs text-slate-500 mt-1">users</div>
        </div>

        <div className="bg-purple-50 rounded-lg p-5 flex flex-col items-center justify-center text-center border border-purple-100">
          <div className="text-xs uppercase tracking-wide text-purple-500 mb-2">
            Estimated Duration
          </div>
          <div
            data-testid="days-estimate"
            className="text-3xl font-bold text-purple-700"
          >
            {daysEstimate !== null ? daysEstimate : 'N/A'}
          </div>
          <div className="text-xs text-slate-500 mt-1">
            {daysEstimate !== null ? 'days' : 'insufficient traffic data'}
          </div>
        </div>
      </div>

      <p className="text-xs text-slate-400">
        Calculated at 80% statistical power and 95% confidence level (two-tailed).
      </p>
    </div>
  );
}
