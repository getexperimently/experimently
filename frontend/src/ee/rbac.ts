/**
 * Enterprise: custom roles and direct permission grants (`/api/v1/rbac/*`).
 *
 * These five calls used to sit in `src/services/admin.ts`, a Community module,
 * which meant a Community build shipped code calling routes its backend does
 * not serve (`docs/planning/ee-coupling-report.md` §6). They now live in the
 * Enterprise tree and are reached through the `@ee/rbac` alias, which resolves
 * to `src/ee-stub/rbac.ts` when that tree is absent.
 *
 * Callers must gate on `useFeature(FEATURES.RBAC)` before invoking any of
 * these — the stub throws rather than pretending to have answered.
 */
import { apiFetch } from '@/services/api';
import { CustomRole } from '@/types/admin';

export interface CreateRoleRequest {
  name: string;
  description: string;
  permissions: string[];
}

export interface UserPermissionsResponse {
  permissions: string[];
}

export const RbacService = {
  async listRoles(): Promise<CustomRole[]> {
    return apiFetch<CustomRole[]>('/api/v1/rbac/roles');
  },

  async createRole(data: CreateRoleRequest): Promise<CustomRole> {
    return apiFetch<CustomRole>('/api/v1/rbac/roles', { method: 'POST', json: data });
  },

  async updateRole(name: string, data: Partial<CustomRole>): Promise<CustomRole> {
    return apiFetch<CustomRole>(`/api/v1/rbac/roles/${name}`, { method: 'PUT', json: data });
  },

  async deleteRole(name: string): Promise<void> {
    await apiFetch<void>(`/api/v1/rbac/roles/${name}`, { method: 'DELETE' });
  },

  async getUserPermissions(userId: string): Promise<UserPermissionsResponse> {
    return apiFetch<UserPermissionsResponse>(`/api/v1/rbac/users/${userId}/permissions`);
  },
};

export default RbacService;
