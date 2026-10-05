import { apiFetch } from '@/services/api';
import { BanditStatus } from '@/types/bandit';

/**
 * Read-only access to a bandit experiment's current weights. The dashboard
 * never calls the update or override routes.
 */
export const BanditService = {
  /** `GET /api/v1/bandit/{id}`: any signed-in role may read it. */
  async status(experimentId: string): Promise<BanditStatus> {
    return apiFetch<BanditStatus>(`/api/v1/bandit/${experimentId}`);
  },
};
