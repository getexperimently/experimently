import React from 'react';

interface JsonDiffViewerProps {
  oldValue?: unknown;
  newValue?: unknown;
}

function formatValue(value: unknown): string {
  if (typeof value === 'string') {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

export function JsonDiffViewer({ oldValue, newValue }: JsonDiffViewerProps) {
  const hasOld = oldValue !== null && oldValue !== undefined;
  const hasNew = newValue !== null && newValue !== undefined;

  if (!hasOld && !hasNew) {
    return null;
  }

  return (
    <div data-testid="json-diff-viewer" className="flex flex-col gap-3">
      {hasOld && (
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase mb-1">Before</p>
          <pre
            data-testid="json-diff-old"
            className="bg-red-50 border border-red-200 rounded p-3 text-xs font-mono whitespace-pre-wrap break-all text-red-900"
          >
            {formatValue(oldValue)}
          </pre>
        </div>
      )}
      {hasNew && (
        <div>
          <p className="text-xs font-semibold text-slate-500 uppercase mb-1">After</p>
          <pre
            data-testid="json-diff-new"
            className="bg-green-50 border border-green-200 rounded p-3 text-xs font-mono whitespace-pre-wrap break-all text-green-900"
          >
            {formatValue(newValue)}
          </pre>
        </div>
      )}
    </div>
  );
}
