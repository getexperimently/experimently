import React, { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { SafetySettingsForm } from '@/components/admin/safety/SafetySettingsForm';
import { SafetyStatusCard } from '@/components/admin/safety/SafetyStatusCard';
import { RollbackHistoryTable } from '@/components/admin/safety/RollbackHistoryTable';
import { AdminService, toFlagSafetyStatus } from '@/services/admin';
import { isApiError } from '@/services/api';
import { FeatureFlagsService } from '@/services/featureFlags';
import { useOptionalAuth } from '@/contexts/AuthContext';
import { FlagSafetyStatus, RollbackRecord } from '@/types/admin';
import { mapWithConcurrency } from '@/utils/concurrency';
import { withAdminGuard } from '@/components/admin/withAdminGuard';

interface RollbackModal {
  flagId: string;
  flagName: string;
}

/**
 * How many `/safety/feature-flags/{id}/check` calls may be in flight at once.
 * Each one runs aggregate queries over `error_logs` and `raw_metrics`, and the
 * non-SDK rate limit is 300 req/min per IP — fanning out one request per flag
 * would spend a third of that budget (and hammer the DB) in a single page view.
 */
export const SAFETY_CHECK_CONCURRENCY = 5;

/** A flag whose safety check did not come back, and why. */
interface FailedCheck {
  key: string;
  /** HTTP 429: the check is fine, we simply asked too often. */
  rateLimited: boolean;
}

/**
 * Load every flag and run `GET /safety/feature-flags/{id}/check` for each,
 * at most `SAFETY_CHECK_CONCURRENCY` at a time. A flag whose check fails is
 * dropped from the grid and reported in `failed`.
 */
/** Flags checked per page load; the grid says so when more exist. */
export const SAFETY_FLAG_LIMIT = 100;

async function loadFlagStatuses(): Promise<{
  statuses: FlagSafetyStatus[];
  failed: FailedCheck[];
  total: number;
}> {
  const { items, total } = await FeatureFlagsService.list({ limit: SAFETY_FLAG_LIMIT });
  const results = await mapWithConcurrency(items, SAFETY_CHECK_CONCURRENCY, async (flag) =>
    toFlagSafetyStatus(flag, await FeatureFlagsService.safetyCheck(flag.id)),
  );
  const statuses: FlagSafetyStatus[] = [];
  const failed: FailedCheck[] = [];
  results.forEach((result, i) => {
    if (result.status === 'fulfilled') statuses.push(result.value);
    else {
      failed.push({
        key: items[i].key,
        rateLimited: isApiError(result.reason) && result.reason.status === 429,
      });
    }
  });
  return { statuses, failed, total };
}

export function SafetyDashboard() {
  const router = useRouter();
  const user = useOptionalAuth()?.user ?? null;
  const [flags, setFlags] = useState<FlagSafetyStatus[]>([]);
  const [flagsLoading, setFlagsLoading] = useState(true);
  const [totalFlags, setTotalFlags] = useState(0);
  const [flagsError, setFlagsError] = useState<string | null>(null);
  const [failedChecks, setFailedChecks] = useState<FailedCheck[]>([]);
  const [rollbacks, setRollbacks] = useState<RollbackRecord[]>([]);
  const [rollbackModal, setRollbackModal] = useState<RollbackModal | null>(null);
  const [rollbackReason, setRollbackReason] = useState('');
  const [rollbackSuccess, setRollbackSuccess] = useState(false);
  const [rollbackError, setRollbackError] = useState<string | null>(null);
  const [rolling, setRolling] = useState(false);

  const refreshFlags = useCallback(async () => {
    setFlagsLoading(true);
    setFlagsError(null);
    try {
      const { statuses, failed, total } = await loadFlagStatuses();
      setFlags(statuses);
      setFailedChecks(failed);
      setTotalFlags(total ?? statuses.length);
    } catch (err) {
      setFlagsError((err as Error).message || 'Failed to load flag safety status');
    } finally {
      setFlagsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshFlags();
  }, [refreshFlags]);

  const handleRollback = (flagId: string) => {
    const flag = flags.find((f) => f.flag_id === flagId);
    if (!flag) return;
    setRollbackModal({ flagId, flagName: flag.flag_name });
    setRollbackReason('');
    setRollbackSuccess(false);
    setRollbackError(null);
  };

  const handleConfirmRollback = async () => {
    if (!rollbackModal) return;
    setRolling(true);
    setRollbackError(null);
    try {
      const result = await AdminService.rollbackFlag(rollbackModal.flagId, rollbackReason);
      if (!result.success) {
        throw new Error(result.message || 'Rollback failed');
      }
      setRollbacks((prev) => [
        {
          id: result.rollback_record_id ?? `${result.feature_flag_id}-${result.timestamp}`,
          flag_id: result.feature_flag_id,
          flag_name: rollbackModal.flagName,
          rolled_back_by: user?.email ?? user?.username ?? 'you',
          reason: rollbackReason.trim() || result.message,
          timestamp: result.timestamp,
          previous_percentage: result.previous_percentage,
          new_percentage: result.new_percentage,
        },
        ...prev,
      ]);
      setRollbackSuccess(true);
      void refreshFlags();
    } catch (err) {
      setRollbackError((err as Error).message || 'Rollback failed');
    } finally {
      setRolling(false);
    }
  };

  const rateLimitedKeys = failedChecks.filter((f) => f.rateLimited).map((f) => f.key);
  const erroredKeys = failedChecks.filter((f) => !f.rateLimited).map((f) => f.key);

  const handleCloseModal = () => {
    setRollbackModal(null);
    setRollbackReason('');
    setRollbackSuccess(false);
    setRollbackError(null);
  };

  return (
    <AdminLayout title="Safety" currentPath={router.pathname}>
      <div data-testid="safety-dashboard" className="flex flex-col gap-8">
        {/* Safety Settings Form */}
        <section>
          <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Global Safety Settings
          </h2>
          <SafetySettingsForm />
        </section>

        {/* Flag Safety Status Cards */}
        <section data-testid="flag-status-section">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider">
              Flag Safety Status
            </h2>
            <button
              type="button"
              data-testid="refresh-flags-button"
              onClick={() => void refreshFlags()}
              disabled={flagsLoading}
              className="text-xs font-medium text-blue-600 hover:text-blue-800 disabled:opacity-50"
            >
              {flagsLoading ? 'Checking…' : 'Re-check'}
            </button>
          </div>

          {flagsError && (
            <div
              data-testid="flag-status-error"
              className="bg-red-50 border border-red-200 rounded p-3 text-red-700 text-sm mb-3"
            >
              {flagsError}
            </div>
          )}

          {totalFlags > SAFETY_FLAG_LIMIT && (
            <p data-testid="flag-limit-notice" className="text-xs text-slate-500">
              Showing the first {SAFETY_FLAG_LIMIT} of {totalFlags} flags.
            </p>
          )}

          {failedChecks.length > 0 && (
            <div
              data-testid="flag-status-partial"
              className="bg-yellow-50 border border-yellow-200 rounded p-3 text-yellow-800 text-sm mb-3 flex flex-col gap-1"
            >
              {rateLimitedKeys.length > 0 && (
                <span data-testid="flag-status-rate-limited">
                  Rate limited, retry in a moment: {rateLimitedKeys.join(', ')}
                </span>
              )}
              {erroredKeys.length > 0 && (
                <span data-testid="flag-status-failed">
                  Safety check failed for: {erroredKeys.join(', ')}
                </span>
              )}
            </div>
          )}

          {flagsLoading && flags.length === 0 ? (
            <div data-testid="flag-status-loading" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-32 bg-slate-100 rounded-lg animate-pulse" />
              ))}
            </div>
          ) : flags.length === 0 && !flagsError ? (
            <div
              data-testid="flag-status-empty"
              className="bg-slate-50 border border-slate-200 rounded-lg p-8 text-center text-sm text-slate-500"
            >
              No feature flags yet. Safety checks appear here once flags exist.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {flags.map((flag) => (
                <SafetyStatusCard key={flag.flag_id} flag={flag} onRollback={handleRollback} />
              ))}
            </div>
          )}
        </section>

        {/* Rollback History */}
        <section>
          <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Rollbacks this session
          </h2>
          <RollbackHistoryTable rollbacks={rollbacks} />
        </section>
      </div>

      {/* Rollback Confirmation Modal */}
      {rollbackModal && (
        <div
          data-testid="rollback-modal"
          className="fixed inset-0 bg-black bg-opacity-40 flex items-center justify-center z-50 p-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md p-6 flex flex-col gap-4">
            <h3 className="text-base font-semibold text-slate-800">Confirm Rollback</h3>

            <p className="text-sm text-slate-600">
              You are about to roll back flag{' '}
              <span
                data-testid="rollback-modal-flag-name"
                className="font-mono font-semibold text-slate-800"
              >
                {rollbackModal.flagName}
              </span>
              . Its rollout percentage will be set to 0% immediately; the flag stays active.
            </p>

            {!rollbackSuccess && (
              <div className="flex flex-col gap-1">
                <label
                  htmlFor="rollback-reason"
                  className="text-sm font-medium text-slate-700"
                >
                  Reason (optional)
                </label>
                <input
                  id="rollback-reason"
                  data-testid="rollback-reason-input"
                  type="text"
                  value={rollbackReason}
                  onChange={(e) => setRollbackReason(e.target.value)}
                  placeholder="e.g. High error rate detected"
                  className="border border-slate-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-400"
                />
              </div>
            )}

            {rollbackError && (
              <div
                data-testid="rollback-error"
                className="bg-red-50 border border-red-200 rounded p-3 text-red-700 text-sm"
              >
                {rollbackError}
              </div>
            )}

            {rollbackSuccess && (
              <div
                data-testid="rollback-success-message"
                className="bg-green-50 border border-green-200 rounded p-3 text-green-700 text-sm"
              >
                Rollback for <strong>{rollbackModal.flagName}</strong> completed successfully.
              </div>
            )}

            <div className="flex justify-end gap-3">
              <button
                data-testid="rollback-cancel-button"
                onClick={handleCloseModal}
                className="px-4 py-2 text-sm font-medium border border-slate-300 rounded hover:bg-slate-50 transition-colors"
              >
                {rollbackSuccess ? 'Close' : 'Cancel'}
              </button>
              {!rollbackSuccess && (
                <button
                  data-testid="rollback-confirm-button"
                  onClick={handleConfirmRollback}
                  disabled={rolling}
                  className="px-4 py-2 text-sm font-medium bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {rolling ? 'Rolling back...' : 'Confirm Rollback'}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </AdminLayout>
  );
}

export default withAdminGuard(SafetyDashboard);
