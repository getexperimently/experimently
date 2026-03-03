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

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export const AdminService = {
  // Users
  async listUsers(params?: {
    page?: number;
    limit?: number;
    search?: string;
  }): Promise<UserListResponse> {
    const url = new URL(`${API_URL}/api/v1/admin/users`);
    if (params?.page !== undefined) {
      url.searchParams.set('page', String(params.page));
    }
    if (params?.limit !== undefined) {
      url.searchParams.set('limit', String(params.limit));
    }
    if (params?.search) {
      url.searchParams.set('search', params.search);
    }
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`Failed to fetch users: ${response.statusText}`);
    }
    return response.json();
  },

  async getUser(id: string): Promise<AdminUser> {
    const response = await fetch(`${API_URL}/api/v1/admin/users/${id}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch user: ${response.statusText}`);
    }
    return response.json();
  },

  async updateUser(id: string, data: Partial<AdminUser>): Promise<AdminUser> {
    const response = await fetch(`${API_URL}/api/v1/admin/users/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      throw new Error(`Failed to update user: ${response.statusText}`);
    }
    return response.json();
  },

  async deleteUser(id: string): Promise<void> {
    const response = await fetch(`${API_URL}/api/v1/admin/users/${id}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      throw new Error(`Failed to delete user: ${response.statusText}`);
    }
  },

  // Stats
  async getStats(): Promise<AdminStats> {
    const response = await fetch(`${API_URL}/api/v1/admin/stats`);
    if (!response.ok) {
      throw new Error(`Failed to fetch stats: ${response.statusText}`);
    }
    return response.json();
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
    const url = new URL(`${API_URL}/api/v1/audit-logs/`);
    if (params?.page !== undefined) {
      url.searchParams.set('page', String(params.page));
    }
    if (params?.limit !== undefined) {
      url.searchParams.set('limit', String(params.limit));
    }
    if (params?.user_id) {
      url.searchParams.set('user_id', params.user_id);
    }
    if (params?.action_type) {
      url.searchParams.set('action_type', params.action_type);
    }
    if (params?.entity_type) {
      url.searchParams.set('entity_type', params.entity_type);
    }
    if (params?.entity_name) {
      url.searchParams.set('entity_name', params.entity_name);
    }
    if (params?.start_date) {
      url.searchParams.set('start_date', params.start_date);
    }
    if (params?.end_date) {
      url.searchParams.set('end_date', params.end_date);
    }
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`Failed to fetch audit logs: ${response.statusText}`);
    }
    return response.json();
  },

  // Roles
  async listRoles(): Promise<CustomRole[]> {
    const response = await fetch(`${API_URL}/api/v1/rbac/roles`);
    if (!response.ok) {
      throw new Error(`Failed to fetch roles: ${response.statusText}`);
    }
    return response.json();
  },

  async createRole(data: {
    name: string;
    description: string;
    permissions: string[];
  }): Promise<CustomRole> {
    const response = await fetch(`${API_URL}/api/v1/rbac/roles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      throw new Error(`Failed to create role: ${response.statusText}`);
    }
    return response.json();
  },

  async updateRole(name: string, data: Partial<CustomRole>): Promise<CustomRole> {
    const response = await fetch(`${API_URL}/api/v1/rbac/roles/${name}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      throw new Error(`Failed to update role: ${response.statusText}`);
    }
    return response.json();
  },

  async deleteRole(name: string): Promise<void> {
    const response = await fetch(`${API_URL}/api/v1/rbac/roles/${name}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      throw new Error(`Failed to delete role: ${response.statusText}`);
    }
  },

  async getUserPermissions(userId: string): Promise<{ permissions: string[] }> {
    const response = await fetch(`${API_URL}/api/v1/rbac/users/${userId}/permissions`);
    if (!response.ok) {
      throw new Error(`Failed to fetch user permissions: ${response.statusText}`);
    }
    return response.json();
  },

  // Safety
  async getSafetySettings(): Promise<SafetySettings> {
    const response = await fetch(`${API_URL}/api/v1/safety/settings`);
    if (!response.ok) {
      throw new Error(`Failed to fetch safety settings: ${response.statusText}`);
    }
    return response.json();
  },

  async updateSafetySettings(data: Partial<SafetySettings>): Promise<SafetySettings> {
    const response = await fetch(`${API_URL}/api/v1/safety/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      throw new Error(`Failed to update safety settings: ${response.statusText}`);
    }
    return response.json();
  },

  async getFlagSafetyStatus(flagId: string): Promise<FlagSafetyStatus> {
    const response = await fetch(`${API_URL}/api/v1/safety/flags/${flagId}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch flag safety status: ${response.statusText}`);
    }
    return response.json();
  },

  async rollbackFlag(flagId: string, reason: string): Promise<{ success: boolean }> {
    const response = await fetch(`${API_URL}/api/v1/safety/rollback/${flagId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    });
    if (!response.ok) {
      throw new Error(`Failed to rollback flag: ${response.statusText}`);
    }
    return response.json();
  },

  // Scheduler
  async getSchedulerHealth(): Promise<SchedulerHealth[]> {
    const response = await fetch(`${API_URL}/api/v1/scheduler/health`);
    if (!response.ok) {
      throw new Error(`Failed to fetch scheduler health: ${response.statusText}`);
    }
    return response.json();
  },

  async getSchedulerHistory(name: string): Promise<SchedulerRun[]> {
    const response = await fetch(`${API_URL}/api/v1/scheduler/${name}/history`);
    if (!response.ok) {
      throw new Error(`Failed to fetch scheduler history: ${response.statusText}`);
    }
    return response.json();
  },

  // Notification preferences
  async getMyNotificationPrefs(): Promise<NotificationPreference> {
    const response = await fetch(`${API_URL}/api/v1/notifications/preferences`);
    if (!response.ok) throw new Error(`Failed to fetch notification preferences: ${response.statusText}`);
    return response.json();
  },

  async updateMyNotificationPrefs(data: Partial<NotificationPreference>): Promise<NotificationPreference> {
    const response = await fetch(`${API_URL}/api/v1/notifications/preferences`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`Failed to update notification preferences: ${response.statusText}`);
    return response.json();
  },

  async getNotificationDeliveryLog(params?: {
    page?: number;
    limit?: number;
    event_type?: string;
    status?: string;
  }): Promise<NotificationDeliveryLogListResponse> {
    const url = new URL(`${API_URL}/api/v1/notifications/delivery-log`);
    if (params?.page !== undefined) url.searchParams.set('page', String(params.page));
    if (params?.limit !== undefined) url.searchParams.set('limit', String(params.limit));
    if (params?.event_type) url.searchParams.set('event_type', params.event_type);
    if (params?.status) url.searchParams.set('status', params.status);
    const response = await fetch(url.toString());
    if (!response.ok) throw new Error(`Failed to fetch delivery log: ${response.statusText}`);
    return response.json();
  },

  async sendTestNotification(channel: NotificationChannel, message: string, recipient?: string): Promise<{ success: boolean; channel: string; message: string }> {
    const response = await fetch(`${API_URL}/api/v1/notifications/test`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ channel, message, recipient }),
    });
    if (!response.ok) throw new Error(`Failed to send test notification: ${response.statusText}`);
    return response.json();
  },
};
