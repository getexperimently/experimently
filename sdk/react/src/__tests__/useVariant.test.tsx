import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { ExperimentationProvider } from '../context/ExperimentationProvider';
import { useVariant } from '../hooks/useVariant';
import { SdkConfig, UserContext, FeatureFlag } from '../client/types';

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

const enabledFlagWithVariant: FeatureFlag = {
  id: 'f3',
  key: 'variant-flag',
  name: 'Variant Flag',
  enabled: true,
  rolloutPercentage: 100,
  variants: [
    { name: 'treatment', weight: 1.0 },
  ],
};

const disabledFlag: FeatureFlag = {
  id: 'f2',
  key: 'disabled-flag',
  name: 'Disabled Flag',
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

function makeWrapper(user: UserContext = defaultUser) {
  return ({ children }: { children: React.ReactNode }) => (
    <ExperimentationProvider config={config} user={user}>
      {children}
    </ExperimentationProvider>
  );
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe('useVariant', () => {
  it('returns null during initial loading', () => {
    makeFetchMock(enabledFlag);
    const { result } = renderHook(() => useVariant('my-flag'), {
      wrapper: makeWrapper(),
    });
    expect(result.current).toBeNull();
  });

  it('returns variant string when flag is enabled', async () => {
    makeFetchMock(enabledFlag);
    const { result } = renderHook(() => useVariant('my-flag'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(typeof result.current).toBe('string');
    expect(result.current).toBe('on');
  });

  it('returns specific variant name when flag has variants', async () => {
    makeFetchMock(enabledFlagWithVariant);
    const { result } = renderHook(() => useVariant('variant-flag'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current).not.toBeNull());
    expect(result.current).toBe('treatment');
  });

  it('returns null when flag is disabled', async () => {
    makeFetchMock(disabledFlag);
    const { result } = renderHook(() => useVariant('disabled-flag'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => {
      // loading finishes (fetch resolves) — variant remains null
      expect(global.fetch).toHaveBeenCalledTimes(1);
    });
    // disabled flag => variant stays null
    expect(result.current).toBeNull();
  });

  it('re-fetches when flagKey changes', async () => {
    const fetchMock = jest.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(enabledFlag),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(enabledFlag),
      });
    global.fetch = fetchMock;

    let flagKey = 'flag-a';
    const { result, rerender } = renderHook(() => useVariant(flagKey), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current).not.toBeNull());
    expect(result.current).toBe('on');
    expect(fetchMock).toHaveBeenCalledTimes(1);

    flagKey = 'flag-b';
    rerender();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    // flag-b was fetched — variant is also 'on' (enabledFlag used again)
    expect(result.current).toBe('on');
  });

  it('returns null on API error', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('Network error'));
    const { result } = renderHook(() => useVariant('my-flag'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1));
    expect(result.current).toBeNull();
  });
});
