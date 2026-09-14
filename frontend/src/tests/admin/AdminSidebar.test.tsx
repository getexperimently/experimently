import React from 'react';
import { render, screen } from '@testing-library/react';
import { AdminSidebar, NAV_ITEMS, visibleNavItems } from '@/components/admin/AdminSidebar';
import { ModulesProvider, __resetModulesCache } from '@/contexts/ModulesContext';
import { CORE_PROFILE, MODULES, ModulesInfo, ModulesService } from '@/services/modules';
import { MODULES_DOC_PATH } from '@/services/modules';

// Only `ModulesService.get` is replaced; MODULES, CORE_PROFILE and the rest
// stay real. The seeded providers below never call it.
jest.mock('@/services/modules', () => {
  const actual = jest.requireActual('@/services/modules');
  return { ...actual, ModulesService: { get: jest.fn() } };
});

const mockGet = ModulesService.get as jest.Mock;

beforeEach(() => {
  __resetModulesCache();
  mockGet.mockReset();
});

// Mock Next.js Link — forward all props so data-testid and className reach the <a>
jest.mock('next/link', () => {
  const MockLink = ({
    children,
    href,
    ...rest
  }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...rest}>{children}</a>
  );
  MockLink.displayName = 'MockLink';
  return MockLink;
});

function full(overrides: Partial<ModulesInfo> = {}): ModulesInfo {
  return {
    profile: 'full',
    modules: [MODULES.RBAC],
    version: '1.0.0',
    ...overrides,
  };
}

/** Render with a seeded answer; `ModulesProvider` makes no request when seeded. */
function renderSidebar(currentPath = '/admin', info: ModulesInfo = CORE_PROFILE) {
  return render(
    <ModulesProvider initial={info}>
      <AdminSidebar currentPath={currentPath} />
    </ModulesProvider>,
  );
}

describe('AdminSidebar', () => {
  it('renders every core nav item', () => {
    renderSidebar();
    expect(screen.getByText(/dashboard/i)).toBeInTheDocument();
    expect(screen.getByText(/users/i)).toBeInTheDocument();
    expect(screen.getByText(/audit log/i)).toBeInTheDocument();
    expect(screen.getByText(/safety/i)).toBeInTheDocument();
    expect(screen.getByText(/scheduler/i)).toBeInTheDocument();
    expect(screen.getByText(/api keys/i)).toBeInTheDocument();
    expect(screen.getByText(/notifications/i)).toBeInTheDocument();
  });

  it('highlights active item based on currentPath', () => {
    renderSidebar('/admin/users');
    const usersLink = screen.getByTestId('nav-item-users');
    expect(usersLink).toHaveClass('bg-blue-50');
    expect(usersLink).toHaveClass('text-blue-700');
  });

  it('core nav items have correct href attributes', () => {
    renderSidebar();
    expect(screen.getByRole('link', { name: /dashboard/i })).toHaveAttribute('href', '/admin');
    expect(screen.getByRole('link', { name: /users/i })).toHaveAttribute('href', '/admin/users');
    expect(screen.getByRole('link', { name: /audit log/i })).toHaveAttribute('href', '/admin/audit');
    expect(screen.getByRole('link', { name: /safety/i })).toHaveAttribute('href', '/admin/safety');
    expect(screen.getByRole('link', { name: /scheduler/i })).toHaveAttribute('href', '/admin/scheduler');
    expect(screen.getByRole('link', { name: /api keys/i })).toHaveAttribute('href', '/admin/api-keys');
  });

  it('renders with data-testid', () => {
    renderSidebar();
    expect(screen.getByTestId('admin-sidebar')).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Module gating — `/admin/roles` belongs to the rbac module
  // -------------------------------------------------------------------------

  describe('Roles (rbac module)', () => {
    it('is absent in the core profile', () => {
      renderSidebar();
      expect(screen.queryByTestId('nav-item-roles')).not.toBeInTheDocument();
      expect(screen.queryByRole('link', { name: /roles/i })).not.toBeInTheDocument();
    });

    it('is present when the rbac module is installed', () => {
      renderSidebar('/admin', full());
      expect(screen.getByTestId('nav-item-roles')).toHaveAttribute('href', '/admin/roles');
    });

    it('is absent when the full profile does not list rbac', () => {
      renderSidebar('/admin', full({ modules: ['hipaa'] }));
      expect(screen.queryByTestId('nav-item-roles')).not.toBeInTheDocument();
    });

    it('is absent with no ModulesProvider at all (the unreachable-backend default)', () => {
      render(<AdminSidebar currentPath="/admin" />);
      expect(screen.queryByTestId('nav-item-roles')).not.toBeInTheDocument();
      expect(screen.getByTestId('nav-item-users')).toBeInTheDocument();
    });
  });

  describe('the hidden-pages note', () => {
    it('says one admin page belongs to a module that is not installed, and links to the guide', () => {
      renderSidebar();
      const note = screen.getByTestId('admin-sidebar-modules-note');
      expect(note).toHaveTextContent('One admin page belongs to a module that is not installed.');
      expect(screen.getByRole('link', { name: 'Modules' })).toHaveAttribute('href', MODULES_DOC_PATH);
    });

    it('is absent once every module page is installed', () => {
      renderSidebar('/admin', full());
      expect(screen.queryByTestId('admin-sidebar-modules-note')).not.toBeInTheDocument();
    });

    it('is absent while the modules are still being probed', () => {
      // An unseeded provider is loading until /api/v1/modules answers; the
      // note must not flash on a full-profile instance in the meantime.
      mockGet.mockReturnValue(new Promise(() => {}));
      render(
        <ModulesProvider>
          <AdminSidebar currentPath="/admin" />
        </ModulesProvider>,
      );
      expect(screen.queryByTestId('admin-sidebar-modules-note')).not.toBeInTheDocument();
      expect(screen.queryByTestId('nav-item-roles')).not.toBeInTheDocument();
      expect(screen.getByTestId('nav-item-users')).toBeInTheDocument();
    });

    it('is absent when the probe failed, which is not the same as not installed', async () => {
      // A failed probe resolves to the core profile, so the count would come
      // out at 1 and the note would tell an operator running rbac that an
      // admin page belongs to a module they do not have. All that happened is
      // that the API did not answer.
      mockGet.mockRejectedValue(new TypeError('Failed to fetch'));
      render(
        <ModulesProvider>
          <AdminSidebar currentPath="/admin" />
        </ModulesProvider>,
      );
      const failed = await screen.findByTestId('admin-sidebar-modules-error');
      expect(failed).toHaveTextContent('could not reach the API');
      expect(screen.queryByTestId('admin-sidebar-modules-note')).not.toBeInTheDocument();
      // The links still stay hidden: the dashboard must not hard-link a route
      // it has no evidence this instance serves.
      expect(screen.queryByTestId('nav-item-roles')).not.toBeInTheDocument();
      expect(screen.getByTestId('nav-item-users')).toBeInTheDocument();
    });

    it('shows no probe-failure note when the answer did arrive', () => {
      renderSidebar();
      expect(screen.getByTestId('admin-sidebar-modules-note')).toBeInTheDocument();
      expect(screen.queryByTestId('admin-sidebar-modules-error')).not.toBeInTheDocument();
    });
  });

  describe('visibleNavItems', () => {
    it('drops exactly the module items in the core profile', () => {
      const visible = visibleNavItems(CORE_PROFILE);
      expect(visible).toHaveLength(NAV_ITEMS.length - 1);
      expect(visible.map((i) => i.href)).not.toContain('/admin/roles');
    });

    it('keeps every item when their modules are installed', () => {
      expect(visibleNavItems(full())).toHaveLength(NAV_ITEMS.length);
    });

    it('marks only /admin/roles as a module page', () => {
      expect(NAV_ITEMS.filter((i) => i.module).map((i) => i.href)).toEqual(['/admin/roles']);
    });
  });
});
