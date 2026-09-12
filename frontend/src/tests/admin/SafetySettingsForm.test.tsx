import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import {
  SafetySettingsForm,
  formToUpdate,
  settingsToForm,
} from '@/components/admin/safety/SafetySettingsForm';
import { AdminService } from '@/services/admin';
import { SafetySettings } from '@/types/admin';

jest.mock('@/services/admin');

const mockGetSafetySettings = AdminService.getSafetySettings as jest.Mock;
const mockUpdateSafetySettings = AdminService.updateSafetySettings as jest.Mock;

const mockSettings: SafetySettings = {
  id: 'settings-1',
  enable_automatic_rollbacks: true,
  default_metrics: {
    error_rate: { warning_threshold: 0.02, critical_threshold: 0.05, comparison_type: 'greater_than' },
    latency: { warning_threshold: 300, critical_threshold: 500, comparison_type: 'greater_than' },
    conversion_rate: { warning_threshold: 0.1, critical_threshold: 0.05, comparison_type: 'less_than' },
  },
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

beforeEach(() => {
  jest.clearAllMocks();
});

describe('settingsToForm / formToUpdate', () => {
  it('renders error-rate fractions as percentages and latency as ms', () => {
    const form = settingsToForm(mockSettings);
    expect(form).toEqual({
      enable_automatic_rollbacks: true,
      error_rate_warning: '2',
      error_rate_critical: '5',
      latency_warning: '300',
      latency_critical: '500',
    });
  });

  it('handles missing default_metrics', () => {
    const form = settingsToForm({ ...mockSettings, default_metrics: null });
    expect(form.error_rate_warning).toBe('');
    expect(form.latency_critical).toBe('');
  });

  it('builds a SafetySettingsUpdate, converting percentages back and keeping other metrics', () => {
    const update = formToUpdate(
      {
        enable_automatic_rollbacks: false,
        error_rate_warning: '1.5',
        error_rate_critical: '7',
        latency_warning: '',
        latency_critical: '800',
      },
      mockSettings,
    );
    expect(update).toEqual({
      enable_automatic_rollbacks: false,
      default_metrics: {
        error_rate: { warning_threshold: 0.015, critical_threshold: 0.07, comparison_type: 'greater_than' },
        latency: { warning_threshold: null, critical_threshold: 800, comparison_type: 'greater_than' },
        conversion_rate: mockSettings.default_metrics!.conversion_rate,
      },
    });
  });

  it('drops a metric whose thresholds are both empty and sends null when none remain', () => {
    const update = formToUpdate(
      {
        enable_automatic_rollbacks: true,
        error_rate_warning: '',
        error_rate_critical: '',
        latency_warning: '',
        latency_critical: '',
      },
      { ...mockSettings, default_metrics: { error_rate: mockSettings.default_metrics!.error_rate } },
    );
    expect(update.default_metrics).toBeNull();
  });
});

describe('SafetySettingsForm', () => {
  it('renders loading state while fetching', () => {
    mockGetSafetySettings.mockImplementation(() => new Promise(() => {}));
    render(<SafetySettingsForm />);
    expect(screen.getByTestId('safety-settings-form-loading')).toBeInTheDocument();
  });

  it('populates the form from GET /safety/settings', async () => {
    mockGetSafetySettings.mockResolvedValue(mockSettings);
    render(<SafetySettingsForm />);
    await waitFor(() => {
      expect(screen.getByTestId('safety-settings-form')).toBeInTheDocument();
    });
    expect(screen.getByTestId('auto-rollback-checkbox')).toBeChecked();
    expect((screen.getByTestId('error-rate-warning-input') as HTMLInputElement).value).toBe('2');
    expect((screen.getByTestId('error-rate-critical-input') as HTMLInputElement).value).toBe('5');
    expect((screen.getByTestId('latency-warning-input') as HTMLInputElement).value).toBe('300');
    expect((screen.getByTestId('latency-critical-input') as HTMLInputElement).value).toBe('500');
  });

  it('shows an error when loading fails', async () => {
    mockGetSafetySettings.mockRejectedValue(new Error('boom'));
    render(<SafetySettingsForm />);
    await waitFor(() => {
      expect(screen.getByTestId('settings-error')).toHaveTextContent('boom');
    });
  });

  it('save calls AdminService.updateSafetySettings with the backend shape', async () => {
    mockGetSafetySettings.mockResolvedValue(mockSettings);
    mockUpdateSafetySettings.mockResolvedValue({ ...mockSettings, enable_automatic_rollbacks: false });
    const onSaved = jest.fn();
    render(<SafetySettingsForm onSaved={onSaved} />);
    await waitFor(() => {
      expect(screen.getByTestId('safety-settings-form')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId('auto-rollback-checkbox'));
    fireEvent.change(screen.getByTestId('error-rate-critical-input'), { target: { value: '10' } });
    fireEvent.click(screen.getByTestId('save-settings-button'));

    await waitFor(() => {
      expect(mockUpdateSafetySettings).toHaveBeenCalledWith({
        enable_automatic_rollbacks: false,
        default_metrics: expect.objectContaining({
          error_rate: { warning_threshold: 0.02, critical_threshold: 0.1, comparison_type: 'greater_than' },
          latency: mockSettings.default_metrics!.latency,
          conversion_rate: mockSettings.default_metrics!.conversion_rate,
        }),
      });
    });
    expect(screen.getByTestId('settings-success')).toBeInTheDocument();
    expect(onSaved).toHaveBeenCalled();
    expect(screen.getByTestId('auto-rollback-checkbox')).not.toBeChecked();
  });

  it('shows the API error when saving fails', async () => {
    mockGetSafetySettings.mockResolvedValue(mockSettings);
    mockUpdateSafetySettings.mockRejectedValue(new Error('Not enough permissions'));
    render(<SafetySettingsForm />);
    await waitFor(() => {
      expect(screen.getByTestId('safety-settings-form')).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTestId('save-settings-button'));
    await waitFor(() => {
      expect(screen.getByTestId('settings-error')).toHaveTextContent('Not enough permissions');
    });
  });
});
