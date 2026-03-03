import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { ExperimentationProvider } from '../context/ExperimentationProvider';
import { useMultipleFlags } from '../hooks/useMultipleFlags';
import { SdkConfig, UserContext, FeatureFlag } from '../client/types';

const config: SdkConfig = {
  apiKey: 'test-key',
  baseUrl: 'https://api.example.com',
};

const defaultUser: UserContext = { userId: 'user-1' };

const enabledFlag: FeatureFlag = {
  id: 'f1',
  key: 'flag-a',
  name: 'Flag A',
  enabled: true,
  rolloutPercentage: 100,
};

const disabledFlag: FeatureFlag = {
  id: 'f2',
  key: 'flag-b',
  name: 'Flag B',
  enabled: false,
  rolloutPercentage: 0,
};

const flagWithVariant: FeatureFlag = {
  id: 'f3',
  key: 'flag-c',
  name: 'Flag C',
  enabled: true,
  rolloutPercentage: 100,
  variants: [
    { name: 'treatment', weight: 1.0 },
  ],
};

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
    const { result } = renderHook(() => useMultipleFlags([]), {
      wrapper: makeWrapper(),
    });
    expect(result.current).toEqual({});
  });

  it('returns null for all flags during initial loading', () => {
    global.fetch = jest.fn().mockReturnValue(new Promise(() => {})); // never resolves
    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-b']), {
      wrapper: makeWrapper(),
    });
    expect(result.current['flag-a']).toBeNull();
    expect(result.current['flag-b']).toBeNull();
  });

  it('evaluates all flags and returns populated map when keys are provided', async () => {
    const fetchMock = jest.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(enabledFlag),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(disabledFlag),
      });
    global.fetch = fetchMock;

    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-b']), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current['flag-a']).not.toBeNull();
    });

    expect(result.current['flag-a']).not.toBeNull();
    expect(result.current['flag-b']).not.toBeNull();
  });

  it('returns correct variant per flag', async () => {
    const fetchMock = jest.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(enabledFlag),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(flagWithVariant),
      });
    global.fetch = fetchMock;

    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-c']), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current['flag-a']).not.toBeNull();
    });

    expect(result.current['flag-a']?.variant).toBe('on');
    expect(result.current['flag-c']?.variant).toBe('treatment');
  });

  it('handles mixed enabled and disabled flags correctly', async () => {
    const fetchMock = jest.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(enabledFlag),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(disabledFlag),
      });
    global.fetch = fetchMock;

    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-b']), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current['flag-a']).not.toBeNull();
    });

    expect(result.current['flag-a']?.isEnabled).toBe(true);
    expect(result.current['flag-b']?.isEnabled).toBe(false);
    expect(result.current['flag-b']?.variant).toBeNull();
  });

  it('re-evaluates flags when keys change — picks up new flag', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(enabledFlag),
    });
    global.fetch = fetchMock;

    let keys = ['flag-a'];
    const { result, rerender } = renderHook(() => useMultipleFlags(keys), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current['flag-a']).not.toBeNull();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    keys = ['flag-a', 'flag-b'];
    rerender();

    // flag-a is cached, flag-b needs a fresh fetch — minimum 2 total calls
    await waitFor(() => {
      expect(result.current['flag-b']).not.toBeNull();
    });
    expect(result.current['flag-a']).not.toBeNull();
    expect(result.current['flag-b']).not.toBeNull();
  });

  it('sets loading: false and no error on successful evaluation', async () => {
    const fetchMock = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(enabledFlag),
    });
    global.fetch = fetchMock;

    const { result } = renderHook(() => useMultipleFlags(['flag-a']), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current['flag-a']).not.toBeNull();
    });

    expect(result.current['flag-a']?.loading).toBe(false);
    expect(result.current['flag-a']?.error).toBeNull();
  });

  it('preserves flagKey in each evaluation result', async () => {
    const fetchMock = jest.fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(enabledFlag),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve(disabledFlag),
      });
    global.fetch = fetchMock;

    const { result } = renderHook(() => useMultipleFlags(['flag-a', 'flag-b']), {
      wrapper: makeWrapper(),
    });

    await waitFor(() => {
      expect(result.current['flag-a']).not.toBeNull();
    });

    expect(result.current['flag-a']?.flagKey).toBe('flag-a');
    expect(result.current['flag-b']?.flagKey).toBe('flag-b');
  });
});
