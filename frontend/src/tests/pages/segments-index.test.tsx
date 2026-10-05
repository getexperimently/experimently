/**
 * The Segments list (#440 PR D; gates-D D13-D16, D18, D21).
 */
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import axe from 'axe-core';
import SegmentsPage from '@/pages/segments/index';
import { ApiError, apiFetch } from '@/services/api';
import { Segment } from '@/services/segments';
import { makeRouter, routedApi } from './helpers/apiMock';

jest.mock('@/services/api', () => ({
  ...jest.requireActual('@/services/api'),
  apiFetch: jest.fn(),
}));

const mockRouter = makeRouter({ pathname: '/segments', asPath: '/segments' });
jest.mock('next/router', () => ({ useRouter: () => mockRouter }));

const mockAuth = jest.fn();
jest.mock('@/contexts/AuthContext', () => ({ useOptionalAuth: () => mockAuth() }));

jest.mock('next/head', () => {
  const Head = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  Head.displayName = 'MockHead';
  return Head;
});

const mocked = apiFetch as jest.MockedFunction<typeof apiFetch>;

function signIn(role: string, is_superuser = false) {
  mockAuth.mockReturnValue({
    status: 'authenticated',
    user: { id: 'u1', email: 'u@example.com', username: 'u', role, is_superuser },
  });
}

function seg(overrides: Partial<Segment>): Segment {
  return {
    id: 'seg-1',
    name: 'Enterprise pilot',
    description: 'CRM export',
    kind: 'id_list',
    rules: null,
    status: 'active',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-02T00:00:00Z',
    ...overrides,
  };
}

function serve(handler: (options: { query?: Record<string, unknown> }) => unknown) {
  mocked.mockImplementation(
    routedApi([{ path: '/api/v1/segments', handler: (_p, options) => handler(options as never) }]) as unknown as typeof apiFetch,
  );
}

const axeOptions: axe.RunOptions = { rules: { 'color-contrast': { enabled: false } } };
async function violations(node: Element) {
  const result = await axe.run(node, axeOptions);
  return result.violations.map((v) => `${v.id} (${v.impact})`);
}

beforeEach(() => {
  mocked.mockReset();
  signIn('DEVELOPER');
});

describe('SegmentsPage', () => {
  it('lists active segments by default with type, status and a link to each', async () => {
    const queries: unknown[] = [];
    serve(({ query }) => {
      queries.push(query);
      return [
        seg({}),
        seg({ id: 'seg-2', name: 'Pro plan', kind: 'rules', rules: { groups: [{ conditions: [{ attribute: 'plan', operator: 'equals', value: 'pro' }] }] } }),
      ];
    });
    const { container } = render(<SegmentsPage />);
    expect(screen.getByTestId('segments-loading')).toHaveTextContent('Loading segments...');
    const rows = await screen.findAllByTestId('segment-row');
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByTestId('segment-link')).toHaveAttribute('href', '/segments/seg-1');
    expect(within(rows[0]).getByTestId('segment-kind')).toHaveTextContent('ID list');
    expect(within(rows[1]).getByTestId('segment-kind')).toHaveTextContent(/^Rules$/);
    expect(within(rows[0]).getByTestId('segment-status')).toHaveTextContent('Active');
    expect(queries).toEqual([{ status: 'active', limit: 50, offset: 0 }]);
    expect(await violations(container)).toEqual([]);
  });

  it('the filters are sent to the API, and All sends no status', async () => {
    const queries: unknown[] = [];
    serve(({ query }) => {
      queries.push(query);
      return [seg({})];
    });
    render(<SegmentsPage />);
    await screen.findAllByTestId('segment-row');
    fireEvent.click(screen.getByTestId('segment-filter-archived'));
    await waitFor(() => expect(queries).toHaveLength(2));
    expect(screen.getByTestId('segment-filter-archived')).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByTestId('segment-filter-all'));
    await waitFor(() => expect(queries).toHaveLength(3));
    expect(queries[1]).toEqual({ status: 'archived', limit: 50, offset: 0 });
    expect(queries[2]).toEqual({ status: undefined, limit: 50, offset: 0 });
  });

  it('pages with Next and Previous', async () => {
    const queries: Array<{ offset?: number }> = [];
    serve(({ query }) => {
      queries.push(query as { offset?: number });
      const n = (query?.offset as number) === 0 ? 50 : 3;
      return Array.from({ length: n }, (_, i) => seg({ id: `s${i}`, name: `S${i}` }));
    });
    render(<SegmentsPage />);
    await screen.findAllByTestId('segment-row');
    expect(screen.getByTestId('segments-previous')).toBeDisabled();
    fireEvent.click(screen.getByTestId('segments-next'));
    await waitFor(() => expect(screen.getAllByTestId('segment-row')).toHaveLength(3));
    expect(queries[1].offset).toBe(50);
    expect(screen.getByTestId('segments-next')).toBeDisabled();
  });

  it('marks legacy rules "Rules not valid" (D18)', async () => {
    serve(() => [
      seg({ id: 'a', kind: 'rules', rules: { operator: 'and', conditions: [{ attribute: 'plan', operator: 'eq', value: 'pro' }] } }),
      seg({ id: 'b', kind: 'rules', rules: { groups: [] } }),
      seg({ id: 'c', kind: 'rules', rules: { groups: [{ conditions: [{ attribute: 'plan', operator: 'equals', value: 'pro' }] }] } }),
    ]);
    render(<SegmentsPage />);
    const rows = await screen.findAllByTestId('segment-row');
    expect(within(rows[0]).getByTestId('segment-rules-not-valid')).toHaveTextContent('Rules not valid');
    expect(within(rows[1]).getByTestId('segment-rules-not-valid')).toBeInTheDocument();
    expect(within(rows[2]).queryByTestId('segment-rules-not-valid')).toBeNull();
  });

  describe('empty states (D16)', () => {
    it('under All, a writer is offered Create', async () => {
      serve(() => []);
      const { container } = render(<SegmentsPage />);
      await screen.findByText('No segments match this filter.');
      fireEvent.click(screen.getByTestId('segment-filter-all'));
      const empty = await screen.findByText('No segments yet.');
      expect(empty).toBeInTheDocument();
      expect(screen.getByTestId('segments-empty-create')).toHaveAttribute('href', '/segments/new');
      expect(await violations(container)).toEqual([]);
    });

    it('under a filter, it offers Show all', async () => {
      serve(() => []);
      render(<SegmentsPage />);
      expect(await screen.findByText('No segments match this filter.')).toBeInTheDocument();
      fireEvent.click(screen.getByTestId('segments-show-all'));
      expect(await screen.findByText('No segments yet.')).toBeInTheDocument();
    });

    it('under All, a reader gets the role note instead of Create', async () => {
      signIn('VIEWER');
      serve(() => []);
      render(<SegmentsPage />);
      fireEvent.click(await screen.findByTestId('segment-filter-all'));
      await screen.findByText('No segments yet.');
      expect(screen.queryByTestId('segments-empty-create')).toBeNull();
      expect(screen.getByTestId('segments-empty')).toHaveTextContent('ADMIN and DEVELOPER');
    });
  });

  describe('a failed load (D14, D15)', () => {
    it('shows fixed copy and Retry, never an empty state or the server text', async () => {
      let calls = 0;
      serve(() => {
        calls += 1;
        if (calls === 1) throw new ApiError({ status: 500, detail: 'Traceback sqlalchemy.exc.PLANTED' });
        return [seg({})];
      });
      const { container } = render(<SegmentsPage />);
      const error = await screen.findByTestId('segments-error');
      expect(error).toHaveTextContent('Something went wrong on the server.');
      expect(document.body.textContent).not.toContain('PLANTED');
      expect(screen.queryByTestId('segments-empty')).toBeNull();
      expect(await violations(container)).toEqual([]);
      fireEvent.click(screen.getByTestId('segments-retry'));
      expect(await screen.findAllByTestId('segment-row')).toHaveLength(1);
    });

    it('a TypeError gets the dashboard copy', async () => {
      serve(() => {
        throw new TypeError("Cannot read properties of undefined (reading 'x')");
      });
      render(<SegmentsPage />);
      const error = await screen.findByTestId('segments-error');
      expect(error).not.toHaveTextContent('Cannot read');
      expect(screen.queryByTestId('segments-empty')).toBeNull();
    });
  });

  describe('roles (D13)', () => {
    it.each(['ADMIN', 'DEVELOPER'])('%s gets New segment', async (role) => {
      signIn(role);
      serve(() => [seg({})]);
      render(<SegmentsPage />);
      await screen.findAllByTestId('segment-row');
      expect(screen.getByTestId('new-segment-btn')).toHaveAttribute('href', '/segments/new');
      expect(screen.queryByTestId('segments-role-note')).toBeNull();
    });

    it.each(['ANALYST', 'VIEWER'])('%s gets the role note and no create control', async (role) => {
      signIn(role);
      serve(() => [seg({})]);
      render(<SegmentsPage />);
      await screen.findAllByTestId('segment-row');
      expect(screen.queryByTestId('new-segment-btn')).toBeNull();
      expect(screen.getByTestId('segments-role-note')).toHaveTextContent('ADMIN and DEVELOPER');
    });

    it('a superuser whatever the role gets New segment', async () => {
      signIn('VIEWER', true);
      serve(() => [seg({})]);
      render(<SegmentsPage />);
      await screen.findAllByTestId('segment-row');
      expect(screen.getByTestId('new-segment-btn')).toBeInTheDocument();
    });
  });
});
