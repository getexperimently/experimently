import React from 'react';
import {
  EvidenceStrength,
  MSPRTResult,
  RecommendedAction,
} from '@/types/sequential';

interface EarlyStoppingBannerProps {
  msprtResult: MSPRTResult | null;
  recommendedAction: RecommendedAction;
}

const EVIDENCE_LABELS: Record<EvidenceStrength, string> = {
  strong_for_effect: 'Strong evidence for effect',
  moderate_for_effect: 'Moderate evidence for effect',
  inconclusive: 'Inconclusive',
  moderate_for_null: 'Moderate evidence for no effect',
  strong_for_null: 'Strong evidence for no effect',
};

const ACTION_CONFIG: Record<
  RecommendedAction,
  { label: string; colorClass: string }
> = {
  stop_for_effect: {
    label: 'Ready to stop — significant effect detected',
    colorClass: 'bg-green-50 border-green-400 text-green-800',
  },
  stop_for_futility: {
    label: 'Consider stopping — unlikely to reach significance',
    colorClass: 'bg-amber-50 border-amber-400 text-amber-800',
  },
  continue: {
    label: 'Continue testing — more data needed',
    colorClass: 'bg-blue-50 border-blue-400 text-blue-800',
  },
};

export function EarlyStoppingBanner({
  msprtResult,
  recommendedAction,
}: EarlyStoppingBannerProps) {
  const config = ACTION_CONFIG[recommendedAction];

  return (
    <div
      data-testid="early-stopping-banner"
      className={`rounded-lg border-l-4 p-4 ${config.colorClass}`}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="font-semibold text-sm" data-testid="action-label">
            {config.label}
          </p>
          {msprtResult && (
            <p className="text-xs mt-1 opacity-80" data-testid="evidence-detail">
              {EVIDENCE_LABELS[msprtResult.evidence_strength]} — p-value:{' '}
              {msprtResult.always_valid_p_value.toFixed(4)}
            </p>
          )}
        </div>
        {msprtResult && (
          <div className="text-right" data-testid="lambda-display">
            <span className="text-2xl font-bold">
              {msprtResult.lambda_ratio.toFixed(2)}
            </span>
            <span className="block text-xs opacity-70">
              Lambda ratio (boundary: {msprtResult.boundary.toFixed(1)})
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
