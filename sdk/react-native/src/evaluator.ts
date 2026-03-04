/**
 * Local feature-flag evaluator using MD5-based consistent hashing.
 *
 * ## Hash Algorithm
 * Byte-for-byte compatible with the Java, Python, Go, iOS (Swift), Android (Kotlin),
 * and Flutter (Dart) SDK implementations:
 *
 * 1. Compute MD5 of `"{userId}:{flagKey}"` encoded as UTF-8.
 * 2. Read the first 4 bytes as a **little-endian unsigned 32-bit integer**.
 * 3. Divide by **4294967296** (2^32 = 0x100000000) to normalise to `[0.0, 1.0)`.
 *
 * The divisor is `2^32` **not** `MaxUInt32` (4294967295). This matches:
 *   - Java SDK:    `HASH_DIVISOR = 0x100000000L`
 *   - Python:      `MAX_HASH_VALUE + 1`
 *   - Go:          `float64(0x100000000)`
 *   - Swift/iOS:   `hashDivisor: Double = 0x100000000`
 *   - Kotlin/Android: `HASH_DIVISOR = 0x100000000L`
 *   - Dart/Flutter: `_hashDivisor = 4294967296.0`
 */

import md5 from 'md5';
import type { FeatureFlag } from './types';

/**
 * Divisor used to normalise the 32-bit hash to [0.0, 1.0).
 * Equals 2^32 = 4294967296.
 * MUST NOT be 4294967295 (MaxUInt32).
 */
const HASH_DIVISOR = 4294967296; // 2^32

/**
 * Computes a deterministic, normalised hash value in `[0.0, 1.0)` for the
 * given `userId` and `flagKey` combination.
 *
 * This is the canonical cross-SDK hash function:
 * ```
 * MD5("{userId}:{flagKey}") → first 4 bytes as little-endian uint32 → ÷ 2^32
 * ```
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
  //   bytes[0] = least-significant byte
  //   bytes[3] = most-significant byte
  // This matches Java:   (bytes[0] & 0xFFL) | ((bytes[1] & 0xFFL) << 8) | ...
  //            Python:   struct.unpack('<I', digest[:4])[0]
  //            Go:       binary.LittleEndian.Uint32(digest[:4])
  //            Dart:     ByteData.getUint32(0, Endian.little)
  const view = new DataView(new Uint8Array(bytes.slice(0, 4)).buffer);
  const uint32 = view.getUint32(0, true); // true = little-endian

  // Divide by 2^32, not (2^32 - 1), to normalise to [0.0, 1.0).
  return uint32 / HASH_DIVISOR;
}

/**
 * Evaluates a feature flag for a user locally using the consistent hash.
 *
 * @returns `true` if the user is in the rollout band; `false` otherwise.
 */
export function evaluateLocally(flag: FeatureFlag, userId: string): boolean {
  if (!flag.enabled) return false;

  const hash = hashUser(userId, flag.key);
  const rolloutFraction = flag.rolloutPercentage / 100;

  return hash < rolloutFraction;
}

/**
 * Returns the variant key for a user based on consistent hashing.
 *
 * @returns The variant key, or `null` if the user is outside the rollout band.
 */
export function assignVariant(flag: FeatureFlag, userId: string): string | null {
  if (!flag.enabled) return null;

  const hash = hashUser(userId, flag.key);
  const rolloutFraction = flag.rolloutPercentage / 100;

  if (hash >= rolloutFraction) return null;
  if (!flag.variants || flag.variants.length === 0) return 'on';

  // Re-scale hash from [0, rolloutFraction) → [0, 1) for variant selection.
  const variantHash = rolloutFraction > 0 ? hash / rolloutFraction : 0;
  const totalWeight = flag.variants.reduce((s, v) => s + v.weight, 0);
  let cumulative = 0;

  for (const variant of flag.variants) {
    cumulative += variant.weight / totalWeight;
    if (variantHash < cumulative) return variant.key;
  }

  // Fallback to last variant (floating-point rounding safety).
  return flag.variants[flag.variants.length - 1].key;
}
