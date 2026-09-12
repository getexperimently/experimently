import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SafetyDashboard, SAFETY_CHECK_CONCURRENCY } from '@/pages/admin/safety';
import { AdminService } from '@/services/admin';
import { ApiError } from '@/services/api';
import { FeatureFlagsService } from '@/services/featureFlags';
import { SafetySettings } from '@/types/admin';
import { SafetyCheckResponse } from '@/types/safety';

jest.mock('@/services/admin', () => {
  const actual = jest.requireActual('@/services/admin');
  return {
    ...actual,
    AdminService: {
      getSafetySettings: jest.fn(),
      updateSafetySettings: jest.fn(),
      rollbackFlag: jest.fn(),
    },
  };
});

jest.mock('@/services/featureFlags', () => ({
  FeatureFlagsService: { list: jest.fn(), safetyCheck: jest.fn() },
}));

// Mock AdminLayout
jest.mock('@/components/admin/AdminLayout', () => ({
  AdminLayout: ({ children, title }: { children: React.ReactNode; title: string }) => (
    <div data-testid="admin-layout">
      <h1>{title}</h1>
      {children}
    </div>
  ),
}));

// Mock SafetySettingsForm
jest.mock('@/components/admin/safety/SafetySettingsForm', () => ({
  SafetySettingsForm: () => <div data-testid="safety-settings-form">Safety Settings Form</div>,
}));

// Mock SafetyStatusCard
jest.mock('@/components/admin/safety/SafetyStatusCard', () => ({
  SafetyStatusCard: ({
    flag,
    onRollback,
  }: {
    flag: { flag_id: string; flag_name: string; health: string };
    onRollback: (id: string) => void;
  }) => (
    <div data-testid="safety-status-card" data-health={flag.health}>
      <span>{flag.flag_name}</span>
      <button data-testid="rollback-button" onClick={() => onRollback(flag.flag_id)}>
        Rollback
      </button>
    </div>
  ),
}));

// Mock RollbackHistoryTable
jest.mock('@/components/admin/safety/RollbackHistoryTable', () => ({
  RollbackHistoryTable: ({ rollbacks }: { rollbacks: { flag_name: string; reason: string }[] }) => (
    <div data-testid="rollback-history-table">
      Rollback History ({rollbacks.length})
      {rollbacks.map((r, i) => (
        <span key={i} data-testid="rollback-history-row">
          {r.flag_name}: {r.reason}
        </span>
      ))}
    </div>
  ),
}));

// Mock Next.js router
jest.mock('next/router', () => ({
  useRouter: () => ({
    pathname: '/admin/safety',
    push: jest.fn(),
  }),
}));

const mockSettings: SafetySettings = {
  id: 'settings-1',
  enable_automatic_rollbacks: false,
  default_metrics: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const flags = [
  { id: 'flag-1', key: 'checkout-v2', name: 'Checkout v2', rollout_percentage: 50, owner_id: null, created_at: '', updated_at: '' },
  { id: 'flag-2', key: 'payments', name: 'Payments redesign', rollout_percentage: 25, owner_id: null, created_at: '', updated_at: '' },
];

const healthyCheck: SafetyCheckResponse = {
  feature_flag_id: 'flag-1',
  is_healthy: true,
  metrics: [],
  last_checked: '2026-01-01T00:00:00Z',
  details: null,
};

const criticalCheck: SafetyCheckResponse = {
  feature_flag_id: 'flag-2',
  is_healthy: false,
  metrics: [
    {
      name: 'error_rate',
      current_value: 0.12,
      threshold: 0.05,
      is_healthy: false,
      details: { warning: true, measured: true },
    },
  ],
  last_checked: '2026-01-01T00:00:00Z',
  details: null,
};

const mockGetSafetySettings = AdminService.getSafetySettings as jest.Mock;
const mockGetFlagSafetyStatus = FeatureFlagsService.safetyCheck as jest.Mock;
const mockRollbackFlag = AdminService.rollbackFlag as jest.Mock;
const mockListFlags = FeatureFlagsService.list as jest.Mock;

/** `n` flags named flag-1…flag-n, for the concurrency bound. */
function manyFlags(n: number) {
  return Array.from({ length: n }, (_, i) => ({
    id: `flag-${i + 1}`,
    key: `flag_${i + 1}`,
    name: `Flag ${i + 1}`,
    rollout_percentage: 10,
    owner_id: null,
    created_at: '',
    updated_at: '',
  }));
}

beforeEach(() => {
  jest.clearAllMocks();
  mockGetSafetySettings.mockResolvedValue(mockSettings);
  mockListFlags.mockResolvedValue({ items: flags, total: 2, skip: 0, limit: 100 });
  mockGetFlagSafetyStatus.mockImplementation((id: string) =>
    Promise.resolve(id === 'flag-2' ? criticalCheck : healthyCheck),
  );
  mockRollbackFlag.mockResolvedValue({
    success: true,
    feature_flag_id: 'flag-2',
    message: 'Rolled back from 25% to 0%',
    trigger_type: 'manual',
    previous_percentage: 25,
    new_percentage: 0,
    rollback_record_id: 'rec-1',
    timestamp: '2026-01-01T00:00:01Z',
  });
});

async function openRollbackModalForSecondFlag() {
  render(<SafetyDashboard />);
  await waitFor(() => {
    expect(screen.getAllByTestId('safety-status-card')).toHaveLength(2);
  });
  fireEvent.click(screen.getAllByTestId('rollback-button')[1]);
  await waitFor(() => {
    expect(screen.getByTestId('rollback-modal')).toBeInTheDocument();
  });
}

describe('SafetyDashboard', () => {
  it('renders SafetySettingsForm', async () => {
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('safety-settings-form')).toBeInTheDocument();
    });
  });

  it('lists every flag and runs a safety check for each', async () => {
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getAllByTestId('safety-status-card')).toHaveLength(2);
    });
    expect(mockListFlags).toHaveBeenCalledWith({ limit: 100 });
    expect(mockGetFlagSafetyStatus).toHaveBeenCalledWith('flag-1');
    expect(mockGetFlagSafetyStatus).toHaveBeenCalledWith('flag-2');
    const cards = screen.getAllByTestId('safety-status-card');
    expect(cards[0]).toHaveAttribute('data-health', 'healthy');
    expect(cards[1]).toHaveAttribute('data-health', 'critical');
  });

  it('shows an empty state when there are no flags', async () => {
    mockListFlags.mockResolvedValue({ items: [], total: 0, skip: 0, limit: 100 });
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('flag-status-empty')).toBeInTheDocument();
    });
  });

  it('shows an error when the flag list cannot be loaded', async () => {
    mockListFlags.mockRejectedValue(new Error('API down'));
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('flag-status-error')).toHaveTextContent('API down');
    });
  });

  it('keeps the other cards and warns when one safety check fails', async () => {
    mockGetFlagSafetyStatus.mockImplementation((id: string) =>
      id === 'flag-2' ? Promise.reject(new Error('404')) : Promise.resolve(healthyCheck),
    );
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('flag-status-partial')).toHaveTextContent('payments');
    });
    expect(screen.getAllByTestId('safety-status-card')).toHaveLength(1);
  });

  it('checks flags through a bounded worker pool instead of all at once', async () => {
    const flagCount = 24;
    mockListFlags.mockResolvedValue({ items: manyFlags(flagCount), total: flagCount, skip: 0, limit: 100 });

    let inFlight = 0;
    let peak = 0;
    mockGetFlagSafetyStatus.mockImplementation(async () => {
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 0));
      inFlight -= 1;
      return healthyCheck;
    });

    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getAllByTestId('safety-status-card')).toHaveLength(flagCount);
    });
    expect(mockGetFlagSafetyStatus).toHaveBeenCalledTimes(flagCount);
    expect(peak).toBeLessThanOrEqual(SAFETY_CHECK_CONCURRENCY);
    // …but still concurrent: a serial implementation would peak at 1.
    expect(peak).toBeGreaterThan(1);
  });

  it('reports a 429 as rate limiting rather than a failed check', async () => {
    mockGetFlagSafetyStatus.mockImplementation((id: string) =>
      id === 'flag-2'
        ? Promise.reject(new ApiError({ status: 429, detail: 'Rate limit exceeded' }))
        : Promise.resolve(healthyCheck),
    );
    render(<SafetyDashboard />);
    const banner = await screen.findByTestId('flag-status-partial');
    expect(banner).toHaveTextContent(/rate limited/i);
    expect(banner).toHaveTextContent(/retry/i);
    expect(banner).toHaveTextContent('payments');
    expect(banner).not.toHaveTextContent(/safety check failed/i);
    expect(screen.getAllByTestId('safety-status-card')).toHaveLength(1);
  });

  it('shows rollback confirmation modal with the flag name', async () => {
    await openRollbackModalForSecondFlag();
    expect(screen.getByTestId('rollback-modal-flag-name')).toHaveTextContent('Payments redesign');
  });

  it('confirming rollback calls AdminService.rollbackFlag with the id and reason', async () => {
    await openRollbackModalForSecondFlag();
    fireEvent.change(screen.getByTestId('rollback-reason-input'), {
      target: { value: 'error spike' },
    });
    fireEvent.click(screen.getByTestId('rollback-confirm-button'));
    await waitFor(() => {
      expect(mockRollbackFlag).toHaveBeenCalledWith('flag-2', 'error spike');
    });
  });

  it('shows success, records the rollback and re-checks flags', async () => {
    await openRollbackModalForSecondFlag();
    mockGetFlagSafetyStatus.mockClear();
    fireEvent.click(screen.getByTestId('rollback-confirm-button'));
    await waitFor(() => {
      expect(screen.getByTestId('rollback-success-message')).toBeInTheDocument();
    });
    expect(screen.getByTestId('rollback-history-row')).toHaveTextContent(
      'Payments redesign: Rolled back from 25% to 0%',
    );
    await waitFor(() => {
      expect(mockGetFlagSafetyStatus).toHaveBeenCalledWith('flag-2');
    });
  });

  it('shows the API error when the rollback fails', async () => {
    mockRollbackFlag.mockRejectedValue(new Error('Not enough permissions'));
    await openRollbackModalForSecondFlag();
    fireEvent.click(screen.getByTestId('rollback-confirm-button'));
    await waitFor(() => {
      expect(screen.getByTestId('rollback-error')).toHaveTextContent('Not enough permissions');
    });
    expect(screen.queryByTestId('rollback-history-row')).not.toBeInTheDocument();
  });

  it('renders rollback history section', async () => {
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('rollback-history-table')).toBeInTheDocument();
    });
  });

  it('renders with data-testid="safety-dashboard"', () => {
    render(<SafetyDashboard />);
    expect(screen.getByTestId('safety-dashboard')).toBeInTheDocument();
  });
});
