/**
 * Reading an id file and cutting it into member requests (#440 PR D;
 * gates-D D1-D3).
 */
import {
  MAX_IDS_PER_REQUEST,
  MAX_REQUEST_BYTES,
  chunkIds,
  idLength,
  parseIdFile,
  utf8Length,
} from '@/utils/segmentIds';

const bodyBytes = (field: 'add' | 'remove', chunk: string[]) => Buffer.byteLength(JSON.stringify({ [field]: chunk }), 'utf8');

describe('parseIdFile (D1)', () => {
  it('skips a BOM, a user_id header, CRLF line ends and blank lines', () => {
    const parsed = parseIdFile('﻿user_id\r\ncust-1\r\n\r\n   \r\ncust-2\r\n');
    expect(parsed).toEqual({ ids: ['cust-1', 'cust-2'], duplicates: 0, tooLong: [] });
  });

  it('removes repeats and counts each extra copy', () => {
    const parsed = parseIdFile('a\nb\na\na\nc\n');
    expect(parsed.ids).toEqual(['a', 'b', 'c']);
    expect(parsed.duplicates).toBe(2);
  });

  it('reads the first column only, unquoting a quoted field', () => {
    const parsed = parseIdFile('user_id,email\ncust-1,a@example.com\n"cust,2",b@example.com\n"say ""hi""",c\n');
    expect(parsed.ids).toEqual(['cust-1', 'cust,2', 'say "hi"']);
  });

  it('matches exactly: case and inner or trailing spaces are kept', () => {
    const parsed = parseIdFile('Cust-1\ncust-1\ncust-1 \n');
    expect(parsed.ids).toEqual(['Cust-1', 'cust-1', 'cust-1 ']);
    expect(parsed.duplicates).toBe(0);
  });

  it('skips an id over 255 characters by line number and keeps one of exactly 255', () => {
    const ok = 'a'.repeat(255);
    const long = 'b'.repeat(256);
    const parsed = parseIdFile(['user_id', ok, long, 'c', long + 'x'].join('\n'));
    expect(parsed.ids).toEqual([ok, 'c']);
    expect(parsed.tooLong).toEqual([3, 5]);
  });

  it('counts length in code points, as the server does', () => {
    // 255 emoji are 510 UTF-16 units but 255 characters on the server.
    const emoji = '\u{1F600}'.repeat(255);
    expect(idLength(emoji)).toBe(255);
    const parsed = parseIdFile(`${emoji}\n${emoji}\u{1F600}\n`);
    expect(parsed.ids).toEqual([emoji]);
    expect(parsed.tooLong).toEqual([2]);
  });

  it('reports no ids for an empty file, a header-only file and blank lines', () => {
    for (const text of ['', 'user_id\n', '\n\n  \r\n']) {
      expect(parseIdFile(text).ids).toEqual([]);
    }
  });
});

describe('chunkIds by count (D2)', () => {
  it('cuts 25,001 ids into exactly 10,000 / 10,000 / 5,001, in order', () => {
    const ids = Array.from({ length: 25_001 }, (_, i) => `u${i}`);
    const chunks = chunkIds(ids, 'add');
    expect(chunks.map((c) => c.length)).toEqual([10_000, 10_000, 5_001]);
    expect(chunks.flat()).toEqual(ids);
    expect(MAX_IDS_PER_REQUEST).toBe(10_000);
  });

  it('sends a single small file as one request', () => {
    expect(chunkIds(['a', 'b'], 'remove')).toEqual([['a', 'b']]);
  });
});

describe('chunkIds by bytes (D3)', () => {
  it.each([
    ['255 ASCII characters', 'x'],
    ['255 two-byte characters', 'é'],
    ['255 four-byte characters', '\u{1F600}'],
  ])('keeps every body of 10,000 ids of %s at or under 1,000,000 bytes', (_label, unit) => {
    const ids = Array.from({ length: 10_000 }, (_, i) => `${i}`.padEnd(6, '-') + unit.repeat(249));
    for (const field of ['add', 'remove'] as const) {
      const chunks = chunkIds(ids, field);
      expect(chunks.length).toBeGreaterThan(1);
      for (const chunk of chunks) {
        expect(bodyBytes(field, chunk)).toBeLessThanOrEqual(MAX_REQUEST_BYTES);
        expect(chunk.length).toBeLessThanOrEqual(MAX_IDS_PER_REQUEST);
      }
      expect(chunks.flat()).toEqual(ids);
    }
  });

  it('fills a chunk up to the byte limit, not short of it', () => {
    const ids = Array.from({ length: 10_000 }, (_, i) => `${i}`.padEnd(255, 'x'));
    const chunks = chunkIds(ids, 'add');
    // Each id costs 257 or 258 bytes; the first chunk ends within one id of the limit.
    expect(bodyBytes('add', chunks[0])).toBeGreaterThan(MAX_REQUEST_BYTES - 260);
  });

  it('measures UTF-8 the way Buffer does', () => {
    for (const text of ['abc', 'é', '€', '\u{1F600}', JSON.stringify('\ud800')]) {
      expect(utf8Length(text)).toBe(Buffer.byteLength(text, 'utf8'));
    }
  });
});
