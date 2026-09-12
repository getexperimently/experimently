import { TargetingRules } from '@/types/targeting';
import { apiFetch } from '@/services/api';

export type FeatureFlagStatus = 'active' | 'inactive' | 'archived';

export interface FeatureFlag {
  id: string;
  name: string;
  key: string;
  description?: string;
  status: FeatureFlagStatus;
  rollout_percentage: number;
  targeting_rules: TargetingRules | null;
  owner_id: string;
  created_at: string;
  updated_at: string;
}

export interface CreateFeatureFlagRequest {
  name: string;
  key?: string;
  description?: string;
  status?: FeatureFlagStatus;
  rollout_percentage?: number;
  targeting_rules?: TargetingRules | null;
}

export interface FeatureFlagListResponse {
  items: FeatureFlag[];
  total: number;
  page: number;
  limit: number;
}

export const FeatureFlagsService = {
  async list(params?: { status?: FeatureFlagStatus; page?: number; limit?: number }): Promise<FeatureFlagListResponse> {
    return apiFetch<FeatureFlagListResponse>('/api/v1/feature-flags', {
      query: { status: params?.status, page: params?.page, limit: params?.limit },
    });
  },

  async get(id: string): Promise<FeatureFlag> {
    return apiFetch<FeatureFlag>(`/api/v1/feature-flags/${id}`);
  },

  async create(data: CreateFeatureFlagRequest): Promise<FeatureFlag> {
    return apiFetch<FeatureFlag>('/api/v1/feature-flags', { method: 'POST', json: data });
  },

  async update(id: string, data: Partial<FeatureFlag>): Promise<FeatureFlag> {
    return apiFetch<FeatureFlag>(`/api/v1/feature-flags/${id}`, { method: 'PUT', json: data });
  },

  async delete(id: string): Promise<void> {
    await apiFetch<void>(`/api/v1/feature-flags/${id}`, { method: 'DELETE' });
  },
};
