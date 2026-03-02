import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SafetySettingsForm } from '@/components/admin/safety/SafetySettingsForm';
import { AdminService } from '@/services/admin';
import { SafetySettings } from '@/types/admin';

jest.mock('@/services/admin');

const mockGetSafetySettings = AdminService.getSafetySettings as jest.Mock;
const mockUpdateSafetySettings = AdminService.updateSafetySettings as jest.Mock;

const mockSettings: SafetySettings = {
  error_rate_threshold: 5.0,
  latency_threshold_ms: 500,
  rollback_policy: 'auto',
  monitoring_window_minutes: 30,
};

beforeEach(() => {
  jest.clearAllMocks();
});

describe('SafetySettingsForm', () => {
  it('renders loading state while fetching', () => {
    mockGetSafetySettings.mockImplementation(() => new Promise(() => {}));
    render(<SafetySettingsForm />);
    expect(screen.getByTestId('safety-settings-form-loading')).toBeInTheDocument();
  });

  it('populates form with current safety settings values', async () => {
    mockGetSafetySettings.mockResolvedValue(mockSettings);
    render(<SafetySettingsForm />);
    await waitFor(() => {
      expect(screen.getByTestId('safety-settings-form')).toBeInTheDocument();
    });
    const errorRateInput = screen.getByTestId('error-rate-threshold-input') as HTMLInputElement;
    expect(errorRateInput.value).toBe('5');
  });

  it('error_rate_threshold input shows current value', async () => {
    mockGetSafetySettings.mockResolvedValue(mockSettings);
    render(<SafetySettingsForm />);
    await waitFor(() => {
      const input = screen.getByTestId('error-rate-threshold-input') as HTMLInputElement;
      expect(Number(input.value)).toBe(mockSettings.error_rate_threshold);
    });
  });

  it('latency_threshold_ms input shows current value', async () => {
    mockGetSafetySettings.mockResolvedValue(mockSettings);
    render(<SafetySettingsForm />);
    await waitFor(() => {
      const input = screen.getByTestId('latency-threshold-input') as HTMLInputElement;
      expect(Number(input.value)).toBe(mockSettings.latency_threshold_ms);
    });
  });

  it('rollback_policy select shows current value', async () => {
    mockGetSafetySettings.mockResolvedValue(mockSettings);
    render(<SafetySettingsForm />);
    await waitFor(() => {
      const select = screen.getByTestId('rollback-policy-select') as HTMLSelectElement;
      expect(select.value).toBe(mockSettings.rollback_policy);
    });
  });

  it('monitoring_window_minutes shows current value', async () => {
    mockGetSafetySettings.mockResolvedValue(mockSettings);
    render(<SafetySettingsForm />);
    await waitFor(() => {
      const input = screen.getByTestId('monitoring-window-input') as HTMLInputElement;
      expect(Number(input.value)).toBe(mockSettings.monitoring_window_minutes);
    });
  });

  it('save calls AdminService.updateSafetySettings with form values', async () => {
    mockGetSafetySettings.mockResolvedValue(mockSettings);
    mockUpdateSafetySettings.mockResolvedValue(mockSettings);
    render(<SafetySettingsForm />);
    await waitFor(() => {
      expect(screen.getByTestId('safety-settings-form')).toBeInTheDocument();
    });

    const errorRateInput = screen.getByTestId('error-rate-threshold-input');
    fireEvent.change(errorRateInput, { target: { value: '10' } });

    const saveButton = screen.getByTestId('save-settings-button');
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(mockUpdateSafetySettings).toHaveBeenCalledWith(
        expect.objectContaining({
          error_rate_threshold: 10,
        })
      );
    });
  });

  it('renders with data-testid="safety-settings-form"', async () => {
    mockGetSafetySettings.mockResolvedValue(mockSettings);
    render(<SafetySettingsForm />);
    await waitFor(() => {
      expect(screen.getByTestId('safety-settings-form')).toBeInTheDocument();
    });
  });
});
