/**
 * The shell wraps every `open` route -- /docs and /power-calculator -- so on
 * the marketing site it is what a visitor sees on every page but the homepage.
 *
 * It rendered "Experiments", "Feature Flags" and a "Sign in" button there. All
 * three 404: the marketing build prunes those routes and there is no API to
 * sign in to. The homepage was fixed first and this was missed, because the
 * button is rendered CLIENT-SIDE once auth resolves to anonymous, so it never
 * appears in the static HTML a curl returns. Checking the built file said
 * "clean" while the rendered page showed the button.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { AppShell } from '@/components/AppShell';
import { AuthProvider } from '@/contexts/AuthContext';
import { isMarketingSite } from '@/utils/site-mode';

jest.mock('@/utils/site-mode', () => ({
  ...jest.requireActual('@/utils/site-mode'),
  isMarketingSite: jest.fn(),
}));
jest.mock('next/router', () => ({ useRouter: () => ({ pathname:'/power-calculator', asPath:'/power-calculator', query:{}, push:jest.fn(), replace:jest.fn(), isReady:true }) }));

const mode = isMarketingSite as jest.Mock;
const show = () => render(<AuthProvider><AppShell><p>page</p></AppShell></AuthProvider>);

beforeEach(() => {
  localStorage.clear();
  mode.mockReset();
  global.fetch = jest.fn(() => Promise.reject(new Error('no API'))) as unknown as typeof fetch;
});

describe('marketing build', () => {
  beforeEach(() => mode.mockReturnValue(true));

  it('shows no sign-in, because there is nothing to sign in to', async () => {
    const { container } = show();
    await waitFor(() => expect(screen.getByText('page')).toBeInTheDocument());
    expect(screen.queryByTestId('nav-sign-in')).toBeNull();
    expect(container.querySelectorAll('a[href^="/login"]')).toHaveLength(0);
  });

  it('offers Source instead', async () => {
    show();
    await waitFor(() => expect(screen.getByTestId('nav-source')).toBeInTheDocument());
  });

  it('shows no link to a route it pruned', async () => {
    const { container } = show();
    await waitFor(() => expect(screen.getByText('page')).toBeInTheDocument());
    for (const dead of ['/experiments', '/feature-flags', '/admin', '/results', '/workspaces']) {
      expect(container.querySelectorAll(`a[href^="${dead}"]`)).toHaveLength(0);
    }
  });

  it('keeps the docs link, which works', async () => {
    const { container } = show();
    await waitFor(() => expect(container.querySelector('a[href="/docs"]')).toBeInTheDocument());
  });
});

describe('platform build', () => {
  beforeEach(() => mode.mockReturnValue(false));

  it('keeps sign-in and the dashboard nav', async () => {
    const { container } = show();
    await waitFor(() => expect(screen.getByTestId('nav-sign-in')).toBeInTheDocument());
    expect(container.querySelector('a[href="/experiments"]')).toBeInTheDocument();
    expect(container.querySelector('a[href="/feature-flags"]')).toBeInTheDocument();
  });
});
