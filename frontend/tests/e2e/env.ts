/**
 * Where the browser journeys point, shared by `playwright.config.ts` and the
 * auth fixture (which builds its own browser contexts and therefore cannot
 * read the test-scoped `baseURL` option).
 *
 * Defaults match the local dev stack (`npm run dev` on 3100, API on 8000), so
 * `npx playwright test` needs no flags either locally or in CI.
 */

export const PORT = Number(process.env.PLAYWRIGHT_PORT ?? 3100);

/** Dashboard origin under test. */
export const BASE_URL = (process.env.PLAYWRIGHT_BASE_URL ?? `http://localhost:${PORT}`).replace(
  /\/+$/,
  '',
);

/** Backend origin, used by specs that assert on API traffic. */
export const API_URL = (process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8000').replace(
  /\/+$/,
  '',
);

/** True when the journeys run against a host we did not start ourselves. */
export const IS_EXTERNAL_BASE_URL = BASE_URL !== `http://localhost:${PORT}`;

/**
 * localStorage key holding the bearer token.
 * Source of truth: `TOKEN_STORAGE_KEY` in `src/services/api.ts`.
 */
export const TOKEN_STORAGE_KEY = "experimently.token";
