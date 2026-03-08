import { test, expect } from "./fixtures/auth.fixture";

/**
 * Visual regression tests using Playwright's built-in screenshot comparison.
 *
 * Baselines are stored in `frontend/tests/e2e/__screenshots__/`.
 * Update baselines with: `npx playwright test visual-regression --update-snapshots`
 *
 * maxDiffPixelRatio allows small rendering differences across environments.
 */

const VISUAL_OPTIONS = {
  maxDiffPixelRatio: 0.02, // Allow 2% pixel difference
  threshold: 0.3, // Color difference threshold
};

test.describe("Visual Regression", () => {
  test.describe("Dashboard", () => {
    test("home page", async ({ adminPage }) => {
      await adminPage.goto("/");
      await adminPage.waitForLoadState("networkidle");
      await expect(adminPage).toHaveScreenshot("dashboard-home.png", VISUAL_OPTIONS);
    });
  });

  test.describe("Experiments", () => {
    test("experiment list page", async ({ adminPage }) => {
      await adminPage.goto("/experiments");
      await adminPage.waitForLoadState("networkidle");
      await expect(adminPage).toHaveScreenshot(
        "experiment-list.png",
        VISUAL_OPTIONS
      );
    });

    test("experiment list - filtered view", async ({ adminPage }) => {
      await adminPage.goto("/experiments");
      await adminPage.waitForLoadState("networkidle");

      // Try to apply a status filter if available
      const filter = adminPage.locator(
        'select[name*="status"], [class*="filter"]'
      );
      if (await filter.isVisible().catch(() => false)) {
        await filter.selectOption({ index: 1 }).catch(() => {});
        await adminPage.waitForLoadState("networkidle");
      }

      await expect(adminPage).toHaveScreenshot(
        "experiment-list-filtered.png",
        VISUAL_OPTIONS
      );
    });
  });

  test.describe("Feature Flags", () => {
    test("feature flag list page", async ({ adminPage }) => {
      await adminPage.goto("/feature-flags");
      await adminPage.waitForLoadState("networkidle");
      await expect(adminPage).toHaveScreenshot(
        "feature-flag-list.png",
        VISUAL_OPTIONS
      );
    });
  });

  test.describe("Admin Panel", () => {
    test("admin dashboard", async ({ adminPage }) => {
      await adminPage.goto("/admin");
      await adminPage.waitForLoadState("networkidle");
      await expect(adminPage).toHaveScreenshot(
        "admin-dashboard.png",
        VISUAL_OPTIONS
      );
    });
  });

  test.describe("Login", () => {
    test("login page", async ({ page }) => {
      await page.goto("/login");
      await page.waitForLoadState("networkidle");
      await expect(page).toHaveScreenshot("login-page.png", VISUAL_OPTIONS);
    });
  });

  test.describe("Responsive", () => {
    test("dashboard at mobile viewport", async ({ adminPage }) => {
      await adminPage.setViewportSize({ width: 375, height: 812 });
      await adminPage.goto("/");
      await adminPage.waitForLoadState("networkidle");
      await expect(adminPage).toHaveScreenshot(
        "dashboard-mobile.png",
        VISUAL_OPTIONS
      );
    });

    test("experiment list at tablet viewport", async ({ adminPage }) => {
      await adminPage.setViewportSize({ width: 768, height: 1024 });
      await adminPage.goto("/experiments");
      await adminPage.waitForLoadState("networkidle");
      await expect(adminPage).toHaveScreenshot(
        "experiment-list-tablet.png",
        VISUAL_OPTIONS
      );
    });
  });
});
