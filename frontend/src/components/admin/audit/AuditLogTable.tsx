import React, { useEffect, useState, useCallback } from 'react';
import { AdminService } from '@/services/admin';
import { AuditLog, AuditLogListResponse } from '@/types/admin';
import { AuditLogDetailPanel } from './AuditLogDetailPanel';
import { AuditLogFilters } from './AuditLogFilter';

interface AuditLogTableProps {
  filters?: AuditLogFilters;
}

const PAGE_LIMIT = 50;

function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export function AuditLogTable({ filters }: AuditLogTableProps) {
  const [data, setData] = useState<AuditLogListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [selectedLog, setSelectedLog] = useState<AuditLog | null>(null);

  const fetchLogs = useCallback(async (currentPage: number) => {
    setLoading(true);
    setError(null);
    try {
      const result = await AdminService.listAuditLogs({
        ...filters,
        page: currentPage,
        limit: PAGE_LIMIT,
      });
      setData(result);
    } catch (err) {
      setError((err as Error).message || 'Failed to load audit logs');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    setPage(1);
    setSelectedLog(null);
  }, [filters]);

  useEffect(() => {
    fetchLogs(page);
  }, [fetchLogs, page]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_LIMIT)) : 1;

  const handleRowClick = (log: AuditLog) => {
    setSelectedLog((prev) => (prev?.id === log.id ? null : log));
  };

  const handleClose = () => setSelectedLog(null);

  const handlePrev = () => {
    if (page > 1) setPage((p) => p - 1);
  };

  const handleNext = () => {
    if (page < totalPages) setPage((p) => p + 1);
  };

  return (
    <div data-testid="audit-log-table" className="flex flex-col gap-4">
      {/* Loading */}
      {loading && (
        <div data-testid="audit-log-table-loading" className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div
              key={i}
              className="h-10 bg-slate-100 rounded animate-pulse"
            />
          ))}
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div
          data-testid="audit-log-error-state"
          className="bg-red-50 border border-red-200 rounded-lg p-6 text-center"
        >
          <p className="text-red-700 font-medium">Failed to load audit logs</p>
          <p className="text-red-500 text-sm mt-1">{error}</p>
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && data && data.items.length === 0 && (
        <div
          data-testid="audit-log-empty-state"
          className="bg-slate-50 border border-slate-200 rounded-lg p-10 text-center"
        >
          <p className="text-slate-500 text-sm">No audit logs found.</p>
        </div>
      )}

      {/* Table */}
      {!loading && !error && data && data.items.length > 0 && (
        <div className="overflow-x-auto border border-slate-200 rounded-lg">
          <table className="w-full text-sm text-left">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="px-4 py-3 font-semibold text-slate-600">Timestamp</th>
                <th className="px-4 py-3 font-semibold text-slate-600">User</th>
                <th className="px-4 py-3 font-semibold text-slate-600">Action</th>
                <th className="px-4 py-3 font-semibold text-slate-600">Entity Type</th>
                <th className="px-4 py-3 font-semibold text-slate-600">Entity Name</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((log) => (
                <React.Fragment key={log.id}>
                  <tr
                    data-testid={`audit-log-row-${log.id}`}
                    onClick={() => handleRowClick(log)}
                    className={`border-b border-slate-100 cursor-pointer hover:bg-blue-50 transition-colors ${
                      selectedLog?.id === log.id ? 'bg-blue-50' : 'bg-white'
                    }`}
                  >
                    <td
                      data-testid={`timestamp-${log.id}`}
                      className="px-4 py-3 text-slate-600 whitespace-nowrap"
                    >
                      {formatTimestamp(log.timestamp)}
                    </td>
                    <td className="px-4 py-3 text-slate-800">{log.user_email}</td>
                    <td className="px-4 py-3">
                      <span className="inline-block bg-slate-100 text-slate-700 px-2 py-0.5 rounded text-xs font-mono">
                        {log.action_type}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-700">{log.entity_type}</td>
                    <td className="px-4 py-3 text-slate-800 font-medium">{log.entity_name}</td>
                  </tr>
                  {selectedLog?.id === log.id && (
                    <tr>
                      <td colSpan={5} className="p-4 bg-slate-50">
                        <AuditLogDetailPanel log={log} onClose={handleClose} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {!loading && !error && data && (
        <div className="flex items-center gap-3 justify-end">
          <button
            data-testid="pagination-prev"
            onClick={handlePrev}
            disabled={page <= 1}
            className="px-3 py-1.5 text-sm font-medium border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Previous
          </button>
          <span data-testid="pagination-label" className="text-sm text-slate-600">
            Page {page} of {totalPages}
          </span>
          <button
            data-testid="pagination-next"
            onClick={handleNext}
            disabled={page >= totalPages}
            className="px-3 py-1.5 text-sm font-medium border border-slate-300 rounded hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
