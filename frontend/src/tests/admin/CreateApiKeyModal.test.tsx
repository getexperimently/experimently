import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CreateApiKeyModal } from '@/components/admin/api-keys/CreateApiKeyModal';

beforeEach(() => {
  jest.clearAllMocks();
});

const defaultProps = {
  isOpen: true,
  onClose: jest.fn(),
  onSuccess: jest.fn(),
};

describe('CreateApiKeyModal', () => {
  it('renders when isOpen=true', () => {
    global.fetch = jest.fn();
    render(<CreateApiKeyModal {...defaultProps} isOpen={true} />);
    expect(screen.getByTestId('create-api-key-modal')).toBeInTheDocument();
  });

  it('does not render when isOpen=false', () => {
    global.fetch = jest.fn();
    render(<CreateApiKeyModal {...defaultProps} isOpen={false} />);
    expect(screen.queryByTestId('create-api-key-modal')).not.toBeInTheDocument();
  });

  it('shows name input', () => {
    global.fetch = jest.fn();
    render(<CreateApiKeyModal {...defaultProps} />);
    expect(screen.getByTestId('api-key-name-input')).toBeInTheDocument();
  });

  it('shows permission scope checkboxes or select', () => {
    global.fetch = jest.fn();
    render(<CreateApiKeyModal {...defaultProps} />);
    // Scope selection — should have at least one scope option
    expect(screen.getByTestId('api-key-scope-input')).toBeInTheDocument();
  });

  it('submit disabled when name empty', () => {
    global.fetch = jest.fn();
    render(<CreateApiKeyModal {...defaultProps} />);
    expect(screen.getByTestId('create-api-key-submit')).toBeDisabled();
  });

  it('calls onSuccess with the new key on successful creation (mock fetch POST /api/v1/api-keys)', async () => {
    const createdKey = {
      id: 'new-key-id',
      name: 'Test Key',
      key_value: 'abcdefgh_very_long_secret_key_value',
      prefix: 'abcdefgh',
      created_at: '2024-06-15T10:00:00Z',
      is_active: true,
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => createdKey,
    });

    const onSuccess = jest.fn();
    render(<CreateApiKeyModal {...defaultProps} onSuccess={onSuccess} />);

    fireEvent.change(screen.getByTestId('api-key-name-input'), {
      target: { value: 'Test Key' },
    });

    fireEvent.click(screen.getByTestId('create-api-key-submit'));

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalledWith(createdKey.key_value);
    });
  });

  it('shows created key value (masked to first 8 chars + "...") after creation', async () => {
    const createdKey = {
      id: 'new-key-id',
      name: 'Test Key',
      key_value: 'abcdefghXXXXXXXXXXXXXXXXXXXX',
      prefix: 'abcdefgh',
      created_at: '2024-06-15T10:00:00Z',
      is_active: true,
    };
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => createdKey,
    });

    render(<CreateApiKeyModal {...defaultProps} />);

    fireEvent.change(screen.getByTestId('api-key-name-input'), {
      target: { value: 'Test Key' },
    });

    fireEvent.click(screen.getByTestId('create-api-key-submit'));

    await waitFor(() => {
      const maskedKey = screen.getByTestId('masked-key-value');
      expect(maskedKey).toBeInTheDocument();
      // Should show first 8 chars + "..."
      expect(maskedKey.textContent).toContain('abcdefgh');
      expect(maskedKey.textContent).toContain('...');
    });
  });

  it('renders with data-testid="create-api-key-modal"', () => {
    global.fetch = jest.fn();
    render(<CreateApiKeyModal {...defaultProps} />);
    expect(screen.getByTestId('create-api-key-modal')).toBeInTheDocument();
  });
});
