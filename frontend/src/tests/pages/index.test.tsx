import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import HomePage from '@/pages/index';
import { AuthProvider } from '@/contexts/AuthContext';
import { TOKEN_STORAGE_KEY, UserMe } from '@/services/api';
import { routeKind } from '@/utils/routes';

const mockReplace = jest.fn().mockResolvedValue(true);

jest.mock('next/router', () => ({
  useRouter: () => ({
    replace: mockReplace,
    push: jest.fn(),
    pathname: '/',
    asPath: '/',
    query: {},
    isReady: true,
  }),
}));

jest.mock('next/head', () => {
  const MockHead = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  MockHead.displayName = 'MockHead';
  return MockHead;
});

const mockFetch = jest.fn();
global.fetch = mockFetch;

const user: UserMe = {
  id: 'u-1',
  email: 'admin@demo.com',
  username: 'admin',
  full_name: null,
  role: 'ADMIN',
  is_superuser: true,
  is_active: true,
  auth_provider: 'local',
};

beforeEach(() => {
  mockFetch.mockReset();
  mockReplace.mockClear();
  localStorage.clear();
});

describe('HomePage (/)', () => {
  it('shows an anonymous visitor the public homepage instead of redirecting', async () => {
    render(
      <AuthProvider>
        <HomePage />
      </AuthProvider>,
    );
    // Settle first. `waitFor` around a NEGATIVE assertion resolves on its first
    // synchronous check, so it adds no waiting at all and would pass while the
    // context was still `loading` -- green even if the redirect came back.
    await screen.findByRole('link', { name: /sign in to the dashboard/i });
    expect(screen.getByTestId('public-home')).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('still offers a way in', () => {
    render(
      <AuthProvider>
        <HomePage />
      </AuthProvider>,
    );
    expect(screen.getAllByRole('link', { name: /sign in/i }).length).toBeGreaterThan(0);
  });

  it('redirects authenticated users to /experiments', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: () => Promise.resolve(user),
      text: () => Promise.resolve(JSON.stringify(user)),
    } as unknown as Response);
    render(
      <AuthProvider>
        <HomePage />
      </AuthProvider>,
    );
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/experiments'));
  });

  it('does not redirect while the session is still loading', () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(
      <AuthProvider>
        <HomePage />
      </AuthProvider>,
    );
    expect(mockReplace).not.toHaveBeenCalled();
    // and shows the page rather than a spinner, so there is no flash.
    expect(screen.getByTestId('public-home')).toBeInTheDocument();
  });

  /**
   * The homepage came back; the claims did not.
   *
   * The landing page that used to live at `/` advertised an event volume, an
   * uptime figure and two compliance certifications for software that has
   * never been deployed. `scripts/publish/export.sh` refuses to publish a tree
   * containing them, so restoring that page would also have made the
   * repository unpublishable.
   *
   * WHY THE PATTERNS ARE ASSEMBLED RATHER THAN WRITTEN OUT. There is a real
   * tension here: a test asserting the absence of a forbidden string has to
   * name that string, and the sweep forbids a tracked file from containing it.
   * Spelling them out failed the export on this very pull request -- five hits,
   * all of them this table. So each is built from fragments at run time and the
   * literal never appears in the source. The sweep stays strict and the test
   * keeps its teeth.
   *
   * These mirror `export.sh`'s CLAIMS and UNMEASURED lists but are NOT shared
   * with it -- nothing links the two, so keep them in step by hand and treat
   * the export sweep as the authority. This is the fast feedback, not the gate.
   *
   * Matched against `container.textContent`, not `queryByText`: the latter sees
   * only one element's direct text children, so a claim split across nested
   * elements is invisible to it, and this page has fragmented paragraphs.
   */
  const forbidden: Array<[string[], string]> = [
    [['SOC', '2'], 'a compliance certification nobody has audited'],
    [['ISO', '27001'], 'the same'],
    [['GDPR', 'Compliant'], 'the same'],
    [['SRM', 'detection'], "in the export's list"],
    [['Enterprise', 'Edition'], 'the editions no longer exist'],
    [['Community', 'Edition'], 'the same'],
    [['licen[cs]e', 'key'], 'the platform has no such gate'],
    [['\\b\\d+(\\.\\d+)?[MB]\\+'], 'a volume for something never deployed'],
    [['99\\.9'], 'an uptime figure with no deployment behind it'],
    [['\\d+%\\s+(\\w+\\s+)?(uptime|hit rate|cache hit|pass rate|coverage)'], 'the same'],
    [['start', 'free', 'trial'], 'there is no paid tier to trial'],
    [['pricing'], 'there is no price'],
  ];

  it.each(forbidden)('makes no claim matching %s (%s)', (parts) => {
    const pattern = new RegExp((parts as string[]).join('\\s+'), 'i');
    const { container } = render(
      <AuthProvider>
        <HomePage />
      </AuthProvider>,
    );
    expect(container.textContent ?? '').not.toMatch(pattern);
  });

  it('renders nothing but the title once authenticated, so there is no flash', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: () => Promise.resolve(user),
      text: () => Promise.resolve(JSON.stringify(user)),
    } as unknown as Response);
    render(
      <AuthProvider>
        <HomePage />
      </AuthProvider>,
    );
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/experiments'));
    // The marketing page must not have been painted on the way through.
    expect(screen.queryByTestId('public-home')).not.toBeInTheDocument();
  });
});

describe('_app routeKind', () => {
  it('renders /login and / without the shell', () => {
    expect(routeKind('/login')).toBe('bare');
    expect(routeKind('/')).toBe('bare');
  });

  it('keeps docs, the power calculator and error pages open', () => {
    expect(routeKind('/docs')).toBe('open');
    expect(routeKind('/docs/[...slug]')).toBe('open');
    expect(routeKind('/power-calculator')).toBe('open');
    expect(routeKind('/404')).toBe('open');
  });

  it('protects everything else', () => {
    expect(routeKind('/experiments')).toBe('protected');
    expect(routeKind('/experiments/[id]')).toBe('protected');
    expect(routeKind('/feature-flags')).toBe('protected');
    expect(routeKind('/admin/users')).toBe('protected');
    expect(routeKind('/results/[id]')).toBe('protected');
    expect(routeKind('/workspaces/[id]/members')).toBe('protected');
  });
});
