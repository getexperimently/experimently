/**
 * The marketing build must not offer a sign-in that cannot work.
 *
 * `getexperimently.com` has no API: `POST /api/v1/auth/login` returns the
 * site's own HTML with a 404. Three "Sign in" controls pointed at it. A dead
 * login button reads as a broken product rather than as software you run
 * yourself, and the homepage already says there is no hosted tier.
 *
 * The flag is MOCKED rather than set through the environment. SITE_MODE is
 * read at module load, so varying it for real needs `isolateModules`, which
 * loads a second React and breaks hooks. What matters here is the page's
 * behaviour given the flag; `site-mode.test.ts` covers reading the variable.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { AuthProvider } from '@/contexts/AuthContext';
import HomePage from '@/pages/index';
import { isMarketingSite } from '@/utils/site-mode';

jest.mock('@/utils/site-mode', () => ({
  ...jest.requireActual('@/utils/site-mode'),
  isMarketingSite: jest.fn(),
}));
jest.mock('next/head', () => { const H=({children}:{children:React.ReactNode})=><>{children}</>; H.displayName='H'; return H; });
jest.mock('next/router', () => ({ useRouter: () => ({ pathname:'/', asPath:'/', query:{}, push:jest.fn(), replace:jest.fn(), isReady:true }) }));

const mode = isMarketingSite as jest.Mock;
const renderHome = () => render(<AuthProvider><HomePage /></AuthProvider>);

beforeEach(() => { localStorage.clear(); mode.mockReset(); });

describe('marketing build', () => {
  beforeEach(() => mode.mockReturnValue(true));

  it('offers no sign-in anywhere', () => {
    const { container } = renderHome();
    expect(container.querySelectorAll('a[href="/login"]')).toHaveLength(0);
    expect(screen.queryByRole('link', { name: /^sign in/i })).toBeNull();
  });

  it('offers the things that do work instead', () => {
    renderHome();
    // Two: the header CTA that replaced Sign in, and the footer nav link.
    expect(screen.getAllByRole('link', { name: /source/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('link', { name: /power calculator/i }).length).toBeGreaterThan(0);
  });

  it('still links the docs and the quick start, which need no backend', () => {
    const { container } = renderHome();
    expect(container.querySelector('a[href="/docs"]')).toBeInTheDocument();
    expect(container.querySelector('a[href*="quick-start.md"]')).toBeInTheDocument();
  });
});

describe('platform build', () => {
  beforeEach(() => mode.mockReturnValue(false));

  it('keeps sign-in, because a self-hoster has an API', () => {
    const { container } = renderHome();
    expect(container.querySelectorAll('a[href="/login"]').length).toBeGreaterThan(0);
  });
});
