import {
  test as base,
  expect as baseExpect,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import { LoginPage } from "../pages/login.page";
import { BASE_URL } from "../env";

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
    roleLabel: "Admin",
  },
  developer: {
    username: "dev@demo.com",
    password: "Demo1234!",
    role: "DEVELOPER",
    roleLabel: "Developer",
  },
  analyst: {
    username: "analyst@demo.com",
    password: "Demo1234!",
    role: "ANALYST",
    roleLabel: "Analyst",
  },
  viewer: {
    username: "viewer@demo.com",
    password: "Demo1234!",
    role: "VIEWER",
    roleLabel: "Viewer",
  },
} as const;

export type UserRole = keyof typeof TEST_USERS;

/**
 * Log in through the real `/login` page and wait until the app has navigated
 * away from it. Fails loudly if the credentials are rejected — there is no
 * "dev mode skips login" tolerance. The only thing tolerated is the platform's
 * own 10/min brute-force limit on `POST /auth/login`, which `submitResilient`
 * waits out (the whole suite logs in from one IP).
 */
export async function loginAs(page: Page, role: UserRole): Promise<void> {
  const loginPage = new LoginPage(page);
  const user = TEST_USERS[role];

  await loginPage.goto();
  await baseExpect(page, `expected the login form at /login for ${role}`).toHaveURL(/\/login/);
  await loginPage.submitResilient(user.username, user.password);

  if (await loginPage.errorMessage.isVisible()) {
    throw new Error(
      `login as ${role} (${user.username}) failed: ${await loginPage.errorMessage.innerText()}`,
    );
  }
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 15_000 });
  await baseExpect(
    loginPage.logoutButton,
    `expected a Log out button after signing in as ${role}`,
  ).toBeVisible({ timeout: 15_000 });
}

/** Resolve a logged-in browser context for a role, creating it on first use. */
export type SessionFactory = (role: UserRole) => Promise<BrowserContext>;

interface WorkerFixtures {
  sessions: SessionFactory;
}

interface TestFixtures {
  adminPage: Page;
  developerPage: Page;
  analystPage: Page;
  viewerPage: Page;
  loginAsRole: (role: UserRole) => Promise<void>;
}

/**
 * Extended fixtures providing a pre-authenticated page per role.
 *
 * The login happens once per role per worker in its own browser context; each
 * test gets a fresh page inside that context, so cookies/localStorage (and
 * therefore the session) are shared while page state is not.
 */
export const test = base.extend<TestFixtures, WorkerFixtures>({
  sessions: [
    async ({ browser }, use) => {
      const contexts = new Map<UserRole, BrowserContext>();

      const factory: SessionFactory = async (role) => {
        const existing = contexts.get(role);
        if (existing) return existing;

        // Contexts built here do not inherit the test-scoped `baseURL` option.
        const context = await browser.newContext({ baseURL: BASE_URL });
        const page = await context.newPage();
        try {
          await loginAs(page, role);
        } catch (error) {
          // Cache only a context that is actually signed in. Memoising a
          // failed one would make every later test in this worker run
          // anonymously and assert the wrong thing.
          await context.close();
          throw error;
        } finally {
          await page.close();
        }
        contexts.set(role, context);
        return context;
      };

      await use(factory);

      // `Array.from` (not a Map iterator): the app tsconfig targets ES5.
      for (const context of Array.from(contexts.values())) {
        await context.close();
      }
    },
    { scope: "worker" },
  ],

  adminPage: async ({ sessions }, use) => {
    const page = await (await sessions("admin")).newPage();
    await use(page);
    await page.close();
  },

  developerPage: async ({ sessions }, use) => {
    const page = await (await sessions("developer")).newPage();
    await use(page);
    await page.close();
  },

  analystPage: async ({ sessions }, use) => {
    const page = await (await sessions("analyst")).newPage();
    await use(page);
    await page.close();
  },

  viewerPage: async ({ sessions }, use) => {
    const page = await (await sessions("viewer")).newPage();
    await use(page);
    await page.close();
  },

  loginAsRole: async ({ page }, use) => {
    await use((role: UserRole) => loginAs(page, role));
  },
});

export { expect } from "@playwright/test";
