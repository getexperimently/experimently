import {
  ExperimentResultsResponse,
  DailyResultsResponse,
  SampleSizeResult,
} from '@/types/results';
import { SequentialTestingResponse } from '@/types/sequential';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export class ResultsService {
  static async getResults(
    experimentId: string,
    params?: { metric_id?: string; breakdown?: string }
  ): Promise<ExperimentResultsResponse> {
    const url = new URL(`${API_URL}/api/v1/results/${experimentId}`);
    if (params?.metric_id) {
      url.searchParams.set('metric_id', params.metric_id);
    }
    if (params?.breakdown) {
      url.searchParams.set('breakdown', params.breakdown);
    }
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`Failed to fetch results: ${response.statusText}`);
    }
    return response.json();
  }

  static async getDailyResults(
    experimentId: string,
    metricId?: string
  ): Promise<DailyResultsResponse> {
    const url = new URL(`${API_URL}/api/v1/results/${experimentId}/daily`);
    if (metricId) {
      url.searchParams.set('metric_id', metricId);
    }
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`Failed to fetch daily results: ${response.statusText}`);
    }
    return response.json();
  }

  static async getSampleSize(
    experimentId: string,
    params?: { mde?: number; power?: number }
  ): Promise<SampleSizeResult> {
    const url = new URL(`${API_URL}/api/v1/results/${experimentId}/sample-size`);
    if (params?.mde !== undefined) {
      url.searchParams.set('mde', String(params.mde));
    }
    if (params?.power !== undefined) {
      url.searchParams.set('power', String(params.power));
    }
    const response = await fetch(url.toString());
    if (!response.ok) {
      throw new Error(`Failed to fetch sample size: ${response.statusText}`);
    }
    return response.json();
  }

  static async getSequentialResults(
    experimentId: string
  ): Promise<SequentialTestingResponse> {
    const url = `${API_URL}/api/v1/results/${experimentId}/sequential`;
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Failed to fetch sequential results: ${response.statusText}`);
    }
    return response.json();
  }

  static async invalidateCache(
    experimentId: string
  ): Promise<{ status: string; experiment_id: string }> {
    const url = `${API_URL}/api/v1/results/${experimentId}/invalidate-cache`;
    const response = await fetch(url, { method: 'POST' });
    if (!response.ok) {
      throw new Error(`Failed to invalidate cache: ${response.statusText}`);
    }
    return response.json();
  }
}
