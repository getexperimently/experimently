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
  ApiError,
  LoginResponse,
  Role,
  TOKEN_STORAGE_KEY,
  UserMe,
  apiFetch,
  clearToken,
  getToken,
  setToken,
  unreachableMessage,
} from '@/services/api';

export type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

export interface AuthContextValue {
  user: UserMe | null;
  status: AuthStatus;
  /** Convenience: `status === 'authenticated'`. */
  isAuthenticated: boolean;
  /** `POST /api/v1/auth/login`; stores the token and resolves with the user. */
  login: (email: string, password: string) => Promise<UserMe>;
  /** `POST /api/v1/auth/logout` (best effort), then clears the token. */
  logout: () => Promise<void>;
  /** Re-fetch `/auth/me` (e.g. after a profile change). */
  refresh: () => Promise<UserMe | null>;
  /** True when the current user has one of the given roles. */
  hasRole: (...roles: Role[]) => boolean;
  /**
   * Why a stored session could not be restored, when the reason was not a
   * rejected token: a server error or an unreachable API. The login page shows
   * it, so the redirect there is not silent. `null` otherwise.
   */
  sessionError: string | null;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

const ME_PATH = '/api/v1/auth/me';
const LOGIN_PATH = '/api/v1/auth/login';
const LOGOUT_PATH = '/api/v1/auth/logout';

/** Copy for a session that could not be restored for a reason other than 401. */
export function sessionErrorMessage(err: unknown): string {
  if (err instanceof ApiError && err.isNetworkError) return unreachableMessage();
  if (err instanceof ApiError && err.isServerError) {
    const id = err.requestId ? ` Request ID: ${err.requestId}.` : '';
    return `Signed out because the server returned an error (HTTP ${err.status}).${id}`;
  }
  return 'Signed out because your session could not be checked. Sign in again.';
}

/**
 * Only the bearer token is persisted (`localStorage["experimently.token"]`).
 * The user object is always re-derived from `GET /api/v1/auth/me` on mount so
 * a stale or revoked token can never resurrect a session.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserMe | null>(null);
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [sessionError, setSessionError] = useState<string | null>(null);
  const mounted = useRef(true);

  const applyAnonymous = useCallback(() => {
    if (!mounted.current) return;
    setUser(null);
    setStatus('anonymous');
  }, []);

  const loadMe = useCallback(async (): Promise<UserMe | null> => {
    if (!getToken()) {
      applyAnonymous();
      return null;
    }
    try {
      const me = await apiFetch<UserMe>(ME_PATH, { redirectOn401: false });
      if (mounted.current) {
        setUser(me);
        setStatus('authenticated');
        setSessionError(null);
      }
      return me;
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        // apiFetch already cleared the token.
        applyAnonymous();
        return null;
      }
      // API unreachable or 5xx: keep the token for the next reload but treat
      // the session as anonymous so protected pages fall back to /login, and
      // say why there.
      if (mounted.current) setSessionError(sessionErrorMessage(err));
      applyAnonymous();
      return null;
    }
  }, [applyAnonymous]);

  useEffect(() => {
    mounted.current = true;
    void loadMe();
    return () => {
      mounted.current = false;
    };
  }, [loadMe]);

  // Keep tabs in sync: logging out (or in) elsewhere updates this tab too.
  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const onStorage = (event: StorageEvent) => {
      if (event.key !== TOKEN_STORAGE_KEY && event.key !== null) return;
      if (!getToken()) {
        applyAnonymous();
      } else {
        void loadMe();
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [applyAnonymous, loadMe]);

  const login = useCallback(async (email: string, password: string): Promise<UserMe> => {
    const result = await apiFetch<LoginResponse>(LOGIN_PATH, {
      method: 'POST',
      json: { email, password },
      auth: false,
    });
    setToken(result.access_token);
    if (mounted.current) {
      setUser(result.user);
      setStatus('authenticated');
      setSessionError(null);
    }
    return result.user;
  }, []);

  const logout = useCallback(async (): Promise<void> => {
    if (getToken()) {
      try {
        await apiFetch<void>(LOGOUT_PATH, { method: 'POST', redirectOn401: false });
      } catch {
        /* stateless logout — the token is discarded regardless */
      }
    }
    clearToken();
    setSessionError(null);
    applyAnonymous();
  }, [applyAnonymous]);

  const hasRole = useCallback(
    (...roles: Role[]): boolean => !!user && roles.includes(user.role),
    [user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      isAuthenticated: status === 'authenticated',
      login,
      logout,
      refresh: loadMe,
      hasRole,
      sessionError,
    }),
    [user, status, login, logout, loadMe, hasRole, sessionError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return ctx;
}

/** Like `useAuth` but returns `null` outside an `AuthProvider`. */
export function useOptionalAuth(): AuthContextValue | null {
  return useContext(AuthContext) ?? null;
}
