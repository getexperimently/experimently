import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import {
  InviteUserModal,
  generateTemporaryPassword,
  usernameFromEmail,
} from '@/components/admin/users/InviteUserModal';

// Mock global fetch — the modal goes through AdminService.createUser → apiFetch → fetch.
const mockFetch = jest.fn();
global.fetch = mockFetch;

const BASE = 'http://localhost:8000';

beforeEach(() => {
  jest.clearAllMocks();
  process.env.NEXT_PUBLIC_API_URL = BASE;
});

afterAll(() => {
  delete process.env.NEXT_PUBLIC_API_URL;
});

function mockCreated(overrides: Record<string, unknown> = {}) {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    status: 201,
    json: () =>
      Promise.resolve({
        id: 'new-user',
        username: 'new',
        email: 'new@example.com',
        full_name: null,
        is_active: true,
        is_superuser: false,
        role: 'DEVELOPER',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...overrides,
      }),
  } as Response);
}

describe('generateTemporaryPassword', () => {
  it('satisfies the UserCreate password rules', () => {
    for (let i = 0; i < 25; i++) {
      const pw = generateTemporaryPassword();
      expect(pw.length).toBeGreaterThanOrEqual(8);
      expect(pw).toMatch(/[A-Z]/);
      expect(pw).toMatch(/[a-z]/);
      expect(pw).toMatch(/[0-9]/);
    }
  });

  it('never returns fewer than 8 characters', () => {
    expect(generateTemporaryPassword(3).length).toBe(8);
  });
});

describe('usernameFromEmail', () => {
  it('uses the sanitised local part', () => {
    expect(usernameFromEmail('Jane.Doe+ops@example.com')).toBe('jane.doe-ops');
    expect(usernameFromEmail('--x--@example.com')).toBe('x');
    expect(usernameFromEmail('')).toBe('');
  });
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

  it('shows email, username, full name and role inputs', () => {
    render(<InviteUserModal {...defaultProps} />);
    expect(screen.getByTestId('invite-email-input')).toBeInTheDocument();
    expect(screen.getByTestId('invite-username-input')).toBeInTheDocument();
    expect(screen.getByTestId('invite-full-name-input')).toBeInTheDocument();
    expect(screen.getByTestId('invite-role-select')).toBeInTheDocument();
  });

  it('submit button disabled when email is empty', () => {
    render(<InviteUserModal {...defaultProps} />);
    expect(screen.getByTestId('invite-submit-button')).toBeDisabled();
  });

  it('derives the username from the email until it is edited', () => {
    render(<InviteUserModal {...defaultProps} />);
    fireEvent.change(screen.getByTestId('invite-email-input'), {
      target: { value: 'Jane.Doe@example.com' },
    });
    expect((screen.getByTestId('invite-username-input') as HTMLInputElement).value).toBe('jane.doe');

    fireEvent.change(screen.getByTestId('invite-username-input'), { target: { value: 'jdoe' } });
    fireEvent.change(screen.getByTestId('invite-email-input'), {
      target: { value: 'jane@example.com' },
    });
    expect((screen.getByTestId('invite-username-input') as HTMLInputElement).value).toBe('jdoe');
  });

  it('disables submit while the username is shorter than 3 characters', () => {
    render(<InviteUserModal {...defaultProps} />);
    fireEvent.change(screen.getByTestId('invite-email-input'), {
      target: { value: 'ab@example.com' },
    });
    expect(screen.getByTestId('invite-submit-button')).toBeDisabled();
    fireEvent.change(screen.getByTestId('invite-username-input'), { target: { value: 'abc' } });
    expect(screen.getByTestId('invite-submit-button')).not.toBeDisabled();
  });

  it('POSTs a UserCreate body to /api/v1/users/ and shows the temporary password once', async () => {
    const onClose = jest.fn();
    const onSuccess = jest.fn();
    mockCreated();

    render(<InviteUserModal isOpen={true} onClose={onClose} onSuccess={onSuccess} />);

    fireEvent.change(screen.getByTestId('invite-email-input'), {
      target: { value: 'new@example.com' },
    });
    fireEvent.change(screen.getByTestId('invite-full-name-input'), {
      target: { value: 'New Person' },
    });
    fireEvent.change(screen.getByTestId('invite-role-select'), { target: { value: 'DEVELOPER' } });

    const submitBtn = screen.getByTestId('invite-submit-button');
    expect(submitBtn).not.toBeDisabled();
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByTestId('invite-created')).toBeInTheDocument();
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockFetch.mock.calls[0];
    expect(url).toBe(`${BASE}/api/v1/users/`);
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({
      email: 'new@example.com',
      username: 'new',
      full_name: 'New Person',
      role: 'DEVELOPER',
      is_active: true,
      is_superuser: false,
    });
    expect(body.password).toMatch(/^(?=.*[A-Z])(?=.*[a-z])(?=.*[0-9]).{8,}$/);

    // The generated password is what the admin sees.
    expect(screen.getByTestId('invite-temp-password')).toHaveTextContent(body.password);
    expect(onSuccess).toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('invite-done-button'));
    expect(onClose).toHaveBeenCalled();
  });

  it('marks ADMIN invitees as superusers', async () => {
    mockCreated({ role: 'ADMIN', is_superuser: true });
    render(<InviteUserModal {...defaultProps} />);
    fireEvent.change(screen.getByTestId('invite-email-input'), {
      target: { value: 'root@example.com' },
    });
    fireEvent.change(screen.getByTestId('invite-role-select'), { target: { value: 'ADMIN' } });
    fireEvent.click(screen.getByTestId('invite-submit-button'));
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalled();
    });
    const body = JSON.parse(mockFetch.mock.calls[0][1].body);
    expect(body.role).toBe('ADMIN');
    expect(body.is_superuser).toBe(true);
  });

  it('shows the API error message when creation fails', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      statusText: 'Conflict',
      json: () => Promise.resolve({ detail: 'Email already registered' }),
    } as Response);

    render(<InviteUserModal {...defaultProps} />);

    fireEvent.change(screen.getByTestId('invite-email-input'), {
      target: { value: 'fail@example.com' },
    });
    fireEvent.click(screen.getByTestId('invite-submit-button'));

    await waitFor(() => {
      expect(screen.getByTestId('invite-error-message')).toHaveTextContent('Email already registered');
    });
    expect(screen.queryByTestId('invite-created')).not.toBeInTheDocument();
  });

  it('calls onClose when cancel button clicked', () => {
    const onClose = jest.fn();
    render(<InviteUserModal {...defaultProps} onClose={onClose} />);
    fireEvent.click(screen.getByTestId('invite-cancel-button'));
    expect(onClose).toHaveBeenCalled();
  });

  it('renders with data-testid="invite-user-modal"', () => {
    render(<InviteUserModal {...defaultProps} />);
    expect(screen.getByTestId('invite-user-modal')).toBeInTheDocument();
  });
});
