import { type Locator } from "@playwright/test";
import { test, expect } from "./fixtures/auth.fixture";

/**
 * Journey 8 — the header collapses to the menu button below 1280 px (#926).
 *
 * Between 768 and 1279 px the inline primary nav reached the user menu: a
 * superuser's at 1024 px, every role's at 768 px, and the "More" group landed
 * under the avatar. The three breakpoint classes in AppShell.tsx now share
 * Tailwind's `xl` (1280 px), so below it every role gets the menu button and
 * the inline nav is not rendered. jsdom applies no media queries, so
 * AppShell.test.tsx reads the classes and this case measures the layout, as
 * the seeded admin: a superuser, which is the longest nav.
 *
 * The other journeys run at Playwright's default 1280x720 and keep the inline
 * nav. Each test gets its own page, so the viewport set here outlives nothing.
 */

interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

async function boxOf(locator: Locator, what: string): Promise<Box> {
  const box = await locator.boundingBox();
  if (!box) throw new Error(`${what} has no bounding box: it is not rendered`);
  return box;
}

test.describe("Journey: header breakpoint", () => {
  test("the header collapses to the menu button below 1280 px", async ({ adminPage }) => {
    const page = adminPage;
    const inlineNav = page.getByRole("navigation", { name: "Primary", exact: true });
    const toggle = page.getByTestId("mobile-nav-toggle");
    const userMenu = page.getByTestId("user-menu");

    await page.goto("/experiments");
    await expect(page.getByTestId("app-shell")).toBeVisible();
    await expect(userMenu).toBeVisible();
    // The seeded admin is a superuser: Admin is in the nav, the longest it gets.
    await expect(page.getByTestId("nav-admin")).toBeVisible();

    // One pixel under the breakpoint: the menu button, and no inline nav.
    await page.setViewportSize({ width: 1279, height: 720 });
    await expect(toggle, "the menu button shows at 1279 px").toBeVisible();
    await expect(page.getByTestId("nav-experiments"), "no inline nav at 1279 px").toBeHidden();
    await expect(inlineNav, "no inline nav at 1279 px").toBeHidden();

    // At the breakpoint: the inline nav, no menu button, and the nav ends
    // left of the user menu (the overlap #926 measured at 768 and 1024 px).
    await page.setViewportSize({ width: 1280, height: 720 });
    await expect(page.getByTestId("nav-experiments"), "the inline nav shows at 1280 px").toBeVisible();
    await expect(inlineNav, "the inline nav shows at 1280 px").toBeVisible();
    await expect(toggle, "no menu button at 1280 px").toBeHidden();
    const nav = await boxOf(inlineNav, "the inline nav");
    const menuAt1280 = await boxOf(userMenu, "the user menu");
    expect(nav.x + nav.width, "at 1280 px the inline nav ends left of the user menu").toBeLessThanOrEqual(
      menuAt1280.x,
    );

    // Tablet: the user menu and the menu button, which is rendered to its
    // right, sit side by side and both fit inside the viewport.
    await page.setViewportSize({ width: 768, height: 720 });
    await expect(toggle, "the menu button shows at 768 px").toBeVisible();
    await expect(inlineNav, "no inline nav at 768 px").toBeHidden();
    const menuAt768 = await boxOf(userMenu, "the user menu");
    const toggleAt768 = await boxOf(toggle, "the menu button");
    expect(menuAt768.x + menuAt768.width, "at 768 px the user menu ends left of the menu button").toBeLessThanOrEqual(
      toggleAt768.x,
    );
    expect(menuAt768.x + menuAt768.width, "at 768 px the user menu fits in the viewport").toBeLessThanOrEqual(768);
    expect(toggleAt768.x + toggleAt768.width, "at 768 px the menu button fits in the viewport").toBeLessThanOrEqual(
      768,
    );
  });

  test("a superuser's header fits on one line at 1280, 1440 and 1920 px (#1069)", async ({ adminPage }) => {
    // The header row is capped at 1280 px, so every wider window has the same
    // 1216 px of content. With "Change password" in the row, a superuser's
    // links "Feature Flags" and "Audit Log" wrapped onto two lines and the
    // name was cut. The name here is the first administrator's, "Platform
    // Admin" (the seeded admin's "Admin Demo" is shorter); only that field of
    // the real /auth/me answer is changed, and only for this page.
    const page = adminPage;
    await page.route("**/api/v1/auth/me", async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, json: { ...(await response.json()), full_name: "Platform Admin" } });
    });
    const inlineNav = page.getByRole("navigation", { name: "Primary", exact: true });
    const name = page.getByTestId("user-menu-name");

    await page.goto("/experiments");
    await expect(name).toHaveText("Platform Admin");
    await expect(page.getByTestId("nav-admin")).toBeVisible();
    await expect(inlineNav.getByTestId("more-nav-group")).toBeVisible();

    for (const width of [1280, 1440, 1920]) {
      await page.setViewportSize({ width, height: 720 });
      await expect(page.getByTestId("nav-experiments")).toBeVisible();
      // "Experiments" is one word and cannot wrap: every other link and More
      // must be exactly as tall.
      const oneLine = (await boxOf(page.getByTestId("nav-experiments"), "Experiments")).height;
      for (const testId of ["nav-feature-flags", "nav-segments", "nav-audit-log", "nav-admin", "nav-docs"]) {
        const height = (await boxOf(page.getByTestId(testId), testId)).height;
        expect(height, `at ${width} px ${testId} is on one line`).toBe(oneLine);
      }
      const more = (await boxOf(inlineNav.locator("summary"), "More")).height;
      expect(more, `at ${width} px More is on one line`).toBe(oneLine);
      const fit = await name.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
      expect(fit.scroll, `at ${width} px the name is not cut`).toBeLessThanOrEqual(fit.client);
      const nav = await boxOf(inlineNav, "the inline nav");
      const menu = await boxOf(page.getByTestId("user-menu"), "the user menu");
      expect(nav.x + nav.width, `at ${width} px the nav ends left of the user menu`).toBeLessThanOrEqual(menu.x);
    }

    // Change password is in More: not in the header row, and reached from the
    // keyboard (the summary opens on Enter, the link follows on Enter).
    await page.setViewportSize({ width: 1280, height: 720 });
    await expect(page.getByTestId("user-menu").getByTestId("change-password-link")).toHaveCount(0);
    const summary = inlineNav.locator("summary");
    await summary.focus();
    await page.keyboard.press("Enter");
    const link = inlineNav.getByTestId("change-password-link");
    await expect(link).toBeVisible();
    await link.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/account\/password$/);
    await expect(page.getByRole("heading", { name: "Change password", level: 1 })).toBeVisible();
  });
});
