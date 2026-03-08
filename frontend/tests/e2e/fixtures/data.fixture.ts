import { test as base, type APIRequestContext } from "@playwright/test";

const API_URL = process.env.PLAYWRIGHT_API_URL ?? "http://localhost:8000";

/**
 * Helpers to seed and clean up test data via the backend API.
 * Uses Playwright's built-in APIRequestContext for HTTP calls.
 */
export interface TestDataApi {
  /** Create an experiment via API and return its ID. */
  createExperiment(data: {
    name: string;
    key: string;
    description?: string;
  }): Promise<string>;

  /** Create a feature flag via API and return its ID. */
  createFeatureFlag(data: {
    name: string;
    key: string;
    description?: string;
  }): Promise<string>;

  /** Delete an experiment by ID. */
  deleteExperiment(id: string): Promise<void>;

  /** Delete a feature flag by ID. */
  deleteFeatureFlag(id: string): Promise<void>;

  /** Check backend health. */
  healthCheck(): Promise<boolean>;
}

function createTestDataApi(request: APIRequestContext): TestDataApi {
  return {
    async createExperiment(data) {
      const res = await request.post(`${API_URL}/api/v1/experiments`, {
        data: {
          name: data.name,
          key: data.key,
          description: data.description ?? `E2E test: ${data.name}`,
          status: "DRAFT",
        },
      });
      const body = await res.json();
      return body.id;
    },

    async createFeatureFlag(data) {
      const res = await request.post(`${API_URL}/api/v1/feature-flags`, {
        data: {
          name: data.name,
          key: data.key,
          description: data.description ?? `E2E test: ${data.name}`,
          is_enabled: false,
          rollout_percentage: 0,
        },
      });
      const body = await res.json();
      return body.id;
    },

    async deleteExperiment(id) {
      await request.delete(
        `${API_URL}/api/v1/experiments/${id}?experiment_key=e2e-cleanup`
      );
    },

    async deleteFeatureFlag(id) {
      await request.delete(`${API_URL}/api/v1/feature-flags/${id}`);
    },

    async healthCheck() {
      try {
        const res = await request.get(`${API_URL}/health`);
        return res.ok();
      } catch {
        return false;
      }
    },
  };
}

/**
 * Extended test fixture that provides a `testData` API for seeding/cleanup.
 */
export const test = base.extend<{ testData: TestDataApi }>({
  testData: async ({ request }, use) => {
    const api = createTestDataApi(request);
    await use(api);
  },
});

export { expect } from "@playwright/test";
export { API_URL };
