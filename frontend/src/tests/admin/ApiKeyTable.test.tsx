import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ApiKeyTable } from '@/components/admin/api-keys/ApiKeyTable';

interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  created_by: string;
  created_at: string;
  last_used?: string;
  is_active: boolean;
}

const makeApiKey = (overrides: Partial<ApiKey> = {}): ApiKey => ({
  id: 'key-1',
  name: 'My API Key',
  prefix: 'abcd1234',
  created_by: 'user-1',
  created_at: '2024-06-15T10:00:00Z',
  is_active: true,
  ...overrides,
});

const mockFetch = (responseData: unknown, ok = true, status = 200) => {
  return jest.fn().mockResolvedValue({
    ok,
    status,
    json: async () => responseData,
    statusText: ok ? 'OK' : 'Internal Server Error',
  });
};

beforeEach(() => {
  jest.clearAllMocks();
  window.confirm = jest.fn(() => true);
});

describe('ApiKeyTable', () => {
  it('renders loading state initially', () => {
    global.fetch = jest.fn().mockImplementation(() => new Promise(() => {}));
    render(<ApiKeyTable onCreateKey={jest.fn()} />);
    expect(screen.getByTestId('api-key-table-loading')).toBeInTheDocument();
  });

  it('renders api key rows after data loads (mock GET /api/v1/api-keys)', async () => {
    const keys = [
      makeApiKey({ id: 'key-1', name: 'Production Key' }),
      makeApiKey({ id: 'key-2', name: 'Dev Key', prefix: 'xyz99999' }),
    ];
    global.fetch = mockFetch(keys);
    render(<ApiKeyTable onCreateKey={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId('api-key-row-key-1')).toBeInTheDocument();
      expect(screen.getByTestId('api-key-row-key-2')).toBeInTheDocument();
    });
  });

  it('shows key name in each row', async () => {
    const keys = [makeApiKey({ id: 'key-1', name: 'My Important Key' })];
    global.fetch = mockFetch(keys);
    render(<ApiKeyTable onCreateKey={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByText('My Important Key')).toBeInTheDocument();
    });
  });

  it('shows created_at in each row', async () => {
    const keys = [makeApiKey({ id: 'key-1', created_at: '2024-06-15T10:00:00Z' })];
    global.fetch = mockFetch(keys);
    render(<ApiKeyTable onCreateKey={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId('created-at-key-1')).toBeInTheDocument();
    });
  });

  it('shows status badge (active/revoked)', async () => {
    const keys = [
      makeApiKey({ id: 'key-active', name: 'Active Key', is_active: true }),
      makeApiKey({ id: 'key-revoked', name: 'Revoked Key', is_active: false }),
    ];
    global.fetch = mockFetch(keys);
    render(<ApiKeyTable onCreateKey={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId('status-badge-key-active')).toHaveTextContent('active');
      expect(screen.getByTestId('status-badge-key-revoked')).toHaveTextContent('revoked');
    });
  });

  it('revoke button calls DELETE /api/v1/api-keys/{id} with confirmation', async () => {
    const keys = [makeApiKey({ id: 'key-99', name: 'To Revoke' })];
    const fetchMock = jest.fn()
      // First call: GET /api/v1/api-keys
      .mockResolvedValueOnce({
        ok: true,
        json: async () => keys,
      })
      // Second call: DELETE /api/v1/api-keys/key-99
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({}),
      })
      // Third call: GET /api/v1/api-keys (refetch)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [],
      });

    global.fetch = fetchMock;
    render(<ApiKeyTable onCreateKey={jest.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId('revoke-button-key-99')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('revoke-button-key-99'));

    await waitFor(() => {
      expect(window.confirm).toHaveBeenCalled();
      const deleteCall = fetchMock.mock.calls.find(
        (call: [string, ...unknown[]]) =>
          typeof call[0] === 'string' &&
          call[0].includes('/api/v1/api-keys/key-99') &&
          (call[1] as { method?: string })?.method === 'DELETE'
      );
      expect(deleteCall).toBeTruthy();
    });
  });

  it('shows empty state when no keys', async () => {
    global.fetch = mockFetch([]);
    render(<ApiKeyTable onCreateKey={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId('api-key-empty-state')).toBeInTheDocument();
    });
  });

  it('shows error state on fetch failure', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('Network error'));
    render(<ApiKeyTable onCreateKey={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId('api-key-error-state')).toBeInTheDocument();
    });
  });

  it('"Create API Key" button is rendered', async () => {
    global.fetch = mockFetch([]);
    render(<ApiKeyTable onCreateKey={jest.fn()} />);
    await waitFor(() => {
      expect(screen.getByTestId('create-api-key-button')).toBeInTheDocument();
    });
  });

  it('renders with data-testid="api-key-table"', () => {
    global.fetch = jest.fn().mockImplementation(() => new Promise(() => {}));
    render(<ApiKeyTable onCreateKey={jest.fn()} />);
    expect(screen.getByTestId('api-key-table')).toBeInTheDocument();
  });
});
