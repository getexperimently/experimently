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

/**
 * Query for `GET /api/v1/experiments/analysis/sample-size`. Rates are
 * fractions (0.12, not 12) and `minimum_detectable_effect` is RELATIVE: 0.05
 * compares 12% with 12.6%, not with 17%.
 */
export interface SampleSizeQuery {
  baseline_rate: number;
  minimum_detectable_effect: number;
  statistical_power: number;
  significance_level: number;
  variant_count: number;
  /** Users per day; the duration is estimated only when this and `traffic_allocation` are both sent. */
  daily_traffic?: number;
  /** Fraction (0, 1] of `daily_traffic` that enters the experiment. */
  traffic_allocation?: number;
}

export interface SampleSizeEstimate {
  baseline_rate: number;
  minimum_detectable_effect: number;
  statistical_power: number;
  significance_level: number;
  is_one_sided: boolean;
  samples_per_variant: number;
  total_samples: number;
  estimated_duration_days: { days: number; weeks: number; months: number } | null;
  notes: string | null;
}

/** Options for `ExperimentsService.create`. */
export interface CreateOptions {
  /** Default true: a 401 sends the browser to the login page. */
  redirectOn401?: boolean;
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

  /**
   * `POST /api/v1/experiments`. Pass `redirectOn401: false` to get the 401 as
   * an error instead of being sent to the login page; `/experiments/new` does,
   * so an expired session never costs the answers on screen.
   */
  async create(data: CreateExperimentRequest, options: CreateOptions = {}): Promise<Experiment> {
    return apiFetch<Experiment>(BASE, { method: 'POST', json: data, ...options });
  },

  /**
   * The users needed per variant, and the days that takes when daily traffic
   * is given. Advisory: nothing is stored. A 401 here does not send the user
   * to the login page, so an estimate never costs them the answers on screen.
   */
  async estimateSampleSize(query: SampleSizeQuery): Promise<SampleSizeEstimate> {
    return apiFetch<SampleSizeEstimate>(`${BASE}/analysis/sample-size`, {
      query: { ...query },
      redirectOn401: false,
    });
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
