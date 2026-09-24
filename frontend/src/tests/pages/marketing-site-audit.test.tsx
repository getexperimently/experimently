/**
 * A sweep of every page the marketing site ships, asserting none of them
 * offers something that cannot work there.
 *
 * Written because fixing them one report at a time did not converge: the
 * homepage was fixed, then the shell still showed Sign in on /docs and
 * /power-calculator, then the calculator still had an AI panel calling an
 * endpoint that 404s. Each was found by a person looking at the site.
 *
 * The rule: on the marketing build, NOTHING may link to /login or to a pruned
 * dashboard route, and nothing may call the API.
 */
import React from 'react';
import { render, waitFor } from '@testing-library/react';
import { AuthProvider } from '@/contexts/AuthContext';
import { isMarketingSite, PLATFORM_ONLY_PREFIXES } from '@/utils/site-mode';

jest.mock('@/utils/site-mode', () => ({
  ...jest.requireActual('@/utils/site-mode'),
  isMarketingSite: jest.fn(),
}));
jest.mock('next/head', () => { const H=({children}:{children:React.ReactNode})=><>{children}</>; H.displayName='H'; return H; });
jest.mock('next/router', () => ({ useRouter: () => ({ pathname:'/', asPath:'/', query:{}, push:jest.fn(), replace:jest.fn(), isReady:true }) }));

import HomePage from '@/pages/index';
import PowerCalculatorPage from '@/pages/power-calculator';
import DocsPage from '@/pages/docs/index';
import { AppShell } from '@/components/AppShell';

const mode = isMarketingSite as jest.Mock;

beforeEach(() => {
  localStorage.clear();
  mode.mockReset().mockReturnValue(true);
  // Every API call fails, as on the published site.
  global.fetch = jest.fn(() => Promise.reject(new Error('no API'))) as unknown as typeof fetch;
});

// The pages the marketing build actually ships, each as it is really wrapped:
// the homepage is `bare`, the other two are `open` and so sit in the shell.
const PAGES: Array<[string, () => React.ReactElement]> = [
  ['/', () => <HomePage />],
  ['/power-calculator', () => <AppShell><PowerCalculatorPage /></AppShell>],
  ['/docs', () => <AppShell><DocsPage /></AppShell>],
];

describe.each(PAGES)('%s on the marketing site', (name, make) => {
  it('links to nothing that 404s there', async () => {
    const { container } = render(<AuthProvider>{make()}</AuthProvider>);
    await waitFor(() => expect(container.querySelector('a, h1, h2')).toBeInTheDocument());

    const hrefs = Array.from(container.querySelectorAll('a[href]'))
      .map((a) => a.getAttribute('href') ?? '');

    const dead = hrefs.filter((h) =>
      PLATFORM_ONLY_PREFIXES.some((p) => h === `/${p}` || h.startsWith(`/${p}/`) || h.startsWith(`/${p}?`)),
    );
    expect({ page: name, dead }).toEqual({ page: name, dead: [] });
  });

  it('renders without reaching the API', async () => {
    render(<AuthProvider>{make()}</AuthProvider>);
    await waitFor(() => {
      const calls = (global.fetch as jest.Mock).mock.calls.map((c) => String(c[0]));
      // The auth probe is allowed: it is how the page learns it is anonymous,
      // and it fails closed to that. Nothing else may call the API.
      const other = calls.filter((u) => !u.includes('/auth/me'));
      expect({ page: name, other }).toEqual({ page: name, other: [] });
    });
  });
});
