import { renderHook, act, waitFor } from '@testing-library/react';
import { useApi } from '@/hooks/useApi';

describe('useApi', () => {
  it('fetches data on mount by default', async () => {
    const fetcher = jest.fn().mockResolvedValue({ id: 1 });
    const { result } = renderHook(() => useApi(fetcher));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual({ id: 1 });
    expect(result.current.error).toBeNull();
  });

  it('does not fetch when immediate is false', async () => {
    const fetcher = jest.fn().mockResolvedValue('ok');
    const { result } = renderHook(() => useApi(fetcher, [], { immediate: false }));

    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('sets error on rejection', async () => {
    const fetcher = jest.fn().mockRejectedValue(new Error('Network fail'));
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('Network fail');
    expect(result.current.data).toBeNull();
  });

  it('handles non-Error rejection', async () => {
    const fetcher = jest.fn().mockRejectedValue('string error');
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('string error');
  });

  it('refetch re-triggers the fetcher', async () => {
    let counter = 0;
    const fetcher = jest.fn().mockImplementation(() => Promise.resolve(++counter));
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.data).toBe(1));
    await act(async () => { result.current.refetch(); });
    await waitFor(() => expect(result.current.data).toBe(2));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('setData updates data manually', async () => {
    const fetcher = jest.fn().mockResolvedValue('original');
    const { result } = renderHook(() => useApi<string>(fetcher));

    await waitFor(() => expect(result.current.data).toBe('original'));
    act(() => { result.current.setData('manual'); });
    expect(result.current.data).toBe('manual');
  });

  it('re-fetches when deps change', async () => {
    const fetcher = jest.fn().mockImplementation((x: number) => Promise.resolve(x));
    let dep = 1;
    const { result, rerender } = renderHook(() =>
      useApi(() => fetcher(dep), [dep]),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetcher).toHaveBeenCalledWith(1);

    dep = 2;
    rerender();
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(2));
  });

  it('clears error on refetch', async () => {
    const fetcher = jest.fn()
      .mockRejectedValueOnce(new Error('fail'))
      .mockResolvedValueOnce('ok');
    const { result } = renderHook(() => useApi(fetcher));

    await waitFor(() => expect(result.current.error).toBe('fail'));
    await act(async () => { result.current.refetch(); });
    await waitFor(() => expect(result.current.error).toBeNull());
    expect(result.current.data).toBe('ok');
  });

  it('loading is true during fetch', async () => {
    let resolvePromise: (v: string) => void;
    const fetcher = jest.fn().mockImplementation(
      () => new Promise<string>((resolve) => { resolvePromise = resolve; }),
    );
    const { result } = renderHook(() => useApi(fetcher));

    expect(result.current.loading).toBe(true);
    await act(async () => { resolvePromise!('done'); });
    expect(result.current.loading).toBe(false);
  });
});
