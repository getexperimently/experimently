import React, { useState } from 'react';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { UserTable } from '@/components/admin/users/UserTable';
import { InviteUserModal } from '@/components/admin/users/InviteUserModal';
import { EditUserModal } from '@/components/admin/users/EditUserModal';
import { EffectivePermissionsModal } from '@/components/admin/users/EffectivePermissionsModal';
import { AdminUser } from '@/types/admin';
import { AdminService } from '@/services/admin';

export function UserManagementPage() {
  const [inviteOpen, setInviteOpen] = useState(false);
  const [editUser, setEditUser] = useState<AdminUser | null>(null);
  const [permissionsUser, setPermissionsUser] = useState<AdminUser | null>(null);
  // Key to force re-mount of UserTable after invite/edit
  const [tableKey, setTableKey] = useState(0);

  const handleInviteSuccess = () => {
    setTableKey((k) => k + 1);
  };

  const handleSaveUser = async (userId: string, data: Partial<AdminUser>) => {
    try {
      await AdminService.updateUser(userId, data);
      setEditUser(null);
      setTableKey((k) => k + 1);
    } catch (err) {
      alert(`Failed to update user: ${(err as Error).message}`);
    }
  };

  return (
    <AdminLayout title="User Management" currentPath="/admin/users">
      <div data-testid="user-management-page">
        {/* Page Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-semibold text-slate-900">User Management</h1>
            <p className="text-sm text-slate-500 mt-1">
              Manage platform users, roles, and permissions.
            </p>
          </div>
          <button
            data-testid="invite-user-button"
            onClick={() => setInviteOpen(true)}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            Invite User
          </button>
        </div>

        {/* User Table */}
        <UserTable key={tableKey} />

        {/* Invite Modal */}
        <InviteUserModal
          isOpen={inviteOpen}
          onClose={() => setInviteOpen(false)}
          onSuccess={handleInviteSuccess}
        />

        {/* Edit Modal */}
        <EditUserModal
          isOpen={editUser !== null}
          user={editUser}
          onClose={() => setEditUser(null)}
          onSave={handleSaveUser}
        />

        {/* Effective Permissions Modal */}
        <EffectivePermissionsModal
          isOpen={permissionsUser !== null}
          userId={permissionsUser?.id ?? null}
          userEmail={permissionsUser?.email}
          onClose={() => setPermissionsUser(null)}
        />
      </div>
    </AdminLayout>
  );
}

export default UserManagementPage;
