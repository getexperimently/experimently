/**
 * The SSO part of `/login` (C2b spec-v3 §11): shown only when the API lists
 * the `sso` module; `/login?sso_error=` copy in the page's own alert, the SSO
 * form open, the parameters removed from the address bar.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import LoginPage from '@/pages/login';
import { AuthProvider } from '@/contexts/AuthContext';
import { ModulesProvider } from '@/contexts/ModulesContext';
import { navigation } from '@/services/api';
import { SSO_STORAGE_KEY } from '@modules/services/sso';


const mockReplace = jest.fn().mockResolvedValue(true);
let mockQuery: Record<string, string> = {};

jest.mock('next/router', () => ({
  useRouter: () => ({
    replace: mockReplace,
    push: jest.fn(),
    pathname: '/login',
    asPath: '/login',
    query: mockQuery,
    isReady: true,
  }),
}));

jest.mock('next/head', () => {
  const MockHead = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  MockHead.displayName = 'MockHead';
  return MockHead;
});

global.fetch = jest.fn();

function renderLogin(modules: string[]) {
  return render(
    <ModulesProvider initial={{ profile: 'full', modules, version: 'test' }}>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </ModulesProvider>,
  );
}

beforeEach(() => {
  mockQuery = {};
  mockReplace.mockClear();
  window.sessionStorage.clear();
  window.history.replaceState(null, '', '/login');
});

describe('Sign in with SSO', () => {
  it('is offered only when the API lists the sso module', () => {
    const { unmount } = renderLogin([]);
    expect(screen.queryByTestId('sso-open')).not.toBeInTheDocument();
    unmount();
    renderLogin(['sso']);
    expect(screen.getByTestId('sso-open')).toHaveTextContent('Sign in with SSO');
  });

  it('asks for the work email and navigates with location.assign, not a form post', async () => {
    const assign = jest.spyOn(navigation, 'assign').mockImplementation(() => undefined);
    mockQuery = { next: '/feature-flags' };
    renderLogin(['sso']);
    fireEvent.click(screen.getByTestId('sso-open'));
    const form = screen.getByTestId('sso-form');
    expect(form).not.toHaveAttribute('action');
    await waitFor(() => expect(screen.getByTestId('sso-email')).toHaveFocus());
    fireEvent.change(screen.getByTestId('sso-email'), { target: { value: 'me@acme.com' } });
    fireEvent.click(screen.getByTestId('sso-submit'));
    await waitFor(() => expect(assign).toHaveBeenCalledTimes(1));
    expect(assign.mock.calls[0][0]).toMatch(/^\/api\/v1\/auth\/sso\/login\?domain=acme\.com&/);
    expect(JSON.parse(window.sessionStorage.getItem(SSO_STORAGE_KEY)!).next).toBe('/feature-flags');
    assign.mockRestore();
  });

  it('shows /login?sso_error copy in the alert, opens the form, and cleans the URL', async () => {
    window.history.replaceState(null, '', '/login?sso_error=sso_idp_error&provider=okta&idp_error=access_denied');
    mockQuery = { sso_error: 'sso_idp_error', provider: 'okta', idp_error: 'access_denied' };
    renderLogin(['sso']);
    expect(await screen.findByTestId('login-error')).toHaveTextContent(
      'Okta did not complete the sign-in (access_denied). If you expected access, contact your administrator.',
    );
    expect(screen.getByTestId('sso-form')).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe('/login');
    await waitFor(() => expect(screen.getByTestId('sso-email')).toHaveFocus());

    // "Start sign-in again" re-focuses the SSO form's email.
    (document.activeElement as HTMLElement | null)?.blur();
    fireEvent.click(screen.getByTestId('sso-retry'));
    await waitFor(() => expect(screen.getByTestId('sso-email')).toHaveFocus());
  });

  it('uses the domain kept at sign-in for the copy, and forgets the secret', async () => {
    window.sessionStorage.setItem(
      SSO_STORAGE_KEY,
      JSON.stringify({ secret: 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8', next: '/x', domain: 'acme.com' }),
    );
    mockQuery = { sso_error: 'sso_not_configured' };
    renderLogin(['sso']);
    expect(await screen.findByTestId('login-error')).toHaveTextContent(
      "Single sign-on isn't set up for acme.com.",
    );
    expect(window.sessionStorage.getItem(SSO_STORAGE_KEY)).toBeNull();
  });

  it('shows the copy even before the modules answer has arrived', async () => {
    mockQuery = { sso_error: 'sso_expired' };
    renderLogin([]);
    expect(await screen.findByTestId('login-error')).toHaveTextContent(
      'Your sign-in took too long and expired. Start again.',
    );
  });

  it('uses C1b copy for the exchange 429', async () => {
    mockQuery = { sso_error: 'sso_rate_limited' };
    renderLogin(['sso']);
    expect(await screen.findByTestId('login-error')).toHaveTextContent(
      'Too many attempts. Please wait a moment and try again.',
    );
  });
});
