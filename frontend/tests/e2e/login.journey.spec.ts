import { test, expect, TEST_USERS } from "./fixtures/auth.fixture";
import { LoginPage } from "./pages/login.page";
import { TOKEN_STORAGE_KEY } from "./env";

/**
 * Journey 1 — login.
 *
 * The dashboard is fail-closed: every route except `/`, `/login`, `/docs/**`
 * and `/power-calculator` is wrapped in `<RequireAuth>` by `_app.tsx`, and the
 * API is the real enforcement. This journey walks the whole session lifecycle
 * against a backend running with `AUTH_PROVIDER=local` / `DEV_AUTH_BYPASS=false`:
 * redirect → rejection → success → token → logout → deep link.
 *
 * Every assertion is hard: there is no "dev mode has no login" branch.
 */
test.describe("Journey: login", () => {
  test.describe.configure({ mode: "serial" });

  const admin = TEST_USERS.admin;

  test("an anonymous visitor is redirected to /login and keeps the deep link", async ({ page }) => {
    await page.goto("/experiments");

    // RequireAuth replaces the URL once the session resolves to `anonymous`.
    await page.waitForURL(/\/login\?next=/, { timeout: 15_000 });
    expect(new URL(page.url()).searchParams.get("next")).toBe("/experiments");

    const loginPage = new LoginPage(page);
    await expect(loginPage.form).toBeVisible();
    await expect(loginPage.emailInput).toBeVisible();
    await expect(loginPage.passwordInput).toBeVisible();
    await expect(loginPage.submitButton).toBeEnabled();
    // Nothing of the app is reachable behind the login wall.
    await expect(page.getByTestId("experiments-table")).toHaveCount(0);
    expect(await loginPage.storedToken()).toBeNull();
  });

  test("a wrong password is rejected in place, with no token stored", async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    // `submitResilient` retries only on the 10/min rate-limit copy, so a wrong
    // password still lands on the assertion below.
    await loginPage.submitResilient(admin.username, "definitely-not-the-password");

    await expect(loginPage.errorMessage).toBeVisible({ timeout: 15_000 });
    await expect(loginPage.errorMessage).toHaveText("Email or password is incorrect.");
    await expect(page).toHaveURL(/\/login/);
    expect(await loginPage.storedToken()).toBeNull();
    // The form stays usable for a second attempt.
    await expect(loginPage.submitButton).toBeEnabled();
  });

  test("the right password lands on /experiments with the shell and a token", async ({ page }) => {
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.submitResilient(admin.username, admin.password);

    await page.waitForURL(/\/experiments$/, { timeout: 20_000 });
    await expect(loginPage.appShell).toBeVisible();
    await expect(page.getByTestId("nav-experiments")).toBeVisible();
    await expect(page.getByTestId("nav-feature-flags")).toBeVisible();
    await expect(loginPage.userMenu).toBeVisible();
    await expect(page.getByTestId("user-menu-name")).toContainText("Admin");
    await expect(loginPage.userMenuRole).toHaveText(admin.roleLabel);
    await expect(loginPage.logoutButton).toBeVisible();

    const token = await loginPage.storedToken();
    expect(token, `expected a bearer token in localStorage["${TOKEN_STORAGE_KEY}"]`).toBeTruthy();
    expect(token!.length).toBeGreaterThan(20);

    // The list itself renders for the signed-in user (seeded demo data).
    await expect(page.getByTestId("experiments-table")).toBeVisible({ timeout: 15_000 });

    // --- log out -----------------------------------------------------------
    await loginPage.logout();
    await expect(page).toHaveURL(/\/login(\?|$)/);
    await expect(loginPage.form).toBeVisible();
    expect(await loginPage.storedToken()).toBeNull();

    // The session is really gone: protected routes bounce again.
    await page.goto("/experiments");
    await page.waitForURL(/\/login\?next=/, { timeout: 15_000 });
  });

  test("a deep link survives the login round-trip", async ({ page }) => {
    await page.goto("/feature-flags");
    await page.waitForURL(/\/login\?next=/, { timeout: 15_000 });
    expect(new URL(page.url()).searchParams.get("next")).toBe("/feature-flags");

    const loginPage = new LoginPage(page);
    await loginPage.submitResilient(admin.username, admin.password);

    await page.waitForURL(/\/feature-flags$/, { timeout: 20_000 });
    await expect(page.getByTestId("app-shell")).toBeVisible();
    await expect(page.getByTestId("flags-table")).toBeVisible({ timeout: 15_000 });
  });
});
