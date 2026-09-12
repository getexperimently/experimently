import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import {
  AppShell,
  ENTERPRISE_NAV_ITEMS,
  NAV_ITEMS,
  displayName,
  isNavActive,
  licensedEnterpriseNav,
} from '@/components/AppShell';
import { AuthProvider } from '@/contexts/AuthContext';
import { EditionProvider } from '@/contexts/EditionContext';
import { COMMUNITY_EDITION, EditionInfo, FEATURES } from '@/services/edition';
import { TOKEN_STORAGE_KEY, UserMe } from '@/services/api';

const mockReplace = jest.fn().mockResolvedValue(true);
let mockPathname = '/experiments';
let mockAsPath = '/experiments';

// A tiny router event bus so tests can fire `routeChangeStart` the way Next
// does on a client-side navigation.
const routerListeners: Record<string, Array<() => void>> = {};
const mockRouterEvents = {
  on: (event: string, cb: () => void) => {
    (routerListeners[event] ??= []).push(cb);
  },
  off: (event: string, cb: () => void) => {
    routerListeners[event] = (routerListeners[event] ?? []).filter((c) => c !== cb);
  },
  emit: (event: string) => {
    (routerListeners[event] ?? []).forEach((cb) => cb());
  },
};

jest.mock('next/router', () => ({
  useRouter: () => ({
    replace: mockReplace,
    push: jest.fn(),
    pathname: mockPathname,
    asPath: mockAsPath,
    query: {},
    isReady: true,
    events: mockRouterEvents,
  }),
}));

jest.mock('next/link', () => {
  const MockLink = ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  );
  MockLink.displayName = 'MockLink';
  return MockLink;
});

const mockFetch = jest.fn();
global.fetch = mockFetch;

function makeUser(overrides: Partial<UserMe> = {}): UserMe {
  return {
    id: 'u-1',
    email: 'admin@demo.com',
    username: 'admin',
    full_name: 'Demo Admin',
    role: 'ADMIN',
    is_superuser: true,
    is_active: true,
    auth_provider: 'local',
    ...overrides,
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(body === undefined ? '' : JSON.stringify(body)),
  } as unknown as Response;
}

function signInAs(user: UserMe) {
  localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
  mockFetch.mockResolvedValueOnce(jsonResponse(200, user));
}

function enterprise(overrides: Partial<EditionInfo> = {}): EditionInfo {
  return {
    edition: 'enterprise',
    features: [FEATURES.WORKSPACES],
    status: 'active',
    expires_at: '2026-09-12T00:00:00Z',
    version: '1.0.0',
    ...overrides,
  };
}

function renderShell(edition: EditionInfo = COMMUNITY_EDITION) {
  return render(
    <EditionProvider initial={edition}>
      <AuthProvider>
        <AppShell>
          <div data-testid="page-content">page</div>
        </AppShell>
      </AuthProvider>
    </EditionProvider>,
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  mockReplace.mockClear();
  localStorage.clear();
  mockPathname = '/experiments';
  mockAsPath = '/experiments';
});

describe('AppShell', () => {
  it('renders children, the wordmark and the edition pill', async () => {
    signInAs(makeUser());
    renderShell();
    expect(screen.getByTestId('page-content')).toBeInTheDocument();
    expect(screen.getByText('Experimently')).toBeInTheDocument();
    expect(screen.getByTestId('edition-pill')).toHaveTextContent('CE');
    await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
  });

  it('shows Experiments, Feature Flags, Admin and Docs for an ADMIN', async () => {
    signInAs(makeUser());
    renderShell();
    await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
    const nav = screen.getByRole('navigation', { name: 'Primary' });
    expect(nav).toHaveTextContent('Experiments');
    expect(nav).toHaveTextContent('Feature Flags');
    expect(nav).toHaveTextContent('Admin');
    expect(nav).toHaveTextContent('Docs');
    expect(screen.getByTestId('nav-admin')).toHaveAttribute('href', '/admin');
    expect(screen.getByTestId('nav-experiments')).toHaveAttribute('aria-current', 'page');
  });

  it('shows Admin for a DEVELOPER but hides it for ANALYST and VIEWER', async () => {
    signInAs(makeUser({ role: 'DEVELOPER' }));
    const { unmount } = renderShell();
    await waitFor(() => expect(screen.getByTestId('nav-admin')).toBeInTheDocument());
    unmount();

    for (const role of ['ANALYST', 'VIEWER'] as const) {
      localStorage.clear();
      mockFetch.mockReset();
      signInAs(makeUser({ role }));
      const view = renderShell();
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.queryByTestId('nav-admin')).not.toBeInTheDocument();
      expect(screen.getByTestId('nav-docs')).toBeInTheDocument();
      view.unmount();
    }
  });

  it('shows the user name, role chip and a visible Log out button', async () => {
    signInAs(makeUser({ full_name: 'Ada Lovelace', role: 'ADMIN' }));
    renderShell();
    await waitFor(() => expect(screen.getByTestId('user-menu-name')).toHaveTextContent('Ada Lovelace'));
    expect(screen.getByTestId('user-menu-role')).toHaveTextContent('Admin');
    expect(screen.getByRole('button', { name: 'Log out' })).toBeVisible();
  });

  it('falls back to username when full_name is empty', () => {
    expect(displayName(makeUser({ full_name: null }))).toBe('admin');
    expect(displayName(makeUser({ full_name: '  ' }))).toBe('admin');
    expect(displayName(makeUser({ full_name: null, username: '' }))).toBe('admin@demo.com');
  });

  it('logs out and navigates to /login', async () => {
    signInAs(makeUser());
    mockFetch.mockResolvedValueOnce(jsonResponse(204, undefined));
    renderShell();
    await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Log out' }));
    });

    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login'));
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull();
    expect(mockFetch.mock.calls[1][0]).toBe('/api/v1/auth/logout');
  });

  it('shows a Sign in link carrying ?next= for anonymous visitors on open pages', async () => {
    mockPathname = '/docs/[...slug]';
    mockAsPath = '/docs/quick-start';
    renderShell();
    await waitFor(() => expect(screen.getByTestId('nav-sign-in')).toBeInTheDocument());
    expect(screen.getByTestId('nav-sign-in')).toHaveAttribute('href', '/login?next=%2Fdocs%2Fquick-start');
    expect(screen.queryByTestId('nav-admin')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Log out' })).not.toBeInTheDocument();
  });

  it('shows a placeholder while the session loads', () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockFetch.mockImplementation(() => new Promise(() => {}));
    renderShell();
    expect(screen.getByTestId('user-menu-loading')).toBeInTheDocument();
  });

  it('toggles the mobile navigation', async () => {
    signInAs(makeUser());
    renderShell();
    await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
    expect(screen.queryByTestId('mobile-nav')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('mobile-nav-toggle'));
    expect(screen.getByTestId('mobile-nav')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('mobile-nav-toggle'));
    expect(screen.queryByTestId('mobile-nav')).not.toBeInTheDocument();
  });

  describe('edition chrome', () => {
    it('reflects the real edition in the pill', async () => {
      signInAs(makeUser());
      renderShell(enterprise());
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.getByTestId('edition-pill')).toHaveTextContent('EE');
    });

    it('shows the grace banner inside the shell', async () => {
      signInAs(makeUser());
      renderShell(enterprise({ status: 'grace' }));
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.getByTestId('edition-banner')).toHaveAttribute('data-status', 'grace');
    });

    it('shows no banner on an active licence or in Community', async () => {
      signInAs(makeUser());
      const view = renderShell(enterprise());
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.queryByTestId('edition-banner')).not.toBeInTheDocument();
      view.unmount();

      localStorage.clear();
      mockFetch.mockReset();
      signInAs(makeUser());
      renderShell();
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.queryByTestId('edition-banner')).not.toBeInTheDocument();
    });

    it('keeps the primary nav free of Enterprise routes', () => {
      expect(NAV_ITEMS.map((i) => i.href)).toEqual([
        '/experiments',
        '/feature-flags',
        '/admin',
        '/docs',
      ]);
    });

    it('offers a collapsed Enterprise group that is closed by default', async () => {
      signInAs(makeUser());
      renderShell();
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      const group = screen.getAllByTestId('enterprise-nav-group')[0];
      expect(group).toBeInTheDocument();
      expect(group).not.toHaveAttribute('open');
      expect(screen.getAllByTestId('nav-editions-docs')[0]).toHaveAttribute(
        'href',
        '/docs/editions',
      );
    });

    it('closes the Enterprise group when a link in it is followed, and on navigation', async () => {
      // _app.tsx keeps one AppShell across client-side navigations, so an
      // uncontrolled <details> stayed open -- a panel over the next page --
      // after any link inside it was clicked.
      signInAs(makeUser());
      renderShell(enterprise());
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      const group = screen.getAllByTestId('enterprise-nav-group')[0] as HTMLDetailsElement;

      fireEvent.click(group.querySelector('summary')!);
      await waitFor(() => expect(group).toHaveAttribute('open'));

      fireEvent.click(screen.getAllByTestId('nav-workspaces')[0]);
      await waitFor(() => expect(group).not.toHaveAttribute('open'));

      // Opened again, then a navigation started elsewhere (browser back, say).
      fireEvent.click(group.querySelector('summary')!);
      await waitFor(() => expect(group).toHaveAttribute('open'));
      act(() => mockRouterEvents.emit('routeChangeStart'));
      await waitFor(() => expect(group).not.toHaveAttribute('open'));
    });

    it('closes the Enterprise group on an outside click and on Escape', async () => {
      signInAs(makeUser());
      renderShell(enterprise());
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      const group = screen.getAllByTestId('enterprise-nav-group')[0] as HTMLDetailsElement;

      fireEvent.click(group.querySelector('summary')!);
      await act(async () => {
        await new Promise((r) => setTimeout(r, 0)); // let the queued toggle land
      });
      expect(group).toHaveAttribute('open');
      fireEvent.mouseDown(document.body);
      await waitFor(() => expect(group).not.toHaveAttribute('open'));

      fireEvent.click(group.querySelector('summary')!);
      await act(async () => {
        await new Promise((r) => setTimeout(r, 0));
      });
      expect(group).toHaveAttribute('open');
      fireEvent.keyDown(document, { key: 'Escape' });
      await waitFor(() => expect(group).not.toHaveAttribute('open'));
    });

    it('carries no Workspaces link in Community', async () => {
      signInAs(makeUser());
      renderShell();
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.queryByTestId('nav-workspaces')).not.toBeInTheDocument();
    });

    it('adds the Workspaces link once the licence allows it', async () => {
      signInAs(makeUser());
      renderShell(enterprise());
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.getAllByTestId('nav-workspaces')[0]).toHaveAttribute('href', '/workspaces');
    });

    it('licensedEnterpriseNav gates on the licence state, not just the edition', () => {
      expect(licensedEnterpriseNav(COMMUNITY_EDITION)).toEqual([]);
      expect(licensedEnterpriseNav(enterprise())).toHaveLength(ENTERPRISE_NAV_ITEMS.length);
      expect(licensedEnterpriseNav(enterprise({ status: 'grace' }))).toHaveLength(1);
      expect(licensedEnterpriseNav(enterprise({ status: 'expired' }))).toEqual([]);
      expect(licensedEnterpriseNav(enterprise({ status: 'invalid' }))).toEqual([]);
      expect(licensedEnterpriseNav(enterprise({ features: ['hipaa'] }))).toEqual([]);
    });
  });

  it('isNavActive matches exact and nested paths only', () => {
    expect(isNavActive('/experiments', '/experiments')).toBe(true);
    expect(isNavActive('/experiments/[id]', '/experiments')).toBe(true);
    expect(isNavActive('/experiments-archive', '/experiments')).toBe(false);
    expect(isNavActive('/feature-flags', '/experiments')).toBe(false);
    expect(NAV_ITEMS.map((i) => i.label)).toEqual(['Experiments', 'Feature Flags', 'Admin', 'Docs']);
  });
});
