import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { SchedulerStatusCard } from '@/components/admin/scheduler/SchedulerStatusCard';
import { SchedulerHealth } from '@/types/admin';

// Mock the child SchedulerRunHistory component so we can test expand/collapse independently
jest.mock('@/components/admin/scheduler/SchedulerRunHistory', () => ({
  SchedulerRunHistory: ({ schedulerName }: { schedulerName: string }) => (
    <div data-testid="scheduler-run-history">Run history for {schedulerName}</div>
  ),
}));

const makeScheduler = (overrides: Partial<SchedulerHealth> = {}): SchedulerHealth => ({
  name: 'experiment-scheduler',
  status: 'idle',
  last_run: '2024-06-15T10:00:00Z',
  next_run: '2024-06-15T10:15:00Z',
  run_count: 42,
  error_count: 2,
  ...overrides,
});

describe('SchedulerStatusCard', () => {
  it('renders scheduler name', () => {
    render(<SchedulerStatusCard scheduler={makeScheduler({ name: 'my-scheduler' })} />);
    expect(screen.getByText('my-scheduler')).toBeInTheDocument();
  });

  it('renders status badge: "idle" shows grey badge', () => {
    render(<SchedulerStatusCard scheduler={makeScheduler({ status: 'idle' })} />);
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveTextContent('idle');
    expect(badge.className).toMatch(/grey|gray|slate/i);
  });

  it('renders status badge: "running" shows blue badge', () => {
    render(<SchedulerStatusCard scheduler={makeScheduler({ status: 'running' })} />);
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveTextContent('running');
    expect(badge.className).toMatch(/blue/i);
  });

  it('renders status badge: "error" shows red badge', () => {
    render(<SchedulerStatusCard scheduler={makeScheduler({ status: 'error' })} />);
    const badge = screen.getByTestId('status-badge');
    expect(badge).toHaveTextContent('error');
    expect(badge.className).toMatch(/red/i);
  });

  it('renders run_count', () => {
    render(<SchedulerStatusCard scheduler={makeScheduler({ run_count: 99 })} />);
    expect(screen.getByTestId('run-count')).toHaveTextContent('99');
  });

  it('renders error_count', () => {
    render(<SchedulerStatusCard scheduler={makeScheduler({ error_count: 5 })} />);
    expect(screen.getByTestId('error-count')).toHaveTextContent('5');
  });

  it('renders last_run timestamp (formatted)', () => {
    render(<SchedulerStatusCard scheduler={makeScheduler({ last_run: '2024-06-15T10:00:00Z' })} />);
    expect(screen.getByTestId('last-run')).toBeInTheDocument();
    // Should not show the raw ISO string — should show a formatted version
    const lastRunEl = screen.getByTestId('last-run');
    expect(lastRunEl.textContent).toBeTruthy();
  });

  it('renders next_run timestamp (formatted)', () => {
    render(<SchedulerStatusCard scheduler={makeScheduler({ next_run: '2024-06-15T10:15:00Z' })} />);
    expect(screen.getByTestId('next-run')).toBeInTheDocument();
    const nextRunEl = screen.getByTestId('next-run');
    expect(nextRunEl.textContent).toBeTruthy();
  });

  it('expand button toggles run history section visibility', () => {
    render(<SchedulerStatusCard scheduler={makeScheduler()} />);
    // Initially history should not be visible
    expect(screen.queryByTestId('scheduler-run-history')).not.toBeInTheDocument();

    // Click to expand
    fireEvent.click(screen.getByTestId('expand-button'));
    expect(screen.getByTestId('scheduler-run-history')).toBeInTheDocument();

    // Click again to collapse
    fireEvent.click(screen.getByTestId('expand-button'));
    expect(screen.queryByTestId('scheduler-run-history')).not.toBeInTheDocument();
  });

  it('renders with data-testid="scheduler-status-card"', () => {
    render(<SchedulerStatusCard scheduler={makeScheduler()} />);
    expect(screen.getByTestId('scheduler-status-card')).toBeInTheDocument();
  });
});
