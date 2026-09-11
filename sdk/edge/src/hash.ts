/**
 * Cross-SDK consistent hash (utility only).
 *
 * Byte-for-byte compatible with the Go, Java, Python, iOS and Android SDKs:
 *   1. UTF-8 encode `${userId}:${flagKey}`
 *   2. MD5 digest (16 bytes)
 *   3. First 4 bytes as a little-endian uint32
 *   4. Divide by 2^32 (4294967296) → float in [0, 1)
 *
 * The server decides every flag evaluation and experiment assignment; nothing
 * in this SDK calls `hashUser` to pick a variant. It is exported so that the
 * golden-vector contract tests (tests/sdk-contract/) and custom integrations
 * can verify hash parity.
 */

import { md5 } from './md5.js';

/** 2^32 — the divisor shared by every SDK (NOT 2^32 - 1). */
const HASH_DIVISOR = 4294967296;

/**
 * Compute a stable bucket value in `[0, 1)` for a user/flag pair.
 */
export function hashUser(userId: string, flagKey: string): number {
  const bytes = md5(`${userId}:${flagKey}`);
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return view.getUint32(0, true) / HASH_DIVISOR;
}
