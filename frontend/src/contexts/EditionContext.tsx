import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  ReactNode,
} from 'react';
import {
  COMMUNITY_EDITION,
  Edition,
  EditionInfo,
  EditionService,
  LicenseStatus,
  expiryDate,
  featureEnabled,
  grantsFeature,
} from '@/services/edition';

/**
 * Edition gating for the dashboard.
 *
 * `GET /api/v1/edition` is fetched once per browser session and cached for
 * five minutes at module scope, so mounting the provider again (a route
 * change, React StrictMode's double mount, a second provider in a test) costs
 * nothing. Concurrent callers share one in-flight request.
 *
 * **Failure means Community.** If the call throws — backend down, CORS, a
 * proxy returning HTML — the value is {@link COMMUNITY_EDITION}. A dashboard
 * that cannot reach its backend degrades to the free feature set rather than
 * rendering enterprise chrome that cannot work.
 */

/** How long a resolved answer is reused. */
export const EDITION_CACHE_TTL_MS = 5 * 60 * 1000;

/**
 * How long a *failed* probe is reused before it is retried.
 *
 * A failure resolves to Community so the chrome never shows enterprise UI it
 * cannot back — but that fallback must not be sticky: the provider is mounted
 * once in `_app.tsx` and nothing else calls `refresh()`, so a single 502
 * while the tab loaded used to render Community chrome on an Enterprise
 * instance for the rest of the session, with no error shown and no self-heal
 * short of a full reload.
 *
 * Retries back off: 30 s, 60 s, 120 s, ... up to {@link EDITION_ERROR_RETRY_MAX_MS},
 * so a Community dashboard against an older backend with no `/edition` route
 * does not ask every 30 s for the life of the tab.
 */
export const EDITION_ERROR_RETRY_MS = 30 * 1000;
export const EDITION_ERROR_RETRY_MAX_MS = 5 * 60 * 1000;

/** The retry delay after `attempt` consecutive failures (0-based). */
export function retryDelayMs(attempt: number): number {
  return Math.min(EDITION_ERROR_RETRY_MS * 2 ** Math.max(0, attempt), EDITION_ERROR_RETRY_MAX_MS);
}

interface CacheEntry {
  info: EditionInfo;
  error: Error | null;
  fetchedAt: number;
}

let cache: CacheEntry | null = null;
let inFlight: Promise<CacheEntry> | null = null;

/** Test hook: drop the module-level cache and any in-flight request. */
export function __resetEditionCache(): void {
  cache = null;
  inFlight = null;
}

function isFresh(entry: CacheEntry | null, now: number): entry is CacheEntry {
  if (entry === null) return false;
  const ttl = entry.error ? EDITION_ERROR_RETRY_MS : EDITION_CACHE_TTL_MS;
  return now - entry.fetchedAt < ttl;
}

/**
 * Resolve the edition, using the cache when it is still fresh.
 * Never rejects: a failed probe resolves to Community with `error` set.
 */
/**
 * Sequence number of the most recently *started* request. A request that
 * settles after a newer one has started is stale: it must neither overwrite
 * the cache nor be handed to its waiters, or a forced `refresh()` that
 * resolved first would be silently undone by the mount-time probe resolving
 * last — Enterprise chrome flickering back to Community until the TTL.
 */
let requestCounter = 0;

export async function loadEdition(force = false): Promise<CacheEntry> {
  const now = Date.now();
  if (!force && isFresh(cache, now)) return cache;
  if (!force && inFlight) return inFlight;

  const seq = ++requestCounter;
  const request: Promise<CacheEntry> = EditionService.get()
    .then((info): CacheEntry => ({ info, error: null, fetchedAt: Date.now() }))
    .catch(
      (err: unknown): CacheEntry => ({
        info: COMMUNITY_EDITION,
        error: err instanceof Error ? err : new Error(String(err)),
        fetchedAt: Date.now(),
      }),
    )
    .then((entry): CacheEntry | Promise<CacheEntry> => {
      if (seq !== requestCounter) {
        // Superseded. Give every waiter the newer answer: the newer request
        // if it is still running, else the cache it already wrote.
        return inFlight ?? cache ?? entry;
      }
      cache = entry;
      inFlight = null;
      return entry;
    });

  inFlight = request;
  return request;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

export interface EditionContextValue {
  /** Never null. Community until (and unless) the backend says otherwise. */
  info: EditionInfo;
  edition: Edition;
  /** One of the five licence states, `none` in Community. */
  status: LicenseStatus;
  features: string[];
  expiresAt: Date | null;
  version: string;
  /** `edition === 'enterprise'` — true even when the licence has lapsed. */
  isEnterprise: boolean;
  /** True while the first probe is outstanding. */
  isLoading: boolean;
  /** The probe failure, if any. `info` is Community whenever this is set. */
  error: Error | null;
  /** True when the licence names the feature *and* it may be used right now. */
  hasFeature: (name: string) => boolean;
  /** True when the licence names the feature, in date or not. */
  grants: (name: string) => boolean;
  /** Force a re-fetch, bypassing the five-minute cache. */
  refresh: () => Promise<EditionInfo>;
}

function valueFor(
  info: EditionInfo,
  isLoading: boolean,
  error: Error | null,
  refresh: () => Promise<EditionInfo>,
): EditionContextValue {
  return {
    info,
    edition: info.edition,
    status: info.status,
    features: info.features,
    expiresAt: expiryDate(info),
    version: info.version,
    isEnterprise: info.edition === 'enterprise',
    isLoading,
    error,
    hasFeature: (name: string) => featureEnabled(info, name),
    grants: (name: string) => grantsFeature(info, name),
    refresh,
  };
}

const noRefresh = (): Promise<EditionInfo> => Promise.resolve(COMMUNITY_EDITION);

/**
 * What `useEdition()` returns with no provider above it: Community, settled,
 * no error. Chrome components (the wordmark pill, the shell) can therefore be
 * rendered in isolation — and in a test — without a provider.
 */
export const DEFAULT_EDITION_CONTEXT: EditionContextValue = valueFor(
  COMMUNITY_EDITION,
  false,
  null,
  noRefresh,
);

const EditionContext = createContext<EditionContextValue | undefined>(undefined);

export interface EditionProviderProps {
  children: ReactNode;
  /** Seed value; when given, no request is made on mount. */
  initial?: EditionInfo;
}

export function EditionProvider({ children, initial }: EditionProviderProps) {
  const seeded = initial !== undefined;
  const [info, setInfo] = useState<EditionInfo>(() => initial ?? cache?.info ?? COMMUNITY_EDITION);
  const [error, setError] = useState<Error | null>(() => (seeded ? null : (cache?.error ?? null)));
  const [isLoading, setIsLoading] = useState<boolean>(() => !seeded && !isFresh(cache, Date.now()));
  const mounted = useRef(true);

  const apply = useCallback((entry: CacheEntry) => {
    if (!mounted.current) return;
    setInfo(entry.info);
    setError(entry.error);
    setIsLoading(false);
  }, []);

  useEffect(() => {
    mounted.current = true;
    if (seeded) {
      setIsLoading(false);
      return () => {
        mounted.current = false;
      };
    }
    // `active` belongs to *this* invocation of the effect. Under StrictMode
    // the effect runs, is cleaned up, and runs again; a `.then` from the first
    // run must not schedule a timer the second run's cleanup never owned.
    let active = true;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let failures = 0;
    const probe = () => {
      void loadEdition().then((entry) => {
        if (!active) return;
        apply(entry);
        // A failed probe is retried while the provider is mounted, so an
        // Enterprise instance recovers from a transient failure on its own.
        if (entry.error) {
          retry = setTimeout(probe, retryDelayMs(failures));
          failures += 1;
        } else {
          failures = 0;
        }
      });
    };
    probe();
    return () => {
      active = false;
      mounted.current = false;
      if (retry !== null) clearTimeout(retry);
    };
  }, [apply, seeded]);

  const refresh = useCallback(async (): Promise<EditionInfo> => {
    if (mounted.current) setIsLoading(true);
    const entry = await loadEdition(true);
    apply(entry);
    return entry.info;
  }, [apply]);

  const value = useMemo(
    () => valueFor(info, isLoading, error, refresh),
    [info, isLoading, error, refresh],
  );

  return <EditionContext.Provider value={value}>{children}</EditionContext.Provider>;
}

/**
 * Edition and licence state. Outside an {@link EditionProvider} this returns
 * {@link DEFAULT_EDITION_CONTEXT} (Community) instead of throwing — the same
 * default as an unreachable backend, and for the same reason.
 */
export function useEdition(): EditionContextValue {
  return useContext(EditionContext) ?? DEFAULT_EDITION_CONTEXT;
}

/** True when `name` is licensed and usable right now. */
export function useFeature(name: string): boolean {
  return useEdition().hasFeature(name);
}

export interface RequiresFeatureProps {
  /** Feature name, e.g. `FEATURES.RBAC`. */
  name: string;
  /** Rendered when the feature is not available. Defaults to nothing at all. */
  fallback?: ReactNode;
  children: ReactNode;
}

/**
 * Render `children` only when `name` is licensed and in date, otherwise
 * `fallback` (nothing by default).
 */
export function RequiresFeature({ name, fallback = null, children }: RequiresFeatureProps) {
  const enabled = useFeature(name);
  return <>{enabled ? children : fallback}</>;
}

export default EditionProvider;
