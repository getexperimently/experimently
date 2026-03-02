import React from 'react';

interface StepDefineHypothesisProps {
  hypothesis: string;
  onHypothesisChange: (h: string) => void;
  primaryMetricId: string | null;
  onMetricChange: (id: string) => void;
}

const MAX_HYPOTHESIS_CHARS = 500;
const MIN_HYPOTHESIS_CHARS = 10;

/**
 * Wizard step 2 — define the hypothesis and select the primary success metric.
 */
export function StepDefineHypothesis({
  hypothesis,
  onHypothesisChange,
  primaryMetricId,
  onMetricChange,
}: StepDefineHypothesisProps) {
  const charCount = hypothesis.length;
  const isTooShort = charCount > 0 && charCount < MIN_HYPOTHESIS_CHARS;
  const isOverLimit = charCount > MAX_HYPOTHESIS_CHARS;

  return (
    <div data-testid="step-define-hypothesis" className="space-y-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold text-slate-800">
          Define your hypothesis &amp; success metric
        </h2>
        <p className="text-sm text-slate-500 mt-1">
          A clear hypothesis helps your team understand what you are testing and why.
        </p>
      </div>

      {/* Hypothesis textarea */}
      <div className="space-y-2">
        <label
          htmlFor="hypothesis"
          className="block text-sm font-medium text-slate-700"
        >
          Hypothesis
          <span className="text-red-500 ml-1">*</span>
        </label>
        <textarea
          id="hypothesis"
          data-testid="hypothesis-input"
          rows={4}
          maxLength={MAX_HYPOTHESIS_CHARS}
          value={hypothesis}
          onChange={(e) => onHypothesisChange(e.target.value)}
          placeholder="We believe that [change] will result in [outcome] for [audience] because [reason]."
          className={`w-full px-3 py-2 text-sm border rounded-md resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 ${
            isTooShort || isOverLimit
              ? 'border-red-400'
              : 'border-slate-300'
          }`}
        />
        <div className="flex justify-between items-center">
          <div className="text-xs text-red-500">
            {isTooShort && `Minimum ${MIN_HYPOTHESIS_CHARS} characters required.`}
            {isOverLimit && `Maximum ${MAX_HYPOTHESIS_CHARS} characters exceeded.`}
          </div>
          <div
            data-testid="hypothesis-char-count"
            className={`text-xs ${
              isOverLimit ? 'text-red-500 font-semibold' : 'text-slate-400'
            }`}
          >
            {charCount} / {MAX_HYPOTHESIS_CHARS} characters
          </div>
        </div>
      </div>

      {/* Primary metric selector */}
      <div className="space-y-2">
        <label
          htmlFor="primary-metric"
          className="block text-sm font-medium text-slate-700"
        >
          Primary Success Metric
          <span className="text-red-500 ml-1">*</span>
        </label>
        <select
          id="primary-metric"
          data-testid="primary-metric-select"
          value={primaryMetricId ?? ''}
          onChange={(e) => onMetricChange(e.target.value)}
          className="w-full px-3 py-2 text-sm border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white"
        >
          <option value="">Select a metric…</option>
          <option value="conversion_rate">Conversion Rate</option>
          <option value="click_through_rate">Click-Through Rate</option>
          <option value="revenue_per_user">Revenue per User</option>
          <option value="session_duration">Session Duration</option>
          <option value="retention_7d">7-Day Retention</option>
        </select>
        {!primaryMetricId && (
          <p className="text-xs text-slate-400">
            Choose the metric that best represents success for this experiment.
          </p>
        )}
      </div>
    </div>
  );
}
