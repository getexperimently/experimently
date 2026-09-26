import { chromium, expect, test, type Page, type Request } from "@playwright/test";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { BASE_URL, TOKEN_STORAGE_KEY } from "./env";

/**
 * Sign in with SSO from the dashboard (C2b, spec-v3 §12).
 *
 * Runs against an API of its own -- `ENVIRONMENT=test` (so the fake provider
 * may be plain http), `LOG_LEVEL=INFO` -- and the fake OIDC provider
 * (`modules/backend/tests/integration/api/fake_oidc_provider.py`), both
 * started as steps of the `browser-e2e` job, with an SSO configuration for
 * the provider's user's domain created after the provider is up.
 *
 *   SSO_EMAIL               the work email the fake provider signs in
 *   SSO_FAKE_PROVIDER_URL   the fake provider (its /_mode switches behaviour)
 *   SSO_API_LOG             the API process's log file, read by the log gate
 *   SSO_API_BASE            where the dashboard's API is (default: same origin)
 *
 * Gates:
 *   - navigation/Referer: no navigated URL, request URL or Referer carries the
 *     hand-off code or the access token -- except the one navigation to
 *     /sso/complete#code=, and there only in the fragment;
 *   - the Chromium History database: it exists and holds that URL (positive
 *     control), holds no access token, and the code it holds is refused
 *     without its secret and after 61 s;
 *   - the API log at INFO holds neither the code nor the token;
 *   - exactly one exchange POST.
 */

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set; the browser-e2e job sets it (see pr-qa-gate.yml)`);
  return value;
}

const SSO_EMAIL = process.env.SSO_EMAIL ?? "e2e-user@sso-e2e.example.com";
const API_BASE = (process.env.SSO_API_BASE ?? BASE_URL).replace(/\/+$/, "");
const COMPLETE_PREFIX = `${BASE_URL}/sso/complete#code=`;

interface Recording {
  navigations: string[];
  requests: { url: string; method: string; referer?: string; body?: string | null }[];
}

function record(page: Page): Recording {
  const rec: Recording = { navigations: [], requests: [] };
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) rec.navigations.push(frame.url());
  });
  page.on("request", (req: Request) => {
    rec.requests.push({
      url: req.url(),
      method: req.method(),
      referer: req.headers()["referer"],
      body: req.postData(),
    });
  });
  return rec;
}

async function setProviderMode(mode: string): Promise<void> {
  const res = await fetch(`${required("SSO_FAKE_PROVIDER_URL")}/_mode?set=${encodeURIComponent(mode)}`);
  expect(res.ok).toBe(true);
}

/** From a protected page, through /login's SSO form and the provider, back again. */
async function signInWithSso(page: Page, from = "/feature-flags"): Promise<void> {
  await page.goto(from);
  await page.waitForURL(/\/login\?next=/, { timeout: 30_000 });
  await page.getByTestId("sso-open").click();
  await page.getByTestId("sso-email").fill(SSO_EMAIL);
  await page.getByTestId("sso-submit").click();
}

function exchangesOf(rec: Recording) {
  return rec.requests.filter((r) => r.method === "POST" && r.url.includes("/api/v1/auth/sso/exchange"));
}

function codeFrom(rec: Recording): string {
  const nav = rec.navigations.find((u) => u.startsWith(COMPLETE_PREFIX));
  if (!nav) throw new Error(`no navigation to ${COMPLETE_PREFIX}: ${JSON.stringify(rec.navigations)}`);
  return nav.slice(COMPLETE_PREFIX.length);
}

function iatOf(code: string): number {
  const payload = JSON.parse(Buffer.from(code.split(".")[1], "base64url").toString("utf8"));
  return Number(payload.iat);
}

async function exchange(code: string, secret: string): Promise<number> {
  const res = await fetch(`${API_BASE}/api/v1/auth/sso/exchange`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ code, secret }),
  });
  return res.status;
}

test.describe("SSO sign-in from the dashboard", () => {
  test.describe.configure({ mode: "serial" });

  test.afterEach(async () => {
    await setProviderMode("good");
  });

  test("@journey signs in with SSO and lands on the page asked for, with nothing leaked", async ({ page }) => {
    const rec = record(page);
    await signInWithSso(page, "/feature-flags");

    await page.waitForURL(/\/feature-flags$/, { timeout: 60_000 });
    await expect(page.getByTestId("app-shell")).toBeVisible();
    const token = await page.evaluate((key) => window.localStorage.getItem(key), TOKEN_STORAGE_KEY);
    expect(token).toBeTruthy();
    const code = codeFrom(rec);
    expect(code).toMatch(/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/);

    // Exactly one exchange, whatever React's StrictMode does in `next dev`.
    const exchanges = exchangesOf(rec);
    console.log(`SSO exchange POSTs: ${exchanges.length}`);
    expect(exchanges).toHaveLength(1);
    expect(JSON.parse(exchanges[0].body ?? "{}").code).toBe(code);

    // Navigations: the code only in the one /sso/complete#code= fragment,
    // the token never.
    // (Chromium reports that one navigation more than once: the load commits,
    // then the page's own same-document events; the URL is the same.)
    const handoffs = new Set(rec.navigations.filter((u) => u.includes(code)));
    expect(Array.from(handoffs)).toEqual([`${COMPLETE_PREFIX}${code}`]);
    for (const url of rec.navigations) expect(url).not.toContain(token!);

    // Requests and Referers: neither, anywhere. (The exchange carries the
    // code in its body, which is the design; its URL does not.)
    for (const req of rec.requests) {
      expect(req.url, req.url).not.toContain(code);
      expect(req.url, req.url).not.toContain(token!);
      if (req.referer) {
        expect(req.referer, `Referer of ${req.url}`).not.toContain(code);
        expect(req.referer, `Referer of ${req.url}`).not.toContain(token!);
      }
    }
    expect(new URL(page.url()).hash).toBe("");

    // The API log at INFO: it saw the exchange (positive control: the log is
    // being written, at INFO), and holds neither value.
    await page.waitForTimeout(500);
    const log = readFileSync(required("SSO_API_LOG"), "utf8");
    expect(log).toContain("POST /api/v1/auth/sso/exchange");
    expect(log.includes(code), "the API log holds the hand-off code").toBe(false);
    expect(log.includes(token!), "the API log holds the access token").toBe(false);
  });

  test("@errors a provider error lands on /login with its copy and a clean URL", async ({ page }) => {
    await setProviderMode("access-denied");
    await signInWithSso(page);
    await expect(page.getByTestId("login-error")).toHaveText(
      /Okta did not complete the sign-in \(access_denied\)\. If you expected access, contact your administrator\./,
      { timeout: 30_000 },
    );
    await expect(page).toHaveURL(`${BASE_URL}/login`);
    await expect(page.getByTestId("sso-form")).toBeVisible();
    await expect(page.getByTestId("sso-retry")).toBeVisible();
  });

  test("@errors an account outside the domain lands on /login as sso_domain", async ({ page }) => {
    await setProviderMode("other-domain");
    await signInWithSso(page);
    await expect(page.getByTestId("login-error")).toHaveText(
      /Okta signed you in with an account outside this organisation's domain\./,
      { timeout: 30_000 },
    );
    await expect(page).toHaveURL(`${BASE_URL}/login`);
  });

  test("@history the History database keeps a dead code and no token", async () => {
    test.setTimeout(180_000);
    const dir = mkdtempSync(join(tmpdir(), "sso-history-"));
    try {
      // `channel: 'chromium'` is the full browser in new headless mode; the
      // default headless shell writes no History file at all, which is why
      // the positive control below exists.
      const context = await chromium.launchPersistentContext(dir, {
        channel: "chromium",
        baseURL: BASE_URL,
      });
      const page = context.pages()[0] ?? (await context.newPage());
      const rec = record(page);
      await signInWithSso(page);
      await page.waitForURL(/\/feature-flags$/, { timeout: 60_000 });
      const token = await page.evaluate((key) => window.localStorage.getItem(key), TOKEN_STORAGE_KEY);
      expect(token).toBeTruthy();
      const [sent] = exchangesOf(rec);
      const secret = JSON.parse(sent.body ?? "{}").secret as string;
      expect(secret).toMatch(/^[A-Za-z0-9_-]{43}$/);
      // History is flushed when the browser closes; read it after.
      await context.close();

      const profile = join(dir, "Default");
      const files = existsSync(profile) ? readdirSync(profile).filter((f) => f.startsWith("History")) : [];
      expect(files, `History files in ${profile}`).toContain("History");
      const bytes = Buffer.concat(files.map((f) => readFileSync(join(profile, f))));
      const text = bytes.toString("latin1");

      // Positive control: the browser did record the hand-off URL.
      const stored = /\/sso\/complete#code=([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)/.exec(text);
      expect(stored, "History holds /sso/complete#code=").not.toBeNull();
      expect(text.includes(token!), "History holds the access token").toBe(false);

      const code = stored![1];
      // Without its secret: refused.
      const otherSecret = Buffer.alloc(32, 7).toString("base64url");
      expect(await exchange(code, otherSecret)).toBe(400);
      // With its secret, 61 s after it was issued: refused.
      const wait = iatOf(code) * 1000 + 61_000 - Date.now();
      if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
      expect(await exchange(code, secret)).toBe(400);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
