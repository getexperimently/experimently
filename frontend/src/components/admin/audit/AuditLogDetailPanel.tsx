import React from 'react';
import { AuditLog } from '@/types/admin';
import { JsonDiffViewer } from './JsonDiffViewer';

interface AuditLogDetailPanelProps {
  log: AuditLog;
  onClose: () => void;
}

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export function AuditLogDetailPanel({ log, onClose }: AuditLogDetailPanelProps) {
  return (
    <div
      data-testid="audit-log-detail-panel"
      className="bg-white border border-slate-200 rounded-lg shadow-md p-5"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-base font-semibold text-slate-900">Audit Log Detail</h3>
        <button
          data-testid="detail-panel-close"
          onClick={onClose}
          className="text-slate-400 hover:text-slate-600 text-xl leading-none"
          aria-label="Close detail panel"
        >
          &times;
        </button>
      </div>

      {/* Fields */}
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm mb-4">
        <div>
          <dt className="text-xs font-semibold text-slate-500 uppercase">User</dt>
          <dd className="text-slate-800 mt-0.5">{log.user_email}</dd>
        </div>

        <div>
          <dt className="text-xs font-semibold text-slate-500 uppercase">Timestamp</dt>
          <dd className="text-slate-800 mt-0.5">{formatTimestamp(log.timestamp)}</dd>
        </div>

        <div className="sm:col-span-2">
          <dt className="text-xs font-semibold text-slate-500 uppercase">Action</dt>
          <dd className="text-slate-800 mt-0.5">{log.action_description}</dd>
        </div>

        <div>
          <dt className="text-xs font-semibold text-slate-500 uppercase">Entity Type</dt>
          <dd className="text-slate-800 mt-0.5">{log.entity_type}</dd>
        </div>

        <div>
          <dt className="text-xs font-semibold text-slate-500 uppercase">Entity Name</dt>
          <dd className="text-slate-800 mt-0.5">{log.entity_name}</dd>
        </div>

        {log.reason && (
          <div className="sm:col-span-2">
            <dt className="text-xs font-semibold text-slate-500 uppercase">Reason</dt>
            <dd className="text-slate-800 mt-0.5">{log.reason}</dd>
          </div>
        )}
      </dl>

      {/* Diff viewer */}
      <JsonDiffViewer oldValue={log.old_value} newValue={log.new_value} />
    </div>
  );
}
