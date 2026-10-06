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
});
