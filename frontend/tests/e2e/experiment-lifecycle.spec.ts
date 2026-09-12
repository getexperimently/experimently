import { test, expect } from "./fixtures/auth.fixture";
import { ExperimentsPage } from "./pages/experiments.page";

/**
 * CE click-path: list → create → detail → start → pause → start → complete →
 * results → archive. Runs against a real backend (`AUTH_PROVIDER=local`) with
 * the demo admin; every step asserts on `data-testid`s from
 * `src/pages/experiments/`.
 */
test.describe("Experiment Lifecycle", () => {
  test.describe.configure({ mode: "serial" });

  const STAMP = Date.now();
  const EXPERIMENT_NAME = `E2E Lifecycle ${STAMP}`;
  const EXPERIMENT_KEY = `e2e-lifecycle-${STAMP}`;
  let experimentId = "";

  test("list page renders a table or the first-run checklist", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.goto();

    await expect(experiments.createButton).toBeVisible();
    await expect(experiments.listError).toHaveCount(0);

    const hasRows = (await experiments.experimentList.count()) > 0;
    if (hasRows) {
      await expect(experiments.experimentRows.first()).toBeVisible();
      // Type column is filled from `experiment_type` and no owner UUID is shown.
      const firstType = experiments.experimentRows.first().getByTestId("experiment-type-cell");
      await expect(firstType).not.toHaveText("");
      await expect(experiments.experimentList).not.toContainText(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}/);
    } else {
      await expect(experiments.firstRunChecklist).toBeVisible();
      await expect(experiments.firstRunChecklist.getByTestId("checklist-curl")).toContainText(
        "/api/v1/tracking/assign",
      );
      await expect(experiments.firstRunChecklist.getByTestId("checklist-api-keys")).toHaveAttribute(
        "href",
        "/admin/api-keys",
      );
    }
  });

  test("create form has variants and metrics and rejects a bad allocation", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoNew();

    await expect(experiments.form).toBeVisible();
    await expect(experiments.variantNameInputs).toHaveCount(2);
    await expect(experiments.metricNameInputs).toHaveCount(1);

    await experiments.nameInput.fill("Broken allocation");
    await experiments.variantAllocationInputs.nth(1).fill("30");
    await experiments.submitButton.click();
    await expect(experiments.formError).toContainText("100%");
    await expect(adminPage).toHaveURL(/\/experiments\/new$/);
  });

  test("creates a draft experiment and lands on its detail page", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    experimentId = await experiments.createExperiment(EXPERIMENT_NAME, EXPERIMENT_KEY, {
      description: "Automated E2E lifecycle experiment",
      metricEventName: "purchase",
    });
    expect(experimentId).not.toBe("");

    await expect(experiments.detailName).toHaveText(EXPERIMENT_NAME);
    await expect(experiments.detailKey).toHaveText(EXPERIMENT_KEY);
    await experiments.expectStatus("draft");
    await expect(experiments.variantsTable.getByTestId("variant-row")).toHaveCount(2);
    await expect(experiments.metricsList.getByTestId("metric-row")).toHaveCount(1);
    await expect(experiments.startButton).toBeVisible();
    await expect(experiments.pauseButton).toHaveCount(0);
    await expect(experiments.resultsLink).toHaveCount(0);
  });

  test("the new experiment appears in the list and opens from it", async ({ adminPage }) => {
    test.skip(!experimentId, "experiment was not created");
    const experiments = new ExperimentsPage(adminPage);
    await experiments.goto();
    await experiments.filterByStatus("draft");
    await expect(experiments.getExperimentRow(EXPERIMENT_NAME)).toBeVisible();
    await experiments.clickExperiment(EXPERIMENT_NAME);
    await expect(adminPage).toHaveURL(new RegExp(`/experiments/${experimentId}$`));
  });

  test("draft → active → paused → active → completed via the action buttons", async ({ adminPage }) => {
    test.skip(!experimentId, "experiment was not created");
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment(experimentId);

    await experiments.startExperiment();
    await expect(experiments.pauseButton).toBeVisible();
    await expect(experiments.completeButton).toBeVisible();
    await expect(experiments.startButton).toHaveCount(0);
    await expect(experiments.resultsLink).toHaveAttribute("href", `/results/${experimentId}`);

    await experiments.pauseExperiment();
    await expect(experiments.startButton).toBeVisible();
    await expect(experiments.completeButton).toBeVisible();

    await experiments.startExperiment();

    // Cancelling the confirmation keeps the experiment active.
    await experiments.completeButton.click();
    await experiments.confirmCancelButton.click();
    await experiments.expectStatus("active");

    await experiments.completeExperiment();
    await expect(experiments.archiveButton).toBeVisible();
    await expect(experiments.actionError).toHaveCount(0);
  });

  test("the detail page survives a reload with the persisted status", async ({ adminPage }) => {
    test.skip(!experimentId, "experiment was not created");
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment(experimentId);
    await experiments.expectStatus("completed");
  });

  test("View results opens the results dashboard", async ({ adminPage }) => {
    test.skip(!experimentId, "experiment was not created");
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment(experimentId);
    await experiments.viewResults();
    await expect(adminPage).toHaveURL(new RegExp(`/results/${experimentId}$`));
    await expect(adminPage.locator("body")).toContainText(/result/i);
  });

  test("/results redirects to the experiments list", async ({ adminPage }) => {
    await adminPage.goto("/results");
    await adminPage.waitForURL(/\/experiments$/, { timeout: 15_000 });
  });

  test("completed → archived", async ({ adminPage }) => {
    test.skip(!experimentId, "experiment was not created");
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment(experimentId);
    await experiments.archiveExperiment();
    await expect(experiments.page.getByTestId("experiment-actions").locator("button")).toHaveCount(0);
  });

  test("an unknown experiment id shows the 404 view", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment("00000000-0000-0000-0000-000000000000");
    await expect(experiments.notFound).toBeVisible({ timeout: 15_000 });
  });
});
