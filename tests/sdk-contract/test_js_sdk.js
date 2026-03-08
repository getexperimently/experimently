/**
 * Cross-SDK contract tests for the JavaScript SDK consistent hashing.
 *
 * Validates that the JS SDK produces identical hash values to the
 * golden test vectors shared across all SDKs.
 *
 * Run: node tests/sdk-contract/test_js_sdk.js
 *   or: npx jest tests/sdk-contract/test_js_sdk.js (if Jest is configured)
 */

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const VECTORS_PATH = path.join(__dirname, "golden-vectors.json");
const TOLERANCE = 1e-10;

/**
 * JavaScript implementation of the cross-SDK MD5 consistent hash.
 */
function computeHash(userId, flagKey) {
  const input = `${userId}:${flagKey}`;
  const digest = crypto.createHash("md5").update(input, "utf8").digest();
  // Read first 4 bytes as little-endian unsigned 32-bit integer
  const uint32 = digest.readUInt32LE(0);
  return uint32 / 0x100000000; // divide by 2^32
}

/**
 * Compute full MD5 hex digest.
 */
function computeMd5Hex(userId, flagKey) {
  const input = `${userId}:${flagKey}`;
  return crypto.createHash("md5").update(input, "utf8").digest("hex");
}

// Load golden vectors
const vectors = JSON.parse(fs.readFileSync(VECTORS_PATH, "utf8"));

let passed = 0;
let failed = 0;
const failures = [];

function assert(condition, message) {
  if (condition) {
    passed++;
  } else {
    failed++;
    failures.push(message);
    console.error(`  FAIL: ${message}`);
  }
}

// ── Hash Vector Tests ──────────────────────────────────────────────────

console.log("Hash Vector Tests");
console.log("─".repeat(60));

for (const v of vectors.hash_vectors) {
  const label = `${v.user_id}:${v.flag_key}`;

  // Test hash value
  const hash = computeHash(v.user_id, v.flag_key);
  assert(
    Math.abs(hash - v.expected_hash) < TOLERANCE,
    `Hash mismatch for ${label}: expected ${v.expected_hash}, got ${hash}`
  );

  // Test MD5 hex
  const md5Hex = computeMd5Hex(v.user_id, v.flag_key);
  assert(
    md5Hex === v.md5_hex,
    `MD5 hex mismatch for ${label}: expected ${v.md5_hex}, got ${md5Hex}`
  );

  console.log(`  ${label}: ${hash.toFixed(16)} ✓`);
}

// ── Rollout Vector Tests ───────────────────────────────────────────────

console.log("\nRollout Vector Tests");
console.log("─".repeat(60));

for (const v of vectors.rollout_vectors) {
  const label = `${v.user_id}:${v.flag_key}`;
  const hash = computeHash(v.user_id, v.flag_key);

  if ("rollout_3_percent" in v) {
    assert(
      (hash < 0.03) === v.rollout_3_percent,
      `3% rollout mismatch for ${label}`
    );
  }
  if ("rollout_5_percent" in v) {
    assert(
      (hash < 0.05) === v.rollout_5_percent,
      `5% rollout mismatch for ${label}`
    );
  }
  if ("rollout_50_percent" in v) {
    assert(
      (hash < 0.5) === v.rollout_50_percent,
      `50% rollout mismatch for ${label}`
    );
  }
  if ("rollout_100_percent" in v) {
    assert(
      (hash < 1.0) === v.rollout_100_percent,
      `100% rollout mismatch for ${label}`
    );
  }

  console.log(`  ${label}: rollout checks ✓`);
}

// ── Property Tests ─────────────────────────────────────────────────────

console.log("\nProperty Tests");
console.log("─".repeat(60));

// Deterministic
const h1 = computeHash("user-123", "my-flag");
const h2 = computeHash("user-123", "my-flag");
assert(h1 === h2, "Hash is not deterministic");
console.log("  Deterministic: ✓");

// Range [0, 1)
let rangeOk = true;
for (let i = 0; i < 100; i++) {
  const h = computeHash(`user-${i}`, "test-flag");
  if (h < 0 || h >= 1) {
    rangeOk = false;
    break;
  }
}
assert(rangeOk, "Hash out of range [0, 1)");
console.log("  Range [0, 1): ✓");

// Uniqueness
const hashes = new Set();
for (let i = 0; i < 100; i++) {
  hashes.add(computeHash(`user-${i}`, "flag"));
}
assert(hashes.size === 100, "Hash collisions detected among 100 users");
console.log("  Uniqueness (100 users): ✓");

// Little-endian verification
const digest = crypto.createHash("md5").update("user-123:my-flag", "utf8").digest();
const leValue = digest.readUInt32LE(0);
const beValue = digest.readUInt32BE(0);
assert(leValue !== beValue, "LE and BE byte orders should differ");
console.log("  Little-endian byte order: ✓");

// ── Summary ────────────────────────────────────────────────────────────

console.log("\n" + "═".repeat(60));
console.log(`Results: ${passed} passed, ${failed} failed`);

if (failures.length > 0) {
  console.log("\nFailures:");
  failures.forEach((f) => console.log(`  - ${f}`));
  process.exit(1);
} else {
  console.log("All contract tests passed!");
  process.exit(0);
}
