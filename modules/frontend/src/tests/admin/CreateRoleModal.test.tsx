import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CreateRoleModal } from '@modules/components/admin/roles/CreateRoleModal';
import { RbacService } from '@modules/rbac';
import { CustomRole } from '@/types/admin';

jest.mock('@modules/rbac');
jest.mock('@modules/components/admin/roles/PermissionCheckboxGrid', () => ({
  PermissionCheckboxGrid: ({
    selectedPermissions,
    onChange,
    readOnly,
  }: {
    selectedPermissions: string[];
    onChange: (p: string[]) => void;
    readOnly?: boolean;
  }) => (
    <div data-testid="permission-checkbox-grid">
      {['experiments:read', 'users:read'].map((perm) => (
        <input
          key={perm}
          type="checkbox"
          data-testid={`permission-checkbox-${perm}`}
          checked={selectedPermissions.includes(perm)}
          disabled={readOnly}
          onChange={() => {
            if (selectedPermissions.includes(perm)) {
              onChange(selectedPermissions.filter((p) => p !== perm));
            } else {
              onChange([...selectedPermissions, perm]);
            }
          }}
          aria-label={perm}
        />
      ))}
    </div>
  ),
}));

const mockCreateRole = RbacService.createRole as jest.Mock;
const mockUpdateRole = RbacService.updateRole as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
});

const mockRole: CustomRole = {
  name: 'existing-role',
  description: 'An existing role',
  permissions: ['experiments:read'],
  created_at: '2024-01-01T00:00:00Z',
};

describe('CreateRoleModal', () => {
  it('renders modal when isOpen=true', () => {
    render(
      <CreateRoleModal
        isOpen={true}
        onClose={jest.fn()}
        onSuccess={jest.fn()}
      />
    );
    expect(screen.getByTestId('create-role-modal')).toBeInTheDocument();
  });

  it('does not render when isOpen=false', () => {
    render(
      <CreateRoleModal
        isOpen={false}
        onClose={jest.fn()}
        onSuccess={jest.fn()}
      />
    );
    expect(screen.queryByTestId('create-role-modal')).not.toBeInTheDocument();
  });

  it('shows name and description inputs', () => {
    render(
      <CreateRoleModal
        isOpen={true}
        onClose={jest.fn()}
        onSuccess={jest.fn()}
      />
    );
    expect(screen.getByTestId('role-name-input')).toBeInTheDocument();
    expect(screen.getByTestId('role-description-input')).toBeInTheDocument();
  });

  it('shows permission checkboxes grid', () => {
    render(
      <CreateRoleModal
        isOpen={true}
        onClose={jest.fn()}
        onSuccess={jest.fn()}
      />
    );
    expect(screen.getByTestId('permission-checkbox-grid')).toBeInTheDocument();
  });

  it('submit disabled when name is empty', () => {
    render(
      <CreateRoleModal
        isOpen={true}
        onClose={jest.fn()}
        onSuccess={jest.fn()}
      />
    );
    const submitButton = screen.getByTestId('modal-submit-button');
    expect(submitButton).toBeDisabled();
  });

  it('calls RbacService.createRole with correct data on submit in create mode', async () => {
    mockCreateRole.mockResolvedValue({
      name: 'new-role',
      description: 'A new role',
      permissions: ['experiments:read'],
      created_at: '2024-01-01T00:00:00Z',
    });

    const onSuccess = jest.fn();
    render(
      <CreateRoleModal
        isOpen={true}
        onClose={jest.fn()}
        onSuccess={onSuccess}
      />
    );

    fireEvent.change(screen.getByTestId('role-name-input'), {
      target: { value: 'new-role' },
    });
    fireEvent.change(screen.getByTestId('role-description-input'), {
      target: { value: 'A new role' },
    });

    // Check a permission
    const permCheckbox = screen.getByTestId('permission-checkbox-experiments:read');
    fireEvent.click(permCheckbox);

    fireEvent.click(screen.getByTestId('modal-submit-button'));

    await waitFor(() => {
      expect(mockCreateRole).toHaveBeenCalledWith({
        name: 'new-role',
        description: 'A new role',
        permissions: ['experiments:read'],
      });
    });

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  it('populates form with existing role data in edit mode', () => {
    render(
      <CreateRoleModal
        isOpen={true}
        role={mockRole}
        onClose={jest.fn()}
        onSuccess={jest.fn()}
      />
    );
    expect(screen.getByTestId('role-name-input')).toHaveValue('existing-role');
    expect(screen.getByTestId('role-description-input')).toHaveValue('An existing role');
  });

  it('calls RbacService.updateRole in edit mode', async () => {
    mockUpdateRole.mockResolvedValue({
      ...mockRole,
      description: 'Updated description',
    });

    const onSuccess = jest.fn();
    render(
      <CreateRoleModal
        isOpen={true}
        role={mockRole}
        onClose={jest.fn()}
        onSuccess={onSuccess}
      />
    );

    fireEvent.change(screen.getByTestId('role-description-input'), {
      target: { value: 'Updated description' },
    });

    fireEvent.click(screen.getByTestId('modal-submit-button'));

    await waitFor(() => {
      expect(mockUpdateRole).toHaveBeenCalledWith(
        'existing-role',
        expect.objectContaining({
          description: 'Updated description',
        })
      );
    });

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled();
    });
  });

  it('shows error message on failure', async () => {
    mockCreateRole.mockRejectedValue(new Error('Failed to create role'));

    render(
      <CreateRoleModal
        isOpen={true}
        onClose={jest.fn()}
        onSuccess={jest.fn()}
      />
    );

    fireEvent.change(screen.getByTestId('role-name-input'), {
      target: { value: 'bad-role' },
    });

    fireEvent.click(screen.getByTestId('modal-submit-button'));

    await waitFor(() => {
      expect(screen.getByTestId('modal-error')).toBeInTheDocument();
    });
  });

  it('calls onClose when cancel clicked', () => {
    const onClose = jest.fn();
    render(
      <CreateRoleModal
        isOpen={true}
        onClose={onClose}
        onSuccess={jest.fn()}
      />
    );
    fireEvent.click(screen.getByTestId('modal-cancel-button'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
