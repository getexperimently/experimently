import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { EffectivePermissionsModal } from '@/components/admin/users/EffectivePermissionsModal';
import { RbacService } from '@modules/rbac';

jest.mock('@modules/rbac');

const mockGetUserPermissions = RbacService.getUserPermissions as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
});

describe('EffectivePermissionsModal', () => {
  const defaultProps = {
    isOpen: true,
    userId: 'user-123',
    userEmail: 'user@example.com',
    onClose: jest.fn(),
  };

  it('renders modal when isOpen=true', async () => {
    mockGetUserPermissions.mockResolvedValue({ permissions: [] });
    render(<EffectivePermissionsModal {...defaultProps} />);
    expect(screen.getByTestId('effective-permissions-modal')).toBeInTheDocument();
    await waitFor(() => {
      expect(mockGetUserPermissions).toHaveBeenCalledWith('user-123');
    });
  });

  it('fetches permissions for userId on open', async () => {
    mockGetUserPermissions.mockResolvedValue({ permissions: ['read:experiments'] });
    render(<EffectivePermissionsModal {...defaultProps} />);
    await waitFor(() => {
      expect(mockGetUserPermissions).toHaveBeenCalledWith('user-123');
    });
  });

  it('shows list of permissions', async () => {
    mockGetUserPermissions.mockResolvedValue({
      permissions: ['read:experiments', 'write:feature_flags', 'admin:users'],
    });
    render(<EffectivePermissionsModal {...defaultProps} />);
    await waitFor(() => {
      expect(screen.getByText('read:experiments')).toBeInTheDocument();
      expect(screen.getByText('write:feature_flags')).toBeInTheDocument();
      expect(screen.getByText('admin:users')).toBeInTheDocument();
    });
  });

  it('shows loading while fetching', () => {
    mockGetUserPermissions.mockImplementation(() => new Promise(() => {}));
    render(<EffectivePermissionsModal {...defaultProps} />);
    expect(screen.getByTestId('permissions-loading')).toBeInTheDocument();
  });

  it('shows error if fetch fails', async () => {
    mockGetUserPermissions.mockRejectedValue(new Error('Forbidden'));
    render(<EffectivePermissionsModal {...defaultProps} />);
    await waitFor(() => {
      expect(screen.getByTestId('permissions-error')).toBeInTheDocument();
    });
  });

  it('renders with data-testid="effective-permissions-modal"', async () => {
    mockGetUserPermissions.mockResolvedValue({ permissions: [] });
    render(<EffectivePermissionsModal {...defaultProps} />);
    expect(screen.getByTestId('effective-permissions-modal')).toBeInTheDocument();
    await waitFor(() => {
      expect(mockGetUserPermissions).toHaveBeenCalledWith('user-123');
    });
  });
});
