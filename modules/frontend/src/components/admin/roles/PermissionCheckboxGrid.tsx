import React from 'react';

interface PermissionCheckboxGridProps {
  selectedPermissions: string[];
  onChange: (permissions: string[]) => void;
  readOnly?: boolean;
}

const PERMISSION_GROUPS: Record<string, string[]> = {
  experiments: ['experiments:read', 'experiments:create', 'experiments:update', 'experiments:delete'],
  feature_flags: ['feature_flags:read', 'feature_flags:create', 'feature_flags:update', 'feature_flags:delete'],
  users: ['users:read', 'users:create', 'users:update', 'users:delete'],
  audit_logs: ['audit_logs:read'],
  safety: ['safety:read', 'safety:update'],
  rbac: ['rbac:read', 'rbac:manage'],
};

function getActionLabel(permission: string): string {
  const action = permission.split(':')[1];
  return action.charAt(0).toUpperCase() + action.slice(1);
}

export function PermissionCheckboxGrid({
  selectedPermissions,
  onChange,
  readOnly = false,
}: PermissionCheckboxGridProps) {
  const handleToggle = (permission: string) => {
    if (selectedPermissions.includes(permission)) {
      onChange(selectedPermissions.filter((p) => p !== permission));
    } else {
      onChange([...selectedPermissions, permission]);
    }
  };

  return (
    <div data-testid="permission-checkbox-grid" className="space-y-4">
      {Object.entries(PERMISSION_GROUPS).map(([group, permissions]) => (
        <div key={group} className="border border-slate-200 rounded-lg p-4">
          <h4 className="text-sm font-semibold text-slate-700 mb-3 uppercase tracking-wide">
            {group}
          </h4>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {permissions.map((permission) => (
              <label
                key={permission}
                className="flex items-center gap-2 cursor-pointer"
              >
                <input
                  type="checkbox"
                  data-testid={`permission-checkbox-${permission}`}
                  checked={selectedPermissions.includes(permission)}
                  onChange={() => handleToggle(permission)}
                  disabled={readOnly}
                  className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:opacity-50"
                />
                <span className="text-sm text-slate-600">
                  {getActionLabel(permission)}
                </span>
              </label>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
