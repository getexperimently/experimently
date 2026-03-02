import React from 'react';

interface WinnerIndicatorProps {
  variantName: string;
  show: boolean;
}

export function WinnerIndicator({ variantName, show }: WinnerIndicatorProps) {
  if (!show) return null;

  return (
    <div
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-green-100 text-green-800"
      data-testid="winner-indicator"
    >
      <span aria-label="winner" role="img">👑</span>
      <span className="text-sm font-medium">{variantName}</span>
    </div>
  );
}
