/**
 * `/sso/complete` (C2b spec-v3 §11): one exchange per page load, even under
 * React StrictMode, and every outcome lands somewhere with its copy.
 */
import React, { StrictMode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { AuthProvider } from '@/contexts/AuthContext';
import { ModulesProvider } from '@/contexts/ModulesContext';
import { TOKEN_STORAGE_KEY } from '@/services/api';
import SsoCompletePage, { __resetSsoCompleteLatch } from '@modules/pages/sso/complete';
import { SSO_STORAGE_KEY } from '@modules/services/sso';

const mockReplace = jest.fn().mockResolvedValue(true);

jest.mock('next/router', () => ({
  useRouter: () => ({
    replace: mockReplace,
    push: jest.fn(),
    pathname: '/sso/complete',
    asPath: '/sso/complete',
    query: {},
    isReady: true,
  }),
}));

jest.mock('next/head', () => {
  const MockHead = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  MockHead.displayName = 'MockHead';
  return MockHead;
});

const SECRET = 'AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8';
const CODE = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1In0.c2ln';

const user = {
  id: 'u-1',
  email: 'me@acme.com',
  username: 'me',
  full_name: null,
  role: 'VIEWER',
  is_superuser: false,
  is_active: true,
  auth_provider: 'local',
};

function response(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  const lower: Record<string, string> = { 'content-type': 'application/json' };
  for (const [k, v] of Object.entries(headers)) lower[k.toLowerCase()] = v;
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'STATUS',
    headers: { get: (name: string) => lower[name.toLowerCase()] ?? null },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  } as unknown as Response;
}

const mockFetch = jest.fn();
global.fetch = mockFetch;

function exchangeCalls() {
  return mockFetch.mock.calls.filter(([url]) => String(url).includes('/api/v1/auth/sso/exchange'));
}

/** `/api/v1/auth/me` for the refresh after sign-in; the exchange as given. */
function routeFetch(exchange: () => Promise<Response>) {
  mockFetch.mockImplementation((url: string) => {
    if (String(url).includes('/api/v1/auth/sso/exchange')) return exchange();
    if (String(url).includes('/api/v1/auth/me')) return Promise.resolve(response(200, user));
    return Promise.resolve(response(404, { detail: 'not found' }));
  });
}

function renderPage({ strict = true } = {}) {
  const tree = (
    <ModulesProvider initial={{ profile: 'full', modules: ['sso'], version: 'test' }}>
      <AuthProvider>
        <SsoCompletePage />
      </AuthProvider>
    </ModulesProvider>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}

function arrive(hash: string, pending: object | null = { secret: SECRET, next: '/feature-flags', domain: 'acme.com' }) {
  window.history.replaceState(null, '', `/sso/complete${hash}`);
  if (pending) window.sessionStorage.setItem(SSO_STORAGE_KEY, JSON.stringify(pending));
}

beforeEach(() => {
  __resetSsoCompleteLatch();
  mockFetch.mockReset();
  mockReplace.mockClear();
  window.sessionStorage.clear();
  window.localStorage.clear();
});

describe('/sso/complete', () => {
  it('exchanges exactly once under StrictMode and lands on next, signed in', async () => {
    routeFetch(() =>
      Promise.resolve(response(200, { access_token: 'tok-1', token_type: 'bearer', user })),
    );
    arrive(`#code=${CODE}`);
    renderPage({ strict: true });

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/feature-flags'));
    expect(exchangeCalls()).toHaveLength(1);
    const [, init] = exchangeCalls()[0];
    expect(JSON.parse(init.body)).toEqual({ code: CODE, secret: SECRET });
    expect(mockReplace).toHaveBeenCalledTimes(1);
    expect(mockReplace).not.toHaveBeenCalledWith(expect.stringContaining('sso_error'));
    expect(window.localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('tok-1');
    expect(window.sessionStorage.getItem(SSO_STORAGE_KEY)).toBeNull();
  });

  it('takes the fragment out of the address bar before anything else', async () => {
    routeFetch(() => new Promise(() => undefined));
    arrive(`#code=${CODE}`);
    renderPage();
    await waitFor(() => expect(exchangeCalls()).toHaveLength(1));
    expect(window.location.hash).toBe('');
    expect(window.location.pathname).toBe('/sso/complete');
    expect(screen.getByTestId('sso-complete')).toHaveTextContent('Signing you in');
  });

  it.each([
    ['a refused exchange', () => Promise.resolve(response(400, { detail: 'x' })), '/login?sso_error=sso_state'],
    [
      'a 5xx, with its request id',
      () => Promise.resolve(response(503, { detail: 'x' }, { 'X-Request-ID': 'req-5' })),
      '/login?sso_error=sso_failed&request_id=req-5',
    ],
    ['a 429', () => Promise.resolve(response(429, { detail: 'slow down' })), '/login?sso_error=sso_rate_limited'],
    ['an unreachable API', () => Promise.reject(new TypeError('Failed to fetch')), '/login?sso_error=sso_unreachable'],
  ])('sends %s to /login with its code', async (_label, exchange, expected) => {
    routeFetch(exchange);
    arrive(`#code=${CODE}`);
    renderPage();
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith(expected));
    expect(exchangeCalls()).toHaveLength(1);
    expect(window.localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
  });

  it.each([
    ['no fragment', '', { secret: SECRET, next: '/', domain: 'd' }],
    ['a fragment that is not a code', '#token=abc', { secret: SECRET, next: '/', domain: 'd' }],
    ['no secret in this tab', `#code=${CODE}`, null],
  ])('with %s, sends sso_state without asking the API', async (_label, hash, pending) => {
    routeFetch(() => Promise.resolve(response(200, {})));
    arrive(hash, pending);
    renderPage();
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login?sso_error=sso_state'));
    expect(exchangeCalls()).toHaveLength(0);
  });

  it('never lands on a next that leaves the dashboard', async () => {
    routeFetch(() =>
      Promise.resolve(response(200, { access_token: 'tok-2', token_type: 'bearer', user })),
    );
    arrive(`#code=${CODE}`, { secret: SECRET, next: '//evil.example', domain: 'acme.com' });
    renderPage();
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/experiments'));
  });
});
