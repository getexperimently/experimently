export type UserRole = 'ADMIN' | 'DEVELOPER' | 'ANALYST' | 'VIEWER';

export interface AdminUser {
  id: string;
  username: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
  last_login?: string;
}

export interface CustomRole {
  name: string;
  description: string;
  permissions: string[];
  created_at: string;
}

export interface AuditLog {
  id: string;
  user_id: string;
  user_email: string;
  action_type: string;
  entity_type: string;
  entity_id: string;
  entity_name: string;
  old_value?: unknown;
  new_value?: unknown;
  reason?: string;
  timestamp: string;
  created_at: string;
  action_description: string;
}

export interface SafetySettings {
  error_rate_threshold: number;
  latency_threshold_ms: number;
  rollback_policy: 'auto' | 'manual';
  monitoring_window_minutes: number;
}

export interface FlagSafetyStatus {
  flag_id: string;
  flag_name: string;
  current_error_rate: number;
  current_latency_ms: number;
  status: 'healthy' | 'warning' | 'critical';
}

export interface RollbackRecord {
  id: string;
  flag_id: string;
  flag_name: string;
  rolled_back_by: string;
  reason: string;
  timestamp: string;
}

export interface SchedulerHealth {
  name: string;
  status: 'running' | 'idle' | 'error';
  last_run: string;
  next_run: string;
  run_count: number;
  error_count: number;
}

export interface SchedulerRun {
  id: string;
  scheduler_name: string;
  started_at: string;
  completed_at: string;
  duration_ms: number;
  outcome: 'success' | 'error';
  error_message?: string;
}

export interface AdminStats {
  total_experiments: number;
  active_experiments: number;
  total_feature_flags: number;
  active_feature_flags: number;
  total_users: number;
}

export interface UserListResponse {
  items: AdminUser[];
  total: number;
  page: number;
  limit: number;
}

export interface AuditLogListResponse {
  items: AuditLog[];
  total: number;
  page: number;
  limit: number;
}

export const ROLE_COLORS: Record<UserRole, string> = {
  ADMIN: 'bg-red-100 text-red-800',
  DEVELOPER: 'bg-blue-100 text-blue-800',
  ANALYST: 'bg-purple-100 text-purple-800',
  VIEWER: 'bg-slate-100 text-slate-700',
};

export const USER_ROLE_LABELS: Record<UserRole, string> = {
  ADMIN: 'Admin',
  DEVELOPER: 'Developer',
  ANALYST: 'Analyst',
  VIEWER: 'Viewer',
};
