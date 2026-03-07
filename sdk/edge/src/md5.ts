/**
 * Pure-JS MD5 implementation — no runtime dependencies, works in any JS environment
 * including Cloudflare Workers, Vercel Edge, Deno Deploy, and browsers.
 *
 * Algorithm: RFC 1321 compliant MD5.
 * Output: Uint8Array of 16 bytes, byte-for-byte identical to Node.js
 *         crypto.createHash('md5').update(input).digest().
 *
 * Reference: Paul Johnston's MD5 implementation (public domain),
 * adapted for TypeScript with typed arrays.
 *
 * Verification:
 *   md5("user-123:my-flag") hex = "43bc57b1e81dec71c5242122ac05170f"
 */

// MD5 round constants
const S11 = 7, S12 = 12, S13 = 17, S14 = 22;
const S21 = 5, S22 = 9, S23 = 14, S24 = 20;
const S31 = 4, S32 = 11, S33 = 16, S34 = 23;
const S41 = 6, S42 = 10, S43 = 15, S44 = 21;

function safeAdd(x: number, y: number): number {
  const lsw = (x & 0xffff) + (y & 0xffff);
  const msw = (x >> 16) + (y >> 16) + (lsw >> 16);
  return (msw << 16) | (lsw & 0xffff);
}

function bitRotateLeft(num: number, cnt: number): number {
  return (num << cnt) | (num >>> (32 - cnt));
}

function F(x: number, y: number, z: number): number {
  return (x & y) | (~x & z);
}

function G(x: number, y: number, z: number): number {
  return (x & z) | (y & ~z);
}

function H(x: number, y: number, z: number): number {
  return x ^ y ^ z;
}

function I(x: number, y: number, z: number): number {
  return y ^ (x | ~z);
}

function FF(a: number, b: number, c: number, d: number, x: number, s: number, t: number): number {
  return safeAdd(bitRotateLeft(safeAdd(safeAdd(a, F(b, c, d)), safeAdd(x, t)), s), b);
}

function GG(a: number, b: number, c: number, d: number, x: number, s: number, t: number): number {
  return safeAdd(bitRotateLeft(safeAdd(safeAdd(a, G(b, c, d)), safeAdd(x, t)), s), b);
}

function HH(a: number, b: number, c: number, d: number, x: number, s: number, t: number): number {
  return safeAdd(bitRotateLeft(safeAdd(safeAdd(a, H(b, c, d)), safeAdd(x, t)), s), b);
}

function II(a: number, b: number, c: number, d: number, x: number, s: number, t: number): number {
  return safeAdd(bitRotateLeft(safeAdd(safeAdd(a, I(b, c, d)), safeAdd(x, t)), s), b);
}

/**
 * Convert a string to a Uint8Array using UTF-8 encoding.
 * Uses TextEncoder when available (all modern runtimes), otherwise falls back
 * to a pure-JS implementation for maximum compatibility.
 */
function stringToUtf8Bytes(str: string): Uint8Array {
  if (typeof TextEncoder !== 'undefined') {
    return new TextEncoder().encode(str);
  }
  // Fallback: manual UTF-8 encoding
  const bytes: number[] = [];
  for (let i = 0; i < str.length; i++) {
    const code = str.charCodeAt(i);
    if (code < 0x80) {
      bytes.push(code);
    } else if (code < 0x800) {
      bytes.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code < 0xd800 || code >= 0xe000) {
      bytes.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    } else {
      // Surrogate pair
      i++;
      const high = code;
      const low = str.charCodeAt(i);
      const codePoint = 0x10000 + ((high & 0x3ff) << 10) + (low & 0x3ff);
      bytes.push(
        0xf0 | (codePoint >> 18),
        0x80 | ((codePoint >> 12) & 0x3f),
        0x80 | ((codePoint >> 6) & 0x3f),
        0x80 | (codePoint & 0x3f),
      );
    }
  }
  return new Uint8Array(bytes);
}

/**
 * Prepare the message for MD5 processing.
 * Pads the input to a multiple of 512 bits (64 bytes) per RFC 1321.
 */
function padMessage(data: Uint8Array): Uint8Array {
  const bitLen = data.length * 8;
  // Number of bytes needed after padding: length + 1 (0x80) + zero padding + 8-byte length
  const padLen = data.length % 64 < 56 ? 56 - (data.length % 64) : 120 - (data.length % 64);
  const padded = new Uint8Array(data.length + padLen + 8);
  padded.set(data);
  padded[data.length] = 0x80; // append 1 bit then zeros

  // Append bit length as 64-bit little-endian (low 32 bits then high 32 bits)
  const view = new DataView(padded.buffer);
  view.setUint32(padded.length - 8, bitLen >>> 0, true);      // low 32 bits
  view.setUint32(padded.length - 4, Math.floor(bitLen / 4294967296) >>> 0, true); // high 32 bits

  return padded;
}

/**
 * Compute MD5 digest of input string.
 *
 * @param input - UTF-8 string to hash
 * @returns Uint8Array of 16 bytes containing the MD5 digest
 */
export function md5(input: string): Uint8Array {
  const data = padMessage(stringToUtf8Bytes(input));

  // Initial hash values (RFC 1321 section 3.3)
  let a = 0x67452301;
  let b = 0xefcdab89;
  let c = 0x98badcfe;
  let d = 0x10325476;

  const view = new DataView(data.buffer);

  // Process each 512-bit (64-byte) block
  for (let offset = 0; offset < data.length; offset += 64) {
    const M: number[] = new Array(16);
    for (let i = 0; i < 16; i++) {
      M[i] = view.getUint32(offset + i * 4, true); // little-endian
    }

    const aa = a, bb = b, cc = c, dd = d;

    // Round 1
    a = FF(a, b, c, d, M[0],  S11, 0xd76aa478);
    d = FF(d, a, b, c, M[1],  S12, 0xe8c7b756);
    c = FF(c, d, a, b, M[2],  S13, 0x242070db);
    b = FF(b, c, d, a, M[3],  S14, 0xc1bdceee);
    a = FF(a, b, c, d, M[4],  S11, 0xf57c0faf);
    d = FF(d, a, b, c, M[5],  S12, 0x4787c62a);
    c = FF(c, d, a, b, M[6],  S13, 0xa8304613);
    b = FF(b, c, d, a, M[7],  S14, 0xfd469501);
    a = FF(a, b, c, d, M[8],  S11, 0x698098d8);
    d = FF(d, a, b, c, M[9],  S12, 0x8b44f7af);
    c = FF(c, d, a, b, M[10], S13, 0xffff5bb1);
    b = FF(b, c, d, a, M[11], S14, 0x895cd7be);
    a = FF(a, b, c, d, M[12], S11, 0x6b901122);
    d = FF(d, a, b, c, M[13], S12, 0xfd987193);
    c = FF(c, d, a, b, M[14], S13, 0xa679438e);
    b = FF(b, c, d, a, M[15], S14, 0x49b40821);

    // Round 2
    a = GG(a, b, c, d, M[1],  S21, 0xf61e2562);
    d = GG(d, a, b, c, M[6],  S22, 0xc040b340);
    c = GG(c, d, a, b, M[11], S23, 0x265e5a51);
    b = GG(b, c, d, a, M[0],  S24, 0xe9b6c7aa);
    a = GG(a, b, c, d, M[5],  S21, 0xd62f105d);
    d = GG(d, a, b, c, M[10], S22, 0x02441453);
    c = GG(c, d, a, b, M[15], S23, 0xd8a1e681);
    b = GG(b, c, d, a, M[4],  S24, 0xe7d3fbc8);
    a = GG(a, b, c, d, M[9],  S21, 0x21e1cde6);
    d = GG(d, a, b, c, M[14], S22, 0xc33707d6);
    c = GG(c, d, a, b, M[3],  S23, 0xf4d50d87);
    b = GG(b, c, d, a, M[8],  S24, 0x455a14ed);
    a = GG(a, b, c, d, M[13], S21, 0xa9e3e905);
    d = GG(d, a, b, c, M[2],  S22, 0xfcefa3f8);
    c = GG(c, d, a, b, M[7],  S23, 0x676f02d9);
    b = GG(b, c, d, a, M[12], S24, 0x8d2a4c8a);

    // Round 3
    a = HH(a, b, c, d, M[5],  S31, 0xfffa3942);
    d = HH(d, a, b, c, M[8],  S32, 0x8771f681);
    c = HH(c, d, a, b, M[11], S33, 0x6d9d6122);
    b = HH(b, c, d, a, M[14], S34, 0xfde5380c);
    a = HH(a, b, c, d, M[1],  S31, 0xa4beea44);
    d = HH(d, a, b, c, M[4],  S32, 0x4bdecfa9);
    c = HH(c, d, a, b, M[7],  S33, 0xf6bb4b60);
    b = HH(b, c, d, a, M[10], S34, 0xbebfbc70);
    a = HH(a, b, c, d, M[13], S31, 0x289b7ec6);
    d = HH(d, a, b, c, M[0],  S32, 0xeaa127fa);
    c = HH(c, d, a, b, M[3],  S33, 0xd4ef3085);
    b = HH(b, c, d, a, M[6],  S34, 0x04881d05);
    a = HH(a, b, c, d, M[9],  S31, 0xd9d4d039);
    d = HH(d, a, b, c, M[12], S32, 0xe6db99e5);
    c = HH(c, d, a, b, M[15], S33, 0x1fa27cf8);
    b = HH(b, c, d, a, M[2],  S34, 0xc4ac5665);

    // Round 4
    a = II(a, b, c, d, M[0],  S41, 0xf4292244);
    d = II(d, a, b, c, M[7],  S42, 0x432aff97);
    c = II(c, d, a, b, M[14], S43, 0xab9423a7);
    b = II(b, c, d, a, M[5],  S44, 0xfc93a039);
    a = II(a, b, c, d, M[12], S41, 0x655b59c3);
    d = II(d, a, b, c, M[3],  S42, 0x8f0ccc92);
    c = II(c, d, a, b, M[10], S43, 0xffeff47d);
    b = II(b, c, d, a, M[1],  S44, 0x85845dd1);
    a = II(a, b, c, d, M[8],  S41, 0x6fa87e4f);
    d = II(d, a, b, c, M[15], S42, 0xfe2ce6e0);
    c = II(c, d, a, b, M[6],  S43, 0xa3014314);
    b = II(b, c, d, a, M[13], S44, 0x4e0811a1);
    a = II(a, b, c, d, M[4],  S41, 0xf7537e82);
    d = II(d, a, b, c, M[11], S42, 0xbd3af235);
    c = II(c, d, a, b, M[2],  S43, 0x2ad7d2bb);
    b = II(b, c, d, a, M[9],  S44, 0xeb86d391);

    // Add block result back to running hash
    a = safeAdd(a, aa);
    b = safeAdd(b, bb);
    c = safeAdd(c, cc);
    d = safeAdd(d, dd);
  }

  // Output: 16 bytes, little-endian uint32 per word
  const result = new Uint8Array(16);
  const outView = new DataView(result.buffer);
  outView.setUint32(0,  a, true);
  outView.setUint32(4,  b, true);
  outView.setUint32(8,  c, true);
  outView.setUint32(12, d, true);

  return result;
}

/**
 * Convenience: return hex string representation of MD5 digest.
 * md5Hex("user-123:my-flag") === "43bc57b1e81dec71c5242122ac05170f"
 */
export function md5Hex(input: string): string {
  const bytes = md5(input);
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}
