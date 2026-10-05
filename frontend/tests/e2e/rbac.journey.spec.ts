import { test, expect, TEST_USERS, type UserRole } from "./fixtures/auth.fixture";
import { ExperimentsPage } from "./pages/experiments.page";

/**
 * Journey 4 — role-based access control.
 *
 * The four seeded demo accounts (`seed_demo_data.py`) must see the navigation
 * their role allows and be refused what it does not. The client-side gates
 * (`NAV_ITEMS` in AppShell, `<RequireAuth>` / `withAdminGuard`) are
 * convenience only — the API is the enforcement, and they have to ask the same
 * question it does: the admin area is gated on `is_superuser`, because every
 * endpoint under /api/v1/admin is `Depends(deps.get_current_superuser)` (#84). The
 * create page asks the API's own create question too: an ANALYST or VIEWER
 * who opens it sees a notice instead of a form that could only earn a 403.
 */

/** Nav items the AppShell renders for a role (`NAV_ITEMS` in AppShell.tsx). */
const NAV_FOR_ROLE: Record<UserRole, { visible: string[]; hidden: string[] }> = {
  admin: {
    visible: ["nav-experiments", "nav-feature-flags", "nav-admin", "nav-docs"],
    hidden: [],
  },
  developer: {
    // nav-admin is NOT here: the admin area is superusers only, and of the
    // four seeded accounts only the admin is one. The item used to be shown
    // to DEVELOPER, who then got a 403 from every /api/v1/admin request (#84).
    visible: ["nav-experiments", "nav-feature-flags", "nav-docs"],
    hidden: ["nav-admin"],
  },
  analyst: {
    visible: ["nav-experiments", "nav-feature-flags", "nav-docs"],
    hidden: ["nav-admin"],
  },
  viewer: {
    visible: ["nav-experiments", "nav-feature-flags", "nav-docs"],
    hidden: ["nav-admin"],
  },
};

test.describe("Journey: RBAC", () => {
  for (const role of ["admin", "developer", "analyst", "viewer"] as const) {
    test(`${role} sees the navigation their role allows`, async ({ sessions }) => {
      const page = await (await sessions(role)).newPage();
      try {
        await page.goto("/experiments");
        await expect(page.getByTestId("app-shell")).toBeVisible();
        await expect(page.getByTestId("user-menu-role")).toHaveText(TEST_USERS[role].roleLabel);

        for (const testId of NAV_FOR_ROLE[role].visible) {
          await expect(page.getByTestId(testId), `${role} should see ${testId}`).toBeVisible();
        }
        for (const testId of NAV_FOR_ROLE[role].hidden) {
          await expect(page.getByTestId(testId), `${role} must not see ${testId}`).toHaveCount(0);
        }

        // The experiments page renders for every role, without an error banner.
        await expect(page.getByTestId("status-filter")).toBeVisible();
        // "+ New Experiment" is offered only to the roles the API lets create:
        // an analyst or viewer who clicked it would get a 403 from POST
        // /api/v1/experiments/.
        if (role === "admin" || role === "developer") {
          await expect(page.getByTestId("new-experiment-btn")).toBeVisible();
        } else {
          await expect(page.getByTestId("new-experiment-btn")).toHaveCount(0);
        }
        await expect(page.getByTestId("experiments-error")).toHaveCount(0);
        await expect(page.getByTestId("experiments-loading")).toHaveCount(0, { timeout: 20_000 });

        // Every role sees the platform, not an empty page.
        //
        // This used to assert the populated table for the admin alone, with a
        // comment explaining that `GET /experiments` gated its "see
        // everything" branch on `is_superuser` rather than on the role, so an
        // ANALYST or VIEWER got an empty list "for a product reason this
        // journey cannot fix". #83 fixed it: the list honours the role table,
        // and all four seeded roles carry LIST. So the assertion that was
        // documenting the gap now proves it closed, for every role.
        await expect(page.getByTestId("experiments-table")).toBeVisible({ timeout: 15_000 });
        expect(await page.getByTestId("experiment-row").count()).toBeGreaterThan(0);
      } finally {
        await page.close();
      }
    });
  }

  test("the admin reaches the admin area", async ({ adminPage }) => {
    await adminPage.goto("/admin");
    await expect(adminPage.getByTestId("admin-layout")).toBeVisible({ timeout: 15_000 });
    await expect(adminPage.getByTestId("require-auth-forbidden")).toHaveCount(0);
  });

  // developer joins analyst and viewer: every endpoint under /api/v1/admin is
  // `Depends(deps.get_current_superuser)`, and the seeded developer is not one.
  // Letting them in was #84 -- the page rendered and then every request on it
  // returned 403.
  // developer joins analyst and viewer for the ADMIN AREA only: every endpoint
  // under /api/v1/admin is `Depends(deps.get_current_superuser)`, and the
  // seeded developer is not one. Letting them in was #84.
  //
  // Two loops, not one. These tests had shared a loop, and widening it to
  // include developer widened BOTH -- which made "developer cannot create an
  // experiment" run for a role that certainly can, and fail. The audiences
  // differ, so the loops do.
  for (const role of ["developer", "analyst", "viewer"] as const) {
    test(`${role} is refused the admin area`, async ({ sessions }) => {
      const page = await (await sessions(role)).newPage();
      try {
        await page.goto("/admin");
        const forbidden = page.getByTestId("require-auth-forbidden");
        await expect(forbidden).toBeVisible({ timeout: 15_000 });
        await expect(forbidden).toContainText(TEST_USERS[role].role);
        // Nothing of the admin surface leaks through the 403 view.
        await expect(page.getByTestId("admin-dashboard")).toHaveCount(0);
        await expect(page.getByTestId("admin-sidebar")).toHaveCount(0);
      } finally {
        await page.close();
      }
    });

  }

  // Create is a different question: a DEVELOPER may create experiments -- the
  // API allows it and the nav test above asserts they get the button. Only
  // ANALYST and VIEWER are refused.
  // /experiments/new asks the same question as the API (superuser, ADMIN or
  // DEVELOPER): anyone else gets a notice in place of either view, and no
  // create request can be sent from it.
  for (const role of ["analyst", "viewer"] as const) {
    test(`${role} cannot create an experiment and the UI says so`, async ({ sessions }) => {
      const page = await (await sessions(role)).newPage();
      const experiments = new ExperimentsPage(page);
      let posts = 0;
      page.on("request", (request) => {
        const { pathname } = new URL(request.url());
        if (request.method() === "POST" && /\/api\/v1\/experiments\/?$/.test(pathname)) posts += 1;
      });
      try {
        for (const open of [() => experiments.gotoGuided(), () => experiments.gotoNew()]) {
          await open();
          await expect(experiments.notAllowed).toBeVisible({ timeout: 15_000 });
          await expect(experiments.notAllowed).toContainText(
            "Your role can view experiments but not create them.",
          );
          await expect(experiments.guided).toHaveCount(0);
          await expect(experiments.form).toHaveCount(0);
          await expect(experiments.nameInput).toHaveCount(0);
        }
        expect(posts).toBe(0);
      } finally {
        await page.close();
      }
    });
  }

  // Opening an experiment is READ, which the role table grants all four roles.
  // The detail route used to answer 403 to every non-superuser, the creator
  // included, and no journey noticed: the lifecycle journey opens detail pages
  // only as the seeded admin, who is a superuser and bypasses every check, and
  // this file stopped at the list. The seeded experiments belong to the admin,
  // so each of these opens one it does not own.
  for (const role of ["developer", "analyst", "viewer"] as const) {
    test(`${role} opens an experiment from the list`, async ({ sessions }) => {
      const page = await (await sessions(role)).newPage();
      const experiments = new ExperimentsPage(page);
      try {
        await experiments.goto();
        await expect(experiments.experimentList).toBeVisible({ timeout: 15_000 });
        await experiments.experimentRows.first().getByTestId("experiment-link").click();
        await expect(experiments.detail).toBeVisible({ timeout: 15_000 });
        await expect(page.getByTestId("experiment-error")).toHaveCount(0);
      } finally {
        await page.close();
      }
    });
  }

  // Starting, pausing, completing and archiving need a role with EXPERIMENT
  // UPDATE (ADMIN or DEVELOPER) or a superuser, whoever owns the experiment.
  // An analyst or viewer opening a running experiment is offered none of
  // them, is told why, and reads its results -- and no request they make on
  // the way is refused by the experiments or results API.
  for (const role of ["analyst", "viewer"] as const) {
    test(`${role} sees no lifecycle action on a running experiment and reads its results`, async ({
      sessions,
    }) => {
      const page = await (await sessions(role)).newPage();
      const experiments = new ExperimentsPage(page);
      const refused: string[] = [];
      page.on("response", (response) => {
        const { pathname } = new URL(response.url());
        if (
          /^\/api\/v1\/(experiments|results)\//.test(pathname) &&
          (response.status() === 401 || response.status() === 403)
        ) {
          refused.push(`${response.status()} ${response.request().method()} ${pathname}`);
        }
      });
      try {
        await experiments.goto();
        await expect(experiments.experimentList).toBeVisible({ timeout: 15_000 });
        // Seeded ACTIVE by seed_demo_data.py and owned by the admin; no
        // journey changes its status.
        await experiments.clickExperiment("Checkout Button Color");
        await experiments.expectStatus("active");

        for (const button of [
          experiments.startButton,
          experiments.pauseButton,
          experiments.completeButton,
          experiments.archiveButton,
        ]) {
          await expect(button).toHaveCount(0);
        }
        await expect(experiments.actions.locator("button")).toHaveCount(0);
        const note = page.getByTestId("experiment-role-note");
        await expect(note).toBeVisible();
        await expect(note).toContainText("requires the ADMIN or DEVELOPER role");
        await expect(note).toContainText(`you are ${TEST_USERS[role].role}.`);

        await experiments.viewResults();
        await expect(page.getByTestId("results-dashboard")).toBeVisible({ timeout: 20_000 });
        await page.waitForLoadState("networkidle");
        expect(refused, "no experiments/results request is refused").toEqual([]);
      } finally {
        await page.close();
      }
    });
  }

  // Reading a bandit's current weights is allowed to every signed-in role
  // (`GET /api/v1/bandit/{id}`), and the panel changes nothing, so all four
  // roles get the same read-only panel. What it shows is compared with the
  // server's own answer to the page's request, not with a value typed here:
  // before the first update (`last_updated` null) the panel says so instead
  // of showing the even split the server fills in.
  for (const role of ["admin", "developer", "analyst", "viewer"] as const) {
    test(`${role} reads a bandit's current traffic weights and is offered no change`, async ({ sessions }) => {
      const page = await (await sessions(role)).newPage();
      const experiments = new ExperimentsPage(page);
      const writes: string[] = [];
      page.on("request", (request) => {
        const { pathname } = new URL(request.url());
        if (pathname.startsWith("/api/v1/bandit/") && request.method() !== "GET") {
          writes.push(`${request.method()} ${pathname}`);
        }
      });
      try {
        await experiments.goto();
        await expect(experiments.experimentList).toBeVisible({ timeout: 15_000 });
        const answer = page.waitForResponse(
          (response) =>
            new URL(response.url()).pathname.startsWith("/api/v1/bandit/") &&
            response.request().method() === "GET",
          { timeout: 20_000 },
        );
        // Seeded ACTIVE with Thompson sampling by seed_demo_data.py.
        await experiments.clickExperiment("Recommendation Algorithm MAB");
        const response = await answer;
        expect(response.status(), `${role} may read the weights`).toBe(200);
        const body = (await response.json()) as {
          last_updated: string | null;
          current_weights: { variant_id: string; current_weight: number }[];
        };

        const panel = page.getByTestId("bandit-weights");
        await expect(panel).toBeVisible();
        await expect(panel.getByTestId("bandit-weights-loading")).toHaveCount(0, { timeout: 15_000 });
        await expect(panel.getByTestId("bandit-weights-error")).toHaveCount(0);
        await expect(panel.getByRole("button")).toHaveText(["Refresh"]);

        if (body.last_updated === null) {
          await expect(panel.getByTestId("bandit-weights-empty")).toBeVisible();
          await expect(panel.getByTestId("bandit-weights-table")).toHaveCount(0);
        } else {
          expect(body.current_weights.length).toBeGreaterThan(0);
          await expect(panel.getByTestId("bandit-weight-row")).toHaveCount(body.current_weights.length);
          for (const weight of body.current_weights) {
            const row = panel.locator(`[data-testid="bandit-weight-row"][data-variant-id="${weight.variant_id}"]`);
            await expect(row.getByTestId("bandit-weight-share")).toHaveText(
              `${(weight.current_weight * 100).toFixed(1)}%`,
            );
          }
        }
        expect(writes, "the panel only reads").toEqual([]);
      } finally {
        await page.close();
      }
    });
  }

  // The reported path end to end: guided setup redirects to the new
  // experiment's page, and its creator -- an ordinary DEVELOPER -- must be able
  // to open it. `createExperiment` resolves only once the detail has rendered.
  test("developer creates an experiment and lands on its page", async ({ sessions }) => {
    const page = await (await sessions("developer")).newPage();
    const experiments = new ExperimentsPage(page);
    const stamp = Date.now();
    try {
      const id = await experiments.createExperiment(`E2E Developer owns ${stamp}`, `e2e_dev_owns_${stamp}`);
      expect(id).toMatch(/^[0-9a-f-]{36}$/);
      await expect(experiments.detailName).toContainText(`E2E Developer owns ${stamp}`);
      await expect(page.getByTestId("experiment-error")).toHaveCount(0);

      // And again from a cold load, not only straight after the redirect.
      await page.reload();
      await expect(experiments.detail).toBeVisible({ timeout: 15_000 });
    } finally {
      await page.close();
    }
  });

  test("developer gets guided setup", async ({ sessions }) => {
    const page = await (await sessions("developer")).newPage();
    const experiments = new ExperimentsPage(page);
    try {
      await experiments.gotoGuided();
      await expect(experiments.guided).toBeVisible({ timeout: 15_000 });
      await expect(experiments.notAllowed).toHaveCount(0);
    } finally {
      await page.close();
    }
  });
});
