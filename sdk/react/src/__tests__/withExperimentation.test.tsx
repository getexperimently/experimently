import '@testing-library/jest-dom';
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ExperimentationProvider } from '../context/ExperimentationProvider';
import { withExperimentation } from '../hoc/withExperimentation';
import { FeatureFlagEvaluation, SdkConfig, UserContext, FeatureFlag } from '../client/types';

const config: SdkConfig = {
  apiKey: 'test-key',
  baseUrl: 'https://api.example.com',
};

const defaultUser: UserContext = { userId: 'user-1' };

const enabledFlag: FeatureFlag = {
  id: 'f1',
  key: 'my-flag',
  name: 'My Flag',
  enabled: true,
  rolloutPercentage: 100,
};

const disabledFlag: FeatureFlag = {
  id: 'f2',
  key: 'my-flag',
  name: 'My Flag',
  enabled: false,
  rolloutPercentage: 0,
};

function makeFetchMock(flag: FeatureFlag, status = 200): jest.Mock {
  const mock = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(flag),
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

// OwnProps are the props the consumer passes (excluding the injected flagEvaluation)
interface OwnProps {
  label: string;
}

// Full props including the injected prop from the HOC
interface TestComponentProps extends OwnProps {
  flagEvaluation: FeatureFlagEvaluation | null;
}

function TestComponent({ flagEvaluation, label }: TestComponentProps) {
  return (
    <div>
      <span data-testid="label">{label}</span>
      <span data-testid="loading">{flagEvaluation?.loading ? 'loading' : 'done'}</span>
      <span data-testid="enabled">{flagEvaluation?.isEnabled ? 'enabled' : 'disabled'}</span>
      <span data-testid="variant">{flagEvaluation?.variant ?? 'null'}</span>
    </div>
  );
}

// The HOC strips flagEvaluation from the outward-facing props
const WrappedTestComponent = withExperimentation(TestComponent, 'my-flag');

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('withExperimentation HOC', () => {
  it('wraps the component and passes flagEvaluation prop', () => {
    global.fetch = jest.fn().mockReturnValue(new Promise(() => {})); // never resolves
    renderWithProvider(<WrappedTestComponent label="test" />);
    expect(screen.getByTestId('label')).toHaveTextContent('test');
  });

  it('flagEvaluation is null during initial loading phase', () => {
    global.fetch = jest.fn().mockReturnValue(new Promise(() => {})); // never resolves
    renderWithProvider(<WrappedTestComponent label="loading-test" />);
    // During loading, flagEvaluation.loading should be true
    expect(screen.getByTestId('loading')).toHaveTextContent('loading');
  });

  it('passes through all original props to the wrapped component', () => {
    makeFetchMock(enabledFlag);
    renderWithProvider(<WrappedTestComponent label="my-custom-label" />);
    expect(screen.getByTestId('label')).toHaveTextContent('my-custom-label');
  });

  it('flagEvaluation has variant when flag is loaded and enabled', async () => {
    makeFetchMock(enabledFlag);
    renderWithProvider(<WrappedTestComponent label="enabled-test" />);
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('done');
    });
    expect(screen.getByTestId('enabled')).toHaveTextContent('enabled');
    expect(screen.getByTestId('variant')).toHaveTextContent('on');
  });

  it('works correctly with an enabled flag', async () => {
    makeFetchMock(enabledFlag);
    renderWithProvider(<WrappedTestComponent label="enabled" />);
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('done');
    });
    expect(screen.getByTestId('enabled')).toHaveTextContent('enabled');
  });

  it('works correctly with a disabled flag', async () => {
    makeFetchMock(disabledFlag);
    renderWithProvider(<WrappedTestComponent label="disabled" />);
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('done');
    });
    expect(screen.getByTestId('enabled')).toHaveTextContent('disabled');
    expect(screen.getByTestId('variant')).toHaveTextContent('null');
  });
});
