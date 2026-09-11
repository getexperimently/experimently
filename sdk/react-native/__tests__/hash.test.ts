/**
 * Cross-SDK hash parity tests for the React Native SDK.
 *
 * `hashUser` is a compatibility utility only: the server decides every flag
 * evaluation and experiment assignment, and nothing in the SDK calls it to
 * pick a variant. It is still exported so the golden-vector contract tests
 * (`tests/sdk-contract/golden-vectors.json`) and custom integrations can
 * verify byte-for-byte parity with the Python, Java, Go, Swift, Kotlin and
 * Dart SDKs.
 */

import { hashUser } from '../src/hash';
import { hashUser as indexHashUser } from '../src';
import goldenVectors from '../../../tests/sdk-contract/golden-vectors.json';

describe('hashUser — cross-SDK parity', () => {
  /**
   * Known test vectors (Python reference):
   *   hashlib.md5(f'{userId}:{flagKey}'.encode()).digest()[:4]
   *   → struct.unpack('<I', ...)[0] / 4294967296.0
   */
  const VECTORS: Array<[string, string, number]> = [
    ['user-123', 'my-flag', 0.6927449859213],
    ['user-456', 'feature-x', 0.0776851554],
    ['alice', 'dark-mode', 0.0353864399],
    ['bob', 'new-checkout', 0.1463384565],
    ['user-789', 'beta-feature', 0.3134219283],
    ['test-user', 'flag-key', 0.992339374],
    ['', 'empty-user', 0.3582690393],
    ['a', 'b', 0.6056532171],
  ];

  test.each(VECTORS)('hashUser(%s, %s) ≈ %f', (userId, flagKey, expected) => {
    expect(hashUser(userId, flagKey)).toBeCloseTo(expected, 7);
  });

  test('matches every vector in tests/sdk-contract/golden-vectors.json', () => {
    const vectors = goldenVectors.hash_vectors as Array<{
      user_id: string;
      flag_key: string;
      expected_hash: number;
    }>;
    expect(vectors.length).toBeGreaterThan(0);
    for (const v of vectors) {
      expect(hashUser(v.user_id, v.flag_key)).toBeCloseTo(v.expected_hash, 12);
    }
  });

  test('is exported from the package index as the same function', () => {
    expect(indexHashUser).toBe(hashUser);
  });
});

describe('hashUser — divisor correctness', () => {
  test('divisor is 2^32 (4294967296) not MaxUInt32 (4294967295)', () => {
    // user-123:my-flag → MD5 first-4-bytes little-endian uint32 = 2975317059
    //   / 4294967296 = 0.692744985921308   ← correct
    //   / 4294967295 = 0.692744986082601   ← wrong (differs at 9th decimal)
    const result = hashUser('user-123', 'my-flag');

    // Correct value matches 2^32 divisor to 12 significant figures.
    expect(result).toBeCloseTo(0.692744985921308, 11);

    // If the wrong divisor were used, result would be ~1.61e-10 larger.
    expect(result).toBeLessThan(0.6927449861);
  });

  test('hash is always in [0.0, 1.0)', () => {
    const cases = [
      ['user-0', 'flag-0'],
      ['', ''],
      ['very-long-user-id-with-lots-of-chars', 'very-long-flag-key-name'],
      ['unicode-é', 'flag'],
    ];
    for (const [uid, fk] of cases) {
      const h = hashUser(uid, fk);
      expect(h).toBeGreaterThanOrEqual(0);
      expect(h).toBeLessThan(1);
    }
  });

  test('separator is colon between userId and flagKey', () => {
    // "{userId}:{flagKey}" — moving the boundary changes the input string.
    expect(hashUser('user-123', 'my-flag')).toBeCloseTo(0.6927449859, 7);
    expect(hashUser('user-123:my', '-flag')).not.toBeCloseTo(0.6927449859, 7);
  });

  test('different inputs produce different hashes', () => {
    const h1 = hashUser('user-A', 'flag-x');
    const h2 = hashUser('user-B', 'flag-x');
    const h3 = hashUser('user-A', 'flag-y');
    expect(h1).not.toBeCloseTo(h2, 10);
    expect(h1).not.toBeCloseTo(h3, 10);
  });

  test('hash is deterministic — same inputs always return same value', () => {
    for (let i = 0; i < 20; i++) {
      expect(hashUser('stable-user', 'stable-flag')).toBe(hashUser('stable-user', 'stable-flag'));
    }
  });

  test('little-endian byte order produces the correct known value', () => {
    // md5("user-123:my-flag") = 43bc57b1... → LE uint32 of [0x43,0xbc,0x57,0xb1] = 0xb157bc43
    const expectedLittleEndian = 0xb157bc43 / 4294967296;
    const wrongBigEndian = 0x43bc57b1 / 4294967296;
    expect(hashUser('user-123', 'my-flag')).toBeCloseTo(expectedLittleEndian, 12);
    expect(hashUser('user-123', 'my-flag')).not.toBeCloseTo(wrongBigEndian, 4);
  });
});
