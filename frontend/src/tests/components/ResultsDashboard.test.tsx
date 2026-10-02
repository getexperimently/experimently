import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ResultsDashboard } from '@/components/results/ResultsDashboard/ResultsDashboard';
import { ResultsService } from '@/services/results';
import { ApiError } from '@/services/api';
import {
  ExperimentResultsResponse,
  DailyResultsResponse,
  SampleSizeResult,
  DimensionalBreakdownResponse,
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
    recommendation_reason: 'No statistically significant difference yet.',
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
  baseline_source: 'observed',
  baseline_users: 4000,
  metric_id: 'metric-1',
  metric_name: 'Conversion',
  metric_type: 'conversion',
  analysed_as: 'conversion',
  alpha: 0.05,
  comparisons: 1,
  correction_method: 'none',
  mde_absolute: 0.0024,
  unavailable_reason: null,
  guide_only_reasons: [],
};

const mockBreakdown: DimensionalBreakdownResponse = {
  dimension: 'platform',
  is_exploratory: true,
  adjusted_alpha: 0.0167,
  has_heterogeneous_effects: false,
  hte_warning: null,
  segments: [
    {
      segment_value: 'ios',
      sample_size: 300,
      variants: [
        {
          variant_id: 'ctrl',
          variant_name: 'Control',
          is_control: true,
          sample_size: 150,
          conversions: 15,
          mean: 0.1,
          confidence_interval: [0.057, 0.143],
          p_value: null,
          is_significant: false,
        },
      ],
    },
  ],
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

  // #666: the sample size loads on its own. Its failure stays inside the
  // Sample Size tab; it must not blank the page.
  describe('when the sample-size request fails', () => {
    const serverError = () =>
      new ApiError({ status: 500, detail: 'The sample size could not be computed.' });

    it('still renders the Overview, and the Sample Size tab shows the error', async () => {
      mockGetResults.mockResolvedValue(mockResults);
      mockGetDailyResults.mockResolvedValue(mockDaily);
      mockGetSampleSize.mockRejectedValue(serverError());

      render(<ResultsDashboard experimentId="exp-1" />);
      await waitFor(() =>
        expect(screen.getByTestId('experiment-summary')).toBeInTheDocument()
      );
      expect(screen.queryByTestId('error-state')).not.toBeInTheDocument();
      expect(screen.getByRole('tab', { name: /overview/i })).toHaveAttribute(
        'aria-selected',
        'true'
      );
      expect(screen.getByText('All Metrics')).toBeInTheDocument();

      await userEvent.click(screen.getByRole('tab', { name: /sample size/i }));
      const alert = await screen.findByTestId('sample-size-error');
      expect(alert).toHaveAttribute('role', 'alert');
      expect(alert).toHaveTextContent('The sample size could not be loaded.');
      expect(alert).toHaveTextContent('The sample size could not be computed.');
      expect(screen.queryByTestId('sample-size-meter')).not.toBeInTheDocument();
      // Only the tab reports it; the summary card above is untouched.
      expect(screen.getByTestId('experiment-summary')).toBeInTheDocument();
    });

    it('lets the user try the tab again without reloading the page', async () => {
      mockGetResults.mockResolvedValue(mockResults);
      mockGetDailyResults.mockResolvedValue(mockDaily);
      mockGetSampleSize
        .mockRejectedValueOnce(serverError())
        .mockResolvedValue(mockSampleSize);

      render(<ResultsDashboard experimentId="exp-1" />);
      await waitFor(() => screen.getByRole('tablist'));
      await userEvent.click(screen.getByRole('tab', { name: /sample size/i }));
      await screen.findByTestId('sample-size-error');

      await userEvent.click(screen.getByRole('button', { name: /try again/i }));
      expect(await screen.findByTestId('sample-size-meter')).toBeInTheDocument();
      expect(screen.queryByTestId('sample-size-error')).not.toBeInTheDocument();
      expect(mockGetResults).toHaveBeenCalledTimes(1);
    });
  });

  it('renders the page before the sample size answers, and the tab once it does', async () => {
    let resolveSampleSize: (v: SampleSizeResult) => void = () => {};
    mockGetResults.mockResolvedValue(mockResults);
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockImplementation(
      () => new Promise<SampleSizeResult>((resolve) => (resolveSampleSize = resolve))
    );

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() =>
      expect(screen.getByTestId('experiment-summary')).toBeInTheDocument()
    );
    await userEvent.click(screen.getByRole('tab', { name: /sample size/i }));
    expect(screen.getByTestId('sample-size-loading')).toBeInTheDocument();

    resolveSampleSize(mockSampleSize);
    expect(await screen.findByTestId('sample-size-meter')).toBeInTheDocument();
  });

  it('opens the Sample Size tab from the Overview card link', async () => {
    mockGetResults.mockResolvedValue(mockResults);
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByTestId('experiment-summary'));
    await userEvent.click(
      screen.getByRole('button', { name: 'See the Sample Size tab for the planned sample.' })
    );
    expect(screen.getByRole('tab', { name: /sample size/i })).toHaveAttribute(
      'aria-selected',
      'true'
    );
    expect(await screen.findByTestId('sample-size-meter')).toBeInTheDocument();
  });

  // #666 (4a): the dashboard sends no fixed values. On load it sends nothing
  // but the id, so the server plans from the observed control rate; after an
  // edit it sends exactly what the user changed, and never touches the URL.
  describe('the Sample Size tab sends only what the user changed', () => {
    it('asks with the experiment id alone on load', async () => {
      mockGetResults.mockResolvedValue(mockResults);
      mockGetDailyResults.mockResolvedValue(mockDaily);
      mockGetSampleSize.mockResolvedValue(mockSampleSize);

      render(<ResultsDashboard experimentId="exp-1" />);
      await waitFor(() => screen.getByTestId('experiment-summary'));
      expect(mockGetSampleSize).toHaveBeenCalledTimes(1);
      expect(mockGetSampleSize.mock.calls[0]).toEqual(['exp-1']);
    });

    it('recalculates with exactly the edited inputs, and leaves the URL alone', async () => {
      mockGetResults.mockResolvedValue(mockResults);
      mockGetDailyResults.mockResolvedValue(mockDaily);
      mockGetSampleSize
        .mockResolvedValueOnce(mockSampleSize)
        .mockResolvedValue({ ...mockSampleSize, mde: 0.1, baseline_rate: 0.15, baseline_source: 'request' });
      const urlBefore = window.location.href;

      render(<ResultsDashboard experimentId="exp-1" />);
      await waitFor(() => screen.getByRole('tablist'));
      await userEvent.click(screen.getByRole('tab', { name: /sample size/i }));
      await screen.findByTestId('sample-size-meter');

      const baseline = screen.getByLabelText('Baseline conversion rate (%)');
      await userEvent.clear(baseline);
      await userEvent.type(baseline, '15');
      const mde = screen.getByLabelText('Minimum detectable effect, relative (%)');
      await userEvent.clear(mde);
      await userEvent.type(mde, '10');
      await userEvent.click(screen.getByRole('button', { name: 'Recalculate' }));

      await waitFor(() => expect(mockGetSampleSize).toHaveBeenCalledTimes(2));
      expect(mockGetSampleSize).toHaveBeenLastCalledWith('exp-1', {
        baseline_conversion_rate: 0.15,
        mde: 0.1,
      });
      expect(await screen.findByTestId('sample-size-baseline-source')).toHaveTextContent(
        'Entered by you.'
      );
      expect(window.location.href).toBe(urlBefore);
      expect(mockGetResults).toHaveBeenCalledTimes(1);
    });

    it('renders the meter for an experiment with no traffic yet', async () => {
      mockGetResults.mockResolvedValue(mockResults);
      mockGetDailyResults.mockResolvedValue(mockDaily);
      mockGetSampleSize.mockResolvedValue({
        ...mockSampleSize,
        required_sample_size_per_variant: null,
        current_sample_size_per_variant: 0,
        is_adequate: false,
        achieved_power: null,
        baseline_rate: null,
        baseline_source: null,
        baseline_users: null,
        mde_absolute: null,
        unavailable_reason: 'no_control_data',
      });

      render(<ResultsDashboard experimentId="exp-1" />);
      await waitFor(() => screen.getByRole('tablist'));
      await userEvent.click(screen.getByRole('tab', { name: /sample size/i }));
      expect(await screen.findByTestId('sample-size-meter')).toBeInTheDocument();
      expect(screen.getByTestId('sample-size-no-traffic')).toBeInTheDocument();
    });
  });

  // Issue #28: Breakdowns tab tests
  it('renders Breakdowns tab in the tab list', async () => {
    mockGetResults.mockResolvedValue(mockResults);
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByRole('tablist'));

    expect(screen.getByRole('tab', { name: /breakdowns/i })).toBeInTheDocument();
  });

  it('switches to the Breakdowns tab and renders the dimension selector', async () => {
    mockGetResults.mockResolvedValue(mockResults);
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByRole('tablist'));

    await userEvent.click(screen.getByRole('tab', { name: /breakdowns/i }));

    expect(screen.getByTestId('breakdown-selector')).toBeInTheDocument();
  });

  it('shows prompt to select a dimension when no dimension is selected', async () => {
    mockGetResults.mockResolvedValue(mockResults);
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByRole('tablist'));
    await userEvent.click(screen.getByRole('tab', { name: /breakdowns/i }));

    expect(
      screen.getByText(/select a dimension above to view segment-level results/i)
    ).toBeInTheDocument();
  });

  it('fetches breakdown and renders SegmentComparisonTable when a dimension is selected', async () => {
    mockGetResults
      .mockResolvedValueOnce(mockResults)
      // second call with breakdown param returns breakdown data
      .mockResolvedValueOnce({ ...mockResults, breakdown: mockBreakdown });
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByRole('tablist'));
    await userEvent.click(screen.getByRole('tab', { name: /breakdowns/i }));

    await userEvent.selectOptions(
      screen.getByTestId('breakdown-selector'),
      'platform'
    );

    await waitFor(() =>
      expect(screen.getByTestId('segment-comparison-table')).toBeInTheDocument()
    );
  });

  it('calls getResults with breakdown param when a dimension is selected', async () => {
    mockGetResults
      .mockResolvedValueOnce(mockResults)
      .mockResolvedValueOnce({ ...mockResults, breakdown: mockBreakdown });
    mockGetDailyResults.mockResolvedValue(mockDaily);
    mockGetSampleSize.mockResolvedValue(mockSampleSize);

    render(<ResultsDashboard experimentId="exp-1" />);
    await waitFor(() => screen.getByRole('tablist'));
    await userEvent.click(screen.getByRole('tab', { name: /breakdowns/i }));

    await userEvent.selectOptions(
      screen.getByTestId('breakdown-selector'),
      'country'
    );

    await waitFor(() =>
      expect(mockGetResults).toHaveBeenCalledWith('exp-1', { breakdown: 'country' })
    );
  });
});
