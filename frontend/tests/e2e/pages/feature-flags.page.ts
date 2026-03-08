import { type Page, type Locator } from "@playwright/test";
import { CommonPage } from "./common.page";

/**
 * Page object for feature flag management pages.
 */
export class FeatureFlagsPage {
  readonly page: Page;
  readonly common: CommonPage;

  // List page
  readonly createButton: Locator;
  readonly flagList: Locator;
  readonly searchInput: Locator;

  // Form fields
  readonly nameInput: Locator;
  readonly keyInput: Locator;
  readonly descriptionInput: Locator;

  // Toggle & rollout
  readonly toggleSwitch: Locator;
  readonly rolloutPercentageInput: Locator;

  // Rollout schedule
  readonly createScheduleButton: Locator;
  readonly scheduleNameInput: Locator;

  // Actions
  readonly saveButton: Locator;
  readonly deleteButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.common = new CommonPage(page);

    // List
    this.createButton = page.locator(
      'button:has-text("Create"), a:has-text("Create"), button:has-text("New Flag")'
    );
    this.flagList = page.locator(
      '[class*="flag-list"], table, [class*="list"]'
    );
    this.searchInput = page.locator(
      'input[placeholder*="search" i], input[placeholder*="filter" i]'
    );

    // Form
    this.nameInput = page.locator(
      'input[name="name"], input[placeholder*="name" i]'
    );
    this.keyInput = page.locator(
      'input[name="key"], input[name="flag_key"]'
    );
    this.descriptionInput = page.locator(
      'textarea[name="description"], input[name="description"]'
    );

    // Toggle & rollout
    this.toggleSwitch = page.locator(
      'input[type="checkbox"][role="switch"], [class*="toggle"], [class*="switch"]'
    );
    this.rolloutPercentageInput = page.locator(
      'input[name*="rollout"], input[name*="percentage"], input[type="range"]'
    );

    // Rollout schedule
    this.createScheduleButton = page.locator(
      'button:has-text("Schedule"), button:has-text("Create Schedule")'
    );
    this.scheduleNameInput = page.locator(
      'input[name="schedule_name"], input[placeholder*="schedule" i]'
    );

    // Actions
    this.saveButton = page.locator(
      'button:has-text("Save"), button[type="submit"]'
    );
    this.deleteButton = page.locator('button:has-text("Delete")');
  }

  async goto() {
    await this.common.navigateTo("/feature-flags");
  }

  async gotoFlag(id: string) {
    await this.common.navigateTo(`/feature-flags/${id}`);
  }

  async createFlag(name: string, key: string, description?: string) {
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

  async clickFlag(name: string) {
    const row = this.flagList
      .locator(`tr:has-text("${name}"), [class*="row"]:has-text("${name}")`)
      .first();
    await row.click();
    await this.common.waitForPageReady();
  }

  async toggleFlag() {
    await this.toggleSwitch.first().click();
    await this.common.waitForPageReady();
  }

  async setRolloutPercentage(percentage: number) {
    await this.rolloutPercentageInput.fill(String(percentage));
    await this.saveButton.click();
    await this.common.waitForPageReady();
  }

  async getFlagCount(): Promise<number> {
    const rows = this.flagList.locator("tr, [class*='row'], [class*='card']");
    return rows.count();
  }

  async deleteFlag() {
    await this.deleteButton.click();
    const modalVisible = await this.common.modal
      .isVisible()
      .catch(() => false);
    if (modalVisible) {
      await this.common.confirmModal();
    }
    await this.common.waitForPageReady();
  }
}
