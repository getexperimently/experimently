import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { RoleTable } from '@modules/components/admin/roles/RoleTable';
import { RbacService } from '@modules/rbac';
import { CustomRole } from '@/types/admin';

jest.mock('@modules/rbac');

const mockListRoles = RbacService.listRoles as jest.Mock;
const mockDeleteRole = RbacService.deleteRole as jest.Mock;

const mockRoles: CustomRole[] = [
  {
    name: 'developer-role',
    description: 'A developer role',
    permissions: ['experiments:read', 'experiments:create', 'feature_flags:read'],
    created_at: '2024-01-01T00:00:00Z',
  },
  {
    name: 'analyst-role',
    description: 'An analyst role',
    permissions: ['experiments:read', 'feature_flags:read'],
    created_at: '2024-01-02T00:00:00Z',
  },
];

beforeEach(() => {
  jest.clearAllMocks();
  // Suppress window.confirm warnings in test output
  window.confirm = jest.fn(() => true);
});

describe('RoleTable', () => {
  it('renders loading state initially', () => {
    mockListRoles.mockImplementation(() => new Promise(() => {}));
    render(<RoleTable onEditRole={jest.fn()} />);
    expect(screen.getByTestId('role-table-loading')).toBeInTheDocument();
  });

  it('renders role rows after data loads', async () => {
    mockListRoles.mockResolvedValue(mockRoles);
    render(<RoleTable onEditRole={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('developer-role')).toBeInTheDocument();
      expect(screen.getByText('analyst-role')).toBeInTheDocument();
    });
  });

  it('shows role name and description', async () => {
    mockListRoles.mockResolvedValue(mockRoles);
    render(<RoleTable onEditRole={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('developer-role')).toBeInTheDocument();
      expect(screen.getByText('A developer role')).toBeInTheDocument();
      expect(screen.getByText('analyst-role')).toBeInTheDocument();
      expect(screen.getByText('An analyst role')).toBeInTheDocument();
    });
  });

  it('shows permissions count per role', async () => {
    mockListRoles.mockResolvedValue(mockRoles);
    render(<RoleTable onEditRole={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('3 permissions')).toBeInTheDocument();
      expect(screen.getByText('2 permissions')).toBeInTheDocument();
    });
  });

  it('clicking edit button calls onEditRole callback', async () => {
    mockListRoles.mockResolvedValue(mockRoles);
    const onEditRole = jest.fn();
    render(<RoleTable onEditRole={onEditRole} />);
    await waitFor(() => {
      expect(screen.getByText('developer-role')).toBeInTheDocument();
    });
    const editButtons = screen.getAllByTestId('edit-role-button');
    fireEvent.click(editButtons[0]);
    expect(onEditRole).toHaveBeenCalledWith(mockRoles[0]);
  });

  it('clicking delete shows confirmation', async () => {
    (window.confirm as jest.Mock).mockReturnValue(false);
    mockListRoles.mockResolvedValue(mockRoles);
    mockDeleteRole.mockResolvedValue(undefined);
    render(<RoleTable onEditRole={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('developer-role')).toBeInTheDocument();
    });
    const deleteButtons = screen.getAllByTestId('delete-role-button');
    fireEvent.click(deleteButtons[0]);
    expect(window.confirm).toHaveBeenCalled();
    expect(mockDeleteRole).not.toHaveBeenCalled();
  });

  it('delete calls RbacService.deleteRole', async () => {
    mockListRoles.mockResolvedValue(mockRoles);
    mockDeleteRole.mockResolvedValue(undefined);
    // mockListRoles returns the same on refetch
    mockListRoles.mockResolvedValue(mockRoles);

    render(<RoleTable onEditRole={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('developer-role')).toBeInTheDocument();
    });

    const deleteButtons = screen.getAllByTestId('delete-role-button');
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      expect(mockDeleteRole).toHaveBeenCalledWith('developer-role');
    });
    await waitFor(() => {
      expect(mockListRoles).toHaveBeenCalledTimes(2);
    });
  });

  it('shows empty state when no roles', async () => {
    mockListRoles.mockResolvedValue([]);
    render(<RoleTable onEditRole={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId('role-table-empty')).toBeInTheDocument();
    });
  });

  it('shows error state if listRoles fails', async () => {
    mockListRoles.mockRejectedValue(new Error('Failed to fetch roles'));
    render(<RoleTable onEditRole={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId('role-table-error')).toBeInTheDocument();
    });
  });

  it('renders with data-testid="role-table"', async () => {
    mockListRoles.mockResolvedValue(mockRoles);
    render(<RoleTable onEditRole={jest.fn()} />);
    expect(screen.getByTestId('role-table')).toBeInTheDocument();
    await screen.findByText('developer-role');
  });
});
