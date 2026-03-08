import React, { useState } from 'react';
import Link from 'next/link';
import {
  Experiment,
  ExperimentStatus,
  ExperimentListResponse,
  EXPERIMENT_STATUS_LABELS,
  EXPERIMENT_STATUS_COLORS,
  EXPERIMENT_TYPE_LABELS,
} from '@/types/experiments';
import { ExperimentsService } from '@/services/experiments';
import { useApi } from '@/hooks/useApi';

const STATUS_FILTERS: Array<{ label: string; value: ExperimentStatus | 'all' }> = [
  { label: 'All', value: 'all' },
  { label: 'Draft', value: 'draft' },
  { label: 'Active', value: 'active' },
  { label: 'Paused', value: 'paused' },
  { label: 'Completed', value: 'completed' },
];

export default function ExperimentsPage() {
  const [statusFilter, setStatusFilter] = useState<ExperimentStatus | 'all'>('all');

  const { data, loading: isLoading, error } = useApi<ExperimentListResponse>(
    () => ExperimentsService.list(statusFilter !== 'all' ? { status: statusFilter } : undefined),
    [statusFilter],
  );

  const experiments = data?.items ?? [];

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Experiments</h1>
            <p className="text-sm text-slate-500 mt-1">
              Manage and monitor your A/B tests and feature experiments
            </p>
          </div>
          <Link
            href="/experiments/new"
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            data-testid="new-experiment-btn"
          >
            + New Experiment
          </Link>
        </div>

        {/* Status filter buttons */}
        <div className="flex gap-2 mb-6 flex-wrap">
          {STATUS_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              data-testid={`filter-${f.value}`}
              onClick={() => setStatusFilter(f.value)}
              className={`px-3 py-1.5 rounded-full text-sm font-medium transition-colors ${
                statusFilter === f.value
                  ? 'bg-blue-600 text-white'
                  : 'bg-white text-slate-600 border border-slate-300 hover:bg-slate-50'
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Loading state */}
        {isLoading && (
          <div className="text-center py-12">
            <div className="inline-block w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
            <p className="text-slate-500 mt-2 text-sm">Loading experiments...</p>
          </div>
        )}

        {/* Error state */}
        {!isLoading && error && (
          <div className="rounded-lg bg-red-50 border border-red-200 p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !error && experiments.length === 0 && (
          <div className="text-center py-16 bg-white rounded-lg border border-slate-200">
            <p className="text-slate-500 mb-4">No experiments found</p>
            <Link
              href="/experiments/new"
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              Create your first experiment
            </Link>
          </div>
        )}

        {/* Experiments table */}
        {!isLoading && !error && experiments.length > 0 && (
          <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="text-left px-4 py-3 text-slate-600 font-medium">Name</th>
                  <th className="text-left px-4 py-3 text-slate-600 font-medium">Status</th>
                  <th className="text-left px-4 py-3 text-slate-600 font-medium">Type</th>
                  <th className="text-left px-4 py-3 text-slate-600 font-medium">Owner</th>
                  <th className="text-left px-4 py-3 text-slate-600 font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {experiments.map((exp) => (
                  <tr key={exp.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-4 py-3">
                      <Link
                        href={`/experiments/${exp.id}`}
                        className="font-medium text-blue-600 hover:text-blue-800 hover:underline"
                      >
                        {exp.name}
                      </Link>
                      {exp.description && (
                        <p className="text-xs text-slate-400 mt-0.5 truncate max-w-xs">
                          {exp.description}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${EXPERIMENT_STATUS_COLORS[exp.status]}`}
                      >
                        {EXPERIMENT_STATUS_LABELS[exp.status]}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {EXPERIMENT_TYPE_LABELS[exp.type]}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {exp.owner_name ?? exp.owner_id}
                    </td>
                    <td className="px-4 py-3 text-slate-500">
                      {new Date(exp.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
