import {
  ExperimentResultsResponse,
  DailyResultsResponse,
  SampleSizeResult,
} from '@/types/results';
import { SequentialTestingResponse } from '@/types/sequential';
import { apiFetch } from '@/services/api';

export class ResultsService {
  static async getResults(
    experimentId: string,
    params?: { metric_id?: string; breakdown?: string }
  ): Promise<ExperimentResultsResponse> {
    return apiFetch<ExperimentResultsResponse>(`/api/v1/results/${experimentId}`, {
      query: {
        metric_id: params?.metric_id || undefined,
        breakdown: params?.breakdown || undefined,
      },
    });
  }

  static async getDailyResults(
    experimentId: string,
    metricId?: string
  ): Promise<DailyResultsResponse> {
    return apiFetch<DailyResultsResponse>(`/api/v1/results/${experimentId}/daily`, {
      query: { metric_id: metricId || undefined },
    });
  }

  static async getSampleSize(
    experimentId: string,
    params?: { mde?: number; power?: number }
  ): Promise<SampleSizeResult> {
    return apiFetch<SampleSizeResult>(`/api/v1/results/${experimentId}/sample-size`, {
      query: { mde: params?.mde, power: params?.power },
    });
  }

  static async getSequentialResults(
    experimentId: string
  ): Promise<SequentialTestingResponse> {
    return apiFetch<SequentialTestingResponse>(`/api/v1/results/${experimentId}/sequential`);
  }

  static async invalidateCache(
    experimentId: string
  ): Promise<{ status: string; experiment_id: string }> {
    return apiFetch<{ status: string; experiment_id: string }>(
      `/api/v1/results/${experimentId}/invalidate-cache`,
      { method: 'POST' }
    );
  }
}
