/**
 * Edition and licence state — `GET /api/v1/edition`.
 *
 * The endpoint is unauthenticated on purpose (it drives chrome that renders
 * before anyone has logged in) and deliberately thin: it never returns the
 * customer, the plan or any part of the licence key. See
 * `backend/app/api/v1/endpoints/edition.py`.
 *
 * Everything here is pure except `EditionService.get()`; the caching,
 * React wiring and `useFeature` hook live in `@/contexts/EditionContext`.
 */
import { apiFetch } from '@/services/api';

export const EDITION_PATH = '/api/v1/edition';

/** Where the editions documentation lives (`docs/getting-started/editions.md`). */
export const EDITIONS_DOC_PATH = '/docs/editions';

export type Edition = 'ce' | 'enterprise';

/**
 * Five states, not four. `invalid` is what a tampered, malformed, revoked or
 * not-yet-valid licence reports (`backend/app/core/license.py::LicenseStatus`)
 * and it is distinct from `none` (no licence configured at all — plain CE).
 * Leaving it out of the union is how the dashboard ends up rendering an
 * unknown state, so it is listed here and exercised by the tests.
 */
export type LicenseStatus = 'none' | 'active' | 'grace' | 'expired' | 'invalid';

/** The five members of {@link LicenseStatus}, in the backend's own order. */
export const LICENSE_STATUSES: readonly LicenseStatus[] = [
  'none',
  'active',
  'grace',
  'expired',
  'invalid',
] as const;

/** Statuses in which an enterprise feature may actually be used. */
export const USABLE_STATUSES: readonly LicenseStatus[] = ['active', 'grace'] as const;

/** Feature name that grants everything (developer licences use it). */
export const WILDCARD_FEATURE = '*';

/** Response body of `GET /api/v1/edition`. */
export interface EditionInfo {
  edition: Edition;
  /** Feature names the licence covers. Empty in CE and for an invalid licence. */
  features: string[];
  status: LicenseStatus;
  /** Licence `exp` as an ISO-8601 string, or `null` in CE. */
  expires_at: string | null;
  version: string;
}

/**
 * What the dashboard is when it has no other information: Community Edition,
 * no features, no licence. Every failure path resolves to this value.
 */
export const COMMUNITY_EDITION: EditionInfo = Object.freeze({
  edition: 'ce',
  features: [],
  status: 'none',
  expires_at: null,
  version: '',
}) as EditionInfo;

/**
 * Feature names — one per `ee-manifest.txt` group. Only the ones the dashboard
 * gates today are referenced in components; the rest are here so the names live
 * in one place.
 *
 * **This block is parsed, not just read.** It is the canonical spelling of the
 * contract: `backend/app/core/license.py::KNOWN_FEATURES` must list exactly
 * these strings in exactly this order, `require_feature()` raises at
 * router-build time for anything outside the list, and
 * `backend/tests/unit/core/test_feature_names.py` extracts this literal and
 * compares the two element for element. Keep it a plain object literal of
 * `KEY: 'value',` lines, and change a spelling on both sides at once.
 */
export const FEATURES = {
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

export type FeatureName = (typeof FEATURES)[keyof typeof FEATURES];

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

export function isLicenseStatus(value: unknown): value is LicenseStatus {
  return typeof value === 'string' && (LICENSE_STATUSES as readonly string[]).indexOf(value) !== -1;
}

/**
 * Coerce an untrusted body into an {@link EditionInfo}.
 *
 * A status the dashboard does not know about is reported as `invalid` rather
 * than passed through: an unrecognised state must never read as a licensed
 * one. An unrecognised `edition` falls back to `ce` for the same reason.
 */
export function normaliseEdition(raw: unknown): EditionInfo {
  if (!raw || typeof raw !== 'object') return COMMUNITY_EDITION;
  const body = raw as Record<string, unknown>;

  const edition: Edition = body.edition === 'enterprise' ? 'enterprise' : 'ce';
  const status: LicenseStatus = isLicenseStatus(body.status)
    ? body.status
    : edition === 'enterprise'
      ? 'invalid'
      : 'none';
  const features = Array.isArray(body.features)
    ? body.features.filter((f): f is string => typeof f === 'string')
    : [];

  return {
    edition,
    features,
    status,
    expires_at: typeof body.expires_at === 'string' ? body.expires_at : null,
    version: typeof body.version === 'string' ? body.version : '',
  };
}

// ---------------------------------------------------------------------------
// Feature checks
// ---------------------------------------------------------------------------

/** True when the licence *names* the feature, ignoring whether it is in date. */
export function grantsFeature(info: EditionInfo, name: string): boolean {
  if (info.edition !== 'enterprise') return false;
  return info.features.indexOf(WILDCARD_FEATURE) !== -1 || info.features.indexOf(name) !== -1;
}

/**
 * True when the feature may be used right now — the frontend mirror of
 * `LicenseState.allows(name, write=True)`.
 *
 * `expired` is treated as off. The backend keeps serving enterprise *reads*
 * for 30 days after the grace window but refuses every write, and the API
 * reports both sub-windows as the same `expired` string, so the dashboard
 * cannot tell them apart. Rendering enterprise UI that can only read — and
 * fails with 403 the moment anyone saves — is worse than hiding it and
 * saying so in the banner.
 */
export function featureEnabled(info: EditionInfo, name: string): boolean {
  if (!grantsFeature(info, name)) return false;
  return (USABLE_STATUSES as readonly string[]).indexOf(info.status) !== -1;
}

/** Licence expiry as a `Date`, or `null` when absent or unparseable. */
export function expiryDate(info: EditionInfo): Date | null {
  if (!info.expires_at) return null;
  const parsed = new Date(info.expires_at);
  return isNaN(parsed.getTime()) ? null : parsed;
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

/**
 * How long the edition probe may hang before it is treated as a failure.
 *
 * A probe that *fails* resolves to Community and is retried; a probe that
 * *hangs* -- a stuck upstream behind nginx's hour-long proxy_read_timeout --
 * used to pin the shared in-flight promise for the whole tab session, with
 * no error to retry from. The timeout turns a hang into a failure.
 */
export const EDITION_PROBE_TIMEOUT_MS = 10_000;

export const EditionService = {
  /**
   * `GET /api/v1/edition`. Sent without the bearer token and without the 401
   * redirect: the chrome asks this before there is a session, and a 401 here
   * must never bounce someone off the page they are reading.
   */
  async get(): Promise<EditionInfo> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), EDITION_PROBE_TIMEOUT_MS);
    try {
      const body = await apiFetch<unknown>(EDITION_PATH, {
        auth: false,
        redirectOn401: false,
        signal: controller.signal,
      });
      return normaliseEdition(body);
    } finally {
      clearTimeout(timer);
    }
  },
};
