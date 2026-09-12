import { test, expect } from "./fixtures/auth.fixture";

/**
 * Journey 5 — admin panel.
 *
 * Admin-only surface: the pages must load for an ADMIN, be refused for a
 * VIEWER, mint an API key that is shown exactly once and then listed, and the
 * safety dashboard must fan out its per-flag checks under a bound (it runs one
 * `/safety/feature-flags/{id}/check` per flag, and the non-SDK rate limit is
 * 300 req/min per IP).
 */

/** Mirrors SAFETY_CHECK_CONCURRENCY / SAFETY_FLAG_LIMIT in src/pages/admin/safety.tsx. */
const SAFETY_CHECK_CONCURRENCY = 5;
const SAFETY_FLAG_LIMIT = 100;

/** Admin pages: each must render for an admin and be refused for a viewer. */
const ADMIN_PAGES = [
  { path: "/admin", testId: "admin-dashboard" },
  { path: "/admin/users", testId: "user-table" },
  { path: "/admin/audit", testId: "audit-log-table" },
  { path: "/admin/safety", testId: "safety-dashboard" },
  { path: "/admin/api-keys", testId: "api-keys-page" },
] as const;

/** Admin pages that must render their content, not just their chrome. */
const ADMIN_LOADS = ADMIN_PAGES;

test.describe("Journey: admin panel", () => {
  test.describe.configure({ mode: "serial" });

  test("every admin page loads for an admin", async ({ adminPage }) => {
    for (const { path, testId } of ADMIN_LOADS) {
      await adminPage.goto(path);
      await expect(adminPage.getByTestId("admin-layout"), `${path} chrome`).toBeVisible({
        timeout: 15_000,
      });
      await expect(adminPage.getByTestId("admin-sidebar")).toBeVisible();
      await expect(adminPage.getByTestId(testId), `${path} content`).toBeVisible({
        timeout: 20_000,
      });
      await expect(adminPage.getByTestId("require-auth-forbidden")).toHaveCount(0);
    }
  });

  test("the dashboard renders its stat tiles from the API", async ({ adminPage }) => {
    await adminPage.goto("/admin");
    await expect(adminPage.getByTestId("admin-dashboard")).toBeVisible({ timeout: 15_000 });
    // GET /api/v1/admin/stats must succeed: five tiles, no error card.
    await expect(adminPage.getByTestId("stat-tile")).toHaveCount(5, { timeout: 20_000 });
    await expect(adminPage.getByTestId("error-state")).toHaveCount(0);
    await expect(adminPage.getByTestId("loading-skeleton")).toHaveCount(0);
    await expect(adminPage.getByTestId("stat-tile").first()).toContainText("Experiments");
  });

  test("a viewer is refused every admin page", async ({ viewerPage }) => {
    for (const { path, testId } of ADMIN_PAGES) {
      await viewerPage.goto(path);
      await expect(
        viewerPage.getByTestId("require-auth-forbidden"),
        `${path} must be refused`,
      ).toBeVisible({ timeout: 15_000 });
      await expect(viewerPage.getByTestId(testId)).toHaveCount(0);
      await expect(viewerPage.getByTestId("admin-sidebar")).toHaveCount(0);
    }
  });

  test("the API-keys page creates a key, shows it once and lists it", async ({ adminPage }) => {
    const keyName = `e2e-key-${Date.now()}`;
    await adminPage.goto("/admin/api-keys");

    const table = adminPage.getByTestId("api-key-table");
    await expect(table).toBeVisible({ timeout: 15_000 });
    await expect(adminPage.getByTestId("api-key-error-state")).toHaveCount(0);

    await adminPage.getByTestId("create-api-key-button").click();
    const modal = adminPage.getByTestId("create-api-key-modal");
    await expect(modal).toBeVisible();
    await adminPage.getByTestId("api-key-name-input").fill(keyName);
    await adminPage.getByTestId("api-key-scope-input").selectOption("write");
    await adminPage.getByTestId("create-api-key-submit").click();

    // Shown once, at creation time only, in the page banner: closing the modal
    // unmounts its own reveal screen, so the banner has to carry the whole key
    // — a truncated preview cannot be used to call the API.
    const banner = adminPage.getByTestId("new-key-banner");
    await expect(banner).toBeVisible({ timeout: 15_000 });
    const revealed = (await adminPage.getByTestId("new-key-value").innerText()).trim();
    expect(revealed).toMatch(/^eptk_[0-9a-f]{32}$/);
    await expect(adminPage.getByTestId("copy-new-key")).toBeVisible();
    await expect(adminPage.getByTestId("modal-error")).toHaveCount(0);
    await expect(modal).toHaveCount(0);

    // …and it is in the list, active, with the scope we asked for.
    const row = table.locator("tr", { hasText: keyName });
    await expect(row).toHaveCount(1, { timeout: 15_000 });
    await expect(row).toContainText("write");
    const rowTestId = await row.getAttribute("data-testid");
    expect(rowTestId).toMatch(/^api-key-row-/);
    const keyId = rowTestId!.replace("api-key-row-", "");
    await expect(adminPage.getByTestId(`status-badge-${keyId}`)).toHaveText("active");

    // The plaintext is never served again: reloading shows the row, not the key.
    await adminPage.reload();
    await expect(adminPage.getByTestId("new-key-banner")).toHaveCount(0);
    await expect(adminPage.getByTestId(`api-key-row-${keyId}`)).toBeVisible({ timeout: 15_000 });

    // Clean up so repeated local runs do not pile up keys.
    await adminPage.getByTestId(`delete-button-${keyId}`).click();
    await expect(adminPage.getByTestId("delete-confirm")).toBeVisible();
    await adminPage.getByTestId("confirm-delete").click();
    await expect(adminPage.getByTestId("delete-error")).toHaveCount(0);
    await expect(adminPage.getByTestId(`api-key-row-${keyId}`)).toHaveCount(0, { timeout: 15_000 });
  });

  test("the safety page renders without an unbounded fan-out of checks", async ({ adminPage }) => {
    const checkUrl = /\/api\/v1\/safety\/feature-flags\/[^/]+\/check/;
    let started = 0;
    let inFlight = 0;
    let maxInFlight = 0;
    let rateLimited = 0;

    adminPage.on("request", (request) => {
      if (!checkUrl.test(request.url())) return;
      started += 1;
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
    });
    const settle = (): void => {
      inFlight = Math.max(0, inFlight - 1);
    };
    adminPage.on("requestfinished", (request) => {
      if (checkUrl.test(request.url())) settle();
    });
    adminPage.on("requestfailed", (request) => {
      if (checkUrl.test(request.url())) settle();
    });
    adminPage.on("response", (response) => {
      if (checkUrl.test(response.url()) && response.status() === 429) rateLimited += 1;
    });

    await adminPage.goto("/admin/safety");
    await expect(adminPage.getByTestId("safety-dashboard")).toBeVisible({ timeout: 15_000 });
    await expect(adminPage.getByTestId("safety-settings-form")).toBeVisible({ timeout: 20_000 });
    await expect(adminPage.getByTestId("flag-status-loading")).toHaveCount(0, { timeout: 30_000 });
    await expect(adminPage.getByTestId("flag-status-error")).toHaveCount(0);
    await expect(adminPage.getByTestId("rollback-history-table")).toBeVisible();

    // One card per flag whose check came back; the seed ships at least two flags.
    const cards = adminPage.getByTestId("safety-status-card");
    expect(await cards.count()).toBeGreaterThan(0);
    await expect(cards.first().getByTestId("status-badge")).not.toBeEmpty();

    expect(started, "the page must actually run the safety checks").toBeGreaterThan(0);
    expect(started, "one check per flag, capped by SAFETY_FLAG_LIMIT").toBeLessThanOrEqual(
      SAFETY_FLAG_LIMIT,
    );
    expect(maxInFlight, "checks must be throttled, not fired all at once").toBeLessThanOrEqual(
      SAFETY_CHECK_CONCURRENCY,
    );
    expect(rateLimited, "safety checks must not trip the rate limiter").toBe(0);

    // No polling loop: the count is stable once the grid has rendered.
    const afterRender = started;
    await adminPage.waitForTimeout(3_000);
    expect(started, "the page must not keep re-checking on a timer").toBe(afterRender);
  });
});
