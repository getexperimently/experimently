import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ExperimentSummary } from '@/components/results/ResultsDashboard/ExperimentSummary';
import { ExperimentResultsResponse } from '@/types/results';

const baseExperiment: ExperimentResultsResponse = {
  experiment_id: 'exp-1',
  experiment_name: 'Homepage CTA Test',
  status: 'ACTIVE',
  start_date: '2024-01-01T00:00:00Z',
  end_date: null,
  confidence_level: 0.95,
  correction_method: 'bonferroni',
  sample_size_adequate: true,
  computed_at: '2024-01-15T12:00:00Z',
  summary: {
    total_users: 5000,
    total_events: 620,
    duration_days: 14,
    has_winner: false,
    winning_variant_id: null,
    recommendation: 'CONTINUE_TESTING',
    recommendation_reason: 'No statistically significant difference yet.',
  },
  metrics: [],
};

const winnerExperiment: ExperimentResultsResponse = {
  ...baseExperiment,
  summary: {
    ...baseExperiment.summary,
    has_winner: true,
    winning_variant_id: 'var-1',
    recommendation: 'SHIP_VARIANT',
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
          sample_size: 2500,
          conversions: 250,
          mean: 0.10,
          std_dev: 0.04,
          confidence_interval: null,
          p_value: null,
          adjusted_p_value: null,
          is_significant: false,
          effect_size: null,
          effect_size_label: null,
          relative_improvement_pct: null,
          power: null,
        },
        {
          variant_id: 'var-1',
          variant_name: 'Variant B',
          is_control: false,
          sample_size: 2500,
          conversions: 370,
          mean: 0.148,
          std_dev: 0.045,
          confidence_interval: [0.13, 0.166],
          p_value: 0.001,
          adjusted_p_value: 0.001,
          is_significant: true,
          effect_size: 0.5,
          effect_size_label: 'medium',
          relative_improvement_pct: 48.0,
          power: 0.95,
        },
      ],
    },
  ],
};

describe('ExperimentSummary', () => {
  it('renders the experiment name', () => {
    render(<ExperimentSummary experiment={baseExperiment} />);
    expect(screen.getByText('Homepage CTA Test')).toBeInTheDocument();
  });

  it('renders the status badge', () => {
    render(<ExperimentSummary experiment={baseExperiment} />);
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
  });

  it('renders total users', () => {
    render(<ExperimentSummary experiment={baseExperiment} />);
    expect(screen.getByText('5,000')).toBeInTheDocument();
  });

  it('renders duration in days', () => {
    render(<ExperimentSummary experiment={baseExperiment} />);
    // Duration appears in the stat grid and the subtitle
    expect(screen.getAllByText(/14/)[0]).toBeInTheDocument();
  });

  it('renders CONTINUE_TESTING recommendation', () => {
    render(<ExperimentSummary experiment={baseExperiment} />);
    expect(screen.getByTestId('recommendation-pill')).toHaveTextContent(
      'Continue Testing'
    );
    expect(screen.getByTestId('recommendation-pill')).toHaveClass('bg-amber-100');
  });

  it('renders SHIP_VARIANT recommendation with green styling', () => {
    render(<ExperimentSummary experiment={winnerExperiment} />);
    expect(screen.getByTestId('recommendation-pill')).toHaveTextContent('Ship Variant');
    expect(screen.getByTestId('recommendation-pill')).toHaveClass('bg-green-100');
  });

  it('renders winner indicator when has_winner is true', () => {
    render(<ExperimentSummary experiment={winnerExperiment} />);
    expect(screen.getByTestId('winner-indicator')).toBeInTheDocument();
    expect(screen.getByText('Variant B')).toBeInTheDocument();
  });

  it('does not render winner indicator when no winner', () => {
    render(<ExperimentSummary experiment={baseExperiment} />);
    expect(screen.queryByTestId('winner-indicator')).not.toBeInTheDocument();
  });

  it('has the experiment-summary data-testid', () => {
    render(<ExperimentSummary experiment={baseExperiment} />);
    expect(screen.getByTestId('experiment-summary')).toBeInTheDocument();
  });

  // #666: the card reports the minimum the recommendation requires, not the
  // planned sample size the Sample Size tab shows, so it must not share the
  // tab's label or its "Adequate / Insufficient" verdict.
  describe('Minimum sample card', () => {
    it('reads "Minimum sample: Reached" when every variant has the minimum', () => {
      render(<ExperimentSummary experiment={baseExperiment} />);
      const card = screen.getByTestId('minimum-sample');
      expect(within(card).getByText('Minimum sample')).toBeInTheDocument();
      expect(within(card).getByText('Reached')).toBeInTheDocument();
      expect(card).toHaveTextContent(/^Minimum sampleReached$/);
    });

    it('reads "Minimum sample: Not reached" otherwise', () => {
      render(
        <ExperimentSummary
          experiment={{ ...baseExperiment, sample_size_adequate: false }}
        />
      );
      const card = screen.getByTestId('minimum-sample');
      expect(card).toHaveTextContent(/^Minimum sampleNot reached$/);
    });

    it('no longer uses the old "Sample Size: Adequate / Insufficient" wording', () => {
      const { rerender } = render(<ExperimentSummary experiment={baseExperiment} />);
      const summary = screen.getByTestId('experiment-summary');
      expect(summary).not.toHaveTextContent(/Adequate|Insufficient/);
      expect(within(summary).queryByText('Sample Size')).not.toBeInTheDocument();
      rerender(
        <ExperimentSummary
          experiment={{ ...baseExperiment, sample_size_adequate: false }}
        />
      );
      expect(screen.getByTestId('experiment-summary')).not.toHaveTextContent(
        /Adequate|Insufficient/
      );
    });

    it('offers a link to the Sample Size tab that calls the handler', async () => {
      const onOpen = jest.fn();
      render(
        <ExperimentSummary experiment={baseExperiment} onOpenSampleSize={onOpen} />
      );
      const link = screen.getByRole('button', {
        name: 'See the Sample Size tab for the planned sample.',
      });
      await userEvent.click(link);
      expect(onOpen).toHaveBeenCalledTimes(1);
    });

    it('shows no link when there is no tab to open', () => {
      render(<ExperimentSummary experiment={baseExperiment} />);
      expect(screen.queryByTestId('open-sample-size-tab')).not.toBeInTheDocument();
    });
  });
});
