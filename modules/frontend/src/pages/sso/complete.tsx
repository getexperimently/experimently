/**
 * `/sso/complete` — finish a dashboard SSO sign-in (C2b).
 *
 * The API's callback redirects here with `#code=<hand-off code>`. This page
 * reads the fragment once, takes it out of the address bar, and exchanges the
 * code together with this tab's secret for a session. A bare route
 * (`BARE_ROUTES` in `@/utils/routes`): no shell, and no `RequireAuth` bounce
 * to `/login?next=` that would carry the fragment along.
 *
 * **Exactly one exchange.** React StrictMode mounts, unmounts and re-mounts
 * in development, and the first mount has already cleared the fragment; so
 * the fragment is captured, and the exchange started, once per page load in a
 * module-scope latch that both mounts subscribe to. Only the mount that is
 * still mounted when it settles navigates.
 */
import React, { useEffect } from 'react';
import { useRouter } from 'next/router';
import { withModule } from '@/components/ModuleNotice';
import { PageTitle } from '@/components/PageTitle';
import { useAuth } from '@/contexts/AuthContext';
import { MODULES } from '@/services/modules';
import { safeNextPath, setToken } from '@/services/api';
import {
  SSO_COMPLETE_PATH,
  clearPending,
  codeFromHash,
  exchangeFailurePath,
  exchangeSsoCode,
  loginErrorPath,
  readPending,
} from '@modules/services/sso';

/** Where a sign-in with no `next` lands (the login page's default). */
const DEFAULT_AFTER_SIGN_IN = '/experiments';

type Outcome = { signedIn: true; next: string } | { signedIn: false; path: string };

let latch: Promise<Outcome> | null = null;

/** Test hook: forget the page load's exchange. */
export function __resetSsoCompleteLatch(): void {
  latch = null;
}

function begin(): Promise<Outcome> {
  const hash = window.location.hash;
  window.history.replaceState(window.history.state, '', SSO_COMPLETE_PATH);
  const code = codeFromHash(hash);
  const pending = readPending();
  if (!code || !pending) {
    return Promise.resolve({ signedIn: false, path: loginErrorPath('sso_state') });
  }
  return exchangeSsoCode(code, pending.secret).then(
    (session): Outcome => {
      setToken(session.access_token);
      clearPending();
      return { signedIn: true, next: safeNextPath(pending.next, DEFAULT_AFTER_SIGN_IN) };
    },
    (err): Outcome => ({ signedIn: false, path: exchangeFailurePath(err) }),
  );
}

function SsoCompletePage() {
  const router = useRouter();
  const { refresh } = useAuth();

  useEffect(() => {
    let mounted = true;
    if (latch === null) latch = begin();
    void latch.then(async (outcome) => {
      if (!mounted) return;
      if (outcome.signedIn) {
        await refresh();
        if (mounted) void router.replace(outcome.next);
      } else {
        void router.replace(outcome.path);
      }
    });
    return () => {
      mounted = false;
    };
    // Once per mount; the latch makes it once per page load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <PageTitle title="Signing in" />
      <main className="min-h-screen bg-slate-50 flex items-center justify-center px-4">
        <p role="status" data-testid="sso-complete" className="text-sm text-slate-600">
          Signing you in…
        </p>
      </main>
    </>
  );
}

export default withModule(SsoCompletePage, {
  title: 'Single sign-on',
  module: MODULES.SSO,
  description: 'Sign in with your organisation’s identity provider (Okta, Google, GitHub).',
});
