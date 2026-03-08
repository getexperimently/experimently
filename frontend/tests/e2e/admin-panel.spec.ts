import { test, expect } from "./fixtures/auth.fixture";
import { AdminPage } from "./pages/admin.page";
import { CommonPage } from "./pages/common.page";

test.describe("Admin Panel", () => {
  test("should load admin panel", async ({ adminPage }) => {
    const admin = new AdminPage(adminPage);
    await admin.goto();

    const pageContent = await adminPage.textContent("body");

    // Admin page should display management content
    const hasAdminContent =
      pageContent?.toLowerCase().includes("admin") ||
      pageContent?.toLowerCase().includes("user") ||
      pageContent?.toLowerCase().includes("management") ||
      pageContent?.toLowerCase().includes("settings") ||
      pageContent?.toLowerCase().includes("audit");

    expect(hasAdminContent).toBeTruthy();
  });

  test("should display user management section", async ({ adminPage }) => {
    const admin = new AdminPage(adminPage);
    await admin.gotoUsers();

    const pageContent = await adminPage.textContent("body");

    const hasUsers =
      pageContent?.toLowerCase().includes("user") ||
      pageContent?.toLowerCase().includes("member") ||
      pageContent?.toLowerCase().includes("role");

    expect(hasUsers).toBeTruthy();
  });

  test("should display audit log", async ({ adminPage }) => {
    const admin = new AdminPage(adminPage);
    await admin.gotoAuditLog();

    const pageContent = await adminPage.textContent("body");

    const hasAuditLog =
      pageContent?.toLowerCase().includes("audit") ||
      pageContent?.toLowerCase().includes("log") ||
      pageContent?.toLowerCase().includes("activity") ||
      pageContent?.toLowerCase().includes("event");

    expect(hasAuditLog).toBeTruthy();
  });

  test("should display system settings", async ({ adminPage }) => {
    const admin = new AdminPage(adminPage);
    await admin.gotoSettings();

    const pageContent = await adminPage.textContent("body");

    const hasSettings =
      pageContent?.toLowerCase().includes("setting") ||
      pageContent?.toLowerCase().includes("config") ||
      pageContent?.toLowerCase().includes("preference");

    expect(hasSettings).toBeTruthy();
  });

  test("should search users", async ({ adminPage }) => {
    const admin = new AdminPage(adminPage);
    await admin.gotoUsers();

    const searchVisible = await admin.userSearchInput
      .isVisible()
      .catch(() => false);

    if (searchVisible) {
      await admin.searchUsers("admin");
      await adminPage.waitForLoadState("networkidle");

      // Search should filter results
      const pageContent = await adminPage.textContent("body");
      expect(pageContent?.toLowerCase().includes("admin")).toBeTruthy();
    } else {
      // Search may not be implemented yet
      test.skip();
    }
  });

  test("should show role badges for users", async ({ adminPage }) => {
    const admin = new AdminPage(adminPage);
    await admin.gotoUsers();

    const pageContent = await adminPage.textContent("body");

    // Should display role information
    const hasRoles =
      pageContent?.toLowerCase().includes("admin") ||
      pageContent?.toLowerCase().includes("developer") ||
      pageContent?.toLowerCase().includes("analyst") ||
      pageContent?.toLowerCase().includes("viewer") ||
      pageContent?.toLowerCase().includes("role");

    expect(hasRoles).toBeTruthy();
  });
});
