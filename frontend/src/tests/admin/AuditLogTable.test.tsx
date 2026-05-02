import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AuditLogTable } from '@/components/admin/audit/AuditLogTable';
import { AdminService } from '@/services/admin';
import { AuditLog, AuditLogListResponse } from '@/types/admin';

jest.mock('@/services/admin');

const mockListAuditLogs = AdminService.listAuditLogs as jest.Mock;

const makeLog = (overrides: Partial<AuditLog> = {}): AuditLog => ({
  id: 'log-1',
  user_id: 'user-1',
  user_email: 'alice@example.com',
  action_type: 'toggle_enable',
  entity_type: 'feature_flag',
  entity_id: 'flag-1',
  entity_name: 'my-feature-flag',
  old_value: { enabled: false },
  new_value: { enabled: true },
  reason: 'Enabling for beta users',
  timestamp: '2024-06-15T10:30:00Z',
  created_at: '2024-06-15T10:30:00Z',
  action_description: 'Enabled feature flag my-feature-flag',
  ...overrides,
});

const makePage = (overrides: Partial<AuditLogListResponse> = {}): AuditLogListResponse => ({
  items: [makeLog()],
  total: 1,
  page: 1,
  limit: 50,
  ...overrides,
});

beforeEach(() => {
  jest.clearAllMocks();
});

describe('AuditLogTable', () => {
  it('renders loading state initially', () => {
    mockListAuditLogs.mockImplementation(() => new Promise(() => {}));
    render(<AuditLogTable />);
    expect(screen.getByTestId('audit-log-table-loading')).toBeInTheDocument();
  });

  it('renders audit log rows after data loads', async () => {
    mockListAuditLogs.mockResolvedValue(makePage());
    render(<AuditLogTable />);
    await waitFor(() => {
      expect(screen.getByTestId('audit-log-row-log-1')).toBeInTheDocument();
    });
  });

  it('shows user_email, action_type, entity_type, entity_name in each row', async () => {
    mockListAuditLogs.mockResolvedValue(makePage());
    render(<AuditLogTable />);
    await waitFor(() => {
      expect(screen.getByText('alice@example.com')).toBeInTheDocument();
      expect(screen.getByText('toggle_enable')).toBeInTheDocument();
      expect(screen.getByText('feature_flag')).toBeInTheDocument();
      expect(screen.getByText('my-feature-flag')).toBeInTheDocument();
    });
  });

  it('shows formatted timestamp', async () => {
    mockListAuditLogs.mockResolvedValue(makePage());
    render(<AuditLogTable />);
    await waitFor(() => {
      // The timestamp should be displayed in some readable format
      const row = screen.getByTestId('audit-log-row-log-1');
      expect(row).toBeInTheDocument();
      // The raw ISO or a formatted version should appear in the document
      expect(screen.getByTestId('timestamp-log-1')).toBeInTheDocument();
    });
  });

  it('clicking a row expands detail panel', async () => {
    mockListAuditLogs.mockResolvedValue(makePage());
    render(<AuditLogTable />);
    await waitFor(() => {
      expect(screen.getByTestId('audit-log-row-log-1')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('audit-log-row-log-1'));
    expect(screen.getByTestId('audit-log-detail-panel')).toBeInTheDocument();
  });

  it('expanded row shows old_value and new_value', async () => {
    mockListAuditLogs.mockResolvedValue(makePage());
    render(<AuditLogTable />);
    await waitFor(() => {
      expect(screen.getByTestId('audit-log-row-log-1')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('audit-log-row-log-1'));
    expect(screen.getByTestId('audit-log-detail-panel')).toBeInTheDocument();
    expect(screen.getByTestId('json-diff-viewer')).toBeInTheDocument();
  });

  it('expanded row shows reason if present', async () => {
    mockListAuditLogs.mockResolvedValue(makePage());
    render(<AuditLogTable />);
    await waitFor(() => {
      expect(screen.getByTestId('audit-log-row-log-1')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('audit-log-row-log-1'));
    expect(screen.getByText('Enabling for beta users')).toBeInTheDocument();
  });

  it('shows pagination controls', async () => {
    mockListAuditLogs.mockResolvedValue(makePage({ total: 100, page: 1, limit: 50 }));
    render(<AuditLogTable />);
    await waitFor(() => {
      expect(screen.getByTestId('pagination-prev')).toBeInTheDocument();
      expect(screen.getByTestId('pagination-next')).toBeInTheDocument();
      expect(screen.getByTestId('pagination-label')).toBeInTheDocument();
    });
  });

  it('next page button calls listAuditLogs with page+1', async () => {
    mockListAuditLogs.mockResolvedValue(makePage({ total: 100, page: 1, limit: 50 }));
    render(<AuditLogTable />);
    await waitFor(() => {
      expect(screen.getByTestId('pagination-next')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('pagination-next'));
    await waitFor(() => {
      expect(mockListAuditLogs).toHaveBeenCalledWith(
        expect.objectContaining({ page: 2 })
      );
    });
  });

  it('shows empty state when no logs', async () => {
    mockListAuditLogs.mockResolvedValue(makePage({ items: [], total: 0 }));
    render(<AuditLogTable />);
    await waitFor(() => {
      expect(screen.getByTestId('audit-log-empty-state')).toBeInTheDocument();
    });
  });

  it('shows error state on failure', async () => {
    mockListAuditLogs.mockRejectedValue(new Error('Network error'));
    render(<AuditLogTable />);
    await waitFor(() => {
      expect(screen.getByTestId('audit-log-error-state')).toBeInTheDocument();
    });
  });

  it('renders with data-testid="audit-log-table"', async () => {
    mockListAuditLogs.mockResolvedValue(makePage());
    render(<AuditLogTable />);
    expect(screen.getByTestId('audit-log-table')).toBeInTheDocument();
    await screen.findByTestId('audit-log-row-log-1');
  });
});
