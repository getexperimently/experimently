import React, { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { PageTitle } from '@/components/PageTitle';
import { useAuth } from '@/contexts/AuthContext';
import { isApiError } from '@/services/api';
import { ExperimentsService } from '@/services/experiments';
import {
  Experiment,
  ExperimentStatus,
  METRIC_TYPE_LABELS,
  MetricType,
  experimentStatusColor,
  experimentStatusLabel,
  experimentTypeLabel,
} from '@/types/experiments';

/** Lifecycle transitions exposed per status (mirrors the backend guards). */
export type LifecycleAction = 'start' | 'pause' | 'complete' | 'archive';

export const ACTIONS_BY_STATUS: Record<ExperimentStatus, LifecycleAction[]> = {
  draft: ['start'],
  active: ['pause', 'complete'],
  paused: ['start', 'complete'],
  completed: ['archive'],
  archived: [],
};

const ACTION_META: Record<
  LifecycleAction,
  { label: string; pending: string; className: string; confirm?: string }
> = {
  start: {
    label: 'Start',
    pending: 'Starting…',
    className: 'bg-green-600 text-white hover:bg-green-700',
  },
  pause: {
    label: 'Pause',
    pending: 'Pausing…',
    className: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50',
  },
  complete: {
    label: 'Complete',
    pending: 'Completing…',
    className: 'bg-blue-600 text-white hover:bg-blue-700',
    confirm: 'Complete this experiment? Assignment stops and the status cannot be reverted.',
  },
  archive: {
    label: 'Archive',
    pending: 'Archiving…',
    className: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50',
    confirm: 'Archive this experiment? It will be hidden from the default list.',
  },
};

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

function shortId(id: string): string {
  return id.length > 12 ? `${id.slice(0, 8)}…` : id;
}

export default function ExperimentDetailPage() {
  const router = useRouter();
  const { user } = useAuth();
  const rawId = router.query.id;
  const id = typeof rawId === 'string' ? rawId : undefined;

  const [experiment, setExperiment] = useState<Experiment | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<{ status: number; message: string } | null>(null);
  const [pendingAction, setPendingAction] = useState<LifecycleAction | null>(null);
  const [confirming, setConfirming] = useState<LifecycleAction | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setLoadError(null);
    try {
      const data = await ExperimentsService.get(id);
      setExperiment(data);
    } catch (err) {
      const status = isApiError(err) ? err.status : 0;
      setLoadError({
        status,
        message: err instanceof Error ? err.message : 'Failed to load experiment',
      });
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const runAction = async (action: LifecycleAction) => {
    if (!experiment) return;
    setConfirming(null);
    setActionError(null);
    setPendingAction(action);
    try {
      const updated = await ExperimentsService[action](experiment.id);
      setExperiment(updated);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : `Failed to ${action} experiment`);
    } finally {
      setPendingAction(null);
    }
  };

  const onActionClick = (action: LifecycleAction) => {
    if (ACTION_META[action].confirm) {
      setActionError(null);
      setConfirming(action);
      return;
    }
    void runAction(action);
  };

  const copyKey = async () => {
    if (!experiment?.key) return;
    try {
      await navigator.clipboard?.writeText(experiment.key);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };

  if (!id || loading) {
    return (
      <div className="flex-1 bg-slate-50 flex items-center justify-center">
        <PageTitle title="Experiment" />
        <div className="text-center" data-testid="experiment-loading">
          <div className="inline-block w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          <p className="text-slate-500 mt-2 text-sm">Loading experiment…</p>
        </div>
      </div>
    );
  }

  if (loadError || !experiment) {
    const notFound = loadError?.status === 404;
    return (
      <div className="flex-1 bg-slate-50 flex items-center justify-center">
        <PageTitle title={notFound ? 'Experiment not found' : 'Experiment'} />
        <div className="text-center max-w-md px-4" data-testid={notFound ? 'experiment-not-found' : 'experiment-error'}>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
            {notFound ? '404' : 'Error'}
          </p>
          <p className="text-slate-800 text-lg mb-2">
            {notFound ? 'Experiment not found' : 'Could not load this experiment'}
          </p>
          {!notFound && loadError?.message && (
            <p className="text-sm text-red-600 mb-4">{loadError.message}</p>
          )}
          <div className="flex items-center justify-center gap-4">
            {!notFound && (
              <button
                type="button"
                onClick={() => void load()}
                className="px-3 py-1.5 rounded-md text-sm font-medium bg-blue-600 text-white hover:bg-blue-700"
                data-testid="experiment-retry"
              >
                Retry
              </button>
            )}
            <Link href="/experiments" className="text-blue-600 hover:underline text-sm">
              &larr; Back to Experiments
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const status = experiment.status;
  const actions = ACTIONS_BY_STATUS[status] ?? [];
  const isOwner = user !== null && user.id === experiment.owner_id;
  const resultsAvailable = status !== 'draft';
  const primaryMetric = experiment.metrics.find((m) => m.is_primary) ?? experiment.metrics[0];

  return (
    <div className="flex-1 bg-slate-50" data-testid="experiment-detail">
      <PageTitle title={experiment.name} />
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-4">
          <Link href="/experiments" className="text-slate-500 hover:text-slate-700 text-sm">
            &larr; Experiments
          </Link>
        </div>

        {/* Header */}
        <div className="bg-white rounded-lg border border-slate-200 p-6 mb-6">
          <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-bold text-slate-900 break-words" data-testid="experiment-name">
                  {experiment.name}
                </h1>
                <span
                  className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${experimentStatusColor(status)}`}
                  data-testid="experiment-status"
                  data-status={status}
                >
                  {experimentStatusLabel(status)}
                </span>
              </div>
              <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-slate-600">
                <div className="flex items-center gap-1.5">
                  <dt className="text-slate-400">Key</dt>
                  <dd className="font-mono text-slate-800" data-testid="experiment-key">
                    {experiment.key ?? '—'}
                  </dd>
                  {experiment.key && (
                    <button
                      type="button"
                      onClick={() => void copyKey()}
                      className="text-xs text-blue-600 hover:underline"
                      data-testid="copy-experiment-key"
                    >
                      {copied ? 'Copied' : 'Copy'}
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-1.5">
                  <dt className="text-slate-400">Type</dt>
                  <dd data-testid="experiment-type">{experimentTypeLabel(experiment.experiment_type)}</dd>
                </div>
                <div className="flex items-center gap-1.5">
                  <dt className="text-slate-400">Owner</dt>
                  <dd data-testid="experiment-owner" title={experiment.owner_id}>
                    {isOwner ? `You (${user?.email ?? user?.username})` : shortId(experiment.owner_id)}
                  </dd>
                </div>
                <div className="flex items-center gap-1.5">
                  <dt className="text-slate-400">Created</dt>
                  <dd>{formatDate(experiment.created_at)}</dd>
                </div>
                {experiment.start_date && (
                  <div className="flex items-center gap-1.5">
                    <dt className="text-slate-400">Started</dt>
                    <dd>{formatDate(experiment.start_date)}</dd>
                  </div>
                )}
                {experiment.end_date && (
                  <div className="flex items-center gap-1.5">
                    <dt className="text-slate-400">Ended</dt>
                    <dd>{formatDate(experiment.end_date)}</dd>
                  </div>
                )}
              </dl>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap items-center gap-2 shrink-0" data-testid="experiment-actions">
              {actions.map((action) => {
                const meta = ACTION_META[action];
                const busy = pendingAction === action;
                return (
                  <button
                    key={action}
                    type="button"
                    onClick={() => onActionClick(action)}
                    disabled={pendingAction !== null}
                    className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${meta.className}`}
                    data-testid={`action-${action}`}
                  >
                    {busy ? meta.pending : meta.label}
                  </button>
                );
              })}
              {resultsAvailable ? (
                <Link
                  href={`/results/${experiment.id}`}
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-slate-900 text-white hover:bg-slate-800 transition-colors"
                  data-testid="view-results"
                >
                  View results
                </Link>
              ) : (
                <span
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-slate-100 text-slate-400 cursor-not-allowed"
                  title="Results are available once the experiment has started"
                  data-testid="view-results-disabled"
                >
                  View results
                </span>
              )}
            </div>
          </div>

          {confirming && (
            <div
              role="dialog"
              aria-label={`Confirm ${ACTION_META[confirming].label}`}
              className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3"
              data-testid="confirm-action"
            >
              <p className="text-sm text-amber-900">{ACTION_META[confirming].confirm}</p>
              <div className="flex gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => setConfirming(null)}
                  className="px-3 py-1.5 rounded-md text-sm font-medium text-slate-600 border border-slate-300 bg-white hover:bg-slate-50"
                  data-testid="confirm-cancel"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void runAction(confirming)}
                  className="px-3 py-1.5 rounded-md text-sm font-medium bg-amber-600 text-white hover:bg-amber-700"
                  data-testid="confirm-yes"
                >
                  Confirm
                </button>
              </div>
            </div>
          )}

          {actionError && (
            <div
              role="alert"
              className="mt-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700"
              data-testid="action-error"
            >
              {actionError}
            </div>
          )}

          {(experiment.description || experiment.hypothesis) && (
            <div className="mt-5 pt-5 border-t border-slate-100 grid gap-4 sm:grid-cols-2">
              {experiment.description && (
                <div>
                  <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1">
                    Description
                  </h2>
                  <p className="text-sm text-slate-700 whitespace-pre-line" data-testid="experiment-description">
                    {experiment.description}
                  </p>
                </div>
              )}
              {experiment.hypothesis && (
                <div>
                  <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-1">
                    Hypothesis
                  </h2>
                  <p className="text-sm text-slate-700 whitespace-pre-line" data-testid="experiment-hypothesis">
                    {experiment.hypothesis}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        <div className="grid gap-6 lg:grid-cols-5">
          {/* Variants */}
          <section className="lg:col-span-3 bg-white rounded-lg border border-slate-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-800">Variants</h2>
              <span className="text-xs text-slate-500">{experiment.variants.length} total</span>
            </div>
            {experiment.variants.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-500">No variants defined.</p>
            ) : (
              <table className="w-full text-sm" data-testid="variants-table">
                <thead className="bg-slate-50 border-b border-slate-200">
                  <tr>
                    <th className="text-left px-5 py-2.5 text-slate-600 font-medium">Name</th>
                    <th className="text-right px-5 py-2.5 text-slate-600 font-medium">Allocation</th>
                    <th className="text-left px-5 py-2.5 text-slate-600 font-medium">Role</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {experiment.variants.map((variant) => (
                    <tr key={variant.id} data-testid="variant-row">
                      <td className="px-5 py-3">
                        <div className="font-medium text-slate-800">{variant.name}</div>
                        {variant.description && (
                          <div className="text-xs text-slate-400 mt-0.5">{variant.description}</div>
                        )}
                      </td>
                      <td className="px-5 py-3 text-right text-slate-700 tabular-nums">
                        {variant.traffic_allocation}%
                      </td>
                      <td className="px-5 py-3">
                        {variant.is_control ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                            Control
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">Treatment</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          {/* Metrics */}
          <section className="lg:col-span-2 bg-white rounded-lg border border-slate-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-200 flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-800">Metrics</h2>
              <span className="text-xs text-slate-500">{experiment.metrics.length} total</span>
            </div>
            {experiment.metrics.length === 0 ? (
              <p className="px-5 py-6 text-sm text-slate-500" data-testid="metrics-empty">
                No metrics defined. Results need at least one metric.
              </p>
            ) : (
              <ul className="divide-y divide-slate-100" data-testid="metrics-list">
                {experiment.metrics.map((metric) => (
                  <li key={metric.id} className="px-5 py-3" data-testid="metric-row">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-slate-800">{metric.name}</span>
                      {metric.is_primary && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                          Primary
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5 flex flex-wrap gap-x-3">
                      <span>
                        event <code className="font-mono text-slate-700">{metric.event_name}</code>
                      </span>
                      <span>{METRIC_TYPE_LABELS[metric.metric_type as MetricType] ?? metric.metric_type}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {/* SDK hint */}
        {experiment.key && (
          <section className="mt-6 bg-white rounded-lg border border-slate-200 p-5" data-testid="sdk-hint">
            <h2 className="text-sm font-semibold text-slate-800 mb-1">Assign a user from your app</h2>
            <p className="text-xs text-slate-500 mb-3">
              Use the experiment key with an API key from{' '}
              <Link href="/admin/api-keys" className="text-blue-600 hover:underline">
                Admin → API Keys
              </Link>
              . Track conversions by sending the metric event name
              {primaryMetric ? (
                <>
                  {' '}
                  (<code className="font-mono">{primaryMetric.event_name}</code>)
                </>
              ) : null}{' '}
              to <code className="font-mono">/api/v1/tracking/track</code>.
            </p>
            <pre className="bg-slate-900 text-slate-100 text-xs rounded-md p-3 overflow-x-auto">
              {`curl -X POST "$API_URL/api/v1/tracking/assign" \\
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \\
  -d '{"experiment_key": "${experiment.key}", "user_id": "user-123"}'`}
            </pre>
          </section>
        )}
      </div>
    </div>
  );
}
