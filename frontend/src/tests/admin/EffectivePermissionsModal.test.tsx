import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { EffectivePermissionsModal } from '@/components/admin/users/EffectivePermissionsModal';
import { RbacService } from '@modules/rbac';

jest.mock('@modules/rbac');

const mockGetUserPermissions = RbacService.getUserPermissions as jest.Mock;

// No permission check reads custom roles or direct grants yet (#891), so the
// dialog must not present the list as what the user can do.
const ACCESS_NOTE =
  "This list adds the user's custom roles and direct grants to their built-in role. " +
  'Custom roles and direct permission grants are recorded, but they do not change what ' +
  "anyone can do yet: each user's built-in role decides.";

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

  it('says, above the list, that custom roles and direct grants do not change access yet (#891)', async () => {
    mockGetUserPermissions.mockResolvedValue({ permissions: ['experiments:read', 'experiments:create'] });
    render(<EffectivePermissionsModal {...defaultProps} />);
    const dialog = screen.getByRole('dialog', { name: 'Recorded Permissions' });
    expect(dialog).toHaveAccessibleDescription(ACCESS_NOTE);
    const list = await screen.findByTestId('permissions-list');
    const note = screen.getByTestId('permissions-access-note');
    expect(note).toHaveTextContent(ACCESS_NOTE);
    // Above the list, so it is read before the permissions are.
    expect(note.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText('Effective Permissions')).not.toBeInTheDocument();
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
