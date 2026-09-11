import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { ExperimentationProvider } from '../context/ExperimentationProvider';
import { useMultipleFlags } from '../hooks/useMultipleFlags';
import { SdkConfig, UserContext, FeatureFlagEvaluateResponse } from '../client/types';

const config: SdkConfig = {
  apiKey: 'test-key',
  baseUrl: 'https://api.example.com',
};

const defaultUser: UserContext = { userId: 'user-1' };

const enabledFlag: FeatureFlagEvaluateResponse = { key: 'flag-a', enabled: true, config: null };
const disabledFlag: FeatureFlagEvaluateResponse = { key: 'flag-b', enabled: false, config: null };
const variantFlag: FeatureFlagEvaluateResponse = {
  key: 'flag-c',
  enabled: true,
  config: { variant: 'treatment' },
};

function jsonResponse(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function mockFetchSequence(...steps: Array<{ body: unknown; status?: number } | Error>): jest.Mock {
  const mock = jest.fn();
  for (const step of steps) {
    if (step instanceof Error) mock.mockRejectedValueOnce(step);
    else mock.mockResolvedValueOnce(jsonResponse(step.body, step.status ?? 200));
  }
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

describe('useMultipleFlags', () => {
  it('returns empty object for empty keys array', () => {
    const fetchMock = jest.fn();
    global.fetch = fetchMock;
    const { result } = renderHook(() => useMultipleFlags([]), { wrapper: makeWrapper() });
    expect(result.current).toEqual({});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('returns null for all flags during initial loading', () => {
    global.fetch = jest.fn().mockReturnValue(new Promise(() => {})); // never resolves
    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-b']), {
      wrapper: makeWrapper(),
    });
    expect(result.current['flag-a']).toBeNull();
    expect(result.current['flag-b']).toBeNull();
  });

  it('requests each flag from the evaluate endpoint with the user id', async () => {
    const fetchMock = mockFetchSequence({ body: enabledFlag }, { body: disabledFlag });
    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-b']), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current['flag-b']).not.toBeNull());

    expect(fetchMock.mock.calls.map(c => c[0])).toEqual([
      'https://api.example.com/api/v1/feature-flags/evaluate/flag-a?user_id=user-1',
      'https://api.example.com/api/v1/feature-flags/evaluate/flag-b?user_id=user-1',
    ]);
  });

  it('evaluates all flags and returns populated map when keys are provided', async () => {
    mockFetchSequence({ body: enabledFlag }, { body: disabledFlag });
    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-b']), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current['flag-a']).not.toBeNull());
    expect(result.current['flag-a']).not.toBeNull();
    expect(result.current['flag-b']).not.toBeNull();
  });

  it('returns correct variant and config per flag', async () => {
    mockFetchSequence({ body: enabledFlag }, { body: variantFlag });
    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-c']), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current['flag-a']).not.toBeNull());
    expect(result.current['flag-a']?.variant).toBe('on');
    expect(result.current['flag-a']?.config).toBeNull();
    expect(result.current['flag-c']?.variant).toBe('treatment');
    expect(result.current['flag-c']?.config).toEqual({ variant: 'treatment' });
  });

  it('handles mixed enabled and disabled flags correctly', async () => {
    mockFetchSequence({ body: enabledFlag }, { body: disabledFlag });
    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-b']), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current['flag-a']).not.toBeNull());
    expect(result.current['flag-a']?.isEnabled).toBe(true);
    expect(result.current['flag-b']?.isEnabled).toBe(false);
    expect(result.current['flag-b']?.variant).toBeNull();
  });

  it('returns an error evaluation for flags that fail without affecting the others', async () => {
    mockFetchSequence({ body: enabledFlag }, new Error('Network down'));
    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-b']), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current['flag-b']).not.toBeNull());
    expect(result.current['flag-a']?.isEnabled).toBe(true);
    expect(result.current['flag-b']).toMatchObject({
      flagKey: 'flag-b',
      variant: null,
      isEnabled: false,
      config: null,
      loading: false,
    });
    expect(result.current['flag-b']?.error?.message).toBe('Network down');
  });

  it('re-evaluates flags when keys change — picks up new flag', async () => {
    const fetchMock = jest.fn().mockResolvedValue(jsonResponse(enabledFlag));
    global.fetch = fetchMock;

    let keys = ['flag-a'];
    const { result, rerender } = renderHook(() => useMultipleFlags(keys), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current['flag-a']).not.toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(1);

    keys = ['flag-a', 'flag-b'];
    rerender();

    await waitFor(() => expect(result.current['flag-b']).not.toBeNull());
    expect(result.current['flag-a']).not.toBeNull();
    // flag-a was served from cache; only flag-b needed a new request
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain('/evaluate/flag-b?');
  });

  it('sets loading: false and no error on successful evaluation', async () => {
    global.fetch = jest.fn().mockResolvedValue(jsonResponse(enabledFlag));
    const { result } = renderHook(() => useMultipleFlags(['flag-a']), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current['flag-a']).not.toBeNull());
    expect(result.current['flag-a']?.loading).toBe(false);
    expect(result.current['flag-a']?.error).toBeNull();
  });

  it('preserves flagKey in each evaluation result', async () => {
    mockFetchSequence({ body: enabledFlag }, { body: disabledFlag });
    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-b']), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => expect(result.current['flag-a']).not.toBeNull());
    expect(result.current['flag-a']?.flagKey).toBe('flag-a');
    expect(result.current['flag-b']?.flagKey).toBe('flag-b');
  });
});
