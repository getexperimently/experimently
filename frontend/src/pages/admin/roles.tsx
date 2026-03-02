import React, { useState } from 'react';
import { AdminLayout } from '@/components/admin/AdminLayout';
import { RoleTable } from '@/components/admin/roles/RoleTable';
import { CreateRoleModal } from '@/components/admin/roles/CreateRoleModal';
import { CustomRole } from '@/types/admin';

export function RoleManagementPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedRole, setSelectedRole] = useState<CustomRole | null>(null);
  const [tableKey, setTableKey] = useState(0);

  const handleCreateRole = () => {
    setSelectedRole(null);
    setModalOpen(true);
  };

  const handleEditRole = (role: CustomRole) => {
    setSelectedRole(role);
    setModalOpen(true);
  };

  const handleModalClose = () => {
    setModalOpen(false);
    setSelectedRole(null);
  };

  const handleModalSuccess = () => {
    setModalOpen(false);
    setSelectedRole(null);
    // Force the RoleTable to re-fetch by changing its key
    setTableKey((k) => k + 1);
  };

  return (
    <AdminLayout title="Role Management" currentPath="/admin/roles">
      <div data-testid="role-management-page" className="space-y-6">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">Role Management</h1>
            <p className="text-sm text-slate-500 mt-1">
              Create and manage custom roles with granular permissions.
            </p>
          </div>
          <button
            data-testid="create-role-button"
            onClick={handleCreateRole}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 transition-colors"
          >
            Create Role
          </button>
        </div>

        {/* Role Table */}
        <RoleTable key={tableKey} onEditRole={handleEditRole} />

        {/* Create / Edit Modal */}
        <CreateRoleModal
          isOpen={modalOpen}
          role={selectedRole}
          onClose={handleModalClose}
          onSuccess={handleModalSuccess}
        />
      </div>
    </AdminLayout>
  );
}

export default RoleManagementPage;
