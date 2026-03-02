import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { InviteUserModal } from '@/components/admin/users/InviteUserModal';

// Mock global fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

beforeEach(() => {
  jest.clearAllMocks();
});

describe('InviteUserModal', () => {
  const defaultProps = {
    isOpen: true,
    onClose: jest.fn(),
    onSuccess: jest.fn(),
  };

  it('renders modal when isOpen=true', () => {
    render(<InviteUserModal {...defaultProps} />);
    expect(screen.getByTestId('invite-user-modal')).toBeInTheDocument();
  });

  it('does not render when isOpen=false', () => {
    render(<InviteUserModal {...defaultProps} isOpen={false} />);
    expect(screen.queryByTestId('invite-user-modal')).not.toBeInTheDocument();
  });

  it('shows email and role inputs', () => {
    render(<InviteUserModal {...defaultProps} />);
    expect(screen.getByTestId('invite-email-input')).toBeInTheDocument();
    expect(screen.getByTestId('invite-role-select')).toBeInTheDocument();
  });

  it('submit button disabled when email is empty', () => {
    render(<InviteUserModal {...defaultProps} />);
    const submitBtn = screen.getByTestId('invite-submit-button');
    expect(submitBtn).toBeDisabled();
  });

  it('calls onSuccess and onClose with email and role on form submit', async () => {
    const onClose = jest.fn();
    const onSuccess = jest.fn();

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ id: 'new-user', email: 'new@example.com', role: 'DEVELOPER' }),
    } as Response);

    render(<InviteUserModal isOpen={true} onClose={onClose} onSuccess={onSuccess} />);

    const emailInput = screen.getByTestId('invite-email-input');
    const roleSelect = screen.getByTestId('invite-role-select');

    fireEvent.change(emailInput, { target: { value: 'new@example.com' } });
    fireEvent.change(roleSelect, { target: { value: 'DEVELOPER' } });

    const submitBtn = screen.getByTestId('invite-submit-button');
    expect(submitBtn).not.toBeDisabled();

    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/v1/admin/users'),
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('new@example.com'),
        })
      );
      expect(onSuccess).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it('shows error message when onSubmit throws', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      statusText: 'Bad Request',
    } as Response);

    render(<InviteUserModal {...defaultProps} />);

    const emailInput = screen.getByTestId('invite-email-input');
    fireEvent.change(emailInput, { target: { value: 'fail@example.com' } });

    const submitBtn = screen.getByTestId('invite-submit-button');
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByTestId('invite-error-message')).toBeInTheDocument();
    });
  });

  it('calls onClose when cancel button clicked', () => {
    const onClose = jest.fn();
    render(<InviteUserModal {...defaultProps} onClose={onClose} />);
    const cancelBtn = screen.getByTestId('invite-cancel-button');
    fireEvent.click(cancelBtn);
    expect(onClose).toHaveBeenCalled();
  });

  it('renders with data-testid="invite-user-modal"', () => {
    render(<InviteUserModal {...defaultProps} />);
    expect(screen.getByTestId('invite-user-modal')).toBeInTheDocument();
  });
});
