import {
  AdminUser,
  AdminStats,
  AuditLogListResponse,
  CustomRole,
  FlagSafetyStatus,
  NotificationChannel,
  NotificationDeliveryLogListResponse,
  NotificationPreference,
  SafetySettings,
  SchedulerHealth,
  SchedulerRun,
  UserListResponse,
} from '@/types/admin';
import { apiFetch } from '@/services/api';

export const AdminService = {
  // Users
  async listUsers(params?: {
    page?: number;
    limit?: number;
    search?: string;
  }): Promise<UserListResponse> {
    return apiFetch<UserListResponse>('/api/v1/admin/users', {
      query: {
        page: params?.page,
        limit: params?.limit,
        search: params?.search || undefined,
      },
    });
  },

  async getUser(id: string): Promise<AdminUser> {
    return apiFetch<AdminUser>(`/api/v1/admin/users/${id}`);
  },

  async updateUser(id: string, data: Partial<AdminUser>): Promise<AdminUser> {
    return apiFetch<AdminUser>(`/api/v1/admin/users/${id}`, { method: 'PUT', json: data });
  },

  async deleteUser(id: string): Promise<void> {
    await apiFetch<void>(`/api/v1/admin/users/${id}`, { method: 'DELETE' });
  },

  // Stats
  async getStats(): Promise<AdminStats> {
    return apiFetch<AdminStats>('/api/v1/admin/stats');
  },

  // Audit logs
  async listAuditLogs(params?: {
    page?: number;
    limit?: number;
    user_id?: string;
    action_type?: string;
    entity_type?: string;
    entity_name?: string;
    start_date?: string;
    end_date?: string;
  }): Promise<AuditLogListResponse> {
    return apiFetch<AuditLogListResponse>('/api/v1/audit-logs/', {
      query: {
        page: params?.page,
        limit: params?.limit,
        user_id: params?.user_id || undefined,
        action_type: params?.action_type || undefined,
        entity_type: params?.entity_type || undefined,
        entity_name: params?.entity_name || undefined,
        start_date: params?.start_date || undefined,
        end_date: params?.end_date || undefined,
      },
    });
  },

  // Roles
  async listRoles(): Promise<CustomRole[]> {
    return apiFetch<CustomRole[]>('/api/v1/rbac/roles');
  },

  async createRole(data: {
    name: string;
    description: string;
    permissions: string[];
  }): Promise<CustomRole> {
    return apiFetch<CustomRole>('/api/v1/rbac/roles', { method: 'POST', json: data });
  },

  async updateRole(name: string, data: Partial<CustomRole>): Promise<CustomRole> {
    return apiFetch<CustomRole>(`/api/v1/rbac/roles/${name}`, { method: 'PUT', json: data });
  },

  async deleteRole(name: string): Promise<void> {
    await apiFetch<void>(`/api/v1/rbac/roles/${name}`, { method: 'DELETE' });
  },

  async getUserPermissions(userId: string): Promise<{ permissions: string[] }> {
    return apiFetch<{ permissions: string[] }>(`/api/v1/rbac/users/${userId}/permissions`);
  },

  // Safety
  async getSafetySettings(): Promise<SafetySettings> {
    return apiFetch<SafetySettings>('/api/v1/safety/settings');
  },

  async updateSafetySettings(data: Partial<SafetySettings>): Promise<SafetySettings> {
    return apiFetch<SafetySettings>('/api/v1/safety/settings', { method: 'PUT', json: data });
  },

  async getFlagSafetyStatus(flagId: string): Promise<FlagSafetyStatus> {
    return apiFetch<FlagSafetyStatus>(`/api/v1/safety/flags/${flagId}`);
  },

  async rollbackFlag(flagId: string, reason: string): Promise<{ success: boolean }> {
    return apiFetch<{ success: boolean }>(`/api/v1/safety/rollback/${flagId}`, {
      method: 'POST',
      json: { reason },
    });
  },

  // Scheduler
  async getSchedulerHealth(): Promise<SchedulerHealth[]> {
    return apiFetch<SchedulerHealth[]>('/api/v1/scheduler/health');
  },

  async getSchedulerHistory(name: string): Promise<SchedulerRun[]> {
    return apiFetch<SchedulerRun[]>(`/api/v1/scheduler/${name}/history`);
  },

  // Notification preferences
  async getMyNotificationPrefs(): Promise<NotificationPreference> {
    return apiFetch<NotificationPreference>('/api/v1/notifications/preferences');
  },

  async updateMyNotificationPrefs(data: Partial<NotificationPreference>): Promise<NotificationPreference> {
    return apiFetch<NotificationPreference>('/api/v1/notifications/preferences', {
      method: 'PUT',
      json: data,
    });
  },

  async getNotificationDeliveryLog(params?: {
    page?: number;
    limit?: number;
    event_type?: string;
    status?: string;
  }): Promise<NotificationDeliveryLogListResponse> {
    return apiFetch<NotificationDeliveryLogListResponse>('/api/v1/notifications/delivery-log', {
      query: {
        page: params?.page,
        limit: params?.limit,
        event_type: params?.event_type || undefined,
        status: params?.status || undefined,
      },
    });
  },

  async sendTestNotification(channel: NotificationChannel, message: string, recipient?: string): Promise<{ success: boolean; channel: string; message: string }> {
    return apiFetch<{ success: boolean; channel: string; message: string }>('/api/v1/notifications/test', {
      method: 'POST',
      json: { channel, message, recipient },
    });
  },
};
