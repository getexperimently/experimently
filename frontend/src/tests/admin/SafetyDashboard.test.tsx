import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SafetyDashboard } from '@/pages/admin/safety';
import { AdminService } from '@/services/admin';
import { SafetySettings } from '@/types/admin';

jest.mock('@/services/admin');

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
  SafetySettingsForm: ({ onSaved }: { onSaved?: () => void }) => (
    <div data-testid="safety-settings-form">Safety Settings Form</div>
  ),
}));

// Mock SafetyStatusCard
jest.mock('@/components/admin/safety/SafetyStatusCard', () => ({
  SafetyStatusCard: ({
    flag,
    onRollback,
  }: {
    flag: { flag_id: string; flag_name: string };
    onRollback: (id: string) => void;
  }) => (
    <div data-testid="safety-status-card">
      <span>{flag.flag_name}</span>
      <button data-testid="rollback-button" onClick={() => onRollback(flag.flag_id)}>
        Rollback
      </button>
    </div>
  ),
}));

// Mock RollbackHistoryTable
jest.mock('@/components/admin/safety/RollbackHistoryTable', () => ({
  RollbackHistoryTable: ({ rollbacks }: { rollbacks: unknown[] }) => (
    <div data-testid="rollback-history-table">Rollback History ({rollbacks.length})</div>
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
  error_rate_threshold: 5.0,
  latency_threshold_ms: 500,
  rollback_policy: 'auto',
  monitoring_window_minutes: 30,
};

const mockGetSafetySettings = AdminService.getSafetySettings as jest.Mock;
const mockRollbackFlag = AdminService.rollbackFlag as jest.Mock;

beforeEach(() => {
  jest.clearAllMocks();
  mockGetSafetySettings.mockResolvedValue(mockSettings);
  mockRollbackFlag.mockResolvedValue({ success: true });
});

describe('SafetyDashboard', () => {
  it('renders SafetySettingsForm', async () => {
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getByTestId('safety-settings-form')).toBeInTheDocument();
    });
  });

  it('renders status cards section', async () => {
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getAllByTestId('safety-status-card').length).toBeGreaterThan(0);
    });
  });

  it('shows rollback confirmation modal when rollback button clicked', async () => {
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getAllByTestId('rollback-button').length).toBeGreaterThan(0);
    });
    const rollbackButtons = screen.getAllByTestId('rollback-button');
    fireEvent.click(rollbackButtons[0]);
    await waitFor(() => {
      expect(screen.getByTestId('rollback-modal')).toBeInTheDocument();
    });
  });

  it('rollback modal has flag name in message', async () => {
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getAllByTestId('rollback-button').length).toBeGreaterThan(0);
    });
    const rollbackButtons = screen.getAllByTestId('rollback-button');
    fireEvent.click(rollbackButtons[0]);
    await waitFor(() => {
      expect(screen.getByTestId('rollback-modal')).toBeInTheDocument();
      expect(screen.getByTestId('rollback-modal-flag-name')).toBeInTheDocument();
    });
  });

  it('confirming rollback calls AdminService.rollbackFlag', async () => {
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getAllByTestId('rollback-button').length).toBeGreaterThan(0);
    });
    const rollbackButtons = screen.getAllByTestId('rollback-button');
    fireEvent.click(rollbackButtons[0]);
    await waitFor(() => {
      expect(screen.getByTestId('rollback-modal')).toBeInTheDocument();
    });

    const confirmButton = screen.getByTestId('rollback-confirm-button');
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(mockRollbackFlag).toHaveBeenCalled();
    });
  });

  it('shows success message after rollback', async () => {
    render(<SafetyDashboard />);
    await waitFor(() => {
      expect(screen.getAllByTestId('rollback-button').length).toBeGreaterThan(0);
    });
    const rollbackButtons = screen.getAllByTestId('rollback-button');
    fireEvent.click(rollbackButtons[0]);
    await waitFor(() => {
      expect(screen.getByTestId('rollback-modal')).toBeInTheDocument();
    });

    const confirmButton = screen.getByTestId('rollback-confirm-button');
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(screen.getByTestId('rollback-success-message')).toBeInTheDocument();
    });
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
