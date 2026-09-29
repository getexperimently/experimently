/**
 * Guided setup, the default view of `/experiments/new`.
 *
 * The single-page form (`?advanced`) keeps its own tests in
 * experiment-new.test.tsx; this file covers the guided view, and the things
 * both views must agree on (the create request, the role notice).
 */
import fs from 'fs';
import path from 'path';
import React from 'react';
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import NewExperimentPage, { ROLE_CANNOT_CREATE } from '@/pages/experiments/new';
import { apiFetch } from '@/services/api';
import { navigateHard } from '@/components/experiments/new/leaveGuard';
import { FRESH_LOAD_NOTICE, STEP_HEADINGS } from '@/components/experiments/new/Wizard';
import {
  createInitialFormState,
  FORM_EXPERIMENT_TYPES,
  validateForm,
} from '@/components/experiments/new/formState';
import {
  ESTIMATE_PROBLEMS,
  POWER_OPTIONS,
  SIGNIFICANCE_OPTIONS,
} from '@/components/experiments/new/estimate';
import {
  NO_USABLE_ESTIMATE,
  SESSION_EXPIRED_ESTIMATE,
} from '@/components/experiments/new/SampleSizeEstimate';
import { apiError, makeRouter, routedApi, Route } from './helpers/apiMock';

jest.mock('@/services/api', () => ({
  ...jest.requireActual('@/services/api'),
  apiFetch: jest.fn(),
}));

let mockRouter = makeRouter();
jest.mock('next/router', () => ({ useRouter: () => mockRouter }));

jest.mock('next/head', () => {
  const Head = ({ children }: { children: React.ReactNode }) => <>{children}</>;
  Head.displayName = 'MockHead';
  return Head;
});

type TestUser = { role: string; is_superuser?: boolean } | null;
let mockUser: TestUser = null;
jest.mock('@/contexts/AuthContext', () => ({
  useOptionalAuth: () => (mockUser ? { user: mockUser } : null),
}));

jest.mock('@/components/experiments/new/leaveGuard', () => ({
  ...jest.requireActual('@/components/experiments/new/leaveGuard'),
  navigateHard: jest.fn(),
}));

const mockedApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;
const mockedNavigateHard = navigateHard as jest.MockedFunction<typeof navigateHard>;

const SAMPLE_SIZE_PATH = '/api/v1/experiments/analysis/sample-size';
const ESTIMATE_47034 = {
  baseline_rate: 0.12,
  minimum_detectable_effect: 0.05,
  statistical_power: 0.8,
  significance_level: 0.05,
  is_one_sided: false,
  samples_per_variant: 47034,
  total_samples: 94068,
  estimated_duration_days: null,
  notes: null,
};

function routerAt(query: Record<string, string> = {}, isReady = true) {
  const search = new URLSearchParams(query).toString();
  mockRouter = makeRouter({
    pathname: '/experiments/new',
    asPath: `/experiments/new${search ? `?${search}` : ''}`,
    query,
    isReady,
  });
}

function api(extra: Route[] = []) {
  mockedApiFetch.mockImplementation(
    routedApi([
      { method: 'POST', path: '/api/v1/experiments', handler: () => ({ id: 'exp-9', status: 'draft' }) },
      { method: 'GET', path: SAMPLE_SIZE_PATH, handler: () => ESTIMATE_47034 },
      ...extra,
    ]) as unknown as typeof apiFetch,
  );
}

const setValue = (testId: string, value: string) =>
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
const heading = () => screen.getByTestId('wizard-step-heading');
const next = () => fireEvent.click(screen.getByTestId('wizard-next'));
const back = () => fireEvent.click(screen.getByTestId('wizard-back'));
const calls = (method: string) =>
  mockedApiFetch.mock.calls.filter(([, o]) => (o?.method ?? 'GET').toUpperCase() === method);

/** The body as it goes over the wire (undefined dropped), with the builder's random ids removed. */
function wire(body: unknown): unknown {
  const strip = (v: unknown): unknown => {
    if (Array.isArray(v)) return v.map(strip);
    if (v && typeof v === 'object') {
      return Object.fromEntries(
        Object.entries(v as Record<string, unknown>)
          .filter(([k]) => k !== 'id')
          .map(([k, x]) => [k, strip(x)]),
      );
    }
    return v;
  };
  return strip(JSON.parse(JSON.stringify(body)));
}

function postedBody(): unknown {
  const posts = calls('POST');
  expect(posts).toHaveLength(1);
  expect(posts[0][0]).toBe('/api/v1/experiments');
  return posts[0][1]?.json;
}

beforeEach(() => {
  mockedApiFetch.mockReset();
  mockedNavigateHard.mockReset();
  mockUser = null;
  routerAt();
});

// --- the parity fixture: every field away from its default -----------------

function fillDetails() {
  setValue('experiment-name', 'Checkout redesign');
  setValue('experiment-key', 'checkout_v2');
  setValue('experiment-description', 'New layout');
  setValue('experiment-hypothesis', 'Shorter checkout raises purchases');
  setValue('metric-name-0', 'Add to cart');
  setValue('metric-event-0', 'add_to_cart');
  setValue('metric-type-0', 'count');
  fireEvent.click(screen.getByTestId('add-metric'));
  setValue('metric-name-1', 'Revenue');
  setValue('metric-event-1', 'purchase');
  setValue('metric-type-1', 'revenue');
  fireEvent.click(screen.getByTestId('metric-primary-1'));
}

function fillVariantsAndTargeting() {
  setValue('variant-name-0', 'Current');
  setValue('variant-name-1', 'Short form');
  fireEvent.click(screen.getByTestId('add-variant'));
  setValue('variant-name-2', 'One page');
  setValue('variant-allocation-0', '20');
  setValue('variant-allocation-1', '30');
  setValue('variant-allocation-2', '50');
  fireEvent.click(screen.getByTestId('variant-control-1'));
  fireEvent.click(screen.getAllByTestId('add-group')[0]);
  setValue('condition-attribute', 'country');
  setValue('condition-value', 'US');
}

const PARITY_LITERAL = {
  name: 'Checkout redesign',
  key: 'checkout_v2',
  description: 'New layout',
  hypothesis: 'Shorter checkout raises purchases',
  experiment_type: 'mv',
  targeting_rules: {
    logical_operator: 'AND',
    groups: [
      { logical_operator: 'AND', conditions: [{ attribute: 'country', operator: 'equals', value: 'US' }] },
    ],
  },
  variants: [
    { name: 'Current', is_control: false, traffic_allocation: 20 },
    { name: 'Short form', is_control: true, traffic_allocation: 30 },
    { name: 'One page', is_control: false, traffic_allocation: 50 },
  ],
  metrics: [
    { name: 'Add to cart', event_name: 'add_to_cart', metric_type: 'count', is_primary: false },
    { name: 'Revenue', event_name: 'purchase', metric_type: 'revenue', is_primary: true },
  ],
};

async function createThroughAdvanced(): Promise<unknown> {
  routerAt({ advanced: '' });
  api();
  const view = render(<NewExperimentPage />);
  setValue('experiment-type', 'mv');
  fillDetails();
  fillVariantsAndTargeting();
  fireEvent.click(screen.getByTestId('submit-experiment'));
  await waitFor(() => expect(mockRouter.push).toHaveBeenCalledWith('/experiments/exp-9'));
  const body = postedBody();
  view.unmount();
  mockedApiFetch.mockReset();
  return body;
}

async function createThroughGuided(): Promise<unknown> {
  routerAt();
  api();
  const view = render(<NewExperimentPage />);
  fireEvent.click(screen.getByTestId('wizard-type-mv'));
  next();
  fillDetails();
  next();
  fillVariantsAndTargeting();
  next();
  next(); // the estimate is optional
  expect(heading()).toHaveTextContent(STEP_HEADINGS.review);
  fireEvent.click(screen.getByTestId('wizard-create'));
  await waitFor(() => expect(mockRouter.push).toHaveBeenCalledWith('/experiments/exp-9'));
  const body = postedBody();
  view.unmount();
  mockedApiFetch.mockReset();
  return body;
}

describe('guided setup sends exactly the request the single-page form sends', () => {
  it('the same answers produce the same body through both views, equal to the literal', async () => {
    const advanced = wire(await createThroughAdvanced());
    const guided = wire(await createThroughGuided());
    expect(guided).toStrictEqual(advanced);
    expect(guided).toStrictEqual(PARITY_LITERAL);
  });

  it('sends the eight keys of the create request and nothing else', async () => {
    const guided = (await createThroughGuided()) as Record<string, unknown>;
    expect(Object.keys(guided).sort()).toEqual(
      [
        'name',
        'key',
        'description',
        'hypothesis',
        'experiment_type',
        'targeting_rules',
        'variants',
        'metrics',
      ].sort(),
    );
  });

  it('sends null targeting rules when no rule was added', async () => {
    api();
    render(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'Plain');
    next();
    next();
    next();
    fireEvent.click(screen.getByTestId('wizard-create'));
    await waitFor(() => expect(mockRouter.push).toHaveBeenCalled());
    expect((postedBody() as Record<string, unknown>).targeting_rules).toBeNull();
  });

  it('offers exactly the types the single-page form offers', () => {
    render(<NewExperimentPage />);
    const radios = screen.getAllByRole('radio') as HTMLInputElement[];
    expect(radios.map((r) => r.value)).toEqual(FORM_EXPERIMENT_TYPES);
    expect(screen.getByTestId('wizard-type-a_b')).toBeChecked();
  });
});

describe('views and the URL', () => {
  it.each([
    ['?advanced (empty value)', { advanced: '' }, 'new-experiment-form'],
    ['?advanced=1', { advanced: '1' }, 'new-experiment-form'],
    ['no ?advanced', {}, 'guided-setup'],
  ])('%s shows %s', (_label, query, testId) => {
    routerAt(query as Record<string, string>);
    render(<NewExperimentPage />);
    expect(screen.getByTestId(testId)).toBeInTheDocument();
    const other = testId === 'guided-setup' ? 'new-experiment-form' : 'guided-setup';
    expect(screen.queryByTestId(other)).not.toBeInTheDocument();
  });

  it('reads nothing until the router is ready, then shows the view the URL names', () => {
    routerAt({ advanced: '' }, false);
    const { rerender } = render(<NewExperimentPage />);
    expect(screen.getByTestId('new-experiment-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('guided-setup')).not.toBeInTheDocument();
    expect(screen.queryByTestId('new-experiment-form')).not.toBeInTheDocument();
    mockRouter.isReady = true;
    rerender(<NewExperimentPage />);
    expect(screen.getByTestId('new-experiment-form')).toBeInTheDocument();
  });

  it('a fresh load at a later step goes to the first step with the notice', () => {
    routerAt({ step: 'review' });
    render(<NewExperimentPage />);
    expect(mockRouter.replace).toHaveBeenCalledWith(
      { pathname: '/experiments/new', query: { step: 'type' } },
      undefined,
      { shallow: true },
    );
    expect(heading()).toHaveTextContent(STEP_HEADINGS.type);
    expect(screen.getByTestId('wizard-fresh-notice')).toHaveTextContent(FRESH_LOAD_NOTICE);
    expect(screen.getByTestId('wizard-fresh-notice').textContent).toBe(
      'Start from the first step. Answers are kept only in this tab, so reloading or opening a link starts over.',
    );
  });

  it('a fresh load at ?step=type shows no notice and changes nothing', () => {
    routerAt({ step: 'type' });
    render(<NewExperimentPage />);
    expect(heading()).toHaveTextContent(STEP_HEADINGS.type);
    expect(screen.queryByTestId('wizard-fresh-notice')).not.toBeInTheDocument();
    expect(mockRouter.replace).not.toHaveBeenCalled();
  });

  it('in the session, a URL past the furthest reachable step is clamped to it, without the notice', () => {
    const { rerender } = render(<NewExperimentPage />);
    // A new experiment has no name, so Details is as far as it can go.
    mockRouter.query = { step: 'review' };
    rerender(<NewExperimentPage />);
    expect(mockRouter.replace).toHaveBeenCalledWith(
      { pathname: '/experiments/new', query: { step: 'details' } },
      undefined,
      { shallow: true },
    );
    expect(heading()).toHaveTextContent(STEP_HEADINGS.details);
    expect(screen.queryByTestId('wizard-fresh-notice')).not.toBeInTheDocument();
  });

  it('in the session, a reachable step in the URL is shown as it is', () => {
    const { rerender } = render(<NewExperimentPage />);
    next();
    // The router reports the step Next pushed, as the real one does.
    mockRouter.query = { step: 'details' };
    rerender(<NewExperimentPage />);
    setValue('experiment-name', 'Named');
    mockRouter.replace.mockClear();
    mockRouter.query = { step: 'review' };
    rerender(<NewExperimentPage />);
    expect(heading()).toHaveTextContent(STEP_HEADINGS.review);
    expect(mockRouter.replace).not.toHaveBeenCalled();
  });

  it('Next and Back push the step to the URL shallowly and keep every answer', () => {
    render(<NewExperimentPage />);
    next();
    expect(mockRouter.push).toHaveBeenLastCalledWith(
      { pathname: '/experiments/new', query: { step: 'details' } },
      undefined,
      { shallow: true },
    );
    setValue('experiment-name', 'Kept');
    setValue('experiment-hypothesis', 'Still here');
    next();
    setValue('variant-allocation-0', '60');
    setValue('variant-allocation-1', '40');
    back();
    expect(screen.getByTestId('experiment-name')).toHaveValue('Kept');
    expect(screen.getByTestId('experiment-hypothesis')).toHaveValue('Still here');
    next();
    expect(screen.getByTestId('variant-allocation-0')).toHaveValue(60);
  });

  it.each([
    ['rejects (cancelled by the browser Back button)', () => mockRouter.push.mockRejectedValueOnce(new Error('Route Cancelled'))],
    ['resolves false', () => mockRouter.push.mockResolvedValueOnce(false)],
  ])('a step change the router %s leaves the view on the address step', async (_label, arrange) => {
    render(<NewExperimentPage />);
    arrange();
    next();
    // The address still says step 1 (no `?step`), so the view goes back there.
    await waitFor(() => expect(heading()).toHaveTextContent(STEP_HEADINGS.type));
  });

  it('switching to the single-page form and back keeps the answers', () => {
    const { rerender } = render(<NewExperimentPage />);
    expect(screen.getByTestId('switch-to-advanced')).toHaveAttribute('href', '/experiments/new?advanced');
    next();
    setValue('experiment-name', 'Carried over');
    mockRouter.query = { advanced: '' };
    rerender(<NewExperimentPage />);
    expect(screen.getByTestId('new-experiment-form')).toBeInTheDocument();
    expect(screen.getByTestId('experiment-name')).toHaveValue('Carried over');
    mockRouter.query = {};
    rerender(<NewExperimentPage />);
    expect(screen.getByTestId('guided-setup')).toBeInTheDocument();
    expect(screen.queryByTestId('wizard-fresh-notice')).not.toBeInTheDocument();
    next();
    expect(screen.getByTestId('experiment-name')).toHaveValue('Carried over');
  });
});

describe('per-step checks', () => {
  const defaults = createInitialFormState();

  it('Next refuses an unnamed experiment with the whole-form message', () => {
    render(<NewExperimentPage />);
    next();
    next();
    expect(screen.getByTestId('step-error')).toHaveTextContent(
      validateForm('', defaults.variants, defaults.metrics) as string,
    );
    expect(heading()).toHaveTextContent(STEP_HEADINGS.details);
  });

  it('Next on Details refuses a metric with no event name', () => {
    render(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'X');
    setValue('metric-event-0', '');
    next();
    const metrics = [{ ...defaults.metrics[0], event_name: '' }];
    expect(screen.getByTestId('step-error')).toHaveTextContent(
      validateForm('X', defaults.variants, metrics) as string,
    );
  });

  it('Next on Variants refuses allocations that do not add up to 100%', () => {
    render(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'X');
    next();
    setValue('variant-allocation-1', '30');
    next();
    const variants = [defaults.variants[0], { ...defaults.variants[1], traffic_allocation: 30 }];
    const expected = validateForm('X', variants, defaults.metrics) as string;
    expect(expected).toBe('Variant allocations must add up to 100% (currently 80%).');
    expect(screen.getByTestId('step-error')).toHaveTextContent(expected);
    expect(heading()).toHaveTextContent(STEP_HEADINGS.variants);
  });

  it('marks each visited step by its own check: two broken steps, two marks', () => {
    render(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'X');
    next();
    setValue('variant-allocation-1', '30');
    back();
    setValue('experiment-name', '');
    back();
    expect(heading()).toHaveTextContent(STEP_HEADINGS.type);
    expect(screen.getByTestId('wizard-step-problem-details')).toBeInTheDocument();
    expect(screen.getByTestId('wizard-step-problem-variants')).toBeInTheDocument();
    expect(screen.queryByTestId('wizard-step-problem-type')).not.toBeInTheDocument();
  });

  it('marks each visited step by its own check: one broken step, one mark', () => {
    render(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'X');
    next();
    back();
    setValue('experiment-name', '');
    back();
    expect(screen.getByTestId('wizard-step-problem-details')).toBeInTheDocument();
    expect(screen.queryByTestId('wizard-step-problem-variants')).not.toBeInTheDocument();
  });

  it('moves focus to the new step heading, and says which step is current', () => {
    render(<NewExperimentPage />);
    next();
    expect(document.activeElement).toBe(heading());
    expect(screen.getByTestId('wizard-step-details')).toHaveAttribute('aria-current', 'step');
    expect(screen.getByTestId('wizard-step-type')).not.toHaveAttribute('aria-current');
    expect(screen.getByTestId('wizard-step-count')).toHaveTextContent('Step 2 of 5');
  });
});

describe('the Enter key', () => {
  it('in a text field on the first three steps presses Next', async () => {
    const user = userEvent.setup();
    render(<NewExperimentPage />);
    next();
    await user.type(screen.getByTestId('experiment-name'), 'Pricing{enter}');
    expect(heading()).toHaveTextContent(STEP_HEADINGS.variants);
  });

  it('does nothing while an input method is composing', () => {
    render(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'Pricing');
    fireEvent.keyDown(screen.getByTestId('experiment-name'), { key: 'Enter', isComposing: true });
    expect(heading()).toHaveTextContent(STEP_HEADINGS.details);
    fireEvent.keyDown(screen.getByTestId('experiment-name'), { key: 'Enter', keyCode: 229 });
    expect(heading()).toHaveTextContent(STEP_HEADINGS.details);
  });

  it('in a textarea adds a line instead', async () => {
    const user = userEvent.setup();
    render(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'Pricing');
    await user.type(screen.getByTestId('experiment-description'), 'one{enter}two');
    expect(heading()).toHaveTextContent(STEP_HEADINGS.details);
    expect(screen.getByTestId('experiment-description')).toHaveValue('one\ntwo');
  });

  it('never submits anything from the Estimate step or Review', async () => {
    const user = userEvent.setup();
    api();
    render(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'No submit');
    next();
    next();
    expect(heading()).toHaveTextContent(STEP_HEADINGS.estimate);
    for (const id of ['estimate-baseline', 'estimate-mde', 'estimate-daily-users', 'estimate-share']) {
      await user.type(screen.getByTestId(id), '12{enter}');
    }
    expect(heading()).toHaveTextContent(STEP_HEADINGS.estimate);
    expect(mockedApiFetch).not.toHaveBeenCalled();
    next();
    expect(document.activeElement).toBe(heading());
    await user.keyboard('{enter}');
    expect(heading()).toHaveTextContent(STEP_HEADINGS.review);
    expect(mockedApiFetch).not.toHaveBeenCalled();
  });

  it('a keyboard-only walk creates exactly one experiment', async () => {
    const user = userEvent.setup();
    api();
    render(<NewExperimentPage />);
    screen.getByTestId('wizard-next').focus();
    await user.keyboard('{enter}');
    await user.type(screen.getByTestId('experiment-name'), 'Keyboard{enter}');
    screen.getByTestId('variant-name-0').focus();
    await user.keyboard('{enter}');
    screen.getByTestId('wizard-next').focus();
    await user.keyboard('{enter}');
    expect(heading()).toHaveTextContent(STEP_HEADINGS.review);
    screen.getByTestId('wizard-create').focus();
    await user.keyboard('{enter}');
    await waitFor(() => expect(mockRouter.push).toHaveBeenCalledWith('/experiments/exp-9'));
    expect(calls('POST')).toHaveLength(1);
  });
});

async function toEstimate(variants?: () => void) {
  render(<NewExperimentPage />);
  next();
  setValue('experiment-name', 'Estimate me');
  next();
  variants?.();
  next();
  expect(heading()).toHaveTextContent(STEP_HEADINGS.estimate);
}

const estimateCalls = () => mockedApiFetch.mock.calls.filter(([p]) => p.split('?')[0] === SAMPLE_SIZE_PATH);

describe('the Estimate step', () => {
  it('asks the sample-size endpoint only when the button is pressed, in fractions, without a login redirect', async () => {
    api();
    await toEstimate();
    setValue('estimate-baseline', '12');
    setValue('estimate-mde', '5');
    expect(mockedApiFetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('estimate-calculate'));
    expect(await screen.findByTestId('estimate-per-variant')).toHaveTextContent('47,034 users per variant');
    expect(screen.getByTestId('estimate-total')).toHaveTextContent('94,068 users in total across 2 variants');
    expect(estimateCalls()).toHaveLength(1);
    const [p, options] = estimateCalls()[0];
    expect(p).toBe(SAMPLE_SIZE_PATH);
    expect(options).toEqual({
      query: {
        baseline_rate: 0.12,
        minimum_detectable_effect: 0.05,
        statistical_power: 0.8,
        significance_level: 0.05,
        variant_count: 2,
      },
      redirectOn401: false,
    });
    expect(screen.getByTestId('estimate-even-split')).toBeInTheDocument();
  });

  it('sends each power and significance option as offered', async () => {
    api();
    await toEstimate();
    setValue('estimate-baseline', '12');
    setValue('estimate-mde', '5');
    const sent: Array<[unknown, unknown]> = [];
    for (let i = 0; i < 3; i += 1) {
      setValue('estimate-power', String(POWER_OPTIONS[i]));
      setValue('estimate-significance', String(SIGNIFICANCE_OPTIONS[i]));
      fireEvent.click(screen.getByTestId('estimate-calculate'));
      await waitFor(() => expect(estimateCalls()).toHaveLength(i + 1));
      await waitFor(() => expect(screen.getByTestId('estimate-calculate')).not.toBeDisabled());
      const q = estimateCalls()[i][1]?.query as Record<string, unknown>;
      sent.push([q.statistical_power, q.significance_level]);
    }
    expect(sent.map(([p]) => p)).toEqual([0.8, 0.9, 0.95]);
    expect(sent.map(([, s]) => s)).toEqual([0.05, 0.01, 0.1]);
  });

  it('sends the number of variants on the Variants step', async () => {
    api();
    await toEstimate(() => {
      fireEvent.click(screen.getByTestId('add-variant'));
      setValue('variant-allocation-0', '20');
      setValue('variant-allocation-1', '30');
      setValue('variant-allocation-2', '50');
    });
    setValue('estimate-baseline', '12');
    setValue('estimate-mde', '5');
    fireEvent.click(screen.getByTestId('estimate-calculate'));
    await screen.findByTestId('estimate-per-variant');
    expect((estimateCalls()[0][1]?.query as Record<string, unknown>).variant_count).toBe(3);
    expect(screen.getByTestId('estimate-uneven-split')).toBeInTheDocument();
    expect(screen.getByTestId('estimate-many-variants')).toBeInTheDocument();
  });

  it('asks for a duration with all daily users when the share is blank', async () => {
    api();
    await toEstimate();
    setValue('estimate-baseline', '12');
    setValue('estimate-mde', '5');
    setValue('estimate-daily-users', '5000');
    fireEvent.click(screen.getByTestId('estimate-calculate'));
    await screen.findByTestId('estimate-per-variant');
    expect(estimateCalls()[0][1]?.query).toMatchObject({ daily_traffic: 5000, traffic_allocation: 1 });
  });

  it.each([
    ['no baseline', {}, ESTIMATE_PROBLEMS.baseline],
    ['a baseline of 100%', { 'estimate-baseline': '100' }, ESTIMATE_PROBLEMS.baseline],
    ['no effect', { 'estimate-baseline': '12' }, ESTIMATE_PROBLEMS.mde],
    ['an effect past 100%', { 'estimate-baseline': '60', 'estimate-mde': '80' }, ESTIMATE_PROBLEMS.ceiling],
    ['fractional daily users', { 'estimate-baseline': '12', 'estimate-mde': '5', 'estimate-daily-users': '1.5' }, ESTIMATE_PROBLEMS.dailyUsers],
    ['a share of 0%', { 'estimate-baseline': '12', 'estimate-mde': '5', 'estimate-daily-users': '10', 'estimate-share': '0' }, ESTIMATE_PROBLEMS.share],
  ])('refuses %s in its own alert, without a request', async (_label, fields, problem) => {
    api();
    await toEstimate();
    for (const [id, value] of Object.entries(fields)) setValue(id, value as string);
    fireEvent.click(screen.getByTestId('estimate-calculate'));
    expect(screen.getByTestId('estimate-error')).toHaveAttribute('role', 'alert');
    expect(screen.getByTestId('estimate-error')).toHaveTextContent(problem);
    expect(screen.queryByTestId('step-error')).toHaveTextContent('');
    expect(mockedApiFetch).not.toHaveBeenCalled();
  });

  it('with a single variant says it needs two and sends nothing', async () => {
    api();
    await toEstimate(() => {
      fireEvent.click(screen.getByTestId('remove-variant-1'));
      setValue('variant-allocation-0', '100');
    });
    setValue('estimate-baseline', '12');
    setValue('estimate-mde', '5');
    fireEvent.click(screen.getByTestId('estimate-calculate'));
    expect(screen.getByTestId('estimate-error')).toHaveTextContent(ESTIMATE_PROBLEMS.variants);
    expect(mockedApiFetch).not.toHaveBeenCalled();
  });

  it('treats an answer below one user per variant as an error', async () => {
    mockedApiFetch.mockImplementation(
      routedApi([
        { method: 'GET', path: SAMPLE_SIZE_PATH, handler: () => ({ ...ESTIMATE_47034, samples_per_variant: -1 }) },
      ]) as unknown as typeof apiFetch,
    );
    await toEstimate();
    setValue('estimate-baseline', '12');
    setValue('estimate-mde', '5');
    fireEvent.click(screen.getByTestId('estimate-calculate'));
    await waitFor(() => expect(screen.getByTestId('estimate-error')).toHaveTextContent(NO_USABLE_ESTIMATE));
    expect(screen.queryByTestId('estimate-per-variant')).not.toBeInTheDocument();
  });

  it.each([
    [401, SESSION_EXPIRED_ESTIMATE],
    [500, 'boom'],
    [422, 'baseline_rate: Input should be less than 1'],
  ])('a %i from the estimate is shown in the panel and never blocks creating', async (status, message) => {
    mockedApiFetch.mockImplementation(
      routedApi([
        {
          method: 'GET',
          path: SAMPLE_SIZE_PATH,
          handler: () => {
            throw apiError(status, status === 401 ? 'Not authenticated' : message);
          },
        },
        { method: 'POST', path: '/api/v1/experiments', handler: () => ({ id: 'exp-9' }) },
      ]) as unknown as typeof apiFetch,
    );
    await toEstimate();
    setValue('estimate-baseline', '12');
    setValue('estimate-mde', '5');
    fireEvent.click(screen.getByTestId('estimate-calculate'));
    await waitFor(() => expect(screen.getByTestId('estimate-error')).toHaveTextContent(message));
    next();
    expect(heading()).toHaveTextContent(STEP_HEADINGS.review);
    fireEvent.click(screen.getByTestId('wizard-create'));
    await waitFor(() => expect(mockRouter.push).toHaveBeenCalledWith('/experiments/exp-9'));
  });

  it('says when the inputs changed since the estimate', async () => {
    api();
    await toEstimate();
    setValue('estimate-baseline', '12');
    setValue('estimate-mde', '5');
    fireEvent.click(screen.getByTestId('estimate-calculate'));
    await screen.findByTestId('estimate-per-variant');
    expect(screen.queryByTestId('estimate-stale')).not.toBeInTheDocument();
    setValue('estimate-mde', '6');
    expect(screen.getByTestId('estimate-stale')).toBeInTheDocument();
  });

  it('keeps the estimate across Back and Next, and never puts it in the create request', async () => {
    api();
    await toEstimate();
    setValue('estimate-baseline', '12');
    setValue('estimate-mde', '5');
    setValue('estimate-daily-users', '5000');
    fireEvent.click(screen.getByTestId('estimate-calculate'));
    await screen.findByTestId('estimate-per-variant');
    back();
    next();
    expect(screen.getByTestId('estimate-baseline')).toHaveValue(12);
    expect(screen.getByTestId('estimate-per-variant')).toBeInTheDocument();
    next();
    expect(screen.getByTestId('review-estimate')).toHaveTextContent('47,034 users per variant');
    fireEvent.click(screen.getByTestId('wizard-create'));
    await waitFor(() => expect(mockRouter.push).toHaveBeenCalled());
    const text = JSON.stringify(postedBody());
    expect(text).not.toMatch(/baseline|detectable|power|significance|daily|47034|5000/);
  });

  it('makes exactly the calls it needs: one estimate, one create, nothing else', async () => {
    api();
    await toEstimate();
    setValue('estimate-baseline', '12');
    setValue('estimate-mde', '5');
    fireEvent.click(screen.getByTestId('estimate-calculate'));
    await screen.findByTestId('estimate-per-variant');
    next();
    fireEvent.click(screen.getByTestId('wizard-create'));
    await waitFor(() => expect(mockRouter.push).toHaveBeenCalled());
    const seen = mockedApiFetch.mock.calls.map(([p, o]) => `${(o?.method ?? 'GET').toUpperCase()} ${p}`);
    expect(seen).toEqual([`GET ${SAMPLE_SIZE_PATH}`, 'POST /api/v1/experiments']);
    expect(seen.join(' ')).not.toContain('/wizard');
  });
});

describe('creating', () => {
  async function toReview() {
    render(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'Create me');
    next();
    next();
    next();
    expect(heading()).toHaveTextContent(STEP_HEADINGS.review);
  }

  it('shows the answers as they will be sent, with a way back to each step', async () => {
    await toReview();
    expect(screen.getByTestId('review-name')).toHaveTextContent('Create me');
    expect(screen.getByTestId('review-key')).toHaveTextContent('create_me');
    expect(screen.getByTestId('review-variants')).toHaveTextContent('Control: 50% (control)');
    expect(screen.getByTestId('review-targeting')).toHaveTextContent('Targeting: everyone');
    fireEvent.click(screen.getByTestId('review-edit-details'));
    expect(heading()).toHaveTextContent(STEP_HEADINGS.details);
  });

  it('one click creates one experiment even when pressed twice', async () => {
    api();
    await toReview();
    const create = screen.getByTestId('wizard-create');
    // Both presses land before React re-renders and disables the button.
    act(() => {
      create.click();
      create.click();
    });
    await waitFor(() => expect(mockRouter.push).toHaveBeenCalledWith('/experiments/exp-9'));
    expect(calls('POST')).toHaveLength(1);
    expect(mockedNavigateHard).not.toHaveBeenCalled();
  });

  it('a failed create stays on Review with the answers kept', async () => {
    mockedApiFetch.mockImplementation(
      routedApi([
        {
          method: 'POST',
          path: '/api/v1/experiments',
          handler: () => {
            throw apiError(422, 'metrics: List should have at least 1 item');
          },
        },
      ]) as unknown as typeof apiFetch,
    );
    await toReview();
    fireEvent.click(screen.getByTestId('wizard-create'));
    expect(await screen.findByTestId('form-error')).toHaveTextContent('metrics: List should have at least 1 item');
    expect(mockRouter.push).not.toHaveBeenCalledWith(expect.stringMatching(/^\/experiments\/exp/));
    expect(screen.getByTestId('review-name')).toHaveTextContent('Create me');
    expect(screen.getByTestId('wizard-create')).not.toBeDisabled();
  });
});

describe('the unsaved-answers warning', () => {
  const unload = () => {
    const event = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  };

  it('does not ask while nothing has been entered', () => {
    render(<NewExperimentPage />);
    expect(unload()).toBe(false);
  });

  it('asks once an answer has been entered', () => {
    render(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'Unsaved');
    expect(unload()).toBe(true);
  });

  it.each([
    ['rejects', () => mockRouter.push.mockRejectedValue(new Error('Route change cancelled'))],
    ['resolves false', () => mockRouter.push.mockResolvedValue(false)],
  ])(
    'after a create whose route change %s, goes to the experiment by a full load, without asking and without an error',
    async (_label, arrange) => {
      api();
      arrange();
      let askedDuringFallback: boolean | null = null;
      mockedNavigateHard.mockImplementation(() => {
        // What the browser does next: fire beforeunload before leaving.
        askedDuringFallback = unload();
      });
      render(<NewExperimentPage />);
      next();
      setValue('experiment-name', 'Saved');
      next();
      next();
      next();
      fireEvent.click(screen.getByTestId('wizard-create'));
      await waitFor(() => expect(mockedNavigateHard).toHaveBeenCalledWith('/experiments/exp-9'));
      expect(askedDuringFallback).toBe(false);
      expect(screen.queryByTestId('form-error')).not.toBeInTheDocument();
      expect(calls('POST')).toHaveLength(1);
    },
  );
});

describe('who may create', () => {
  const cases: Array<[string, TestUser, boolean]> = [
    ['ADMIN', { role: 'ADMIN' }, true],
    ['DEVELOPER', { role: 'DEVELOPER' }, true],
    ['ANALYST', { role: 'ANALYST' }, false],
    ['VIEWER', { role: 'VIEWER' }, false],
    ['superuser VIEWER', { role: 'VIEWER', is_superuser: true }, true],
    ['superuser ANALYST', { role: 'ANALYST', is_superuser: true }, true],
  ];

  for (const view of ['guided', 'advanced'] as const) {
    it.each(cases)(`${view}: %s`, (_label, user, allowed) => {
      mockUser = user;
      routerAt(view === 'advanced' ? { advanced: '' } : {});
      render(<NewExperimentPage />);
      if (allowed) {
        expect(screen.queryByTestId('create-not-allowed')).not.toBeInTheDocument();
        expect(screen.getByTestId(view === 'advanced' ? 'new-experiment-form' : 'guided-setup')).toBeInTheDocument();
      } else {
        expect(screen.getByTestId('create-not-allowed')).toHaveTextContent(ROLE_CANNOT_CREATE);
        expect(screen.queryByTestId('guided-setup')).not.toBeInTheDocument();
        expect(screen.queryByTestId('new-experiment-form')).not.toBeInTheDocument();
      }
      expect(mockedApiFetch).not.toHaveBeenCalled();
    });
  }
});

describe('contrast', () => {
  // Low-contrast text classes on white: slate-400 is about 2.6:1, red-400 and
  // red-500 below 4.5:1. Guided setup's own files must not use them.
  const FILES = ['Wizard.tsx', 'SampleSizeEstimate.tsx'];
  it.each(FILES)('%s uses no low-contrast text colour', (file) => {
    const source = fs.readFileSync(
      path.join(__dirname, '..', '..', 'components', 'experiments', 'new', file),
      'utf8',
    );
    expect(source.match(/\btext-(slate-400|red-400|red-500)\b/g)).toBeNull();
  });
});
