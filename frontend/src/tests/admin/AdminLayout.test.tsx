import React from 'react';
import { render, screen } from '@testing-library/react';
import { AdminLayout } from '@/components/admin/AdminLayout';

// Mock AdminSidebar
jest.mock('@/components/admin/AdminSidebar', () => ({
  AdminSidebar: ({ currentPath }: { currentPath: string }) => (
    <nav data-testid="admin-sidebar" data-current-path={currentPath}>
      Sidebar
    </nav>
  ),
}));

// Mock Next.js Link — forward all props
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

describe('AdminLayout', () => {
  it('renders children', () => {
    render(
      <AdminLayout title="Test Title" currentPath="/admin">
        <div data-testid="child-content">Child Content</div>
      </AdminLayout>
    );
    expect(screen.getByTestId('child-content')).toBeInTheDocument();
    expect(screen.getByText('Child Content')).toBeInTheDocument();
  });

  it('renders title', () => {
    render(
      <AdminLayout title="Dashboard" currentPath="/admin">
        <div>Content</div>
      </AdminLayout>
    );
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
  });

  it('renders sidebar', () => {
    render(
      <AdminLayout title="Test" currentPath="/admin/users">
        <div>Content</div>
      </AdminLayout>
    );
    expect(screen.getByTestId('admin-sidebar')).toBeInTheDocument();
  });

  it('renders with data-testid', () => {
    render(
      <AdminLayout title="Test" currentPath="/admin">
        <div>Content</div>
      </AdminLayout>
    );
    expect(screen.getByTestId('admin-layout')).toBeInTheDocument();
  });

  it('shows admin-layout wrapper', () => {
    render(
      <AdminLayout title="Test" currentPath="/admin">
        <div>Content</div>
      </AdminLayout>
    );
    const layout = screen.getByTestId('admin-layout');
    expect(layout).toBeInTheDocument();
  });

  it('renders current path indicator in sidebar', () => {
    render(
      <AdminLayout title="Test" currentPath="/admin/users">
        <div>Content</div>
      </AdminLayout>
    );
    const sidebar = screen.getByTestId('admin-sidebar');
    expect(sidebar).toHaveAttribute('data-current-path', '/admin/users');
  });
});
