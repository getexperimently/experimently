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
  it('redirects anonymous visitors to /login', async () => {
    render(
      <AuthProvider>
        <HomePage />
      </AuthProvider>,
    );
    expect(screen.getByTestId('home-redirect')).toBeInTheDocument();
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login'));
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
  });

  it('contains no marketing copy', () => {
    render(
      <AuthProvider>
        <HomePage />
      </AuthProvider>,
    );
    expect(screen.queryByText(/pricing/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/start free trial/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/SOC 2/i)).not.toBeInTheDocument();
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
