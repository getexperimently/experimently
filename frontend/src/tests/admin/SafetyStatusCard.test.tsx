import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { SafetyStatusCard } from '@/components/admin/safety/SafetyStatusCard';
import { flagHealth, toFlagSafetyStatus } from '@/services/admin';
import { FlagSafetyStatus } from '@/types/admin';
import { SafetyCheckResponse, SafetyMetricStatus } from '@/types/safety';

const metric = (overrides: Partial<SafetyMetricStatus> = {}): SafetyMetricStatus => ({
  name: 'error_rate',
  current_value: 0.025,
  threshold: 0.05,
  is_healthy: true,
  details: { warning: false, measured: true },
  ...overrides,
});

const check = (overrides: Partial<SafetyCheckResponse> = {}): SafetyCheckResponse => ({
  feature_flag_id: 'flag-123',
  is_healthy: true,
  metrics: [metric(), metric({ name: 'latency', current_value: 120, threshold: 500 })],
  last_checked: '2026-01-01T00:00:00Z',
  details: { feature_flag_key: 'my-feature-flag' },
  ...overrides,
});

const makeFlag = (overrides: Partial<FlagSafetyStatus> = {}): FlagSafetyStatus => ({
  ...toFlagSafetyStatus({ id: 'flag-123', name: 'my-feature-flag', key: 'my-feature-flag' }, check()),
  ...overrides,
});

describe('toFlagSafetyStatus / flagHealth', () => {
  it('maps a healthy check to "healthy" with error rate and latency metrics', () => {
    const status = toFlagSafetyStatus({ id: 'f', name: 'Flag', key: 'flag' }, check());
    expect(status.health).toBe('healthy');
    expect(status.error_rate).toBe(0.025);
    expect(status.latency_ms).toBe(120);
    expect(status.flag_key).toBe('flag');
  });

  it('is "critical" when the backend reports unhealthy', () => {
    expect(flagHealth(check({ is_healthy: false }))).toBe('critical');
  });

  it('is "warning" when a metric breached its warning threshold only', () => {
    const c = check({ metrics: [metric({ details: { warning: true, measured: true } })] });
    expect(flagHealth(c)).toBe('warning');
  });

  it('reports null for metrics the backend could not measure', () => {
    const c = check({
      metrics: [metric({ details: { warning: false, measured: false } })],
      details: { unmeasured_metrics: ['error_rate'] },
    });
    const status = toFlagSafetyStatus({ id: 'f', name: 'Flag', key: 'flag' }, c);
    expect(status.error_rate).toBeNull();
    expect(status.latency_ms).toBeNull();
  });
});

describe('SafetyStatusCard', () => {
  it('renders flag name and key', () => {
    const flag = makeFlag({ flag_name: 'Checkout v2', flag_key: 'checkout-v2' });
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    expect(screen.getByText('Checkout v2')).toBeInTheDocument();
    expect(screen.getByText('checkout-v2')).toBeInTheDocument();
  });

  it('renders error_rate fraction as a percentage', () => {
    const flag = makeFlag({ error_rate: 0.0375 });
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    expect(screen.getByTestId('error-rate-value')).toHaveTextContent('3.75%');
  });

  it('renders latency with "ms" suffix', () => {
    const flag = makeFlag({ latency_ms: 250 });
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    expect(screen.getByTestId('latency-value')).toHaveTextContent('250 ms');
  });

  it('renders n/a when a metric is not measured', () => {
    const flag = makeFlag({ error_rate: null, latency_ms: null });
    render(<SafetyStatusCard flag={flag} onRollback={jest.fn()} />);
    expect(screen.getByTestId('error-rate-value')).toHaveTextContent('n/a');
    expect(screen.getByTestId('latency-value')).toHaveTextContent('n/a');
  });

  it('shows green badge for "healthy"', () => {
    render(<SafetyStatusCard flag={makeFlag({ health: 'healthy' })} onRollback={jest.fn()} />);
    expect(screen.getByTestId('status-badge')).toHaveClass('bg-green-100');
  });

  it('shows yellow badge for "warning"', () => {
    render(<SafetyStatusCard flag={makeFlag({ health: 'warning' })} onRollback={jest.fn()} />);
    expect(screen.getByTestId('status-badge')).toHaveClass('bg-yellow-100');
  });

  it('shows red badge for "critical"', () => {
    render(<SafetyStatusCard flag={makeFlag({ health: 'critical' })} onRollback={jest.fn()} />);
    expect(screen.getByTestId('status-badge')).toHaveClass('bg-red-100');
  });

  it('"Rollback" button is visible for critical/warning only and reports the flag id', () => {
    const onRollback = jest.fn();
    const { rerender } = render(
      <SafetyStatusCard flag={makeFlag({ health: 'warning' })} onRollback={onRollback} />,
    );
    fireEvent.click(screen.getByTestId('rollback-button'));
    expect(onRollback).toHaveBeenCalledWith('flag-123');

    rerender(<SafetyStatusCard flag={makeFlag({ health: 'critical' })} onRollback={onRollback} />);
    expect(screen.getByTestId('rollback-button')).toBeInTheDocument();

    rerender(<SafetyStatusCard flag={makeFlag({ health: 'healthy' })} onRollback={onRollback} />);
    expect(screen.queryByTestId('rollback-button')).not.toBeInTheDocument();
  });

  it('notes when no metrics are configured or some are unmeasured', () => {
    const none = makeFlag({ check: check({ metrics: [] }) });
    const { rerender } = render(<SafetyStatusCard flag={none} onRollback={jest.fn()} />);
    expect(screen.getByTestId('safety-disabled-note')).toBeInTheDocument();

    const partial = makeFlag({ check: check({ details: { unmeasured_metrics: ['latency'] } }) });
    rerender(<SafetyStatusCard flag={partial} onRollback={jest.fn()} />);
    expect(screen.getByTestId('safety-unmeasured-note')).toHaveTextContent('latency');
  });

  it('renders with data-testid="safety-status-card"', () => {
    render(<SafetyStatusCard flag={makeFlag()} onRollback={jest.fn()} />);
    expect(screen.getByTestId('safety-status-card')).toBeInTheDocument();
  });
});
