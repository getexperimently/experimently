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
  CORE_PROFILE,
  ModulesInfo,
  ModulesService,
  Profile,
  moduleInstalled,
} from '@/services/modules';

/**
 * Which modules this instance has, for the dashboard.
 *
 * `GET /api/v1/modules` is fetched once per browser session and cached for
 * five minutes at module scope, so mounting the provider again (a route
 * change, React StrictMode's double mount, a second provider in a test) costs
 * nothing. Concurrent callers share one in-flight request.
 *
 * **Failure means core.** If the call throws — backend down, CORS, a proxy
 * returning HTML — the value is {@link CORE_PROFILE}. A dashboard that cannot
 * reach its backend degrades to the core feature set rather than rendering
 * module chrome that cannot work.
 */

/** How long a resolved answer is reused. */
export const MODULES_CACHE_TTL_MS = 5 * 60 * 1000;

/**
 * How long a *failed* probe is reused before it is retried.
 *
 * A failure resolves to core so the chrome never shows module UI it cannot
 * back — but that fallback must not be sticky: the provider is mounted once
 * in `_app.tsx` and nothing else calls `refresh()`, so a single 502 while the
 * tab loaded used to render core chrome on a full-profile instance for the
 * rest of the session, with no error shown and no self-heal short of a full
 * reload.
 *
 * Retries back off: 30 s, 60 s, 120 s, ... up to {@link MODULES_ERROR_RETRY_MAX_MS},
 * so a dashboard against an older backend with no `/modules` route does not
 * ask every 30 s for the life of the tab.
 */
export const MODULES_ERROR_RETRY_MS = 30 * 1000;
export const MODULES_ERROR_RETRY_MAX_MS = 5 * 60 * 1000;

/** The retry delay after `attempt` consecutive failures (0-based). */
export function retryDelayMs(attempt: number): number {
  return Math.min(MODULES_ERROR_RETRY_MS * 2 ** Math.max(0, attempt), MODULES_ERROR_RETRY_MAX_MS);
}

interface CacheEntry {
  info: ModulesInfo;
  error: Error | null;
  fetchedAt: number;
}

let cache: CacheEntry | null = null;
let inFlight: Promise<CacheEntry> | null = null;

/** Test hook: drop the module-level cache and any in-flight request. */
export function __resetModulesCache(): void {
  cache = null;
  inFlight = null;
}

function isFresh(entry: CacheEntry | null, now: number): entry is CacheEntry {
  if (entry === null) return false;
  const ttl = entry.error ? MODULES_ERROR_RETRY_MS : MODULES_CACHE_TTL_MS;
  return now - entry.fetchedAt < ttl;
}

/**
 * Sequence number of the most recently *started* request. A request that
 * settles after a newer one has started is stale: it must neither overwrite
 * the cache nor be handed to its waiters, or a forced `refresh()` that
 * resolved first would be silently undone by the mount-time probe resolving
 * last — module chrome flickering back to core until the TTL.
 */
let requestCounter = 0;

/**
 * Resolve the installed modules, using the cache when it is still fresh.
 * Never rejects: a failed probe resolves to core with `error` set.
 */
export async function loadModules(force = false): Promise<CacheEntry> {
  const now = Date.now();
  if (!force && isFresh(cache, now)) return cache;
  if (!force && inFlight) return inFlight;

  const seq = ++requestCounter;
  const request: Promise<CacheEntry> = ModulesService.get()
    .then((info): CacheEntry => ({ info, error: null, fetchedAt: Date.now() }))
    .catch(
      (err: unknown): CacheEntry => ({
        info: CORE_PROFILE,
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

export interface ModulesContextValue {
  /** `core` until (and unless) the backend says `full`. */
  profile: Profile;
  /** Names of the installed modules. Empty in `core`. */
  modules: string[];
  version: string;
  /**
   * True while there is no answer yet — the first probe, and only that.
   *
   * A {@link ModulesContextValue.refresh} that already has an answer leaves
   * this false: "we are asking again" is not "we have nothing to show", and a
   * consumer that blanks itself on `isLoading` would otherwise unmount the very
   * button the user clicked to trigger the refresh.
   */
  isLoading: boolean;
  /** The probe failure, if any. The profile is `core` whenever this is set. */
  error: Error | null;
  /** True when the named module is installed on this instance. */
  hasModule: (name: string) => boolean;
  /** Force a re-fetch, bypassing the five-minute cache. */
  refresh: () => Promise<ModulesInfo>;
}

function valueFor(
  info: ModulesInfo,
  isLoading: boolean,
  error: Error | null,
  refresh: () => Promise<ModulesInfo>,
): ModulesContextValue {
  return {
    profile: info.profile,
    modules: info.modules,
    version: info.version,
    isLoading,
    error,
    hasModule: (name: string) => moduleInstalled(info, name),
    refresh,
  };
}

const noRefresh = (): Promise<ModulesInfo> => Promise.resolve(CORE_PROFILE);

/**
 * What `useModules()` returns with no provider above it: core, settled, no
 * error. Chrome components (the shell, the admin sidebar) can therefore be
 * rendered in isolation — and in a test — without a provider.
 */
export const DEFAULT_MODULES_CONTEXT: ModulesContextValue = valueFor(
  CORE_PROFILE,
  false,
  null,
  noRefresh,
);

const ModulesContext = createContext<ModulesContextValue | undefined>(undefined);

export interface ModulesProviderProps {
  children: ReactNode;
  /** Seed value; when given, no request is made on mount. */
  initial?: ModulesInfo;
}

export function ModulesProvider({ children, initial }: ModulesProviderProps) {
  const seeded = initial !== undefined;
  const [info, setInfo] = useState<ModulesInfo>(() => initial ?? cache?.info ?? CORE_PROFILE);
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
      void loadModules().then((entry) => {
        if (!active) return;
        apply(entry);
        // A failed probe is retried while the provider is mounted, so a
        // full-profile instance recovers from a transient failure on its own.
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

  const refresh = useCallback(async (): Promise<ModulesInfo> => {
    // Deliberately does NOT raise `isLoading`. It means "nothing to show yet",
    // and a refresh that already has an answer still has that answer: the only
    // caller is the retry button inside `ModuleUnavailableNotice`, which would
    // unmount itself the instant it was clicked — a blank page for the length
    // of the probe (up to the ten-second timeout), and the button's own
    // "Checking…" state unreachable. Whoever asked for the refresh owns the
    // in-flight affordance; the context owns the answer.
    const entry = await loadModules(true);
    apply(entry);
    return entry.info;
  }, [apply]);

  const value = useMemo(
    () => valueFor(info, isLoading, error, refresh),
    [info, isLoading, error, refresh],
  );

  return <ModulesContext.Provider value={value}>{children}</ModulesContext.Provider>;
}

/**
 * Profile and installed modules. Outside a {@link ModulesProvider} this
 * returns {@link DEFAULT_MODULES_CONTEXT} (core) instead of throwing — the
 * same default as an unreachable backend, and for the same reason.
 */
export function useModules(): ModulesContextValue {
  return useContext(ModulesContext) ?? DEFAULT_MODULES_CONTEXT;
}

/** True when the module `name` is installed on this instance. */
export function useModule(name: string): boolean {
  return useModules().hasModule(name);
}

export interface RequiresModuleProps {
  /** Module name, e.g. `MODULES.RBAC`. */
  name: string;
  /** Rendered when the module is not installed. Defaults to nothing at all. */
  fallback?: ReactNode;
  children: ReactNode;
}

/**
 * Render `children` only when the module `name` is installed, otherwise
 * `fallback` (nothing by default).
 */
export function RequiresModule({ name, fallback = null, children }: RequiresModuleProps) {
  const installed = useModule(name);
  return <>{installed ? children : fallback}</>;
}

export default ModulesProvider;
