/**
 * A variant's configuration, and Bayesian analysis, on `/experiments/new` (#442).
 *
 * Both views: guided setup (the default) and the single-page form
 * (`?advanced`). The request both views send is pinned with every other field
 * in experiment-new-guided.test.tsx ("guided setup sends exactly the request
 * the single-page form sends"); this file covers the field itself: what it
 * refuses, that a problem is never left in a closed section, what Review
 * shows, who sees it, and that it passes axe.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import axe from 'axe-core';
import NewExperimentPage from '@/pages/experiments/new';
import { ApiError, apiFetch } from '@/services/api';
import {
  CONFIGURATION_MAX_BYTES,
  CONFIGURATION_NOT_JSON,
  CONFIGURATION_NOT_OBJECT,
} from '@/components/experiments/new/formState';
import { STEP_HEADINGS } from '@/components/experiments/new/Wizard';
import { BAYESIAN_HELP, BAYESIAN_LABEL } from '@/components/experiments/new/AnalysisSettingsFields';
import { CREATE_FAILED } from '@/components/experiments/new/createErrors';
import { makeRouter, routedApi } from './helpers/apiMock';

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

type TestUser = { role: string; is_superuser?: boolean };
// A resolved user in every test: with no user the page shows the create
// controls for any role, so a role test without one would pass for the wrong reason.
let mockUser: TestUser = { role: 'DEVELOPER', is_superuser: false };
jest.mock('@/contexts/AuthContext', () => ({
  useOptionalAuth: () => ({ user: mockUser }),
}));

const mockedApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;

function routerAt(query: Record<string, string> = {}) {
  const search = new URLSearchParams(query).toString();
  mockRouter = makeRouter({
    pathname: '/experiments/new',
    asPath: `/experiments/new${search ? `?${search}` : ''}`,
    query,
  });
}

function api() {
  mockedApiFetch.mockImplementation(
    routedApi([
      { method: 'POST', path: '/api/v1/experiments', handler: () => ({ id: 'exp-9', status: 'draft' }) },
    ]) as unknown as typeof apiFetch,
  );
}

const setValue = (testId: string, value: string) =>
  fireEvent.change(screen.getByTestId(testId), { target: { value } });
const next = () => fireEvent.click(screen.getByTestId('wizard-next'));
const heading = () => screen.getByTestId('wizard-step-heading');
const posts = () =>
  mockedApiFetch.mock.calls.filter(([, o]) => (o?.method ?? 'GET').toUpperCase() === 'POST');

/** Guided setup, on the Variants step, with a valid name. */
function toVariants() {
  routerAt();
  api();
  render(<NewExperimentPage />);
  next();
  setValue('experiment-name', 'Hero copy');
  next();
  expect(heading()).toHaveTextContent(STEP_HEADINGS.variants);
}

/** A JSON object of `bytes` UTF-8 bytes ending in `é` (two bytes, one character). */
function overLimitText(): string {
  const head = '{"a":"';
  const tail = '"}';
  // One byte over the limit: the filler leaves room for one 'é' (2 bytes) where 1 byte would fit.
  return head + 'x'.repeat(CONFIGURATION_MAX_BYTES - head.length - tail.length - 1) + 'é' + tail;
}

beforeEach(() => {
  mockedApiFetch.mockReset();
  mockUser = { role: 'DEVELOPER', is_superuser: false };
  routerAt();
});

describe('the configuration field', () => {
  it('is closed by default, and opens with a visible label, help and placeholder', () => {
    toVariants();
    const toggle = screen.getByTestId('variant-configuration-toggle-1');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('variant-configuration-1')).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const field = screen.getByLabelText('Configuration (JSON) for Treatment');
    expect(field).toBe(screen.getByTestId('variant-configuration-1'));
    expect(field).toHaveAttribute('placeholder', '{"button_color": "green"}');
    expect(field).toHaveAccessibleDescription(/your app receives this object with the assignment/i);
  });

  it.each([
    ['[1, 2]', CONFIGURATION_NOT_OBJECT],
    ['"blue"', CONFIGURATION_NOT_OBJECT],
    ['null', CONFIGURATION_NOT_OBJECT],
    ['{"a": 1,}', CONFIGURATION_NOT_JSON],
  ])('refuses %s beside the field and at Next, and sends nothing', (text, problem) => {
    toVariants();
    fireEvent.click(screen.getByTestId('variant-configuration-toggle-1'));
    setValue('variant-configuration-1', text);
    expect(screen.getByTestId('variant-configuration-error-1')).toHaveTextContent(problem);
    expect(screen.getByTestId('variant-configuration-1')).toHaveAttribute('aria-invalid', 'true');
    next();
    expect(heading()).toHaveTextContent(STEP_HEADINGS.variants);
    expect(screen.getByTestId('step-error')).toHaveTextContent(
      `The configuration of “Treatment” needs fixing: ${problem}`,
    );
    expect(posts()).toHaveLength(0);
  });

  it('refuses a configuration one byte over the limit when the last character is two bytes, and says the API accepts more', () => {
    toVariants();
    fireEvent.click(screen.getByTestId('variant-configuration-toggle-0'));
    const text = overLimitText();
    expect(text.length).toBe(CONFIGURATION_MAX_BYTES); // characters: at the limit
    setValue('variant-configuration-0', text);
    const error = screen.getByTestId('variant-configuration-error-0');
    expect(error).toHaveTextContent(
      'This configuration is 16,385 bytes. The dashboard accepts up to 16,384 bytes; the API accepts larger ones.',
    );
    next();
    expect(heading()).toHaveTextContent(STEP_HEADINGS.variants);
  });

  it('clears the problem once the text is fixed, and moves on', () => {
    toVariants();
    fireEvent.click(screen.getByTestId('variant-configuration-toggle-1'));
    setValue('variant-configuration-1', '{"a": ');
    expect(screen.getByTestId('variant-configuration-error-1')).toBeInTheDocument();
    setValue('variant-configuration-1', '{"a": 1}');
    expect(screen.queryByTestId('variant-configuration-error-1')).not.toBeInTheDocument();
    expect(screen.getByTestId('variant-configuration-1')).not.toHaveAttribute('aria-invalid');
    next();
    expect(heading()).toHaveTextContent(STEP_HEADINGS.estimate);
  });

  it('a closed section that holds text says so', () => {
    toVariants();
    const toggle = screen.getByTestId('variant-configuration-toggle-1');
    fireEvent.click(toggle);
    setValue('variant-configuration-1', '{"a": 1}');
    fireEvent.click(toggle);
    expect(screen.getByTestId('variant-configuration-set-1')).toHaveTextContent(': set');
    fireEvent.click(toggle);
    setValue('variant-configuration-1', '{"a": ');
    fireEvent.click(toggle);
    expect(screen.getByTestId('variant-configuration-set-1')).toHaveTextContent(': needs fixing');
  });

  it('removing a variant keeps each open section with its own variant', () => {
    toVariants();
    fireEvent.click(screen.getByTestId('add-variant'));
    fireEvent.click(screen.getByTestId('variant-configuration-toggle-2'));
    setValue('variant-configuration-2', '{"third": true}');
    fireEvent.click(screen.getByTestId('remove-variant-1'));
    // The third variant is now the second; its section is still open with its text.
    expect(screen.getByTestId('variant-configuration-toggle-1')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('variant-configuration-1')).toHaveValue('{"third": true}');
    expect(screen.getByTestId('variant-configuration-toggle-0')).toHaveAttribute('aria-expanded', 'false');
  });
});

describe('a problem is never left in a closed section', () => {
  it('guided setup: Next opens the closed section and focuses the field', () => {
    toVariants();
    const toggle = screen.getByTestId('variant-configuration-toggle-1');
    fireEvent.click(toggle);
    setValue('variant-configuration-1', '[]');
    fireEvent.click(toggle); // closed, with the problem inside
    expect(screen.queryByTestId('variant-configuration-1')).not.toBeInTheDocument();

    next();

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    const field = screen.getByTestId('variant-configuration-1');
    expect(field).toHaveFocus();
    expect(screen.getByTestId('variant-configuration-error-1')).toHaveTextContent(CONFIGURATION_NOT_OBJECT);
    expect(heading()).toHaveTextContent(STEP_HEADINGS.variants);
  });

  it('the single-page form: Create opens the closed section, focuses the field and sends nothing', async () => {
    routerAt({ advanced: '' });
    api();
    render(<NewExperimentPage />);
    setValue('experiment-name', 'Hero copy');
    const toggle = screen.getByTestId('variant-configuration-toggle-0');
    fireEvent.click(toggle);
    setValue('variant-configuration-0', '{"a": 1,}');
    fireEvent.click(toggle);

    fireEvent.click(screen.getByTestId('submit-experiment'));

    await waitFor(() => expect(screen.getByTestId('variant-configuration-0')).toHaveFocus());
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('form-error')).toHaveTextContent(
      `The configuration of “Control” needs fixing: ${CONFIGURATION_NOT_JSON}`,
    );
    expect(posts()).toHaveLength(0);
  });

  it('opens every section with a problem and focuses the first', () => {
    toVariants();
    for (const i of [0, 1]) {
      const toggle = screen.getByTestId(`variant-configuration-toggle-${i}`);
      fireEvent.click(toggle);
      setValue(`variant-configuration-${i}`, '1');
      fireEvent.click(toggle);
    }
    next();
    expect(screen.getByTestId('variant-configuration-0')).toHaveFocus();
    expect(screen.getByTestId('variant-configuration-1')).toBeInTheDocument();
  });

  it('a section reopened after switching views shows the text it held', () => {
    routerAt({ advanced: '' });
    api();
    const view = render(<NewExperimentPage />);
    fireEvent.click(screen.getByTestId('variant-configuration-toggle-1'));
    setValue('variant-configuration-1', '{"kept": 1}');
    // Switch to guided setup: the form state is the page's, the editor is new.
    routerAt();
    view.rerender(<NewExperimentPage />);
    next();
    setValue('experiment-name', 'Hero copy');
    next();
    expect(screen.getByTestId('variant-configuration-toggle-1')).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('variant-configuration-1')).toHaveValue('{"kept": 1}');
  });
});

describe('Review shows the configuration and Bayesian analysis as text', () => {
  async function toReview(configuration: string, bayesian: boolean) {
    toVariants();
    fireEvent.click(screen.getByTestId('variant-configuration-toggle-1'));
    setValue('variant-configuration-1', configuration);
    next();
    if (bayesian) fireEvent.click(screen.getByTestId('analysis-bayesian'));
    next();
    expect(heading()).toHaveTextContent(STEP_HEADINGS.review);
  }

  it('shows each configuration under its variant and the Bayesian setting in the Analysis row', async () => {
    await toReview('{ "copy": "Buy now" }', true);
    const variants = screen.getByTestId('review-variants');
    expect(within(variants).getByTestId('review-variant-configuration-1')).toHaveTextContent('{"copy":"Buy now"}');
    expect(within(variants).queryByTestId('review-variant-configuration-0')).not.toBeInTheDocument();
    expect(screen.getByTestId('review-analysis')).toHaveTextContent(
      '95% confidence · Benjamini-Hochberg correction · Bayesian analysis on',
    );
  });

  it('says nothing about Bayesian analysis when it is off', async () => {
    await toReview('{}', false);
    expect(screen.getByTestId('review-analysis').textContent).toBe(
      '95% confidence · Benjamini-Hochberg correction',
    );
  });

  it('renders markup in a configuration as text, never as an element', async () => {
    await toReview('{"x": "<img src=x onerror=alert(1)><b>bold</b>"}', false);
    const review = screen.getByTestId('wizard-review');
    expect(review.querySelector('img')).toBeNull();
    expect(review.querySelector('b')).toBeNull();
    expect(screen.getByTestId('review-variant-configuration-1')).toHaveTextContent(
      '{"x":"<img src=x onerror=alert(1)><b>bold</b>"}',
    );
  });
});

describe('the Bayesian checkbox', () => {
  it('is off by default, labelled, and explains itself', () => {
    routerAt({ advanced: '' });
    render(<NewExperimentPage />);
    const box = screen.getByLabelText(BAYESIAN_LABEL);
    expect(box).toBe(screen.getByTestId('analysis-bayesian'));
    expect(box).not.toBeChecked();
    expect(box).toHaveAccessibleDescription(`${BAYESIAN_HELP} How Bayesian analysis works`);
  });

  it('shows in the collapsed Analysis settings summary when on, so nothing hidden changes the results', () => {
    routerAt({ advanced: '' });
    render(<NewExperimentPage />);
    const summary = screen.getByTestId('analysis-settings-summary');
    expect(summary).not.toHaveTextContent(/bayesian/i);
    fireEvent.click(screen.getByTestId('analysis-bayesian'));
    expect(summary).toHaveTextContent(
      'Analysis settings: 95% confidence, Benjamini-Hochberg correction, Bayesian analysis on',
    );
  });
});

describe('who sees the fields', () => {
  it.each(['ANALYST', 'VIEWER'])('%s is told it cannot create, and sees neither field', (role) => {
    mockUser = { role, is_superuser: false };
    routerAt({ advanced: '' });
    render(<NewExperimentPage />);
    expect(screen.getByTestId('create-not-allowed')).toBeInTheDocument();
    expect(screen.queryByTestId('variant-configuration-toggle-0')).not.toBeInTheDocument();
    expect(screen.queryByTestId('analysis-bayesian')).not.toBeInTheDocument();
  });

  it.each(['ADMIN', 'DEVELOPER'])('%s sees both fields', (role) => {
    mockUser = { role, is_superuser: false };
    routerAt({ advanced: '' });
    render(<NewExperimentPage />);
    expect(screen.getByTestId('variant-configuration-toggle-0')).toBeInTheDocument();
    expect(screen.getByTestId('analysis-bayesian')).toBeInTheDocument();
  });
});

describe('a create that fails for a reason other than the API shows fixed words', () => {
  it('an exception thrown in the browser shows the fixed copy, not its own text', async () => {
    routerAt({ advanced: '' });
    mockedApiFetch.mockImplementation(async () => {
      throw new TypeError("Cannot read properties of undefined (reading 'PLANTED-7f3')");
    });
    render(<NewExperimentPage />);
    setValue('experiment-name', 'Hero copy');
    fireEvent.click(screen.getByTestId('submit-experiment'));
    const error = await screen.findByTestId('form-error');
    expect(error).toHaveTextContent(CREATE_FAILED);
    expect(document.body.textContent).not.toContain('PLANTED');
    expect(document.body.textContent).not.toContain('Cannot read');
  });

  it('a 422 refusing a configuration shows the API’s rule', async () => {
    routerAt({ advanced: '' });
    mockedApiFetch.mockImplementation(async () => {
      throw new ApiError({
        status: 422,
        detail: [
          {
            loc: ['body', 'variants', 0, 'configuration'],
            msg: 'Input should be a valid dictionary',
            type: 'dict_type',
          },
        ],
      });
    });
    render(<NewExperimentPage />);
    setValue('experiment-name', 'Hero copy');
    fireEvent.click(screen.getByTestId('submit-experiment'));
    expect(await screen.findByTestId('form-error')).toHaveTextContent(/valid dictionary/);
  });
});

describe('accessibility of the new fields (axe-core in jsdom; colour contrast is not computable here)', () => {
  const axeOptions: axe.RunOptions = { rules: { 'color-contrast': { enabled: false } } };

  async function violations() {
    const container = document.querySelector('body > div');
    if (!container) throw new Error('nothing rendered');
    const result = await axe.run(container, axeOptions);
    return result.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(', ')}`);
  }

  it('the Variants step with a section open and a problem showing has no axe violations', async () => {
    toVariants();
    fireEvent.click(screen.getByTestId('variant-configuration-toggle-0'));
    setValue('variant-configuration-0', '[]');
    fireEvent.click(screen.getByTestId('variant-configuration-toggle-1'));
    setValue('variant-configuration-1', '{"ok": true}');
    expect(await violations()).toEqual([]);
  });

  it('the Estimate step with Bayesian analysis on has no axe violations', async () => {
    toVariants();
    next();
    fireEvent.click(screen.getByTestId('analysis-bayesian'));
    expect(await violations()).toEqual([]);
  });

  it('Review with a configuration has no axe violations', async () => {
    toVariants();
    fireEvent.click(screen.getByTestId('variant-configuration-toggle-1'));
    setValue('variant-configuration-1', '{"copy": "Buy now"}');
    next();
    next();
    expect(await violations()).toEqual([]);
  });
});
