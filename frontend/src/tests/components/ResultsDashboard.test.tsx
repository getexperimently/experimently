import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResultsDashboard } from '@/components/results/ResultsDashboard/ResultsDashboard';
import { ResultsService } from '@/services/results';
import {
  ExperimentResultsResponse,
  DailyResultsResponse,
  SampleSizeResult,
} from '@/types/results';

jest.mock('@/services/results');

const mockGetResults = ResultsService.getResults as jest.Mock;
const mockGetDailyResults = ResultsService.getDailyResults as jest.Mock;
const mockGetSampleSize = ResultsService.getSampleSize as jest.Mock;

const mockResults: ExperimentResultsResponse = {
  experiment_id: 'exp-1',
  experiment_name: 'Test Experiment',
  status: 'ACTIVE',
  start_date: '2024-01-01T00:00:00Z',
  end_date: null,
  confidence_level: 0.95,
  correction_method: 'bonferroni',
  sample_size_adequate: true,
  computed_at: '2024-01-15T12:00:00Z',
  summary: {
    total_users: 2000,
    total_events: 240,
    duration_days: 7,
    has_winner: false,
    winning_variant_id: null,
    recommendation: 'CONTINUE_TESTING',
  },
  metrics: [
    {
      metric_id: 'm1',
      metric_name: 'Conversion Rate',
      metric_type: 'conversion',
      is_primary: true,
      variants: [
        {
          variant_id: 'ctrl',
          variant_name: 'Control',
          is_control: true,
          sample_size: 1000,
          conversions: 120,
          mean: 0.12,
          std_dev: 0.05,
          confidence_interval: [0.10, 0.14],
          p_value: null,
          adjusted_p_value: null,
          is_significant: false,
          effect_size: null,
          effect_size_label: null,
          relative_improvement_pct: null,
          power: null,
        },
      ],
    },
  ],
};

const mockDaily: DailyResultsResponse = {
  experiment_id: 'exp-1',
  metric_id: null,
  series: [],
};

const mockSampleSize: SampleSizeResult = {
  required_sample_size_per_variant: 3000,
  current_sample_size_per_variant: 4000,
  is_adequate: true,
  achieved_power: 0.90,
  days_to_significance: null,
  projected_completion_date: null,
  baseline_rate: 0.12,
  mde: 0.02,
  confidence_level: 0.95,
  power_target: 0.8,
};

beforeEach(() => {
  jest.clearAllMocks();
});

describe('ResultsDashboard', () => {
  it('shows loading state while fetching', () => {
    // Never resolves
    mockGetResults.mockImplementation(() => new Promise(() => {}));
    mockGetDailyResults.mockImplementation(() => new Promise(() => {}));
    mockGetSampleSize.mockImplementation(() => new Promise(() => {}));

    render(<ResultsDashboard experimentId="exp-1" />);
    expect(screen.getByTestId('loading-skeleton')).toBeInTheDocument();
  });

  it('shows error state on fetch failure', async () => {
    mockGetResults.mockRejectedValue(new Error('Network error'));
    mockGetDailyResults.mockRejectedValue(new Error('Network error'));
    mockGetSampleSize.mockRejectedValue(new Error('Network error'));

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() =>
      expect(screen.getByTestId('error-state')).toBeInTheDocument()
    );
    expect(screen.getByText(/failed to load results/i)).toBeInTheDocument();
  });

  it('renders ExperimentSummary on success', async () => {
    mockGetResults.mockResolvedValue(mockResults);
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() =>
      expect(screen.getByTestId('experiment-summary')).toBeInTheDocument()
    );
  });

  it('renders tab navigation', async () => {
    mockGetResults.mockResolvedValue(mockResults);
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByRole('tablist'));

    expect(screen.getByRole('tab', { name: /overview/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /trends/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /sample size/i })).toBeInTheDocument();
  });

  it('switches to trends tab when clicked', async () => {
    mockGetResults.mockResolvedValue(mockResults);
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByRole('tablist'));

    await userEvent.click(screen.getByRole('tab', { name: /trends/i }));
    expect(screen.getByRole('tab', { name: /trends/i })).toHaveAttribute(
      'aria-selected',
      'true'
    );
    // With empty series, TrendChart renders the empty state
    expect(
      screen.getByTestId('trend-empty') || screen.queryByTestId('trend-chart')
    ).toBeTruthy();
  });

  it('switches to sample size tab when clicked', async () => {
    mockGetResults.mockResolvedValue(mockResults);
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByRole('tablist'));

    await userEvent.click(screen.getByRole('tab', { name: /sample size/i }));
    expect(screen.getByTestId('sample-size-meter')).toBeInTheDocument();
  });

  it('calls all three service methods with the experiment id', async () => {
    mockGetResults.mockResolvedValue(mockResults);
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByTestId('experiment-summary'));

    expect(mockGetResults).toHaveBeenCalledWith('exp-1');
    expect(mockGetDailyResults).toHaveBeenCalledWith('exp-1');
    expect(mockGetSampleSize).toHaveBeenCalledWith('exp-1');
  });

  it('shows retry button on error and re-fetches on click', async () => {
    mockGetResults
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValue(mockResults);
    mockGetDailyResults
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValue(mockDaily);
    mockGetSampleSize
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByTestId('error-state'));

    await userEvent.click(screen.getByRole('button', { name: /retry/i }));

    await waitFor(() =>
      expect(screen.getByTestId('experiment-summary')).toBeInTheDocument()
    );
  });
});
