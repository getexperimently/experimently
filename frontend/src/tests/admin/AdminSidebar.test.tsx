import React from 'react';
import { render, screen } from '@testing-library/react';
import { AdminSidebar, NAV_ITEMS, visibleNavItems } from '@/components/admin/AdminSidebar';
import { EditionProvider } from '@/contexts/EditionContext';
import { COMMUNITY_EDITION, EditionInfo, FEATURES } from '@/services/edition';

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

function licensed(overrides: Partial<EditionInfo> = {}): EditionInfo {
  return {
    edition: 'enterprise',
    features: [FEATURES.RBAC],
    status: 'active',
    expires_at: '2027-01-01T00:00:00Z',
    version: '1.0.0',
    ...overrides,
  };
}

/** Render with a seeded edition; `EditionProvider` makes no request when seeded. */
function renderSidebar(currentPath = '/admin', edition: EditionInfo = COMMUNITY_EDITION) {
  return render(
    <EditionProvider initial={edition}>
      <AdminSidebar currentPath={currentPath} />
    </EditionProvider>,
  );
}

describe('AdminSidebar', () => {
  it('renders every Community nav item', () => {
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

  it('Community nav items have correct href attributes', () => {
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
  // Edition gating — `/admin/roles` is an Enterprise route
  // (docs/planning/ee-coupling-report.md §6)
  // -------------------------------------------------------------------------

  describe('Roles (Enterprise)', () => {
    it('is absent in Community', () => {
      renderSidebar();
      expect(screen.queryByTestId('nav-item-roles')).not.toBeInTheDocument();
      expect(screen.queryByRole('link', { name: /roles/i })).not.toBeInTheDocument();
    });

    it('is present with an active licence that names rbac', () => {
      renderSidebar('/admin', licensed());
      expect(screen.getByTestId('nav-item-roles')).toHaveAttribute('href', '/admin/roles');
    });

    it('is present under a wildcard licence', () => {
      renderSidebar('/admin', licensed({ features: ['*'] }));
      expect(screen.getByTestId('nav-item-roles')).toBeInTheDocument();
    });

    it('is present during the grace period', () => {
      renderSidebar('/admin', licensed({ status: 'grace' }));
      expect(screen.getByTestId('nav-item-roles')).toBeInTheDocument();
    });

    it.each(['expired', 'invalid'] as const)('is absent when the licence is %s', (status) => {
      renderSidebar('/admin', licensed({ status }));
      expect(screen.queryByTestId('nav-item-roles')).not.toBeInTheDocument();
    });

    it('is absent when the licence does not name rbac', () => {
      renderSidebar('/admin', licensed({ features: ['hipaa'] }));
      expect(screen.queryByTestId('nav-item-roles')).not.toBeInTheDocument();
    });

    it('is absent with no EditionProvider at all (the unreachable-backend default)', () => {
      render(<AdminSidebar currentPath="/admin" />);
      expect(screen.queryByTestId('nav-item-roles')).not.toBeInTheDocument();
      expect(screen.getByTestId('nav-item-users')).toBeInTheDocument();
    });
  });

  describe('the hidden-pages note', () => {
    it('names Enterprise and links to the editions docs in Community', () => {
      renderSidebar();
      const note = screen.getByTestId('admin-sidebar-enterprise-note');
      expect(note).toHaveTextContent('One admin page is part of Enterprise');
      expect(screen.getByRole('link', { name: /enterprise/i })).toHaveAttribute(
        'href',
        '/docs/editions',
      );
    });

    it('is absent once everything is licensed', () => {
      renderSidebar('/admin', licensed());
      expect(screen.queryByTestId('admin-sidebar-enterprise-note')).not.toBeInTheDocument();
    });
  });

  describe('visibleNavItems', () => {
    it('drops exactly the Enterprise items in Community', () => {
      const visible = visibleNavItems(COMMUNITY_EDITION);
      expect(visible).toHaveLength(NAV_ITEMS.length - 1);
      expect(visible.map((i) => i.href)).not.toContain('/admin/roles');
    });

    it('keeps every item when the licence allows them', () => {
      expect(visibleNavItems(licensed())).toHaveLength(NAV_ITEMS.length);
    });

    it('marks only /admin/roles as Enterprise', () => {
      expect(NAV_ITEMS.filter((i) => i.feature).map((i) => i.href)).toEqual(['/admin/roles']);
    });
  });
});
