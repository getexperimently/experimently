import React from 'react';
import { render, screen } from '@testing-library/react';
import { EarlyStoppingBanner } from '@/components/results/Sequential/EarlyStoppingBanner';
import { MSPRTResult } from '@/types/sequential';

const mockMSPRT: MSPRTResult = {
  lambda_ratio: 25.42,
  always_valid_p_value: 0.0394,
  can_stop: true,
  evidence_strength: 'strong_for_effect',
  boundary: 20.0,
};

describe('EarlyStoppingBanner', () => {
  it('renders the banner with data-testid', () => {
    render(
      <EarlyStoppingBanner msprtResult={mockMSPRT} recommendedAction="stop_for_effect" />
    );
    expect(screen.getByTestId('early-stopping-banner')).toBeInTheDocument();
  });

  it('shows green banner for stop_for_effect', () => {
    render(
      <EarlyStoppingBanner msprtResult={mockMSPRT} recommendedAction="stop_for_effect" />
    );
    const banner = screen.getByTestId('early-stopping-banner');
    expect(banner.className).toContain('bg-green-50');
    expect(screen.getByTestId('action-label')).toHaveTextContent(
      /ready to stop/i
    );
  });

  it('shows amber banner for stop_for_futility', () => {
    render(
      <EarlyStoppingBanner msprtResult={mockMSPRT} recommendedAction="stop_for_futility" />
    );
    const banner = screen.getByTestId('early-stopping-banner');
    expect(banner.className).toContain('bg-amber-50');
    expect(screen.getByTestId('action-label')).toHaveTextContent(
      /consider stopping/i
    );
  });

  it('shows blue banner for continue', () => {
    render(
      <EarlyStoppingBanner msprtResult={mockMSPRT} recommendedAction="continue" />
    );
    const banner = screen.getByTestId('early-stopping-banner');
    expect(banner.className).toContain('bg-blue-50');
    expect(screen.getByTestId('action-label')).toHaveTextContent(
      /continue testing/i
    );
  });

  it('displays lambda ratio and boundary', () => {
    render(
      <EarlyStoppingBanner msprtResult={mockMSPRT} recommendedAction="stop_for_effect" />
    );
    const lambda = screen.getByTestId('lambda-display');
    expect(lambda).toHaveTextContent('25.42');
    expect(lambda).toHaveTextContent('20.0');
  });

  it('displays evidence detail with p-value', () => {
    render(
      <EarlyStoppingBanner msprtResult={mockMSPRT} recommendedAction="stop_for_effect" />
    );
    const detail = screen.getByTestId('evidence-detail');
    expect(detail).toHaveTextContent(/strong evidence for effect/i);
    expect(detail).toHaveTextContent('0.0394');
  });

  it('renders without msprtResult (null)', () => {
    render(
      <EarlyStoppingBanner msprtResult={null} recommendedAction="continue" />
    );
    expect(screen.getByTestId('early-stopping-banner')).toBeInTheDocument();
    expect(screen.getByTestId('action-label')).toHaveTextContent(
      /continue testing/i
    );
    expect(screen.queryByTestId('lambda-display')).not.toBeInTheDocument();
    expect(screen.queryByTestId('evidence-detail')).not.toBeInTheDocument();
  });

  it('has correct aria role', () => {
    render(
      <EarlyStoppingBanner msprtResult={mockMSPRT} recommendedAction="continue" />
    );
    expect(screen.getByRole('status')).toBeInTheDocument();
  });
});
