import {
  AdminUser,
  AdminStats,
  AuditLogListResponse,
  CreateUserRequest,
  CreatedUser,
  FlagHealth,
  FlagSafetyStatus,
  NotificationChannel,
  NotificationDeliveryLogListResponse,
  NotificationPreference,
  RollbackResponse,
  SafetySettings,
  SafetySettingsUpdate,
  SchedulerHealth,
  SchedulerRun,
  UserListResponse,
} from '@/types/admin';
import type { SafetyCheckResponse, SafetyMetricStatus } from '@/types/safety';
import { apiFetch } from '@/services/api';

const ERROR_RATE_METRICS = ['error_rate'];
const LATENCY_METRICS = ['latency', 'avg_latency', 'p95_latency', 'max_latency'];

function findMetric(metrics: SafetyMetricStatus[], names: string[]): SafetyMetricStatus | undefined {
  for (const name of names) {
    const hit = metrics.find((m) => m.name === name && m.details?.measured !== false);
    if (hit) return hit;
  }
  return undefined;
}

/** `critical` when the backend says unhealthy, `warning` when any metric breached its warning threshold. */
export function flagHealth(check: SafetyCheckResponse): FlagHealth {
  if (!check.is_healthy) return 'critical';
  if (check.metrics.some((m) => m.details?.warning === true)) return 'warning';
  return 'healthy';
}

/** Join a `GET /safety/feature-flags/{id}/check` response with the flag it describes. */
export function toFlagSafetyStatus(
  flag: { id: string; name: string; key: string },
  check: SafetyCheckResponse,
): FlagSafetyStatus {
  const errorRate = findMetric(check.metrics, ERROR_RATE_METRICS);
  const latency = findMetric(check.metrics, LATENCY_METRICS);
  return {
    flag_id: flag.id,
    flag_name: flag.name,
    flag_key: flag.key,
    health: flagHealth(check),
    error_rate: errorRate ? errorRate.current_value : null,
    latency_ms: latency ? latency.current_value : null,
    last_checked: check.last_checked,
    check,
  };
}

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

  /** Superuser only. There is no `POST /admin/users`; users are created via `/users/`. */
  async createUser(data: CreateUserRequest): Promise<CreatedUser> {
    return apiFetch<CreatedUser>('/api/v1/users/', { method: 'POST', json: data });
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

  // Roles, permission grants and effective permissions (`/api/v1/rbac/*`)
  // belong to the rbac module: see `modules/frontend/src/rbac.ts`, reached
  // through the `@modules/rbac` alias. They used to live here, which shipped
  // core builds with calls to routes their backend does not serve.

  // Safety (`backend/app/api/v1/endpoints/safety.py`)
  async getSafetySettings(): Promise<SafetySettings> {
    return apiFetch<SafetySettings>('/api/v1/safety/settings');
  },

  /** Superuser only. The backend upserts the single global settings row via POST. */
  async updateSafetySettings(data: SafetySettingsUpdate): Promise<SafetySettings> {
    return apiFetch<SafetySettings>('/api/v1/safety/settings', { method: 'POST', json: data });
  },

  // The per-flag safety check lives on `FeatureFlagsService.safetyCheck()` —
  // one implementation of `GET /safety/feature-flags/{id}/check`, used by the
  // flag detail page and this dashboard alike.

  /**
   * Superuser only. Rolls the flag's rollout down to `percentage` (default 0);
   * the backend takes both values as query parameters, not a JSON body.
   */
  async rollbackFlag(flagId: string, reason: string, percentage = 0): Promise<RollbackResponse> {
    return apiFetch<RollbackResponse>(`/api/v1/safety/feature-flags/${flagId}/rollback`, {
      method: 'POST',
      query: { percentage, reason: reason.trim() || undefined },
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
