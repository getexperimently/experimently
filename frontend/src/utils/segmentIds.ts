/**
 * Reading a file of user ids for an id-list segment, and cutting it into the
 * requests the member routes accept (#440).
 *
 * The routes take 1 to 10,000 ids per request, each 1 to 255 characters,
 * matched exactly. A chunk is also kept at or under 1,000,000 bytes of JSON
 * body, so 10,000 long ids never make a request a body-size limit in front
 * of the API would refuse.
 */

/** At most this many ids per request (the API's limit). */
export const MAX_IDS_PER_REQUEST = 10_000;

/** At most this many bytes of JSON body per request. */
export const MAX_REQUEST_BYTES = 1_000_000;

/** An id is 1 to this many characters, counted as the server counts them (code points). */
export const MAX_ID_LENGTH = 255;

/** A segment holds at most this many ids. */
export const MAX_SEGMENT_MEMBERS = 1_000_000;

export interface ParsedIds {
  /** Distinct ids, in file order. */
  ids: string[];
  /** Repeats removed (each counted once per extra copy). */
  duplicates: number;
  /** 1-based line numbers skipped because the id is longer than `MAX_ID_LENGTH`. */
  tooLong: number[];
}

/** Length in code points, as Python's `len` counts the id on the server. */
export function idLength(id: string): number {
  let n = 0;
  for (let i = 0; i < id.length; i += 1) {
    const unit = id.charCodeAt(i);
    // A high surrogate followed by a low one is one code point.
    if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < id.length) {
      const next = id.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) i += 1;
    }
    n += 1;
  }
  return n;
}

/** The first column of one CSV line: the text before the first comma, unquoted when quoted. */
function firstColumn(line: string): string {
  if (line.startsWith('"')) {
    let out = '';
    for (let i = 1; i < line.length; i += 1) {
      const ch = line[i];
      if (ch === '"') {
        if (line[i + 1] === '"') {
          out += '"';
          i += 1;
        } else {
          return out;
        }
      } else {
        out += ch;
      }
    }
    return out;
  }
  const comma = line.indexOf(',');
  return comma === -1 ? line : line.slice(0, comma);
}

/**
 * Read the ids in `text`: one per line, in the first column.
 *
 * - A byte-order mark is dropped, and both `\n` and `\r\n` end a line.
 * - A line that is empty or only spaces is skipped. Otherwise nothing is
 *   trimmed: ids are matched exactly, including case and spaces.
 * - A first id reading `user_id` is a header and skipped.
 * - An id longer than 255 characters is skipped and its line number kept.
 * - Repeats are removed and counted.
 */
export function parseIdFile(text: string): ParsedIds {
  const body = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  const lines = body.split('\n');
  const seen = new Set<string>();
  const ids: string[] = [];
  const tooLong: number[] = [];
  let duplicates = 0;
  let first = true;
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].endsWith('\r') ? lines[i].slice(0, -1) : lines[i];
    if (line.trim() === '') continue;
    const id = firstColumn(line);
    if (first) {
      first = false;
      if (id.trim().toLowerCase() === 'user_id') continue;
    }
    if (id.trim() === '') continue;
    if (idLength(id) > MAX_ID_LENGTH) {
      tooLong.push(i + 1);
      continue;
    }
    if (seen.has(id)) {
      duplicates += 1;
      continue;
    }
    seen.add(id);
    ids.push(id);
  }
  return { ids, duplicates, tooLong };
}

/** UTF-8 byte length of `text`. */
export function utf8Length(text: string): number {
  let bytes = 0;
  for (let i = 0; i < text.length; i += 1) {
    const unit = text.charCodeAt(i);
    if (unit < 0x80) bytes += 1;
    else if (unit < 0x800) bytes += 2;
    else if (unit >= 0xd800 && unit <= 0xdbff && i + 1 < text.length) {
      const next = text.charCodeAt(i + 1);
      if (next >= 0xdc00 && next <= 0xdfff) {
        // A surrogate pair: one code point above U+FFFF, four bytes.
        bytes += 4;
        i += 1;
      } else {
        bytes += 3;
      }
    } else bytes += 3;
  }
  return bytes;
}

/**
 * Cut `ids` into requests of at most `maxCount` ids whose JSON body
 * (`{"<field>": [...]}`) is at most `maxBytes` bytes. Order is kept.
 */
export function chunkIds(
  ids: string[],
  field: 'add' | 'remove',
  maxCount: number = MAX_IDS_PER_REQUEST,
  maxBytes: number = MAX_REQUEST_BYTES,
): string[][] {
  // `{"add":[]}`: the body around the ids.
  const frame = utf8Length(JSON.stringify({ [field]: [] }));
  const chunks: string[][] = [];
  let current: string[] = [];
  let bytes = frame;
  for (const id of ids) {
    const size = utf8Length(JSON.stringify(id)) + (current.length > 0 ? 1 : 0);
    if (current.length > 0 && (current.length >= maxCount || bytes + size > maxBytes)) {
      chunks.push(current);
      current = [];
      bytes = frame;
    }
    bytes += utf8Length(JSON.stringify(id)) + (current.length > 0 ? 1 : 0);
    current.push(id);
  }
  if (current.length > 0) chunks.push(current);
  return chunks;
}

/** `12480` → `12,480`. */
export function formatCount(n: number): string {
  return n.toLocaleString('en-US');
}
