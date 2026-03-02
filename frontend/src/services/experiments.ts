import {
  Experiment,
  ExperimentListResponse,
  CreateExperimentRequest,
  ExperimentStatus,
} from '@/types/experiments';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

interface ListParams {
  status?: ExperimentStatus;
  page?: number;
  limit?: number;
}

export const ExperimentsService = {
  async list(params?: ListParams): Promise<ExperimentListResponse> {
    const url = new URL(`${API_URL}/api/v1/experiments`);
    if (params?.status) {
      url.searchParams.set('status', params.status);
    }
    if (params?.page !== undefined) {
      url.searchParams.set('page', String(params.page));
    }
    if (params?.limit !== undefined) {
      url.searchParams.set('limit', String(params.limit));
    }
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`Failed to fetch experiments: ${response.statusText}`);
    }
    return response.json();
  },

  async get(id: string): Promise<Experiment> {
    const response = await fetch(`${API_URL}/api/v1/experiments/${id}`);
    if (!response.ok) {
      throw new Error(`Failed to fetch experiment: ${response.statusText}`);
    }
    return response.json();
  },

  async create(data: CreateExperimentRequest): Promise<Experiment> {
    const response = await fetch(`${API_URL}/api/v1/experiments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      throw new Error(`Failed to create experiment: ${response.statusText}`);
    }
    return response.json();
  },

  async update(id: string, data: Partial<Experiment>): Promise<Experiment> {
    const response = await fetch(`${API_URL}/api/v1/experiments/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!response.ok) {
      throw new Error(`Failed to update experiment: ${response.statusText}`);
    }
    return response.json();
  },

  async delete(id: string): Promise<void> {
    const response = await fetch(`${API_URL}/api/v1/experiments/${id}`, {
      method: 'DELETE',
    });
    if (!response.ok) {
      throw new Error(`Failed to delete experiment: ${response.statusText}`);
    }
  },
};
