import React, { useEffect } from 'react';
import { useRouter } from 'next/router';
import { useAuth } from '@/contexts/AuthContext';
import { PageTitle } from '@/components/PageTitle';
import { Wordmark } from '@/components/Wordmark';
import { LOGIN_PATH } from '@/services/api';

export const HOME_AFTER_LOGIN = '/experiments';

/**
 * Dashboard entry point. The marketing landing page that used to live here
 * moves to the public site; the app root now only routes the visitor:
 * authenticated → /experiments, anonymous → /login.
 */
export default function HomePage() {
  const router = useRouter();
  const { status } = useAuth();

  useEffect(() => {
    if (status === 'authenticated') {
      void router.replace(HOME_AFTER_LOGIN);
    } else if (status === 'anonymous') {
      void router.replace(LOGIN_PATH);
    }
  }, [status, router]);

  return (
    <>
      <PageTitle />
      <main
        data-testid="home-redirect"
        role="status"
        aria-live="polite"
        className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-4"
      >
        <Wordmark href={null} />
        <div className="inline-block w-5 h-5 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
        <span className="sr-only">Redirecting…</span>
      </main>
    </>
  );
}
