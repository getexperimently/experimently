import React from 'react';
import { render, screen } from '@testing-library/react';
import { SampleSizeMeter } from '@/components/results/ResultsDashboard/SampleSizeMeter';
import { SampleSizeResult } from '@/types/results';

const adequateData: SampleSizeResult = {
  required_sample_size_per_variant: 3842,
  current_sample_size_per_variant: 6200,
  is_adequate: true,
  achieved_power: 0.95,
  days_to_significance: null,
  projected_completion_date: null,
  baseline_rate: 0.12,
  mde: 0.02,
  confidence_level: 0.95,
  power_target: 0.8,
};

const insufficientData: SampleSizeResult = {
  required_sample_size_per_variant: 5000,
  current_sample_size_per_variant: 2000,
  is_adequate: false,
  achieved_power: 0.45,
  days_to_significance: 14,
  projected_completion_date: '2024-02-15T00:00:00Z',
  baseline_rate: 0.12,
  mde: 0.02,
  confidence_level: 0.95,
  power_target: 0.8,
};

describe('SampleSizeMeter', () => {
  it('renders the sample size label', () => {
    render(<SampleSizeMeter data={adequateData} />);
    expect(screen.getByTestId('sample-size-label')).toHaveTextContent(
      '6,200 / 3,842 (161%)'
    );
  });

  it('renders achieved power', () => {
    render(<SampleSizeMeter data={adequateData} />);
    expect(screen.getByTestId('power-label')).toHaveTextContent('Power: 95%');
  });

  it('shows adequate status with green bar', () => {
    render(<SampleSizeMeter data={adequateData} />);
    expect(screen.getByText(/adequate ✓/i)).toBeInTheDocument();
    expect(screen.getByTestId('sample-size-bar')).toHaveClass('bg-green-500');
  });

  it('caps bar width at 100% when exceeded', () => {
    render(<SampleSizeMeter data={adequateData} />);
    const bar = screen.getByTestId('sample-size-bar');
    expect(bar).toHaveStyle({ width: '100%' });
  });

  it('shows insufficient status with red bar when < 80%', () => {
    render(<SampleSizeMeter data={insufficientData} />);
    expect(screen.getByText(/insufficient/i)).toBeInTheDocument();
    expect(screen.getByTestId('sample-size-bar')).toHaveClass('bg-red-400');
  });

  it('shows days to significance when not adequate', () => {
    render(<SampleSizeMeter data={insufficientData} />);
    expect(screen.getByTestId('days-to-significance')).toHaveTextContent('14');
  });

  it('shows projected completion date when not adequate', () => {
    render(<SampleSizeMeter data={insufficientData} />);
    expect(screen.getByTestId('projected-date')).toBeInTheDocument();
  });

  it('does not show projection info when adequate', () => {
    render(<SampleSizeMeter data={adequateData} />);
    expect(screen.queryByTestId('days-to-significance')).not.toBeInTheDocument();
    expect(screen.queryByTestId('projected-date')).not.toBeInTheDocument();
  });

  it('has accessible progressbar role', () => {
    render(<SampleSizeMeter data={adequateData} />);
    expect(screen.getByRole('progressbar')).toBeInTheDocument();
  });
});
