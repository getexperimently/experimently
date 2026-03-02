import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { SafetyStatusCard } from '@/components/admin/safety/SafetyStatusCard';
import { FlagSafetyStatus } from '@/types/admin';

const makeFlag = (overrides: Partial<FlagSafetyStatus> = {}): FlagSafetyStatus => ({
  flag_id: 'flag-123',
  flag_name: 'my-feature-flag',
  current_error_rate: 2.5,
  current_latency_ms: 120,
  status: 'healthy',
  ...overrides,
});

describe('SafetyStatusCard', () => {
  it('renders flag_name', () => {
    const flag = makeFlag({ flag_name: 'checkout-v2' });
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    expect(screen.getByText('checkout-v2')).toBeInTheDocument();
  });

  it('renders current_error_rate as percentage', () => {
    const flag = makeFlag({ current_error_rate: 3.75 });
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    expect(screen.getByText(/3\.75%/)).toBeInTheDocument();
  });

  it('renders current_latency_ms with "ms" suffix', () => {
    const flag = makeFlag({ current_latency_ms: 250 });
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    expect(screen.getByText(/250\s*ms/)).toBeInTheDocument();
  });

  it('shows green badge for "healthy" status', () => {
    const flag = makeFlag({ status: 'healthy' });
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-green-100');
  });

  it('shows yellow badge for "warning" status', () => {
    const flag = makeFlag({ status: 'warning' });
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-yellow-100');
  });

  it('shows red badge for "critical" status', () => {
    const flag = makeFlag({ status: 'critical' });
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveClass('bg-red-100');
  });

  it('"Rollback" button is visible for critical/warning status', () => {
    const warningFlag = makeFlag({ status: 'warning' });
    const { rerender } = render(<SafetyStatusCard flag={warningFlag} onRollback={jest.fn()} />);
    expect(screen.getByTestId('rollback-button')).toBeInTheDocument();

    const criticalFlag = makeFlag({ status: 'critical' });
    rerender(<SafetyStatusCard flag={criticalFlag} onRollback={jest.fn()} />);
    expect(screen.getByTestId('rollback-button')).toBeInTheDocument();

    const healthyFlag = makeFlag({ status: 'healthy' });
    rerender(<SafetyStatusCard flag={healthyFlag} onRollback={jest.fn()} />);
    expect(screen.queryByTestId('rollback-button')).not.toBeInTheDocument();
  });

  it('renders with data-testid="safety-status-card"', () => {
    const flag = makeFlag();
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    expect(screen.getByTestId('safety-status-card')).toBeInTheDocument();
  });
});
