import React from 'react';
import { renderHook, act } from '@testing-library/react';
import { ExperimentationProvider } from '../context/ExperimentationProvider';
import { useTrackEvent } from '../hooks/useTrackEvent';
import { SdkConfig, UserContext } from '../client/types';

const config: SdkConfig = {
  apiKey: 'test-key',
  baseUrl: 'https://api.example.com',
};

const user: UserContext = { userId: 'user-42' };

function makeWrapper(u: UserContext = user) {
  return ({ children }: { children: React.ReactNode }) => (
    <ExperimentationProvider config={config} user={u}>
      {children}
    </ExperimentationProvider>
  );
}

function setupFetchMock(): jest.Mock {
  const mock = jest.fn().mockResolvedValue({ ok: true, status: 200 });
  global.fetch = mock;
  return mock;
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe('useTrackEvent', () => {
  it('returns a callable function', () => {
    setupFetchMock();
    const { result } = renderHook(() => useTrackEvent(), { wrapper: makeWrapper() });
    expect(typeof result.current).toBe('function');
  });

  it('calls client.trackEvent with the correct userId', async () => {
    const fetchMock = setupFetchMock();
    const { result } = renderHook(() => useTrackEvent(), { wrapper: makeWrapper() });

    await act(async () => {
      result.current('button_clicked');
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.user_id).toBe('user-42');
  });

  it('passes the event name to the API', async () => {
    const fetchMock = setupFetchMock();
    const { result } = renderHook(() => useTrackEvent(), { wrapper: makeWrapper() });

    await act(async () => {
      result.current('purchase_completed');
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.event_name).toBe('purchase_completed');
  });

  it('passes properties to the API', async () => {
    const fetchMock = setupFetchMock();
    const { result } = renderHook(() => useTrackEvent(), { wrapper: makeWrapper() });

    await act(async () => {
      result.current('add_to_cart', { product_id: 'sku-123', quantity: 2 });
    });

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.properties).toEqual({ product_id: 'sku-123', quantity: 2 });
  });

  it('returns a stable callback reference across re-renders (same user)', () => {
    setupFetchMock();
    const { result, rerender } = renderHook(() => useTrackEvent(), { wrapper: makeWrapper() });

    const first = result.current;
    rerender();
    const second = result.current;

    expect(first).toBe(second);
  });

  it('returns a new callback when userId changes', () => {
    setupFetchMock();

    let currentUser = user;
    const DynamicWrapper = ({ children }: { children: React.ReactNode }) => (
      <ExperimentationProvider config={config} user={currentUser}>
        {children}
      </ExperimentationProvider>
    );

    const { result, rerender } = renderHook(() => useTrackEvent(), { wrapper: DynamicWrapper });
    const firstCallback = result.current;

    currentUser = { userId: 'user-99' };
    rerender();
    const secondCallback = result.current;

    expect(secondCallback).not.toBe(firstCallback);
  });

  it('does not throw when network fails (fire-and-forget)', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('Network error'));
    const { result } = renderHook(() => useTrackEvent(), { wrapper: makeWrapper() });

    await act(async () => {
      // Should not throw
      result.current('click');
    });
  });
});
