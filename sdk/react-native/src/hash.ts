/**
 * Cross-SDK consistent hash (utility only).
 *
 * ## Hash Algorithm
 * Byte-for-byte compatible with the Java, Python, Go, iOS (Swift), Android (Kotlin),
 * and Flutter (Dart) SDK implementations:
 *
 * 1. Compute MD5 of `"{userId}:{flagKey}"` encoded as UTF-8.
 * 2. Read the first 4 bytes as a **little-endian unsigned 32-bit integer**.
 * 3. Divide by **4294967296** (2^32 = 0x100000000) to normalise to `[0.0, 1.0)`.
 *
 * The divisor is `2^32` **not** `MaxUInt32` (4294967295).
 *
 * The server decides every flag evaluation and experiment assignment; nothing
 * in this SDK calls `hashUser` to pick a variant. It is exported so that the
 * golden-vector contract tests and custom integrations can verify hash parity.
 */

import md5 from 'md5';

/**
 * Divisor used to normalise the 32-bit hash to [0.0, 1.0).
 * Equals 2^32 = 4294967296. MUST NOT be 4294967295 (MaxUInt32).
 */
const HASH_DIVISOR = 4294967296; // 2^32

/**
 * Computes a deterministic, normalised hash value in `[0.0, 1.0)` for the
 * given `userId` and `flagKey` combination.
 *
 * @example
 * ```typescript
 * hashUser('user-123', 'my-flag'); // ≈ 0.6927449859 (verified cross-SDK)
 * hashUser('alice', 'dark-mode');  // ≈ 0.0353864399
 * ```
 */
export function hashUser(userId: string, flagKey: string): number {
  const input = `${userId}:${flagKey}`;
  // md5() with { asBytes: true } returns a number[] of 16 bytes.
  const bytes = md5(input, { asBytes: true }) as number[];

  // Interpret the first 4 bytes as a little-endian unsigned 32-bit integer.
  const view = new DataView(new Uint8Array(bytes.slice(0, 4)).buffer);
  const uint32 = view.getUint32(0, true); // true = little-endian

  return uint32 / HASH_DIVISOR;
}
