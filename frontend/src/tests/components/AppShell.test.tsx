import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import {
  AppShell,
  MODULE_NAV_ITEMS,
  NAV_ITEMS,
  displayName,
  isNavActive,
  installedModuleNav,
} from '@/components/AppShell';
import { AuthProvider } from '@/contexts/AuthContext';
import { ModulesProvider, __resetModulesCache } from '@/contexts/ModulesContext';
import { CORE_PROFILE, MODULES, ModulesInfo } from '@/services/modules';
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

function full(overrides: Partial<ModulesInfo> = {}): ModulesInfo {
  return {
    profile: 'full',
    modules: [MODULES.WORKSPACES],
    version: '1.0.0',
    ...overrides,
  };
}

function renderShell(info: ModulesInfo = CORE_PROFILE) {
  return render(
    <ModulesProvider initial={info}>
      <AuthProvider>
        <AppShell>
          <div data-testid="page-content">page</div>
        </AppShell>
      </AuthProvider>
    </ModulesProvider>,
  );
}

beforeEach(() => {
  // The modules cache lives at module scope and outlives a test; an unseeded
  // provider in one test would otherwise reuse the previous test's answer.
  __resetModulesCache();
  mockFetch.mockReset();
  mockReplace.mockClear();
  localStorage.clear();
  mockPathname = '/experiments';
  mockAsPath = '/experiments';
});

describe('AppShell', () => {
  it('renders children and the wordmark, with no status pill on it', async () => {
    signInAs(makeUser());
    renderShell();
    expect(screen.getByTestId('page-content')).toBeInTheDocument();
    expect(screen.getByText('Experimently')).toBeInTheDocument();
    // The wordmark is the badge letter and the name, nothing appended.
    expect(screen.getByLabelText('Experimently home')).toHaveTextContent(/^EExperimently$/);
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

  describe('module chrome', () => {
    it('keeps the primary nav free of module routes', () => {
      expect(NAV_ITEMS.map((i) => i.href)).toEqual([
        '/experiments',
        '/feature-flags',
        '/admin',
        '/docs',
      ]);
    });

    it('offers a collapsed More group that is closed by default', async () => {
      signInAs(makeUser());
      renderShell();
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      const group = screen.getAllByTestId('more-nav-group')[0];
      expect(group).toBeInTheDocument();
      expect(group).not.toHaveAttribute('open');
      expect(group.querySelector('summary')).toHaveTextContent('More');
    });

    it('links to the modules guide in the core profile, and not in the full one', async () => {
      signInAs(makeUser());
      const view = renderShell();
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.getAllByTestId('nav-modules-docs')[0]).toHaveAttribute('href', '/docs/modules');
      expect(screen.getAllByTestId('nav-modules-docs')[0]).toHaveTextContent('Modules');
      view.unmount();

      localStorage.clear();
      mockFetch.mockReset();
      signInAs(makeUser());
      renderShell(full());
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.queryByTestId('nav-modules-docs')).not.toBeInTheDocument();
    });

    it('closes the More group when a link in it is followed, and on navigation', async () => {
      // _app.tsx keeps one AppShell across client-side navigations, so an
      // uncontrolled <details> stayed open -- a panel over the next page --
      // after any link inside it was clicked.
      signInAs(makeUser());
      renderShell(full());
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      const group = screen.getAllByTestId('more-nav-group')[0] as HTMLDetailsElement;

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

    it('closes the More group on an outside click and on Escape', async () => {
      signInAs(makeUser());
      renderShell(full());
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      const group = screen.getAllByTestId('more-nav-group')[0] as HTMLDetailsElement;

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

    it('carries no Workspaces link in the core profile', async () => {
      signInAs(makeUser());
      renderShell();
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.queryByTestId('nav-workspaces')).not.toBeInTheDocument();
    });

    it('adds the Workspaces link once the workspaces module is installed', async () => {
      signInAs(makeUser());
      renderShell(full());
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.getAllByTestId('nav-workspaces')[0]).toHaveAttribute('href', '/workspaces');
    });

    it('shows no More group at all in a full profile with no routed module installed', async () => {
      // A full instance whose installed modules carry no dashboard route has
      // nothing to put in the group, and an empty disclosure is noise.
      signInAs(makeUser());
      renderShell(full({ modules: [MODULES.HIPAA] }));
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.queryByTestId('more-nav-group')).not.toBeInTheDocument();
    });

    it('hides the More group while the modules are still being probed', async () => {
      // The provider's initial state is core, so an unseeded shell would
      // otherwise paint the "Modules" guide link on a full instance and swap
      // it for the routes when the probe resolved.
      mockFetch.mockImplementation((url: string) =>
        url.endsWith('/api/v1/modules')
          ? new Promise(() => {})
          : Promise.resolve(jsonResponse(200, makeUser())),
      );
      localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
      render(
        <ModulesProvider>
          <AuthProvider>
            <AppShell>
              <div data-testid="page-content">page</div>
            </AppShell>
          </AuthProvider>
        </ModulesProvider>,
      );
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      expect(screen.queryByTestId('more-nav-group')).not.toBeInTheDocument();
      expect(screen.queryByTestId('nav-modules-docs')).not.toBeInTheDocument();
    });

    it('shows no Modules guide link when the probe failed', async () => {
      // A failed probe also resolves to core, and the guide link says "this
      // instance runs the core profile" -- which the dashboard cannot know
      // when all that happened is that /api/v1/modules did not answer.
      mockFetch.mockImplementation((url: string) =>
        url.endsWith('/api/v1/modules')
          ? Promise.reject(new TypeError('Failed to fetch'))
          : Promise.resolve(jsonResponse(200, makeUser())),
      );
      localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
      render(
        <ModulesProvider>
          <AuthProvider>
            <AppShell>
              <div data-testid="page-content">page</div>
            </AppShell>
          </AuthProvider>
        </ModulesProvider>,
      );
      await waitFor(() => expect(screen.getByTestId('user-menu')).toBeInTheDocument());
      await waitFor(() =>
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/v1/modules'),
          expect.anything(),
        ),
      );
      expect(screen.queryByTestId('nav-modules-docs')).not.toBeInTheDocument();
      expect(screen.queryByTestId('more-nav-group')).not.toBeInTheDocument();
    });

    it('installedModuleNav lists exactly the routes whose module is installed', () => {
      expect(installedModuleNav(CORE_PROFILE)).toEqual([]);
      expect(installedModuleNav(full())).toHaveLength(MODULE_NAV_ITEMS.length);
      expect(installedModuleNav(full({ modules: ['hipaa'] }))).toEqual([]);
      expect(installedModuleNav(full({ profile: 'core' }))).toHaveLength(1);
      expect(MODULE_NAV_ITEMS.map((i) => i.href)).toEqual(['/workspaces']);
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
