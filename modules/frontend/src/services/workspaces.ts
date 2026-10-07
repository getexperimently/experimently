import { apiFetch } from '@/services/api';

export interface Workspace {
  id: string;
  name: string;
  slug: string;
  description: string;
  is_active: boolean;
  /** From the list and a workspace's own read; a create does not answer it. */
  member_count?: number;
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

export interface WorkspaceInvite {
  token: string;
  workspace_name: string;
  /**
   * `null` when the inviting account no longer exists. The invitation preview
   * returns it only to the account the invitation was sent to.
   */
  inviter_username: string | null;
  /** The invited address; the preview masks it for anyone but the invitee. */
  email: string;
  role: string;
  expires_at: string;
  accepted_at: string | null;
}

/** What a create accepts; the server refuses any other field with 422. */
export interface CreateWorkspaceData {
  name: string;
  slug: string;
  description?: string;
}

/** What an update accepts; the server refuses any other field with 422. */
export interface UpdateWorkspaceData {
  name?: string;
  description?: string;
}

export const workspaceService = {
  list: () =>
    apiFetch<Workspace[]>('/api/v1/workspaces/'),

  create: (data: CreateWorkspaceData) =>
    apiFetch<Workspace>('/api/v1/workspaces/', { method: 'POST', json: data }),

  get: (id: string) =>
    apiFetch<Workspace>(`/api/v1/workspaces/${id}`),

  update: (id: string, data: UpdateWorkspaceData) =>
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
};
