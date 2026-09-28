import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AnalysisNotice } from '@/components/results/shared/AnalysisNotice';

const CUPED_NOTICE =
  'Beta: the covariate is not yet a pre-experiment metric, so ' +
  'variance_reduction_pct is close to 0 and the adjusted estimate is ' +
  'close to the unadjusted one. ' +
  'https://github.com/getexperimently/experimently/issues/217';

describe('AnalysisNotice', () => {
  it('renders a Beta label, the notice text and the issue link when beta', () => {
    render(<AnalysisNotice status="beta" notice={CUPED_NOTICE} />);

    const region = screen.getByRole('region', { name: /beta/i });
    // The label is text, not colour alone.
    expect(within(region).getByTestId('analysis-notice-label')).toHaveTextContent(/^Beta$/);
    expect(region).toHaveTextContent(/the covariate is not yet a pre-experiment metric/i);
    // The "Beta:" prefix is not repeated after the label.
    expect(screen.getByTestId('analysis-notice-text').textContent).not.toMatch(/^Beta:/);

    const link = within(region).getByRole('link', { name: 'issue #217' });
    expect(link).toHaveAttribute(
      'href',
      'https://github.com/getexperimently/experimently/issues/217'
    );
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('is not an alert, and its link is reachable by keyboard', async () => {
    render(<AnalysisNotice status="beta" notice={CUPED_NOTICE} />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByTestId('analysis-notice')).not.toHaveAttribute('aria-live');

    await userEvent.tab();
    expect(screen.getByRole('link', { name: 'issue #217' })).toHaveFocus();
  });

  it('keeps text that follows the issue link', () => {
    render(
      <AnalysisNotice
        status="beta"
        notice={
          'Beta: part is not computed. ' +
          'https://github.com/getexperimently/experimently/issues/231 ' +
          'The stored method always_valid is shown as msprt.'
        }
      />
    );
    expect(screen.getByTestId('analysis-notice-text')).toHaveTextContent(
      'part is not computed. issue #231 The stored method always_valid is shown as msprt.'
    );
  });

  it('renders a notice with no issue URL as plain text, without a link', () => {
    render(<AnalysisNotice status="beta" notice="Beta: not computed yet." />);
    expect(screen.getByTestId('analysis-notice-text')).toHaveTextContent('not computed yet.');
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('does not link a URL that is not an issue link', () => {
    render(
      <AnalysisNotice status="beta" notice="Beta: see https://example.com/issues/1 for more." />
    );
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders nothing when the status is ga', () => {
    const { container } = render(<AnalysisNotice status="ga" notice={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when the fields are absent', () => {
    const { container } = render(<AnalysisNotice />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders nothing when beta arrives without a notice', () => {
    const { container } = render(<AnalysisNotice status="beta" notice={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
