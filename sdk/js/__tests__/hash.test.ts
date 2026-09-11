import { createHash } from 'crypto';
import { readFileSync } from 'fs';
import { join } from 'path';
import { consistentHash, md5Hex, md5Bytes } from '../src/hash';

interface HashVector {
  user_id: string;
  flag_key: string;
  md5_hex: string;
  expected_hash: number;
}

interface RolloutVector {
  user_id: string;
  flag_key: string;
  rollout_3_percent?: boolean;
  rollout_5_percent?: boolean;
  rollout_50_percent?: boolean;
  rollout_100_percent?: boolean;
}

const vectors = JSON.parse(
  readFileSync(join(__dirname, '..', '..', '..', 'tests', 'sdk-contract', 'golden-vectors.json'), 'utf8')
) as { hash_vectors: HashVector[]; rollout_vectors: RolloutVector[] };

const nodeMd5Hex = (input: string) => createHash('md5').update(input, 'utf8').digest('hex');

describe('md5 (pure TypeScript)', () => {
  test.each([
    ['', 'd41d8cd98f00b204e9800998ecf8427e'],
    ['abc', '900150983cd24fb0d6963f7d28e17f72'],
    ['The quick brown fox jumps over the lazy dog', '9e107d9d372bb6826bd81d3542a419d6'],
    ['user-123:my-flag', '43bc57b1e81dec71c5242122ac05170f'],
  ])('md5Hex(%j) matches the known digest', (input, expected) => {
    expect(md5Hex(input)).toBe(expected);
  });

  test('md5Bytes returns 16 bytes', () => {
    expect(md5Bytes('hello')).toBeInstanceOf(Uint8Array);
    expect(md5Bytes('hello')).toHaveLength(16);
  });

  test.each([
    'héllo',
    'ünïcödé:flag',
    '日本語:フラグ',
    'emoji 😀:flag',
    'a'.repeat(55),
    'a'.repeat(56),
    'a'.repeat(63),
    'a'.repeat(64),
    'a'.repeat(65),
    'a'.repeat(1000),
  ])('matches Node crypto for %j', input => {
    expect(md5Hex(input)).toBe(nodeMd5Hex(input));
  });

  test('matches Node crypto for 200 generated inputs of varying length', () => {
    for (let i = 0; i < 200; i++) {
      const input = `user-${i}:${'x'.repeat(i % 97)}:${String.fromCharCode(0x100 + i)}`;
      expect(md5Hex(input)).toBe(nodeMd5Hex(input));
    }
  });
});

describe('consistentHash — golden vectors (tests/sdk-contract/golden-vectors.json)', () => {
  test.each(vectors.hash_vectors.map(v => [v.user_id, v.flag_key, v] as const))(
    'consistentHash(%j, %j)',
    (userId, flagKey, v) => {
      expect(Math.abs(consistentHash(userId, flagKey) - v.expected_hash)).toBeLessThan(1e-10);
      expect(md5Hex(`${userId}:${flagKey}`)).toBe(v.md5_hex);
    }
  );

  test.each(vectors.rollout_vectors.map(v => [v.user_id, v.flag_key, v] as const))(
    'rollout thresholds for %j / %j',
    (userId, flagKey, v) => {
      const hash = consistentHash(userId, flagKey);
      if (v.rollout_3_percent !== undefined) expect(hash < 0.03).toBe(v.rollout_3_percent);
      if (v.rollout_5_percent !== undefined) expect(hash < 0.05).toBe(v.rollout_5_percent);
      if (v.rollout_50_percent !== undefined) expect(hash < 0.5).toBe(v.rollout_50_percent);
      if (v.rollout_100_percent !== undefined) expect(hash < 1.0).toBe(v.rollout_100_percent);
    }
  );

  test('is deterministic and in [0, 1)', () => {
    for (let i = 0; i < 100; i++) {
      const h = consistentHash(`user-${i}`, 'test-flag');
      expect(h).toBeGreaterThanOrEqual(0);
      expect(h).toBeLessThan(1);
      expect(consistentHash(`user-${i}`, 'test-flag')).toBe(h);
    }
  });

  test('uses little-endian byte order (matches Node readUInt32LE)', () => {
    const digest = createHash('md5').update('user-123:my-flag', 'utf8').digest();
    expect(consistentHash('user-123', 'my-flag')).toBe(digest.readUInt32LE(0) / 0x100000000);
    expect(consistentHash('user-123', 'my-flag')).not.toBe(digest.readUInt32BE(0) / 0x100000000);
  });
});
