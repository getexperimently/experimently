import React from 'react';

interface StatisticalBadgeProps {
  pValue: number | null;
  /** e.g. 0.95 for 95% confidence */
  confidenceLevel: number;
}

export function StatisticalBadge({ pValue, confidenceLevel }: StatisticalBadgeProps) {
  // Round to avoid floating-point artifacts (e.g. 1 - 0.95 = 0.050000000000000044)
  const alpha = Math.round((1 - confidenceLevel) * 10000) / 10000;

  if (pValue === null) {
    return (
      <span
        role="status"
        className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600"
      >
        N/A
      </span>
    );
  }

  const isSignificant = pValue < alpha;

  return (
    <span
      role="status"
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
        isSignificant
          ? 'bg-green-100 text-green-800'
          : 'bg-gray-100 text-gray-700'
      }`}
    >
      {isSignificant
        ? `Significant (p=${pValue.toFixed(3)})`
        : `Not Significant (p=${pValue.toFixed(3)})`}
    </span>
  );
}
