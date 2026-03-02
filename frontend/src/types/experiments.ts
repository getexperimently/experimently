import { TargetingRules } from './targeting';

export type ExperimentStatus = 'draft' | 'active' | 'paused' | 'completed' | 'archived';
export type ExperimentType = 'a_b' | 'mv' | 'split_url' | 'bandit';

export interface ExperimentVariant {
  id: string;
  name: string;
  description?: string;
  allocation: number;
  is_control: boolean;
  configuration?: Record<string, unknown>;
}

export interface ExperimentMetric {
  metric_id: string;
  metric_name: string;
  is_primary: boolean;
}

export interface Experiment {
  id: string;
  name: string;
  key: string;
  description?: string;
  hypothesis?: string;
  status: ExperimentStatus;
  type: ExperimentType;
  owner_id: string;
  owner_name?: string;
  traffic_allocation: number;
  targeting_rules: TargetingRules | null;
  variants: ExperimentVariant[];
  metrics: ExperimentMetric[];
  start_date: string | null;
  end_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateExperimentRequest {
  name: string;
  key?: string;
  description?: string;
  hypothesis?: string;
  type: ExperimentType;
  traffic_allocation: number;
  targeting_rules?: TargetingRules | null;
  variants: Omit<ExperimentVariant, 'id'>[];
  metrics?: ExperimentMetric[];
  start_date?: string | null;
  end_date?: string | null;
}

export interface ExperimentListResponse {
  items: Experiment[];
  total: number;
  page: number;
  limit: number;
}

export const EXPERIMENT_STATUS_LABELS: Record<ExperimentStatus, string> = {
  draft: 'Draft',
  active: 'Active',
  paused: 'Paused',
  completed: 'Completed',
  archived: 'Archived',
};

export const EXPERIMENT_TYPE_LABELS: Record<ExperimentType, string> = {
  a_b: 'A/B Test',
  mv: 'Multivariate',
  split_url: 'Split URL',
  bandit: 'Bandit',
};

export const EXPERIMENT_STATUS_COLORS: Record<ExperimentStatus, string> = {
  draft: 'bg-slate-100 text-slate-700',
  active: 'bg-green-100 text-green-800',
  paused: 'bg-yellow-100 text-yellow-800',
  completed: 'bg-blue-100 text-blue-800',
  archived: 'bg-gray-100 text-gray-600',
};
