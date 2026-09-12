/**
 * Bounded-concurrency helpers.
 *
 * Fanning a page's per-row requests out with `Promise.all`/`allSettled` issues
 * one request per row at once; a hundred rows is a hundred simultaneous calls
 * and, against the dashboard's 300 req/min budget, a self-inflicted 429. These
 * helpers keep at most `limit` requests in flight while still overlapping them.
 */

/**
 * `Promise.allSettled(items.map(worker))` with at most `limit` workers running
 * at a time. Results keep the order of `items`.
 */
export async function mapWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<PromiseSettledResult<R>[]> {
  const results: PromiseSettledResult<R>[] = new Array(items.length);
  let next = 0;

  const runner = async (): Promise<void> => {
    for (;;) {
      const index = next;
      next += 1;
      if (index >= items.length) return;
      try {
        results[index] = { status: 'fulfilled', value: await worker(items[index], index) };
      } catch (reason) {
        results[index] = { status: 'rejected', reason };
      }
    }
  };

  const workers = Math.max(1, Math.min(Math.floor(limit) || 1, items.length));
  await Promise.all(Array.from({ length: workers }, () => runner()));
  return results;
}
