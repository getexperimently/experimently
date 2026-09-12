import {
  Experiment,
  ExperimentListResponse,
  CreateExperimentRequest,
  ExperimentStatus,
} from '@/types/experiments';
import { apiFetch } from '@/services/api';

interface ListParams {
  status?: ExperimentStatus;
  page?: number;
  limit?: number;
}

export const ExperimentsService = {
  async list(params?: ListParams): Promise<ExperimentListResponse> {
    return apiFetch<ExperimentListResponse>('/api/v1/experiments', {
      query: {
        status: params?.status,
        page: params?.page,
        limit: params?.limit,
      },
    });
  },

  async get(id: string): Promise<Experiment> {
    return apiFetch<Experiment>(`/api/v1/experiments/${id}`);
  },

  async create(data: CreateExperimentRequest): Promise<Experiment> {
    return apiFetch<Experiment>('/api/v1/experiments', { method: 'POST', json: data });
  },

  async update(id: string, data: Partial<Experiment>): Promise<Experiment> {
    return apiFetch<Experiment>(`/api/v1/experiments/${id}`, { method: 'PUT', json: data });
  },

  async delete(id: string): Promise<void> {
    await apiFetch<void>(`/api/v1/experiments/${id}`, { method: 'DELETE' });
  },
};
