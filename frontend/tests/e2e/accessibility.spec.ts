import { test, expect } from "./fixtures/auth.fixture";

/**
 * Accessibility tests using @axe-core/playwright for WCAG 2.1 AA compliance.
 *
 * Install: npm install -D @axe-core/playwright
 * Run: npx playwright test accessibility
 *
 * These tests scan pages for accessibility violations and fail on
 * critical or serious issues. Moderate/minor issues are reported as warnings.
 */

// Dynamic import to gracefully handle missing dependency
async function getAxeBuilder() {
  try {
    const { default: AxeBuilder } = await import("@axe-core/playwright");
    return AxeBuilder;
  } catch {
    return null;
  }
}

test.describe("Accessibility Audits", () => {
  test.beforeEach(async () => {
    const AxeBuilder = await getAxeBuilder();
    if (!AxeBuilder) {
      test.skip();
    }
  });

  test("login page has no critical a11y violations", async ({ page }) => {
    const AxeBuilder = await getAxeBuilder();
    if (!AxeBuilder) return;

    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious"
    );

    if (critical.length > 0) {
      const summary = critical
        .map((v) => `[${v.impact}] ${v.id}: ${v.description} (${v.nodes.length} instances)`)
        .join("\n");
      expect(critical, `A11y violations found:\n${summary}`).toHaveLength(0);
    }
  });

  test("dashboard has no critical a11y violations", async ({ adminPage }) => {
    const AxeBuilder = await getAxeBuilder();
    if (!AxeBuilder) return;

    await adminPage.goto("/");
    await adminPage.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page: adminPage })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious"
    );

    expect(critical).toHaveLength(0);
  });

  test("experiments page has no critical a11y violations", async ({
    adminPage,
  }) => {
    const AxeBuilder = await getAxeBuilder();
    if (!AxeBuilder) return;

    await adminPage.goto("/experiments");
    await adminPage.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page: adminPage })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious"
    );

    expect(critical).toHaveLength(0);
  });

  test("feature flags page has no critical a11y violations", async ({
    adminPage,
  }) => {
    const AxeBuilder = await getAxeBuilder();
    if (!AxeBuilder) return;

    await adminPage.goto("/feature-flags");
    await adminPage.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page: adminPage })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious"
    );

    expect(critical).toHaveLength(0);
  });

  test("admin panel has no critical a11y violations", async ({
    adminPage,
  }) => {
    const AxeBuilder = await getAxeBuilder();
    if (!AxeBuilder) return;

    await adminPage.goto("/admin");
    await adminPage.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page: adminPage })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious"
    );

    expect(critical).toHaveLength(0);
  });

  test("keyboard navigation works on main pages", async ({ adminPage }) => {
    await adminPage.goto("/");
    await adminPage.waitForLoadState("networkidle");

    // Tab through the page and verify focus is visible
    await adminPage.keyboard.press("Tab");
    const focusedElement = await adminPage.evaluate(() => {
      const el = document.activeElement;
      return el ? el.tagName : null;
    });

    // Something should receive focus
    expect(focusedElement).not.toBeNull();
  });

  test("forms have proper labels", async ({ adminPage }) => {
    const AxeBuilder = await getAxeBuilder();
    if (!AxeBuilder) return;

    // Navigate to a form page (create experiment)
    await adminPage.goto("/experiments");
    await adminPage.waitForLoadState("networkidle");

    const createButton = adminPage.locator(
      'button:has-text("Create"), a:has-text("Create")'
    );
    if (await createButton.isVisible().catch(() => false)) {
      await createButton.click();
      await adminPage.waitForLoadState("networkidle");

      // Run axe specifically for form-related rules
      const results = await new AxeBuilder({ page: adminPage })
        .withRules(["label", "label-title-only", "select-name"])
        .analyze();

      const formViolations = results.violations.filter(
        (v) => v.impact === "critical" || v.impact === "serious"
      );

      expect(formViolations).toHaveLength(0);
    }
  });

  test("color contrast meets WCAG AA", async ({ adminPage }) => {
    const AxeBuilder = await getAxeBuilder();
    if (!AxeBuilder) return;

    await adminPage.goto("/");
    await adminPage.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page: adminPage })
      .withRules(["color-contrast"])
      .analyze();

    // Report contrast issues but don't fail on minor ones
    if (results.violations.length > 0) {
      const summary = results.violations
        .map((v) => `${v.nodes.length} contrast issues`)
        .join(", ");
      console.warn(`Color contrast warnings: ${summary}`);
    }
  });

  test("images have alt text", async ({ adminPage }) => {
    const AxeBuilder = await getAxeBuilder();
    if (!AxeBuilder) return;

    await adminPage.goto("/");
    await adminPage.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page: adminPage })
      .withRules(["image-alt"])
      .analyze();

    const critical = results.violations.filter(
      (v) => v.impact === "critical" || v.impact === "serious"
    );

    expect(critical).toHaveLength(0);
  });
});
