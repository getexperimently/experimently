import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { RequireAuth } from '@/components/RequireAuth';
import { AuthProvider } from '@/contexts/AuthContext';
import { TOKEN_STORAGE_KEY, UserMe } from '@/services/api';

const mockReplace = jest.fn();
let mockAsPath = '/experiments/abc?tab=results';

jest.mock('next/router', () => ({
  useRouter: () => ({
    replace: mockReplace,
    push: jest.fn(),
    pathname: '/experiments/[id]',
    asPath: mockAsPath,
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

const viewer: UserMe = {
  id: 'u-2',
  email: 'viewer@demo.com',
  username: 'viewer',
  full_name: 'Demo Viewer',
  role: 'VIEWER',
  is_superuser: false,
  is_active: true,
  auth_provider: 'local',
};

function meResponse(user: UserMe): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(user),
    text: () => Promise.resolve(JSON.stringify(user)),
  } as unknown as Response;
}

function renderGuarded(roles?: UserMe['role'][]) {
  return render(
    <AuthProvider>
      <RequireAuth roles={roles}>
        <div data-testid="protected">secret</div>
      </RequireAuth>
    </AuthProvider>,
  );
}

beforeEach(() => {
  mockFetch.mockReset();
  mockReplace.mockReset();
  localStorage.clear();
  mockAsPath = '/experiments/abc?tab=results';
});

describe('RequireAuth', () => {
  it('shows the loading state while the session resolves and hides children', () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockFetch.mockImplementation(() => new Promise(() => {}));
    renderGuarded();
    expect(screen.getByTestId('require-auth-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('redirects anonymous users to /login?next=<current path>', async () => {
    renderGuarded();
    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith('/login?next=%2Fexperiments%2Fabc%3Ftab%3Dresults'),
    );
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
  });

  it('redirects to plain /login when the current path is the root', async () => {
    mockAsPath = '/';
    renderGuarded();
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith('/login'));
  });

  it('renders children for an authenticated user with no role restriction', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockFetch.mockResolvedValueOnce(meResponse(viewer));
    renderGuarded();
    await waitFor(() => expect(screen.getByTestId('protected')).toBeInTheDocument());
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('renders children when the user holds one of the allowed roles', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockFetch.mockResolvedValueOnce(meResponse({ ...viewer, role: 'ADMIN' }));
    renderGuarded(['ADMIN', 'DEVELOPER']);
    await waitFor(() => expect(screen.getByTestId('protected')).toBeInTheDocument());
  });

  it('renders the inline 403 view when the role is not allowed', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'tok');
    mockFetch.mockResolvedValueOnce(meResponse(viewer));
    renderGuarded(['ADMIN']);
    await waitFor(() => expect(screen.getByTestId('require-auth-forbidden')).toBeInTheDocument());
    expect(screen.queryByTestId('protected')).not.toBeInTheDocument();
    expect(screen.getByText(/do not have permission/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /go to home/i })).toHaveAttribute('href', '/experiments');
    expect(mockReplace).not.toHaveBeenCalled();
  });
});
