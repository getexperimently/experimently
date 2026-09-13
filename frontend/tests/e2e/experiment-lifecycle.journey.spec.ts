import { test, expect } from "./fixtures/auth.fixture";
import { ExperimentsPage } from "./pages/experiments.page";

/**
 * Journey 2 — experiment lifecycle.
 *
 * The core click-path an evaluator walks in their first ten minutes:
 * list → `/experiments/new` → detail → start → pause → resume → complete →
 * results → archive. It runs against a real backend with the demo admin, and
 * every step asserts on `data-testid`s rendered by `src/pages/experiments/`
 * and `src/pages/results/`.
 *
 * Serial: the tests share one experiment, created by the third test. A failure
 * stops the chain rather than letting later steps pass vacuously.
 */
test.describe("Journey: experiment lifecycle", () => {
  test.describe.configure({ mode: "serial" });

  const STAMP = Date.now();
  const EXPERIMENT_NAME = `E2E Lifecycle ${STAMP}`;
  const EXPERIMENT_KEY = `e2e_lifecycle_${STAMP}`;
  let experimentId = "";

  test("the list renders the seeded experiments", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.goto();

    await expect(experiments.createButton).toBeVisible();
    await expect(experiments.createButton).toHaveAttribute("href", "/experiments/new");
    await expect(experiments.listError).toHaveCount(0);

    // `seed_demo_data.py` creates three experiments; the table must render.
    await expect(experiments.experimentList).toBeVisible({ timeout: 15_000 });
    expect(await experiments.experimentRows.count()).toBeGreaterThan(0);

    const firstRow = experiments.experimentRows.first();
    await expect(firstRow.getByTestId("experiment-link")).toBeVisible();
    await expect(firstRow.getByTestId("experiment-status-pill")).not.toBeEmpty();
    // The Type column renders a label, not the raw enum or an owner UUID.
    await expect(firstRow.getByTestId("experiment-type-cell")).not.toBeEmpty();
    await expect(experiments.experimentList).not.toContainText(
      /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/,
    );

    // The status filters narrow the list without erroring.
    await experiments.filterByStatus("active");
    await expect(experiments.listError).toHaveCount(0);
    await experiments.filterByStatus("all");
  });

  test("the create form refuses an allocation that does not add up to 100%", async ({
    adminPage,
  }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoNew();

    await expect(experiments.form).toBeVisible();
    // Ships with Control/Treatment at 50/50 and one conversion metric.
    await expect(experiments.variantNameInputs).toHaveCount(2);
    await expect(experiments.metricNameInputs).toHaveCount(1);

    await experiments.nameInput.fill("Broken allocation");
    await experiments.variantAllocationInputs.nth(1).fill("30");
    await experiments.submitButton.click();

    await expect(experiments.formError).toBeVisible();
    await expect(experiments.formError).toContainText("add up to 100%");
    await expect(adminPage).toHaveURL(/\/experiments\/new$/);
  });

  test("creates a draft experiment and lands on its detail page", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    experimentId = await experiments.createExperiment(EXPERIMENT_NAME, EXPERIMENT_KEY, {
      description: "Automated E2E lifecycle experiment",
      metricEventName: "purchase",
    });
    expect(experimentId).toMatch(/^[0-9a-f-]{36}$/);

    await expect(experiments.detailName).toHaveText(EXPERIMENT_NAME);
    await expect(experiments.detailKey).toHaveText(EXPERIMENT_KEY);
    await experiments.expectStatus("draft");
    await expect(experiments.variantsTable.getByTestId("variant-row")).toHaveCount(2);
    await expect(experiments.metricsList.getByTestId("metric-row")).toHaveCount(1);
    await expect(experiments.detail.getByTestId("experiment-description")).toContainText(
      "Automated E2E lifecycle experiment",
    );

    // Draft: only Start is offered and results are not reachable yet.
    await expect(experiments.startButton).toBeVisible();
    await expect(experiments.pauseButton).toHaveCount(0);
    await expect(experiments.completeButton).toHaveCount(0);
    await expect(experiments.resultsLink).toHaveCount(0);
    await expect(adminPage.getByTestId("view-results-disabled")).toBeVisible();

    // The SDK snippet carries the key the tracking API expects.
    await expect(adminPage.getByTestId("sdk-hint")).toContainText(EXPERIMENT_KEY);
  });

  test("the new experiment appears in the list and opens from it", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.goto();
    await experiments.filterByStatus("draft");

    const row = experiments.getExperimentRow(EXPERIMENT_NAME);
    await expect(row).toBeVisible({ timeout: 15_000 });
    await expect(row.getByTestId("experiment-status-pill")).toHaveText("Draft");

    await experiments.clickExperiment(EXPERIMENT_NAME);
    await expect(adminPage).toHaveURL(new RegExp(`/experiments/${experimentId}$`));
  });

  test("draft → active → paused → active → completed through the action buttons", async ({
    adminPage,
  }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment(experimentId);
    await experiments.expectStatus("draft");

    // start
    await experiments.startExperiment();
    await expect(experiments.pauseButton).toBeVisible();
    await expect(experiments.completeButton).toBeVisible();
    await expect(experiments.startButton).toHaveCount(0);
    await expect(experiments.resultsLink).toHaveAttribute("href", `/results/${experimentId}`);

    // pause
    await experiments.pauseExperiment();
    await expect(experiments.startButton).toBeVisible();
    await expect(experiments.completeButton).toBeVisible();

    // resume
    await experiments.startExperiment();

    // Cancelling the confirmation must leave the experiment running.
    await experiments.completeButton.click();
    await expect(experiments.confirmDialog).toBeVisible();
    await experiments.confirmCancelButton.click();
    await expect(experiments.confirmDialog).toHaveCount(0);
    await experiments.expectStatus("active");

    // complete
    await experiments.completeExperiment();
    await expect(experiments.archiveButton).toBeVisible();
    await expect(experiments.actionError).toHaveCount(0);
  });

  test("the persisted status survives a reload", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment(experimentId);
    await experiments.expectStatus("completed");
    await adminPage.reload();
    await experiments.expectStatus("completed");
  });

  test("View results opens the results dashboard", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment(experimentId);
    await experiments.viewResults();

    await expect(adminPage).toHaveURL(new RegExp(`/results/${experimentId}$`));
    await expect(adminPage.getByTestId("results-dashboard")).toBeVisible({ timeout: 20_000 });
    await expect(adminPage.getByTestId("error-state")).toHaveCount(0);
    await expect(adminPage.getByTestId("experiment-summary")).toContainText(EXPERIMENT_NAME);

    // Sample-size tab renders the power meter for an experiment with no traffic.
    await adminPage.getByRole("tab", { name: "Sample Size" }).click();
    await expect(adminPage.getByTestId("sample-size-meter")).toBeVisible();
  });

  test("/results without an id sends you back to the experiments list", async ({ adminPage }) => {
    // The page redirects from a useEffect, so its interstitial
    // (`results-redirect`) can be gone before an assertion sees it — assert the
    // destination, which is what the user actually gets.
    await adminPage.goto("/results");
    await adminPage.waitForURL(/\/experiments$/, { timeout: 15_000 });
    await expect(adminPage.getByTestId("experiments-table")).toBeVisible({ timeout: 15_000 });
  });

  test("completed → archived, after which no lifecycle action remains", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment(experimentId);
    await experiments.archiveExperiment();
    await expect(experiments.actionError).toHaveCount(0);
    await expect(experiments.actions.locator("button")).toHaveCount(0);
    // Results stay reachable for an archived experiment.
    await expect(experiments.resultsLink).toBeVisible();
  });

  test("an unknown experiment id shows the 404 view", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment("00000000-0000-0000-0000-000000000000");
    await expect(experiments.notFound).toBeVisible({ timeout: 15_000 });
  });
});
