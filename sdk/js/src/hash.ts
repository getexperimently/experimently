import { md5Bytes } from './md5';

/** 2^32 — the divisor shared by every SDK (NOT 2^32 - 1). */
const HASH_DIVISOR = 4294967296;

/** Lower-case hex MD5 digest of the UTF-8 encoding of `input`. */
export function md5Hex(input: string): string {
  return Array.from(md5Bytes(input))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Cross-SDK consistent hash in `[0, 1)`:
 * `MD5("{userId}:{flagKey}")` → first 4 bytes as little-endian uint32 → ÷ 2^32.
 *
 * Exported as a utility only. It is NOT the function the server buckets flag
 * rollouts with (that is `int(md5(...), 16) % 100`, "md5-mod100-v1", which
 * local evaluation reproduces in `evaluator.ts`), and nothing in this SDK uses
 * it to pick a variant or decide a flag.
 */
export function consistentHash(userId: string, flagKey: string): number {
  const digest = md5Bytes(`${userId}:${flagKey}`);
  const uint32 = new DataView(digest.buffer).getUint32(0, true);
  return uint32 / HASH_DIVISOR;
}

export { md5Bytes };
