/**
 * Sending chunks: stop at the first failure, resume from it, wait out a 429
 * (#440 PR D; gates-D D4, D5).
 */
import { ApiError } from '@/services/api';
import { DEFAULT_RETRY_AFTER_SECONDS, MAX_WAITS_PER_CHUNK, retryDelay, runChunks } from '@/utils/segmentUpload';

const chunks = [['a', 'b'], ['c'], ['d', 'e']];

function harness(fail: (call: number, ids: string[]) => unknown | null) {
  const sent: string[][] = [];
  const done: number[] = [];
  const waits: number[] = [];
  let call = 0;
  const send = jest.fn(async (ids: string[]) => {
    call += 1;
    sent.push(ids);
    const err = fail(call, ids);
    if (err) throw err;
    return { added: ids.length, already_members: 0, member_count: sent.flat().length };
  });
  return {
    sent,
    done,
    waits,
    run: (startAt = 0) =>
      runChunks({
        chunks,
        startAt,
        send,
        onChunkDone: (index) => done.push(index),
        shouldStop: () => false,
        wait: async (seconds) => {
          waits.push(seconds);
        },
      }),
  };
}

describe('runChunks (D4)', () => {
  it('sends every chunk in order', async () => {
    const h = harness(() => null);
    await expect(h.run()).resolves.toEqual({ outcome: 'done', next: 3 });
    expect(h.sent).toEqual(chunks);
    expect(h.done).toEqual([0, 1, 2]);
  });

  it('stops at the first failure and sends nothing after it', async () => {
    const boom = new ApiError({ status: 500, detail: 'x' });
    const h = harness((call) => (call === 2 ? boom : null));
    const result = await h.run();
    expect(result).toEqual({ outcome: 'failed', next: 1, error: boom });
    expect(h.sent).toEqual([['a', 'b'], ['c']]);
    expect(h.done).toEqual([0]);
  });

  it('a retry from the failed chunk sends that chunk and the rest only', async () => {
    const h = harness(() => null);
    await expect(h.run(1)).resolves.toEqual({ outcome: 'done', next: 3 });
    expect(h.sent).toEqual([['c'], ['d', 'e']]);
  });

  it('stops between chunks when asked', async () => {
    let stop = false;
    const sent: string[][] = [];
    const result = await runChunks({
      chunks,
      startAt: 0,
      send: async (ids) => {
        sent.push(ids);
        stop = true;
        return {};
      },
      onChunkDone: () => undefined,
      shouldStop: () => stop,
      wait: async () => undefined,
    });
    expect(result).toEqual({ outcome: 'stopped', next: 1 });
    expect(sent).toEqual([['a', 'b']]);
  });
});

describe('runChunks on 429 (D5)', () => {
  it('waits Retry-After seconds and resends the same chunk', async () => {
    const limited = new ApiError({ status: 429, detail: 'slow down', retryAfter: 1 });
    const h = harness((call) => (call === 2 ? limited : null));
    await expect(h.run()).resolves.toEqual({ outcome: 'done', next: 3 });
    expect(h.waits).toEqual([1]);
    expect(h.sent).toEqual([['a', 'b'], ['c'], ['c'], ['d', 'e']]);
  });

  it('gives up as failed after five waits in a row on one chunk', async () => {
    const limited = new ApiError({ status: 429, detail: 'slow down' });
    const h = harness((call) => (call >= 2 ? limited : null));
    const result = await h.run();
    expect(result.outcome).toBe('failed');
    expect(result.next).toBe(1);
    expect(h.waits).toHaveLength(MAX_WAITS_PER_CHUNK);
  });

  it('waits the default without a Retry-After, and caps a long one', () => {
    expect(retryDelay(new ApiError({ status: 429 }))).toBe(DEFAULT_RETRY_AFTER_SECONDS);
    expect(retryDelay(new ApiError({ status: 429, retryAfter: 9999 }))).toBe(120);
    expect(retryDelay(new ApiError({ status: 429, retryAfter: 0 }))).toBe(1);
  });
});
