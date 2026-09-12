import React from 'react';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { UserTable } from '@/components/admin/users/UserTable';
import { AdminService } from '@/services/admin';
import { AdminUser, UserListResponse } from '@/types/admin';

jest.mock('@/services/admin');

const mockListUsers = AdminService.listUsers as jest.Mock;
const mockDeleteUser = AdminService.deleteUser as jest.Mock;

const makeUser = (overrides: Partial<AdminUser> = {}): AdminUser => ({
  id: '1',
  username: 'testuser',
  email: 'test@example.com',
  role: 'DEVELOPER',
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
  ...overrides,
});

const makeResponse = (users: AdminUser[], total?: number): UserListResponse => ({
  items: users,
  total: total ?? users.length,
  page: 1,
  limit: 50,
});

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  // Default: suppress window.confirm
  window.confirm = jest.fn(() => true);
});

afterEach(() => {
  jest.useRealTimers();
});

describe('UserTable', () => {
  it('renders loading state initially', () => {
    mockListUsers.mockImplementation(() => new Promise(() => {}));
    render(<UserTable />);
    // Loading skeleton should appear (animate-pulse rows)
    expect(screen.getByTestId('user-table')).toBeInTheDocument();
    expect(screen.getByTestId('loading-skeleton')).toBeInTheDocument();
  });

  it('renders user rows after data loads', async () => {
    const users = [
      makeUser({ id: '1', username: 'alice', email: 'alice@example.com' }),
      makeUser({ id: '2', username: 'bob', email: 'bob@example.com' }),
    ];
    mockListUsers.mockResolvedValue(makeResponse(users));
    render(<UserTable />);
    await waitFor(() => {
      expect(screen.getByText('alice')).toBeInTheDocument();
      expect(screen.getByText('bob')).toBeInTheDocument();
    });
  });

  it('shows username and email in each row', async () => {
    const users = [makeUser({ username: 'charlie', email: 'charlie@corp.com' })];
    mockListUsers.mockResolvedValue(makeResponse(users));
    render(<UserTable />);
    await waitFor(() => {
      expect(screen.getByText('charlie')).toBeInTheDocument();
      expect(screen.getByText('charlie@corp.com')).toBeInTheDocument();
    });
  });

  it('shows role badge with correct text', async () => {
    const users = [makeUser({ role: 'ADMIN' })];
    mockListUsers.mockResolvedValue(makeResponse(users));
    render(<UserTable />);
    await waitFor(() => {
      expect(screen.getByText('Admin')).toBeInTheDocument();
    });
  });

  it('shows active/inactive status badge', async () => {
    const users = [
      makeUser({ id: '1', username: 'active-user', is_active: true }),
      makeUser({ id: '2', username: 'inactive-user', is_active: false }),
    ];
    mockListUsers.mockResolvedValue(makeResponse(users));
    render(<UserTable />);
    await waitFor(() => {
      expect(screen.getByText('Active')).toBeInTheDocument();
      expect(screen.getByText('Inactive')).toBeInTheDocument();
    });
  });

  it('search input filters by name/email (calls listUsers with search param after debounce)', async () => {
    mockListUsers.mockResolvedValue(makeResponse([]));
    render(<UserTable />);
    // Wait for initial load
    await waitFor(() => expect(mockListUsers).toHaveBeenCalledTimes(1));

    const searchInput = screen.getByTestId('user-search');
    fireEvent.change(searchInput, { target: { value: 'alice' } });

    // Debounce: should not call immediately
    expect(mockListUsers).toHaveBeenCalledTimes(1);

    // Advance timers past the 300ms debounce
    act(() => {
      jest.advanceTimersByTime(300);
    });

    await waitFor(() => {
      expect(mockListUsers).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'alice' })
      );
    });
  });

  it('clicking delete button calls AdminService.deleteUser with user id', async () => {
    const user = makeUser({ id: 'user-42' });
    mockListUsers.mockResolvedValue(makeResponse([user]));
    mockDeleteUser.mockResolvedValue(undefined);

    render(<UserTable />);
    await waitFor(() => screen.getByText('testuser'));

    const deleteBtn = screen.getByTestId('delete-user-user-42');
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(mockDeleteUser).toHaveBeenCalledWith('user-42');
    });
  });

  it('shows confirmation before delete', async () => {
    const user = makeUser({ id: 'user-99' });
    mockListUsers.mockResolvedValue(makeResponse([user]));
    mockDeleteUser.mockResolvedValue(undefined);
    const confirmMock = jest.fn(() => false);
    window.confirm = confirmMock;

    render(<UserTable />);
    await waitFor(() => screen.getByText('testuser'));

    const deleteBtn = screen.getByTestId('delete-user-user-99');
    fireEvent.click(deleteBtn);

    expect(confirmMock).toHaveBeenCalled();
    // Since confirm returns false, deleteUser should NOT be called
    expect(mockDeleteUser).not.toHaveBeenCalled();
  });

  it('shows error state if listUsers fails', async () => {
    mockListUsers.mockRejectedValue(new Error('Network error'));
    render(<UserTable />);
    await waitFor(() => {
      expect(screen.getByTestId('error-state')).toBeInTheDocument();
    });
  });

  it('renders empty state when no users', async () => {
    mockListUsers.mockResolvedValue(makeResponse([]));
    render(<UserTable />);
    await waitFor(() => {
      expect(screen.getByText(/no users found/i)).toBeInTheDocument();
    });
  });

  it('pagination shows correct page info', async () => {
    const users = [makeUser()];
    mockListUsers.mockResolvedValue({ items: users, total: 42, page: 1, limit: 50 });
    render(<UserTable />);
    await waitFor(() => {
      expect(screen.getByText(/showing 1 of 42/i)).toBeInTheDocument();
    });
  });

  it('renders with data-testid="user-table"', () => {
    mockListUsers.mockImplementation(() => new Promise(() => {}));
    render(<UserTable />);
    expect(screen.getByTestId('user-table')).toBeInTheDocument();
  });
});
