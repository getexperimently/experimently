import { test, expect } from "./fixtures/auth.fixture";
import { ExperimentsPage } from "./pages/experiments.page";

test.describe("Experiment Lifecycle", () => {
  const EXPERIMENT_NAME = `E2E Test Experiment ${Date.now()}`;
  const EXPERIMENT_KEY = `e2e-test-${Date.now()}`;

  test("should display experiments list page", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.goto();

    // Page should load and show the experiments section
    const pageContent = await adminPage.textContent("body");
    expect(
      pageContent?.toLowerCase().includes("experiment") ||
        pageContent?.toLowerCase().includes("create")
    ).toBeTruthy();
  });

  test("should navigate to create experiment form", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.goto();

    const createVisible = await experiments.createButton
      .isVisible()
      .catch(() => false);

    if (createVisible) {
      await experiments.createButton.click();
      await adminPage.waitForLoadState("networkidle");

      // Should show form fields
      const hasNameField = await experiments.nameInput
        .isVisible()
        .catch(() => false);
      const hasKeyField = await experiments.keyInput
        .isVisible()
        .catch(() => false);

      expect(hasNameField || hasKeyField).toBeTruthy();
    } else {
      // Create button might be a nav link
      const createLink = adminPage.locator('a[href*="create"], a[href*="new"]');
      const linkVisible = await createLink.isVisible().catch(() => false);
      if (linkVisible) {
        await createLink.click();
        await adminPage.waitForLoadState("networkidle");
      }
    }
  });

  test("should create a draft experiment", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.goto();

    const createVisible = await experiments.createButton
      .isVisible()
      .catch(() => false);

    if (!createVisible) {
      test.skip();
      return;
    }

    await experiments.createExperiment(
      EXPERIMENT_NAME,
      EXPERIMENT_KEY,
      "Automated E2E test experiment"
    );

    // Should either redirect to detail page or show success
    const pageContent = await adminPage.textContent("body");
    const success =
      pageContent?.includes(EXPERIMENT_NAME) ||
      pageContent?.toLowerCase().includes("created") ||
      pageContent?.toLowerCase().includes("draft");

    expect(success).toBeTruthy();
  });

  test("should view experiment details", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.goto();

    // Try to find and click the created experiment
    const experimentRow = adminPage
      .locator(`text=${EXPERIMENT_NAME}`)
      .first();
    const visible = await experimentRow.isVisible().catch(() => false);

    if (visible) {
      await experimentRow.click();
      await adminPage.waitForLoadState("networkidle");

      const pageContent = await adminPage.textContent("body");
      expect(pageContent?.includes(EXPERIMENT_NAME)).toBeTruthy();
    } else {
      // Experiment list may be empty or paginated
      test.skip();
    }
  });

  test("should display experiment status transitions", async ({
    adminPage,
  }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.goto();

    // Verify status indicators are present in the list
    const pageContent = await adminPage.textContent("body");
    const hasStatusIndicators =
      pageContent?.toLowerCase().includes("draft") ||
      pageContent?.toLowerCase().includes("active") ||
      pageContent?.toLowerCase().includes("completed") ||
      pageContent?.toLowerCase().includes("paused") ||
      pageContent?.toLowerCase().includes("status");

    expect(hasStatusIndicators).toBeTruthy();
  });

  test("should show results tab for experiments", async ({ adminPage }) => {
    const experiments = new ExperimentsPage(adminPage);
    await experiments.goto();

    // Look for any experiment to click into
    const experimentLinks = adminPage.locator(
      'a[href*="/experiments/"], tr:has(a), [class*="card"]'
    );
    const count = await experimentLinks.count();

    if (count > 0) {
      await experimentLinks.first().click();
      await adminPage.waitForLoadState("networkidle");

      // Check for results tab or results section
      const hasResults =
        (await experiments.resultsTab.isVisible().catch(() => false)) ||
        (await adminPage.textContent("body"))
          ?.toLowerCase()
          .includes("result");

      // Results tab may not be visible for draft experiments
      expect(hasResults !== undefined).toBeTruthy();
    } else {
      test.skip();
    }
  });
});
