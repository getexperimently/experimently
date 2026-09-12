import React, { useEffect, useState } from 'react';
import { RbacService } from '@ee/rbac';

interface EffectivePermissionsModalProps {
  isOpen: boolean;
  userId: string | null;
  userEmail?: string;
  onClose: () => void;
}

export function EffectivePermissionsModal({
  isOpen,
  userId,
  userEmail,
  onClose,
}: EffectivePermissionsModalProps) {
  const [permissions, setPermissions] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen && userId) {
      setLoading(true);
      setError(null);
      setPermissions([]);

      RbacService.getUserPermissions(userId)
        .then((data) => {
          setPermissions(data.permissions);
        })
        .catch((err: Error) => {
          setError(err.message || 'Failed to load permissions');
        })
        .finally(() => {
          setLoading(false);
        });
    }
  }, [isOpen, userId]);

  if (!isOpen) return null;

  return (
    <div
      data-testid="effective-permissions-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="permissions-modal-title"
    >
      <div className="bg-white rounded-lg shadow-xl w-full max-w-lg mx-4 p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 id="permissions-modal-title" className="text-lg font-semibold text-slate-900">
              Effective Permissions
            </h2>
            {userEmail && (
              <p className="text-sm text-slate-500 mt-0.5">{userEmail}</p>
            )}
          </div>
          <button
            type="button"
            data-testid="permissions-close-button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600"
            aria-label="Close"
          >
            <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Loading */}
        {loading && (
          <div data-testid="permissions-loading" className="py-8 text-center text-slate-500">
            <div className="inline-block animate-spin h-6 w-6 border-2 border-blue-500 border-t-transparent rounded-full" />
            <p className="mt-2 text-sm">Loading permissions...</p>
          </div>
        )}

        {/* Error */}
        {!loading && error && (
          <div
            data-testid="permissions-error"
            className="p-4 bg-red-50 border border-red-200 rounded-md text-sm text-red-700"
          >
            {error}
          </div>
        )}

        {/* Permissions List */}
        {!loading && !error && (
          <>
            {permissions.length === 0 ? (
              <p className="text-sm text-slate-500 py-4">No permissions assigned.</p>
            ) : (
              <div
                data-testid="permissions-list"
                className="flex flex-wrap gap-2 py-2"
              >
                {permissions.map((perm) => (
                  <span
                    key={perm}
                    className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-50 text-blue-800 border border-blue-200"
                  >
                    {perm}
                  </span>
                ))}
              </div>
            )}
          </>
        )}

        {/* Close */}
        <div className="mt-6 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
