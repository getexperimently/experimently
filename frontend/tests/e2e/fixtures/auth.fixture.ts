import { test as base, type Page } from "@playwright/test";
import { LoginPage } from "../pages/login.page";

/**
 * Test credentials for different roles.
 * These match the dev-mode bypass credentials in the backend.
 */
export const TEST_USERS = {
  admin: {
    username: "admin@experimently.io",
    password: "admin123",
    role: "ADMIN",
  },
  developer: {
    username: "developer@experimently.io",
    password: "dev123",
    role: "DEVELOPER",
  },
  analyst: {
    username: "analyst@experimently.io",
    password: "analyst123",
    role: "ANALYST",
  },
  viewer: {
    username: "viewer@experimently.io",
    password: "viewer123",
    role: "VIEWER",
  },
} as const;

export type UserRole = keyof typeof TEST_USERS;

/**
 * Attempt login and return whether it succeeded.
 * Gracefully handles apps that skip login in dev mode.
 */
async function loginAs(page: Page, role: UserRole): Promise<void> {
  const loginPage = new LoginPage(page);
  await loginPage.goto();

  // If already logged in or no login page, skip
  const isLoginPage = page.url().includes("/login");
  if (!isLoginPage) return;

  const user = TEST_USERS[role];
  await loginPage.login(user.username, user.password);
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
