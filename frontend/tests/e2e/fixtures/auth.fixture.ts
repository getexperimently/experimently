import { test as base, expect as baseExpect, type Page } from "@playwright/test";
import { LoginPage } from "../pages/login.page";

/**
 * Test credentials for each role.
 *
 * These are the accounts created by `backend/scripts/seed_demo_data.py`
 * (also `SEED=demo` in docker compose). All share the password `Demo1234!`.
 * The backend must run with `AUTH_PROVIDER=local` and `DEV_AUTH_BYPASS=false`
 * so that `/login` is a real login.
 */
export const TEST_USERS = {
  admin: {
    username: "admin@demo.com",
    password: "Demo1234!",
    role: "ADMIN",
  },
  developer: {
    username: "dev@demo.com",
    password: "Demo1234!",
    role: "DEVELOPER",
  },
  analyst: {
    username: "analyst@demo.com",
    password: "Demo1234!",
    role: "ANALYST",
  },
  viewer: {
    username: "viewer@demo.com",
    password: "Demo1234!",
    role: "VIEWER",
  },
} as const;

export type UserRole = keyof typeof TEST_USERS;

/**
 * Log in through the real `/login` page and wait until the app has navigated
 * away from it. Fails loudly if the credentials are rejected — there is no
 * "dev mode skips login" tolerance any more.
 */
async function loginAs(page: Page, role: UserRole): Promise<void> {
  const loginPage = new LoginPage(page);
  const user = TEST_USERS[role];

  await loginPage.goto();
  await baseExpect(page, `expected the login form at /login for ${role}`).toHaveURL(/\/login/);
  await loginPage.login(user.username, user.password);

  await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
    timeout: 15_000,
  });
  await baseExpect(loginPage.logoutButton.first(), `expected a Log out button after signing in as ${role}`).toBeVisible({
    timeout: 15_000,
  });
}

/**
 * Extended test fixtures that provide pre-authenticated pages for each role.
 */
export const test = base.extend<{
  adminPage: Page;
  developerPage: Page;
  analystPage: Page;
  viewerPage: Page;
  loginAsRole: (role: UserRole) => Promise<void>;
}>({
  adminPage: async ({ page }, use) => {
    await loginAs(page, "admin");
    await use(page);
  },

  developerPage: async ({ page }, use) => {
    await loginAs(page, "developer");
    await use(page);
  },

  analystPage: async ({ page }, use) => {
    await loginAs(page, "analyst");
    await use(page);
  },

  viewerPage: async ({ page }, use) => {
    await loginAs(page, "viewer");
    await use(page);
  },

  loginAsRole: async ({ page }, use) => {
    const fn = async (role: UserRole) => {
      await loginAs(page, role);
    };
    await use(fn);
  },
});

export { expect } from "@playwright/test";
