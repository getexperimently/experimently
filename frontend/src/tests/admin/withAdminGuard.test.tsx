import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { withAdminGuard, rolesAtLeast, ADMIN_AREA_ROLES } from '@/components/admin/withAdminGuard';
import { AuthProvider } from '@/contexts/AuthContext';
import { TOKEN_STORAGE_KEY, UserMe } from '@/services/api';
import { UserRole } from '@/types/admin';

const mockReplace = jest.fn();

// Mock Next.js router
jest.mock('next/router', () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: mockReplace,
    pathname: '/admin',
    asPath: '/admin',
    query: {},
    isReady: true,
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

// Simple test component
const TestComponent: React.FC<{ title?: string }> = ({ title = 'Test Content' }) => (
  <div data-testid="protected-content">{title}</div>
);

function user(role: UserRole): UserMe {
  return {
    id: '1',
    username: role.toLowerCase(),
    email: `${role.toLowerCase()}@example.com`,
    full_name: null,
    role,
    is_superuser: role === 'ADMIN',
    is_active: true,
    auth_provider: 'local',
  };
}

function signInAs(role: UserRole) {
  localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
  mockFetch.mockResolvedValueOnce({
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(user(role)),
    text: () => Promise.resolve(JSON.stringify(user(role))),
  } as unknown as Response);
}

function renderGuarded(Guarded: React.FC<{ title?: string }>) {
  return render(
    <AuthProvider>
      <Guarded />
    </AuthProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  mockFetch.mockReset();
  mockReplace.mockReset();
});

describe('withAdminGuard', () => {
  it('renders component when user is ADMIN', async () => {
    signInAs('ADMIN');
    const GuardedComponent = withAdminGuard(TestComponent);
    renderGuarded(GuardedComponent);
    await waitFor(() => expect(screen.getByTestId('protected-content')).toBeInTheDocument());
  });

  it('admits DEVELOPER by default (matches the Admin nav item)', async () => {
    signInAs('DEVELOPER');
    const GuardedComponent = withAdminGuard(TestComponent);
    renderGuarded(GuardedComponent);
    await waitFor(() => expect(screen.getByTestId('protected-content')).toBeInTheDocument());
    expect(ADMIN_AREA_ROLES).toEqual(['ADMIN', 'DEVELOPER']);
  });

  it('redirects to /login when there is no session', async () => {
    const GuardedComponent = withAdminGuard(TestComponent);
    renderGuarded(GuardedComponent);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login?next=%2Fadmin'));
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  it('shows the 403 view when user role is below requiredRole', async () => {
    signInAs('DEVELOPER');
    const GuardedComponent = withAdminGuard(TestComponent, { requiredRole: 'ADMIN' });
    renderGuarded(GuardedComponent);
    await waitFor(() => expect(screen.getByTestId('require-auth-forbidden')).toBeInTheDocument());
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to home/i })).toBeInTheDocument();
  });

  it('shows the 403 view for VIEWER on the default admin audience', async () => {
    signInAs('VIEWER');
    const GuardedComponent = withAdminGuard(TestComponent);
    renderGuarded(GuardedComponent);
    await waitFor(() => expect(screen.getByTestId('require-auth-forbidden')).toBeInTheDocument());
  });

  it('shows loading state initially', () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockFetch.mockImplementation(() => new Promise(() => {}));
    const GuardedComponent = withAdminGuard(TestComponent);
    renderGuarded(GuardedComponent);
    expect(screen.getByTestId('require-auth-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  it('works with DEVELOPER role when requiredRole is DEVELOPER', async () => {
    signInAs('DEVELOPER');
    const GuardedComponent = withAdminGuard(TestComponent, { requiredRole: 'DEVELOPER' });
    renderGuarded(GuardedComponent);
    await waitFor(() => expect(screen.getByTestId('protected-content')).toBeInTheDocument());
  });

  it('requiredRole is hierarchical: ADMIN passes a DEVELOPER requirement', async () => {
    signInAs('ADMIN');
    const GuardedComponent = withAdminGuard(TestComponent, { requiredRole: 'DEVELOPER' });
    renderGuarded(GuardedComponent);
    await waitFor(() => expect(screen.getByTestId('protected-content')).toBeInTheDocument());
    expect(rolesAtLeast('DEVELOPER')).toEqual(['DEVELOPER', 'ADMIN']);
    expect(rolesAtLeast('VIEWER')).toEqual(['VIEWER', 'ANALYST', 'DEVELOPER', 'ADMIN']);
  });

  it('explicit roles list takes precedence', async () => {
    signInAs('ANALYST');
    const GuardedComponent = withAdminGuard(TestComponent, { roles: ['ANALYST'] });
    renderGuarded(GuardedComponent);
    await waitFor(() => expect(screen.getByTestId('protected-content')).toBeInTheDocument());
  });

  it('ignores a stale admin_user object in localStorage', async () => {
    localStorage.setItem('admin_user', JSON.stringify(user('ADMIN')));
    const GuardedComponent = withAdminGuard(TestComponent);
    renderGuarded(GuardedComponent);
    await waitFor(() => expect(mockReplace).toHaveBeenCalled());
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  it('sets a helpful displayName', () => {
    const GuardedComponent = withAdminGuard(TestComponent);
    expect(GuardedComponent.displayName).toBe('withAdminGuard(TestComponent)');
  });
});
