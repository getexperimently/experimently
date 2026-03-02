import React from 'react';
import { FlagSafetyStatus } from '@/types/admin';

interface SafetyStatusCardProps {
  flag: FlagSafetyStatus;
  onRollback: (flagId: string) => void;
}

const STATUS_BADGE_CLASSES: Record<FlagSafetyStatus['status'], string> = {
  healthy: 'bg-green-100 text-green-800',
  warning: 'bg-yellow-100 text-yellow-800',
  critical: 'bg-red-100 text-red-800',
};

export function SafetyStatusCard({ flag, onRollback }: SafetyStatusCardProps) {
  const badgeClass = STATUS_BADGE_CLASSES[flag.status];
  const showRollback = flag.status === 'warning' || flag.status === 'critical';

  return (
    <div
      data-testid="safety-status-card"
      className="bg-white border border-slate-200 rounded-lg p-4 flex flex-col gap-3"
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-slate-800 text-sm truncate">{flag.flag_name}</span>
        <span
          data-testid="status-badge"
          className={`text-xs font-medium px-2 py-0.5 rounded-full whitespace-nowrap ${badgeClass}`}
        >
          {flag.status}
        </span>
      </div>

      <div className="flex flex-col gap-1 text-sm text-slate-600">
        <div className="flex justify-between">
          <span>Error Rate</span>
          <span data-testid="error-rate-value" className="font-medium text-slate-800">
            {flag.current_error_rate.toFixed(2)}%
          </span>
        </div>
        <div className="flex justify-between">
          <span>Latency</span>
          <span data-testid="latency-value" className="font-medium text-slate-800">
            {flag.current_latency_ms} ms
          </span>
        </div>
      </div>

      {showRollback && (
        <button
          data-testid="rollback-button"
          onClick={() => onRollback(flag.flag_id)}
          className="mt-1 w-full bg-red-600 text-white text-sm font-medium py-1.5 rounded hover:bg-red-700 transition-colors"
        >
          Rollback
        </button>
      )}
    </div>
  );
}
