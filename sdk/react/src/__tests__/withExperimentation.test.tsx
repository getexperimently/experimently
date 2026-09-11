import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ExperimentationProvider } from '../context/ExperimentationProvider';
import { withExperimentation } from '../hoc/withExperimentation';
import { FeatureFlagEvaluation, SdkConfig, UserContext, FeatureFlagEvaluateResponse } from '../client/types';

const config: SdkConfig = {
  apiKey: 'test-key',
  baseUrl: 'https://api.example.com',
};

const defaultUser: UserContext = { userId: 'user-1' };

const enabledFlag: FeatureFlagEvaluateResponse = { key: 'my-flag', enabled: true, config: null };
const disabledFlag: FeatureFlagEvaluateResponse = { key: 'my-flag', enabled: false, config: null };
const variantFlag: FeatureFlagEvaluateResponse = {
  key: 'my-flag',
  enabled: true,
  config: { variant: 'treatment', headline: 'Hello' },
};

function makeFetchMock(body: unknown, status = 200): jest.Mock {
  const mock = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  });
  global.fetch = mock;
  return mock;
}

function renderWithProvider(ui: React.ReactElement) {
  return render(
    <ExperimentationProvider config={config} user={defaultUser}>
      {ui}
    </ExperimentationProvider>
  );
}

afterEach(() => {
  jest.restoreAllMocks();
});

// ─── Test component ───────────────────────────────────────────────────────────

interface OwnProps {
  label: string;
}

interface TestComponentProps extends OwnProps {
  flagEvaluation: FeatureFlagEvaluation | null;
}

function TestComponent({ flagEvaluation, label }: TestComponentProps) {
  const headline = (flagEvaluation?.config as { headline?: string } | null)?.headline;
  return (
    <div>
      <span data-testid="label">{label}</span>
      <span data-testid="loading">{flagEvaluation?.loading ? 'loading' : 'done'}</span>
      <span data-testid="enabled">{flagEvaluation?.isEnabled ? 'enabled' : 'disabled'}</span>
      <span data-testid="variant">{flagEvaluation?.variant ?? 'null'}</span>
      <span data-testid="headline">{headline ?? 'none'}</span>
    </div>
  );
}

const WrappedTestComponent = withExperimentation(TestComponent, 'my-flag');

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('withExperimentation HOC', () => {
  it('wraps the component and passes flagEvaluation prop', () => {
    global.fetch = jest.fn().mockReturnValue(new Promise(() => {})); // never resolves
    renderWithProvider(<WrappedTestComponent label="test" />);
    expect(screen.getByTestId('label')).toHaveTextContent('test');
  });

  it('flagEvaluation reports loading during the initial evaluation', () => {
    global.fetch = jest.fn().mockReturnValue(new Promise(() => {})); // never resolves
    renderWithProvider(<WrappedTestComponent label="loading-test" />);
    expect(screen.getByTestId('loading')).toHaveTextContent('loading');
    expect(screen.getByTestId('enabled')).toHaveTextContent('disabled');
  });

  it('passes through all original props to the wrapped component', async () => {
    makeFetchMock(enabledFlag);
    renderWithProvider(<WrappedTestComponent label="my-custom-label" />);
    expect(screen.getByTestId('label')).toHaveTextContent('my-custom-label');
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('done'));
    expect(screen.getByTestId('label')).toHaveTextContent('my-custom-label');
  });

  it('evaluates the configured flag key for the provider user', async () => {
    const fetchMock = makeFetchMock(enabledFlag);
    renderWithProvider(<WrappedTestComponent label="url" />);
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('done'));
    expect(fetchMock.mock.calls[0][0]).toBe(
      'https://api.example.com/api/v1/feature-flags/evaluate/my-flag?user_id=user-1'
    );
  });

  it('flagEvaluation has variant "on" when the flag is loaded and enabled', async () => {
    makeFetchMock(enabledFlag);
    renderWithProvider(<WrappedTestComponent label="enabled-test" />);
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('done'));
    expect(screen.getByTestId('enabled')).toHaveTextContent('enabled');
    expect(screen.getByTestId('variant')).toHaveTextContent('on');
  });

  it('injects the server config and config.variant', async () => {
    makeFetchMock(variantFlag);
    renderWithProvider(<WrappedTestComponent label="config" />);
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('done'));
    expect(screen.getByTestId('variant')).toHaveTextContent('treatment');
    expect(screen.getByTestId('headline')).toHaveTextContent('Hello');
  });

  it('works correctly with a disabled flag', async () => {
    makeFetchMock(disabledFlag);
    renderWithProvider(<WrappedTestComponent label="disabled" />);
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('done'));
    expect(screen.getByTestId('enabled')).toHaveTextContent('disabled');
    expect(screen.getByTestId('variant')).toHaveTextContent('null');
  });

  it('reports the flag as disabled when evaluation fails', async () => {
    makeFetchMock({}, 500);
    renderWithProvider(<WrappedTestComponent label="error" />);
    await waitFor(() => expect(screen.getByTestId('loading')).toHaveTextContent('done'));
    expect(screen.getByTestId('enabled')).toHaveTextContent('disabled');
    expect(screen.getByTestId('variant')).toHaveTextContent('null');
  });

  it('sets a descriptive displayName', () => {
    expect(WrappedTestComponent.displayName).toBe('withExperimentation(TestComponent)');
  });
});
