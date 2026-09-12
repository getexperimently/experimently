import React, { ReactNode, useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useAuth } from '@/contexts/AuthContext';
import { Wordmark } from '@/components/Wordmark';
import { LOGIN_PATH, Role, UserMe, safeNextPath } from '@/services/api';
import { ROLE_COLORS, USER_ROLE_LABELS } from '@/types/admin';
import { EditionBanner } from '@/components/EditionBanner';
import { useEdition } from '@/contexts/EditionContext';
import { EDITIONS_DOC_PATH, EditionInfo, FEATURES, featureEnabled } from '@/services/edition';

export interface NavItem {
  label: string;
  href: string;
  testId: string;
  /** When set, the item is only shown to users holding one of these roles. */
  roles?: Role[];
}

export const NAV_ITEMS: NavItem[] = [
  { label: 'Experiments', href: '/experiments', testId: 'nav-experiments' },
  { label: 'Feature Flags', href: '/feature-flags', testId: 'nav-feature-flags' },
  { label: 'Admin', href: '/admin', testId: 'nav-admin', roles: ['ADMIN', 'DEVELOPER'] },
  { label: 'Docs', href: '/docs', testId: 'nav-docs' },
];

export function isNavActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Routes that only exist under an Enterprise licence. They are kept out of
 * `NAV_ITEMS` — the primary nav is Community chrome and must not hard-link
 * Enterprise routes (`docs/planning/ee-coupling-report.md` §6) — and surface
 * instead inside the collapsed "Enterprise" group below.
 */
export const ENTERPRISE_NAV_ITEMS: (NavItem & { feature: string })[] = [
  {
    label: 'Workspaces',
    href: '/workspaces',
    testId: 'nav-workspaces',
    feature: FEATURES.WORKSPACES,
  },
];

/** The Enterprise routes this licence actually allows. */
export function licensedEnterpriseNav(edition: EditionInfo): NavItem[] {
  return ENTERPRISE_NAV_ITEMS.filter((item) => featureEnabled(edition, item.feature));
}

/**
 * Collapsed "Enterprise" disclosure. Closed by default and never opened for
 * the viewer: it is a place to find out what the tier is, not a prompt. In a
 * licensed instance it also carries the Enterprise routes, which otherwise
 * have no navigation at all.
 */
function EnterpriseNavGroup({
  items,
  id,
  onNavigate,
}: {
  items: NavItem[];
  id: string;
  /** Called when a link inside the group is followed (closes the mobile menu). */
  onNavigate?: () => void;
}) {
  // Controlled, not a bare <details>: _app.tsx keeps one AppShell across
  // client-side navigations, so an uncontrolled disclosure stayed open --
  // an absolutely positioned panel over the *next* page -- after any link
  // in it was clicked. It closes on the click and on every route change.
  const [open, setOpen] = useState(false);
  const details = useRef<HTMLDetailsElement>(null);
  const router = useRouter();
  // Close both the React state and the element itself. The browser flips the
  // `open` attribute the moment <summary> is clicked and reports it through a
  // *queued* toggle event, so a close requested before that event lands would
  // otherwise be a no-op for React (prop false -> false) while the DOM stays
  // open.
  const close = useCallback(() => {
    setOpen(false);
    if (details.current) details.current.open = false;
  }, []);
  useEffect(() => {
    router.events?.on('routeChangeStart', close);
    return () => {
      router.events?.off('routeChangeStart', close);
    };
  }, [router.events, close]);
  // A native <details> never closes on an outside click or Escape, and this
  // one is an absolutely positioned panel over the page: while it is open,
  // a click anywhere else or Escape closes it.
  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: MouseEvent) => {
      if (details.current && !details.current.contains(event.target as Node)) close();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close();
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, close]);
  const follow = () => {
    close();
    onNavigate?.();
  };
  return (
    <details
      ref={details}
      data-testid="enterprise-nav-group"
      className="relative"
      open={open}
      onToggle={(event) => setOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className="cursor-pointer list-none px-3 py-1.5 rounded-md text-sm font-medium text-slate-500 hover:text-slate-900 hover:bg-slate-50">
        Enterprise
      </summary>
      <div
        id={id}
        className="absolute right-0 z-40 mt-1 w-56 rounded-md border border-slate-200 bg-white p-1 shadow-lg"
      >
        {items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            data-testid={item.testId}
            onClick={follow}
            className="block px-3 py-2 rounded-md text-sm text-slate-700 hover:bg-slate-50"
          >
            {item.label}
          </Link>
        ))}
        <Link
          href={EDITIONS_DOC_PATH}
          data-testid="nav-editions-docs"
          onClick={follow}
          className="block px-3 py-2 rounded-md text-sm text-slate-600 hover:bg-slate-50"
        >
          Editions &amp; licensing
        </Link>
      </div>
    </details>
  );
}

export function displayName(user: UserMe): string {
  return user.full_name?.trim() || user.username || user.email;
}

function initials(user: UserMe): string {
  const name = displayName(user);
  const parts = name.split(/[\s@._-]+/).filter(Boolean);
  const letters = parts.slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '');
  return letters.join('') || 'U';
}

interface AppShellProps {
  children: ReactNode;
}

/**
 * Application chrome: top navigation (Experiments · Feature Flags · Admin ·
 * Docs), the edition pill and the user area with a visible "Log out" button.
 * Mounted by `_app.tsx` for every route except `/login`.
 */
export function AppShell({ children }: AppShellProps) {
  const router = useRouter();
  const { user, status, logout } = useAuth();
  const { info: edition } = useEdition();
  const [menuOpen, setMenuOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  const pathname = router.pathname;
  const visibleNav = NAV_ITEMS.filter(
    (item) => !item.roles || (user !== null && item.roles.includes(user.role)),
  );
  const enterpriseNav = licensedEnterpriseNav(edition);

  const handleLogout = async () => {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await logout();
    } finally {
      setLoggingOut(false);
      setMenuOpen(false);
      void router.replace(LOGIN_PATH);
    }
  };

  const signInHref = (() => {
    // Before hydration `asPath` may still be the route pattern; link plainly then.
    if (!router.isReady) return LOGIN_PATH;
    const next = safeNextPath(router.asPath, '/');
    return next === '/' ? LOGIN_PATH : `${LOGIN_PATH}?next=${encodeURIComponent(next)}`;
  })();

  return (
    <div data-testid="app-shell" className="min-h-screen bg-slate-50 flex flex-col">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:bg-white focus:px-3 focus:py-2 focus:rounded-md focus:shadow"
      >
        Skip to content
      </a>

      <header className="bg-white border-b border-slate-200 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center justify-between gap-4">
          <div className="flex items-center gap-6 min-w-0">
            <Wordmark href={status === 'authenticated' ? '/experiments' : '/'} />

            <nav aria-label="Primary" className="hidden md:flex items-center gap-1">
              {visibleNav.map((item) => {
                const active = isNavActive(pathname, item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    data-testid={item.testId}
                    aria-current={active ? 'page' : undefined}
                    className={[
                      'px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
                      active
                        ? 'bg-blue-50 text-blue-700'
                        : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50',
                    ].join(' ')}
                  >
                    {item.label}
                  </Link>
                );
              })}
              <EnterpriseNavGroup items={enterpriseNav} id="enterprise-nav-desktop" />
            </nav>
          </div>

          <div className="flex items-center gap-3">
            {status === 'loading' && (
              <div data-testid="user-menu-loading" className="h-8 w-24 rounded-md bg-slate-100 animate-pulse" />
            )}

            {status === 'anonymous' && (
              <Link
                href={signInHref}
                data-testid="nav-sign-in"
                className="px-3 py-1.5 rounded-md text-sm font-medium bg-blue-600 text-white hover:bg-blue-700"
              >
                Sign in
              </Link>
            )}

            {status === 'authenticated' && user && (
              <div data-testid="user-menu" className="flex items-center gap-3">
                <div className="hidden sm:flex items-center gap-2 min-w-0">
                  <span
                    aria-hidden="true"
                    className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700"
                  >
                    {initials(user)}
                  </span>
                  <span
                    data-testid="user-menu-name"
                    className="text-sm font-medium text-slate-800 truncate max-w-[12rem]"
                    title={user.email}
                  >
                    {displayName(user)}
                  </span>
                  <span
                    data-testid="user-menu-role"
                    className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-semibold ${ROLE_COLORS[user.role]}`}
                  >
                    {USER_ROLE_LABELS[user.role]}
                  </span>
                </div>
                <button
                  type="button"
                  data-testid="logout-button"
                  onClick={() => void handleLogout()}
                  disabled={loggingOut}
                  className="px-3 py-1.5 rounded-md text-sm font-medium text-slate-600 border border-slate-300 hover:bg-slate-50 hover:text-slate-900 disabled:opacity-60"
                >
                  {loggingOut ? 'Logging out…' : 'Log out'}
                </button>
              </div>
            )}

            <button
              type="button"
              className="md:hidden inline-flex items-center justify-center h-8 w-8 rounded-md text-slate-600 hover:bg-slate-100"
              aria-label={menuOpen ? 'Close navigation' : 'Open navigation'}
              aria-expanded={menuOpen}
              aria-controls="mobile-nav"
              data-testid="mobile-nav-toggle"
              onClick={() => setMenuOpen((open) => !open)}
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                {menuOpen ? (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                )}
              </svg>
            </button>
          </div>
        </div>

        {menuOpen && (
          <nav
            id="mobile-nav"
            aria-label="Primary mobile"
            data-testid="mobile-nav"
            className="md:hidden border-t border-slate-200 bg-white px-4 py-2 flex flex-col gap-1"
          >
            {visibleNav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                onClick={() => setMenuOpen(false)}
                aria-current={isNavActive(pathname, item.href) ? 'page' : undefined}
                className={[
                  'px-3 py-2 rounded-md text-sm font-medium',
                  isNavActive(pathname, item.href) ? 'bg-blue-50 text-blue-700' : 'text-slate-700 hover:bg-slate-50',
                ].join(' ')}
              >
                {item.label}
              </Link>
            ))}
            <EnterpriseNavGroup
              items={enterpriseNav}
              id="enterprise-nav-mobile"
              onNavigate={() => setMenuOpen(false)}
            />
          </nav>
        )}
      </header>

      <EditionBanner />

      <main id="main-content" className="flex-1 flex flex-col">
        {children}
      </main>
    </div>
  );
}

export default AppShell;
