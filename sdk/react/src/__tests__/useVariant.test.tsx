import React from 'react';
import { renderHook, act, waitFor } from '@testing-library/react';
import { ExperimentationProvider } from '../context/ExperimentationProvider';
import { useVariant } from '../hooks/useVariant';
import { SdkConfig, UserContext, FeatureFlagEvaluateResponse } from '../client/types';

const config: SdkConfig = {
  apiKey: 'test-key',
  baseUrl: 'https://api.example.com',
};

const defaultUser: UserContext = { userId: 'user-1' };

const enabledFlag: FeatureFlagEvaluateResponse = { key: 'my-flag', enabled: true, config: null };
const enabledFlagWithVariant: FeatureFlagEvaluateResponse = {
  key: 'variant-flag',
  enabled: true,
  config: { variant: 'treatment' },
};
const enabledFlagWithConfig: FeatureFlagEvaluateResponse = {
  key: 'config-flag',
  enabled: true,
  config: { engine: 'v2' },
};
const disabledFlag: FeatureFlagEvaluateResponse = { key: 'disabled-flag', enabled: false, config: null };

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function makeFetchMock(body: unknown, status = 200): jest.Mock {
  const mock = jest.fn().mockResolvedValue(jsonResponse(body, status));
  global.fetch = mock;
  return mock;
}

function makeWrapper(user: UserContext = defaultUser) {
  return ({ children }: { children: React.ReactNode }) => (
    <ExperimentationProvider config={config} user={user}>
      {children}
    </ExperimentationProvider>
  );
}

/** Let a resolved fetch chain settle inside act() so no state update lands outside it. */
const flush = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });

afterEach(() => {
  jest.restoreAllMocks();
});

describe('useVariant', () => {
  it('returns null during initial loading', () => {
    global.fetch = jest.fn().mockReturnValue(new Promise(() => {})); // never resolves
    const { result } = renderHook(() => useVariant('my-flag'), { wrapper: makeWrapper() });
    expect(result.current).toBeNull();
  });

  it('returns "on" when the flag is enabled without a config variant', async () => {
    makeFetchMock(enabledFlag);
    const { result } = renderHook(() => useVariant('my-flag'), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(result.current).toBe('on');
  });

  it('returns config.variant when the server config names one', async () => {
    makeFetchMock(enabledFlagWithVariant);
    const { result } = renderHook(() => useVariant('variant-flag'), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(result.current).toBe('treatment');
  });

  it('returns "on" when the config has no variant field', async () => {
    makeFetchMock(enabledFlagWithConfig);
    const { result } = renderHook(() => useVariant('config-flag'), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(result.current).toBe('on');
  });

  it('returns null when flag is disabled', async () => {
    makeFetchMock(disabledFlag);
    const { result } = renderHook(() => useVariant('disabled-flag'), { wrapper: makeWrapper() });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    await flush();
    expect(result.current).toBeNull();
  });

  it('re-fetches when flagKey changes', async () => {
    const fetchMock = jest
      .fn()
      .mockResolvedValueOnce(jsonResponse(enabledFlag))
      .mockResolvedValueOnce(jsonResponse(enabledFlagWithVariant));
    global.fetch = fetchMock;

    let flagKey = 'flag-a';
    const { result, rerender } = renderHook(() => useVariant(flagKey), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current).not.toBeNull());
    expect(result.current).toBe('on');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    flagKey = 'flag-b';
    rerender();
    await waitFor(() => expect(result.current).toBe('treatment'));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('returns null on API error', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('Network error'));
    const { result } = renderHook(() => useVariant('my-flag'), { wrapper: makeWrapper() });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    await flush();
    expect(result.current).toBeNull();
  });
});
