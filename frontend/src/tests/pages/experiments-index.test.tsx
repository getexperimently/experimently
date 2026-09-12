import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import ExperimentsPage from '@/pages/experiments/index';
import { apiFetch } from '@/services/api';
import { Experiment } from '@/types/experiments';
import { apiError, makeRouter, routedApi } from './helpers/apiMock';

jest.mock('@/services/api', () => ({
  ...jest.requireActual('@/services/api'),
  apiFetch: jest.fn(),
}));

const mockRouter = makeRouter({ pathname: '/experiments', asPath: '/experiments' });
jest.mock('next/router', () => ({ useRouter: () => mockRouter }));

jest.mock('next/head', () => {
  const Head = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  Head.displayName = 'MockHead';
  return Head;
});

const mockedApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;

function exp(overrides: Partial<Experiment>): Experiment {
  return {
    id: 'exp-1',
    name: 'Checkout CTA',
    key: 'checkout-cta',
    experiment_type: 'a_b',
    status: 'active',
    targeting_rules: null,
    owner_id: 'a1b2c3d4-0000-0000-0000-000000000000',
    start_date: null,
    end_date: null,
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-01T10:00:00Z',
    variants: [
      { id: 'v1', name: 'Control', is_control: true, traffic_allocation: 50 },
      { id: 'v2', name: 'B', is_control: false, traffic_allocation: 50 },
    ],
    metrics: [],
    ...overrides,
  };
}

function listResponse(items: Experiment[]) {
  return { items, total: items.length, skip: 0, limit: 100 };
}

beforeEach(() => {
  mockedApiFetch.mockReset();
  process.env.NEXT_PUBLIC_API_URL = 'http://api.test';
});

afterAll(() => {
  delete process.env.NEXT_PUBLIC_API_URL;
});

describe('ExperimentsPage', () => {
  it('renders the table with a Type column filled from experiment_type and no owner UUID', async () => {
    mockedApiFetch.mockImplementation(
      routedApi([
        {
          path: '/api/v1/experiments',
          handler: () =>
            listResponse([
              exp({ id: 'exp-1', name: 'Checkout CTA', experiment_type: 'a_b' }),
              exp({ id: 'exp-2', name: 'Pricing page', experiment_type: 'bandit', status: 'draft' }),
              exp({ id: 'exp-3', name: 'Unknown type', experiment_type: 'weird' }),
            ]),
        },
      ]) as unknown as typeof apiFetch,
    );

    render(<ExperimentsPage />);
    expect(screen.getByTestId('experiments-loading')).toBeInTheDocument();

    const table = await screen.findByTestId('experiments-table');
    const rows = within(table).getAllByTestId('experiment-row');
    expect(rows).toHaveLength(3);

    const types = within(table).getAllByTestId('experiment-type-cell').map((el) => el.textContent);
    expect(types).toEqual(['A/B Test', 'Bandit', 'weird']);

    expect(within(rows[0]).getByTestId('experiment-link')).toHaveAttribute('href', '/experiments/exp-1');
    expect(within(rows[0]).getByTestId('experiment-status-pill')).toHaveTextContent('Active');
    expect(within(rows[1]).getByTestId('experiment-status-pill')).toHaveTextContent('Draft');

    // The list response only carries owner_id; the raw UUID must not be rendered.
    expect(table).not.toHaveTextContent('a1b2c3d4-0000');
    expect(within(table).queryByText('Owner')).not.toBeInTheDocument();
    expect(screen.queryByTestId('first-run-checklist')).not.toBeInTheDocument();
  });

  it('sends the status filter as status_filter when a pill is clicked', async () => {
    mockedApiFetch.mockImplementation(
      routedApi([{ path: '/api/v1/experiments', handler: () => listResponse([exp({})]) }]) as unknown as typeof apiFetch,
    );
    render(<ExperimentsPage />);
    await screen.findByTestId('experiments-table');

    fireEvent.click(screen.getByTestId('filter-paused'));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(2));
    const [, options] = mockedApiFetch.mock.calls[1];
    expect(options?.query).toMatchObject({ status_filter: 'paused' });
    expect(screen.getByTestId('filter-paused')).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows the first-run checklist with a copyable curl when there are no experiments', async () => {
    mockedApiFetch.mockImplementation(
      routedApi([{ path: '/api/v1/experiments', handler: () => listResponse([]) }]) as unknown as typeof apiFetch,
    );
    render(<ExperimentsPage />);

    const card = await screen.findByTestId('first-run-checklist');
    expect(within(card).getByTestId('checklist-create-experiment')).toHaveAttribute('href', '/experiments/new');
    expect(within(card).getByTestId('checklist-api-keys')).toHaveAttribute('href', '/admin/api-keys');

    const curl = within(card).getByTestId('checklist-curl').textContent ?? '';
    expect(curl).toContain('http://api.test/api/v1/tracking/assign');
    expect(curl).toContain('X-API-Key');
    expect(curl).toContain('"experiment_key"');
    expect(curl).toContain('"user_id"');

    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    fireEvent.click(within(card).getByTestId('checklist-copy-curl'));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(curl));
    expect(await within(card).findByText('Copied')).toBeInTheDocument();
    expect(screen.queryByTestId('experiments-table')).not.toBeInTheDocument();
  });

  it('shows a plain empty state (not the checklist) when a filter yields nothing', async () => {
    mockedApiFetch.mockImplementation(
      routedApi([
        {
          path: '/api/v1/experiments',
          handler: (_path, options) =>
            options.query?.status_filter ? listResponse([]) : listResponse([exp({})]),
        },
      ]) as unknown as typeof apiFetch,
    );
    render(<ExperimentsPage />);
    await screen.findByTestId('experiments-table');

    fireEvent.click(screen.getByTestId('filter-completed'));
    const empty = await screen.findByTestId('experiments-empty');
    expect(empty).toHaveTextContent('No completed experiments');
    expect(screen.queryByTestId('first-run-checklist')).not.toBeInTheDocument();

    fireEvent.click(within(empty).getByRole('button', { name: /show all/i }));
    expect(await screen.findByTestId('experiments-table')).toBeInTheDocument();
  });

  it('renders the error banner when the list request fails', async () => {
    mockedApiFetch.mockImplementation(
      routedApi([
        {
          path: '/api/v1/experiments',
          handler: () => {
            throw apiError(500, 'database is on fire');
          },
        },
      ]) as unknown as typeof apiFetch,
    );
    render(<ExperimentsPage />);
    expect(await screen.findByTestId('experiments-error')).toHaveTextContent('database is on fire');
    expect(screen.queryByTestId('first-run-checklist')).not.toBeInTheDocument();
  });
});
