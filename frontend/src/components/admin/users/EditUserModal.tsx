import React, { useEffect, useState } from 'react';
import { AdminUser, UserRole, USER_ROLE_LABELS } from '@/types/admin';

interface EditUserModalProps {
  isOpen: boolean;
  user: AdminUser | null;
  onClose: () => void;
  onSave: (userId: string, data: Partial<AdminUser>) => void;
}

const ROLES: UserRole[] = ['ADMIN', 'DEVELOPER', 'ANALYST', 'VIEWER'];

export function EditUserModal({ isOpen, user, onClose, onSave }: EditUserModalProps) {
  const [role, setRole] = useState<UserRole>('VIEWER');
  const [isActive, setIsActive] = useState(true);
  const [showDeactivateWarning, setShowDeactivateWarning] = useState(false);

  // Sync form state when user changes
  useEffect(() => {
    if (user) {
      setRole(user.role);
      setIsActive(user.is_active);
      setShowDeactivateWarning(false);
    }
  }, [user]);

  if (!isOpen || !user) return null;

  const handleActiveToggle = () => {
    const newValue = !isActive;
    setIsActive(newValue);
    // Show warning when switching an active user to inactive
    if (user.is_active && !newValue) {
      setShowDeactivateWarning(true);
    } else {
      setShowDeactivateWarning(false);
    }
  };

  const handleSave = () => {
    onSave(user.id, { role, is_active: isActive });
  };

  const handleClose = () => {
    // Reset local state to original
    setRole(user.role);
    setIsActive(user.is_active);
    setShowDeactivateWarning(false);
    onClose();
  };

  return (
    <div
      data-testid="edit-user-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby="edit-modal-title"
    >
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-6">
        <h2 id="edit-modal-title" className="text-lg font-semibold text-slate-900 mb-1">
          Edit User
        </h2>
        <p className="text-sm text-slate-500 mb-4">{user.email}</p>

        {/* Role */}
        <div className="mb-4">
          <label
            htmlFor="edit-role"
            className="block text-sm font-medium text-slate-700 mb-1"
          >
            Role
          </label>
          <select
            id="edit-role"
            data-testid="edit-role-select"
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
            className="w-full px-3 py-2 border border-slate-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {USER_ROLE_LABELS[r]}
              </option>
            ))}
          </select>
        </div>

        {/* Active toggle */}
        <div className="mb-4">
          <div className="flex items-center gap-3">
            <input
              id="edit-active"
              data-testid="edit-active-toggle"
              type="checkbox"
              checked={isActive}
              onChange={handleActiveToggle}
              className="h-4 w-4 text-blue-600 border-slate-300 rounded focus:ring-blue-500"
            />
            <label htmlFor="edit-active" className="text-sm font-medium text-slate-700">
              Active
            </label>
          </div>

          {/* Deactivation warning */}
          {showDeactivateWarning && (
            <div
              data-testid="deactivate-warning"
              className="mt-2 p-3 bg-amber-50 border border-amber-200 rounded-md text-sm text-amber-800"
            >
              This will prevent the user from logging in.
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3 mt-6">
          <button
            type="button"
            data-testid="edit-cancel-button"
            onClick={handleClose}
            className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-md hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            data-testid="edit-save-button"
            onClick={handleSave}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700"
          >
            Save Changes
          </button>
        </div>
      </div>
    </div>
  );
}
