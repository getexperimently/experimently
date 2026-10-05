/**
 * Sending an id file to a segment chunk by chunk (#440).
 *
 * One request per chunk, in order. The first failure stops the run, and a
 * retry starts again from the chunk that failed: adding or removing the same
 * ids twice is safe, so nothing is lost by resending it. A 429 is not a
 * failure: the run waits as long as the API's `Retry-After` asks and sends
 * the same chunk again.
 */
import { isApiError } from '@/services/api';

/** How long to wait on a 429 that carries no `Retry-After`, in seconds. */
export const DEFAULT_RETRY_AFTER_SECONDS = 20;

/** The longest wait honoured, in seconds. */
export const MAX_RETRY_AFTER_SECONDS = 120;

/** After this many 429s in a row on one chunk the run stops as failed. */
export const MAX_WAITS_PER_CHUNK = 5;

export type RunOutcome = 'done' | 'stopped' | 'failed';

export interface RunResult {
  outcome: RunOutcome;
  /** The index of the next chunk to send: the failed one, or `chunks.length` when done. */
  next: number;
  /** What the failed request threw. */
  error?: unknown;
}

export interface RunOptions<T> {
  chunks: string[][];
  /** The first chunk to send (0, or the failed chunk on a retry). */
  startAt: number;
  send: (ids: string[]) => Promise<T>;
  /** Called after each chunk the API accepted. */
  onChunkDone: (index: number, result: T) => void;
  /** Checked before each chunk: true stops the run after the current one. */
  shouldStop: () => boolean;
  /** Wait `seconds` (a 429). A parameter, so tests do not sleep. */
  wait: (seconds: number) => Promise<void>;
  /** Called before a wait, with its length, so the page can say so. */
  onWait?: (seconds: number) => void;
}

/** Seconds to wait for a 429: its `Retry-After`, or the default, capped. */
export function retryDelay(err: unknown): number {
  const asked = isApiError(err) && typeof err.retryAfter === 'number' ? err.retryAfter : DEFAULT_RETRY_AFTER_SECONDS;
  return Math.min(Math.max(asked, 1), MAX_RETRY_AFTER_SECONDS);
}

export async function runChunks<T>(options: RunOptions<T>): Promise<RunResult> {
  const { chunks, startAt, send, onChunkDone, shouldStop, wait, onWait } = options;
  for (let index = startAt; index < chunks.length; index += 1) {
    if (index > startAt && shouldStop()) return { outcome: 'stopped', next: index };
    let waits = 0;
    for (;;) {
      try {
        const result = await send(chunks[index]);
        onChunkDone(index, result);
        break;
      } catch (err) {
        if (isApiError(err) && err.status === 429 && waits < MAX_WAITS_PER_CHUNK) {
          waits += 1;
          const seconds = retryDelay(err);
          onWait?.(seconds);
          await wait(seconds);
          continue;
        }
        return { outcome: 'failed', next: index, error: err };
      }
    }
  }
  return { outcome: 'done', next: chunks.length };
}
