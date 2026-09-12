import { type Page, type Locator, expect } from "@playwright/test";
import { CommonPage } from "./common.page";

/**
 * Page object for the experiments list (`/experiments`), the create form
 * (`/experiments/new`) and the detail page (`/experiments/[id]`).
 *
 * Every selector is a `data-testid` rendered by the corresponding page in
 * `src/pages/experiments/`; keep the two in sync.
 */
export class ExperimentsPage {
  readonly page: Page;
  readonly common: CommonPage;

  // List page
  readonly createButton: Locator;
  readonly experimentList: Locator;
  readonly experimentRows: Locator;
  readonly statusFilter: Locator;
  readonly firstRunChecklist: Locator;
  readonly emptyState: Locator;
  readonly listError: Locator;

  // Create form
  readonly form: Locator;
  readonly nameInput: Locator;
  readonly keyInput: Locator;
  readonly descriptionInput: Locator;
  readonly hypothesisInput: Locator;
  readonly typeSelect: Locator;
  readonly addVariantButton: Locator;
  readonly variantNameInputs: Locator;
  readonly variantAllocationInputs: Locator;
  readonly addMetricButton: Locator;
  readonly metricNameInputs: Locator;
  readonly metricEventInputs: Locator;
  readonly submitButton: Locator;
  readonly formError: Locator;

  // Detail page
  readonly detail: Locator;
  readonly detailName: Locator;
  readonly detailKey: Locator;
  readonly statusBadge: Locator;
  readonly variantsTable: Locator;
  readonly metricsList: Locator;
  readonly actions: Locator;
  readonly startButton: Locator;
  readonly pauseButton: Locator;
  readonly completeButton: Locator;
  readonly archiveButton: Locator;
  readonly confirmDialog: Locator;
  readonly confirmButton: Locator;
  readonly confirmCancelButton: Locator;
  readonly actionError: Locator;
  readonly resultsLink: Locator;
  readonly notFound: Locator;

  constructor(page: Page) {
    this.page = page;
    this.common = new CommonPage(page);

    // List
    this.createButton = page.getByTestId("new-experiment-btn");
    this.experimentList = page.getByTestId("experiments-table");
    this.experimentRows = page.getByTestId("experiment-row");
    this.statusFilter = page.getByTestId("status-filter");
    this.firstRunChecklist = page.getByTestId("first-run-checklist");
    this.emptyState = page.getByTestId("experiments-empty");
    this.listError = page.getByTestId("experiments-error");

    // Create form
    this.form = page.getByTestId("new-experiment-form");
    this.nameInput = page.getByTestId("experiment-name");
    this.keyInput = page.getByTestId("experiment-key");
    this.descriptionInput = page.getByTestId("experiment-description");
    this.hypothesisInput = page.getByTestId("experiment-hypothesis");
    this.typeSelect = page.getByTestId("experiment-type");
    this.addVariantButton = page.getByTestId("add-variant");
    this.variantNameInputs = page.locator('[data-testid^="variant-name-"]');
    this.variantAllocationInputs = page.locator('[data-testid^="variant-allocation-"]');
    this.addMetricButton = page.getByTestId("add-metric");
    this.metricNameInputs = page.locator('[data-testid^="metric-name-"]');
    this.metricEventInputs = page.locator('[data-testid^="metric-event-"]');
    this.submitButton = page.getByTestId("submit-experiment");
    this.formError = page.getByTestId("form-error");

    // Detail
    this.detail = page.getByTestId("experiment-detail");
    this.detailName = page.getByTestId("experiment-name");
    this.detailKey = page.getByTestId("experiment-key");
    this.statusBadge = page.getByTestId("experiment-status");
    this.variantsTable = page.getByTestId("variants-table");
    this.metricsList = page.getByTestId("metrics-list");
    this.actions = page.getByTestId("experiment-actions");
    this.startButton = page.getByTestId("action-start");
    this.pauseButton = page.getByTestId("action-pause");
    this.completeButton = page.getByTestId("action-complete");
    this.archiveButton = page.getByTestId("action-archive");
    this.confirmDialog = page.getByTestId("confirm-action");
    this.confirmButton = page.getByTestId("confirm-yes");
    this.confirmCancelButton = page.getByTestId("confirm-cancel");
    this.actionError = page.getByTestId("action-error");
    this.resultsLink = page.getByTestId("view-results");
    this.notFound = page.getByTestId("experiment-not-found");
  }

  async goto() {
    await this.common.navigateTo("/experiments");
  }

  async gotoNew() {
    await this.common.navigateTo("/experiments/new");
  }

  async gotoExperiment(id: string) {
    await this.common.navigateTo(`/experiments/${id}`);
  }

  /** Filter pill on the list page: `all | draft | active | paused | completed`. */
  async filterByStatus(status: "all" | "draft" | "active" | "paused" | "completed") {
    await this.page.getByTestId(`filter-${status}`).click();
    await this.common.waitForPageReady();
  }

  /**
   * Fill the create form and submit. The form ships with Control/Treatment
   * variants (50/50) and one conversion metric, so name + key are enough for
   * a valid `ExperimentCreate` payload. Resolves with the new experiment id
   * once the detail page has loaded.
   */
  async createExperiment(
    name: string,
    key: string,
    options: { description?: string; metricEventName?: string } = {},
  ): Promise<string> {
    await this.gotoNew();
    await this.nameInput.fill(name);
    await this.keyInput.fill(key);
    if (options.description) {
      await this.descriptionInput.fill(options.description);
    }
    if (options.metricEventName) {
      await this.metricEventInputs.first().fill(options.metricEventName);
    }
    await this.submitButton.click();
    await this.page.waitForURL(/\/experiments\/[^/]+$/, { timeout: 15_000 });
    await expect(this.detail).toBeVisible({ timeout: 15_000 });
    const match = this.page.url().match(/\/experiments\/([^/?#]+)/);
    return match ? match[1] : "";
  }

  getExperimentRow(name: string): Locator {
    return this.experimentRows.filter({ hasText: name }).first();
  }

  async clickExperiment(name: string) {
    await this.getExperimentRow(name).getByTestId("experiment-link").click();
    await expect(this.detail).toBeVisible({ timeout: 15_000 });
  }

  async getExperimentCount(): Promise<number> {
    return this.experimentRows.count();
  }

  /** Lower-case status from the detail page pill (`draft`, `active`, …). */
  async getStatus(): Promise<string> {
    return (await this.statusBadge.getAttribute("data-status")) ?? "";
  }

  async expectStatus(status: string) {
    await expect(this.statusBadge).toHaveAttribute("data-status", status, { timeout: 15_000 });
  }

  async startExperiment() {
    await this.startButton.click();
    await this.expectStatus("active");
  }

  async pauseExperiment() {
    await this.pauseButton.click();
    await this.expectStatus("paused");
  }

  /** Complete is guarded by an inline confirmation. */
  async completeExperiment() {
    await this.completeButton.click();
    await this.confirmButton.click();
    await this.expectStatus("completed");
  }

  /** Archive is guarded by an inline confirmation. */
  async archiveExperiment() {
    await this.archiveButton.click();
    await this.confirmButton.click();
    await this.expectStatus("archived");
  }

  async viewResults() {
    await this.resultsLink.click();
    await this.page.waitForURL(/\/results\/[^/]+$/, { timeout: 15_000 });
    await this.common.waitForPageReady();
  }
}
