import React, { useState } from 'react';
import { useRouter } from 'next/router';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { SafetySettingsForm } from '@/components/admin/safety/SafetySettingsForm';
import { SafetyStatusCard } from '@/components/admin/safety/SafetyStatusCard';
import { RollbackHistoryTable } from '@/components/admin/safety/RollbackHistoryTable';
import { AdminService } from '@/services/admin';
import { FlagSafetyStatus, RollbackRecord } from '@/types/admin';

const MOCK_FLAGS: FlagSafetyStatus[] = [
  {
    flag_id: 'flag-001',
    flag_name: 'checkout-v2',
    current_error_rate: 1.2,
    current_latency_ms: 95,
    status: 'healthy',
  },
  {
    flag_id: 'flag-002',
    flag_name: 'payments-redesign',
    current_error_rate: 6.8,
    current_latency_ms: 420,
    status: 'warning',
  },
  {
    flag_id: 'flag-003',
    flag_name: 'auth-service-v3',
    current_error_rate: 15.3,
    current_latency_ms: 850,
    status: 'critical',
  },
];

const STATIC_ROLLBACKS: RollbackRecord[] = [];

interface RollbackModal {
  flagId: string;
  flagName: string;
}

export function SafetyDashboard() {
  const router = useRouter();
  const [rollbackModal, setRollbackModal] = useState<RollbackModal | null>(null);
  const [rollbackReason, setRollbackReason] = useState('');
  const [rollbackSuccess, setRollbackSuccess] = useState(false);
  const [rollbackError, setRollbackError] = useState<string | null>(null);
  const [rolling, setRolling] = useState(false);

  const handleRollback = (flagId: string) => {
    const flag = MOCK_FLAGS.find((f) => f.flag_id === flagId);
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
      await AdminService.rollbackFlag(rollbackModal.flagId, rollbackReason);
      setRollbackSuccess(true);
    } catch (err) {
      setRollbackError((err as Error).message || 'Rollback failed');
    } finally {
      setRolling(false);
    }
  };

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
          <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Flag Safety Status
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {MOCK_FLAGS.map((flag) => (
              <SafetyStatusCard
                key={flag.flag_id}
                flag={flag}
                onRollback={handleRollback}
              />
            ))}
          </div>
        </section>

        {/* Rollback History */}
        <section>
          <h2 className="text-sm font-semibold text-slate-500 uppercase tracking-wider mb-3">
            Rollback History
          </h2>
          <RollbackHistoryTable rollbacks={STATIC_ROLLBACKS} />
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
              . This action will disable the flag immediately.
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

export default SafetyDashboard;
