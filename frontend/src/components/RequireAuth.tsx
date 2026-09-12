import React, { ReactNode, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useAuth } from '@/contexts/AuthContext';
import { LOGIN_PATH, Role, safeNextPath } from '@/services/api';

export interface RequireAuthProps {
  children: ReactNode;
  /** When set, the user must hold one of these roles. */
  roles?: Role[];
  /** Where the "Go back" link on the 403 view points. Default `/experiments`. */
  fallbackPath?: string;
  /** Custom element rendered while the session is being resolved. */
  loading?: ReactNode;
}

/**
 * Client-side gate for protected pages (the API is the real enforcement).
 *
 * - `loading`    → spinner
 * - `anonymous`  → `router.replace('/login?next=<current path>')`
 * - wrong role   → inline 403 view (`data-testid="require-auth-forbidden"`)
 */
export function RequireAuth({ children, roles, fallbackPath = '/experiments', loading }: RequireAuthProps) {
  const { status, user } = useAuth();
  const router = useRouter();

  const { isReady, asPath } = router;

  useEffect(() => {
    if (status !== 'anonymous') return;
    // On a static export `asPath` is the route pattern (`/experiments/[id]`)
    // until the router is ready; wait so `next=` carries the real URL.
    if (!isReady) return;
    const next = safeNextPath(asPath, '/');
    const target =
      next === '/' || next.startsWith(LOGIN_PATH)
        ? LOGIN_PATH
        : `${LOGIN_PATH}?next=${encodeURIComponent(next)}`;
    void router.replace(target);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, isReady, asPath]);

  if (status === 'loading' || status === 'anonymous' || !user) {
    return (
      <>
        {loading ?? (
          <div
            data-testid="require-auth-loading"
            className="flex items-center justify-center min-h-[40vh]"
            role="status"
            aria-live="polite"
          >
            <div className="inline-block w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
            <span className="sr-only">Loading…</span>
          </div>
        )}
      </>
    );
  }

  if (roles && roles.length > 0 && !roles.includes(user.role)) {
    return (
      <div
        data-testid="require-auth-forbidden"
        className="flex flex-col items-center justify-center min-h-[40vh] gap-4 px-4 text-center"
      >
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">403</p>
        <p className="text-slate-700 text-lg">You do not have permission to access this page.</p>
        <p className="text-sm text-slate-500">
          Signed in as <span className="font-medium">{user.email}</span> ({user.role}). This page
          requires {roles.join(' or ')}.
        </p>
        <Link href={fallbackPath} className="text-blue-600 hover:underline" aria-label="Go to Home">
          Go to Home
        </Link>
      </div>
    );
  }

  return <>{children}</>;
}

export default RequireAuth;
