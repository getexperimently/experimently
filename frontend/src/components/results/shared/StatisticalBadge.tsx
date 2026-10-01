import React from 'react';
import { NOT_ENOUGH_DATA, isFiniteNumber } from './resultFormat';

interface StatisticalBadgeProps {
  /**
   * The p-value significance was decided from: the adjusted one when a
   * correction applies. null means "not applicable" (the control).
   */
  pValue: number | null | undefined;
  /** e.g. 0.95 for 95% confidence */
  confidenceLevel: number;
  /**
   * The engine's decision (`is_significant`). When given it wins, so the
   * badge can never disagree with the row colour or the recommendation.
   */
  isSignificant?: boolean;
  /** Names the p in the badge text, e.g. "adjusted p". Defaults to "p". */
  pLabel?: string;
}

export function StatisticalBadge({
  pValue,
  confidenceLevel,
  isSignificant,
  pLabel = 'p',
}: StatisticalBadgeProps) {
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

  if (!isFiniteNumber(pValue)) {
    return (
      <span
        role="status"
        className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700"
      >
        {NOT_ENOUGH_DATA}
      </span>
    );
  }

  const significant = isSignificant ?? pValue < alpha;

  return (
    <span
      role="status"
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
        significant ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-700'
      }`}
    >
      {significant
        ? `Significant (${pLabel}=${pValue.toFixed(3)})`
        : `Not Significant (${pLabel}=${pValue.toFixed(3)})`}
    </span>
  );
}
