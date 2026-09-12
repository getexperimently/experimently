import {
  Experiment,
  ExperimentListResponse,
  CreateExperimentRequest,
  ExperimentStatus,
} from '@/types/experiments';
import { apiFetch } from '@/services/api';

/**
 * Query parameters accepted by `GET /api/v1/experiments/`
 * (`status_filter`, `skip`, `limit`, `search`, `sort_by`, `sort_order`).
 */
export interface ExperimentListParams {
  status?: ExperimentStatus;
  skip?: number;
  limit?: number;
  search?: string;
  sort_by?: 'created_at' | 'updated_at' | 'name' | 'status';
  sort_order?: 'asc' | 'desc';
}

const BASE = '/api/v1/experiments';

export const ExperimentsService = {
  async list(params?: ExperimentListParams): Promise<ExperimentListResponse> {
    return apiFetch<ExperimentListResponse>(BASE, {
      query: {
        status_filter: params?.status,
        skip: params?.skip,
        limit: params?.limit,
        search: params?.search,
        sort_by: params?.sort_by,
        sort_order: params?.sort_order,
      },
    });
  },

  async get(id: string): Promise<Experiment> {
    return apiFetch<Experiment>(`${BASE}/${id}`);
  },

  async create(data: CreateExperimentRequest): Promise<Experiment> {
    return apiFetch<Experiment>(BASE, { method: 'POST', json: data });
  },

  async update(id: string, data: Partial<Experiment>): Promise<Experiment> {
    return apiFetch<Experiment>(`${BASE}/${id}`, { method: 'PUT', json: data });
  },

  async delete(id: string): Promise<void> {
    await apiFetch<void>(`${BASE}/${id}`, { method: 'DELETE' });
  },

  // Lifecycle transitions — each returns the updated experiment.
  // start: draft|paused → active; pause: active → paused;
  // complete: active|paused → completed; archive: any non-archived → archived.
  async start(id: string): Promise<Experiment> {
    return apiFetch<Experiment>(`${BASE}/${id}/start`, { method: 'POST' });
  },

  async pause(id: string): Promise<Experiment> {
    return apiFetch<Experiment>(`${BASE}/${id}/pause`, { method: 'POST' });
  },

  async complete(id: string): Promise<Experiment> {
    return apiFetch<Experiment>(`${BASE}/${id}/complete`, { method: 'POST' });
  },

  async archive(id: string): Promise<Experiment> {
    return apiFetch<Experiment>(`${BASE}/${id}/archive`, { method: 'POST' });
  },
};
