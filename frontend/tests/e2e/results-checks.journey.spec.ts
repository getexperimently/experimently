import { test, expect } from "./fixtures/auth.fixture";
import type { Page } from "@playwright/test";
import { API_URL, TOKEN_STORAGE_KEY } from "./env";

/**
 * Journey — the results page shows the API's sample-ratio check and Bayesian
 * analysis (#442).
 *
 * For every experiment the API lists, the page is compared with what
 * `GET /api/v1/results/{id}` returns for it, so each assertion is about a
 * value the server computed, not one the test typed:
 *
 *   - `srm` null: no notice and no "passed" line;
 *   - `srm.warning` false: the quiet line with the server's p-value;
 *   - `srm.warning` true: the notice, with the server's p-value;
 *   - `bayesian_results.is_enabled`: the panel, one row per variant, the
 *     decision's label;
 *   - otherwise, with the experiment's `bayesian_enabled` on: the muted line;
 *     with it off: nothing.
 *
 * `seed_demo_data.py` gives at least one fixed-allocation experiment with
 * assignments (`checkout_button_color`, 15,000 / 15,000), so the "passed" line
 * is exercised against real numbers; the journey fails if no experiment
 * reaches that branch.
 */

interface SrmBlock {
  p_value: number;
  warning: boolean;
}
interface BayesianBlock {
  is_enabled: boolean;
  decision?: string | null;
  variant_results?: unknown[];
}
interface ResultsBody {
  srm?: SrmBlock | null;
  bayesian_results?: BayesianBlock | null;
}
interface ExperimentRow {
  id: string;
  key: string | null;
  bayesian_enabled?: boolean;
}

/** The page's own formatting rule (SrmNotice.formatSrmP), written out. */
function expectedP(p: number): string {
  return p < 0.001 ? "p < 0.001" : `p = ${Number(p.toPrecision(2))}`;
}

const DECISION_LABELS: Record<string, string> = {
  CONTINUE: "Continue",
  STOP_WINNER: "Stop: a winner is clear",
  STOP_EQUIVALENT: "Stop: the variants are equivalent",
  STOP_FUTILE: "Stop: a meaningful difference is unlikely",
};

async function api<T>(page: Page, token: string, path: string): Promise<T> {
  const response = await page.request.get(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(response.status(), `GET ${path}`).toBe(200);
  return (await response.json()) as T;
}

test.describe("Journey: results checks", () => {
  test("every experiment's results page shows the API's sample-ratio check and Bayesian analysis", async ({
    adminPage,
  }) => {
    test.setTimeout(180_000);
    await adminPage.goto("/experiments");
    const token = await adminPage.evaluate((key) => window.localStorage.getItem(key), TOKEN_STORAGE_KEY);
    expect(token, "the admin session has a token").toBeTruthy();

    const list = await api<{ items: ExperimentRow[] }>(adminPage, token as string, "/api/v1/experiments/?limit=100");
    expect(list.items.length).toBeGreaterThan(0);

    const reached = { srmNull: 0, srmPassed: 0, srmWarning: 0, bayesian: 0 };
    const passedKeys: (string | null)[] = [];

    for (const experiment of list.items) {
      const body = await api<ResultsBody>(adminPage, token as string, `/api/v1/results/${experiment.id}`);

      await adminPage.goto(`/results/${experiment.id}`);
      await expect(adminPage.getByTestId("results-dashboard"), experiment.id).toBeVisible({ timeout: 20_000 });
      await expect(adminPage.getByTestId("error-state")).toHaveCount(0);

      const srm = body.srm ?? null;
      if (srm === null) {
        reached.srmNull += 1;
        await expect(adminPage.getByTestId("srm-notice")).toHaveCount(0);
        await expect(adminPage.getByTestId("srm-check-passed")).toHaveCount(0);
        await expect(adminPage.getByTestId("leading-srm-qualifier")).toHaveCount(0);
      } else if (!srm.warning) {
        reached.srmPassed += 1;
        passedKeys.push(experiment.key);
        await expect(adminPage.getByTestId("srm-notice")).toHaveCount(0);
        await expect(adminPage.getByTestId("srm-check-passed")).toContainText(`(${expectedP(srm.p_value)})`);
        await expect(adminPage.getByTestId("leading-srm-qualifier")).toHaveCount(0);
      } else {
        reached.srmWarning += 1;
        await expect(adminPage.getByTestId("srm-notice")).toBeVisible();
        await expect(adminPage.getByTestId("srm-notice").getByTestId("srm-p")).toHaveText(expectedP(srm.p_value));
        await expect(adminPage.getByTestId("srm-check-passed")).toHaveCount(0);
      }

      const bayesian = body.bayesian_results ?? null;
      if (bayesian?.is_enabled) {
        reached.bayesian += 1;
        const panel = adminPage.getByTestId("bayesian-panel");
        await expect(panel).toBeVisible();
        const rows = bayesian.variant_results ?? [];
        if (rows.length > 0) {
          await expect(panel.getByTestId("bayesian-row")).toHaveCount(rows.length);
        } else {
          await expect(panel.getByTestId("bayesian-no-data")).toBeVisible();
        }
        const label = bayesian.decision ? DECISION_LABELS[bayesian.decision] : "No decision";
        await expect(panel.getByTestId("bayesian-decision")).toHaveText(`Decision: ${label}`);
        await expect(adminPage.getByTestId("bayesian-unavailable")).toHaveCount(0);
      } else if (experiment.bayesian_enabled === true) {
        await expect(adminPage.getByTestId("bayesian-unavailable")).toBeVisible();
        await expect(adminPage.getByTestId("bayesian-panel")).toHaveCount(0);
      } else {
        await expect(adminPage.getByTestId("bayesian-panel")).toHaveCount(0);
        await expect(adminPage.getByTestId("bayesian-unavailable")).toHaveCount(0);
      }
    }

    // Not vacuous: the seed's balanced experiment reaches the "passed" branch.
    expect(reached.srmPassed, JSON.stringify(reached)).toBeGreaterThan(0);
    expect(passedKeys).toContain("checkout_button_color");
  });
});
