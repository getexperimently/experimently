import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { test, expect } from "./fixtures/auth.fixture";

/**
 * Journey 6 — segments (#440).
 *
 * A DEVELOPER (not a superuser) creates an id-list segment, uploads a CSV
 * through the page and reads the member count the server computed, checks
 * a member and a non-member, finds the segment in a flag rule's picker, and
 * archives it. ANALYST and VIEWER see the same pages with no control that
 * changes anything.
 *
 * axe runs here, in the fail-hard project, not in the nightly accessibility
 * spec (which skips itself when axe cannot be imported): the import is
 * static, and any serious or critical WCAG 2.0 A/AA violation fails the PR.
 *
 * The seed has no segments, so the journey makes its own; it leaves one
 * archived segment behind, which nothing else reads.
 */

async function expectNoSeriousViolations(page: Page, where: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = results.violations
    .filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${v.id} (${v.impact}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(serious, `axe on ${where}`).toEqual([]);
}

test.describe("Journey: segments", () => {
  test.describe.configure({ mode: "serial" });

  const stamp = Date.now();
  const name = `E2E pilot ${stamp}`;
  let segmentUrl = "";

  test("a developer creates an id-list segment and uploads its IDs", async ({ developerPage: page }) => {
    await page.goto("/segments");
    await expect(page.getByRole("heading", { level: 1, name: "Segments" })).toBeVisible();
    await expect(page.getByTestId("segments-loading")).toHaveCount(0, { timeout: 15_000 });
    await expect(page.getByTestId("segments-error")).toHaveCount(0);
    await expectNoSeriousViolations(page, "/segments");

    await page.getByTestId("new-segment-btn").click();
    await expect(page).toHaveURL(/\/segments\/new$/);
    await expectNoSeriousViolations(page, "/segments/new (rules)");
    await page.getByTestId("segment-kind-id-list").check();
    await expectNoSeriousViolations(page, "/segments/new (ID list)");
    await page.getByLabel("Name", { exact: true }).fill(name);
    await page.getByTestId("segment-create").click();

    await expect(page).toHaveURL(/\/segments\/[0-9a-f-]{36}$/, { timeout: 15_000 });
    segmentUrl = new URL(page.url()).pathname;
    await expect(page.getByTestId("segment-name-heading")).toHaveText(name);
    await expect(page.getByTestId("segment-member-count")).toHaveText("0");
    await expectNoSeriousViolations(page, "the segment page");

    await page.getByTestId("upload-file-add").setInputFiles({
      name: "customers.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("user_id\ne2e-member-a\ne2e-member-b\ne2e-member-a\n"),
    });
    await expect(page.getByTestId("upload-summary")).toContainText("2 IDs found in customers.csv.");
    await expect(page.getByTestId("upload-summary")).toContainText("1 duplicate removed.");
    await expectNoSeriousViolations(page, "the segment page with a file summary");
    await page.getByTestId("upload-start").click();
    await expect(page.getByTestId("upload-done")).toContainText(
      "2 IDs uploaded. 2 were added and 0 were already members. The segment now has 2 members.",
      { timeout: 15_000 },
    );

    // The count the server holds, read back on a fresh load.
    await page.reload();
    await expect(page.getByTestId("segment-member-count")).toHaveText("2", { timeout: 15_000 });

    await page.getByLabel("User ID", { exact: true }).fill("e2e-member-a");
    await page.getByTestId("segment-check-submit").click();
    await expect(page.getByTestId("segment-check-answer")).toHaveText("e2e-member-a is a member.");
    await page.getByLabel("User ID", { exact: true }).fill("e2e-member-z");
    await page.getByTestId("segment-check-submit").click();
    await expect(page.getByTestId("segment-check-answer")).toHaveText("e2e-member-z is not a member.");
  });

  test("the segment is offered by the picker in a flag's rules", async ({ developerPage: page }) => {
    await page.goto("/feature-flags/new");
    await page.getByTestId("add-group").first().click();
    await page.getByLabel("Group 1, condition 1 attribute").fill("segment");
    await page.getByLabel("Group 1, condition 1 operator").selectOption("in_segment");
    const picker = page.getByRole("combobox", { name: "Group 1, condition 1 segment" });
    await expect(picker).toBeEnabled({ timeout: 15_000 });
    await expect(picker.locator("option", { hasText: `${name} · ID list` })).toHaveCount(1);
    await picker.selectOption({ label: `${name} · ID list` });
    await expectNoSeriousViolations(page, "a new flag with the segment picker open");
  });

  for (const role of ["analyst", "viewer"] as const) {
    test(`${role} reads segments and changes nothing`, async ({ sessions }) => {
      const page = await (await sessions(role)).newPage();
      try {
        await page.goto("/segments");
        await expect(page.getByTestId("segments-role-note")).toContainText("ADMIN and DEVELOPER");
        await expect(page.getByTestId("new-segment-btn")).toHaveCount(0);
        await page.goto(segmentUrl);
        await expect(page.getByTestId("segment-name-heading")).toHaveText(name, { timeout: 15_000 });
        await expect(page.getByTestId("segment-member-count")).toHaveText("2");
        for (const id of ["upload-add", "upload-remove", "segment-mode-add", "segment-archive"]) {
          await expect(page.getByTestId(id)).toHaveCount(0);
        }
        await expect(page.getByTestId("segment-role-note")).toBeVisible();
        await expectNoSeriousViolations(page, `the segment page as ${role}`);
      } finally {
        await page.close();
      }
    });
  }

  test("a developer archives the segment after confirming in the page", async ({ developerPage: page }) => {
    await page.goto(segmentUrl);
    await expect(page.getByTestId("segment-name-heading")).toHaveText(name, { timeout: 15_000 });
    await page.getByTestId("segment-archive").click();
    await expect(page.getByTestId("segment-archive-confirm")).toContainText(`Archive ${name}?`);
    await expectNoSeriousViolations(page, "the archive confirmation");
    await page.getByTestId("segment-archive-yes").click();
    await expect(page.getByTestId("segment-detail-status")).toHaveText("Archived", { timeout: 15_000 });
    await expect(page.getByTestId("segment-archive")).toHaveCount(0);
  });
});
