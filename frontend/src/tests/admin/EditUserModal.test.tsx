import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EditUserModal } from '@/components/admin/users/EditUserModal';
import { AdminUser } from '@/types/admin';

const mockUser: AdminUser = {
  id: 'user-1',
  username: 'jdoe',
  email: 'jdoe@example.com',
  role: 'DEVELOPER',
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
};

describe('EditUserModal', () => {
  const defaultProps = {
    isOpen: true,
    user: mockUser,
    onClose: jest.fn(),
    onSave: jest.fn(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders modal when isOpen=true', () => {
    render(<EditUserModal {...defaultProps} />);
    expect(screen.getByTestId('edit-user-modal')).toBeInTheDocument();
  });

  it('populates form with user data', () => {
    render(<EditUserModal {...defaultProps} />);
    // Email should be displayed somewhere (read-only or as label)
    expect(screen.getByText('jdoe@example.com')).toBeInTheDocument();
  });

  it('role select shows current user role', () => {
    render(<EditUserModal {...defaultProps} />);
    const roleSelect = screen.getByTestId('edit-role-select') as HTMLSelectElement;
    expect(roleSelect.value).toBe('DEVELOPER');
  });

  it('is_active toggle shows current state', () => {
    render(<EditUserModal {...defaultProps} />);
    const activeToggle = screen.getByTestId('edit-active-toggle') as HTMLInputElement;
    expect(activeToggle.checked).toBe(true);
  });

  it('calls onSave with updated data on submit', () => {
    const onSave = jest.fn();
    render(<EditUserModal {...defaultProps} onSave={onSave} />);

    const roleSelect = screen.getByTestId('edit-role-select');
    fireEvent.change(roleSelect, { target: { value: 'ANALYST' } });

    const saveBtn = screen.getByTestId('edit-save-button');
    fireEvent.click(saveBtn);

    expect(onSave).toHaveBeenCalledWith('user-1', expect.objectContaining({ role: 'ANALYST' }));
  });

  it('shows confirmation warning when deactivating an active user', () => {
    render(<EditUserModal {...defaultProps} />);
    const activeToggle = screen.getByTestId('edit-active-toggle');

    // Uncheck the toggle to deactivate
    fireEvent.click(activeToggle);

    expect(screen.getByTestId('deactivate-warning')).toBeInTheDocument();
  });

  it('calls onClose when cancel is clicked', () => {
    const onClose = jest.fn();
    render(<EditUserModal {...defaultProps} onClose={onClose} />);
    const cancelBtn = screen.getByTestId('edit-cancel-button');
    fireEvent.click(cancelBtn);
    expect(onClose).toHaveBeenCalled();
  });

  it('renders with data-testid="edit-user-modal"', () => {
    render(<EditUserModal {...defaultProps} />);
    expect(screen.getByTestId('edit-user-modal')).toBeInTheDocument();
  });
});
