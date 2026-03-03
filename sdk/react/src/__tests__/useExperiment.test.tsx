import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { ExperimentationProvider } from '../context/ExperimentationProvider';
import { useExperiment } from '../hooks/useExperiment';
import { SdkConfig, UserContext, FeatureFlag } from '../client/types';

const config: SdkConfig = {
  apiKey: 'test-key',
  baseUrl: 'https://api.example.com',
};

const user: UserContext = { userId: 'user-1' };

const treatmentFlag: FeatureFlag = {
  id: 'exp-1',
  key: 'checkout-experiment',
  name: 'Checkout Experiment',
  enabled: true,
  rolloutPercentage: 100,
  variants: [
    { name: 'control', weight: 0.5 },
    { name: 'treatment', weight: 0.5 },
  ],
};

const disabledFlag: FeatureFlag = {
  id: 'exp-2',
  key: 'checkout-experiment',
  name: 'Checkout Experiment',
  enabled: false,
  rolloutPercentage: 0,
};

function makeWrapper() {
  return ({ children }: { children: React.ReactNode }) => (
    <ExperimentationProvider config={config} user={user}>
      {children}
    </ExperimentationProvider>
  );
}

function makeFetchMock(flag: FeatureFlag, status = 200): jest.Mock {
  const mock = jest.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(flag),
  });
  global.fetch = mock;
  return mock;
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe('useExperiment', () => {
  it('starts with loading: true', () => {
    makeFetchMock(treatmentFlag);
    const { result } = renderHook(() => useExperiment('checkout-experiment'), {
      wrapper: makeWrapper(),
    });
    expect(result.current.loading).toBe(true);
  });

  it('starts with variantKey: "control" and no error', () => {
    makeFetchMock(treatmentFlag);
    const { result } = renderHook(() => useExperiment('checkout-experiment'), {
      wrapper: makeWrapper(),
    });
    expect(result.current.variantKey).toBe('control');
    expect(result.current.error).toBeNull();
  });

  it('exposes experimentKey in the returned state', async () => {
    makeFetchMock(treatmentFlag);
    const { result } = renderHook(() => useExperiment('checkout-experiment'), {
      wrapper: makeWrapper(),
    });
    expect(result.current.experimentKey).toBe('checkout-experiment');
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.experimentKey).toBe('checkout-experiment');
  });

  it('resolves to a variant from the flag when enabled', async () => {
    makeFetchMock(treatmentFlag);
    const { result } = renderHook(() => useExperiment('checkout-experiment'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(['control', 'treatment']).toContain(result.current.variantKey);
    expect(result.current.error).toBeNull();
  });

  it('capitalises variantName from variantKey', async () => {
    makeFetchMock(treatmentFlag);
    const { result } = renderHook(() => useExperiment('checkout-experiment'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    const { variantKey, variantName } = result.current;
    expect(variantName).toBe(variantKey.charAt(0).toUpperCase() + variantKey.slice(1));
  });

  it('falls back to variantKey: "control" when the flag is disabled', async () => {
    makeFetchMock(disabledFlag);
    const { result } = renderHook(() => useExperiment('checkout-experiment'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.variantKey).toBe('control');
  });

  it('sets error and keeps variantKey: "control" on API failure', async () => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 503,
      json: () => Promise.resolve({}),
    });
    const { result } = renderHook(() => useExperiment('checkout-experiment'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.variantKey).toBe('control');
  });

  it('sets loading: false after resolution', async () => {
    makeFetchMock(treatmentFlag);
    const { result } = renderHook(() => useExperiment('checkout-experiment'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.loading).toBe(false);
  });

  it('re-fetches when experimentKey changes', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(treatmentFlag),
    });
    global.fetch = fetchMock;

    let expKey = 'exp-a';
    const { result, rerender } = renderHook(() => useExperiment(expKey), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    expKey = 'exp-b';
    rerender();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
