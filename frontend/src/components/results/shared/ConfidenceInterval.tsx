import React from 'react';

interface ConfidenceIntervalProps {
  value: number;
  bounds: [number, number] | null;
  /** Optional formatter, defaults to percentage */
  format?: (v: number) => string;
}

function defaultFormat(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

export function ConfidenceInterval({ value, bounds, format = defaultFormat }: ConfidenceIntervalProps) {
  return (
    <span className="text-sm font-medium text-slate-700" data-testid="confidence-interval">
      <span data-testid="ci-value">{format(value)}</span>
      {bounds && (
        <span className="text-slate-500 ml-1" data-testid="ci-bounds">
          [{format(bounds[0])} – {format(bounds[1])}]
        </span>
      )}
    </span>
  );
}
