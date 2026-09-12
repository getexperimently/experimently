import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import ExperimentDetailPage, { ACTIONS_BY_STATUS } from '@/pages/experiments/[id]';
import { apiFetch } from '@/services/api';
import { Experiment } from '@/types/experiments';
import { apiError, makeRouter, routedApi } from './helpers/apiMock';

jest.mock('@/services/api', () => ({
  ...jest.requireActual('@/services/api'),
  apiFetch: jest.fn(),
}));

const mockRouter = makeRouter({ pathname: '/experiments/[id]', query: { id: 'exp-1' } });
jest.mock('next/router', () => ({ useRouter: () => mockRouter }));

jest.mock('next/head', () => {
  const Head = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  Head.displayName = 'MockHead';
  return Head;
});

const mockUseAuth = jest.fn();
jest.mock('@/contexts/AuthContext', () => ({ useAuth: () => mockUseAuth() }));

const mockedApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;

const BASE_EXPERIMENT: Experiment = {
  id: 'exp-1',
  name: 'Checkout button colour',
  key: 'checkout-button-colour',
  description: 'Blue vs green CTA',
  hypothesis: 'Blue converts better',
  experiment_type: 'a_b',
  status: 'draft',
  targeting_rules: null,
  tags: null,
  owner_id: 'user-1',
  start_date: null,
  end_date: null,
  created_at: '2026-09-01T10:00:00Z',
  updated_at: '2026-09-01T10:00:00Z',
  variants: [
    { id: 'v-1', name: 'Control', is_control: true, traffic_allocation: 50 },
    { id: 'v-2', name: 'Blue CTA', is_control: false, traffic_allocation: 50, description: 'Blue button' },
  ],
  metrics: [
    { id: 'm-1', name: 'Purchase', event_name: 'purchase', metric_type: 'conversion', is_primary: true },
    { id: 'm-2', name: 'Revenue', event_name: 'purchase', metric_type: 'revenue', is_primary: false },
  ],
};

function experiment(overrides: Partial<Experiment> = {}): Experiment {
  return { ...BASE_EXPERIMENT, ...overrides };
}

function install(current: Experiment) {
  let state = current;
  const transition = (status: Experiment['status']) => () => {
    state = { ...state, status };
    return state;
  };
  mockedApiFetch.mockImplementation(
    routedApi([
      { path: '/api/v1/experiments/exp-1', handler: () => state },
      { method: 'POST', path: '/api/v1/experiments/exp-1/start', handler: transition('active') },
      { method: 'POST', path: '/api/v1/experiments/exp-1/pause', handler: transition('paused') },
      { method: 'POST', path: '/api/v1/experiments/exp-1/complete', handler: transition('completed') },
      { method: 'POST', path: '/api/v1/experiments/exp-1/archive', handler: transition('archived') },
    ]) as unknown as typeof apiFetch,
  );
}

const calledWith = (method: string, path: string) =>
  mockedApiFetch.mock.calls.some(
    ([p, o]) => p === path && ((o?.method ?? 'GET').toUpperCase() === method),
  );

beforeEach(() => {
  mockedApiFetch.mockReset();
  mockUseAuth.mockReturnValue({
    user: { id: 'user-1', email: 'admin@demo.com', username: 'admin', role: 'ADMIN' },
    status: 'authenticated',
  });
});

describe('ACTIONS_BY_STATUS', () => {
  it('mirrors the backend lifecycle guards', () => {
    expect(ACTIONS_BY_STATUS.draft).toEqual(['start']);
    expect(ACTIONS_BY_STATUS.active).toEqual(['pause', 'complete']);
    expect(ACTIONS_BY_STATUS.paused).toEqual(['start', 'complete']);
    expect(ACTIONS_BY_STATUS.completed).toEqual(['archive']);
    expect(ACTIONS_BY_STATUS.archived).toEqual([]);
  });
});

describe('ExperimentDetailPage — rendering', () => {
  it('shows the header, variants, metrics and owner', async () => {
    install(experiment());
    render(<ExperimentDetailPage />);

    expect(screen.getByTestId('experiment-loading')).toBeInTheDocument();
    expect(await screen.findByTestId('experiment-detail')).toBeInTheDocument();

    expect(screen.getByTestId('experiment-name')).toHaveTextContent('Checkout button colour');
    expect(screen.getByTestId('experiment-key')).toHaveTextContent('checkout-button-colour');
    expect(screen.getByTestId('experiment-status')).toHaveTextContent('Draft');
    expect(screen.getByTestId('experiment-type')).toHaveTextContent('A/B Test');
    expect(screen.getByTestId('experiment-owner')).toHaveTextContent('You (admin@demo.com)');
    expect(screen.getByTestId('experiment-description')).toHaveTextContent('Blue vs green CTA');
    expect(screen.getByTestId('experiment-hypothesis')).toHaveTextContent('Blue converts better');

    const rows = within(screen.getByTestId('variants-table')).getAllByTestId('variant-row');
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent('Control');
    expect(rows[0]).toHaveTextContent('50%');
    expect(rows[1]).toHaveTextContent('Blue CTA');
    expect(rows[1]).toHaveTextContent('Treatment');

    const metrics = within(screen.getByTestId('metrics-list')).getAllByTestId('metric-row');
    expect(metrics).toHaveLength(2);
    expect(metrics[0]).toHaveTextContent('Purchase');
    expect(metrics[0]).toHaveTextContent('Primary');
    expect(metrics[0]).toHaveTextContent('purchase');
    expect(metrics[1]).not.toHaveTextContent('Primary');

    expect(screen.getByTestId('sdk-hint')).toHaveTextContent('"experiment_key": "checkout-button-colour"');
  });

  it('shows a truncated owner id for experiments owned by someone else', async () => {
    install(experiment({ owner_id: '0f9e8d7c-6b5a-4c3d-2e1f-0a9b8c7d6e5f' }));
    render(<ExperimentDetailPage />);
    expect(await screen.findByTestId('experiment-owner')).toHaveTextContent('0f9e8d7c…');
  });

  it('renders an empty metrics hint when there are none', async () => {
    install(experiment({ metrics: [] }));
    render(<ExperimentDetailPage />);
    expect(await screen.findByTestId('metrics-empty')).toBeInTheDocument();
  });

  it('disables "View results" for drafts and links it otherwise', async () => {
    install(experiment({ status: 'draft' }));
    const { unmount } = render(<ExperimentDetailPage />);
    expect(await screen.findByTestId('view-results-disabled')).toBeInTheDocument();
    expect(screen.queryByTestId('view-results')).not.toBeInTheDocument();
    unmount();

    install(experiment({ status: 'active' }));
    render(<ExperimentDetailPage />);
    const link = await screen.findByTestId('view-results');
    expect(link).toHaveAttribute('href', '/results/exp-1');
  });
});

describe('ExperimentDetailPage — lifecycle actions', () => {
  it('draft → Start calls POST /start and refreshes the status pill', async () => {
    install(experiment({ status: 'draft' }));
    render(<ExperimentDetailPage />);
    await screen.findByTestId('experiment-detail');

    const actions = screen.getByTestId('experiment-actions');
    expect(within(actions).getByTestId('action-start')).toBeInTheDocument();
    expect(within(actions).queryByTestId('action-pause')).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('action-start'));
    await waitFor(() => expect(screen.getByTestId('experiment-status')).toHaveTextContent('Active'));
    expect(calledWith('POST', '/api/v1/experiments/exp-1/start')).toBe(true);

    // Now active: Pause and Complete are offered, Start is gone.
    expect(screen.getByTestId('action-pause')).toBeInTheDocument();
    expect(screen.getByTestId('action-complete')).toBeInTheDocument();
    expect(screen.queryByTestId('action-start')).not.toBeInTheDocument();
    expect(screen.getByTestId('view-results')).toHaveAttribute('href', '/results/exp-1');
  });

  it('active → Pause calls POST /pause; paused offers Start + Complete', async () => {
    install(experiment({ status: 'active' }));
    render(<ExperimentDetailPage />);
    await screen.findByTestId('experiment-detail');

    fireEvent.click(screen.getByTestId('action-pause'));
    await waitFor(() => expect(screen.getByTestId('experiment-status')).toHaveTextContent('Paused'));
    expect(calledWith('POST', '/api/v1/experiments/exp-1/pause')).toBe(true);
    expect(screen.getByTestId('action-start')).toBeInTheDocument();
    expect(screen.getByTestId('action-complete')).toBeInTheDocument();
  });

  it('Complete asks for confirmation, then calls POST /complete', async () => {
    install(experiment({ status: 'active' }));
    render(<ExperimentDetailPage />);
    await screen.findByTestId('experiment-detail');

    fireEvent.click(screen.getByTestId('action-complete'));
    expect(screen.getByTestId('confirm-action')).toBeInTheDocument();
    expect(calledWith('POST', '/api/v1/experiments/exp-1/complete')).toBe(false);

    // Cancel keeps the status.
    fireEvent.click(screen.getByTestId('confirm-cancel'));
    expect(screen.queryByTestId('confirm-action')).not.toBeInTheDocument();
    expect(screen.getByTestId('experiment-status')).toHaveTextContent('Active');

    fireEvent.click(screen.getByTestId('action-complete'));
    fireEvent.click(screen.getByTestId('confirm-yes'));
    await waitFor(() => expect(screen.getByTestId('experiment-status')).toHaveTextContent('Completed'));
    expect(calledWith('POST', '/api/v1/experiments/exp-1/complete')).toBe(true);
    expect(screen.getByTestId('action-archive')).toBeInTheDocument();
  });

  it('completed → Archive (confirmed) calls POST /archive and leaves no actions', async () => {
    install(experiment({ status: 'completed' }));
    render(<ExperimentDetailPage />);
    await screen.findByTestId('experiment-detail');

    fireEvent.click(screen.getByTestId('action-archive'));
    fireEvent.click(screen.getByTestId('confirm-yes'));
    await waitFor(() => expect(screen.getByTestId('experiment-status')).toHaveTextContent('Archived'));
    expect(calledWith('POST', '/api/v1/experiments/exp-1/archive')).toBe(true);
    expect(screen.getByTestId('experiment-actions').querySelectorAll('button')).toHaveLength(0);
  });

  it('surfaces the backend error and keeps the old status when a transition fails', async () => {
    mockedApiFetch.mockImplementation(
      routedApi([
        { path: '/api/v1/experiments/exp-1', handler: () => experiment({ status: 'draft' }) },
        {
          method: 'POST',
          path: '/api/v1/experiments/exp-1/start',
          handler: () => {
            throw apiError(400, 'Cannot start experiment with status: draft (no metrics)');
          },
        },
      ]) as unknown as typeof apiFetch,
    );

    render(<ExperimentDetailPage />);
    await screen.findByTestId('experiment-detail');
    fireEvent.click(screen.getByTestId('action-start'));

    expect(await screen.findByTestId('action-error')).toHaveTextContent(
      'Cannot start experiment with status: draft (no metrics)',
    );
    expect(screen.getByTestId('experiment-status')).toHaveTextContent('Draft');
    expect(screen.getByTestId('action-start')).not.toBeDisabled();
  });
});

describe('ExperimentDetailPage — error states', () => {
  it('renders a 404 view when the experiment does not exist', async () => {
    mockedApiFetch.mockImplementation(
      routedApi([
        {
          path: '/api/v1/experiments/exp-1',
          handler: () => {
            throw apiError(404, 'Experiment not found');
          },
        },
      ]) as unknown as typeof apiFetch,
    );
    render(<ExperimentDetailPage />);
    expect(await screen.findByTestId('experiment-not-found')).toBeInTheDocument();
    expect(screen.getByText('Experiment not found')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /back to experiments/i })).toHaveAttribute('href', '/experiments');
    expect(screen.queryByTestId('experiment-retry')).not.toBeInTheDocument();
  });

  it('renders a generic error with retry for other failures', async () => {
    let calls = 0;
    mockedApiFetch.mockImplementation(
      routedApi([
        {
          path: '/api/v1/experiments/exp-1',
          handler: () => {
            calls += 1;
            if (calls === 1) throw apiError(0, "Can't reach the API");
            return experiment();
          },
        },
      ]) as unknown as typeof apiFetch,
    );
    render(<ExperimentDetailPage />);
    const errorView = await screen.findByTestId('experiment-error');
    expect(errorView).toHaveTextContent("Can't reach the API");

    fireEvent.click(screen.getByTestId('experiment-retry'));
    expect(await screen.findByTestId('experiment-detail')).toBeInTheDocument();
  });
});
