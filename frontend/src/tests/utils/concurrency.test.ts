import { mapWithConcurrency } from '@/utils/concurrency';

/** Worker that records how many calls overlap. */
function trackingWorker<T, R>(fn: (item: T, index: number) => R | Promise<R>) {
  const state = { inFlight: 0, peak: 0, calls: 0 };
  const worker = async (item: T, index: number): Promise<R> => {
    state.calls += 1;
    state.inFlight += 1;
    state.peak = Math.max(state.peak, state.inFlight);
    try {
      await new Promise((resolve) => setTimeout(resolve, 0));
      return await fn(item, index);
    } finally {
      state.inFlight -= 1;
    }
  };
  return { state, worker };
}

describe('mapWithConcurrency', () => {
  it('never runs more than `limit` workers at once but still overlaps them', async () => {
    const items = Array.from({ length: 20 }, (_, i) => i);
    const { state, worker } = trackingWorker<number, number>((n) => n * 2);

    const results = await mapWithConcurrency(items, 4, worker);

    expect(state.calls).toBe(20);
    expect(state.peak).toBeLessThanOrEqual(4);
    expect(state.peak).toBeGreaterThan(1);
    expect(results.map((r) => (r.status === 'fulfilled' ? r.value : null))).toEqual(
      items.map((n) => n * 2),
    );
  });

  it('settles rejections in place instead of failing the whole batch', async () => {
    const results = await mapWithConcurrency([1, 2, 3], 2, async (n) => {
      if (n === 2) throw new Error('nope');
      return n;
    });

    expect(results.map((r) => r.status)).toEqual(['fulfilled', 'rejected', 'fulfilled']);
    expect((results[1] as PromiseRejectedResult).reason).toEqual(new Error('nope'));
  });

  it('handles an empty list and a nonsensical limit', async () => {
    expect(await mapWithConcurrency([], 5, async (n) => n)).toEqual([]);
    const { state, worker } = trackingWorker<number, number>((n) => n);
    const results = await mapWithConcurrency([1, 2], 0, worker);
    expect(state.peak).toBe(1);
    expect(results).toHaveLength(2);
  });
});
