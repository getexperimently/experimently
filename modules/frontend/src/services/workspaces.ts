import { apiFetch } from '@/services/api';

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string;
  plan: 'free' | 'pro' | 'enterprise';
  is_active: boolean;
  max_experiments: number;
  max_feature_flags: number;
  max_members: number;
  member_count: number;
  experiment_count?: number;
  feature_flag_count?: number;
  api_key_count?: number;
  created_at: string;
  owner_username?: string;
}

export interface WorkspaceMember {
  user_id: string;
  username: string;
  email: string;
  role: 'OWNER' | 'ADMIN' | 'DEVELOPER' | 'ANALYST' | 'VIEWER';
  joined_at: string;
}

export interface WorkspaceAPIKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  is_active: boolean;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface CreateWorkspaceAPIKeyResponse extends WorkspaceAPIKey {
  key: string;
}

export interface WorkspaceInvite {
  token: string;
  workspace_name: string;
  inviter_username: string;
  email: string;
  role: string;
  expires_at: string;
}

export const workspaceService = {
  list: () =>
    apiFetch<Workspace[]>('/api/v1/workspaces/'),

  create: (data: Partial<Workspace>) =>
    apiFetch<Workspace>('/api/v1/workspaces/', { method: 'POST', json: data }),

  get: (id: string) =>
    apiFetch<Workspace>(`/api/v1/workspaces/${id}`),

  update: (id: string, data: Partial<Workspace>) =>
    apiFetch<Workspace>(`/api/v1/workspaces/${id}`, { method: 'PUT', json: data }),

  delete: (id: string) =>
    apiFetch<void>(`/api/v1/workspaces/${id}`, { method: 'DELETE' }),

  listMembers: (id: string) =>
    apiFetch<WorkspaceMember[]>(`/api/v1/workspaces/${id}/members`),

  addMember: (id: string, data: { user_id: string; role: string }) =>
    apiFetch<WorkspaceMember>(`/api/v1/workspaces/${id}/members`, { method: 'POST', json: data }),

  updateMember: (id: string, userId: string, role: string) =>
    apiFetch<WorkspaceMember>(`/api/v1/workspaces/${id}/members/${userId}`, {
      method: 'PUT',
      json: { role },
    }),

  removeMember: (id: string, userId: string) =>
    apiFetch<void>(`/api/v1/workspaces/${id}/members/${userId}`, { method: 'DELETE' }),

  sendInvite: (id: string, email: string, role: string) =>
    apiFetch<WorkspaceInvite>(`/api/v1/workspaces/${id}/invites`, {
      method: 'POST',
      json: { email, role },
    }),

  getInvite: (token: string) =>
    apiFetch<WorkspaceInvite>(`/api/v1/workspaces/invites/${token}`),

  acceptInvite: (token: string) =>
    apiFetch<{ workspace_id: string }>(`/api/v1/workspaces/invites/${token}/accept`, {
      method: 'POST',
    }),

  listAPIKeys: (id: string) =>
    apiFetch<WorkspaceAPIKey[]>(`/api/v1/workspaces/${id}/api-keys`),

  createAPIKey: (id: string, data: { name: string; scopes: string[] }) =>
    apiFetch<CreateWorkspaceAPIKeyResponse>(`/api/v1/workspaces/${id}/api-keys`, {
      method: 'POST',
      json: data,
    }),

  revokeAPIKey: (id: string, keyId: string) =>
    apiFetch<void>(`/api/v1/workspaces/${id}/api-keys/${keyId}`, { method: 'DELETE' }),

  rotateAPIKey: (id: string, keyId: string) =>
    apiFetch<CreateWorkspaceAPIKeyResponse>(
      `/api/v1/workspaces/${id}/api-keys/${keyId}/rotate`,
      { method: 'POST' }
    ),
};
