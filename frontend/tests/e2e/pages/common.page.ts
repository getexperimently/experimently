import { type Page, type Locator } from "@playwright/test";

/**
 * Common page object with shared navigation, toasts, and modal helpers.
 */
export class CommonPage {
  readonly page: Page;
  readonly nav: Locator;
  readonly toastContainer: Locator;
  readonly modal: Locator;
  readonly modalConfirm: Locator;
  readonly modalCancel: Locator;
  readonly spinner: Locator;

  constructor(page: Page) {
    this.page = page;
    this.nav = page.locator("nav");
    this.toastContainer = page.locator('[role="alert"], [class*="toast"]');
    this.modal = page.locator('[role="dialog"], [class*="modal"]');
    this.modalConfirm = this.modal.locator(
      'button:has-text("Confirm"), button:has-text("Yes"), button:has-text("Delete"), button:has-text("OK")'
    );
    this.modalCancel = this.modal.locator(
      'button:has-text("Cancel"), button:has-text("No"), button:has-text("Close")'
    );
    this.spinner = page.locator(
      '[class*="spinner"], [class*="loading"], [role="progressbar"]'
    );
  }

  async navigateTo(path: string) {
    await this.page.goto(path);
    await this.page.waitForLoadState("networkidle");
  }

  async waitForPageReady() {
    await this.page.waitForLoadState("networkidle");
    // Wait for spinners to disappear
    await this.spinner.waitFor({ state: "hidden", timeout: 10_000 }).catch(() => {
      // No spinner present — that's fine
    });
  }

  async expectToastMessage(text: string) {
    await this.toastContainer.filter({ hasText: text }).waitFor({ timeout: 5_000 });
  }

  async confirmModal() {
    await this.modal.waitFor({ state: "visible" });
    await this.modalConfirm.click();
  }

  async cancelModal() {
    await this.modal.waitFor({ state: "visible" });
    await this.modalCancel.click();
  }

  async clickNavLink(text: string) {
    await this.nav.getByRole("link", { name: text }).click();
    await this.waitForPageReady();
  }

  async getPageTitle(): Promise<string> {
    return this.page.locator("h1").first().innerText();
  }
}
