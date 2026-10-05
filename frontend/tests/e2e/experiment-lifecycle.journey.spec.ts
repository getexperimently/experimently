import { test, expect } from "./fixtures/auth.fixture";
import { ESTIMATE_STEP_HEADING, ExperimentsPage } from "./pages/experiments.page";
import { TOKEN_STORAGE_KEY } from "./env";

/**
 * Journey 2 — experiment lifecycle.
 *
 * The core click-path an evaluator walks in their first ten minutes:
 * list → guided setup at `/experiments/new` → detail → start → pause → resume → complete →
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

  test("guided setup refuses an allocation that does not add up to 100%", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoGuided();

    await expect(experiments.guided).toBeVisible();
    await expect(experiments.stepHeading).toHaveText("What kind of experiment?");
    await experiments.nextStep("Name it and choose what to measure");
    // Ships with Control/Treatment at 50/50 and one conversion metric.
    await expect(experiments.metricNameInputs).toHaveCount(1);
    await experiments.nameInput.fill("Broken allocation");
    await experiments.nextStep("Set up the versions users will see");
    await expect(adminPage).toHaveURL(/\/experiments\/new\?step=variants$/);
    await expect(experiments.variantNameInputs).toHaveCount(2);

    await experiments.variantAllocationInputs.nth(1).fill("30");
    await experiments.nextButton.click();

    await expect(experiments.stepError).toContainText("add up to 100%");
    await expect(experiments.stepHeading).toHaveText("Set up the versions users will see");
    await expect(adminPage).toHaveURL(/\/experiments\/new\?step=variants$/);

    // Back never checks anything, and the answers survive the round trip.
    await experiments.backButton.click();
    await expect(experiments.nameInput).toHaveValue("Broken allocation");
    // The view changes before the URL does; wait for the history entry.
    await expect(adminPage).toHaveURL(/\/experiments\/new\?step=details$/);
    // Back is a step in the browser's history too: the browser's own Back
    // returns to Variants, answers intact.
    await adminPage.goBack();
    await expect(experiments.stepHeading).toHaveText("Set up the versions users will see");
    await expect(adminPage).toHaveURL(/\/experiments\/new\?step=variants$/);
    await expect(experiments.variantAllocationInputs.nth(1)).toHaveValue("30");

    // Leaving with answers in the tab asks first (the browser's own prompt).
    let prompt = "";
    adminPage.once("dialog", async (dialog) => {
      prompt = dialog.type();
      await dialog.accept();
    });
    await adminPage.close({ runBeforeUnload: true });
    await expect.poll(() => prompt).toBe("beforeunload");
  });

  test("Enter never creates anything from the Estimate step or Review", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    let posts = 0;
    adminPage.on("request", (request) => {
      const { pathname } = new URL(request.url());
      if (request.method() === "POST" && /\/api\/v1\/experiments\/?$/.test(pathname)) posts += 1;
    });
    await experiments.gotoGuided();
    await experiments.nextStep("Name it and choose what to measure");
    await experiments.nameInput.fill(`Enter probe ${STAMP}`);
    // Enter in a text field on the first three steps is Next.
    await experiments.nameInput.press("Enter");
    await expect(experiments.stepHeading).toHaveText("Set up the versions users will see");
    await experiments.nextStep(ESTIMATE_STEP_HEADING);

    await experiments.estimateBaseline.fill("12");
    await experiments.estimateBaseline.press("Enter");
    await experiments.estimateMde.fill("5");
    await experiments.estimateMde.press("Enter");
    await expect(experiments.stepHeading).toHaveText(ESTIMATE_STEP_HEADING);
    // The saved settings on the same step start at their defaults (#580).
    await expect(adminPage.getByTestId("analysis-confidence")).toHaveValue("0.95");
    await expect(adminPage.getByTestId("analysis-correction")).toHaveValue("benjamini_hochberg");

    await experiments.nextStep("Check and create");
    await experiments.stepHeading.press("Enter");
    await expect(experiments.stepHeading).toHaveText("Check and create");
    await expect(adminPage).toHaveURL(/\/experiments\/new\?step=review$/);

    // A fresh load at a later step starts over, with the notice. The reload
    // leaves a tab with answers in it, so the browser asks first.
    adminPage.on("dialog", (dialog) => dialog.accept());
    await adminPage.reload();
    await expect(experiments.stepHeading).toHaveText("What kind of experiment?");
    await expect(adminPage.getByTestId("wizard-fresh-notice")).toContainText("Start from the first step.");
    await expect(adminPage).toHaveURL(/\/experiments\/new\?step=type$/);
    expect(posts).toBe(0);
  });

  test("the single-page form at ?advanced still creates an experiment", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    // A nested, non-ASCII configuration on the treatment, and Bayesian analysis on (#442).
    const configuration = { headline: "Été ✓", layout: { columns: 2 }, express: true };
    const id = await experiments.createExperimentAdvanced(
      `E2E Advanced ${STAMP}`,
      `e2e_advanced_${STAMP}`,
      {
        metricEventName: "purchase",
        configurations: { 1: JSON.stringify(configuration) },
        bayesian: true,
      },
    );
    expect(id).toMatch(/^[0-9a-f-]{36}$/);
    await expect(experiments.detailName).toHaveText(`E2E Advanced ${STAMP}`);
    await experiments.expectStatus("draft");

    // The page shows what the API stored, read back from GET /experiments/{id}.
    await expect(adminPage.getByTestId("variant-configuration-none-0")).toBeVisible();
    const shown = await adminPage.getByTestId("variant-configuration-view-1").textContent();
    expect(JSON.parse(shown ?? "")).toEqual(configuration);
    await expect(adminPage.getByTestId("experiment-bayesian")).toHaveText("On");
    await expect(adminPage.getByTestId("experiment-algorithm")).toHaveCount(0);
  });

  test("creates a draft experiment and lands on its detail page", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    experimentId = await experiments.createExperiment(EXPERIMENT_NAME, EXPERIMENT_KEY, {
      description: "Automated E2E lifecycle experiment",
      metricEventName: "purchase",
      // The pinned answer (backend test_sample_size_pinned_answer.py), end to end.
      estimate: { baselinePct: "12", mdePct: "5", perVariant: "47,036 users per variant" },
    });
    expect(experimentId).toMatch(/^[0-9a-f-]{36}$/);

    await expect(experiments.detailName).toHaveText(EXPERIMENT_NAME);
    await expect(experiments.detailKey).toHaveText(EXPERIMENT_KEY);
    await experiments.expectStatus("draft");
    await expect(experiments.variantsTable.getByTestId("variant-row")).toHaveCount(2);
    // Guided setup with no configuration typed and Bayesian analysis left off.
    await expect(adminPage.getByTestId("variant-configuration-none-1")).toBeVisible();
    await expect(adminPage.getByTestId("experiment-bayesian")).toHaveText("Off");
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

  test("a taken key or an expired session at Create keeps every answer", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    const creates: number[] = [];
    adminPage.on("response", (response) => {
      const request = response.request();
      const { pathname } = new URL(request.url());
      // The API redirects /experiments to /experiments/ (307); count answers only.
      const status = response.status();
      const redirect = status >= 300 && status < 400;
      if (request.method() === "POST" && /\/api\/v1\/experiments\/?$/.test(pathname) && !redirect) {
        creates.push(status);
      }
    });
    const name = `E2E Keeps answers ${STAMP}`;

    await experiments.gotoGuided();
    await experiments.nextStep("Name it and choose what to measure");
    await experiments.nameInput.fill(name);
    // The key the previous test created.
    await experiments.keyInput.fill(EXPERIMENT_KEY);
    await experiments.nextStep("Set up the versions users will see");
    await experiments.nextStep(ESTIMATE_STEP_HEADING);
    await experiments.nextStep("Check and create");

    // Taken key: the API answers 409; the page says so in its own words.
    await experiments.createStepButton.click();
    // Exactly the page's sentence and its button: nothing of the API's body.
    await expect(experiments.formError).toHaveText(
      `An experiment with the key “${EXPERIMENT_KEY}” already exists. ` +
        "Choose a different key on the Details step. Edit details",
    );
    await expect(adminPage).toHaveURL(/\/experiments\/new\?step=review$/);
    await expect(adminPage.getByTestId("review-name")).toContainText(name);

    // "Edit details" goes to the key field, ready to change.
    await adminPage.getByTestId("form-error-edit-details").click();
    await expect(experiments.stepHeading).toHaveText("Name it and choose what to measure");
    await expect(experiments.keyInput).toBeFocused();
    await experiments.keyInput.fill(`e2e_keeps_answers_${STAMP}`);
    await experiments.nextStep("Set up the versions users will see");
    await experiments.nextStep(ESTIMATE_STEP_HEADING);
    await experiments.nextStep("Check and create");
    await expect(experiments.formError).toHaveCount(0);

    // The session ends while the tab is open: the API answers 401, and the
    // page stays where it is with the answers, instead of going to /login.
    // The session is shared by every admin test in this worker, so put the
    // token back afterwards.
    const token = await adminPage.evaluate((key) => window.localStorage.getItem(key), TOKEN_STORAGE_KEY);
    expect(token).toBeTruthy();
    await adminPage.evaluate((key) => window.localStorage.removeItem(key), TOKEN_STORAGE_KEY);
    await experiments.createStepButton.click();
    await expect(experiments.formError).toContainText("Your session has expired.");
    await expect(experiments.formError).toContainText("Your answers are still here.");
    await expect(adminPage).toHaveURL(/\/experiments\/new\?step=review$/);
    await expect(adminPage.getByTestId("review-name")).toContainText(name);
    await expect(adminPage.getByTestId("review-key")).toContainText(`e2e_keeps_answers_${STAMP}`);
    expect(creates).toEqual([409, 401]);

    await adminPage.evaluate(([key, value]) => window.localStorage.setItem(key, value), [
      TOKEN_STORAGE_KEY,
      token as string,
    ]);
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
    // Clone is still offered, outside experiment-actions (#442).
    await expect(adminPage.getByTestId("experiment-manage").getByTestId("experiment-clone")).toBeVisible();
    await expect(adminPage.getByTestId("experiment-edit-details")).toHaveCount(0);
    await expect(adminPage.getByTestId("experiment-delete")).toHaveCount(0);
  });

  // #442: a draft's name, description and hypothesis are edited in place, an
  // experiment is cloned, and a draft is deleted after a confirmation in the
  // page. The draft is this test's own, so the shared one above is untouched.
  test("edit a draft's name, clone it, then delete the clone", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    const name = `E2E Manage ${STAMP}`;
    const id = await experiments.createExperimentAdvanced(name, `e2e_manage_${STAMP}`, {
      metricEventName: "purchase",
    });
    expect(id).toMatch(/^[0-9a-f-]{36}$/);

    // The controls sit outside experiment-actions, whose draft buttons are
    // unchanged: Start only.
    const manage = adminPage.getByTestId("experiment-manage");
    await expect(manage).toBeVisible();
    await expect(experiments.actions.locator("button")).toHaveCount(1);
    await expect(experiments.startButton).toBeVisible();
    await expect(experiments.actions.getByTestId("experiment-clone")).toHaveCount(0);

    // Edit the name: the PUT carries the name and nothing else.
    const renamed = `${name} renamed`;
    await manage.getByTestId("experiment-edit-details").click();
    await adminPage.getByTestId("manage-edit-name").fill(renamed);
    const put = adminPage.waitForRequest(
      (request) =>
        request.method() === "PUT" && new URL(request.url()).pathname === `/api/v1/experiments/${id}`,
    );
    await adminPage.getByTestId("manage-edit-save").click();
    expect((await put).postDataJSON()).toEqual({ name: renamed });
    await expect(adminPage.getByTestId("manage-saved")).toBeVisible();
    await expect(experiments.detailName).toHaveText(renamed);

    // Stored, and the variants and metric are still there after a reload.
    await adminPage.reload();
    await expect(experiments.detailName).toHaveText(renamed);
    await expect(experiments.variantsTable.getByTestId("variant-row")).toHaveCount(2);
    await expect(experiments.metricsList.getByTestId("metric-row")).toHaveCount(1);

    // Clone: the page moves to the new experiment, whose name the server chose.
    await manage.getByTestId("experiment-clone").click();
    await adminPage.waitForURL(
      (url) => /\/experiments\/[0-9a-f-]{36}$/.test(url.pathname) && !url.pathname.endsWith(id),
      { timeout: 15_000 },
    );
    const cloneId = new URL(adminPage.url()).pathname.split("/").pop() ?? "";
    expect(cloneId).not.toBe(id);
    await expect(experiments.detailName).toHaveText(`Copy of ${renamed}`, { timeout: 15_000 });
    await experiments.expectStatus("draft");

    // Delete the clone: asked in the page, never through a browser dialog.
    let dialogs = 0;
    adminPage.on("dialog", (dialog) => {
      dialogs += 1;
      void dialog.dismiss();
    });
    await adminPage.getByTestId("experiment-delete").click();
    await expect(adminPage.getByTestId("manage-delete-confirm")).toBeVisible();
    await adminPage.getByTestId("manage-delete-yes").click();
    await adminPage.waitForURL(/\/experiments$/, { timeout: 15_000 });
    expect(dialogs).toBe(0);

    await experiments.gotoExperiment(cloneId);
    await expect(experiments.notFound).toBeVisible({ timeout: 15_000 });
    // The source draft is untouched.
    await experiments.gotoExperiment(id);
    await expect(experiments.detailName).toHaveText(renamed, { timeout: 15_000 });
  });

  test("an unknown experiment id shows the 404 view", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.gotoExperiment("00000000-0000-0000-0000-000000000000");
    await expect(experiments.notFound).toBeVisible({ timeout: 15_000 });
  });
});
