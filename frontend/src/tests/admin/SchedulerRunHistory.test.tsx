import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { SchedulerRunHistory } from '@/components/admin/scheduler/SchedulerRunHistory';
import { AdminService } from '@/services/admin';
import { SchedulerRun } from '@/types/admin';

jest.mock('@/services/admin');

const mockGetSchedulerHistory = AdminService.getSchedulerHistory as jest.Mock;

const makeRun = (overrides: Partial<SchedulerRun> = {}): SchedulerRun => ({
  id: 'run-1',
  scheduler_name: 'experiment-scheduler',
  started_at: '2024-06-15T10:00:00Z',
  completed_at: '2024-06-15T10:00:05Z',
  duration_ms: 5000,
  outcome: 'success',
  error_message: undefined,
  ...overrides,
});

beforeEach(() => {
  jest.clearAllMocks();
});

describe('SchedulerRunHistory', () => {
  it('renders loading state while fetching', () => {
    mockGetSchedulerHistory.mockImplementation(() => new Promise(() => {}));
    render(<SchedulerRunHistory schedulerName="experiment-scheduler" />);
    expect(screen.getByTestId('run-history-loading')).toBeInTheDocument();
  });

  it('renders run history rows after load', async () => {
    mockGetSchedulerHistory.mockResolvedValue([
      makeRun({ id: 'run-1' }),
      makeRun({ id: 'run-2', duration_ms: 3000 }),
    ]);
    render(<SchedulerRunHistory schedulerName="experiment-scheduler" />);
    await waitFor(() => {
      expect(screen.getByTestId('run-row-run-1')).toBeInTheDocument();
      expect(screen.getByTestId('run-row-run-2')).toBeInTheDocument();
    });
  });

  it('shows outcome badge: success=green, error=red', async () => {
    mockGetSchedulerHistory.mockResolvedValue([
      makeRun({ id: 'run-ok', outcome: 'success' }),
      makeRun({ id: 'run-err', outcome: 'error', error_message: 'Something went wrong' }),
    ]);
    render(<SchedulerRunHistory schedulerName="experiment-scheduler" />);
    await waitFor(() => {
      const successBadge = screen.getByTestId('outcome-badge-run-ok');
      const errorBadge = screen.getByTestId('outcome-badge-run-err');
      expect(successBadge.className).toMatch(/green/i);
      expect(errorBadge.className).toMatch(/red/i);
    });
  });

  it('shows duration in ms', async () => {
    mockGetSchedulerHistory.mockResolvedValue([
      makeRun({ id: 'run-1', duration_ms: 1234 }),
    ]);
    render(<SchedulerRunHistory schedulerName="experiment-scheduler" />);
    await waitFor(() => {
      expect(screen.getByTestId('duration-run-1')).toHaveTextContent('1234');
    });
  });

  it('shows error_message when outcome is error', async () => {
    mockGetSchedulerHistory.mockResolvedValue([
      makeRun({ id: 'run-err', outcome: 'error', error_message: 'DB connection failed' }),
    ]);
    render(<SchedulerRunHistory schedulerName="experiment-scheduler" />);
    await waitFor(() => {
      expect(screen.getByText('DB connection failed')).toBeInTheDocument();
    });
  });

  it('renders with data-testid="scheduler-run-history"', () => {
    mockGetSchedulerHistory.mockImplementation(() => new Promise(() => {}));
    render(<SchedulerRunHistory schedulerName="experiment-scheduler" />);
    expect(screen.getByTestId('scheduler-run-history')).toBeInTheDocument();
  });
});
