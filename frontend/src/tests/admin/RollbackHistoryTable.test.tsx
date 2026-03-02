import React from 'react';
import { render, screen } from '@testing-library/react';
import { RollbackHistoryTable } from '@/components/admin/safety/RollbackHistoryTable';
import { RollbackRecord } from '@/types/admin';

const makeRecord = (overrides: Partial<RollbackRecord> = {}): RollbackRecord => ({
  id: 'rollback-1',
  flag_id: 'flag-123',
  flag_name: 'payments-v2',
  rolled_back_by: 'alice@example.com',
  reason: 'High error rate detected',
  timestamp: '2024-06-15T10:30:00Z',
  ...overrides,
});

describe('RollbackHistoryTable', () => {
  it('renders table headers', () => {
    render(<RollbackHistoryTable rollbacks={[makeRecord()]} />);
    expect(screen.getByText('Flag')).toBeInTheDocument();
    expect(screen.getByText('Rolled Back By')).toBeInTheDocument();
    expect(screen.getByText('Reason')).toBeInTheDocument();
    expect(screen.getByText('Timestamp')).toBeInTheDocument();
  });

  it('renders each rollback record row', () => {
    const records = [
      makeRecord({ id: 'rollback-1' }),
      makeRecord({ id: 'rollback-2', flag_name: 'auth-service' }),
    ];
    render(<RollbackHistoryTable rollbacks={records} />);
    expect(screen.getByTestId('rollback-row-rollback-1')).toBeInTheDocument();
    expect(screen.getByTestId('rollback-row-rollback-2')).toBeInTheDocument();
  });

  it('shows flag_name in each row', () => {
    const records = [
      makeRecord({ flag_name: 'payments-v2' }),
      makeRecord({ id: 'rollback-2', flag_name: 'auth-service' }),
    ];
    render(<RollbackHistoryTable rollbacks={records} />);
    expect(screen.getByText('payments-v2')).toBeInTheDocument();
    expect(screen.getByText('auth-service')).toBeInTheDocument();
  });

  it('shows rolled_back_by in each row', () => {
    const records = [
      makeRecord({ rolled_back_by: 'alice@example.com' }),
      makeRecord({ id: 'rollback-2', rolled_back_by: 'bob@example.com' }),
    ];
    render(<RollbackHistoryTable rollbacks={records} />);
    expect(screen.getByText('alice@example.com')).toBeInTheDocument();
    expect(screen.getByText('bob@example.com')).toBeInTheDocument();
  });

  it('shows empty state when rollbacks is empty', () => {
    render(<RollbackHistoryTable rollbacks={[]} />);
    expect(screen.getByTestId('rollback-empty-state')).toBeInTheDocument();
    expect(screen.getByText('No rollbacks recorded')).toBeInTheDocument();
  });

  it('renders with data-testid="rollback-history-table"', () => {
    render(<RollbackHistoryTable rollbacks={[]} />);
    expect(screen.getByTestId('rollback-history-table')).toBeInTheDocument();
  });
});
