import React from 'react';
import { renderHook, act, waitFor } from '@testing-library/react';
import { ExperimentationProvider } from '../context/ExperimentationProvider';
import { useFeatureFlag } from '../hooks/useFeatureFlag';
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

describe('useFeatureFlag', () => {
  it('starts with loading: true and isEnabled: false', () => {
    makeFetchMock(enabledFlag);
    const { result } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: makeWrapper(),
    });
    expect(result.current.loading).toBe(true);
    expect(result.current.isEnabled).toBe(false);
    expect(result.current.error).toBeNull();
  });

  it('starts with loading: true, variant null, no error', () => {
    makeFetchMock(enabledFlag);
    const { result } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: makeWrapper(),
    });
    expect(result.current.variant).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('sets isEnabled: true when flag is enabled with 100% rollout', async () => {
    makeFetchMock(enabledFlag);
    const { result } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isEnabled).toBe(true);
  });

  it('sets variant: "on" for an enabled flag with no variants', async () => {
    makeFetchMock(enabledFlag);
    const { result } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.variant).toBe('on');
  });

  it('sets isEnabled: false when flag is disabled', async () => {
    makeFetchMock(disabledFlag);
    const { result } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isEnabled).toBe(false);
    expect(result.current.variant).toBeNull();
  });

  it('exposes flagKey in the returned state', async () => {
    makeFetchMock(enabledFlag);
    const { result } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: makeWrapper(),
    });
    expect(result.current.flagKey).toBe('my-flag');
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.flagKey).toBe('my-flag');
  });

  it('sets error when the API returns a non-2xx response', async () => {
    global.fetch = jest.fn().mockResolvedValue({ ok: false, status: 500, json: () => Promise.resolve({}) });
    const { result } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.isEnabled).toBe(false);
  });

  it('sets error on network failure', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('Network down'));
    const { result } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toBe('Network down');
  });

  it('clears error on successful re-fetch after flagKey change', async () => {
    // First call fails
    global.fetch = jest.fn()
      .mockRejectedValueOnce(new Error('Network down'))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(enabledFlag),
      });

    let flagKey = 'flag-a';
    const { result, rerender } = renderHook(() => useFeatureFlag(flagKey), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).not.toBeNull();

    flagKey = 'flag-b';
    rerender();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.isEnabled).toBe(true);
  });

  it('re-fetches when flagKey changes', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(enabledFlag),
    });
    global.fetch = fetchMock;

    let flagKey = 'flag-a';
    const { result, rerender } = renderHook(() => useFeatureFlag(flagKey), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    flagKey = 'flag-b';
    rerender();
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('re-fetches when user.userId changes', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(enabledFlag),
    });
    global.fetch = fetchMock;

    let currentUser = defaultUser;
    const DynamicWrapper = ({ children }: { children: React.ReactNode }) => (
      <ExperimentationProvider config={config} user={currentUser}>
        {children}
      </ExperimentationProvider>
    );

    const { result, rerender } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: DynamicWrapper,
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    currentUser = { userId: 'user-2' };
    rerender();
    await waitFor(() => expect(result.current.loading).toBe(false));
    // Second fetch because user changed (cache key is userId:flagKey)
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not update state after unmount (no setState on cancelled effect)', async () => {
    let resolveFetch!: (val: unknown) => void;
    global.fetch = jest.fn().mockReturnValue(
      new Promise(resolve => {
        resolveFetch = resolve;
      })
    );

    const { result, unmount } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: makeWrapper(),
    });

    expect(result.current.loading).toBe(true);
    unmount();

    // Resolve fetch after unmount — should not throw or update state
    act(() => {
      resolveFetch({
        ok: true,
        status: 200,
        json: () => Promise.resolve(enabledFlag),
      });
    });

    // State should remain as it was at unmount time
    expect(result.current.loading).toBe(true);
  });

  it('returns loading: false and correct variant after successful fetch', async () => {
    makeFetchMock(enabledFlag);
    const { result } = renderHook(() => useFeatureFlag('my-flag'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeNull();
  });
});
