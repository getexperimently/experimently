/**
 * Installed modules — `GET /api/v1/modules`.
 *
 * The endpoint is unauthenticated on purpose (it drives chrome that renders
 * before anyone has logged in) and deliberately thin: it answers exactly three
 * keys — which profile the instance runs, which modules are installed, and the
 * version. See `backend/app/api/v1/endpoints/modules.py`.
 *
 * Everything here is pure except `ModulesService.get()`; the caching, React
 * wiring and `useModule` hook live in `@/contexts/ModulesContext`.
 */
import { apiFetch } from '@/services/api';

export const MODULES_PATH = '/api/v1/modules';

/** Where the modules guide lives (`docs/getting-started/modules.md`). */
export const MODULES_DOC_PATH = '/docs/modules';

/**
 * `core` is the product without the optional modules; `full` is the product
 * with them. There is nothing else: no tier, no key, no state to expire.
 */
export type Profile = 'core' | 'full';

/** The two members of {@link Profile}, in the backend's own order. */
export const PROFILES: readonly Profile[] = ['core', 'full'] as const;

/** Response body of `GET /api/v1/modules`. */
export interface ModulesInfo {
  profile: Profile;
  /** Names of the installed modules — a subset of {@link MODULES}. Empty in `core`. */
  modules: string[];
  version: string;
}

/**
 * What the dashboard is when it has no other information: the core profile,
 * no modules. Every failure path resolves to this value.
 */
export const CORE_PROFILE: ModulesInfo = Object.freeze({
  profile: 'core',
  modules: [],
  version: '',
}) as ModulesInfo;

/**
 * Module names — one per `modules-manifest.txt` group. Only the ones the
 * dashboard gates today are referenced in components; the rest are here so
 * the names live in one place.
 *
 * **This block is parsed, not just read.** It is the canonical spelling of the
 * contract: `backend/app/core/hooks.py::KNOWN_MODULES` must list exactly
 * these strings in exactly this order, `hooks.register_modules()` refuses a
 * name outside the list, and `backend/tests/unit/core/test_module_names.py`
 * extracts this literal and compares the two element for element. Keep it a
 * plain object literal of `KEY: 'value',` lines, and change a spelling on
 * both sides at once.
 */
export const MODULES = {
  WORKSPACES: 'workspaces',
  HIPAA: 'hipaa',
  COMPLIANCE: 'compliance',
  SSO: 'sso',
  RBAC: 'rbac',
  WAREHOUSE: 'warehouse',
  INTEGRATIONS: 'integrations',
  COUNTERS: 'counters',
  ETL: 'etl',
  SPLIT_URL: 'split_url',
} as const;

export type ModuleName = (typeof MODULES)[keyof typeof MODULES];

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

export function isProfile(value: unknown): value is Profile {
  return typeof value === 'string' && (PROFILES as readonly string[]).indexOf(value) !== -1;
}

/**
 * Coerce an untrusted body into a {@link ModulesInfo}.
 *
 * A profile the dashboard does not know about is read as `core`, and a
 * `modules` that is not an array as none: an unrecognised answer must never
 * read as more installed than it is. Non-string entries are dropped.
 */
export function normaliseModules(raw: unknown): ModulesInfo {
  if (!raw || typeof raw !== 'object') return CORE_PROFILE;
  const body = raw as Record<string, unknown>;

  const profile: Profile = isProfile(body.profile) ? body.profile : 'core';
  const modules = Array.isArray(body.modules)
    ? body.modules.filter((m): m is string => typeof m === 'string')
    : [];

  return {
    profile,
    modules,
    version: typeof body.version === 'string' ? body.version : '',
  };
}

// ---------------------------------------------------------------------------
// Module checks
// ---------------------------------------------------------------------------

/** True when the module is installed on this instance. */
export function moduleInstalled(info: ModulesInfo, name: string): boolean {
  return info.modules.indexOf(name) !== -1;
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

/**
 * How long the modules probe may hang before it is treated as a failure.
 *
 * A probe that *fails* resolves to the core profile and is retried; a probe
 * that *hangs* -- a stuck upstream behind nginx's hour-long proxy_read_timeout
 * -- used to pin the shared in-flight promise for the whole tab session, with
 * no error to retry from. The timeout turns a hang into a failure.
 */
export const MODULES_PROBE_TIMEOUT_MS = 10_000;

export const ModulesService = {
  /**
   * `GET /api/v1/modules`. Sent without the bearer token and without the 401
   * redirect: the chrome asks this before there is a session, and a 401 here
   * must never bounce someone off the page they are reading.
   */
  async get(): Promise<ModulesInfo> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), MODULES_PROBE_TIMEOUT_MS);
    try {
      const body = await apiFetch<unknown>(MODULES_PATH, {
        auth: false,
        redirectOn401: false,
        signal: controller.signal,
      });
      return normaliseModules(body);
    } finally {
      clearTimeout(timer);
    }
  },
};
