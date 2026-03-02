import React from 'react';
import { render, screen } from '@testing-library/react';
import { AdminSidebar } from '@/components/admin/AdminSidebar';

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

describe('AdminSidebar', () => {
  it('renders all nav items', () => {
    render(<AdminSidebar currentPath="/admin" />);
    expect(screen.getByText(/dashboard/i)).toBeInTheDocument();
    expect(screen.getByText(/users/i)).toBeInTheDocument();
    expect(screen.getByText(/roles/i)).toBeInTheDocument();
    expect(screen.getByText(/audit log/i)).toBeInTheDocument();
    expect(screen.getByText(/safety/i)).toBeInTheDocument();
    expect(screen.getByText(/scheduler/i)).toBeInTheDocument();
    expect(screen.getByText(/api keys/i)).toBeInTheDocument();
  });

  it('highlights active item based on currentPath', () => {
    render(<AdminSidebar currentPath="/admin/users" />);
    const usersLink = screen.getByTestId('nav-item-users');
    expect(usersLink).toHaveClass('bg-blue-50');
    expect(usersLink).toHaveClass('text-blue-700');
  });

  it('nav items have correct href attributes', () => {
    render(<AdminSidebar currentPath="/admin" />);
    expect(screen.getByRole('link', { name: /dashboard/i })).toHaveAttribute('href', '/admin');
    expect(screen.getByRole('link', { name: /users/i })).toHaveAttribute('href', '/admin/users');
    expect(screen.getByRole('link', { name: /roles/i })).toHaveAttribute('href', '/admin/roles');
    expect(screen.getByRole('link', { name: /audit log/i })).toHaveAttribute('href', '/admin/audit');
    expect(screen.getByRole('link', { name: /safety/i })).toHaveAttribute('href', '/admin/safety');
    expect(screen.getByRole('link', { name: /scheduler/i })).toHaveAttribute('href', '/admin/scheduler');
    expect(screen.getByRole('link', { name: /api keys/i })).toHaveAttribute('href', '/admin/api-keys');
  });

  it('renders with data-testid', () => {
    render(<AdminSidebar currentPath="/admin" />);
    expect(screen.getByTestId('admin-sidebar')).toBeInTheDocument();
  });

  it('renders Dashboard link', () => {
    render(<AdminSidebar currentPath="/admin" />);
    const dashboardLink = screen.getByRole('link', { name: /dashboard/i });
    expect(dashboardLink).toBeInTheDocument();
    expect(dashboardLink).toHaveAttribute('href', '/admin');
  });

  it('renders Users link', () => {
    render(<AdminSidebar currentPath="/admin" />);
    const usersLink = screen.getByRole('link', { name: /users/i });
    expect(usersLink).toBeInTheDocument();
    expect(usersLink).toHaveAttribute('href', '/admin/users');
  });

  it('renders Audit Log link', () => {
    render(<AdminSidebar currentPath="/admin" />);
    const auditLink = screen.getByRole('link', { name: /audit log/i });
    expect(auditLink).toBeInTheDocument();
    expect(auditLink).toHaveAttribute('href', '/admin/audit');
  });

  it('renders Safety link', () => {
    render(<AdminSidebar currentPath="/admin" />);
    const safetyLink = screen.getByRole('link', { name: /safety/i });
    expect(safetyLink).toBeInTheDocument();
    expect(safetyLink).toHaveAttribute('href', '/admin/safety');
  });
});
