import { type Page, type Locator } from "@playwright/test";

/**
 * Page object for the login form.
 */
export class LoginPage {
  readonly page: Page;
  readonly usernameInput: Locator;
  readonly passwordInput: Locator;
  readonly emailInput: Locator;
  readonly submitButton: Locator;
  readonly errorMessage: Locator;
  readonly logoutButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.usernameInput = page.locator(
      'input[name="username"], input[type="text"][placeholder*="user" i]'
    );
    this.passwordInput = page.locator('input[type="password"]');
    this.emailInput = page.locator('input[type="email"], input[name="email"]');
    this.submitButton = page.locator(
      'button[type="submit"], button:has-text("Log in"), button:has-text("Sign in")'
    );
    this.errorMessage = page.locator(
      '[class*="error"], [role="alert"]:has-text("error"), [class*="Error"]'
    );
    this.logoutButton = page.locator(
      'button:has-text("Log out"), button:has-text("Logout"), a:has-text("Log out")'
    );
  }

  async goto() {
    await this.page.goto("/login");
    await this.page.waitForLoadState("networkidle");
  }

  async login(username: string, password: string) {
    // Try username field first, fall back to email
    const usernameVisible = await this.usernameInput.isVisible().catch(() => false);
    if (usernameVisible) {
      await this.usernameInput.fill(username);
    } else {
      await this.emailInput.fill(username);
    }
    await this.passwordInput.fill(password);
    await this.submitButton.click();
    await this.page.waitForLoadState("networkidle");
  }

  async logout() {
    await this.logoutButton.click();
    await this.page.waitForLoadState("networkidle");
  }

  async expectLoginError() {
    await this.errorMessage.waitFor({ state: "visible", timeout: 5_000 });
  }

  async isLoggedIn(): Promise<boolean> {
    // Check if we're NOT on the login page (redirected to dashboard)
    const url = this.page.url();
    return !url.includes("/login");
  }
}
