import { type Page, type Locator } from "@playwright/test";
import { TOKEN_STORAGE_KEY } from "../env";

/** `LOGIN_PATH` in src/services/api.ts. */
const LOGIN_PATH = "/login";

/** Copy shown by src/pages/login.tsx for a 429 from `POST /auth/login`. */
export const RATE_LIMIT_MESSAGE = /too many/i;

/**
 * The limiter's fixed window is 60s, counted from the first request in it, so
 * the budget can free up at any point inside that minute. Poll rather than
 * sleeping a whole window: a rejected attempt neither extends the window nor
 * costs anything but a round-trip.
 */
export const RATE_LIMIT_RETRY_MS = 15_000;

/**
 * Page object for `/login` (src/pages/login.tsx) and the shell's log-out
 * control (src/components/AppShell.tsx). Every selector is a `data-testid`
 * rendered by those files — no text or class heuristics.
 */
export class LoginPage {
  readonly page: Page;
  readonly form: Locator;
  readonly emailInput: Locator;
  readonly passwordInput: Locator;
  readonly submitButton: Locator;
  readonly errorMessage: Locator;
  readonly togglePassword: Locator;
  readonly logoutButton: Locator;
  readonly appShell: Locator;
  readonly userMenu: Locator;
  readonly userMenuRole: Locator;

  constructor(page: Page) {
    this.page = page;
    this.form = page.getByTestId("login-form");
    // The inputs carry generated ids (useId) and no testid; name= is stable and
    // is what the browser's autofill uses.
    this.emailInput = this.form.locator('input[name="email"]');
    this.passwordInput = this.form.locator('input[name="password"]');
    this.submitButton = page.getByTestId("login-submit");
    this.errorMessage = page.getByTestId("login-error");
    this.togglePassword = page.getByTestId("toggle-password");
    this.logoutButton = page.getByTestId("logout-button");
    this.appShell = page.getByTestId("app-shell");
    this.userMenu = page.getByTestId("user-menu");
    this.userMenuRole = page.getByTestId("user-menu-role");
  }

  async goto(next?: string) {
    const target = next ? `/login?next=${encodeURIComponent(next)}` : "/login";
    await this.page.goto(target);
    await this.form.waitFor({ state: "visible", timeout: 30_000 });
  }

  /** Fill the form and submit. Does not assert on the outcome. */
  async submit(email: string, password: string) {
    await this.emailInput.fill(email);
    await this.passwordInput.fill(password);
    await this.submitButton.click();
  }

  /**
   * Submit and wait for the app to settle — either it navigated away from
   * /login, or the form is showing an error.
   */
  private async settle(timeout = 20_000): Promise<"navigated" | "error"> {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      if (!new URL(this.page.url()).pathname.startsWith(LOGIN_PATH)) return "navigated";
      if (await this.errorMessage.isVisible()) return "error";
      await this.page.waitForTimeout(100);
    }
    return "error";
  }

  /**
   * Submit, and if the platform's brute-force guard answers 429
   * ("Too many attempts…"), wait out its fixed window and submit again.
   *
   * `POST /api/v1/auth/login` allows 10 requests per minute per IP
   * (`RATE_LIMIT_CONFIG` in backend/app/middleware/rate_limiter.py) and a whole
   * browser suite shares one IP, so back-to-back runs can trip it. Any other
   * error returns immediately for the caller to assert on — this waits out the
   * rate limiter, it does not paper over failed credentials.
   */
  async submitResilient(email: string, password: string, attempts = 5): Promise<void> {
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      await this.submit(email, password);
      if ((await this.settle()) === "navigated") return;

      const text = (await this.errorMessage.innerText().catch(() => "")) ?? "";
      if (!RATE_LIMIT_MESSAGE.test(text) || attempt === attempts) return;
      await this.page.waitForTimeout(RATE_LIMIT_RETRY_MS);
    }
  }

  async logout() {
    await this.logoutButton.click();
    await this.page.waitForURL(/\/login(\?|$)/, { timeout: 15_000 });
  }

  /** The bearer token the app stores after a successful login. */
  async storedToken(): Promise<string | null> {
    return this.page.evaluate((key) => window.localStorage.getItem(key), TOKEN_STORAGE_KEY);
  }
}
