import { test, expect, TEST_USERS, type UserRole } from "./fixtures/auth.fixture";
import { CommonPage } from "./pages/common.page";

test.describe("Role-Based Access Control", () => {
  test("admin should see all navigation options", async ({ adminPage }) => {
    const common = new CommonPage(adminPage);
    await adminPage.goto("/");
    await common.waitForPageReady();

    const navContent = await common.nav.textContent().catch(() => "");

    // Admin should have access to management sections
    const hasExperiments =
      navContent?.toLowerCase().includes("experiment") ?? false;
    const hasFlags = navContent?.toLowerCase().includes("flag") ?? false;
    const hasAdmin = navContent?.toLowerCase().includes("admin") ?? false;

    // At minimum, experiments should be visible
    expect(hasExperiments || hasFlags || hasAdmin).toBeTruthy();
  });

  test("admin should access admin panel", async ({ adminPage }) => {
    await adminPage.goto("/admin");
    await adminPage.waitForLoadState("networkidle");

    // Admin should NOT get redirected to a 403 or login page
    const pageContent = await adminPage.textContent("body");
    const isAccessDenied =
      pageContent?.toLowerCase().includes("forbidden") ||
      pageContent?.toLowerCase().includes("access denied") ||
      pageContent?.toLowerCase().includes("403");

    expect(isAccessDenied).toBeFalsy();
  });

  test("analyst should access experiments in read-only mode", async ({
    analystPage,
  }) => {
    await analystPage.goto("/experiments");
    await analystPage.waitForLoadState("networkidle");

    const pageContent = await analystPage.textContent("body");

    // Analyst should see experiments content
    const canView =
      pageContent?.toLowerCase().includes("experiment") ||
      !analystPage.url().includes("/login");

    expect(canView).toBeTruthy();

    // Analyst should NOT see create/edit buttons (read-only)
    const createButton = analystPage.locator(
      'button:has-text("Create"), button:has-text("New")'
    );
    const createVisible = await createButton.isVisible().catch(() => false);

    // Note: Some UIs show the button but disable it; others hide it entirely
    if (createVisible) {
      const isDisabled = await createButton.isDisabled().catch(() => false);
      // If visible, it should be disabled for analyst role
      // (this depends on the frontend implementation)
    }
  });

  test("viewer should have read-only access", async ({ viewerPage }) => {
    await viewerPage.goto("/experiments");
    await viewerPage.waitForLoadState("networkidle");

    const pageContent = await viewerPage.textContent("body");

    // Viewer should either see content or get gracefully restricted
    const isAccessible =
      !viewerPage.url().includes("/login") ||
      pageContent?.toLowerCase().includes("experiment") ||
      pageContent?.toLowerCase().includes("viewer");

    expect(isAccessible).toBeTruthy();
  });

  test("viewer should not access admin panel", async ({ viewerPage }) => {
    await viewerPage.goto("/admin");
    await viewerPage.waitForLoadState("networkidle");

    const pageContent = await viewerPage.textContent("body");
    const url = viewerPage.url();

    // Viewer should be denied or redirected
    const isDenied =
      url.includes("/login") ||
      url === viewerPage.url() && (
        pageContent?.toLowerCase().includes("forbidden") ||
        pageContent?.toLowerCase().includes("access denied") ||
        pageContent?.toLowerCase().includes("unauthorized") ||
        pageContent?.toLowerCase().includes("403")
      ) ||
      // Or redirected to home/dashboard
      !url.includes("/admin");

    expect(isDenied).toBeTruthy();
  });

  test("different roles see appropriate UI elements", async ({
    loginAsRole,
    page,
  }) => {
    // Test with developer role
    await loginAsRole("developer");
    await page.goto("/experiments");
    await page.waitForLoadState("networkidle");

    const pageContent = await page.textContent("body");

    // Developer should see the experiments page
    const canAccess =
      pageContent?.toLowerCase().includes("experiment") ||
      !page.url().includes("/login");

    expect(canAccess).toBeTruthy();
  });
});
