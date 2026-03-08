import { type Page, type Locator } from "@playwright/test";
import { CommonPage } from "./common.page";

/**
 * Page object for experiment list and detail pages.
 */
export class ExperimentsPage {
  readonly page: Page;
  readonly common: CommonPage;

  // List page
  readonly createButton: Locator;
  readonly experimentList: Locator;
  readonly searchInput: Locator;
  readonly statusFilter: Locator;

  // Detail / form fields
  readonly nameInput: Locator;
  readonly descriptionInput: Locator;
  readonly keyInput: Locator;
  readonly statusBadge: Locator;

  // Variant management
  readonly addVariantButton: Locator;
  readonly variantNameInput: Locator;
  readonly variantWeightInput: Locator;

  // Metric management
  readonly addMetricButton: Locator;
  readonly metricNameInput: Locator;

  // Action buttons
  readonly startButton: Locator;
  readonly pauseButton: Locator;
  readonly archiveButton: Locator;
  readonly deleteButton: Locator;
  readonly saveButton: Locator;

  // Results tab
  readonly resultsTab: Locator;

  constructor(page: Page) {
    this.page = page;
    this.common = new CommonPage(page);

    // List page
    this.createButton = page.locator(
      'button:has-text("Create"), a:has-text("Create"), button:has-text("New Experiment")'
    );
    this.experimentList = page.locator(
      '[class*="experiment-list"], table, [class*="list"]'
    );
    this.searchInput = page.locator(
      'input[placeholder*="search" i], input[placeholder*="filter" i]'
    );
    this.statusFilter = page.locator(
      'select[name*="status"], [class*="status-filter"]'
    );

    // Form fields
    this.nameInput = page.locator(
      'input[name="name"], input[placeholder*="name" i]'
    );
    this.descriptionInput = page.locator(
      'textarea[name="description"], input[name="description"]'
    );
    this.keyInput = page.locator(
      'input[name="key"], input[name="experiment_key"]'
    );
    this.statusBadge = page.locator(
      '[class*="status"], [class*="badge"]:near(h1)'
    );

    // Variants
    this.addVariantButton = page.locator(
      'button:has-text("Add Variant"), button:has-text("Add variant")'
    );
    this.variantNameInput = page.locator(
      'input[name*="variant_name"], input[placeholder*="variant" i]'
    );
    this.variantWeightInput = page.locator(
      'input[name*="weight"], input[type="number"][placeholder*="weight" i]'
    );

    // Metrics
    this.addMetricButton = page.locator(
      'button:has-text("Add Metric"), button:has-text("Add metric")'
    );
    this.metricNameInput = page.locator(
      'input[name*="metric_name"], input[placeholder*="metric" i]'
    );

    // Actions
    this.startButton = page.locator('button:has-text("Start"), button:has-text("Activate")');
    this.pauseButton = page.locator('button:has-text("Pause")');
    this.archiveButton = page.locator('button:has-text("Archive"), button:has-text("Complete")');
    this.deleteButton = page.locator('button:has-text("Delete")');
    this.saveButton = page.locator('button:has-text("Save"), button[type="submit"]');

    // Results
    this.resultsTab = page.locator(
      'button:has-text("Results"), a:has-text("Results"), [role="tab"]:has-text("Results")'
    );
  }

  async goto() {
    await this.common.navigateTo("/experiments");
  }

  async gotoExperiment(id: string) {
    await this.common.navigateTo(`/experiments/${id}`);
  }

  async createExperiment(name: string, key: string, description?: string) {
    await this.createButton.click();
    await this.page.waitForLoadState("networkidle");
    await this.nameInput.fill(name);
    await this.keyInput.fill(key);
    if (description) {
      await this.descriptionInput.fill(description);
    }
    await this.saveButton.click();
    await this.common.waitForPageReady();
  }

  async getExperimentRow(name: string): Promise<Locator> {
    return this.experimentList
      .locator(`tr:has-text("${name}"), [class*="row"]:has-text("${name}")`)
      .first();
  }

  async clickExperiment(name: string) {
    const row = await this.getExperimentRow(name);
    await row.click();
    await this.common.waitForPageReady();
  }

  async getExperimentCount(): Promise<number> {
    const rows = this.experimentList.locator("tr, [class*='row'], [class*='card']");
    return rows.count();
  }

  async startExperiment() {
    await this.startButton.click();
    await this.common.waitForPageReady();
  }

  async pauseExperiment() {
    await this.pauseButton.click();
    await this.common.waitForPageReady();
  }

  async archiveExperiment() {
    await this.archiveButton.click();
    await this.common.waitForPageReady();
  }

  async deleteExperiment() {
    await this.deleteButton.click();
    // May trigger confirmation modal
    const modalVisible = await this.common.modal
      .isVisible()
      .catch(() => false);
    if (modalVisible) {
      await this.common.confirmModal();
    }
    await this.common.waitForPageReady();
  }

  async viewResults() {
    await this.resultsTab.click();
    await this.common.waitForPageReady();
  }
}
