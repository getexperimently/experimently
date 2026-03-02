import { TargetingRules } from '@/types/targeting';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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
    const url = new URL(`${API_URL}/api/v1/feature-flags`);
    if (params?.status) url.searchParams.set('status', params.status);
    if (params?.page !== undefined) url.searchParams.set('page', String(params.page));
    if (params?.limit !== undefined) url.searchParams.set('limit', String(params.limit));
    const response = await fetch(url.toString());
    if (!response.ok) throw new Error(`Failed to fetch feature flags: ${response.statusText}`);
    return response.json();
  },

  async get(id: string): Promise<FeatureFlag> {
    const response = await fetch(`${API_URL}/api/v1/feature-flags/${id}`);
    if (!response.ok) throw new Error(`Failed to fetch feature flag: ${response.statusText}`);
    return response.json();
  },

  async create(data: CreateFeatureFlagRequest): Promise<FeatureFlag> {
    const response = await fetch(`${API_URL}/api/v1/feature-flags`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`Failed to create feature flag: ${response.statusText}`);
    return response.json();
  },

  async update(id: string, data: Partial<FeatureFlag>): Promise<FeatureFlag> {
    const response = await fetch(`${API_URL}/api/v1/feature-flags/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) throw new Error(`Failed to update feature flag: ${response.statusText}`);
    return response.json();
  },

  async delete(id: string): Promise<void> {
    const response = await fetch(`${API_URL}/api/v1/feature-flags/${id}`, {
      method: 'DELETE',
    });
    if (!response.ok) throw new Error(`Failed to delete feature flag: ${response.statusText}`);
  },
};
