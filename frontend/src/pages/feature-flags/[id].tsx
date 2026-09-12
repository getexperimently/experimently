import React, { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { TargetingRuleBuilder } from '@/components/targeting';
import { TargetingRules } from '@/types/targeting';
import { jsonToRules } from '@/utils/targeting';
import { isApiError } from '@/services/api';
import {
  FeatureFlag,
  FeatureFlagsService,
  RolloutSchedule,
  flagRules,
  isFlagOn,
} from '@/services/featureFlags';
import type { SafetyCheckResponse } from '@/types/safety';
import { PageTitle } from '@/components/PageTitle';
import { FlagToggle } from '@/components/feature-flags/FlagToggle';

const SCHEDULE_STATUS_COLORS: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-700',
  active: 'bg-green-100 text-green-800',
  paused: 'bg-yellow-100 text-yellow-800',
  completed: 'bg-blue-100 text-blue-800',
  cancelled: 'bg-gray-100 text-gray-600',
};

const STAGE_STATUS_COLORS: Record<string, string> = {
  pending: 'bg-slate-100 text-slate-600',
  in_progress: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
};

const TRIGGER_LABELS: Record<string, string> = {
  time_based: 'Time-based',
  metric_based: 'Metric-based',
  manual: 'Manual',
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

function humanize(value: string): string {
  return value.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
}

/** Pick the schedule worth showing: active > paused > draft > most recent. */
export function pickSchedule(items: RolloutSchedule[]): RolloutSchedule | null {
  if (items.length === 0) return null;
  const rank: Record<string, number> = { active: 0, paused: 1, draft: 2, completed: 3, cancelled: 4 };
  return [...items].sort((a, b) => {
    const r = (rank[a.status] ?? 9) - (rank[b.status] ?? 9);
    if (r !== 0) return r;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  })[0];
}

export default function FeatureFlagDetailPage() {
  const router = useRouter();
  const rawId = router.query.id;
  const id = typeof rawId === 'string' ? rawId : undefined;

  const [flag, setFlag] = useState<FeatureFlag | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<{ status: number; message: string } | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // On/off
  const [toggling, setToggling] = useState(false);
  const [toggleError, setToggleError] = useState<string | null>(null);

  // Editable fields
  const [rules, setRules] = useState<TargetingRules | null>(null);
  const [rolloutPercentage, setRolloutPercentage] = useState(0);

  // Rollout schedule
  const [schedules, setSchedules] = useState<RolloutSchedule[] | null>(null);
  const [scheduleError, setScheduleError] = useState<string | null>(null);

  // Safety
  const [safety, setSafety] = useState<SafetyCheckResponse | null>(null);
  const [safetyError, setSafetyError] = useState<string | null>(null);
  const [safetyLoading, setSafetyLoading] = useState(false);

  const loadSafety = useCallback(async (flagId: string) => {
    setSafetyLoading(true);
    setSafetyError(null);
    try {
      setSafety(await FeatureFlagsService.safetyCheck(flagId));
    } catch (err) {
      setSafetyError(err instanceof Error ? err.message : 'Safety check unavailable');
    } finally {
      setSafetyLoading(false);
    }
  }, []);

  const loadSchedules = useCallback(async (flagId: string) => {
    setScheduleError(null);
    try {
      const res = await FeatureFlagsService.listRolloutSchedules(flagId);
      setSchedules(res.items ?? []);
    } catch (err) {
      setSchedules([]);
      setScheduleError(err instanceof Error ? err.message : 'Rollout schedules unavailable');
    }
  }, []);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    const fetchFlag = async () => {
      setIsLoading(true);
      setLoadError(null);
      try {
        const data = await FeatureFlagsService.get(id);
        if (cancelled) return;
        setFlag(data);
        const json = flagRules(data);
        setRules(json ? jsonToRules(json) : null);
        setRolloutPercentage(data.rollout_percentage ?? 0);
        // Secondary panels load in parallel; their failures are non-fatal.
        void loadSchedules(id);
        void loadSafety(id);
      } catch (err) {
        if (cancelled) return;
        setLoadError({
          status: isApiError(err) ? err.status : 0,
          message: err instanceof Error ? err.message : 'Failed to load feature flag',
        });
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };

    void fetchFlag();
    return () => {
      cancelled = true;
    };
  }, [id, loadSchedules, loadSafety]);

  const handleToggle = async (next: boolean) => {
    if (!flag) return;
    const previous = flag;
    setToggleError(null);
    setToggling(true);
    setFlag({ ...flag, status: next ? 'active' : 'inactive', is_active: next });
    try {
      const res = await FeatureFlagsService.setEnabled(flag.id, next);
      setFlag((current) =>
        current
          ? { ...current, status: res.status, is_active: res.status === 'active', updated_at: res.updated_at }
          : current,
      );
    } catch (err) {
      setFlag(previous);
      setToggleError(err instanceof Error ? err.message : 'Failed to update the flag');
    } finally {
      setToggling(false);
    }
  };

  const handleSave = async () => {
    if (!flag) return;
    setSaveError(null);
    setSaveSuccess(false);
    setIsSaving(true);

    try {
      const updated = await FeatureFlagsService.update(flag.id, {
        targeting_rules: rules && rules.groups.length > 0 ? rules : null,
        rollout_percentage: rolloutPercentage,
      });
      setFlag((current) => ({ ...(current ?? updated), ...updated }));
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Failed to save changes');
    } finally {
      setIsSaving(false);
    }
  };

  if (!id || isLoading) {
    return (
      <div className="flex-1 bg-slate-50 flex items-center justify-center">
        <PageTitle title="Feature Flag" />
        <div className="text-center" data-testid="flag-loading">
          <div className="inline-block w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
          <p className="text-slate-500 mt-2 text-sm">Loading feature flag...</p>
        </div>
      </div>
    );
  }

  if (loadError || !flag) {
    const notFound = loadError?.status === 404;
    return (
      <div className="flex-1 bg-slate-50 flex items-center justify-center">
        <PageTitle title={notFound ? 'Flag not found' : 'Feature Flag'} />
        <div className="text-center max-w-md px-4" data-testid={notFound ? 'flag-not-found' : 'flag-error'}>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">
            {notFound ? '404' : 'Error'}
          </p>
          <p className="text-slate-800 text-lg mb-2">
            {notFound ? 'Feature flag not found' : 'Could not load this feature flag'}
          </p>
          {!notFound && loadError?.message && (
            <p className="text-sm text-red-600 mb-4">{loadError.message}</p>
          )}
          <Link href="/feature-flags" className="text-blue-600 hover:underline text-sm">
            &larr; Back to Feature Flags
          </Link>
        </div>
      </div>
    );
  }

  const on = isFlagOn(flag);
  const schedule = schedules ? pickSchedule(schedules) : null;
  const activeStage =
    schedule?.stages.find((s) => s.status === 'in_progress') ??
    schedule?.stages.find((s) => s.status === 'pending') ??
    null;

  return (
    <div className="flex-1 bg-slate-50" data-testid="flag-detail">
      <PageTitle title={flag.name} />
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex items-center gap-4 mb-4">
          <Link href="/feature-flags" className="text-slate-500 hover:text-slate-700 text-sm">
            &larr; Feature Flags
          </Link>
        </div>

        <div className="bg-white rounded-lg border border-slate-200 p-6 mb-6">
          <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-bold text-slate-900 break-words" data-testid="flag-name">
                  {flag.name}
                </h1>
                <span
                  className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                    on ? 'bg-green-100 text-green-800' : 'bg-slate-100 text-slate-700'
                  }`}
                  data-testid="flag-status"
                  data-status={on ? 'active' : 'inactive'}
                >
                  {on ? 'On' : 'Off'}
                </span>
              </div>
              <p className="text-sm text-slate-500 mt-1 font-mono" data-testid="flag-key">
                {flag.key}
              </p>
              {flag.description && (
                <p className="text-sm text-slate-600 mt-2" data-testid="flag-description">
                  {flag.description}
                </p>
              )}
            </div>

            <div className="flex items-center gap-3 shrink-0">
              <span className="text-sm text-slate-600">{on ? 'Serving' : 'Not serving'}</span>
              <FlagToggle
                on={on}
                disabled={toggling}
                label={`Turn ${flag.key} ${on ? 'off' : 'on'}`}
                onChange={(next) => void handleToggle(next)}
                data-testid="flag-toggle"
              />
            </div>
          </div>
          {toggleError && (
            <div
              role="alert"
              className="mt-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700"
              data-testid="flag-toggle-error"
            >
              {toggleError}
            </div>
          )}
        </div>

        <div className="grid gap-6 lg:grid-cols-2 mb-6">
          {/* Rollout schedule */}
          <section className="bg-white rounded-lg border border-slate-200 p-6" data-testid="rollout-schedule-section">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-base font-semibold text-slate-800">Rollout schedule</h2>
              {schedule && (
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                    SCHEDULE_STATUS_COLORS[schedule.status] ?? 'bg-slate-100 text-slate-700'
                  }`}
                  data-testid="rollout-schedule-status"
                >
                  {humanize(schedule.status)}
                </span>
              )}
            </div>

            {schedules === null && !scheduleError && (
              <p className="text-sm text-slate-400" data-testid="rollout-schedule-loading">
                Loading…
              </p>
            )}
            {scheduleError && (
              <p className="text-sm text-red-600" data-testid="rollout-schedule-error">
                {scheduleError}
              </p>
            )}
            {schedules !== null && !scheduleError && !schedule && (
              <p className="text-sm text-slate-500" data-testid="rollout-schedule-empty">
                No rollout schedule. The rollout percentage below applies immediately; schedules
                can be created through <code className="font-mono">/api/v1/rollout-schedules</code>.
              </p>
            )}
            {schedule && (
              <div>
                <p className="text-sm text-slate-700 font-medium" data-testid="rollout-schedule-name">
                  {schedule.name}
                </p>
                <p className="text-xs text-slate-500 mt-0.5">
                  Up to {schedule.max_percentage}%
                  {activeStage ? ` · next: ${activeStage.name} → ${activeStage.target_percentage}%` : ''}
                </p>
                <ol className="mt-3 space-y-2" data-testid="rollout-stages">
                  {[...schedule.stages]
                    .sort((a, b) => a.stage_order - b.stage_order)
                    .map((stage) => (
                      <li
                        key={stage.id}
                        className="flex items-center justify-between gap-3 text-sm"
                        data-testid="rollout-stage"
                      >
                        <div className="min-w-0">
                          <span className="text-slate-800">{stage.name}</span>
                          <span className="text-xs text-slate-400 ml-2">
                            {TRIGGER_LABELS[stage.trigger_type] ?? stage.trigger_type}
                            {stage.start_date ? ` · ${formatDateTime(stage.start_date)}` : ''}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="tabular-nums text-slate-700">{stage.target_percentage}%</span>
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${
                              STAGE_STATUS_COLORS[stage.status] ?? 'bg-slate-100 text-slate-600'
                            }`}
                          >
                            {humanize(stage.status)}
                          </span>
                        </div>
                      </li>
                    ))}
                </ol>
              </div>
            )}
          </section>

          {/* Safety */}
          <section className="bg-white rounded-lg border border-slate-200 p-6" data-testid="safety-section">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-base font-semibold text-slate-800">Safety check</h2>
              <div className="flex items-center gap-2">
                {safety && (
                  <span
                    className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                      safety.is_healthy ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                    }`}
                    data-testid="safety-status"
                    data-healthy={safety.is_healthy ? 'true' : 'false'}
                  >
                    {safety.is_healthy ? 'Healthy' : 'Unhealthy'}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => void loadSafety(flag.id)}
                  disabled={safetyLoading}
                  className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                  data-testid="safety-recheck"
                >
                  {safetyLoading ? 'Checking…' : 'Re-check'}
                </button>
              </div>
            </div>

            {!safety && safetyLoading && (
              <p className="text-sm text-slate-400" data-testid="safety-loading">Checking…</p>
            )}
            {safetyError && (
              <p className="text-sm text-red-600" data-testid="safety-error">{safetyError}</p>
            )}
            {safety && (
              <div>
                {safety.metrics.length === 0 ? (
                  <p className="text-sm text-slate-500">No safety metrics recorded yet.</p>
                ) : (
                  <ul className="space-y-2" data-testid="safety-metrics">
                    {safety.metrics.map((m) => (
                      <li
                        key={m.name}
                        className="flex items-center justify-between gap-3 text-sm"
                        data-testid="safety-metric"
                      >
                        <span className="text-slate-800">{humanize(m.name)}</span>
                        <span className="flex items-center gap-2 shrink-0">
                          <span className="tabular-nums text-slate-700">
                            {m.current_value}
                            {m.unit ? ` ${m.unit}` : ''}{' '}
                            <span className="text-slate-400">/ {m.threshold}{m.unit ? ` ${m.unit}` : ''}</span>
                          </span>
                          <span
                            className={`inline-block h-2 w-2 rounded-full ${m.is_healthy ? 'bg-green-500' : 'bg-red-500'}`}
                            aria-label={m.is_healthy ? 'healthy' : 'unhealthy'}
                          />
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                <p className="text-xs text-slate-400 mt-3" data-testid="safety-last-checked">
                  Last checked {formatDateTime(safety.last_checked)}
                </p>
              </div>
            )}
          </section>
        </div>

        <div className="space-y-6">
          {/* Targeting Rules */}
          <section className="bg-white rounded-lg border border-slate-200 p-6">
            <TargetingRuleBuilder
              value={rules}
              onChange={setRules}
              data-testid="targeting-rule-builder"
            />
          </section>

          {/* Rollout Percentage */}
          <section className="bg-white rounded-lg border border-slate-200 p-6 space-y-4">
            <h2 className="text-base font-semibold text-slate-800">Rollout</h2>
            <div>
              <div className="flex items-center justify-between mb-2">
                <label htmlFor="rollout-percentage" className="text-sm font-medium text-slate-700">
                  Rollout percentage
                </label>
                <span className="text-sm font-semibold text-slate-900" data-testid="rollout-value">
                  {rolloutPercentage}%
                </span>
              </div>
              <input
                id="rollout-percentage"
                name="rollout_percentage"
                type="range"
                min={0}
                max={100}
                value={rolloutPercentage}
                onChange={(e) => setRolloutPercentage(Number(e.target.value))}
                className="w-full accent-blue-600"
                data-testid="rollout-percentage"
              />
              <div className="flex justify-between text-xs text-slate-400 mt-1">
                <span>0%</span>
                <span>100%</span>
              </div>
            </div>
          </section>

          {saveError && (
            <div
              role="alert"
              className="rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700"
              data-testid="save-error"
            >
              {saveError}
            </div>
          )}
          {saveSuccess && (
            <div
              role="status"
              className="rounded-lg bg-green-50 border border-green-200 p-3 text-sm text-green-700"
              data-testid="save-success"
            >
              Changes saved successfully.
            </div>
          )}

          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={isSaving}
              className="px-6 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              data-testid="save-flag"
            >
              {isSaving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
