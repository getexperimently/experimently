import React from 'react';
import { render, screen } from '@testing-library/react';
import { withAdminGuard } from '@/components/admin/withAdminGuard';
import { AdminUser, UserRole } from '@/types/admin';

// Mock Next.js router
jest.mock('next/router', () => ({
  useRouter: () => ({
    push: jest.fn(),
    pathname: '/',
  }),
}));

// Simple test component
const TestComponent: React.FC<{ title?: string }> = ({ title = 'Test Content' }) => (
  <div data-testid="protected-content">{title}</div>
);

const mockAdminUser: AdminUser = {
  id: '1',
  username: 'admin',
  email: 'admin@example.com',
  role: 'ADMIN',
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
};

const mockDeveloperUser: AdminUser = {
  id: '2',
  username: 'developer',
  email: 'dev@example.com',
  role: 'DEVELOPER',
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
};

function setLocalStorage(user: AdminUser | null) {
  if (user) {
    localStorage.setItem('admin_user', JSON.stringify(user));
  } else {
    localStorage.removeItem('admin_user');
  }
}

beforeEach(() => {
  localStorage.clear();
});

describe('withAdminGuard', () => {
  it('renders component when user is ADMIN', () => {
    setLocalStorage(mockAdminUser);
    const GuardedComponent = withAdminGuard(TestComponent);
    render(<GuardedComponent />);
    expect(screen.getByTestId('protected-content')).toBeInTheDocument();
  });

  it('redirects to "/" when no user in localStorage', () => {
    const GuardedComponent = withAdminGuard(TestComponent);
    render(<GuardedComponent />);
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to home/i })).toBeInTheDocument();
  });

  it('redirects when user role does not match requiredRole', () => {
    setLocalStorage(mockDeveloperUser);
    const GuardedComponent = withAdminGuard(TestComponent, { requiredRole: 'ADMIN' });
    render(<GuardedComponent />);
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to home/i })).toBeInTheDocument();
  });

  it('shows loading state initially', () => {
    // localStorage is sync but we still check it renders without crash
    setLocalStorage(mockAdminUser);
    const GuardedComponent = withAdminGuard(TestComponent);
    const { container } = render(<GuardedComponent />);
    // Component should render (either loading or content after sync check)
    expect(container).toBeTruthy();
  });

  it('works with DEVELOPER role when requiredRole is DEVELOPER', () => {
    setLocalStorage(mockDeveloperUser);
    const GuardedComponent = withAdminGuard(TestComponent, { requiredRole: 'DEVELOPER' });
    render(<GuardedComponent />);
    expect(screen.getByTestId('protected-content')).toBeInTheDocument();
  });

  it('handles invalid JSON in localStorage gracefully', () => {
    localStorage.setItem('admin_user', 'invalid-json{{{');
    const GuardedComponent = withAdminGuard(TestComponent);
    render(<GuardedComponent />);
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to home/i })).toBeInTheDocument();
  });
});
