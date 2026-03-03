import React from 'react';
import { render, screen } from '@testing-library/react';
import { DeliveryLogTable } from '../../../components/admin/notifications/DeliveryLogTable';
import { NotificationDeliveryLog } from '../../../types/admin';

const mockLogs: NotificationDeliveryLog[] = [
  {
    id: 'log-001',
    event_type: 'experiment_started',
    channel: 'slack',
    recipient: '#experiments',
    subject: null,
    status: 'sent',
    error_message: null,
    created_at: '2024-01-01T10:00:00Z',
  },
  {
    id: 'log-002',
    event_type: 'safety_rollback',
    channel: 'email',
    recipient: 'admin@example.com',
    subject: 'Safety Rollback Alert',
    status: 'failed',
    error_message: 'SMTP connection failed',
    created_at: '2024-01-01T11:00:00Z',
  },
  {
    id: 'log-003',
    event_type: 'rollout_advanced',
    channel: 'webhook',
    recipient: 'https://hooks.example.com/notify',
    subject: null,
    status: 'skipped',
    error_message: null,
    created_at: '2024-01-01T12:00:00Z',
  },
];

describe('DeliveryLogTable', () => {
  it('renders_empty_state_when_no_logs', () => {
    render(<DeliveryLogTable logs={[]} />);
    expect(screen.getByTestId('empty-state')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state')).toHaveTextContent('No delivery log entries found.');
  });

  it('renders_loading_indicator_when_loading', () => {
    render(<DeliveryLogTable logs={[]} loading={true} />);
    expect(screen.getByTestId('loading-indicator')).toBeInTheDocument();
    expect(screen.getByTestId('loading-indicator')).toHaveTextContent('Loading delivery log...');
  });

  it('renders_table_with_log_entries', () => {
    render(<DeliveryLogTable logs={mockLogs} />);
    expect(screen.getByTestId('delivery-log-table')).toBeInTheDocument();
    expect(screen.getByTestId('log-row-log-001')).toBeInTheDocument();
    expect(screen.getByTestId('log-row-log-002')).toBeInTheDocument();
    expect(screen.getByTestId('log-row-log-003')).toBeInTheDocument();
  });

  it('shows_status_badge_for_each_log', () => {
    render(<DeliveryLogTable logs={mockLogs} />);
    expect(screen.getByText('sent')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText('skipped')).toBeInTheDocument();
  });

  it('shows_correct_channel_for_each_log', () => {
    render(<DeliveryLogTable logs={mockLogs} />);
    expect(screen.getByText('slack')).toBeInTheDocument();
    expect(screen.getByText('email')).toBeInTheDocument();
    expect(screen.getByText('webhook')).toBeInTheDocument();
  });

  it('renders_log_row_with_test_id', () => {
    render(<DeliveryLogTable logs={mockLogs} />);
    const row = screen.getByTestId('log-row-log-001');
    expect(row).toBeInTheDocument();
    expect(row).toHaveTextContent('experiment_started');
  });
});
