/**
 * BreakdownSelector — Issue #28: Dimensional Analysis & Segment Breakdown
 *
 * Dropdown that lets users choose a dimension for segment breakdown.
 * Maps human-readable labels to backend API dimension keys.
 */

import React from 'react';

export interface BreakdownOption {
  label: string;
  value: string;
}

export const BREAKDOWN_OPTIONS: BreakdownOption[] = [
  { label: 'Platform', value: 'platform' },
  { label: 'Country', value: 'country' },
  { label: 'User Tier', value: 'user_tier' },
];

export interface BreakdownSelectorProps {
  /** Currently selected dimension, or null if none selected. */
  value: string | null;
  /** Called when the user selects a dimension. */
  onChange: (dim: string | null) => void;
}

export function BreakdownSelector({ value, onChange }: BreakdownSelectorProps) {
  function handleChange(event: React.ChangeEvent<HTMLSelectElement>) {
    const selected = event.target.value;
    onChange(selected === '' ? null : selected);
  }

  return (
    <div className="flex items-center gap-2">
      <label
        htmlFor="breakdown-selector"
        className="text-sm font-medium text-slate-700"
      >
        Break down by:
      </label>
      <select
        id="breakdown-selector"
        data-testid="breakdown-selector"
        value={value ?? ''}
        onChange={handleChange}
        className="rounded border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-900 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        <option value="">— None —</option>
        {BREAKDOWN_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
