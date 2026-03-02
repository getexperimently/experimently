import React from 'react';
import { render, screen } from '@testing-library/react';
import { AuditLogDetailPanel } from '@/components/admin/audit/AuditLogDetailPanel';
import { AuditLog } from '@/types/admin';

const mockLog: AuditLog = {
  id: 'log-42',
  user_id: 'user-1',
  user_email: 'bob@example.com',
  action_type: 'feature_flag_update',
  entity_type: 'feature_flag',
  entity_id: 'flag-99',
  entity_name: 'dark-mode-flag',
  old_value: { enabled: false, rollout: 10 },
  new_value: { enabled: true, rollout: 50 },
  reason: 'Gradual rollout approved',
  timestamp: '2024-07-01T14:00:00Z',
  created_at: '2024-07-01T14:00:00Z',
  action_description: 'Updated feature flag dark-mode-flag',
};

const mockOnClose = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
});

describe('AuditLogDetailPanel', () => {
  it('renders user email', () => {
    render(<AuditLogDetailPanel log={mockLog} onClose={mockOnClose} />);
    expect(screen.getByText('bob@example.com')).toBeInTheDocument();
  });

  it('renders action description', () => {
    render(<AuditLogDetailPanel log={mockLog} onClose={mockOnClose} />);
    expect(screen.getByText('Updated feature flag dark-mode-flag')).toBeInTheDocument();
  });

  it('renders entity name and type', () => {
    render(<AuditLogDetailPanel log={mockLog} onClose={mockOnClose} />);
    expect(screen.getByText('dark-mode-flag')).toBeInTheDocument();
    expect(screen.getByText('feature_flag')).toBeInTheDocument();
  });

  it('renders reason when present', () => {
    render(<AuditLogDetailPanel log={mockLog} onClose={mockOnClose} />);
    expect(screen.getByText('Gradual rollout approved')).toBeInTheDocument();
  });

  it('renders JsonDiffViewer with old/new values', () => {
    render(<AuditLogDetailPanel log={mockLog} onClose={mockOnClose} />);
    expect(screen.getByTestId('json-diff-viewer')).toBeInTheDocument();
  });

  it('renders with data-testid="audit-log-detail-panel"', () => {
    render(<AuditLogDetailPanel log={mockLog} onClose={mockOnClose} />);
    expect(screen.getByTestId('audit-log-detail-panel')).toBeInTheDocument();
  });
});
